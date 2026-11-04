# Value Book, Part 6: Telegram, the Web, and the Book's Surfaces — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan **section by section** (one subagent per section, never per task — see "Execution model"). Every section opens with **entry checks** the orchestrator runs itself before it spawns the section's subagent. Each section carries a **model** and an **effort** label; the orchestrator passes both when it spawns. Sections F–I touch `web/`: their subagents invoke the `da-vinci` skill first (the operator's rule for any UI work), and nobody runs `npm run build`, `next build` or `next dev` inside `web/` (the operator's `next dev` shares `web/.next`). Steps use checkbox (`- [ ]`) syntax for tracking.

> **Written against `main` at `971c825` (2026-11-04)**, with Parts 1–5 merged, pushed and post-merge fixed
> (Part 5's Progress log, row "Post-merge fixes"). Every line number quoted below was read from that tree
> on 2026-11-04. **This plan was not prototyped in a scratch copy** (unlike Parts 1–5): the
> safety-critical code (the command kinds, the value process's drain, the trim, the trading drain's skip,
> the Telegram forwarder, the severity fix) is given whole; the read-side modules, the API and the cards
> are given as exact interfaces, behaviour and named tests, and the web sections as the surface, the data
> contract and the acceptance tests, because da-vinci designs the markup at build time (ruling 30). Every
> section's entry checks re-grep what it edits; a false fact stops the section (Execution model, step 6).

**Goal:** Close the value book's loop with the operator. Approve and reject value proposals from Telegram
and the web (intents drained by the value process, which re-gates and sends on clientId 31); the drawdown's
"trim to half" card with its one button; the full §7.1 trigger set for a held name with no shadow entry;
re-evaluation cards and a nightly digest; `/value`, `/value NAME`, `/value NAME analyse`; a watchdog check
on the nightly run; the follow window's `last_viewed_at` and an `is_fresh` that can match; Claude's `VALUE
NOTE` in the wheel's trade review, roll review and `/scan NAME`; card labels for the Part 5 reason codes;
value fills split out of the whole-account ledger; the read API (`src/api/value_db.py`); and, last and
each cuttable, the web surfaces of spec §10 (Home's Value card and `value` kind, the stock page's value
block, the Research strip).

**Architecture:** A neutral, stdlib-only `src/common/value_commands.py` names the value command kinds, the
proposal fingerprint and the Telegram callback format, so the API, `approval_service` and the value process
agree without importing each other. The API validates and enqueues `value_*` intents in `app_commands` like
every other web write; `approval_service` turns a `vbook:` button tap into the same intent and leaves every
`value_*` row alone in its own drain. The value process (`scripts/run_value.py`) claims those rows every
`value.telegram.commands_poll_seconds`, applies them through `src/value/commands.py` (one transaction in
`value.db`, `book.decide` for a tap, `book.trim_to_half` for the trim) and marks the command applied or
failed through `src.storage.app_commands`, imported lazily. Nothing on the trading path imports
`src.value`; the wheel reads value.db only through `src/common/value_view.py` (new read functions for the
`/value` commands, the watchdog and the `VALUE NOTE`). Cards with buttons are rendered by pure
`src/value/cards.py` and sent by `src/value/notify.py`. The API reads value.db through `src/api/value_db.py`
(`mode=ro`, plain SQL) and, for a stale ticker file, computes one on the spot with the pure
`src.value.scorecard` over `src/common/value_inputs.py` and records a `value_snapshot` intent carrying its
fingerprint (spec §6.9). The reporting tier gains plain `ValuePayInput` / `ValueDayInput` values the API
reads from value.db; `src/reporting/` never imports `src.value`.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2 (SQLite, WAL; `mode=ro`), `sqlite3`, python-telegram-bot
(`InlineKeyboardMarkup`), FastAPI, pytest, ruff, mypy; Next.js (App Router) + TypeScript + Tailwind v4,
`@tanstack/react-query`, vitest, for Sections F–I.

**Spec:** `docs/superpowers/specs/2026-10-28-value-swing-book-design.md` — §6.9 (fresh on search, the
follow window, the `value_snapshot` intent), §7 (review cards), §7.1 (triggers, cards, digest; ruling 22 of
Part 5), §8.5 (requests outrank everything in the read queue), §9.6 (the 25% trim), §9.7 (value approvals
drained by the value service), §10 (what it looks like), §11 (`ValuePayInput`, the ledger tag), §16 (fences),
§18 (docs), §21 (revision 4). Task 18 adds **§22 Revision 5** recording the operator's 2026-11-04 answers.
Part 5's plan and its Progress log are the ground truth for the code this part builds on.

## Execution model

| Section | Tasks | Model | Effort | Why this model | Why this effort |
|---|---|---|---|---|---|
| **Orchestrator** (the main session) | — | **sonnet** | **high** | Runs entry checks, spawns, verifies, asks the operator; writes no product code. | It is the one reader of every subagent's report and the protected-file diff; a missed red gate ships. |
| **A — The value command kinds and the value process's drain** | 1–3 | **opus** | **high** | An approved value buy can cause capital-release closes of wheel CSPs without another tap (Part 5 ruling 7), so a tap is an order-reaching intent: idempotency, stale cards, live refusal and the trading drain's skip must be exact. Edits `src/notify/command_drain.py` and `src/storage/app_commands.py`. | The section that changes what reaches an order. |
| **B — Telegram: cards, buttons, `/value`, the digest** | 4–6 | **sonnet** | **high** | Pure renderers, one forwarder in `approval_service`, three commands that read through `value_view`; patterns given. | `approval_service` is a live daemon's process; its imports are fenced. |
| **C — The value process's own surfaces** | 7–9 | **sonnet** | **high** | Held-name triggers (Part 5 ruling 22), the snapshot/analyse/refresh intents, `is_fresh` (Part 1 M1), the watchdog. | Trigger code changes when adds pause; the snapshot path must persist exactly the input set it was handed. |
| **D — The wheel side: VALUE NOTE, reason labels, the ledger split** | 10–12 | **sonnet** | **high** | Prompt text through `runner.py` (reduce-only reach, ruling 9), two label maps, the reporting tier's book names. | The VALUE NOTE reaches the prompt that sets Claude's reduce-only cut; the ledger split changes the wheel's cost-basis walk on a shared name. |
| **E — The read API and the docs** | 13–15 | **sonnet** | **high** | `src/api/value_db.py`, routes, the reporting inputs, the on-open recompute, the backend doc sweep. | Web fences (`mode=ro`, one written table, two allowed `src.value` imports). |
| **Whole-branch review (backend)** | after E | **opus** | **high** | One review of A–E before any web section; no per-task reviews. | Reads the command path end to end against the core invariant, the value fence and spec §9.7. |
| **Review fix pass** | after the review | **sonnet** | **high** | Critical/Important findings fixed in one commit. | Fixes land in the acceptance path with the full gate as the only check. |
| **F — Web: Home's Value card and the value decide flow** *(web-overhaul-sensitive)* | 16 | **sonnet** | **high** | da-vinci; one card and one decide flow over Section E's contract. | Home is the overhaul's most-designed surface. |
| **G — Web: the stock page's value block** *(web-overhaul-sensitive)* | 17 | **sonnet** | **high** | da-vinci; one block on `/stock/[symbol]`. | Research and the stock page are web overhaul Part 4's, not yet planned. |
| **H — Web: the Research "Top opportunities" strip** *(web-overhaul-sensitive)* | 18 | **sonnet** | **high** | da-vinci; one strip above the watchlist. | As G. |
| **I — Web: the `value` kind across Home's pay stub, positions, Done today and calendar** *(web-overhaul-sensitive)* | 19 | **sonnet** | **high** | da-vinci; edits Parts 1–3 surfaces in place under their tests. | The strategy switcher and every Home card are touched. |
| **J — Spec revision 5, STATUS, the finish** | 20 | **sonnet** | **medium** | Text given; the final gate. | Docs only. |
| **A section's rerun** (only when its subagent stopped because a plan fact was false) | that section | as the section | **xhigh** | The same section prompt plus the orchestrator's corrected fact. | The plan was wrong once there; the rerun has to reason past it. |

**Sections F–I may be cut or moved.** After Part 6 is built, a Sonnet agent re-plans the remaining web overhaul
(HANDOFF "Flow after Part 5") and may drop or rebuild any of F–I. Each is self-contained: it reads only
Section E's routes and the existing web primitives, adds its own tests, and leaves every other section green
without it. **If the operator cuts a web section before it runs**, mark its row "cut (operator, <date>)"
in the Progress log, skip its entry checks, and go straight to J; nothing in A–E or J depends on F–I.

**How the orchestrator runs a section** (the main session: the operator starts it on Sonnet at
effort high, since a session cannot set its own effort):

1. Run the section's **entry checks** itself, in order, from the worktree root. Any check fails →
   stop, report the failing command and its output, and do not spawn. A failure that belongs to the
   previous section is fixed there first (reopen its last task, record the ruling).
2. All pass → add a "Section X entry" row to the Progress log (gate result, date, and the
   recomputed commit count and test target — see "Counts" below).
3. Spawn **one subagent for the whole section** with the Agent tool, `model` set to the section's
   **Model** and `effort` set to the section's **Effort** from the table above, with this prompt (fill
   the brackets):

   > You are executing Section [X] of `docs/superpowers/plans/2026-10-29-value-book-6-web-telegram.md`
   > in the git worktree `.claude/worktrees/value-book-6` (branch `feat/value-book-6`). Read, in this
   > order: the plan's "Rulings made up front", "Global Constraints" and Section [X] in full; the spec
   > sections Section [X] cites; and only the files its tasks list. Do the tasks in order, TDD as
   > written: each failing test first, then the code, then the gates the task names. Where the plan
   > gives code, apply it byte for byte (the Edit tool, or Write a file in your scratchpad and
   > `git apply` it from the worktree root); where it gives an interface and named tests, write the
   > tests first exactly as named and asserting what they say, then the code. Run pytest from the
   > worktree root. One commit per task, message ending `Co-Authored-By: <your model name>
   > <noreply@anthropic.com>`. After each task tick its checkboxes and fill its Progress-log row
   > (status, commit, gate counts, date, every ruling with its cost-if-wrong) and commit that with the
   > next task (the last task's row goes in a final `docs(plan)` commit). Never import a
   > `scripts.run_*` module; never connect to IBKR or Telegram (every test fakes both); never touch
   > `data/*.db` of the main checkout; never edit a private `config/*.yaml`; never copy `research.db`.
   > [Sections F–I only: invoke the `da-vinci` skill before any UI code and use it for the critique and
   > audit finish the task names; never run `npm run build`, `next build` or `next dev` inside `web/` —
   > build in a scratch copy as the task says.] If an entry-check fact turns out false mid-task, stop
   > and report instead of improvising. Report: commits, gate counts, rulings, anything left undone.

4. When the subagent reports, **verify it yourself** before anything else: `git log --oneline
   main..HEAD`, `git status --short` (clean), the section exit's gate command and its counts, and the
   protected-file diff (Global Constraints).
5. **Stop and ask the operator** whether to continue to the next section or stop here. Never start
   the next section without that answer.
6. If a subagent stopped because a plan fact was false: record the false fact and the corrected one
   in the Progress log as a ruling, then rerun that section once with `effort: "xhigh"` and the
   corrected fact prepended to the prompt. A second stop goes to the operator.

After Section E: spawn **one opus subagent** (`effort: "high"`) for the backend whole-branch review
(superpowers:requesting-code-review; the prompt is under "Whole-branch review"), then **one sonnet
subagent** (`effort: "high"`) that fixes every Critical and Important finding in one commit, then verify
it and **ask the operator** whether to run the web sections F–I, cut some, or go to J. After J, ask
before merging or pushing.

**Counts go stale, so recompute them.** Each section adds one final `docs(plan)` commit and a
Progress-log row beyond its task commits, and the review fix pass adds its own. Never trust a fixed
total in this plan: at every entry check and exit, take the commit count from
`git log --oneline main..HEAD | wc -l` and record it, and state pytest targets as **baseline + N**
(baseline recorded at A2; N the sum of the tasks' "new tests", File structure). Vitest targets in F–I are
**vitest baseline (recorded at F1) + N** likewise.

**Commits.** Each task is one commit; Task 1's commit also adds this plan file. Every commit
message ends with the trailer `Co-Authored-By: <model> <noreply@anthropic.com>`, where `<model>`
is the executing agent's own model name.

## Progress log

| Section / task | Status | Commits | Gate | Date | Rulings |
|---|---|---|---|---|---|
| **Plan written** | done | (plan file only, uncommitted) | n/a | 2026-11-04 | Written by an Opus subagent after Parts 1–5 merged. Three operator questions were asked and answered the same day (rulings 1, 9 and 18); the plan writer's defaults on the digest, the watchdog, `/value NAME` and the web set were accepted by the operator (rulings 13, 15, 12, 30). |
| **Section A entry** | done | 0 commits on `main..HEAD` | A1-A4 pass; worktree `.claude/worktrees/value-book-6`; baseline `python -m pytest -q` = **5506 passed, 1 skipped**; ruff clean; mypy 348 files clean | 2026-11-04 | Operator (2026-11-04) authorised running A through the Review Fix Pass without asking between sections; stops before the web (F-I). Section A exit target: 5506 + 28 = 5534. |
| **Task 1** — value kinds, fingerprint, trading drain's skip | done | `11a490f` | targeted (`test_value_commands`, `test_value_fence`, `test_command_schemas`, `test_write_path_invariants`, `test_value_config`, `test_drain_promote`) 112 passed; `-k "command_drain or drain"` 137 passed; `test_openapi_current` 1 passed; ruff clean; mypy 349 files clean. **12 new** (11 in `test_value_commands.py`, the parametrised case counting five, + 1 fence) | 2026-11-04 | (a) `web/lib/api-types.ts` **not** regenerated: the orchestrator ruled api-types regeneration out of Section A, so only `docs/web/openapi.json` was regenerated (the pytest contract check); the Section A exit's web check is therefore "`web/` diff empty". Cost if wrong: one `npx openapi-typescript` run in a later section (E regenerates after its routes). (b) `docs/web/commands.md` documents kinds as sections, not table rows: added one section "The value book's kinds" holding a table with one row per kind, plus `value_put` on `promote`, the no-dedupe-key list in the routes table and the drain loop's step 2. Cost: wording. (c) Step 8's "(10 new)" disagrees with its own tests (11 + 1 fence = 12, as the File structure says); 12 is what landed. Cost: none. (d) `_LIVE_CONFIRM_KINDS` is the five-member set, written multi-line by `ruff format`. (e) `dedupe_key_for`'s docstring keeps its "twelve repeatable kinds" list and gains the plan's one sentence for the three value read-side kinds. Cost: wording. |
| **Task 2** — the value process drains its kinds | done | `4c9b1ac` | `test_value_commands` + `test_value_fence` + `test_value_live` 71 passed; `py_compile scripts/run_value.py` silent; ruff clean; mypy 350 files clean. **11 new** (10 in `test_value_commands.py` + `test_the_value_entrypoint_drains_lazily`; `test_live_allows_read_kinds` is Task 8's, as the plan says) | 2026-11-04 | (a) `scripts/run_value.py` imports `import src.value.commands as vcmd`, not the plan's `from src.value import commands`: the fence's `ast` parser records the latter as `src.value`, outside the entrypoint allowlist. Cost: none. (b) `last_slow = time.monotonic() - poll`, not `0.0`: the monotonic clock's zero is undefined (boot time on macOS and Linux), so `0.0` could hold the first night/Claude/book tick back up to `poll_seconds` after a reboot. Cost: none. (c) `drain(rows, apply_fn, mark_fn)` takes 5-tuples `(id, kind, payload, requested_by, confirm_token)`, skips a row with a token (the filter moved in, as Step 1 asks), catches `ValueCommandFailed` and any exception (`handler_error`) itself, calls `mark_fn(id, result, reason, detail)` after `apply_fn` returns (value.db committed), and returns `DrainOutcome`s; `_drain_commands` builds the Telegram replies from them for `VALUE_ORDER_KINDS` requested by `telegram`. Cost: none. (d) `_trim` raised `not_built` until Task 3, as the plan says; `outcome_line` is the one-line Task 2 body. |
| **Task 3** — the 25% drawdown's trim to half | done | `a3d1a9a` | `test_value_commands` + `test_value_live` + `test_value_stage3` 60 passed; `py_compile scripts/value_book.py` silent; ruff clean; mypy 350 files clean. **5 new** | 2026-11-04 | (a) `TRIM_TTL_HOURS = 30.0` (`src/value/book.py`), the funding request's horizon, as the plan proposes: a trim sell not sent within 30 h expires like any approved proposal. Cost if wrong: one constant. (b) The reset is `book.reset_drawdown(state)` (drops `trim_offered_at`, `episode`, `trimmed`, `trimmed_at`; high = value, stop off), called by `scripts/value_book.py --reset-drawdown`, so the test checks the reset's state write without importing a script. Cost: none. (c) `_high_water` returns the episode id only when it first offers it (`None` on every later cycle until a reset); the cycle then appends the plain line "The value book is down N% from its high: trim to half?" (Task 4 renders the card). (d) `BookRefused(reason)` lives in `book.py`; `commands._trim` maps it to `ValueCommandFailed`. `totals()` is read once, outside the loop. (e) Step 2's red was `not_built` / a `KeyError`, not the plan's `ImportError`, because Task 2 already registered a `_trim` stub and did not import `trim_to_half`. Cost: none. (f) `trimmed: True` is written even when no position had a share to sell (a second tap is still `already_trimmed`). Cost: one condition. |
| **Section A exit** | done | 4 commits on `main..HEAD` (3 task + this `docs(plan)`) | `python -m pytest -q` = **5534 passed, 1 skipped** (baseline 5506 + 28: T1 12, T2 11, T3 5); `ruff check .` clean; `ruff format --check` on the 13 touched `.py` files clean; `mypy src` 350 files clean; `py_compile` of `scripts/run_value.py` and `scripts/value_book.py` silent; protected-file diff empty; `git diff --stat main...HEAD -- web` **empty** (`web/lib/api-types.ts` not regenerated, Task 1 ruling a); the `src.value` grep over `src/notify` and `src/api` prints nothing | 2026-11-05 | The ARCHITECTURE / SETUP / CLAUDE.md doc sweep for the new modules (`src/common/value_commands.py`, `src/value/commands.py`, the new config keys, the drain exception) is Task 15's, as the File structure says; only `docs/web/commands.md` changed here. Operator to-do unchanged: re-copy `config/examples/value.yaml`'s `telegram:` and `prompt_note:` blocks (defaults load without them). |
| **Section B entry** | done | 4 commits on `main..HEAD` | B1-B3 pass (the `pathlib` allowlist line in `tests/test_value_fence.py` is now at 459, not ~418, because Section A added fence tests; every other grep matches); Section A orchestrator re-verified: 5534 passed, 1 skipped, ruff and mypy (350 files) clean, protected diff empty | 2026-11-05 | Operator pre-authorised continuing without asking. Section B exit target: 5534 + 30 = 5564. |
| **Task 4** — cards with buttons, the outbox | done | `4e65d5b` | `test_value_cards` + `test_value_commands` + `test_value_stage3` + `test_value_store` + `test_value_fence` + `test_value_live` 101 passed; `py_compile scripts/run_value.py` silent; ruff clean; mypy 352 files clean. **11 new** (`tests/test_value_cards.py`) | 2026-11-05 | (a) `proposal_card` takes one extra keyword, `tranches: int | None = None`, so the title reads "tranche 1 of 3" (the outbox passes `book.tranches`); without it the text reads "tranche 1". Cost: none. (b) The outbox posts a re-evaluation card only for a **held** Major row (`position_id IS NOT NULL`): a shadow entry's Major row is hypothetical and a night scores hundreds, so ruling 14's "one card per Major row" means the held rows the mirror and the held-name triggers write. Cost if wrong: one `WHERE` clause. (c) `outbox.MAX_AGE = 48 h`: a proposal must also be unexpired, a re-evaluation younger than 48 h, so a database that predates the `posted_at` columns does not replay its history. Cost: one constant. (d) `trim_posted` joins `book.TRIM_STATE_KEYS` so a `--reset-drawdown` ends the episode's "posted" mark with the rest, and `live._high_water` keeps it; `live.cycle` drops its plain "trim to half?" line (the card replaces it) and `stage3.run_cycle` its plain "re-evaluation opened" lines (logged instead), as the task says. Cost: none. (e) `book.clear_attribution` also resets `posted_at`, so a later freeze of the same name posts its own card. Cost: none. (f) `tests/test_value_fence.py`'s `run_value.py` allowlist gains `src.value.outbox` (the task text names `_post_outbox()` in the script but not the allowlist). Cost: one line. (g) `outcome_line` (`src/value/commands.py`) delegates to `cards.outcome_line`; the module imports `src.value.cards`, which imports only `src.common.value_commands` and the store. |

*(Rows are added as each section and task lands; a ruling is any deviation from the task text, and why.)*

## Roadmap (this plan is Part 6 of 6)

- **Parts 1–5.** Merged and pushed; `value_rules` v1–v4 frozen (v4 `be30d1eaa915`). Part 5's book is off
  until `value.book.enabled` (the fault drills and the ledger history import come first; Part 5 operator
  to-dos).
- **Part 6 — Telegram, the web, the book's surfaces.** This plan. **Moved in from Part 5:** the
  `value_approve` / `value_reject` kinds and their buttons (Part 5 ruling 14), the 25% trim (ruling 15),
  held-name triggers for names with no shadow entry (ruling 22), `value_put` in `PromotePayload` (ruling 25),
  the reason-code labels and the ledger split (Part 5 Progress log, Tasks 10 and 15). **From Part 4:**
  `src/common/value_text.py` (the `VALUE NOTE`), `/value NAME analyse` and the "Run Claude's analysis"
  button, the display of Claude's prose, drivers, clamps, kill triggers and grounded facts. **From Parts 2
  and 3:** `last_viewed_at`, the digest and review cards, the watchdog check, Major/Minor re-evaluation
  cards, Part 1 M1's `is_fresh`. **Moved out:** none of the backend. The web sections F–I are explicitly
  re-plannable by the web overhaul (above). **Not built:** live trading for the value book (a separate live
  plan after spec §12's review); a web "trim" button (the trim card is Telegram and the Home card only,
  ruling 10); editing a proposal's size from a tap (a tap approves or rejects exactly what Python sized).
- **After Part 6.** The HANDOFF's "Flow after Part 5": a Sonnet agent ledgers the web overhaul and decides
  what of F–I to keep; then the next web overhaul part is planned.

## Rulings made up front (the operator may overturn any of them)

Every ruling was checked against `main` at `971c825`. "Cost if wrong" is what reversing it would take.

### Operator decisions (2026-11-04, binding)

1. **The value process drains the value kinds (spec §9.7).** `value_approve`, `value_reject`, `value_trim`,
   `value_snapshot`, `value_analyse` and `value_refresh` are `app_commands` intents; the API enqueues them
   (web) and `approval_service` enqueues them (Telegram taps and commands), and **neither drains them**:
   `command_drain.drain_once` reads pending commands excluding `VALUE_KINDS`, so they are never failed as
   `unknown_kind`, while its TTL sweep (`expire_stale_commands`, `approval.ttl_minutes`) still expires one
   the value process never picked up. `scripts/run_value.py` claims them with a lazy import of
   `src.storage.app_commands` and `src.storage.db.session_scope`, applies each through
   `src/value/commands.py`, and marks it applied or failed. Root `CLAUDE.md`'s "every web action is an
   intent drained by `approval_service`" gains a named exception (Task 15). *Cost if wrong: one set
   constant and one drain function.*
2. **A tap is order-reaching, so it is guarded like the wheel's approve.** Each `value_approve` /
   `value_reject` payload carries `proposal_id` and `fingerprint` (ruling 5). The handler refuses: an
   unknown proposal (`no_such_proposal`), a fingerprint that does not match (`stale_proposal`), a proposal
   not `pending` (`already_<status>`, idempotent: a second tap on the same card is a no-op answer, never a
   second decision), an expired one (`expired`), and anything under `LIVE_TRADING=true` (`not_paper`). It
   records `decided_by` from the command's `requested_by` (`web` | `telegram`). Approval only changes the
   row: the value process's next RTH cycle re-gates the buy or sale on a fresh quote at send time
   (`src/value/risk.py::validate`, Part 5) and only clientId 31 sends. *Cost if wrong: one reason.*
3. **"Trim to half" = one button that creates half-size sell proposals, already approved (operator,
   question 2, option b).** When the book's drawdown from its high reaches `book.drawdown_trim_pct` (25),
   the value process sends one trim card (once per drawdown episode, ruling 11). Its button enqueues
   `value_trim` carrying the episode id; the handler creates, for every open position with filled shares,
   a sell proposal for `book.sell_shares(filled, 0.5)` shares, `reason="drawdown_trim"`, `cause="python"`,
   `status="approved"`, `decided_by` the tapper; a name that already has an open sell is skipped (`propose`
   already refuses a second). Each sale is still re-gated at send time and capped by the sell cap (Part 5
   ruling 19) in `live._sell`. A second tap, or a tap after the episode reset, is `already_trimmed` /
   `stale_proposal`. *Cost if wrong: one function; option (c) is `auto=False`.*

### The command path

4. **The kinds and payloads** (`src/api/models/commands.py`, pydantic, `extra="forbid"`):
   `value_approve` / `value_reject` {`proposal_id: int`, `fingerprint: str` (10 hex)};
   `value_trim` {`episode: str` (10 hex)}; `value_snapshot` {`symbol`, `fingerprint: dict`} (spec §6.9);
   `value_analyse` {`symbol`}; `value_refresh` {`symbol`}. Dedupe keys: `value_approve:<id>` /
   `value_reject:<id>` (two clicks are one row), `value_trim:<episode>`; the other three are repeatable
   (the value process dedupes the read queue itself). **`value_approve` and `value_trim` join
   `_LIVE_CONFIRM_KINDS`** so a live-mode web click needs the second confirmation, though the handler
   refuses live anyway (belt and braces; the book idles in live). *Cost if wrong: a set member.*
5. **The proposal fingerprint** is `sha256(f"{id}|{kind}|{symbol}|{shares:g}|{created_at:%Y-%m-%dT%H:%M:%S}")`
   truncated to 10 hex characters (`src/common/value_commands.proposal_fingerprint`). It changes if the
   row is ever re-sized or replaced, and the card carries it, so a button on an old card cannot approve a
   different trade. The trim episode id is the same hash over `f"trim|{high:.2f}|{offered_at:%Y-%m-%dT%H:%M:%S}"`.
   *Cost if wrong: none (a tap refused as stale is re-tapped from the current card).*
6. **Telegram callback data** is `vbook:<a|r|t>:<id-or-0>:<fp>` (≤ 64 bytes, Telegram's limit). `approval_service`
   registers `CallbackQueryHandler(handle_value_button, pattern="^vbook:")`, parses it with
   `value_commands.parse_callback`, enqueues the intent through `src.storage.app_commands.enqueue_command`
   (`requested_by="telegram"`) and answers "Queued: the value process acts on it within a minute". It
   imports nothing from `src.value` (fence) and never edits value.db. The value process replies with the
   outcome in `TELEGRAM_THREAD_VALUE` (approved, rejected, refused with the reason). *Cost if wrong: none.*
7. **The value process's loop** gains a short tick: `stop.wait(value.telegram.commands_poll_seconds)` (15),
   draining commands every tick, and the existing night / Claude / book ticks only when
   `value.service.poll_seconds` has passed since the last one. A tap is acted on within ~15 s; a buy still
   sends only at the next RTH cycle (`book.cycle_minutes`). *Cost if wrong: one number.*
8. **`value_put` in `PromotePayload`** becomes a declared field `value_put: bool = False` (Part 5 ruling 25);
   the drain already reads it from the raw payload, so behaviour is unchanged and the OpenAPI document gains
   the field. *Cost if wrong: none.*

### The book's surfaces

9. **The VALUE NOTE (operator, question 3).** `src/common/value_text.py` renders, for each reviewed name the
   value book knows, one compact block: the effective verdict per list and who decided it, Python's and the
   effective fair value, the margin of safety, the value put ceiling, the value book's holding and its next
   exit level, and an open re-evaluation, then one rule line ("Context only. It never moves the Rules
   Engine; the value put ceiling is enforced by the system."). It is read through new plain-SQL functions in
   `src/common/value_view.py` and wired once in `src/claude/runner.py` (`review_candidates` and `review_roll`)
   into both backends' prompts, which covers the scan's trade review, the roll review and `/scan NAME`.
   Behind `value.prompt_note.enabled` (default true). It reaches the prompt that sets Claude's reduce-only
   `max_contracts` cut, so it can only ever lower a CSP's size, record-only in live; nothing else reads it.
   *Cost if wrong: one config key.*
10. **Trim on the web** is a Home Value-card line with no button (Section F): the button lives on the Telegram
    card only, so one human decision has one place to happen. *Cost if wrong: a web button on the same
    intent.*
11. **The trim card fires once per episode.** `live._high_water` stores `trim_offered_at` and the episode id
    when the drawdown first reaches `drawdown_trim_pct`; it is offered again only after
    `python -m scripts.value_book --reset-drawdown` (which already resets the high). *Cost if wrong: one
    state key.*
12. **`/value`** (no argument): the top five READY or WATCH names per list from `value_ticker_files`
    (effective verdict, margin of safety, fair value, age), then the book's open proposals with buttons.
    **`/value NAME`**: the stored ticker file through `value_view.read_ticker_file` with its age in words and,
    for a held name, its plan and open re-evaluation; if the file is stale (older than the last settled
    session or its fingerprint no longer current, ruling 16) the reply says so and a `value_refresh` intent is
    queued, after which the value process scores the name and posts the fresh card to the value thread.
    **`/value NAME analyse`** queues `value_analyse` (Claude's read at the "request" priority, spec §8.5).
    Unknown names say "Not scored yet" and queue the refresh. *Cost if wrong: wording.*
13. **The digest** is one message a night, after the night's run and the book's night step, to
    `TELEGRAM_THREAD_VALUE`: Minor re-evaluations since the last digest (what fired, plan before → now),
    review cards (a kill trigger fired; nine months held with no progress — a close never above entry + 10%
    of the distance to fair value; fair value down 10% or more since entry while the price is not), the
    book's line (positions, cost, value, drawdown from the high, breaker states), and the proposals waiting
    for a tap. Nothing is sent when every part is empty. Behind `value.telegram.digest_enabled` (default
    true). *Cost if wrong: config numbers (`no_progress_months: 9`, `fv_drop_pct: 10`).*
14. **Major re-evaluations post the same day** (spec §7.1 step 4): the nightly mirror and the held-name
    triggers (ruling 17) post one card per Major row; the hourly check's Major rows post at once from the
    cycle. A row is posted once (`value_reevaluations.posted_at`, a migration-safe added column). *Cost if
    wrong: one column.*
15. **The watchdog** (`src/ops/watchdog.py`, out of process) gains `value_check`: while `value.service` is
    expected to run (the private `value.yaml` exists), it reads the newest finished `nightly` row of
    `value_runs` through `value_view.last_nightly_run()` and alerts when it is older than the last weekday
    session's close + `watchdog.value_grace_hours` (default 26). A missing value.db is "never ran". *Cost if
    wrong: one number.*
16. **`is_fresh` (Part 1 M1).** The two "latest accession" readings disagree by design (the scorecard's is
    the newest *concept-map* fact; `current_fingerprint_parts` is the newest `financials` row of any
    concept). Ruling: freshness never compares the scorecard's fingerprint with the cheap parts. The value
    process stores the cheap parts it read beside each file (`value_ticker_files.freshness_json`, migration-safe)
    and `ticker_file.freshness_key(parts, regime, version, digest)` hashes them; a file is fresh when the
    stored freshness key equals the key of the current cheap parts. `Fingerprint.key()` and history rows are
    untouched. A file written before this column reads as stale once, and is recomputed. *Cost if wrong: one
    function and one column.*
17. **Held names with no shadow entry get the full §7.1 trigger set (Part 5 ruling 22).** Each night, for
    every open value position with no open READY shadow entry on its name and list, `service._book_night`
    runs `reevaluate.session_triggers` on the position itself (entry date as the first "after", the last
    held re-evaluation's session as `last_reevaluation`, the same residual, filing, earnings, news, regime and
    kill inputs the shadow path gets) and opens or joins its held re-evaluation through the same debounce
    (`reevaluate.joins`). Levels and stops are untouched (the live policy is `value`; shock stops are
    `full` only). Claude's review is queued for a held name as the mirror does. **Folded-in defect:**
    `live.mirror_reevaluations` takes `max(r.severity for r in shadow_rows)` on the strings `"major"` /
    `"minor"`, which picks `"minor"` (line 902); it now ranks them. *Cost if wrong: none for the fix; the
    trigger set is one function.*
18. **Where the VALUE NOTE does not go.** Only the three wheel prompts of ruling 9 carry it: never the spreads picker, the
    EOD narrative, the news process or the value book's own Claude reads (which read value.db through `src/value/`).
    *Cost if wrong: one call site.*
19. **`value_snapshot` (spec §6.9).** The API sends it whenever it shows a ticker file (stored or computed)
    for a name; the value process sets `last_viewed_at = now` (the follow window's input, Part 2) and, when
    the payload carries a fingerprint that differs from the stored one, persists a scorecard recomputed from
    exactly that input set (the accession, the price bar's date and close, the regime, the ruleset) through
    `ticker_file.persist`; when its own recomputation's fingerprint does not equal the payload's (the
    research worker moved since), it persists its own and records `detail="moved"` on the result. Names
    under `universe` stay tagged as they are; a name outside every universe is tagged `lookup`. *Cost if
    wrong: one handler.*
20. **`value_analyse`** queues a Claude read with `claude_reads.queue_read(vs, symbol, kind="verdict",
    reason="request", now=now)` (priority "your requests", spec §8.5); with `value.claude.enabled` false the
    result is `claude_off` and the card/web says so. Part 4's per-day caps still apply. *Cost if wrong: none.*
21. **The reason-code labels.** `formatters._REJECT_REASON_LABELS` (`src/notify/formatters.py:669`) and
    `routers/options._REASON_LABELS` (`src/api/routers/options.py:74`) gain plain words for every Part 5 code
    that can reach a wheel card: `book_attribution_mismatch`, `value_book_unreadable`, `gross_notional_cap`,
    `combined_name_cap`, `above_value_ceiling`, `reserved_for_spreads_book`, `release_not_paper`,
    `release_not_csp`, `release_at_loss` and the other `release_*` codes `risk_engine.validate_release`
    returns. The value book's own reasons get one map in `src/value/cards.py` (`VALUE_REASON_LABELS`). *Cost
    if wrong: wording.*
22. **The ledger split.** `LedgerBookName` (`src/common/schemas.py:1615`) gains `"value"`; `trade_ledger._merge_book`
    and `_book_name` (`src/reporting/trade_ledger.py:134-145`) keep `value` (after `spreads`, before `system`);
    the ticker roll-up's wheel-adjusted cost basis and stock lots skip `book == "value"` trades, so a shared
    name's wheel basis is the wheel's (matching `wheel_shares`); the whole-account totals still count value
    trades (account truth). The Sheets mirror writes the book word. *Cost if wrong: a Literal member.*
23. **The read API** (`src/api/value_db.py`, `src/api/routers/value.py`, `src/api/models/value.py`):
    `GET /value/top?list=deep_value|quality_growth` (up to ten, READY first), `GET /value/book` (positions
    with next exit level, open proposals with fingerprints, funding requests, breaker and trim state, the
    ceiling used), `GET /value/positions?status=open|closed`, `GET /value/{symbol}` (the ticker file: verdict,
    fair values and methods, the effective verdict and who decided, Claude's drivers/clamps/notes/kill
    triggers/facts labelled `source: claude`, re-evaluations, the plan for a held name, age, and
    `computed: "stored" | "now" | "pending"`). An absent value.db is `available: false`, never an error and
    never "none". Every response carries `as_of` (the Envelope convention). *Cost if wrong: routes.*
24. **The on-open recompute** lives in `src/api/value_lookup.py`: when `GET /value/{symbol}` finds no file or a
    stale one (ruling 16), it builds the inputs through `src/common/value_inputs.py` (research.db `mode=ro`),
    the market facts through `value_inputs.fetch_market_facts` and the earnings dates through
    `src/api/news_db.py`'s read-only session, calls `src.value.scorecard.build_scorecard`, returns it with
    `computed: "now"`, and enqueues `value_snapshot` with its fingerprint; it never writes value.db. Filings
    missing from research.db → `computed: "pending"` and the existing research ingest path (the research
    router's `IngestJobRow` enqueue) is reused. It runs inside `research.tiers.materialization_budget_seconds`;
    past the budget it answers the stored file (or `pending`). *Cost if wrong: one module.*
25. **Home's `value` kind** (Section E backend, Section I web): `src/reporting/pay.py` and `day.py` gain plain
    `ValuePayInput` (realised P&L per closed lot, by close date) and `ValueDayInput` (each value fill: buy or
    sell, shares, price, the proposal's reason and cause), and `PayStrategy` gains `"value"`. `GET /pnl/month`,
    `GET /pnl/day` and `GET /pnl/calendar` read them through `value_db.py` and accept `strategy=value`; with
    `strategy=all` value lines join the stub as their own labelled lines ("Value book, realised"), never
    mixed into premium. The income target is unchanged (the operator's options-income wage; value realised
    P&L is shown beside it, ruling 26). *Cost if wrong: one Literal member and two inputs.*
26. **The pay meter counts options income only.** Value realised P&L is a separate stub line and is not
    counted toward the monthly income target, because the target is the wheel's wage (DESIGN.md "The
    payslip") and a share sale is a capital gain. *Cost if wrong: one sum.*
27. **Positions:** `GET /portfolio/positions` is unchanged (the wheel's view since Part 5, `wheel_view`);
    value shares reach Home through `GET /value/positions`, as the spreads book's do through
    `GET /spreads/positions`. *Cost if wrong: none.*
28. **No new written table in the API.** Every web write in this part is a `POST /commands` of a value kind;
    `tests/test_web_fence.py::test_the_api_still_writes_exactly_one_table` stays green. *Cost if wrong: none.*
29. **Review minors folded in.** Fixed here: the severity `max` (ruling 17); Part 1 M1 (ruling 16); Part 5's
    raw reason codes (ruling 21); Part 5 Task 10's ledger note (ruling 22). Still deferred with their earlier
    reasons (no code here touches them): Part 5's "still open" list in `STATUS.md` (a CC roll on a frozen name,
    the release runner's quote load, the sector tally, the `select_releases` pool, `ingest` re-tagging on a
    non-value orderRef, an unexplained stock dropping out until the freeze, the 20-character quote minimum
    in the prompt), Part 1 M2–M8, Part 2 M8–M12/M15, Part 3's trigger-4 full fix.

### The web (Sections F–I)

30. **The web set is spec §10's, each section cuttable** (operator, 2026-11-04): F the Home Value card with the
    value decide flow; G the stock page's value block with "Run Claude's analysis"; H the Research strip; I the
    `value` kind on Home's existing cards. Each conforms to `web/DESIGN.md` (ratified 2026-10-28): the payslip
    world, one idea per card, lime only on the primary act, unknown as hatched `n/a`, Claude's text labelled
    as Claude's and never on a button, words for states, no em dashes. Each new component reuses the
    primitives (`components/ui/*`: Card, Stub, StatusWord, Disclosure, Sheet, Button, SegmentedControl) and
    the decide flow's safety pieces (`ConfirmAction`, `CommandReceipt`, `lib/commands.ts`'s
    `submitCommand` / `useCommandStatus` / persistence). DESIGN.md gains a "Value" surface paragraph only
    through da-vinci, and no new token, colour, font, radius or elevation without the operator.
31. **The value decide flow is a new component, not a change to `DecideControls`.** `components/value/ValueDecide.tsx`
    mirrors `DecideControls`' shape (ConfirmAction first, one `POST /commands`, a `CommandReceipt`, in-flight
    disabled, `localStorage` persistence keyed `value:<proposal_id>`) and sends `value_approve` /
    `value_reject` with the fingerprint from `GET /value/book`. The protected `DecideControls`,
    `ConfirmAction`, `CommandReceipt`, `HaltControl`, `AutonomyControl`, `RollModeControl`, `lib/commands.ts`
    and `lib/receipt.ts` do not change (their diff stays empty). The confirm dialog's sentence for a buy says
    what the approval may cause: "Approving lets the system buy N shares of SYMBOL at up to $X at its next
    check. If cash is short it may close up to K of your wheel's cash-secured puts at breakeven or better to
    fund it." (K is `release.max_closes_per_request`, read from `GET /value/book`). *Cost if wrong: copy.*

## Global Constraints

- **The core invariant holds.** No LLM output reaches an order except through Part 4's validated effective
  verdict and clamped fair value, and in live not at all. A tap approves exactly what Python proposed; the value
  gate re-runs at send time on a fresh quote; only clientId 31 sends a value order; the Rules Engine gates every
  capital-release close twice. The VALUE NOTE is prompt text that can at most lower a CSP's contract count
  through the existing clamped `claude_cut`.
- **Fences stay green, unweakened:** `tests/test_value_fence.py`, `tests/test_web_fence.py`,
  `tests/test_eval_skills.py`, `tests/test_regime_fence.py`, `tests/test_news_fence.py`,
  `tests/test_spreads_fence.py`, `tests/test_wheel_spreads_isolation.py`. New assertions (Tasks 1, 2, 5, 10, 13):
  the API imports from `src.value` only `scorecard` and `schemas`; only `src/api/value_db.py` opens value.db in
  the API; `src/common/value_commands.py` imports only the standard library; `approval_service` and
  `command_drain` import nothing from `src.value`; `src/claude/` reaches value.db only through
  `src.common.value_view` / `src.common.value_text`; `scripts/run_value.py`'s allowlist gains exactly
  `src.common.value_commands`, `src.value.commands` and (lazily) `src.storage.app_commands`, `src.storage.db`.
- **The value process still loads no wheel layer and no `ib_async` at import** (Part 2's `sys.modules` probe).
  `src.storage.app_commands` and `src.storage.db` are imported inside `_drain_commands()` only.
- **`approval_service` imports nothing from `src.value`;** it imports `src.common.value_commands` and
  `src.common.value_view`.
- **The API writes exactly one table** (`app_commands`). value.db is read `mode=ro` with plain SQL.
- **Paper only.** Every value command handler refuses under `LIVE_TRADING=true` except `value_snapshot`,
  `value_refresh` and `value_analyse` (read-side; they change no order state).
- **Protected files** (diff must be empty at every section exit): `src/engine/`, `src/execution/`,
  `src/strategies/`, `src/orchestrator/`, `src/monitor/`, `src/spreads/`, `src/spreads_ai/`, `src/news/`,
  `src/value_ai/`, `src/ledger/` except `sheets_mirror.py` (Task 12), `src/research/`; and in `web/`:
  `components/options/{DecideControls,ConfirmAction,CommandReceipt,HaltControl,AutonomyControl,RollModeControl}.tsx`,
  `lib/commands.ts`, `lib/receipt.ts`.
- **No `value_rules` bump.** Nothing here is under `rules:`; `FROZEN["v4"]` stays `be30d1eaa915`. New keys go
  in `config/examples/value.yaml` and `config/examples/settings.yaml` with defaults, so a stale private copy
  still loads (operator to-do: re-copy).
- **Gotchas (HANDOFF §4):** run pytest from the worktree root; no compound Bash naming git paths in the
  worktree; never import `scripts.run_*` (`python -m py_compile` instead); never copy `research.db`; worktree
  sessions cannot edit private `config/*.yaml`; daemons do not hot-reload (`./ibkr restart` after the merge).
  **Test clocks:** pin `now` in every test that compares a fixture time with an expiry (Part 5 Section B note).
- **Web (F–I):** every colour a semantic token; Hanken Grotesk and Red Hat Mono; `.tabular` on numbers; lime only
  on the act; `n/a` hatched; no state by colour alone; no shadow except the sheet and the confirm dialog; zero em
  dashes and none of the banned words in UI copy; charts never animate in; `grep -rn
  "submitCommand\|confirmCommand" web/features` prints only `features/more/TargetCard.tsx` and its test (the value
  flow lives in `components/value/`); gate `cd web && npx vitest run && npx tsc --noEmit && npm run lint`, plus
  the full Python gate when a task touched Python; build only in a scratch copy (Task 16 Step 1 gives the
  command); `npx openapi-typescript ../docs/web/openapi.json -o lib/api-types.ts` after any API contract change.
- **Quality gate after every task:** the task's targeted tests; at every section exit `python -m pytest -q`,
  `ruff check .`, `ruff format --check` on touched files, `mypy src`.

## Review Focus

For the backend whole-branch review (after E) and the final one (after J):

- A `value_*` row can never be applied by `approval_service`, failed as `unknown_kind`, or applied twice by the
  value process (claim, apply, mark in one guarded step; a crash between apply and mark re-runs an idempotent
  handler: `decide` and `trim_to_half` refuse a second application).
- A stale card cannot approve a different trade (fingerprint); a live-mode tap does nothing (`not_paper`).
- The trim creates approved sells only for filled shares, at half, never past the sell cap at send time.
- Nothing on the trading path or in `approval_service` imports `src.value`; the API imports only `scorecard` and
  `schemas` from it and never writes value.db; `value_snapshot` persists exactly the input set it carries.
- The VALUE NOTE cannot reach anything but prompt text; the ledger split leaves the account totals unchanged.
- Held-name triggers change no level or stop; adds pause; Claude's review is queued.

## File structure

| File | Task | New / edit | New tests |
|---|---|---|---|
| `src/common/value_commands.py` | 1 | new (stdlib only) | — |
| `src/api/models/commands.py`, `src/api/routers/commands.py` | 1 | edit | — |
| `src/storage/app_commands.py`, `src/notify/command_drain.py` | 1 | edit | — |
| `config/examples/value.yaml`, `src/common/config.py` | 1 | edit (`telegram`, `prompt_note`) | — |
| `docs/web/commands.md` | 1 | edit | — |
| `tests/test_value_commands.py` | 1–3 | new | 11 (T1) + 10 (T2) + 5 (T3) |
| `src/value/commands.py` | 2 | new | — |
| `scripts/run_value.py` | 2 | edit (loop, `_drain_commands`) | — |
| `tests/test_value_fence.py` | 1, 2, 5, 10, 13 | edit | 1 + 1 + 1 + 1 + 2 |
| `src/value/book.py` (`trim_to_half`), `src/value/live.py` (`_high_water` trim state) | 3 | edit | — |
| `src/value/cards.py` | 4 | new (pure) | 8 |
| `src/value/notify.py` (buttons), `src/value/stage3.py`, `src/value/service.py` (posting) | 4 | edit | 3 |
| `src/value/store.py` (`posted_at`, `freshness_json`, `trim` state) | 4, 8 | edit | — |
| `src/notify/approval_service.py` (`handle_value_button`, `/value`) | 5 | edit | 7 |
| `src/common/value_view.py` (new read functions) | 5, 9, 10 | edit | 3 + 1 + 1 |
| `src/value/digest.py`, `src/value/service.py` hook | 6 | new / edit | 7 |
| `src/value/live.py`, `src/value/service.py` (held triggers, severity) | 7 | edit | 6 |
| `src/value/commands.py` (snapshot, analyse, refresh), `src/value/ticker_file.py` (`freshness_key`) | 8 | edit | 7 |
| `src/ops/watchdog.py`, `src/common/config.py` (`WatchdogCfg.value_grace_hours`), `config/examples/settings.yaml` | 9 | edit | 4 |
| `src/common/value_text.py`, `src/claude/value_context.py` | 10 | new | 6 |
| `src/claude/runner.py`, `src/claude/ollama_runner.py`, `src/claude/prompts/strategist.py`, `src/claude/prompts/roll.py` | 10 | edit | 3 |
| `src/notify/formatters.py`, `src/api/routers/options.py` | 11 | edit | 2 |
| `src/common/schemas.py`, `src/reporting/trade_ledger.py`, `src/ledger/sheets_mirror.py` | 12 | edit | 5 |
| `src/api/value_db.py`, `src/api/models/value.py`, `src/api/routers/value.py`, `src/api/main.py` | 13 | new / edit | 12 |
| `src/reporting/pay.py`, `src/reporting/day.py`, `src/api/routers/pnl.py` | 14 | edit | 8 |
| `src/api/value_lookup.py` | 14 | new | 5 |
| `docs/web/openapi.json`, `web/lib/api-types.ts` | 13, 14 | regenerate | — |
| `ARCHITECTURE.md`, `SETUP.md`, `README.md`, `CLAUDE.md`, `docs/web/api.md`, `docs/web/commands.md` | 15 | edit | — |
| `web/components/value/*`, `web/features/home/*` | 16 | new / edit | vitest ≈ 14 |
| `web/features/stock-value/*`, `web/app/stock/[symbol]/page.tsx` | 17 | new / edit | vitest ≈ 12 |
| `web/features/research/TopOpportunities*`, `web/app/research/page.tsx` | 18 | new / edit | vitest ≈ 8 |
| `web/features/home/*`, `web/lib/strategy.ts`, `web/features/activity/*` | 19 | edit | vitest ≈ 12 |
| `docs/superpowers/specs/2026-10-28-value-swing-book-design.md` (§22), `STATUS.md`, `web/CLAUDE.md`, `web/DESIGN.md` | 15–20 | edit | — |

Python new tests (collected items), A–E: **122** (T1 12, T2 11, T3 5, T4 11, T5 12, T6 7, T7 6, T8 7, T9 5, T10 12,
T11 2, T12 5, T13 14, T14 13). The orchestrator recomputes from the tasks' own counts.

## Section A — The value command kinds and the value process's drain (Tasks 1–3) · model: opus · effort: high

**Reads:** this plan's rulings 1–8, 11 and Global Constraints; spec §9.6, §9.7; `src/api/models/commands.py`,
`src/api/routers/commands.py` (lines 36–48 and 120–150), `src/storage/app_commands.py`,
`src/notify/command_drain.py` (lines 1–140), `src/value/book.py` (lines 160–260, 318–375), `src/value/live.py`
(lines 541–560), `scripts/run_value.py`, `tests/test_value_fence.py` (lines 274–330), `tests/test_command_schemas.py`
(pattern), `tests/test_value_live.py` (fixtures pattern).

### Entry checks (the orchestrator, from the repo root of the main checkout, then the worktree)

- **A1 — the base.** `git -C "/Users/ianlim/Desktop/IBKR Investments" log --oneline -1 main` prints `971c825` or a
  descendant whose `git diff --stat 971c825 main -- src scripts tests config/examples` is empty except for this plan.
  `df -h .` shows at least 10 GiB free.
- **A2 — the worktree and the baseline.** Create `.claude/worktrees/value-book-6` on `feat/value-book-6` from `main`
  (HANDOFF §4: symlink `.venv`; `IBKR_CONFIG_USE_EXAMPLES=1 .venv/bin/python -c "from src.storage.db import init_db;
  init_db()"`; symlink `web/node_modules` too, since F–I touch `web/`). Copy this plan file in. Then from the
  worktree root: `python -m pytest -q` (record the count as **baseline**; Part 5's post-merge row says 5506 passed,
  1 skipped), `ruff check .` clean, `mypy src` clean (record the file count).
- **A3 — the lines this section edits** (each grep prints exactly the line shown):
  - `grep -n "^class CommandKind" src/api/models/commands.py` → `24:class CommandKind(StrEnum):`
  - `grep -n "NEWS_BRIEF = \"news_brief\"" src/api/models/commands.py` → `42:    NEWS_BRIEF = "news_brief"`
  - `grep -n "^class PromotePayload" -A6 src/api/models/commands.py` → lines 56–61, ending `    expiry: date`
  - `grep -n "^PAYLOAD_FOR" src/api/models/commands.py` → `172:PAYLOAD_FOR: dict[CommandKind, type[BaseModel]] = {`
  - `grep -n "CommandKind.NEWS_BRIEF: NewsBriefPayload," src/api/models/commands.py` → `188:...`
  - `grep -n "^def dedupe_key_for" src/api/models/commands.py` → `197:...`
  - `grep -n "_LIVE_CONFIRM_KINDS: frozenset" -A2 src/api/routers/commands.py` → `44:` then
    `    {CommandKind.APPROVE, CommandKind.PROMOTE, CommandKind.ROLL_REQUEST}` on line 45
  - `grep -n "^def pending_commands" src/storage/app_commands.py` → `68:def pending_commands(session: Session, *, limit: int = 50) -> list[AppCommandRow]:`
  - `grep -n "commands = pending_commands(s)" src/notify/command_drain.py` → `105:        commands = pending_commands(s)`
  - `grep -n "^def decide" src/value/book.py` → `217:def decide(vs: Session, proposal_id: int, *, approve: bool, now: datetime, by: str) -> str:`
  - `grep -n "^def _high_water" src/value/live.py` → `541:...`
  - `grep -n "if stop.wait(poll):" scripts/run_value.py` → `213:        if stop.wait(poll):`
  - `grep -n "class ValueServiceCfg" src/common/config.py` → `1759:...`; `grep -n "    book: ValueBookCfg = Field" src/common/config.py` → `1943:...`
- **A4 — nothing drains a value kind yet.** `grep -rn "value_approve\|value_reject\|VALUE_KINDS" src scripts` prints nothing.

Record the Section A entry row; exit target: baseline + 28 (Tasks 1–3).

### Task 1: The value kinds, the fingerprint and the trading drain's skip

**Files:** create `src/common/value_commands.py`; edit `src/api/models/commands.py`, `src/api/routers/commands.py`,
`src/storage/app_commands.py`, `src/notify/command_drain.py`, `src/common/config.py`, `config/examples/value.yaml`,
`docs/web/commands.md`, `tests/test_value_fence.py`; create `tests/test_value_commands.py`.

- [x] **Step 1: the failing tests.** Create `tests/test_value_commands.py` with these nine tests (Task 1's part; Tasks 2–3
  append their own):

```python
"""Part 6: the value command kinds (rulings 1-8). The value process drains them; nothing else does."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from src.api.models.commands import (
    CommandKind,
    PromotePayload,
    dedupe_key_for,
    validate_payload,
)
from src.common import value_commands as vc

CREATED = datetime(2026, 11, 2, 14, 35, 0)


def test_the_fingerprint_is_ten_hex_and_moves_with_the_trade() -> None:
    fp = vc.proposal_fingerprint(12, "buy", "GOOGL", 10.0, CREATED)
    assert len(fp) == 10 and int(fp, 16) >= 0
    assert fp == vc.proposal_fingerprint(12, "buy", "GOOGL", 10.0, CREATED)
    assert fp != vc.proposal_fingerprint(12, "buy", "GOOGL", 11.0, CREATED)
    assert fp != vc.proposal_fingerprint(13, "buy", "GOOGL", 10.0, CREATED)


def test_callback_data_round_trips_and_fits_telegram() -> None:
    fp = vc.proposal_fingerprint(12, "buy", "GOOGL", 10.0, CREATED)
    for action in ("approve", "reject", "trim"):
        data = vc.callback_data(action, 12 if action != "trim" else 0, fp)
        assert len(data.encode()) <= 64
        assert vc.parse_callback(data) == (action, 12 if action != "trim" else 0, fp)


@pytest.mark.parametrize("data", ["vbook:x:1:abcdef0123", "vbook:a:one:abcdef0123", "vbook:a:1:zz", "approve:1", ""])
def test_bad_callback_data_is_none(data: str) -> None:
    assert vc.parse_callback(data) is None


def test_every_value_kind_is_a_command_kind() -> None:
    assert {k.value for k in CommandKind if k.value.startswith("value_")} == set(vc.VALUE_KINDS)


def test_value_payloads_are_strict() -> None:
    ok = validate_payload(CommandKind.VALUE_APPROVE, {"proposal_id": 3, "fingerprint": "abcdef0123"})
    assert dedupe_key_for(CommandKind.VALUE_APPROVE, ok) == "value_approve:3"
    with pytest.raises(ValidationError):
        validate_payload(CommandKind.VALUE_APPROVE, {"proposal_id": 3, "fingerprint": "nothex!!!!"})
    with pytest.raises(ValidationError):
        validate_payload(CommandKind.VALUE_REJECT, {"proposal_id": 3, "fingerprint": "abcdef0123", "shares": 5})
    trim = validate_payload(CommandKind.VALUE_TRIM, {"episode": "0123456789"})
    assert dedupe_key_for(CommandKind.VALUE_TRIM, trim) == "value_trim:0123456789"
    snap = validate_payload(CommandKind.VALUE_SNAPSHOT, {"symbol": "googl", "fingerprint": {}})
    assert dedupe_key_for(CommandKind.VALUE_SNAPSHOT, snap) is None


def test_promote_declares_value_put() -> None:
    p = PromotePayload(candidate_id="c", symbol="X", strategy="cash_secured_put", strike=1.0, expiry="2026-12-18")
    assert p.value_put is False


def test_the_trading_drain_never_reads_a_value_kind(db) -> None:
    from src.storage import app_commands as ac
    from src.storage.db import session_scope

    with session_scope() as s:
        ac.enqueue_command(s, kind="value_approve", payload={"proposal_id": 1, "fingerprint": "abcdef0123"},
                           requested_by="web")
        ac.enqueue_command(s, kind="halt", payload={}, requested_by="web")
        s.commit()
        kinds = [c.kind for c in ac.pending_commands(s, exclude_kinds=vc.VALUE_KINDS)]
        mine = [c.kind for c in ac.pending_commands(s, only_kinds=vc.VALUE_KINDS)]
    assert "value_approve" not in kinds and "halt" in kinds
    assert mine == ["value_approve"]
```

  (Eleven collected items, the parametrised case counting five; with Step 6's fence test, Task 1 adds **12**.) The drain test uses `tests/conftest.py`'s `db` fixture
  (line 561: an isolated trading DB behind `session_scope`); read it first and adapt the seeding to it.

- [x] **Step 2: run them red.** `python -m pytest tests/test_value_commands.py -q` → collection `ModuleNotFoundError:
  No module named 'src.common.value_commands'`.

- [x] **Step 3: the neutral module.** Create `src/common/value_commands.py`:

```python
"""The value book's command kinds, proposal fingerprint and Telegram callback format (Part 6, spec §9.7).

Standard library only: the API, ``approval_service`` and the value process all import it, and none of them may
import another's code. The value process is the only drainer of these kinds; ``command_drain`` skips them.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Literal

VALUE_KINDS: frozenset[str] = frozenset(
    {"value_approve", "value_reject", "value_trim", "value_snapshot", "value_analyse", "value_refresh"}
)
# Kinds that change order state; the value process refuses them under LIVE_TRADING=true.
VALUE_ORDER_KINDS: frozenset[str] = frozenset({"value_approve", "value_reject", "value_trim"})

Action = Literal["approve", "reject", "trim"]
_CODE: dict[str, str] = {"approve": "a", "reject": "r", "trim": "t"}
_ACTION: dict[str, Action] = {"a": "approve", "r": "reject", "t": "trim"}
_FP = re.compile(r"^[0-9a-f]{10}$")
_CALLBACK = re.compile(r"^vbook:([art]):(\d{1,9}):([0-9a-f]{10})$")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:10]


def proposal_fingerprint(pid: int, kind: str, symbol: str, shares: float, created_at: datetime) -> str:
    """What a card shows and a tap must carry back: a re-sized or replaced proposal no longer matches."""
    return _hash(f"{pid}|{kind}|{symbol.upper()}|{shares:g}|{created_at:%Y-%m-%dT%H:%M:%S}")


def trim_episode(high: float, offered_at: datetime) -> str:
    """One drawdown episode's id: a trim tap after ``--reset-drawdown`` no longer matches."""
    return _hash(f"trim|{high:.2f}|{offered_at:%Y-%m-%dT%H:%M:%S}")


def is_fingerprint(text: str) -> bool:
    return bool(_FP.match(text))


def callback_data(action: Action, target: int, fingerprint: str) -> str:
    """``vbook:<a|r|t>:<id>:<fp>``; at most 32 bytes, under Telegram's 64."""
    return f"vbook:{_CODE[action]}:{target}:{fingerprint}"


def parse_callback(data: str) -> tuple[Action, int, str] | None:
    m = _CALLBACK.match(data or "")
    if m is None:
        return None
    return _ACTION[m.group(1)], int(m.group(2)), m.group(3)
```

- [x] **Step 4: the API models.** In `src/api/models/commands.py`:
  - after line 42 (`NEWS_BRIEF = "news_brief"`) add the six members `VALUE_APPROVE = "value_approve"`,
    `VALUE_REJECT = "value_reject"`, `VALUE_TRIM = "value_trim"`, `VALUE_SNAPSHOT = "value_snapshot"`,
    `VALUE_ANALYSE = "value_analyse"`, `VALUE_REFRESH = "value_refresh"`;
  - in `PromotePayload` (line 61) add `    value_put: bool = False` after `expiry: date`;
  - after `NewsBriefPayload` add:

```python
_SYMBOL = r"^\$?[A-Za-z][A-Za-z0-9.\-]{0,9}$"


class ValueDecisionPayload(BaseModel):
    """A tap on a value proposal (spec §9.7). The value process re-gates and sends; this decides nothing else."""

    model_config = ConfigDict(extra="forbid")
    proposal_id: int = Field(ge=1)
    fingerprint: str = Field(pattern=r"^[0-9a-f]{10}$")


class ValueTrimPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episode: str = Field(pattern=r"^[0-9a-f]{10}$")


class ValueSymbolPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(pattern=_SYMBOL)


class ValueSnapshotPayload(BaseModel):
    """Spec §6.9: the API showed this name's file; ``fingerprint`` is the input set it used (empty: stored)."""

    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(pattern=_SYMBOL)
    fingerprint: dict = Field(default_factory=dict)
```

  - in `PAYLOAD_FOR` after line 188 add the six entries (`VALUE_APPROVE` and `VALUE_REJECT` →
    `ValueDecisionPayload`, `VALUE_TRIM` → `ValueTrimPayload`, `VALUE_SNAPSHOT` → `ValueSnapshotPayload`,
    `VALUE_ANALYSE` and `VALUE_REFRESH` → `ValueSymbolPayload`);
  - in `dedupe_key_for`: add `CommandKind.VALUE_SNAPSHOT, CommandKind.VALUE_ANALYSE, CommandKind.VALUE_REFRESH` to the
    repeatable tuple (extend the docstring by one sentence: "The value read-side kinds are repeatable: the value
    process dedupes its read queue."), and before the final `return None`:

```python
    if kind in (CommandKind.VALUE_APPROVE, CommandKind.VALUE_REJECT):
        assert isinstance(payload, ValueDecisionPayload)
        return f"{kind.value}:{payload.proposal_id}"
    if kind == CommandKind.VALUE_TRIM:
        assert isinstance(payload, ValueTrimPayload)
        return f"{kind.value}:{payload.episode}"
```

  In `src/api/routers/commands.py` line 45 the set becomes
  `{CommandKind.APPROVE, CommandKind.PROMOTE, CommandKind.ROLL_REQUEST, CommandKind.VALUE_APPROVE, CommandKind.VALUE_TRIM}`
  and the comment above it gains: "`value_approve` and `value_trim` reach an order through the value process (an
  approved buy may release wheel capital), so they confirm in live too, though the value process refuses live."

- [x] **Step 5: the trading drain skips them.** In `src/storage/app_commands.py` replace `pending_commands` (line 68) with:

```python
def pending_commands(
    session: Session,
    *,
    limit: int = 50,
    exclude_kinds: frozenset[str] | None = None,
    only_kinds: frozenset[str] | None = None,
) -> list[AppCommandRow]:
    """All commands still awaiting application, oldest first. ``exclude_kinds``: the trading drain leaves the
    value kinds for the value process (spec §9.7); ``only_kinds``: what the value process claims."""
    q = select(AppCommandRow).where(AppCommandRow.status == "pending")
    if exclude_kinds:
        q = q.where(AppCommandRow.kind.not_in(sorted(exclude_kinds)))
    if only_kinds:
        q = q.where(AppCommandRow.kind.in_(sorted(only_kinds)))
    return list(session.execute(q.order_by(AppCommandRow.id).limit(limit)).scalars().all())
```

  In `src/notify/command_drain.py` add `from src.common.value_commands import VALUE_KINDS` to the imports and change
  line 105 to `        commands = pending_commands(s, exclude_kinds=VALUE_KINDS)`; add one sentence to the module
  docstring's design point 2: "The value kinds (`src/common/value_commands.VALUE_KINDS`) are never read here: the value
  process drains them (spec §9.7); the TTL sweep still expires one it never picked up."

- [x] **Step 6: config and the fence.** In `src/common/config.py` after `ValueServiceCfg` add:

```python
class ValueTelegramCfg(_ValueModel):
    """Part 6: the value process's command poll and its nightly digest (rulings 7, 13)."""

    commands_poll_seconds: int = 15
    digest_enabled: bool = True
    no_progress_months: int = 9  # a review card: held this long, never past entry + 10% of the way to fair value
    fv_drop_pct: float = 10.0  # a review card: fair value down this much since entry while the price is not

    @model_validator(mode="after")
    def _sane(self) -> ValueTelegramCfg:
        if not 5 <= self.commands_poll_seconds <= 300:
            raise ValueError("value telegram.commands_poll_seconds must be 5-300")
        return self


class ValuePromptNoteCfg(_ValueModel):
    """Part 6, ruling 9: the VALUE NOTE in the wheel's trade review, roll review and /scan NAME."""

    enabled: bool = True
```

  and in `ValueCfg` after line 1943 (`book: ...`) add `    telegram: ValueTelegramCfg = Field(default_factory=ValueTelegramCfg)`
  and `    prompt_note: ValuePromptNoteCfg = Field(default_factory=ValuePromptNoteCfg)`. Append to `config/examples/value.yaml`
  (top level, after `book:`):

```yaml
telegram:                      # Part 6: the value process's taps and digest
  commands_poll_seconds: 15    # how often the value process drains value_* commands
  digest_enabled: true         # one message a night to TELEGRAM_THREAD_VALUE
  no_progress_months: 9        # review card: held this long with no progress
  fv_drop_pct: 10              # review card: fair value down this much while the price is not
prompt_note:
  enabled: true                # the VALUE NOTE in the wheel's review prompts (reduce-only reach)
```

  Neither key is under `rules:`; check `python -c "from src.value.ruleset import ...` is unnecessary: the frozen-hash
  test `tests/test_value_config.py` (or wherever `FROZEN["v4"]` is asserted) must stay green. In
  `tests/test_value_fence.py` add:

```python
def test_value_commands_is_stdlib_only() -> None:
    mods = imported_modules(ROOT / "src" / "common" / "value_commands.py")
    assert {m.split(".")[0] for m in mods} <= {"__future__", "hashlib", "re", "datetime", "typing"}
```

  and add `"src.notify.command_drain"` to nothing: the existing `test_the_trading_path_never_imports_the_value_book`
  already covers `src/notify/` (it checks `src.value`, and `src.common.value_commands` is not under it).

- [x] **Step 7: docs/web/commands.md.** Add one table row per new kind in the file's existing format: who sends it (web,
  Telegram), its payload, its dedupe key, **"drained by the value process (`scripts/run_value.py`), not by
  `approval_service`"**, its failure reasons (`no_such_proposal`, `stale_proposal`, `already_<status>`, `expired`,
  `not_paper`, `already_trimmed`, `claude_off`, `invalid_symbol`) and that a `value_approve` may cause capital-release
  closes of wheel CSPs (Part 5 ruling 7). Add `value_put` to the `promote` row.

- [x] **Step 8: gates.** `python -m pytest tests/test_value_commands.py tests/test_value_fence.py tests/test_command_schemas.py
  tests/test_write_path_invariants.py tests/test_value_config.py tests/test_drain_promote.py -q` green (10 new);
  `python -m pytest tests -q -k "command_drain or drain"` green; regenerate the contract
  (`IBKR_CONFIG_USE_EXAMPLES=1 python -c "import json; from src.api.main import create_app; ..."` — use the exact
  command `tests/test_openapi_current.py`'s failure message prints) and `cd web && npx openapi-typescript
  ../docs/web/openapi.json -o lib/api-types.ts` (da-vinci not needed: a generated file, no surface), then
  `python -m pytest tests/test_openapi_current.py -q` green; `ruff check .`, `ruff format` on the touched files,
  `mypy src`. Commit `feat(value): the value command kinds; the trading drain leaves them to the value process`
  (with this plan file).

### Task 2: The value process drains its kinds

**Files:** create `src/value/commands.py`; edit `scripts/run_value.py`, `tests/test_value_fence.py`; append to
`tests/test_value_commands.py`.

`src/value/commands.py` is pure over a value.db `Session` (no `src.storage` import: the entrypoint owns the trading DB
side). It exposes:

```python
"""Apply the value command kinds (Part 6, spec §9.7) inside value.db. Pure over a Session; the entrypoint claims
the app_commands rows and marks them. Paper only for the kinds that change order state."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from src.common.value_commands import VALUE_ORDER_KINDS, proposal_fingerprint
from src.value.book import decide, trim_to_half
from src.value.store import ValueProposalRow


class ValueCommandFailed(Exception):
    def __init__(self, reason: str, detail: dict | None = None) -> None:
        super().__init__(reason)
        self.reason, self.detail = reason, detail or {}


Handler = Callable[[Session, dict, str, datetime], dict]
HANDLERS: dict[str, Handler] = {}


def _register(kind: str) -> Callable[[Handler], Handler]:
    def wrap(fn: Handler) -> Handler:
        HANDLERS[kind] = fn
        return fn

    return wrap


def apply(vs: Session, kind: str, payload: dict, *, requested_by: str, now: datetime, live: bool) -> dict:
    """One command. Raises ValueCommandFailed with a machine reason; the caller marks the command."""
    if live and kind in VALUE_ORDER_KINDS:
        raise ValueCommandFailed("not_paper")
    fn = HANDLERS.get(kind)
    if fn is None:
        raise ValueCommandFailed("unknown_kind")
    return fn(vs, payload, _by(requested_by), now)


def _by(requested_by: str) -> str:
    return requested_by if requested_by in ("web", "telegram", "cli") else "web"


def _decision(vs: Session, payload: dict, by: str, now: datetime, *, approve: bool) -> dict:
    pid = int(payload["proposal_id"])
    row = vs.get(ValueProposalRow, pid)
    if row is None:
        raise ValueCommandFailed("no_such_proposal")
    if proposal_fingerprint(row.id, row.kind, row.symbol, row.shares, row.created_at) != payload["fingerprint"]:
        raise ValueCommandFailed("stale_proposal")
    status = decide(vs, pid, approve=approve, now=now, by=by)
    if status not in ("approved", "rejected"):
        raise ValueCommandFailed(status, {"proposal_id": pid})  # already_<status> | expired
    return {"proposal_id": pid, "decision": status, "symbol": row.symbol, "kind": row.kind}


@_register("value_approve")
def _approve(vs: Session, payload: dict, by: str, now: datetime) -> dict:
    return _decision(vs, payload, by, now, approve=True)


@_register("value_reject")
def _reject(vs: Session, payload: dict, by: str, now: datetime) -> dict:
    return _decision(vs, payload, by, now, approve=False)


@_register("value_trim")
def _trim(vs: Session, payload: dict, by: str, now: datetime) -> dict:
    created = trim_to_half(vs, episode=str(payload["episode"]), by=by, now=now)  # Task 3
    return {"episode": payload["episode"], "proposals": created}


def outcome_line(kind: str, result: dict | None, reason: str | None) -> str:
    """The plain reply the value process posts to TELEGRAM_THREAD_VALUE after a tap."""
    ...  # Task 4 replaces this stub with cards.outcome_line; Task 2 returns f"{kind}: {reason or 'done'}"
```

(The `outcome_line` body in Task 2 is the one-line return in its comment; Task 4 moves the wording to `cards.py`.)
Task 3 adds `trim_to_half`; until then Task 2 registers `value_trim` with a body that raises
`ValueCommandFailed("not_built")`, and Task 3 replaces it with the body above.

In `scripts/run_value.py` add, above `main`:

```python
def _drain_commands() -> int:
    """Claim the value kinds from app_commands, apply each in value.db, mark it (spec §9.7, ruling 1). The trading
    DB is imported here only: importing this script loads no wheel layer (the fence's probe)."""
    from src.common.value_commands import VALUE_KINDS
    from src.storage.app_commands import mark_applied, mark_failed, pending_commands
    from src.storage.db import session_scope
    from src.value import commands as vcmd
    from src.value.store import init_value_db, value_session

    cfg = get_config()
    with session_scope() as s:
        rows = [
            (c.id, c.kind, dict(c.payload or {}), c.requested_by or "web")
            for c in pending_commands(s, only_kinds=VALUE_KINDS)
            if c.confirm_token is None
        ]
        s.commit()
    if not rows:
        return 0
    init_value_db()
    replies: list[str] = []
    for cid, kind, payload, by in rows:
        now = datetime.now(UTC).replace(tzinfo=None)
        result: dict | None = None
        reason: str | None = None
        detail: dict | None = None
        try:
            with value_session() as vs:
                result = vcmd.apply(vs, kind, payload, requested_by=by, now=now, live=cfg.is_live)
        except vcmd.ValueCommandFailed as exc:
            reason, detail = exc.reason, exc.detail
        except Exception as exc:  # noqa: BLE001 - one bad command never stops the drain
            log.exception("value: command %d (%s) raised", cid, kind)
            reason, detail = "handler_error", {"error": str(exc)}
        with session_scope() as s:
            if reason is None:
                mark_applied(s, cid, result or {})
            else:
                mark_failed(s, cid, reason, detail)
            s.commit()
        if kind in ("value_approve", "value_reject", "value_trim") and by == "telegram":
            replies.append(vcmd.outcome_line(kind, result, reason))
    if replies:
        from src.value.notify import send

        asyncio.run(send(replies))
    return len(rows)
```

  (`value_session()` commits on exit and rolls back on an exception — check `src/value/store.py`'s context manager
  before relying on it; if it does not commit, add `vs.commit()` after `apply`.) The order is "value.db commits, then
  the command is marked": a crash between them leaves the command pending and the next drain re-applies it, which
  `decide` answers `already_approved` (marked failed with that reason, harmless) — the review focus checks this.

  Replace `main`'s loop (lines 198–214) with:

```python
    cfg = get_config().value
    poll, fast = cfg.service.poll_seconds, cfg.telegram.commands_poll_seconds
    log.info("value: running; commands every %ds, a settled session every %ds", fast, poll)
    last_slow = 0.0
    while True:
        try:
            _drain_commands()
        except Exception:  # noqa: BLE001 - commands wait for the next tick
            log.exception("value: the command drain failed; retrying at the next tick")
        if time.monotonic() - last_slow >= poll:
            last_slow = time.monotonic()
            try:
                _tick()
            except Exception:  # noqa: BLE001 - a failed night is retried at the next poll
                log.exception("value: the nightly run failed; retrying at the next poll")
            try:
                _claude_tick()
            except Exception:  # noqa: BLE001 - a failed read is recorded; the queue waits
                log.exception("value: claude reads failed; the queue waits for the next poll")
            try:
                _book_tick()
            except Exception:  # noqa: BLE001 - a failed cycle sends nothing; the next one retries
                log.exception("value: the book cycle failed; retrying at the next poll")
        if stop.wait(fast):
            break
```

  with `import time` added to the module's imports. Check `_book_tick`'s own `cycle_minutes` guard still bounds the RTH cycle
  (it does: it compares against the last cycle's time, line 122).

- [x] **Step 1: the failing tests** (append to `tests/test_value_commands.py`, eleven): `test_approve_needs_the_current_fingerprint`
  (a stale fingerprint → `stale_proposal`, the row stays `pending`); `test_approve_marks_who_decided` (`requested_by="telegram"`
  → `decided_by == "telegram"`, `status == "approved"`); `test_a_second_tap_is_a_no_op_answer` (second apply raises
  `already_approved`, `decided_at` unchanged); `test_reject_after_approve_is_refused`; `test_an_expired_proposal_expires`
  (pin `now` after `expires_at` → `expired`); `test_no_such_proposal`; `test_live_refuses_order_kinds` (each of the three
  order kinds with `live=True` → `not_paper`, value.db unchanged); `test_live_allows_read_kinds` (`value_refresh` with
  `live=True` is not refused for `not_paper`; Task 8 gives it a body — until then it raises `unknown_kind`, so this test is
  written in Task 8; count it there); `test_unknown_requester_reads_as_web`; `test_drain_marks_applied_and_failed`
  (`_drain_commands` cannot be imported: test the same loop through a helper — **put the loop body in
  `src/value/commands.py::drain(rows, apply_fn, mark_fn)`** taking plain tuples and two callables, and have
  `_drain_commands` call it; the test passes fakes for both and asserts applied/failed calls and that value.db commits
  before the mark); `test_drain_skips_a_command_awaiting_confirmation` (the entrypoint's filter is `confirm_token is None`:
  test it on `drain`'s input filter by moving that filter into `drain` too); `test_the_value_entrypoint_drains_lazily`
  (fence, in `tests/test_value_fence.py`: extend the entrypoint allowlist with `"time"`, `"src.common.value_commands"`,
  `"src.value.commands"`, `"src.storage.app_commands"`, `"src.storage.db"`, `"src.value.store"`, and assert by `ast` that
  `src.storage.app_commands` and `src.storage.db` are imported only inside a function body of `scripts/run_value.py`).
  Fixtures: `tests/test_value_live.py`'s value.db fixture pattern (an in-memory or `tmp_path` value.db through
  `value_session`), a proposal built with `book.propose(..., auto=False)`. **11 new.**
- [x] **Step 2: red.** `ModuleNotFoundError: No module named 'src.value.commands'`.
- [x] **Step 3: code** as above (with `drain` holding the loop; note that a `ValueCommandFailed` raised inside
  `value_session()` rolls the value.db transaction back, so a refused tap changes nothing there — including
  `decide`'s own `expired` write, which `book.expire` repeats on the next cycle; `_drain_commands` only gathers rows, opens sessions and
  calls `drain`).
- [x] **Step 4: gates.** `python -m pytest tests/test_value_commands.py tests/test_value_fence.py tests/test_value_live.py -q`;
  `python -m py_compile scripts/run_value.py` silent; ruff, `mypy src`. Commit
  `feat(value): the value process drains its own command kinds (spec 9.7)`.

### Task 3: The 25% drawdown's "trim to half"

**Files:** edit `src/value/book.py`, `src/value/live.py`, `scripts/value_book.py` (the reset clears the episode),
`src/value/commands.py` (the real `_trim`); append to `tests/test_value_commands.py`.

- [x] **Step 1: the failing tests** (five): `test_trim_halves_every_filled_position` (two open positions of 10 and 7
  filled shares → two sell proposals of 5 and 3 shares (`sell_shares`' rounding), `status == "approved"`,
  `reason == "drawdown_trim"`, `cause == "python"`, `decided_by == "telegram"`); `test_trim_skips_a_name_with_an_open_sell`;
  `test_trim_needs_the_current_episode` (wrong episode → `stale_proposal`; no episode offered → `no_trim_offered`);
  `test_a_second_trim_is_already_trimmed`; `test_the_trim_is_offered_once_per_episode` (`_high_water` with the value 26%
  under the high sets `trim_offered_at` and `episode` once; a second call keeps them; `--reset-drawdown`'s state write
  clears them). **5 new.**
- [x] **Step 2: red** (`ImportError: cannot import name 'trim_to_half'`).
- [x] **Step 3: code.** In `live._high_water` (line 541) after `stop = ...` compute
  `trim = high > 0 and (high - value) / high * 100.0 >= cfg.book.drawdown_trim_pct`; carry `trim_offered_at` /
  `episode` / `trimmed` forward from `state`; when `trim` and no `trim_offered_at`, set `trim_offered_at = now` and
  `episode = value_commands.trim_episode(high, now)`, and return the episode so the cycle's messages gain the trim card
  (Task 4 renders it; until then a plain line "The value book is down N% from its high: trim to half?"). In `book.py`
  add:

```python
def trim_to_half(vs: Session, *, episode: str, by: str, now: datetime) -> list[int]:
    """Spec §9.6 and Part 6 ruling 3: one tap sells half of every filled position, approved now; each sale is
    still re-gated and capped by the sell cap at send time. Returns the new proposal ids."""
    state = get_state(vs, "high_water") or {}
    if not state.get("episode"):
        raise_reason("no_trim_offered")
    if state.get("episode") != episode:
        raise_reason("stale_proposal")
    if state.get("trimmed"):
        raise_reason("already_trimmed")
    made: list[int] = []
    for pos in vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open")):
        held = totals(vs).names.get(pos.symbol)
        shares = sell_shares(held.filled if held else 0.0, 0.5)
        if shares <= 0:
            continue
        row = propose(vs, kind="sell", symbol=pos.symbol, list_name=pos.list_name, shares=float(shares),
                      price=None, reason="drawdown_trim", cause="python", auto=True, now=now,
                      ttl_hours=TRIM_TTL_HOURS, position_id=pos.id)
        if row is not None:
            row.decided_by = by
            made.append(row.id)
    set_state(vs, "high_water", {**state, "trimmed": True, "trimmed_at": now.isoformat()}, now)
    return made
```

  where `raise_reason` raises `src.value.commands.ValueCommandFailed` — **no**: `book.py` must not import `commands.py`
  (a cycle). Define `class BookRefused(Exception)` with a `reason` in `book.py`, raise it here, and have
  `commands._trim` translate it to `ValueCommandFailed(exc.reason)`. `TRIM_TTL_HOURS = 30` (a module constant beside
  the others: the same horizon as a funding request; record the number as a ruling). Read `totals()` once outside the
  loop. `scripts/value_book.py --reset-drawdown` already writes `{**state, "stop": False, "high": value}`: make it
  also drop `trim_offered_at`, `episode`, `trimmed`, `trimmed_at`.
- [x] **Step 4: gates.** `python -m pytest tests/test_value_commands.py tests/test_value_live.py tests/test_value_stage3.py -q`;
  `py_compile scripts/value_book.py`; ruff; mypy. Commit `feat(value): the 25% drawdown's trim to half, one tap`.

### Section A exit

- [x] Full gate: `python -m pytest -q` = baseline + 28 (recompute), `ruff check .`, `mypy src`, `py_compile` of
  `scripts/run_value.py` and `scripts/value_book.py`; protected-file diff empty; `git diff --stat main...HEAD -- web`
  lists only `web/lib/api-types.ts`; `grep -rn "src.value" src/notify src/api | grep -v "value_commands\|value_view\|value_db\|value_lookup"`
  prints nothing. Add the Section A exit row; ask the operator before Section B.

## Section B — Telegram: cards, buttons, `/value`, the digest (Tasks 4–6) · model: sonnet · effort: high

**Reads:** rulings 3, 6, 11–14, 21; spec §7 (review cards), §7.1 step 4, §10 "Telegram"; `src/value/notify.py`,
`src/value/store.py` (lines 253–280, 476–560, 560–620), `src/value/stage3.py` (lines 72–145), `scripts/run_value.py`
(lines 109–190), `src/common/value_view.py`, `src/notify/approval_service.py` (lines 150–175, 273–300, 418–470,
532–566, 2003–2030), `src/notify/formatters.py` (only to see the escaping convention; the value cards are plain text),
`tests/test_value_view.py`, `tests/test_value_fence.py` (lines 407–434).

### Entry checks

- **B1.** Section A's exit row is filled and the operator said go. `git log --oneline main..HEAD | wc -l` recorded.
- **B2.** `grep -n "^async def send" src/value/notify.py` → `15:`; `grep -n "app.add_handler(CallbackQueryHandler(handle_close_short" src/notify/approval_service.py`
  → `2011:`; `grep -n "app.add_handler(CommandHandler(\"campaigns\"" src/notify/approval_service.py` → `2029:`;
  `grep -n "^def _is_authorized" src/notify/approval_service.py` → `161:`; `grep -n "^def put_ceiling" src/common/value_view.py`
  → `189:`; `grep -n "\"pathlib\"," tests/test_value_fence.py` → one line inside
  `test_the_wheel_reads_the_value_book_only_through_the_read_only_view` (≈ line 418).
- **B3.** `grep -n "posted_at" src/value/store.py` prints nothing.

Exit target: Section A's exit + 30 (baseline + 58).

### Task 4: Cards with buttons, and the outbox that posts them once

**Files:** create `src/value/cards.py` (pure) and `src/value/outbox.py`; edit `src/value/store.py`, `src/value/notify.py`,
`scripts/run_value.py`, `src/value/stage3.py`, `src/value/commands.py` (`outcome_line` delegates to `cards`); create
`tests/test_value_cards.py`.

**Interfaces.**

```python
# src/value/cards.py — pure: no I/O, no Telegram import.
@dataclass(frozen=True)
class Card:
    key: str                       # what the outbox marks posted: "proposal:12", "reeval:7", "trim:<episode>", "freeze:GOOGL"
    text: str                      # plain text, at most 3,500 characters
    buttons: tuple[tuple[str, str], ...] = ()   # (label, callback_data) from value_commands.callback_data

VALUE_REASON_LABELS: dict[str, str]  # every reason src/value/risk.py can return, plus the command reasons, in words

def proposal_card(p: ValueProposalRow, *, release_closes: int, fair_value: float | None,
                  mos: float | None, verdict_by: str) -> Card
def reevaluation_card(r: ValueReevaluationRow) -> Card          # Major: what fired, plan before -> now, why
def trim_card(state: dict, positions: list[tuple[str, float]]) -> Card
def freeze_card(symbol: str, detail: str) -> Card
def outcome_line(kind: str, result: dict | None, reason: str | None) -> str
def reason_words(code: str) -> str   # VALUE_REASON_LABELS.get(code, code.replace("_", " "))
```

`proposal_card` text, in this order: the kind and name ("Buy 10 GOOGL (quality growth, tranche 1 of 3)" or "Sell 5
GOOGL"), who caused it ("Python" or "Claude's number": a `cause="claude"` sale says "Only Claude's number makes this
sale; it waits for you"), the close it was sized at, fair value and margin of safety ("n/a" when unknown, never 0),
the reason in words, and for a buy: "If cash is short, approving may close up to {release_closes} of the wheel's
cash-secured puts at breakeven or better to fund it." Buttons: Approve and Reject with
`callback_data("approve"|"reject", p.id, proposal_fingerprint(...))`; no buttons when `needs_tap` is false (an auto
proposal's card is informational and says "Approved by the system"). `trim_card`: "The value book is down N% from its
high ($H to $V). Trim every holding to half?" listing each name and the shares a trim would sell, one button "Trim to
half" (`callback_data("trim", 0, episode)`), and the line "Each sale is still checked at send time; nothing sells
until the next check." No Claude prose appears on any button (ruling 30's rule applies to Telegram too).

`src/value/outbox.py::due(vs, now, cfg) -> list[Card]` collects, oldest first: pending (and newly auto-approved)
proposals with `posted_at IS NULL`; Major `value_reevaluations` rows with `posted_at IS NULL` (Minor ones wait for
the digest, Task 6); the trim card when `high_water.episode` is set and `high_water.trim_posted` is not; frozen
attributions not yet posted (`value_attribution.state == "frozen"`, a `posted_at` on that row too).
`mark_posted(vs, keys, now)` stamps them. Three nullable `posted_at` columns (`value_proposals`, `value_reevaluations`,
`value_attribution`) go through `_ADDED_COLUMNS` in `store.py` (migration-safe, Part 5 Task 2's pattern).

`src/value/notify.py` gains `async def send_cards(cards: list[Card]) -> list[str]` returning the keys it sent (an
`InlineKeyboardMarkup` of one row per card when it has buttons; never raises; logs each card). `scripts/run_value.py`
gains `_post_outbox()` called after `_drain_commands()` on every fast tick (reads `outbox.due`, sends, marks the sent
keys in a second short transaction). `stage3.run_cycle`'s plain "re-evaluation opened" lines (line 139) are dropped,
since the outbox now posts the Major card; its other messages (fills, refusals) stay plain.

- [x] **Step 1: the failing tests** (`tests/test_value_cards.py`, eleven): `test_a_buy_card_names_the_release_it_may_cause`;
  `test_a_tap_card_has_approve_and_reject_with_the_fingerprint`; `test_an_auto_proposal_card_has_no_buttons`;
  `test_a_claude_sale_says_it_waits_for_you`; `test_unknown_numbers_read_n_a`; `test_every_risk_reason_has_words`
  (parse `src/value/risk.py` for its reason strings with `ast`, assert each is in `VALUE_REASON_LABELS`);
  `test_the_trim_card_lists_what_it_would_sell`; `test_a_major_reevaluation_card_shows_plan_before_and_after`;
  `test_the_outbox_posts_each_card_once` (due → mark_posted → due is empty); `test_minor_reevaluations_wait_for_the_digest`;
  `test_send_cards_never_raises` (a `telegram.Bot` stub raising → returns `[]`; patch `telegram.Bot`, never reach the
  network — the Part 5 post-merge fix "the notifier test no longer posts to a real Telegram chat" is the pattern). **11.**
- [x] **Step 2: red; Step 3: code; Step 4: gates** `python -m pytest tests/test_value_cards.py tests/test_value_commands.py
  tests/test_value_stage3.py tests/test_value_store.py tests/test_value_fence.py -q`; `py_compile scripts/run_value.py`;
  ruff; mypy. Commit `feat(value): cards with buttons, posted once through the outbox`.

### Task 5: The forwarder and `/value` in `approval_service`

**Files:** edit `src/common/value_view.py`, `src/notify/approval_service.py`, `tests/test_value_fence.py`; create
`tests/test_value_telegram.py`.

**`value_view` additions** (plain SQL, `mode=ro`, through the existing `_connect`; each returns `None` when value.db
is missing or unreadable, never raises):

```python
@dataclass(frozen=True)
class TickerFileView:   # one row of value_ticker_files, the summary fields only
    symbol: str; computed_at: datetime; as_of: date; universe: str; verdict_deep: str; verdict_growth: str
    filed_list: str | None; fair_value_deep: float | None; fair_value_growth: float | None
    mos_deep: float | None; mos_growth: float | None; price: float | None
    effective: dict[str, tuple[str, str]]  # list -> (verdict, "claude" | "python") from value_effective
    held_shares: float; open_reevaluation: str | None   # severity of an open held re-evaluation
    freshness_json: str | None

def read_ticker_file(symbol: str) -> TickerFileView | None
def top_names(list_name: str, n: int = 5) -> list[TickerFileView] | None   # READY then WATCH, by rank
def open_proposals() -> list[ProposalView] | None   # pending/approved/funding/sent, with the fingerprint
def last_nightly_run() -> datetime | None            # Task 9 uses it
```

`ProposalView` carries `id, kind, symbol, list_name, shares, price, reason, cause, needs_tap, status, created_at,
expires_at, fingerprint` (computed with `value_commands.proposal_fingerprint`). `value_view` may now import `json` and
`src.common.value_commands` (both stdlib-only); widen the fence test's allowed set by `"json"` and its `src.`
assertion to accept `src.common.value_commands` beside `src.common.config` — **the only widening of a fence in this
plan**, recorded as a ruling (cost if wrong: none; both are read-only and import no value code).

**`approval_service`:**

```python
async def handle_value_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """A tap on a value card (spec §9.7): forward it as an intent; the value process decides, re-gates and sends."""
    query = update.callback_query
    if query is None or not _is_authorized(update):
        return
    from src.common import value_commands as vc

    parsed = vc.parse_callback(query.data or "")
    if parsed is None:
        logger.warning("Unexpected value callback_data: %r", query.data)
        await query.answer("Not a value button.")
        return
    action, target, fp = parsed
    kind, payload = (
        ("value_trim", {"episode": fp}) if action == "trim"
        else (f"value_{action}", {"proposal_id": target, "fingerprint": fp})
    )
    key = f"{kind}:{fp if action == 'trim' else target}"
    from src.storage.app_commands import enqueue_command

    with session_scope() as s:
        _, created = enqueue_command(s, kind=kind, payload=payload, requested_by="telegram", dedupe_key=key)
        s.commit()
    await query.answer("Queued: the value process acts on it within a minute." if created else "Already queued.")
```

registered after line 2011 as `app.add_handler(CallbackQueryHandler(handle_value_button, pattern="^vbook:"))`, and
`handle_value_command` for `/value`, `/value NAME`, `/value NAME analyse` (ruling 12), registered after line 2029. It reads
only `value_view`; to queue a refresh or analysis it enqueues `value_refresh` / `value_analyse` the same way
(`requested_by="telegram"`); it never builds a scorecard. `/value` lists `top_names` for both lists and the open
proposals, each tap-waiting proposal with its own Approve/Reject buttons (built with `value_commands.callback_data`;
render them here with plain f-strings, not `src.value.cards`, which `approval_service` may not import). Use
`session_scope` (already imported by `approval_service`; check) and `asyncio.to_thread` around the sqlite reads as
`/news` does. `/help`'s text (line 418) gains the three forms. Every reply is plain text.

- [ ] **Step 1: the failing tests** (twelve across `tests/test_value_telegram.py` and `tests/test_value_view.py`):
  `test_a_value_tap_becomes_one_intent` (twice → one row, the second answer "Already queued."); `test_a_trim_tap_carries_the_episode`;
  `test_a_bad_value_callback_is_refused`; `test_an_unauthorised_tap_does_nothing`; `test_value_lists_both_lists_and_proposals`;
  `test_value_name_shows_the_stored_file_and_its_age`; `test_a_stale_file_queues_a_refresh`; `test_value_name_analyse_queues_a_read`;
  `test_value_without_a_value_db_says_so`; `read_ticker_file`, `top_names`, `open_proposals` each against a seeded
  `tmp_path` value.db (3 tests in `tests/test_value_view.py`, the autouse `_value_view_in_tmp` pattern there). Drive
  the handlers with `MagicMock` updates as `tests/test_telegram_*` do (find the existing `/news` handler test with
  `grep -rln "handle_news_command" tests` and copy its fakes). Plus the fence (in `tests/test_value_fence.py`):
  `test_approval_service_reaches_the_value_book_only_through_the_view` (`ast`: `src/notify/approval_service.py`
  imports `src.common.value_view` and `src.common.value_commands` and nothing under `src.value`). **12.**
- [ ] **Step 2: red; Step 3: code; Step 4: gates** the new files plus `tests/test_value_fence.py`, `tests/test_eval_skills.py`,
  `tests/test_web_fence.py`, the existing approval-service suites (`python -m pytest tests -q -k "approval_service or telegram"`);
  ruff; mypy. Commit `feat(notify): value buttons become intents; /value reads the value book read-only`.

### Task 6: The nightly digest and the review cards

**Files:** create `src/value/digest.py` (pure) and `tests/test_value_digest.py`; edit `src/value/service.py`
(`run_nightly` returns the digest's inputs), `scripts/run_value.py` (`_tick` posts it), `src/value/store.py`
(`value_book_state` key `digest` holding the last digest's time).

`digest.build(vs, *, since: datetime, now: datetime, cfg: ValueCfg) -> str | None` (ruling 13): Minor re-evaluations
recorded since `since` (what fired, plan before → now, one line each); review cards — a kill trigger that fired tonight
(`value_kill_triggers`), a position held `no_progress_months` or more whose highest close since entry never passed
entry + 10% of the distance to fair value, a position whose Python fair value fell `fv_drop_pct` or more since entry
while its close did not fall (spec §7 "Review cards, not exits"); the book line (open positions, cost, marked value,
drawdown from the high, the drawdown and trend breaker states in words); proposals waiting for a tap (ids and names;
the buttons are on their own cards). Returns `None` when every part is empty. The night posts it once after
`run_nightly` succeeds (`value.telegram.digest_enabled`), then sets the `digest` state. These cards never sell (spec §7).

- [ ] **Step 1: the failing tests** (seven): `test_an_empty_night_sends_nothing`; `test_minor_reevaluations_are_listed_once`
  (a second build with the stored `since` omits them); `test_a_fired_kill_trigger_is_a_review_card`;
  `test_nine_months_without_progress_is_a_review_card`; `test_fair_value_down_while_price_is_not_is_a_review_card`;
  `test_the_book_line_says_the_breakers_in_words`; `test_review_cards_never_create_a_proposal` (proposal count unchanged). **7.**
- [ ] **Steps 2–4:** red, code, gates (`tests/test_value_digest.py tests/test_value_service.py tests/test_value_fence.py`;
  `py_compile scripts/run_value.py`; ruff; mypy). Commit `feat(value): the nightly digest and review cards`.

### Section B exit

- [ ] Full gate (Section A's exit + 30); protected diff empty; `grep -rn "^from src.value\|^import src.value" src/notify`
  prints nothing. Exit row; ask the operator.

## Section C — The value process's own surfaces (Tasks 7–9) · model: sonnet · effort: high

**Reads:** rulings 14–17, 19–20; spec §6.9, §7.1, §8.5; `src/value/reevaluate.py`, `src/value/shadow.py` (lines 480–560,
the shadow path's call of `session_triggers`, as the pattern), `src/value/live.py` (lines 813–916), `src/value/service.py`
(lines 100–130, 404–448), `src/value/ticker_file.py`, `src/value/claude_reads.py` (`queue_read`), `src/common/value_inputs.py`
(lines 459–482), `src/ops/watchdog.py`, `src/common/config.py` (lines 747–770).

### Entry checks

- **C1.** Section B's exit row filled; go from the operator.
- **C2.** `grep -n "severity=max(r.severity for r in shadow_rows)," src/value/live.py` → `902:`;
  `grep -n "^def mirror_reevaluations" src/value/live.py` → `870:`; `grep -n "return reevaluate.session_triggers(" src/value/shadow.py`
  → `510:`; `grep -n "^def is_fresh" src/value/ticker_file.py` → `174:`; `grep -n "^def current_fingerprint_parts" src/common/value_inputs.py`
  → `459:`; `grep -n "^def run_checks" src/ops/watchdog.py` → `373:`; `grep -n "news_max_age_minutes: int = 30" src/common/config.py` → `764:`;
  `grep -n "^def queue_read" src/value/claude_reads.py` → one line.

Exit target: Section B's exit + 18.

### Task 7: Held names with no shadow entry get the whole §7.1 trigger set

**Files:** edit `src/value/live.py`, `src/value/service.py`; create `tests/test_value_held_triggers.py`.

- Fix line 902: `severity=max((r.severity for r in shadow_rows), key=_SEVERITY_RANK.__getitem__)` with
  `_SEVERITY_RANK = {"minor": 0, "major": 1}` at module level.
- New `live.held_reevaluations(vs, day, now, *, inputs: dict[str, HeldInputs], cfg, ruleset_version, ruleset_hash) -> int`:
  for each open `ValuePositionRow` with **no** open READY `value_shadow` entry on its symbol and list, call
  `reevaluate.session_triggers(day=day, after=<the position's last checked session, kept in value_book_state
  "held_checked">, move=..., filings=..., earnings=..., news=..., regime_stepped=..., last_reevaluation=<last held
  re-evaluation's session, else the position's opened date>, cfg=cfg.rules.reevaluation, kill=...)`, then
  `reevaluate.severity`/`joins` exactly as the shadow path does, opening or extending a `position_id`-keyed row
  (plan before = plan after = the position's plan: no level moves under `value`), and queue Claude's review for it as
  `mirror_reevaluations` does. `HeldInputs` is a dataclass of the same per-name inputs the shadow path builds
  (`Move`, `FilingEvent`s, earnings dates, `NewsVolume`, kill-trigger names); `service._book_night` builds them with
  the same helpers it already calls for the shadow record (read `shadow.py` around line 480–520 for where each comes
  from and reuse those calls; do not re-derive the residual).
- Call it from `_book_night` after `mirror_reevaluations`; add `"held_reevaluations": n` to its return.

- [ ] **Step 1: the failing tests** (six): `test_mirror_takes_the_higher_severity` (one major + one minor shadow row →
  `"major"`; red today); `test_a_held_name_without_a_shadow_entry_gets_an_earnings_trigger`; `..._gets_a_regime_trigger`;
  `..._gets_the_quiet_trigger_after_90_days`; `test_a_held_name_with_a_shadow_entry_is_left_to_the_mirror` (no second
  row); `test_held_triggers_move_no_level` (the position's `plan_json` and stop unchanged; a review read queued). **6.**
- [ ] Steps 2–4: red, code, gates (`tests/test_value_held_triggers.py tests/test_value_live.py tests/test_value_reevaluate.py
  tests/test_value_service.py -q`; ruff; mypy). Commit `feat(value): held names get every re-evaluation trigger; severity ranks`.

### Task 8: `value_snapshot`, `value_refresh`, `value_analyse`, and an `is_fresh` that can match

**Files:** edit `src/value/commands.py`, `src/value/ticker_file.py`, `src/value/store.py` (`freshness_json`),
`src/value/service.py` (writes `freshness_json` on every persist; exposes `score_one(vs, rs, symbol, *, now,
fingerprint: dict | None) -> Fingerprint`), `scripts/run_value.py` (the drain passes a research session to the
read-side handlers: `vcmd.apply(..., research=vi.research_read)`); append to `tests/test_value_commands.py`; create
`tests/test_value_freshness.py`.

- `ticker_file.freshness_key(parts: dict, regime: str, version: str, digest: str) -> str` (sha256 of the sorted JSON,
  16 hex) and `is_current(stored_freshness_json: str | None, parts: dict, regime: str, version: str, digest: str) -> bool`.
  `is_fresh` keeps its signature for the history path (ruling 16); the API and `/value NAME` use `is_current`.
- `value_snapshot` (ruling 19): set `last_viewed_at = now` on the file (create nothing when the name has no file and
  the payload has no fingerprint: queue a refresh instead); when the payload's fingerprint differs from the stored one,
  `score_one(..., fingerprint=payload)` and record `detail: "moved"` when its own fingerprint differs.
- `value_refresh`: `score_one(..., fingerprint=None)`, tag `lookup` when outside every universe, then the outbox posts
  a one-name card (`cards.ticker_card(view)`, add it in this task with one test).
- `value_analyse` (ruling 20): `queue_read(vs, symbol, kind="verdict", reason="request", now=now)`; `claude_off` when
  `value.claude.enabled` is false.

- [ ] **Step 1: the failing tests** (seven): `test_snapshot_sets_last_viewed_at` (and `followed_names` now returns the
  name); `test_snapshot_persists_exactly_the_input_set_it_carries`; `test_snapshot_records_moved_when_inputs_moved`;
  `test_refresh_scores_a_name_outside_the_universe_as_lookup`; `test_analyse_queues_a_request_read` (and `claude_off`);
  `test_live_allows_read_kinds` (moved here from Task 2); `test_a_file_is_current_only_when_the_cheap_parts_match`
  (`tests/test_value_freshness.py`: equal parts → current; a new bar → not; a pre-Part-6 file without `freshness_json`
  → not current). **7.**
- [ ] Steps 2–4: red, code, gates (`tests/test_value_commands.py tests/test_value_freshness.py tests/test_value_ticker_file.py
  tests/test_value_service.py tests/test_value_fence.py`; `py_compile scripts/run_value.py`; ruff; mypy). Commit
  `feat(value): snapshot, refresh and analyse intents; freshness on the cheap fingerprint`.

### Task 9: The watchdog checks the nightly run

**Files:** edit `src/ops/watchdog.py`, `src/common/config.py` (`WatchdogCfg.value_grace_hours: int = 26`),
`config/examples/settings.yaml` (the key under `watchdog:` with a comment), `src/common/value_view.py`
(`last_nightly_run`, from Task 5's interface); create `tests/test_watchdog_value.py`.

`value_check(now, *, grace_hours, expected: bool) -> Check`: `expected` is "the private `config/value.yaml` exists"
(`Path(...).exists()`, so a fork without the value book is never alerted); missing value.db → `Check("value", False,
"value: data/value.db missing - the value service never ran")`; the newest finished `nightly` run older than the last
weekday close (16:00 ET) + `grace_hours` → not ok with the age in words; else ok. `run_checks` appends it after the news
check (line 398). The watchdog imports `src.common.value_view` only (never `src.value`).

- [ ] **Step 1: the failing tests** (five): ok when tonight's run finished; alert when the last run is two sessions old;
  never-ran message on a missing value.db; not expected → no check at all; `last_nightly_run` reads only `kind='nightly'`
  with a `finished_at` (in `tests/test_value_view.py`). **5.**
- [ ] Steps 2–4: red, code, gates (`tests/test_watchdog_value.py tests/test_watchdog*.py tests/test_value_view.py
  tests/test_config_keys.py tests/test_private_config.py -q`; ruff; mypy). Commit `feat(ops): the watchdog checks the value book's nightly run`.

### Section C exit

- [ ] Full gate (Section B's exit + 18); protected diff empty; fences green. Exit row; ask the operator.

## Section D — The wheel side: VALUE NOTE, reason labels, the ledger split (Tasks 10–12) · model: sonnet · effort: high

**Reads:** rulings 9, 18, 21, 22; root `CLAUDE.md` "Analytics tiers" and "The `src/ledger/` fence"; `src/claude/runner.py`
(lines 184–440), `src/claude/ollama_runner.py` (lines 286–460), `src/claude/prompts/strategist.py` (lines 445–580),
`src/claude/prompts/roll.py` (lines 1–60), `src/claude/dossier_context.py` (the block pattern), `src/notify/formatters.py`
(lines 660–720), `src/api/routers/options.py` (lines 70–110), `src/engine/risk_engine.py` (only `grep -n "release_\|reasons.append"`
for the code list), `src/reporting/trade_ledger.py` (lines 120–200, 300–330, 800–860 and the ticker roll-up),
`src/common/schemas.py` (lines 1610–1660), `src/ledger/sheets_mirror.py`.

### Entry checks

- **D1.** Section C's exit row filled; go.
- **D2.** `grep -n "    dossier_block: str | None = None," src/claude/prompts/strategist.py` → `456:`; `grep -n "if dossier_block:" src/claude/prompts/strategist.py`
  → `576:`; `grep -n "^def build_roll_prompt" src/claude/prompts/roll.py` → `8:`; `grep -n "        dossier_block=dossier_block,$" src/claude/runner.py`
  → lines 225, 289, 387, 396, 406, 435 (six); `grep -n "^_REJECT_REASON_LABELS" src/notify/formatters.py` → `669:`;
  `grep -n "^_REASON_LABELS" src/api/routers/options.py` → `74:`; `grep -n "^LedgerBookName" src/common/schemas.py` → `1615:`;
  `grep -n "^def _merge_book\|^def _book_name" src/reporting/trade_ledger.py` → `134:` and `142:`.

Exit target: Section C's exit + 19.

### Task 10: The VALUE NOTE in the wheel's review prompts

**Files:** create `src/common/value_text.py` (pure renderer over plain values), `src/claude/value_context.py`
(`load_value_block(symbols, now) -> str | None`, reads `value_view.read_notes`); edit `src/common/value_view.py`
(`read_notes(symbols) -> dict[str, ValueNoteView] | None`), `src/claude/runner.py`, `src/claude/ollama_runner.py`,
`src/claude/prompts/strategist.py` (`build_prompt(..., value_block: str | None = None)`, placed right after the dossier
block), `src/claude/prompts/roll.py` (`build_roll_prompt(..., value_block=None)`, after the dossier block),
`tests/test_value_fence.py`, `tests/test_eval_skills.py` (if its enrichment list needs `src.claude.value_context`);
create `tests/test_value_note.py`.

The block (ruling 9), one per name the value book knows, at most 6 lines a name and 2,000 characters in all:

```
=== VALUE NOTE ===
GOOGL  quality growth: READY (Claude) · deep value: WAIT (Python)
  fair value $151.00 (Python) / $180.00 (effective, Claude's clamped) · margin 22% · value put ceiling $148.00
  value book holds 10 sh · next exit: sell half at $180.00 · re-evaluation open (major, 2026-11-03)
Context only. It never moves the Rules Engine; the value put ceiling is enforced by the system.
```

Unknown numbers print `n/a`. `runner.review_candidates` computes `value_block = load_value_block([c.underlying for c in
candidates], now)` when `value.prompt_note.enabled` and passes it in `kwargs` (both backends); `review_roll` does the
same for the rolled underlying. `load_value_block` never raises (a missing or unreadable value.db → `None`).

- [ ] **Step 1: the failing tests** (twelve): `value_text` — renders both lists and who decided; `n/a` for unknowns;
  the rule line is always last; truncates at 2,000 characters on a name boundary; a name the book does not know prints
  nothing; `value_view.read_notes` — one test on a seeded value.db, one on a missing file (→ `None`); prompts —
  `build_prompt` places the block after the dossier block and before `=== TRADE CANDIDATES ===`; `build_roll_prompt`
  carries it; `runner.review_candidates` passes it to the CLI path and to the Ollama path (fake both, assert the prompt
  text); `value.prompt_note.enabled: false` → no block; fence `test_claude_reaches_value_db_only_through_the_view`
  (`ast` over `src/claude/`: no `src.value`; `src.common.value_view` / `value_text` only from `value_context.py`). **12.**
- [ ] Steps 2–4: red, code, gates (`tests/test_value_note.py tests/test_strategist*.py tests/test_roll_prompt*.py
  tests/test_runner*.py tests/test_ollama*.py tests/test_value_fence.py tests/test_eval_skills.py tests/test_regime_fence.py -q`
  — find the exact existing prompt-test file names with `ls tests | grep -i "prompt\|runner\|ollama"` first); ruff; mypy.
  Commit `feat(claude): the VALUE NOTE in the trade review, roll review and /scan NAME`.

### Task 11: Words for the Part 5 reason codes

**Files:** edit `src/notify/formatters.py` (line 669), `src/api/routers/options.py` (line 74); create
`tests/test_reason_labels_value.py`.

- [ ] Every reason code ruling 21 names gets a plain phrase in both maps (the same words in both; e.g.
  `gross_notional_cap`: "would pass the account's gross exposure cap (both books)", `combined_name_cap`: "this name across
  the wheel and the value book would pass its cap", `book_attribution_mismatch`: "the value book's share count for this
  name is under review", `value_book_unreadable`: "the value book could not be read, so new puts wait",
  `above_value_ceiling`: "strike above the value book's price worth paying", `release_*`: one phrase each). Two tests:
  every `release_*` and value code returned by `src/engine/risk_engine.py` (found with `ast`) is in both maps; the two
  maps agree on those codes. **2.** Gates: the two files' existing suites, ruff, mypy. Commit
  `fix(notify,api): plain words for the value book's reason codes`.

### Task 12: Value fills split out of the whole-account ledger

**Files:** edit `src/common/schemas.py` (line 1615), `src/reporting/trade_ledger.py`, `src/ledger/sheets_mirror.py`
(the book column writes the word, whatever it is; check whether it already does and leave it if so); create
`tests/test_trade_ledger_value_book.py`.

- [ ] `LedgerBookName = Literal["system", "manual", "spreads", "value"]`; `_merge_book`: spreads, then value, then
  system, else manual; `_book_name` keeps `value`; the ticker roll-up's wheel-adjusted cost basis and stock lots skip
  value trades (account totals unchanged). Five tests: a `book="value"` execution's trade carries `book == "value"`; a mixed
  order merges spreads first, then value; a shared name's wheel cost basis ignores value buys and sells; the account's
  realised total still counts the value sale; `GET /ledger/trades?book=value` filters (the route's `book` parameter type
  comes from `LedgerBookName`; regenerate the OpenAPI contract and `web/lib/api-types.ts`). **5.** Gates:
  `tests/test_trade_ledger*.py tests/test_ledger*.py tests/test_web_fence.py tests/test_openapi_current.py -q`; ruff; mypy.
  Commit `feat(reporting): value fills are their own book in the trade ledger`.

### Section D exit

- [ ] Full gate (Section C's exit + 19); protected diff empty (`src/ledger/` only `sheets_mirror.py` if it changed); fences
  green. Exit row; ask the operator.

## Section E — The read API and the backend docs (Tasks 13–15) · model: sonnet · effort: high

**Reads:** rulings 19, 23–28; spec §6.9, §9.7 last bullet, §10, §11, §16, §18; `src/api/spreads_db.py` (the pattern to copy),
`src/api/routers/spreads.py`, `src/api/models/` (one spreads model file), `src/api/routers/pnl.py`, `src/api/spread_inputs.py`,
`src/reporting/pay.py`, `src/reporting/day.py` (lines 40–80, 730–800), `src/api/routers/research.py` (lines 580–700: the
materialisation budget and ingest enqueue), `src/api/news_db.py`, `docs/web/api.md`, `tests/test_web_fence.py` (lines 248–340).

### Entry checks

- **E1.** Section D's exit row filled; go.
- **E2.** `ls src/api/value_db.py src/api/routers/value.py` → both missing; `grep -n "app.include_router(spreads.router)" src/api/main.py`
  → `66:`; `grep -n "^PayStrategy" src/reporting/pay.py` → `23:PayStrategy = Literal["all", "csp", "cc", "spread"]`;
  `grep -n "^class SpreadPayInput\|^class SpreadDayInput" src/reporting/pay.py src/reporting/day.py` → `pay.py:27`, `day.py:50`;
  `grep -n "def test_only_spreads_db_opens_the_spreads_file_in_the_api" tests/test_web_fence.py` → `330:`.

Exit target: Section D's exit + 27.

### Task 13: `src/api/value_db.py` and the value routes

**Files:** create `src/api/value_db.py` (copy `spreads_db.py`'s shape: `_resolve_path` from `value_db_url_abs`,
`mode=ro&uri=true`, `value_read_session()` yielding `None` when the file is missing, plain SQL helpers returning plain
dicts, `_columns_of` for migration-tolerant reads), `src/api/models/value.py`, `src/api/routers/value.py`; edit
`src/api/main.py` (include after line 66), `tests/test_web_fence.py`, `tests/test_value_fence.py`, `docs/web/openapi.json`,
`web/lib/api-types.ts`; create `tests/test_api_value.py`.

Routes (ruling 23), all `CurrentUser`-guarded like the spreads routes, all read-only:
- `GET /value/top?list=deep_value|quality_growth` → `ValueTopResponse{available, as_of, items[≤10]: {symbol, list, verdict,
  decided_by: "claude"|"python", price, fair_value, entry_ceiling, stop, half_sell, mos, reasons[3], put_ceiling,
  age_days}}`, READY first then WATCH then WAIT, by rank.
- `GET /value/book` → `ValueBookResponse{available, as_of, enabled, ceiling_usd, used_usd, positions[...], proposals[{id,
  kind, symbol, shares, price, reason, cause, needs_tap, status, expires_at, fingerprint}], funding[...], breakers{trend,
  drawdown, drawdown_pct, trim_offered, trim_episode}, release_max_closes}` (`release_max_closes` from
  `get_config().value.book.release.max_closes_per_request` or wherever Part 5 put it — check).
- `GET /value/positions?status=open|closed` → rows with `symbol, list, shares, avg_cost, mark, opened_at, next_exit:
  {kind, level}, realised_usd`.
- `GET /value/{symbol}` → `ValueTickerResponse{available, computed: "stored"|"now"|"pending", as_of, age_days, file:
  {...the scorecard summary, gates with value and threshold, methods with the median marked, timing, verdicts per list,
  effective verdicts with who decided}, claude: {verdict, fair_value, drivers[{name, chosen, clamped_to, bound}],
  cap_applied, notes[{kind, text}], kill_triggers[{name, distance_pct}], facts[{text, quote, filing}], read_at,
  source: "claude"} | null, reevaluations[{session, severity, triggers, plan_before, plan_after, review_state}], plan |
  null}`. Task 14 adds the on-open recompute behind `computed`.

Fences (ruling 28): `test_only_value_db_opens_the_value_file_in_the_api` (copy line 330's test: only `value_db.py` names
`value_db_url_abs` in `src/api/`, and it says `mode=ro`); `test_the_api_imports_only_scorecard_and_schemas_from_value`
(`ast` over `src/api/`: every `src.value*` import is `src.value.scorecard` or `src.value.schemas`; `src.value_ai` never);
`test_the_api_still_writes_exactly_one_table` unchanged and green.

- [ ] **Step 1: the failing tests** (fourteen): each route on a seeded `tmp_path` value.db (top ordering; book with a
  proposal's fingerprint equal to `value_commands.proposal_fingerprint` of the row; positions open/closed; ticker with
  Claude's block labelled `source: "claude"` and `null` when no read), each route with value.db missing →
  `available: false` and 200, unknown symbol → 404, auth required (one parametrised test), the two fences, and
  `test_openapi_current`. **14.**
- [ ] Steps 2–4: red, code, regenerate the contract, gates (`tests/test_api_value.py tests/test_web_fence.py
  tests/test_value_fence.py tests/test_openapi_current.py -q`; ruff; mypy). Commit `feat(api): the value book, read-only, through value_db.py`.

### Task 14: Home's value inputs and the on-open recompute

**Files:** edit `src/reporting/pay.py`, `src/reporting/day.py`, `src/api/routers/pnl.py`, `src/api/value_db.py`
(`read_value_pay_inputs`, `read_value_day_inputs`); create `src/api/value_lookup.py`; edit `src/api/routers/value.py`
(`GET /value/{symbol}` calls the lookup); create `tests/test_reporting_value.py`, `tests/test_api_value_lookup.py`.

- `ValuePayInput(closed_at, symbol, realised_usd, commissions_usd | None)` and `ValueDayInput(at, symbol, side, shares,
  price, reason, cause, proposal_id)` (frozen dataclasses, plain values; `src/reporting/` imports nothing from `src.value`
  and nothing from `src.api`). `PayStrategy` gains `"value"`. `build_month_pay(legs, spreads, values=(), ...)`: with
  `strategy="value"` only value lines; with `"all"` a separate "Value book, realised" line that the income target does not
  count (ruling 26). `build_day_trades` and `build_month_calendar` gain `values=()` likewise: a value fill is a trade
  ("Bought 10 GOOGL", "Sold 5 GOOGL", with the proposal's reason in words and `cause`; Claude's cause labelled).
- `GET /pnl/month|day|calendar` accept `strategy=value` and pass `read_value_*_inputs` (an absent value.db → no value lines
  and `value_available: false` on the response; never mixed with the spreads flag).
- `value_lookup.lookup(symbol, *, now) -> ValueTickerResponse` (ruling 24): stored and current (`ticker_file.is_current`
  is in `src.value.ticker_file`, which the API may **not** import: re-implement `freshness_key`'s 6-line hash in
  `value_lookup.py` and pin both with one test that they agree — cheaper than widening the fence); otherwise compute with
  `src.value.scorecard.build_scorecard` over `src.common.value_inputs` inside the materialisation budget, enqueue
  `value_snapshot` through `src.api.commands.submit` (the API's one write path) with the fingerprint, and answer
  `computed: "now"`; missing filings → enqueue the research ingest exactly as `routers/research.py` does and answer
  `pending`. It never opens value.db for writing.

- [ ] **Step 1: the failing tests** (thirteen): pay — value-only month; "all" keeps the value line separate and out of the
  target's sum; day — a value buy and a Claude-caused sale labelled; calendar — a value sale's realised on its day; routes —
  `strategy=value` on the three routes, value.db missing → `value_available: false`; lookup — fresh file → `stored`, no
  intent; stale → `now`, one `value_snapshot` row carrying the fingerprint; missing filings → `pending` and one ingest job;
  past the budget → the stored file; the freshness hash agrees with `ticker_file.freshness_key`; the lookup writes nothing to
  value.db (file mtime unchanged). **13.**
- [ ] Steps 2–4: red, code, regenerate the contract, gates (`tests/test_reporting_value.py tests/test_api_value_lookup.py
  tests/test_reporting*.py tests/test_api_pnl*.py tests/test_web_fence.py tests/test_value_fence.py tests/test_openapi_current.py -q`;
  ruff; mypy). Commit `feat(api,reporting): the value book on Home's money; a ticker file fresh on open`.

### Task 15: The backend docs

**Files:** `ARCHITECTURE.md`, `SETUP.md`, `README.md`, root `CLAUDE.md`, `docs/web/api.md`, `docs/web/commands.md`,
`config/examples/value.yaml` comments, `STATUS.md` (the Part 6 backend lines; Task 20 finishes it).

- [ ] Per the root `CLAUDE.md` doc-update table: ARCHITECTURE.md folder guide rows for `src/common/value_commands.py`,
  `src/common/value_text.py`, `src/claude/value_context.py`, `src/value/{commands,cards,outbox,digest}.py`,
  `src/api/{value_db,value_lookup}.py`, `src/api/routers/value.py`, `src/api/models/value.py`; the src/notify commands
  table (`/value` three forms, the `vbook:` buttons); the config section (`value.telegram`, `value.prompt_note`,
  `watchdog.value_grace_hours`); the data-flow note "value taps: Telegram/web → app_commands → the value process → value.db
  → clientId 31". SETUP.md "Using the Telegram bot" commands table and §19 (taps, the trim card, the digest, the
  watchdog line). README.md Telegram commands table (`/value`). `docs/web/api.md`: the four value routes and
  `strategy=value`. **Root `CLAUDE.md`:** in "The web layer and the trading database", the sentence "Every web action is an
  intent drained by `approval_service`" becomes "Every web action is an intent drained by `approval_service`, **except the
  value book's kinds (`src/common/value_commands.VALUE_KINDS`), which the value process drains (spec §9.7): `approval_service`
  only forwards a Telegram tap as the same intent and its drain never reads them**"; the value fence section gains the
  three new allowances (the entrypoint's lazy `src.storage.app_commands`/`src.storage.db`; `value_view`'s `json` and
  `value_commands`; `src/claude/value_context.py` → `value_view`/`value_text`) and the sentence "the API imports from
  `src.value` only `scorecard` and `schemas`" with its test name. No code. Gate: `python -m pytest tests/test_docs*.py -q`
  if such a test exists (check `ls tests | grep -i doc`), else none. Commit `docs: value book Part 6 - taps, cards, /value, the read API`.

### Section E exit

- [ ] Full gate (Section D's exit + 27 = baseline + 122, recompute); protected diff empty; fences green;
  `git diff --stat main...HEAD -- web` lists only `web/lib/api-types.ts`. Exit row; then the backend whole-branch review.

## Whole-branch review (backend) · model: opus · effort: high, then one sonnet fix pass · effort: high

After Section E, before any web section. Prompt for the opus subagent:

> Review branch `feat/value-book-6` (worktree `.claude/worktrees/value-book-6`) against `main` with
> superpowers:requesting-code-review, read-only, no commits. Read root `CLAUDE.md` (core invariant, the value
> fence, the web layer), the plan's Rulings, Global Constraints and Review Focus, and spec §6.9, §7.1, §9.6, §9.7.
> Check end to end: Telegram tap / web click → `app_commands` → the value process's drain → value.db → the RTH
> cycle's send-time gate → clientId 31; that `approval_service`'s drain can never apply or fail a value kind; that a
> crash at any point leaves no double decision; that a stale card, a live-mode tap, an expired proposal and a second
> tap are refused; that the trim sells only filled shares, at half, and is still sell-capped at send time; that the
> VALUE NOTE reaches prompt text only; that the API never writes value.db and imports only `scorecard` and
> `schemas` from `src.value`; that `value_snapshot` persists exactly its input set; that held-name triggers move no
> level; that the ledger split leaves account totals unchanged. Run the full gate. Report Critical / Important /
> Minor findings with file:line and a one-line fix each; disprove nothing you have not run.

Then one sonnet subagent fixes every Critical and Important finding in one commit (`fix(value): Part 6 review
fixes`), full gate, and the orchestrator records the row and **asks the operator** whether to run F, G, H, I (any
subset) or go straight to J.

## Section F — Web: Home's Value card and the value decide flow (Task 16) · model: sonnet · effort: high · *web-overhaul-sensitive*

> **Touches:** Home (`features/home/HomePage.tsx`'s grid, overhaul Part 1 and the 2026-10-15 follow-ups) and the
> decide-flow pattern of Part 2 (`ReviewSheet`, `DecideControls`, read, not edited). Cut cleanly by not running it:
> nothing else reads `components/value/`.

**Reads:** `web/DESIGN.md` (Overview, Colors, Layout, Components, Do's and Don'ts, Surfaces → Home), `web/CLAUDE.md`,
`features/home/HomePage.tsx`, `features/home/ProposalCard.tsx`, `features/home/ReviewSheet.tsx`,
`components/options/DecideControls.tsx` (the pattern; do not edit), `lib/commands.ts`, Section E's `GET /value/book`
and `GET /value/positions` in `web/lib/api-types.ts`; rulings 10, 30, 31.

### Entry checks

- **F1.** The backend review fix row is filled and the operator chose to run F. `cd web && npx vitest run && npx tsc --noEmit
  && npm run lint` green: record the **vitest baseline**. `grep -n "PositionsCard strategy={strategy}" web/features/home/HomePage.tsx`
  → `53:`. `grep -n "\"/value/book\"" web/lib/api-types.ts` prints one line.
- **F2.** The scratch-copy build is green (never inside `web/`):

  ```bash
  S="$(mktemp -d)/web" && rsync -a --exclude node_modules --exclude .next web/ "$S/" \
    && ln -s "$PWD/web/node_modules" "$S/node_modules" && (cd "$S" && npm run build)
  ```

### Task 16: The Value card on Home, and approving a value proposal from it

**Files:** create `web/components/value/{ValueCard,ValueDecide,ValueProposalRow,types,format}.tsx|ts` and their tests;
edit `web/features/home/HomePage.tsx` (one card slot); `web/DESIGN.md` (Surfaces → Home: a "Value card" paragraph, through
da-vinci); `web/CLAUDE.md` (a `components/value/` entry).

- [ ] **Step 1: invoke `da-vinci`** (`document`/`shape` as it decides; DESIGN.md is ratified, so it reads it rather than
  re-asking). Record its sync check. No new token, colour, font, radius or elevation without the operator.
- [ ] **Step 2: the failing tests** (vitest, ≈14): the card renders "Value book" with the ceiling used as a sum ("$7,200
  of $30,000"), each open position with its next exit level in words ("sell half at $180.00"), and today's proposals;
  `available: false` → one sentence ("The value book has not written anything yet"), never "none"; `enabled: false` → "The
  value book is off" in words; a tap-waiting proposal shows Review, an auto one shows "Approved by the system"; the
  breakers as `StatusWord`s (flag tone) with words; the trim line when `trim_offered` (no button, ruling 10: "Trim to half
  is offered in Telegram"); `ValueDecide`: Approve opens `ConfirmAction` whose sentence for a buy names the possible
  release (ruling 31) and for a Claude-caused sale says "Only Claude's number makes this sale"; confirm sends exactly one
  `submitCommand("value_approve", {proposal_id, fingerprint})`; Reject sends `value_reject`; in-flight disables both;
  a `CommandReceipt` follows the command; a failed `stale_proposal` reads "This card is out of date; refresh it"; the
  in-flight command survives a reload (`localStorage` key `value:<id>` through `lib/commands.ts`'s persistence helpers);
  unknowns are hatched `n/a`; Claude's words never sit on a button.
- [ ] **Step 3: code**, composed from `Card`, `Stub` (the ceiling sum), `StatusWord`, `Disclosure`, `Button`, `ConfirmAction`,
  `CommandReceipt`. The card sits on Home after `PositionsCard` (line 53) and shows under the strategy filters "all" and
  (Section I) "value"; lime only on Review. The decide flow lives in `components/value/`, so the `web/features` command
  grep stays as it is.
- [ ] **Step 4: gates** vitest (baseline + ≈14), tsc, lint; da-vinci `lint.py` on `web/components/value` and
  `web/features/home`; `design_md_check.py web/DESIGN.md`; the protected-component diff empty; the scratch build (F2);
  then da-vinci `critique` and `audit` at 1440px and 390px, light and dark, against a mock of `GET /value/book` (write the
  mock in the scratchpad, never in the repo) and fix what they find, each fix with a test. Commit
  `feat(web): the Value card on Home and the value decide flow`.

## Section G — Web: the stock page's value block (Task 17) · model: sonnet · effort: high · *web-overhaul-sensitive*

> **Touches:** `/stock/[symbol]` (`app/stock/[symbol]/page.tsx`), which belongs to web overhaul Part 4 (Research, not yet
> planned): the block is one self-contained component mounted with one line, so Part 4 can move or restyle it.

**Reads:** `web/DESIGN.md` (Surfaces → Research, What Claude knows for how Claude's words are labelled), `app/stock/[symbol]/page.tsx`,
`features/market/NameNotes.tsx` (the labelled-prose pattern), `components/stock/SectionShell.tsx`, Section E's `GET /value/{symbol}`;
spec §10 "Stock page"; ruling 30.

### Entry checks

- **G1.** Operator chose G; web gates green (record vitest). `grep -n "<NameNotes symbol={upper} />" "web/app/stock/[symbol]/page.tsx"` → `64:`.

### Task 17: The value block on the stock page

**Files:** create `web/features/stock-value/{ValueBlock,WorthBlock,BusinessBlock,SizeBlock,ClaudeBlock,AnalyseButton,types,format}.tsx|ts`
and tests; edit `app/stock/[symbol]/page.tsx` (one mount after `NameNotes`); `web/DESIGN.md` (Surfaces → Research: a
"Value block" paragraph, through da-vinci); `web/CLAUDE.md`.

- [ ] **Step 1: da-vinci** as in Task 16.
- [ ] **Step 2: the failing tests** (≈12): verdict first (state per list, who decided it in words, fair value vs price, margin
  of safety, the plan in one sentence "stop $X · sell half at $Y · then trail" for a held name); the three question blocks of
  spec §10 (*Is the business still doing its job?* gates with value and threshold, what changed, kill triggers and their
  distance; *What is it worth?* Python's methods with the median marked, then Claude's fair value with its drivers, any clamp
  and the 1.5x cap, Python's and Claude's verdicts side by side when they differ; *How much, and when?* timing, tranches, what
  the regime asks); the re-evaluations as a short dated list; the file's age, and `computed: "now"` says "Worked out just now
  from the latest filings" while `pending` says "Fetching the filings" and polls (react-query `refetchInterval` while pending,
  as the stock page's other sections do); every piece of Claude's text labelled ("Claude's thesis", "Claude's bear case",
  "Claude's review"), with the scorecard date it was written against; "Run Claude's analysis" sends `value_analyse` through a
  confirm-less one-click flow with a `CommandReceipt` (it changes no order state), and `claude_off` reads "Claude's reads are off
  in config"; `available: false` → one sentence; `n/a` hatched for unknowns; no em dash.
- [ ] **Step 3: code; Step 4: gates and the da-vinci finish** exactly as Task 16 Step 4 (mock `GET /value/GOOGL` in the
  scratchpad). The command flow for "Run Claude's analysis" lives in `features/stock-value/AnalyseButton.tsx`: extend the Global
  Constraints' command grep allowance to name that one file (record the ruling; cost if wrong: none). Commit
  `feat(web): the value block on the stock page`.

## Section H — Web: the Research "Top opportunities" strip (Task 18) · model: sonnet · effort: high · *web-overhaul-sensitive*

> **Touches:** `/research` (`app/research/page.tsx`, above `WatchlistTable` at line 30), web overhaul Part 4's surface.

**Reads:** `web/DESIGN.md`, `app/research/page.tsx`, `components/ui/SegmentedControl.tsx`, `features/stock-value/` (if G ran: reuse
its `format.ts`; if not, H carries its own), Section E's `GET /value/top`; spec §10 "Research page".

### Entry checks

- **H1.** Operator chose H; web gates green. `grep -n "<WatchlistTable />" web/app/research/page.tsx` → `30:`.

### Task 18: Top opportunities

**Files:** create `web/features/research/{TopOpportunities,OpportunityCard,types}.tsx|ts` and tests; edit `app/research/page.tsx`;
`web/DESIGN.md` (Surfaces → Research), `web/CLAUDE.md`.

- [ ] **Step 1: da-vinci.** **Step 2: the failing tests** (≈8): two tabs (Deep value, Quality growth) as a `SegmentedControl`;
  up to ten cards each, READY first; each card has the name, list and verdict with who decided it, one bar with price, fair value,
  the entry ceiling, the stop and the half-sell marked (labelled points, numbers visible; no animation), the margin of safety,
  three plain reasons, "Buy shares" only as a link to the stock page's value block (no order from the strip), "Sell a put up to
  $C" only when `put_ceiling` and a passing CSP candidate exist (a link to Trades → Assessed for that name), and the file's
  age; Claude's one-line note only when present and labelled; `available: false` → one sentence. **Step 3: code; Step 4: gates
  and finish** as Task 16. Commit `feat(web): Top opportunities on Research`.

## Section I — Web: the `value` kind across Home (Task 19) · model: sonnet · effort: high · *web-overhaul-sensitive*

> **Touches:** the strategy switcher (`lib/strategy.ts`, Parts 1–2), `PayCard`, `PositionsCard` / `PositionRowItem`,
> `TodayTrades` / `TradeCard`, the realised calendar (Part 1 follow-ups), Activity's Pay (Part 3). The most entangled web
> section: run it last, or let the web-overhaul re-plan take it.

**Reads:** `web/DESIGN.md` (Home, Activity), `lib/strategy.ts`, `features/home/{HomePage,PayCard,PositionsCard,positions.ts,TodayTrades,trades.ts,calendar.ts}`,
`features/activity/PayMonth.tsx`, Section E's `strategy=value` and `GET /value/positions`; rulings 25–27.

### Entry checks

- **I1.** Operator chose I; web gates green. `grep -n "export type StrategyKind = \"csp\" | \"cc\" | \"spread\";" web/lib/strategy.ts`
  → `2:`; `grep -n "STRATEGY_FILTERS" web/lib/strategy.ts` → `5:`.

### Task 19: A `value` kind wherever Home distinguishes kinds

**Files:** edit `web/lib/strategy.ts` (`"value"` kind, label "Value", eyebrow), `features/home/*` (the cards accept it),
`features/activity/PayMonth.tsx` (the separate "Value book, realised" line), and the existing tests in place where they
enumerate kinds; `web/DESIGN.md` Home and Activity paragraphs; `web/CLAUDE.md`.

- [ ] **Step 1: da-vinci.** **Step 2: the failing tests** (≈12): the switcher shows Value with its pending count from
  `GET /value/book`; Pay with Value selected shows only value lines and no target meter ("The income target counts options
  income only"); Pay with All shows the value line apart from premium and the meter's sum unchanged (ruling 26); Positions
  with Value lists `GET /value/positions` rows (shares, average cost, next exit level) and with All adds them as a "Value
  book" group, never merged into the wheel's share rows on a shared name (the two counts stay apart, spec §9.2); Done today
  shows value fills as trade cards ("Bought 10 GOOGL") with Claude's cause labelled; the realised calendar counts a value sale
  on its day, labelled; an unreadable value book says so, never "none". Every existing Home and Activity test passes
  unmodified except where it enumerates the kinds (edit only that enumeration; record each file). **Steps 3–4:** code; gates
  and finish as Task 16. Commit `feat(web): the value book as a kind across Home`.

## Section J — Spec revision 5, STATUS, the finish (Task 20) · model: sonnet · effort: medium

### Entry checks

- **J1.** Every earlier section is done or recorded as cut; full gates green (Python; and web if any of F–I ran).

### Task 20: Revision 5 and the closing docs

- [ ] Append to the spec `## 22. Revision 5 — 2026-11-04: the operator's Part 6 answers`: the three answers (rulings 1, 3, 9)
  and the accepted defaults (rulings 12, 13, 15, 30), each one sentence with its section reference; amend §9.7's bullet to
  name `VALUE_KINDS` and the trading drain's skip.
- [ ] `STATUS.md`: a "Built (date — value book Part 6)" entry (what was built, which web sections ran or were cut, known
  limitations: taps act at the next RTH cycle; the trim button is Telegram only; the on-open recompute needs filings in
  research.db; the VALUE NOTE is prompt text only; Part 5's still-open list carried); the "Value book Part 6" row in the
  not-built table removed; the live-verification list gains "a real Telegram tap on a value card in paper reaches the value
  process and the next RTH cycle sends; the trim card's button; the digest's first night; the watchdog's value line".
- [ ] `web/CLAUDE.md` and `web/DESIGN.md` consistent with whichever of F–I ran (`design_md_check.py` exit 0).
- [ ] Full gate: `python -m pytest -q` (baseline + 122 + the review fix pass's tests, recompute), `ruff check .`, `mypy src`,
  `py_compile` of `scripts/run_value.py`, `scripts/value_book.py`, `scripts/healthcheck.py`; web gates and the scratch
  build if any web section ran; protected diff empty; fences green. Commit `docs: value book Part 6 - spec revision 5, status`.
  Then the final whole-branch review (opus, the same prompt with F–I added if they ran) and one fix pass, and **ask the
  operator before merging or pushing**.

## Operator to-dos

**Before execution:** none beyond the HANDOFF's (the restart and a few nights of Part 5's paper record are welcome but not
required: every Part 6 test fakes the broker and Telegram).

**After the merge:**
1. Re-copy the value example's new blocks into the private `config/value.yaml` (`telegram:`, `prompt_note:`) and
   `watchdog.value_grace_hours` into `config/settings.yaml` (defaults load without them; the copy is for visibility).
2. `./ibkr restart` (the value process gains its command poll; `approval_service` gains the `vbook:` handler and `/value`;
   the API gains the value routes). Restart the trading service before the API, as with every web change.
3. In paper with `value.book.enabled` still false: `/value`, `/value GOOGL`, `/value GOOGL analyse`; check the reply and that the
   value thread receives the refreshed card.
4. When the book is on (after Part 5's fault drills): approve one proposal from Telegram and one from the web; confirm the next
   RTH cycle sends it on clientId 31 and `decided_by` reads `telegram` / `web`.
5. Read the first digest and the watchdog's value line; confirm a stale card's tap answers "out of date".

## Self-review (run by the plan's author, 2026-11-04)

- **Spec coverage.** §6.9 fresh on search and the follow window → Tasks 8, 14; §7 review cards → Task 6; §7.1 cards, digest, held
  triggers → Tasks 4, 6, 7; §8.5 request priority → Task 8; §9.6 trim → Task 3; §9.7 taps drained by the value service → Tasks 1, 2,
  5; §10 Telegram → Tasks 4–6, Research/stock/Home → Tasks 16–19; §11 `ValuePayInput` and the ledger tag → Tasks 12, 14; §16
  fences → Tasks 1, 2, 5, 10, 13; §18 docs → Tasks 15, 20. Part 5's moved items: ruling 14 → Tasks 1–2, 4–5; ruling 15 → Task 3;
  ruling 22 → Task 7; ruling 25 → Task 1; reason labels → Task 11; ledger split → Task 12. Part 4's moved items: VALUE NOTE →
  Task 10; analyse → Tasks 5, 8, 17; Claude's display → Task 17. Parts 2–3: `last_viewed_at` → Task 8; digest → Task 6;
  watchdog → Task 9; `is_fresh` → Task 8.
- **Not prototyped.** Unlike Parts 1–5 this plan was not run in a scratch copy. What is given whole (Tasks 1–3's modules, the
  drain, the forwarder) was checked against the quoted signatures (`enqueue_command`, `pending_commands`, `mark_applied`,
  `mark_failed`, `decide`, `propose`, `sell_shares`, `value_session`'s commit-on-exit, `get_config().is_live`) but not executed;
  the rest is interface plus named tests. The entry checks pin every line the plan edits, and a false fact stops the section
  (rerun at xhigh). Expect small deviations (fixture names, exact existing test-file names) and record them as rulings.
- **Placeholders.** `outcome_line`'s body in Task 2 is a one-line return, replaced in Task 4 (stated). `TRIM_TTL_HOURS = 30` is a
  plan number (stated). The release-close count's config path is to be confirmed in Task 13 (stated).
- **Type consistency.** `VALUE_KINDS` / `VALUE_ORDER_KINDS` are `frozenset[str]` everywhere; `CommandKind` members equal them
  (Task 1 test); the callback format is produced and parsed only by `value_commands`.
- **Risk.** The one trading-behaviour change is that a tap from Telegram or the web now approves a value proposal (before: the CLI
  only); everything downstream (the gate at send time, the sell cap, capital release's own two gates) is Part 5's, unchanged.
