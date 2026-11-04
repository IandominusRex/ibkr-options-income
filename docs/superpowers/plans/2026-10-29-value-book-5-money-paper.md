# Value Book, Part 5: Money in Paper — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan **section by section** (one subagent per section, never per task — see "Execution model"). Every section opens with **entry checks** the orchestrator runs itself before it spawns the section's subagent. Each section carries a **model** and an **effort** label; the orchestrator passes both when it spawns. One task (Task 5) changes one generated line in `web/lib/api-types.ts`; its subagent invokes the `da-vinci` skill first (the operator's rule for any `web/` change) and nobody runs `npm`, `next build` or `next dev` inside `web/`. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Written against Part 4's PLAN, not its merged code (2026-10-30).** This plan and
> `docs/superpowers/plans/2026-10-29-value-book-4-claude-analyst.md` were written together. Every
> line this plan quotes from Part 4 is quoted as Part 4's plan creates it. **Before Section A
> starts, the orchestrator reconciles this plan with Part 4's Progress log and its operator rulings
> (entry check A1)**; every later section's entry checks re-grep the Part 4 lines they edit against
> the merged tree.

**Goal:** Stage 3 of the value book, **paper only** (spec §9 as amended by revision 4 of
2026-10-30): the value book buys READY names in tranches sized by the effective margin of safety,
holds them under the pre-registered `value` exit policy and sells on its signals, on its own
clientId 31, with every share attributed by `orderRef` and two independent counts; it holds **no
cash back** — when a valid buy cannot be funded, the wheel **closes cash-secured puts at breakeven
or better through the Rules Engine** to release the capital, then the buy is re-gated and sent.

**Architecture:** On the wheel's side, a read-only window (`src/common/value_view.py`, SQLite
`mode=ro`, plain SQL) and the attribution rule (`src/common/books.py`) are the only way the engine,
the strategies, execution and the IBKR readers learn of the book; the wheel's own share count W
comes from the broker-truth ledger (`src/storage/wheel_shares.py`), never "broker minus value".
`get_positions` gives the wheel only its own shares; the Rules Engine counts the value book's
stock and approved buys against the wheel's excess liquidity, a gross notional cap and a combined
name cap, refuses opens on a frozen name, and gates a new kind of close — the capital release
(`risk_engine.validate_release`, `capital.select_releases`), run by `src/execution/capital_release.py`
in the trading process's intraday loop through the wheel's own close path. On the value side,
`src/value/` gains a pure gate (`risk.py`) and sizing (`sizing.py`), the book's rows
(`book.py`: orders, positions, proposals, funding requests, the reconcile), an executor
(`executor.py`, `LimitOrder` at mid, `orderRef = "value:<id>"`, the row written before
`placeOrder`), the night's proposals and the RTH cycle (`live.py`), the IBKR side (`stage3.py`,
clientId 31) and plain notifications (`notify.py`). The ledger carries `orderRef` and tags value
fills. Nothing an LLM produced reaches an order except through the effective verdict and fair
value Part 4 computed and clamped, and in live not at all (the book idles in live).

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy 2 (SQLite, WAL; `mode=ro`), `sqlite3`
(read-only), ib_async (clientId 31; `qualifyContractsAsync`, `req_fresh_mkt_data`, `LimitOrder`),
python-telegram-bot (plain messages), pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-10-28-value-swing-book-design.md` (revisions 1–3, and
revision 4 — §21 — which Task 15 adds). Part 5 implements §9 as amended (§9.1's put ceiling,
§9.2's attribution with its fail-closed reads and seven fault drills, §9.3 as amended, §9.4's
gate, §9.5's sizing and tranches, §9.6's cycle rules, §9.7's executor and process), §7's live exits
(`rules.exits.live_policy`) as orders, §7.1's held-position steps (the hourly check of triggers 1
and 4, "pause adds", Claude's review queued), §11's rows and ledger tag, §13 failure modes 1 and 4,
and §16/§18 for what Part 5 builds. The operator's 2026-10-30 decision on capital release (HANDOFF
§3) is binding. Part 4's plan and Progress log are the ground truth for the code Part 5 builds on.
## Execution model

| Section | Tasks | Model | Effort | Why this model | Why this effort |
|---|---|---|---|---|---|
| **Orchestrator** (the main session) | — | **sonnet** | **high** | Runs entry checks, spawns, verifies, asks the operator; writes no product code. | It is the one reader of every subagent's report and the protected-file diff; a missed red gate ships. |
| **A — Config, the book's tables, the read-only view, the attribution rule** | 1–3 | **sonnet** | **high** | Every line given; the risk is wiring into `config.py`, `value.db` and `books.py`, which the wheel imports. | `books.py` and `value_view.py` are read by the live wheel's engine; a slip there changes the wheel. |
| **B — The Rules Engine and capital release** | 4–6 | **opus** | **high** | Rules-Engine edits (E1–E3, E5–E7 of the rulings), the operator's capital-release decision, the trading process's intraday loop. | The only section that changes how the live wheel gates, sizes and closes; HANDOFF's rule for Rules-Engine sections. |
| **C — The value gate, the book, the executor** | 7–9 | **sonnet** | **high** | Pure gate and sizing, the book's rows, the executor and the cycle, given whole and pinned by tests. | The first code that places orders; send-time re-gating and close-then-buy sequencing must be exact. |
| **D — Share attribution end to end, the fault drills** | 10–12 | **opus** | **high** | The ledger (E8), the wheel's view in `get_positions` (E4), the seven drills. | Attribution is where a covered call against the wrong shares would come from (spec §9.2). |
| **E — The process, the spec amendment, the docs** | 13–15 | **sonnet** | **high** | The night and the entrypoint wiring, the fences, revision 4 and the docs, given as text. | Wires clientId 31 into a live daemon's loop; the docs carry the core invariant's text. |
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

   > You are executing Section [X] of `docs/superpowers/plans/2026-10-29-value-book-5-money-paper.md`
   > in the git worktree `.claude/worktrees/value-book-5` (branch `feat/value-book-5`). Read, in this
   > order: the plan's "Rulings made up front", "Global Constraints" and Section [X] in full; the spec
   > sections Section [X] cites; and only the files its tasks list. Do the tasks in order, TDD as
   > written: each failing test first, then the code, then the gates the task names. Apply each diff
   > with the Edit tool, or save it with the Write tool to a file in your scratchpad (outside the
   > worktree) and run `git apply <that file>` from the worktree root; a new file is written whole
   > with the Write tool. Run pytest from the worktree root. One commit per task, message ending
   > `Co-Authored-By: <your model name> <noreply@anthropic.com>`. After each task tick its checkboxes
   > and fill its Progress-log row (status, commit, gate counts, date, every ruling with its
   > cost-if-wrong) and commit that with the next task (the last task's row goes in a final
   > `docs(plan)` commit). Never import a `scripts.run_*` module; never connect to IBKR (every test
   > fakes the broker); never touch `data/*.db` of the main checkout; never edit a private
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

After Section E: spawn **one opus subagent** (`effort: "high"`) for a whole-branch review
(superpowers:requesting-code-review; the prompt is under "Whole-branch review"), then **one sonnet
subagent** (`effort: "high"`) that fixes every Critical and Important finding in one commit, then
verify it and **ask the operator before merging or pushing**. Part 5 has no calibration section and
places no order before the merge: the book is off until the operator turns `value.book.enabled`
on after the scripted fault drills (operator to-dos).

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
| Section A entry | checks A1–A5 passed | 0 (branch `feat/value-book-5` at `490d8ca` = main with Part 4 merged locally, not pushed) | **baseline: pytest 5393 passed, 1 skipped**; ruff clean; mypy 338 source files; df 29 GiB free | 2026-11-04 | **A1 reconciliation with Part 4 as merged:** every A4 grep matched at the quoted line numbers (Part 4's prototype numbers held exactly). Part 4's review fixes (`reset_at` in the breaker state, `ready_names` in the night summary, `Accepted.refused`/`kept_earlier`, `filing_text`, `FACT_UNITS`) touch nothing Part 5 references; `queue_read(vs, symbol, *, kind, reason, now, accn=None, reevaluation_id=None)`, `ValueEffectiveRow`'s columns and `value_claude_state` match this plan's use. **Operator answers (2026-11-04):** E1–E8 approved; the five HANDOFF questions accepted at their defaults (release inherits its buy's approval; combined name cap 15%; release thresholds 0% floor / 25% prefer / 3 closes per request / 4 a day / 10% of net liq a day; "trim to half" is a card in Part 6). Part 4 merged locally to main (fast-forward), NOT pushed. Section A exit target: baseline 5393 + 12 = 5405 passed, 1 skipped |
| Task 1 - the book's configuration | done | `2c762d5` | tests/test_value_config.py 21 passed (+3), with test_config_keys and test_private_config 37 passed; v4 ruleset hash unchanged (`FROZEN["v4"]`); ruff check/format and `mypy src/common/config.py` clean | 2026-11-04 | No deviation from the task text. Red run: 2 of 3 new tests failed as written; `test_nonsense_book_keys_are_refused` was green before the code because an unknown `book` key was itself refused, so after the code I confirmed by hand that each of its six cases raises for its own reason (cost if wrong: none, the test is a little weaker than it reads at the red stage). `book` is outside `rules:` per ruling 8, so v4 stays |
| Task 2 - the book's tables and the wheel's window | done | `324fca4` | tests/test_value_view.py 4 passed (+4); with test_value_store and test_value_fence 30 passed; ruff check/format and `mypy src/value/store.py src/common/value_view.py` clean | 2026-11-04 | No deviation. Red run: collection `ImportError` on `src.common.value_view`. `init_value_db()` adds `value_reevaluations.position_id` to an existing value.db through `_ADDED_COLUMNS` (checked: `_add_missing_columns` skips a column that already exists, so a fresh db created from the model is fine). The autouse `_value_view_in_tmp` points `value_view._path` at a file that never exists, so no test reads the operator's value.db (cost if wrong: none) |

## Roadmap (this plan is Part 5 of 6)

- **Parts 1–3.** Merged and pushed; `value_rules` v1–v3 frozen.
- **Part 4 — Stage 2: Claude as the analyst.** `docs/superpowers/plans/2026-10-29-value-book-4-claude-analyst.md`;
  `value_rules: v4`. This plan builds on its plan text (see the note at the top).
- **Part 5 — Stage 3: money in paper.** This plan. The value gate, sizing and tranches, the book's
  rows, the executor on clientId 31 with `orderRef`, the night's proposals and the RTH cycle, the
  live policy's exits as orders (Claude-caused sales always a tap), share attribution (the ledger's
  `orderRef`, W and V, the wheel's view, fail-closed reads, the reconcile and its freeze, the sell
  cap, the seven fault drills), the Rules Engine's value-book gates, **capital release** (operator,
  2026-10-30: spec revision 4, §21), the value put's ceiling at `promote`, the hourly check of
  triggers 1 and 4 with "pause adds" and Claude's review of held names, plain Telegram messages, and
  the operator's CLI. **Moved out to Part 6:** the `value_approve` / `value_reject` command kinds and
  their buttons (taps are `scripts/value_book.py` here, ruling 14), the drawdown's "trim to half"
  proposal (a review card, ruling 15), the full §7.1 trigger set for a held name with no open shadow
  entry (ruling 22), `value_put` in the API's `PromotePayload` (ruling 25). **Not built:** live
  trading (a separate live plan after spec §12's review).
- **Part 6 — Web and Telegram.** As Part 4's Roadmap says, plus the above, plus the value book's
  `value` kind across Home (pay stub, positions, calendar) through `src/api/value_db.py`.

## Rulings made up front (the operator may overturn any of them)

Every ruling was checked against `main` at `da5d3c3` and against a prototype of this whole plan
built **on top of a prototype of Part 4's plan** in a code-only scratch copy of `main` (every code
block below passed its tests, `ruff check .`, `ruff format --check` on every touched file and
`mypy src` there). "Cost if wrong" is what reversing it would take.

### The Rules-Engine edits, for the operator's approval before Section B runs

These are the only changes to the deterministic trading path. Each keeps the core invariant: no LLM
output reaches any of them, and every one is inert while `value.book.enabled` is false.

| # | File | Edit |
|---|---|---|
| E1 | `src/engine/capital.py` | `resolve_caps(..., value_claim=0.0)` subtracts the value book's claim from excess liquidity before the reserve; `seed_budgets(..., extra_exposure=None)` adds the value book's stock per name to the concentration tally; new pure `ReleaseCandidate`, `release_reasons`, `select_releases` |
| E2 | `src/engine/risk_engine.py` | `validate_candidates` reads `books.value_exposure()` once: passes its claim and exposure to E1; refuses a CSP or covered call on a frozen name (`book_attribution_mismatch`), a CSP while value.db is unreadable with the book on (`value_book_unreadable`), a CSP past the gross cap (`gross_notional_cap`) or, on a name the book holds, past the combined name cap (`combined_name_cap`); new `validate_release` (the capital-release gate) |
| E3 | `src/strategies/cash_secured_put.py`, `src/engine/regime_limits.py` | the sizer and the regime fit pass the same claim and exposure (generator and gate never disagree) |
| E4 | `src/ibkr/portfolio.py` | `get_positions` gives the wheel its own shares on a shared name (`wheel_view`), `include_value=True` is the account truth (the healthcheck, the value process) |
| E5 | `src/execution/capital_release.py` (new), `position_manager.close_short_position(..., note="")`, `CloseReason.CAPITAL_RELEASE` | the release runner |
| E6 | `src/notify/approval_service.py` | one call to the runner in the intraday loop, after the loss exits |
| E7 | `src/notify/command_drain.py` | `promote` refuses `above_value_ceiling` for a value-suggested put |
| E8 | `src/ledger/{live,flex,ingest}.py`, `src/storage/models.py`, `src/storage/db.py`, `src/common/schemas.py` | `orderRef` through the ledger; value fills tagged `book="value"` |

### Capital release (the operator's 2026-10-30 decision; HANDOFF §3)

1. **Only cash-secured puts are released.** Closing a covered call frees no cash (the shares stay);
   `validate_release` refuses a call (`release_not_csp`) and a spreads-book contract. *Cost if
   wrong: one reason.*
2. **Eligibility: breakeven or better, never a loss.** A put's profit is `1 − mid / entry credit`
   on the roll chain's net credit (`chain_entry_credit_per_share`, the profit-take arithmetic);
   below `release.min_profit_pct` (0: breakeven) it is refused (`release_at_loss`). Those at
   `preferred_profit_pct` (25) or more are preferred; breakeven-to-25% ones are the fallback. A quote
   wider than `max_spread_pct` (25% of the mid) is not closed into. *Cost if wrong: config numbers.*
3. **Selection: the fewest closes that cover the shortfall** (`select_releases`): among sets of the
   smallest size, fewest below 25%, then least premium given up (`mid × 100 × contracts`), then most
   capital released per dollar given up; ties by contract key; at most `max_closes_per_request` (3);
   **never a partial release** (no allowed set covers it → nothing is closed). The pool is the 20
   best by capital per dollar given up, so the search stays small. *Cost if wrong: one function.*
4. **The Rules Engine gates each close twice and the wheel's own close path sends it.** Decision
   time: every put is quoted (`_quote_short`: `qualifyContracts`, `req_fresh_mkt_data`) and gated;
   send time: the chosen put is quoted again and gated again, and only then sent by
   `close_short_position` (a `LimitOrder` at mid, cancel on timeout, the OrderRow/FillRow record,
   per-contract idempotency), stamped `CloseReason.CAPITAL_RELEASE` with "capital release request N"
   in the order's detail. A put refused at send time stops the request for the cycle. *Cost if wrong:
   none of the wheel's path changes.*
5. **Close first, confirm, then buy.** The trading process only closes; it never buys and writes
   nothing in value.db. The value process re-reads its own fresh account (clientId 31) every RTH cycle,
   re-gates the buy on a fresh quote and sends it only when the room is there; the request is then
   `funded`. *Cost if wrong: none.*
6. **No stranded state, no churn.** While an approved buy waits, its whole cost is **earmarked** in
   the wheel's gross cap (`value_exposure().earmarked`), so the wheel cannot re-sell into the freed
   collateral. A request lapses after `request_ttl_hours` (30), when its buy is refused at send time,
   or when the buy expires; a lapsed name asks again only after `cooldown_days` (3). Closes already
   made stay made (each was at breakeven or better). Caps: `max_closes_per_day` (4) and
   `max_release_pct_per_day` (10% of net liq). Halted: no request is serviced. No earnings rule:
   closing a put before earnings reduces risk. A buy is never released for unless it passed every
   value gate but the gross cap (the name cap, the combined cap, the max positions and the earnings
   window already refused it otherwise). *Cost if wrong: config numbers and one condition.*
7. **Approval — a release inherits its buy's approval (QUESTION FOR THE OPERATOR, default
   shown).** A funding request exists only for an approved buy: an auto buy (the autonomy ladder:
   `may_auto_open`) releases automatically; a buy that waits for a tap opens no request until it is
   tapped, and the tap approves the release with it. Reasoning: the release serves an opening trade,
   so it follows the opening ladder (HANDOFF §3: "buys follow the autonomy ladder"), while every close
   is deterministic and profitable or flat. The alternative (every release always waits for its own
   tap) is one condition in `capital_release.py`.

### The book (spec §9 as amended)

8. **No pot: ceilings.** `value.book.ceiling_pct_of_net_liq` (30) caps the book's cost; the name cap
   (8% of the ceiling), `max_positions` (20) and the per-list share cap (70% of the ceiling) are
   ceilings within it; the trend brake halves the ceiling. Nothing is reserved; `value_exposure()`
   claims only what the book holds and has approved. The `value.book` keys are risk configuration,
   **outside the ruleset hash** (they change no verdict; v4 stays). *Cost if wrong: moving them
   under `rules:` is a v5.*
9. **The gross cap is the cash-only rule.** A value buy fits when stock of both books + CSP
   collateral + other approved buys + its cost stays within `portfolio.max_gross_notional_pct`
   (100) of net liq. `portfolio.max_combined_name_pct` = 15 (spec §17 left it open): the wheel's
   10% collateral cap plus a full value position (2.4%) with headroom. Both keys go in
   `config/examples/risk_limits.yaml` with `value_maintenance_pct: 25`. *Cost if wrong: numbers.*
10. **The gate** (`src/value/risk.py::validate`, pure) carries every spec §9.4 reason plus
    `list_share_cap`, `adds_paused`, `not_paper`, `halted`, `reserved_for_spreads_book` and
    `no_shares`; `sleeve_exhausted` now means "past the ceiling". Unknown earnings is a refusal, never
    a pass. Only `gross_notional_cap` is fundable. A margin above the 60% review line is a
    **tap-only** proposal, never refused outright and never automatic. *Cost if wrong: one reason.*
11. **Sizing** (`sizing.py`, pure): the effective margin of safety picks the tier per list (spec
    §6.0), its share of the ceiling, capped at the name cap; thirds; the second tranche on a higher
    low (the last five sessions' low above the low before them since the first tranche), the third on
    a close above the 50-day SMA, at least `tranche_min_sessions` (5) apart. `src/analytics/scale_in`
    is the wheel's CSP ladder with its own zones from the regime context: not reused. *Cost if wrong: a
    function.*
12. **Claude's margin of safety and its breaker.** The size follows the **effective** margin
    (Claude's clamped fair value where it applies: Part 4's `value_effective`). Part 4's breaker is the
    margin breaker: tripped, `value_effective` is Python's baseline and so is the size. In live with
    `value.claude.apply_live` false the effective verdict is Python's already (Part 4 ruling 7); the
    book idles in live anyway. *Cost if wrong: none.*
13. **Exits as orders.** Each held position carries the live policy's plan (`rules.exits.live_policy`,
    `value`), stepped each night on Python's numbers. A Python exit (catastrophe, thesis,
    re-marked below) is a sell proposal approved at once when `automation.auto_close_enabled` (spec
    §14 question 4); the half-sale is Python's when the close is at or past Python's fair value, else
    Claude's; every Claude-caused sale (the effective-only proposal, Claude's BROKEN review, Claude's
    NO on a held name) **always waits for a tap**. `full` and `hold12` never trade. *Cost if wrong:
    none.*
14. **Taps in Part 5 are a CLI**: `python -m scripts.value_book --approve N / --reject N`. The
    Telegram and web buttons (`value_approve` / `value_reject` command kinds drained by
    `approval_service`) are Part 6, with the cards. No command kind is added here. *Cost if wrong: the
    operator taps in a terminal until Part 6.*
15. **The trend brake** reads SPY's month-end closes from the night's bars (`month_end_closes`, the
    current month counted once it has ended) and is stored for the RTH cycle; **the drawdown
    breaker** keeps the book's high-water mark (filled shares at their marks) and stops entries past
    15%; `--reset-drawdown` resets it. The 25% "trim to half" proposal is deferred to Part 6 (it is a
    review card). *Cost if wrong: one proposal kind.*

### Attribution (spec §9.2)

16. **W from the ledger.** `wheel_shares` sums every stock execution not tagged `value` or `spreads`
    (fills, assignments, exercises, manual trades) in time order, applying a split the ledger records
    as a corporate action ("N FOR M"); its average cost replaces IBKR's blended `avgCost` on a shared
    name, so a value purchase never moves the wheel's strike floor (`covered_call` and
    `adjusted_cost_basis_for` read the position they are given, unchanged). The ledger begins at its
    first import: **import the account's history before the first buy** (operator to-do). *Cost if
    wrong: a shared name with pre-ledger stock reads unexplained and freezes (fail closed).*
17. **The wheel's view** (`books.attribute`): `min(W, broker − V claimed)`, never below zero, V
    claimed = filled + working buys; value.db unreadable → W where the broker agrees with W, nothing
    elsewhere. Only names the value book holds or is trading change while value.db reads; every
    stock name is checked while it does not. *Cost if wrong: none (errs short).*
18. **The reconcile** runs every RTH cycle in the value process: broker = W + V filled, else
    `pending` for `attribution_grace_hours` (36, the Flex lag), then `frozen` with a Telegram message;
    a freeze stops the value gate and the Rules Engine (CSPs and calls) on the name until
    `value_book --clear SYMBOL`. A split restates V with `value_book --split SYMBOL N:M`. **Only a
    value-book stop or thesis sale may send on a frozen name** (the sell cap below still applies).
    *Cost if wrong: the grace number.*
19. **The sell cap**: `min(value filled, broker − 100 × wheel short calls)` (spec §9.2).
20. **The seven fault drills** are unit tests (`tests/test_value_fault_drills.py`, one per drill) and
    seven scripted paper drills the operator runs before `value.book.enabled` (operator to-dos).

### The process, held names, the boundary

21. **clientId 31 per cycle.** The value process connects for each RTH cycle (every
    `book.cycle_minutes`, 15) and disconnects after it; ib_async and `src.ibkr` are imported inside
    `src/value/stage3.py`'s functions, so importing `src.value` loads neither (Part 2's probe stays
    green). Paper only: the cycle never runs with `LIVE_TRADING=true`.
22. **Held re-evaluations** (spec §7.1, Part 3's Roadmap): the hourly check (a raw move past 10%
    against the last close on the cycle's own marks, or a Major 8-K filed since yesterday) and a
    nightly mirror of the shadow record's re-evaluations on the same name and list open a
    `value_reevaluations` row keyed by `position_id`; adds pause while it is within the debounce or
    Claude's review is pending, WEAKENED or BROKEN; Claude's review is queued (Part 4's `review` read).
    A held name with no open shadow entry gets the hourly check only. *Cost if wrong: a held name's
    quiet and regime triggers wait for Part 6.* **Part 3's deferred "trigger 4 robust to late
    indexing"**: the hourly check reads a two-day filing window — partly fixed; the full fix stays
    deferred.
23. **Held names stay fresh and are read**: they are scored nightly (`held:trading`), kept fresh
    (`value_keep_fresh.json`) and get filing reads (Part 4's `value_filing_reads.json`).
24. **Telegram, the minimum**: `src/value/notify.py` sends plain messages (fills, refusals, freezes,
    funding requests, re-evaluations) to `TELEGRAM_THREAD_VALUE` (new, optional; the main chat when
    empty). Cards, buttons, digests and the watchdog are Part 6.
25. **The put flow** (spec §9.1): `promote` refuses `above_value_ceiling` when the command carries
    `value_put: true`, reading `value_view.put_ceiling`. The API model gains the field with Part 6's
    strip (the drain reads it from the payload today, so the OpenAPI document does not change for
    it). `docs/web/commands.md` gains the reason.
26. **Part 4 ruling 7 holds:** the claude shadow track keeps measuring Claude whatever the book does.
27. **Review minors**: Part 3's deferred trigger-4 item is partly fixed (ruling 22); the rest stay
    deferred with Part 3's reasons (no code here touches them).

## Global Constraints

- **The core invariant holds.** The value book's orders pass only `src/value/risk.py::validate`
  (decision time and send time) and go only through `src/value/executor.py` on clientId 31; the
  wheel's orders pass only the Rules Engine; a capital-release close passes
  `risk_engine.validate_release` twice. No LLM output selects, sizes, prices or gates any of them;
  what Claude produced reaches the value gate only as Part 4's effective verdict and fair value.
- **Paper only.** The book never trades with `LIVE_TRADING=true` (the gate refuses `not_paper` and
  the entrypoint idles the cycle). No test connects to IBKR: every broker is a fake.
- **Fences.** Nothing in `src/engine/`, `src/execution/`, `src/strategies/`, `src/orchestrator/`,
  `src/monitor/`, `src/notify/`, `src/ibkr/`, `src/spreads/`, `src/news/` or `src/claude/` imports
  `src.value`; they reach the book only through `src/common/value_view.py` and `src/common/books.py`.
  `src/value/` keeps Part 4's fence (no `src.claude`, `src.news`, `src.value_ai`, the trading path,
  `src.ledger`, `src.reporting`); it may now read `src.storage.wheel_shares` (W) and, inside
  `stage3.py`'s functions only, `src.ibkr` and `src.storage.system_settings`. The value book never
  trades SPY, SPX or XSP (`reserved_for_spreads_book`). Only `src/value/` constructs `value.db` rows;
  only `src/ledger/` constructs ledger rows.
- **Unknown is never zero**: an unknown earnings date refuses a buy; an unreadable value.db fails the
  wheel closed; an unreadable corporate action leaves W unadjusted (the name freezes).
- **Never import `scripts.run_*`**; check it with `.venv/bin/python -m py_compile`. Never open the
  main checkout's `data/*.db`; never copy `research.db`.
- **`web/`**: Task 5 changes one generated line of `web/lib/api-types.ts` by hand (the OpenAPI
  document's `CloseReason`); its subagent invokes the `da-vinci` skill first, and nobody runs `npm`,
  `next build` or `next dev`.
- Worktree Bash: plain single commands; no heredocs, no `cd x && …`, no compound git-path commands.
- New keys go into `config/examples/value.yaml`, `settings.yaml`, `risk_limits.yaml` and
  `.env.example` with code defaults; private copies are operator to-dos.
- **Protected files** (empty at every section exit; the branch is cut from a `main` that contains
  Part 4, so the diff shows Part 5 alone):
  `git diff --stat main...HEAD -- src/orchestrator src/monitor src/spreads src/api src/news src/claude src/reporting src/research src/value_ai`
  prints nothing, and `git diff --stat main...HEAD -- web` prints only `web/lib/api-types.ts`.
  Part 5's other edits outside `src/value/`, `src/common/`, `scripts/`, `tests/`,
  `config/examples/`, `.env.example` and the docs are exactly the rulings' table E1–E8.
- Per-task gate: the task's test files + `ruff check` + `ruff format --check` on touched files +
  `mypy` on touched src files. Full gate at section exits, from the worktree root.

## Review Focus

1. **A value buy races ahead of its funding** → nothing is sent until the fresh snapshot shows room;
   the request is funded only by the buy's fill → Task 8
   `test_a_buy_short_of_cash_asks_for_capital_then_buys_once_the_room_is_there`.
2. **A release closes at a loss, a call, more than needed, or a partial set** → Task 4
   `test_the_fewest_closes_that_cover_the_need_never_a_partial_one`,
   `test_the_release_gate_never_closes_at_a_loss_or_a_call_and_caps_the_day`; Task 5
   `test_the_runner_closes_after_a_second_gate_on_a_fresh_quote`.
3. **The wheel writes a call against value shares, or a value sale uncovers a wheel call** → Task 3
   `test_the_wheel_sees_min_of_its_count_and_broker_less_value`; Task 11
   `test_get_positions_gives_the_wheel_its_own_shares_at_its_own_cost`; Task 8
   `test_a_sell_never_uncovers_a_wheel_call`; the seven drills (Task 12).
4. **A Claude number causes a sale on its own** → Task 8
   `test_a_half_sale_only_claudes_value_reaches_waits_for_a_tap`,
   `test_claudes_broken_review_is_a_tap_only_sell`, `test_on_a_frozen_name_only_a_stop_or_thesis_sale_sends`.
5. **The book being off changes the wheel** → Task 4 `test_with_the_book_off_the_wheel_is_unchanged`;
   the existing engine, sizer and portfolio suites stay green at every section exit.
6. **A test reads the operator's `data/value.db`** → Task 2's autouse `_value_view_in_tmp`.

---

## File structure

```
config/examples/value.yaml, settings.yaml, risk_limits.yaml; .env.example   MODIFY (T1, T4)
src/
  common/config.py                 MODIFY  ValueTiersCfg, ValueReleaseCfg, ValueBookCfg; client id;
                                           TELEGRAM_THREAD_VALUE (T1)
  common/value_view.py             CREATE  the wheel's read-only window (T2)
  common/books.py                  MODIFY  attribute, value_sell_cap, value_exposure (T3)
  common/schemas.py                MODIFY  CloseReason.CAPITAL_RELEASE (T5); ParsedExecution.order_ref (T10)
  storage/wheel_shares.py          CREATE  W from the ledger, splits applied (T3)
  storage/models.py, storage/db.py MODIFY  broker_executions.order_ref (T10)
  engine/capital.py                MODIFY  value claim, extra exposure, release selection (T4)
  engine/risk_engine.py            MODIFY  value gates, validate_release (T4)
  engine/regime_limits.py, strategies/cash_secured_put.py   MODIFY  the same claim (T4)
  execution/capital_release.py     CREATE  the release runner (T5)
  execution/position_manager.py    MODIFY  close note (T5)
  notify/approval_service.py       MODIFY  one call in the intraday loop (T5)
  notify/command_drain.py          MODIFY  above_value_ceiling (T6)
  ledger/live.py, flex.py, ingest.py   MODIFY  orderRef; book="value" (T10)
  ibkr/portfolio.py                MODIFY  wheel_view, include_value (T11)
  value/store.py                   MODIFY  six tables, position_id (T2)
  value/risk.py, sizing.py         CREATE  the gate, sizing, tranches; pure (T7)
  value/scorecard.py               MODIFY  adv_dollar_20 (T7)
  value/book.py, executor.py, live.py   CREATE  rows, orders, the night and the cycle (T8)
  value/stage3.py, notify.py       CREATE  clientId 31's cycle; messages (T9)
  value/service.py                 MODIFY  BookHooks, held names, the night's book step (T13)
scripts/run_value.py               MODIFY  the book's hooks and RTH cycle (T14)
scripts/value_book.py              CREATE  the operator's CLI (T14)
scripts/healthcheck.py             MODIFY  include_value (T11)
docs/web/openapi.json, web/lib/api-types.ts   MODIFY  CloseReason (T5)
docs/web/commands.md               MODIFY  above_value_ceiling (T6)
tests/
  test_value_config.py             MODIFY  (+3)                                  T1  +3
  conftest.py, value_book_fixtures.py   MODIFY / CREATE  (fixtures)            T2
  test_value_view.py               CREATE  (4)                                   T2  +4
  test_value_attribution.py        CREATE  (5), then +2 (T10), +2 (T11)          T3 +5, T10 +2, T11 +2
  test_value_capital_release.py    CREATE  (7), then +3 (T5)                     T4 +7, T5 +3
  test_drain_promote.py            MODIFY  (+1)                                  T6  +1
  test_value_risk.py               CREATE  (4 functions, 23 collected)           T7  +23
  test_value_live.py               CREATE  (14)                                  T8  +14
  test_value_stage3.py             CREATE  (2), then +1 (T13), +1 (T14)          T9 +2, T13 +1, T14 +1
  test_value_fault_drills.py       CREATE  (7)                                   T12 +7
  test_value_fence.py              MODIFY  (+2; rows, pure list, allowlist)      T14 +2
docs/superpowers/specs/2026-10-28-value-swing-book-design.md   MODIFY  revision 4 (T15)
CLAUDE.md, ARCHITECTURE.md, SETUP.md, STATUS.md   MODIFY (T15)
```

**77 new tests** (Part 4's prototype end 5382 → 5459 passed, 1 skipped; mypy 348 source files).
No new command kind, route or top-level directory.

---

## Section A — Config, the book's tables, the read-only view, the attribution rule (Tasks 1–3) · model: sonnet · effort: high

**Spec to read:** §9 intro, §9.1, §9.2, §9.3 with its revision-4 note, §9.5, §9.7, §21.

**Files the subagent reads:** `src/common/config.py` (the value models), `config/examples/value.yaml`,
`src/value/store.py`, `src/common/books.py`, `tests/conftest.py` (lines 75–110),
`src/storage/models.py` (`BrokerExecutionRow`, `BrokerCorporateActionRow`), `tests/test_value_config.py`.

**Entry checks (the orchestrator runs these before spawning):**

- [ ] **A1. Reconcile this plan with Part 4 as merged (do this first, in full).** Part 5 was written
  against Part 4's plan. From the main checkout:
  1. `git -C "/Users/ianlim/Desktop/IBKR Investments" log --oneline -1 main` and confirm Part 4 is
     merged (`grep -c "value_ai" src/value/claude_reads.py` from a `main` worktree, or
     `git show main:src/value/claude_reads.py | head -3` prints its docstring).
  2. Read Part 4's Progress log (every row, every ruling and the review-fix rulings) and its operator
     rulings. For each Part 4 ruling the operator overturned or the executor changed, find the Part 5
     text that depends on it: the effective verdict (`value_effective`, Part 4 ruling 4/7), the
     review read (`claude_reads.queue_read(kind="review", reason="review", reevaluation_id=...)`,
     ruling 15), the breaker (ruling 8), `value_ai_types`, the v4 hash, `ValueReevaluationRow`,
     `ValueEffectiveRow` columns, `run_value.py`'s Claude tick, `test_value_fence.py`'s allowlist,
     `tests/conftest.py`'s keep-fresh fixture, and `service.run_nightly`'s body.
  3. Run every `grep` of this plan's entry checks whose label says "(Part 4)" against the merged
     tree. Every one must print the quoted text (line numbers may differ: record them).
  4. Any mismatch → stop; record the mismatch and the correction as a ruling in this plan's Progress
     log; patch the affected task text in this plan (a one-commit `docs(plan)` change the operator
     approves) before Section A runs. A mismatch inside a code block means the section is rerun at
     `xhigh` with the corrected fact.
- [ ] **A2. Disk, worktree, setup.** `df -h .` shows at least 8 GiB free; then (one command each):

  ```bash
  git -C "/Users/ianlim/Desktop/IBKR Investments" worktree add "/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/value-book-5" -b feat/value-book-5 main
  ln -s "/Users/ianlim/Desktop/IBKR Investments/.venv" .venv
  cp "/Users/ianlim/Desktop/IBKR Investments/docs/superpowers/plans/2026-10-29-value-book-5-money-paper.md" docs/superpowers/plans/
  IBKR_CONFIG_USE_EXAMPLES=1 .venv/bin/python -c "from src.storage.db import init_db; init_db()"
  ```

  (No `web/node_modules` link: no web test runs.)
- [ ] **A3. A green baseline** from the worktree root: `.venv/bin/python -m pytest -q`,
  `.venv/bin/ruff check .`, `.venv/bin/mypy src`; record it as the baseline (Part 4's prototype end:
  `5382 passed, 1 skipped`, mypy 338 files; the merged number may differ by Part 4's review fixes).
- [ ] **A4. The code Section A edits is where this plan says** (Part 4 lines are marked; line
  numbers as of Part 4's prototype end, `main` at `da5d3c3` for the rest):

  ```bash
  grep -nF 'class ValueCfg(_ValueModel):' src/common/config.py   # 1843:   (Part 4)
  grep -nF '    claude: ValueClaudeCfg = Field(default_factory=ValueClaudeCfg)' src/common/config.py   # 1854:   (Part 4)
  grep -nF '                raise ValueError("ibkr.client_ids.spreads must be set when spreads.enabled is true")' src/common/config.py   # 2552:
  grep -nF '    telegram_thread_news: str = Field(default="", alias="TELEGRAM_THREAD_NEWS")' src/common/config.py   # 83:
  grep -nF '    min_values: 8' config/examples/value.yaml   # 258:   (Part 4; the file's last line)
  grep -nF '    spreads: 30       # daily credit-spread service' config/examples/settings.yaml   # 17:
  grep -nF 'TELEGRAM_THREAD_NEWS=4409' .env.example   # 28:
  grep -nF 'def test_part_2_turns_the_research_sweep_on() -> None:' tests/test_value_config.py   # 168:
  grep -nF '- ``value_claude_state`` - small key/value state (the breaker).' src/value/store.py   # 42:   (Part 4)
  grep -nF '_engine: Engine | None = None' src/value/store.py   # 414:
  grep -nF '_ADDED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {' src/value/store.py   # 419:
  grep -nF 'def _value_keep_fresh_in_tmp(monkeypatch, tmp_path_factory):' tests/conftest.py   # 79:   (Part 4 edited its body)
  grep -nF 'def is_spreads_underlying(symbol: str | None) -> bool:' src/common/books.py   # 26:
  ```

- [ ] **A5. No Part 5 code yet:** `grep -rln "ValueBookCfg\|value_view\|wheel_shares\|CAPITAL_RELEASE" src tests scripts` prints nothing.

**Section exit:** three task commits plus the `docs(plan)` commit; full gate with pytest = baseline +
12; the protected-file diff empty; `py_compile scripts/run_value.py` silent; `git status --short`
clean.

---

### Task 1: The book's configuration — ceilings, tiers, release; clientId 31

**Files:** Modify `src/common/config.py`, `config/examples/value.yaml`,
`config/examples/settings.yaml`, `.env.example`, `tests/test_value_config.py`.

**Interfaces:** `ValueCfg.book: ValueBookCfg` (`enabled`, `ceiling_pct_of_net_liq`, `name_cap_pct`,
`max_positions`, `max_list_share_pct`, `tiers: ValueTiersCfg`, `tranches`, `tranche_min_sessions`,
`illiquid_adv_pct`, `trend_brake_ceiling_pct`, `drawdown_stop_pct`, `drawdown_trim_pct`,
`quote_max_age_seconds`, `cycle_minutes`, `proposal_ttl_hours`, `attribution_grace_hours`,
`fill_timeout_seconds`, `release: ValueReleaseCfg`); `Secrets.telegram_thread_value`;
`ibkr.client_ids.value` required when the book is on. Outside `rules:` (ruling 8): v4's hash does not
move.

- [x] **Step 1: Write the failing tests** — apply:

```diff
diff --git a/tests/test_value_config.py b/tests/test_value_config.py
index 7b0c48c..c1e63ca 100644
--- a/tests/test_value_config.py
+++ b/tests/test_value_config.py
@@ -168,3 +168,37 @@ def test_nonsense_exit_and_service_keys_are_refused() -> None:
 def test_part_2_turns_the_research_sweep_on() -> None:
     assert ValueCfg().research_sweep.enabled is True
     assert ValueCfg().service.run_hour_et == 6
+
+
+def test_the_book_is_off_and_holds_no_cash_back_by_default() -> None:
+    """Revision 4 (2026-10-30): no pot; the 30% is a ceiling; the book is off until the operator
+    turns it on, and only paper ever trades."""
+    book = ValueCfg().book
+    assert book.enabled is False and book.ceiling_pct_of_net_liq == 30.0
+    assert (book.name_cap_pct, book.max_positions, book.max_list_share_pct) == (8.0, 20, 70.0)
+    assert book.release.min_profit_pct == 0.0 and book.release.preferred_profit_pct == 25.0
+    assert book.tiers.deep_value == [(25.0, 3.0), (35.0, 5.0), (45.0, 8.0)]
+    assert ruleset_hash(ValueCfg(**{"book": {"enabled": True}}).rules) == FROZEN["v4"]
+
+
+def test_nonsense_book_keys_are_refused() -> None:
+    for bad in (
+        {"book": {"ceiling_pct_of_net_liq": 0.0}},
+        {"book": {"drawdown_stop_pct": 30.0}},
+        {"book": {"tiers": {"deep_value": [[35.0, 5.0], [25.0, 3.0]]}}},
+        {"book": {"release": {"min_profit_pct": -5.0}}},
+        {"book": {"release": {"preferred_profit_pct": 0.0, "min_profit_pct": 10.0}}},
+        {"book": {"pot_pct": 30.0}},
+    ):
+        with pytest.raises(ValidationError):
+            ValueCfg(**bad)
+
+
+def test_an_enabled_book_needs_its_client_id(monkeypatch) -> None:
+    cfg = get_config()
+    assert cfg.ibkr.client_ids["value"] == 31
+    data = cfg.model_dump(by_alias=True)
+    data["value"]["book"]["enabled"] = True
+    data["ibkr"]["client_ids"].pop("value")
+    with pytest.raises(ValidationError, match="client_ids.value"):
+        type(cfg).model_validate(data)
```

- [x] **Step 2: Run them to see them fail** — `.venv/bin/python -m pytest -q tests/test_value_config.py`:
  `AttributeError: 'ValueCfg' object has no attribute 'book'`.
- [x] **Step 3: The config** — apply:

```diff
diff --git a/.env.example b/.env.example
index 0e2e876..b1647fa 100644
--- a/.env.example
+++ b/.env.example
@@ -26,6 +26,7 @@ TELEGRAM_THREAD_BUY=56     # Buy-to-own recommendations
 TELEGRAM_THREAD_ACCOUNT=58 # Account snapshot
 TELEGRAM_THREAD_SPREADS=4308 # Daily credit-spread system (src/spreads/)
 TELEGRAM_THREAD_NEWS=4409  # News thread (src/news/)
+TELEGRAM_THREAD_VALUE=     # Value book thread (scripts.run_value, Stage 3); empty = the main chat
 # Optional: Finnhub free key (personal use) — company news with images, general news, earnings.
 FINNHUB_API_KEY=
 
diff --git a/config/examples/settings.yaml b/config/examples/settings.yaml
index 77764d8..85227f7 100644
--- a/config/examples/settings.yaml
+++ b/config/examples/settings.yaml
@@ -15,6 +15,7 @@ ibkr:
     exec: 14          # execution engine order-placement (approval_service daemon)
     scan: 15          # market data fetch during /scan command (approval_service daemon)
     spreads: 30       # daily credit-spread service (scripts.run_spreads) — config/spreads.yaml
+    value: 31         # value book, Stage 3 (scripts.run_value) — config/value.yaml → book
     healthcheck: 19
     # trading_skills MCP should be configured with clientId 20 (see .mcp.json)
     # dashboard should use clientId 21
diff --git a/config/examples/value.yaml b/config/examples/value.yaml
index 0cecd7e..9785021 100644
--- a/config/examples/value.yaml
+++ b/config/examples/value.yaml
@@ -256,3 +256,36 @@ claude:                      # spec §8: Claude as the analyst (src/value_ai/).
     min_ready: 5             # ... and at least 5
     clamp_rate_pct: 25.0     # or the 1.5x clamp binding on more than 25% of Claude's values ...
     min_values: 8            # ... read over at least 8 of them
+
+book:                        # Stage 3, paper only (spec §9, revision 4): no cash is held back; the
+                             # caps are ceilings, and a valid buy short of cash asks the wheel to
+                             # release capital. Risk config, outside the ruleset hash
+  enabled: false             # no value order of any kind without it (and never in live)
+  ceiling_pct_of_net_liq: 30.0   # the book's cost at most 30% of net liq (a ceiling, not a pot)
+  name_cap_pct: 8.0          # of the ceiling, per name (2.4% of net liq at the full ceiling)
+  max_positions: 20
+  max_list_share_pct: 70.0   # of the ceiling, per list
+  tiers:                     # [margin of safety from %, size % of the ceiling]
+    deep_value: [[25.0, 3.0], [35.0, 5.0], [45.0, 8.0]]
+    quality_growth: [[10.0, 3.0], [20.0, 5.0], [30.0, 8.0]]
+  tranches: 3                # 1/3 at READY, 1/3 on a higher low, 1/3 on a close above SMA50
+  tranche_min_sessions: 5
+  illiquid_adv_pct: 1.0      # refuse a position above 1% of 20-day dollar volume
+  trend_brake_ceiling_pct: 50.0  # SPY under its 10-month SMA: no entries, ceiling x 50%
+  drawdown_stop_pct: 15.0    # the book 15% below its high: no entries
+  drawdown_trim_pct: 25.0    # 25%: a tap-only proposal to trim each position to half
+  quote_max_age_seconds: 30.0
+  cycle_minutes: 15          # the RTH cycle (reconcile, send, fund)
+  proposal_ttl_hours: 30.0
+  attribution_grace_hours: 36.0  # unexplained shares older than this freeze the name
+  fill_timeout_seconds: 120.0
+  release:                   # capital release (operator, 2026-10-30)
+    enabled: true
+    min_profit_pct: 0.0      # breakeven or better: a release never realises a loss
+    preferred_profit_pct: 25.0   # those at 25% of max profit or more go first
+    max_closes_per_request: 3
+    max_closes_per_day: 4
+    max_release_pct_per_day: 10.0  # collateral released per ET day, % of net liq
+    request_ttl_hours: 30.0
+    cooldown_days: 3
+    max_spread_pct: 25.0
diff --git a/src/common/config.py b/src/common/config.py
index 22f26df..f0899aa 100644
--- a/src/common/config.py
+++ b/src/common/config.py
@@ -81,6 +81,8 @@ class Secrets(BaseSettings):
     telegram_thread_spreads: str = Field(default="", alias="TELEGRAM_THREAD_SPREADS")
     # News thread (docs/superpowers/specs/2026-10-09-news-thread-design.md).
     telegram_thread_news: str = Field(default="", alias="TELEGRAM_THREAD_NEWS")
+    # The value book's thread (docs/superpowers/specs/2026-10-28-value-swing-book-design.md §9.7).
+    telegram_thread_value: str = Field(default="", alias="TELEGRAM_THREAD_VALUE")
     finnhub_api_key: str = Field(default="", alias="FINNHUB_API_KEY")
 
 
@@ -1840,6 +1842,92 @@ class ValueClaudeCfg(_ValueModel):
         return self
 
 
+class ValueTiersCfg(_ValueModel):
+    """Spec §9.5 (§6.0's table): size by the effective margin of safety, per list. Each row is
+    (margin from, in percent; size, in percent of the book's ceiling); the highest row the margin
+    reaches applies, below the first row nothing is bought."""
+
+    deep_value: list[tuple[float, float]] = Field(
+        default_factory=lambda: [(25.0, 3.0), (35.0, 5.0), (45.0, 8.0)]
+    )
+    quality_growth: list[tuple[float, float]] = Field(
+        default_factory=lambda: [(10.0, 3.0), (20.0, 5.0), (30.0, 8.0)]
+    )
+
+    @model_validator(mode="after")
+    def _sane(self) -> ValueTiersCfg:
+        for rows in (self.deep_value, self.quality_growth):
+            froms = [f for f, _ in rows]
+            if not rows or froms != sorted(froms) or any(not 0 < s <= 100 for _, s in rows):
+                raise ValueError("value book.tiers: rows ascend by margin; sizes in (0, 100]")
+        return self
+
+
+class ValueReleaseCfg(_ValueModel):
+    """Capital release (operator, 2026-10-30; spec revision 4): when a valid value buy cannot be
+    funded, the wheel closes cash-secured puts at breakeven or better (never at a loss),
+    preferring those at least ``preferred_profit_pct`` of max profit captured, fewest closes that
+    release enough. Deterministic; the Rules Engine gates each close twice."""
+
+    enabled: bool = True
+    min_profit_pct: float = 0.0  # breakeven: the close never realises a loss
+    preferred_profit_pct: float = 25.0
+    max_closes_per_request: int = 3
+    max_closes_per_day: int = 4
+    max_release_pct_per_day: float = 10.0  # collateral released per ET day, % of net liq
+    request_ttl_hours: float = 30.0  # a request not funded by then lapses
+    cooldown_days: int = 3  # after a lapsed request, none for that name for this long
+    max_spread_pct: float = 25.0  # a quote wider than this (of the mid) is not closed into
+
+    @model_validator(mode="after")
+    def _sane(self) -> ValueReleaseCfg:
+        if self.min_profit_pct < 0:
+            raise ValueError("value book.release.min_profit_pct must be >= 0: never at a loss")
+        if self.preferred_profit_pct < self.min_profit_pct:
+            raise ValueError("value book.release.preferred_profit_pct >= min_profit_pct")
+        if min(self.max_closes_per_request, self.max_closes_per_day) < 1:
+            raise ValueError("value book.release: at least one close")
+        return self
+
+
+class ValueBookCfg(_ValueModel):
+    """Stage 3, money in paper (spec §9 as amended by revision 4, 2026-10-30): the value book holds
+    **no cash back**. Its caps are ceilings on what it may hold, not reservations; a valid buy that
+    cannot be funded asks the wheel to release capital. Risk configuration, not rules: nothing here
+    changes a verdict, so it is outside the ruleset hash."""
+
+    enabled: bool = False  # no order of any kind without it; paper only whatever it says
+    ceiling_pct_of_net_liq: float = 30.0  # the book's cost at most this share of net liq
+    name_cap_pct: float = 8.0  # of the ceiling, per name
+    max_positions: int = 20
+    max_list_share_pct: float = 70.0  # of the ceiling, per list
+    tiers: ValueTiersCfg = Field(default_factory=ValueTiersCfg)
+    tranches: int = 3
+    tranche_min_sessions: int = 5  # sessions between two tranches of one name
+    illiquid_adv_pct: float = 1.0  # a position above this share of 20-day dollar volume
+    trend_brake_ceiling_pct: float = 50.0  # SPY under its 10-month SMA: entries stop, ceiling x
+    drawdown_stop_pct: float = 15.0  # the book down this far from its high: entries stop
+    drawdown_trim_pct: float = 25.0  # ... this far: a tap-only proposal to trim to half
+    quote_max_age_seconds: float = 30.0  # a send-time quote older than this is stale
+    cycle_minutes: int = 15  # the RTH cycle: reconcile, send, fund
+    proposal_ttl_hours: float = 30.0  # a proposal not acted on by then expires
+    attribution_grace_hours: float = 36.0  # unexplained shares older than this freeze the name
+    fill_timeout_seconds: float = 120.0
+    release: ValueReleaseCfg = Field(default_factory=ValueReleaseCfg)
+
+    @model_validator(mode="after")
+    def _sane(self) -> ValueBookCfg:
+        if not 0 < self.ceiling_pct_of_net_liq <= 100:
+            raise ValueError("value book.ceiling_pct_of_net_liq must be in (0, 100]")
+        if not 0 < self.name_cap_pct <= 100 or not 0 < self.max_list_share_pct <= 100:
+            raise ValueError("value book: name_cap_pct and max_list_share_pct in (0, 100]")
+        if self.max_positions < 1 or self.tranches < 1 or self.cycle_minutes < 1:
+            raise ValueError("value book: max_positions, tranches, cycle_minutes >= 1")
+        if not self.drawdown_stop_pct < self.drawdown_trim_pct:
+            raise ValueError("value book: drawdown_stop_pct < drawdown_trim_pct")
+        return self
+
+
 class ValueCfg(_ValueModel):
     """The value book (config/value.yaml). Parts 1-4: the scorecard, the shadow record, its
     re-evaluations and Claude as the analyst; nothing that trades."""
@@ -1852,6 +1940,7 @@ class ValueCfg(_ValueModel):
     service: ValueServiceCfg = Field(default_factory=ValueServiceCfg)
     rules: ValueRulesCfg = Field(default_factory=ValueRulesCfg)
     claude: ValueClaudeCfg = Field(default_factory=ValueClaudeCfg)
+    book: ValueBookCfg = Field(default_factory=ValueBookCfg)
 
 
 class _KeyedCfg(BaseModel):
@@ -2550,6 +2639,8 @@ class Config(BaseModel):
                 )
             if "spreads" not in self.ibkr.client_ids:
                 raise ValueError("ibkr.client_ids.spreads must be set when spreads.enabled is true")
+        if self.value.book.enabled and "value" not in self.ibkr.client_ids:
+            raise ValueError("ibkr.client_ids.value must be set when value book.enabled is true")
         return self
 
 
```

- [x] **Step 4: Run them to see them pass** —
  `.venv/bin/python -m pytest -q tests/test_value_config.py tests/test_config_keys.py tests/test_private_config.py`;
  the v4 hash check of Part 4 Task 1 still prints `be30d1eaa915`.
- [x] **Step 5: Gates and commit** (ruff check/format on the five files; `mypy src/common/config.py`):

  ```bash
  git add docs/superpowers/plans/2026-10-29-value-book-5-money-paper.md src/common/config.py config/examples/value.yaml config/examples/settings.yaml .env.example tests/test_value_config.py
  git commit -m "feat(value): the book's configuration - ceilings, tiers, capital release, clientId 31"
  ```

---

### Task 2: The book's tables and the wheel's read-only window

**Files:** Modify `src/value/store.py`, `tests/conftest.py`; create `src/common/value_view.py`,
`tests/value_book_fixtures.py`, `tests/test_value_view.py`.

**Interfaces:** tables `value_orders`, `value_positions`, `value_proposals`,
`value_funding_requests`, `value_attribution` (with `mark`), `value_book_state`;
`value_reevaluations.position_id` (added by `init_value_db`); `value_view.read_book(now=None) ->
ValueBook | None` (`holdings: dict[str, ValueHolding]` with `filled`, `pending_buy`, `pending_sell`,
`cost`, `mark`, `claimed`, `market_value`; `earmarked_usd`; `frozen`; `requests:
tuple[FundingRequest, ...]`), `value_view.put_ceiling(symbol)`; the autouse fixture
`_value_view_in_tmp` (no test reads the operator's value.db) and the fixture `value_book_db`.

- [x] **Step 1: Write the failing tests** — create `tests/value_book_fixtures.py`:

```python
"""Shared helpers for the value book's Stage 3 tests (Part 5): value orders, proposals and funding
requests written the way src/value writes them. The ``value_book_db`` fixture (a value.db in tmp,
with value_view pointed at it) is in tests/conftest.py."""

from __future__ import annotations

from datetime import datetime, timedelta

from src.value.store import ValueFundingRow, ValueOrderRow, ValueProposalRow, value_session

NOW = datetime(2026, 11, 2, 15, 0)  # naive UTC: 10:00 ET, a Monday


def order(
    symbol: str,
    *,
    side: str = "buy",
    shares: float = 10,
    filled: float = 10,
    avg: float | None = 100.0,
    status: str = "filled",
    list_name: str = "deep_value",
) -> int:
    with value_session() as s:
        row = ValueOrderRow(
            symbol=symbol,
            list_name=list_name,
            side=side,
            shares=shares,
            filled=filled,
            avg_price=avg,
            status=status,
            created_at=NOW,
        )
        s.add(row)
        s.flush()
        row.order_ref = f"value:{row.id}"
        return row.id


def proposal(symbol: str, *, status: str = "approved", cost: float = 1000.0, kind: str = "buy"):
    with value_session() as s:
        row = ValueProposalRow(
            kind=kind,
            symbol=symbol,
            list_name="deep_value",
            shares=10,
            price=cost / 10,
            cost_usd=cost,
            reason="tranche 1",
            status=status,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=30),
        )
        s.add(row)
        s.flush()
        return row.id


def funding(symbol: str, needed: float, *, proposal_id: int = 1, status: str = "open", hours=30):
    with value_session() as s:
        row = ValueFundingRow(
            proposal_id=proposal_id,
            symbol=symbol,
            needed_usd=needed,
            status=status,
            created_at=NOW,
            expires_at=NOW + timedelta(hours=hours),
        )
        s.add(row)
        s.flush()
        return row.id
```

  …create `tests/test_value_view.py`:

```python
"""The wheel's read-only window onto the value book (value book spec §9.1-§9.2, revision 4)."""

from __future__ import annotations

from datetime import date

from src.common import value_view as vv
from src.value.store import ValueAttributionRow, ValueEffectiveRow, value_session
from tests.value_book_fixtures import NOW, funding, order, proposal


def test_no_value_db_is_an_empty_book(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(vv, "_path", lambda: tmp_path / "absent.db")
    book = vv.read_book(NOW)
    assert book is not None and book.holdings == {} and book.earmarked_usd == 0.0
    assert vv.put_ceiling("GOOGL") is None


def test_an_unreadable_value_db_fails_closed(tmp_path, monkeypatch) -> None:
    bad = tmp_path / "value.db"
    bad.write_bytes(b"this is not a database")
    monkeypatch.setattr(vv, "_path", lambda: bad)
    assert vv.read_book(NOW) is None


def test_holdings_earmarks_freezes_and_requests(value_book_db) -> None:
    order("GOOGL", shares=10, filled=10, avg=150.0)
    order("GOOGL", shares=10, filled=4, avg=160.0, status="partial")
    order("GOOGL", side="sell", shares=5, filled=5, avg=170.0)
    order("META", shares=20, filled=0, avg=None, status="submitted")
    order("BAC", shares=30, filled=0, avg=None, status="cancelled")
    proposal("META", status="funding", cost=12_000.0)
    proposal("MU", status="pending", cost=5_000.0)  # not approved: no earmark
    funding("META", 4_000.0)
    funding("OLD", 1_000.0, status="lapsed")
    with value_session() as s:
        s.add(
            ValueAttributionRow(
                symbol="BAC", broker=130, wheel=100, value_filled=0, state="frozen", updated_at=NOW
            )
        )
    book = vv.read_book(NOW)
    assert book is not None
    g = book.holding("googl")
    assert (g.filled, g.pending_buy, g.pending_sell) == (9.0, 6.0, 0.0)  # 14 bought, 5 sold
    assert g.claimed == 15.0
    assert round(g.cost, 2) == round(9 * (10 * 150 + 4 * 160) / 14, 2)
    assert book.holding("META").claimed == 20.0 and book.holding("BAC").claimed == 0.0
    assert book.earmarked_usd == 12_000.0
    assert book.frozen == frozenset({"BAC"})
    assert [(r.symbol, r.needed_usd) for r in book.requests] == [("META", 4_000.0)]


def test_the_put_ceiling_is_the_highest_effective_ceiling_of_a_live_list(value_book_db) -> None:
    with value_session() as s:
        for list_name, verdict, ceiling in (
            ("deep_value", "WAIT", 140.0),
            ("quality_growth", "READY", 180.0),
        ):
            s.add(
                ValueEffectiveRow(
                    symbol="GOOGL",
                    list_name=list_name,
                    as_of=date(2026, 10, 30),
                    verdict=verdict,
                    decided_by="python",
                    python_verdict=verdict,
                    entry_ceiling=ceiling,
                    updated_at=NOW,
                )
            )
        s.add(
            ValueEffectiveRow(
                symbol="SICK",
                list_name="deep_value",
                as_of=date(2026, 10, 30),
                verdict="NO",
                decided_by="python",
                python_verdict="NO",
                entry_ceiling=50.0,
                updated_at=NOW,
            )
        )
    assert vv.put_ceiling("googl") == 180.0
    assert vv.put_ceiling("SICK") is None  # NO: no value-suggested put
```

  …and apply to `tests/conftest.py`:

```diff
diff --git a/tests/conftest.py b/tests/conftest.py
index 5ad1f43..3a81d14 100644
--- a/tests/conftest.py
+++ b/tests/conftest.py
@@ -75,6 +75,31 @@ def _clear_effective_universe_cache():
     invalidate_universe_cache()
 
 
+@pytest.fixture(autouse=True)
+def _value_view_in_tmp(monkeypatch, tmp_path_factory):
+    """The wheel reads the value book through src/common/value_view.py (Part 5). No test may read
+    the operator's data/value.db: by default it points at a file that does not exist (an empty
+    book); a test that needs one patches ``_path`` itself."""
+    monkeypatch.setattr(
+        "src.common.value_view._path",
+        lambda: tmp_path_factory.getbasetemp() / "no_value_book" / "value.db",
+    )
+
+
+@pytest.fixture()
+def value_book_db(tmp_path, monkeypatch):
+    """value.db in tmp with src/common/value_view.py pointed at the same file (Part 5)."""
+    import src.value.store as store
+
+    path = tmp_path / "value.db"
+    monkeypatch.setattr(store, "_resolve_url", lambda: f"sqlite:///{path.as_posix()}")
+    monkeypatch.setattr("src.common.value_view._path", lambda: path)
+    store.reset_engine()
+    store.init_value_db()
+    yield path
+    store.reset_engine()
+
+
 @pytest.fixture(autouse=True)
 def _value_keep_fresh_in_tmp(monkeypatch, tmp_path_factory):
     """The value process writes data/value_keep_fresh.json and (Part 4)
```

- [x] **Step 2: Run them to see them fail** — `ModuleNotFoundError: No module named 'src.common.value_view'`.
- [x] **Step 3: The tables** — apply:

```diff
diff --git a/src/value/store.py b/src/value/store.py
index 542a38d..7eddf75 100644
--- a/src/value/store.py
+++ b/src/value/store.py
@@ -40,6 +40,18 @@ Part 4 (spec §8, Claude as the analyst). Claude's half of the ticker file, ever
   ``grounding.py`` accepted it;
 - ``value_effective`` - the effective verdict per name and list, rewritten every night;
 - ``value_claude_state`` - small key/value state (the breaker).
+
+Part 5 (spec §9, revision 4: money in paper, no cash held back):
+- ``value_orders`` - every order clientId 31 sends, written **before** ``placeOrder`` with its
+  ``orderRef`` (``value:<id>``), then its fills: the value book's share count V;
+- ``value_positions`` - one per name and list while held: the live policy's exit plan (a
+  ``LegState``), the tranches done;
+- ``value_proposals`` - every buy and sell the book proposes, with who caused it, whether it
+  waits for a tap, and what the gate said;
+- ``value_funding_requests`` - capital the wheel is asked to release for an approved buy;
+- ``value_attribution`` - each shared name's reconcile (broker = wheel + value), and its freeze;
+- ``value_book_state`` - small key/value state (the book's high-water mark);
+- ``value_reevaluations.position_id`` - a held position's re-evaluation (``shadow_id`` 0).
 """
 
 from __future__ import annotations
@@ -261,6 +273,7 @@ class ValueReevaluationRow(ValueBase):
     ruleset_version: Mapped[str] = mapped_column(String(32))
     ruleset_hash: Mapped[str] = mapped_column(String(12))
     created_at: Mapped[datetime] = mapped_column(DateTime)
+    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # held (Part 5)
 
 
 class ValueClaudeReadRow(ValueBase):
@@ -411,6 +424,134 @@ class ValueClaudeStateRow(ValueBase):
     updated_at: Mapped[datetime] = mapped_column(DateTime)
 
 
+class ValueOrderRow(ValueBase):
+    """One order of the value book (spec §9.2, §9.7). Written before ``placeOrder`` so a fill
+    can never arrive for an order value.db does not know; ``order_ref`` is ``value:<id>``.
+    ``status``: pending (written, not sent) | submitted | partial | filled | cancelled |
+    rejected | error."""
+
+    __tablename__ = "value_orders"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    symbol: Mapped[str] = mapped_column(String(16), index=True)
+    list_name: Mapped[str] = mapped_column(String(16))
+    side: Mapped[str] = mapped_column(String(4))  # buy | sell
+    tranche: Mapped[int | None] = mapped_column(Integer, nullable=True)
+    reason: Mapped[str] = mapped_column(String(32), default="")
+    proposal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
+    shares: Mapped[float] = mapped_column(Float)
+    filled: Mapped[float] = mapped_column(Float, default=0.0)
+    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
+    avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
+    status: Mapped[str] = mapped_column(String(12), default="pending")
+    order_ref: Mapped[str] = mapped_column(String(32), default="")
+    ib_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
+    perm_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
+    created_at: Mapped[datetime] = mapped_column(DateTime)
+    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
+    done_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
+    detail: Mapped[str] = mapped_column(Text, default="")
+
+
+class ValuePositionRow(ValueBase):
+    """One held name on one list (spec §11): its exit plan under the live policy and its
+    tranches. ``status``: open | closed."""
+
+    __tablename__ = "value_positions"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    symbol: Mapped[str] = mapped_column(String(16), index=True)
+    list_name: Mapped[str] = mapped_column(String(16))
+    status: Mapped[str] = mapped_column(String(8), default="open")
+    opened_on: Mapped[date] = mapped_column(Date)
+    closed_on: Mapped[date | None] = mapped_column(Date, nullable=True)
+    tranches_done: Mapped[int] = mapped_column(Integer, default=0)
+    last_tranche_on: Mapped[date | None] = mapped_column(Date, nullable=True)
+    low_since_tranche: Mapped[float | None] = mapped_column(Float, nullable=True)
+    plan_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # exits.LegState
+    plan_step: Mapped[date | None] = mapped_column(Date, nullable=True)
+    decided_by: Mapped[str] = mapped_column(String(8), default="python")
+
+
+class ValueProposalRow(ValueBase):
+    """A buy or a sell the book proposes (spec §9.5, §7). ``cause``: python | claude (a sale
+    only Claude's number would make always waits for a tap). ``status``: pending (waits for a
+    tap) | approved | funding (approved, waiting for released capital) | sent | done |
+    rejected | refused (the gate said no at send time) | expired."""
+
+    __tablename__ = "value_proposals"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    kind: Mapped[str] = mapped_column(String(4))  # buy | sell
+    symbol: Mapped[str] = mapped_column(String(16), index=True)
+    list_name: Mapped[str] = mapped_column(String(16))
+    shares: Mapped[float] = mapped_column(Float)
+    price: Mapped[float | None] = mapped_column(Float, nullable=True)  # the close it was sized at
+    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)  # earmarked while approved
+    tranche: Mapped[int | None] = mapped_column(Integer, nullable=True)
+    position_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
+    reason: Mapped[str] = mapped_column(String(48))
+    cause: Mapped[str] = mapped_column(String(8), default="python")
+    needs_tap: Mapped[bool] = mapped_column(Boolean, default=True)
+    status: Mapped[str] = mapped_column(String(12), default="pending", index=True)
+    gate_json: Mapped[str] = mapped_column(Text, default="[]")
+    created_at: Mapped[datetime] = mapped_column(DateTime)
+    expires_at: Mapped[datetime] = mapped_column(DateTime)
+    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
+    decided_by: Mapped[str | None] = mapped_column(String(12), nullable=True)
+    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
+    detail: Mapped[str] = mapped_column(Text, default="")
+
+
+class ValueFundingRow(ValueBase):
+    """Capital the wheel is asked to release for an approved buy (revision 4). The trading
+    process reads open rows through ``src/common/value_view.py`` and closes eligible CSPs through
+    the Rules Engine; the value process marks the row funded when its own fresh account shows the
+    cash, or lapsed. ``status``: open | funded | lapsed."""
+
+    __tablename__ = "value_funding_requests"
+
+    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
+    proposal_id: Mapped[int] = mapped_column(Integer, index=True)
+    symbol: Mapped[str] = mapped_column(String(16))
+    needed_usd: Mapped[float] = mapped_column(Float)
+    status: Mapped[str] = mapped_column(String(8), default="open", index=True)
+    created_at: Mapped[datetime] = mapped_column(DateTime)
+    expires_at: Mapped[datetime] = mapped_column(DateTime)
+    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
+    detail: Mapped[str] = mapped_column(Text, default="")
+
+
+class ValueAttributionRow(ValueBase):
+    """One name's share reconcile (spec §9.2): broker = wheel (W) + value (V filled). ``state``:
+    ok | pending (unexplained, inside the grace) | frozen (both books stop opening on the name
+    until a human clears it)."""
+
+    __tablename__ = "value_attribution"
+
+    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
+    broker: Mapped[float] = mapped_column(Float)
+    wheel: Mapped[float] = mapped_column(Float)
+    value_filled: Mapped[float] = mapped_column(Float)
+    value_pending: Mapped[float] = mapped_column(Float, default=0.0)
+    mark: Mapped[float | None] = mapped_column(Float, nullable=True)  # the last price seen
+    state: Mapped[str] = mapped_column(String(8), default="ok")
+    since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
+    updated_at: Mapped[datetime] = mapped_column(DateTime)
+    cleared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
+    detail: Mapped[str] = mapped_column(Text, default="")
+
+
+class ValueBookStateRow(ValueBase):
+    """Small key/value state of the book (its high-water mark)."""
+
+    __tablename__ = "value_book_state"
+
+    key: Mapped[str] = mapped_column(String(32), primary_key=True)
+    value: Mapped[str] = mapped_column(Text)
+    updated_at: Mapped[datetime] = mapped_column(DateTime)
+
+
 _engine: Engine | None = None
 _SessionLocal: sessionmaker[Session] | None = None
 
@@ -419,6 +560,7 @@ _SessionLocal: sessionmaker[Session] | None = None
 _ADDED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
     "value_shadow_legs": (("plan", "VARCHAR(8) NOT NULL DEFAULT 'main'"),),
     "value_shadow_events": (("plan", "VARCHAR(8) NOT NULL DEFAULT 'main'"),),
+    "value_reevaluations": (("position_id", "INTEGER"),),
 }
 
 
```

- [x] **Step 4: The view** — create `src/common/value_view.py`:

```python
"""The wheel's only window onto the value book (spec §9.1, §9.2; revision 4).

Read-only: ``data/value.db`` opened ``mode=ro`` with plain SQL. Imports nothing from ``src.value``
and no enrichment, so the engine, the strategies and execution may import it (with
``src.common.books``) and nothing else of the value book (tests/test_value_fence.py).

``read_book`` returns ``None`` when value.db exists but cannot be read: callers then **fail
closed** (the wheel uses its own share count alone and writes no covered call on unexplained
shares). A value.db that does not exist yet, or predates the Part 5 tables, is an empty book: no
value order has ever been placed, so that is the truth.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.common.config import get_config

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ValueHolding:
    """One name's value shares: filled (bought less sold), and what open orders would add or
    take away. ``cost`` is the filled shares' cost, in dollars."""

    symbol: str
    filled: float = 0.0
    pending_buy: float = 0.0
    pending_sell: float = 0.0
    cost: float = 0.0
    mark: float | None = None  # the last price the value process saw

    @property
    def market_value(self) -> float:
        """Filled shares at the last mark, else at cost."""
        return self.filled * self.mark if self.mark is not None else self.cost

    @property
    def claimed(self) -> float:
        """The shares the wheel must never write against: filled plus pending buys."""
        return self.filled + self.pending_buy


@dataclass(frozen=True, slots=True)
class FundingRequest:
    id: int
    proposal_id: int
    symbol: str
    needed_usd: float
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class ValueBook:
    holdings: dict[str, ValueHolding] = field(default_factory=dict)
    earmarked_usd: float = 0.0  # approved buys not yet filled: cash the wheel must not re-use
    frozen: frozenset[str] = frozenset()  # names whose attribution is frozen (spec §9.2)
    requests: tuple[FundingRequest, ...] = ()  # open capital-release requests

    def holding(self, symbol: str) -> ValueHolding:
        return self.holdings.get(symbol.upper(), ValueHolding(symbol.upper()))


def _path() -> Path:
    url = get_config().value_db_url_abs()
    return Path(url[len("sqlite:///") :] if url.startswith("sqlite:///") else url)


def _naive(text: str | None) -> datetime | None:
    if not text:
        return None
    dt = datetime.fromisoformat(text)
    return dt.astimezone(UTC).replace(tzinfo=None) if dt.tzinfo else dt


def _connect(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)


def read_book(now: datetime | None = None) -> ValueBook | None:
    """The value book as the wheel sees it, or None when value.db cannot be read."""
    path = _path()
    if not path.exists():
        return ValueBook()
    now = now or datetime.now(UTC).replace(tzinfo=None)
    try:
        with _connect(path) as con:
            orders = con.execute(
                "SELECT symbol, side, shares, filled, avg_price, status FROM value_orders"
            ).fetchall()
            earmark = con.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) FROM value_proposals "
                "WHERE kind = 'buy' AND status IN ('approved', 'funding')"
            ).fetchone()[0]
            attribution = con.execute(
                "SELECT symbol, state, mark FROM value_attribution"
            ).fetchall()
            requests = con.execute(
                "SELECT id, proposal_id, symbol, needed_usd, created_at, expires_at "
                "FROM value_funding_requests WHERE status = 'open' ORDER BY id"
            ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return ValueBook()  # a value.db from before Part 5: no value order exists
        log.critical("value_view: value.db unreadable (%s): the wheel fails closed", exc)
        return None
    except sqlite3.Error as exc:
        log.critical("value_view: value.db unreadable (%s): the wheel fails closed", exc)
        return None
    acc: dict[str, dict[str, float]] = {}
    for symbol, side, shares, filled, avg, status in orders:
        h = acc.setdefault(
            symbol.upper(), dict.fromkeys(("bought", "sold", "buy", "sell", "spent"), 0.0)
        )
        done = float(filled or 0.0)
        working = status in ("pending", "submitted", "partial")
        open_qty = max(0.0, float(shares) - done) if working else 0.0
        if side == "buy":
            h["bought"] += done
            h["spent"] += done * float(avg or 0.0)
            h["buy"] += open_qty
        else:
            h["sold"] += done
            h["sell"] += open_qty
    marks = {str(sym).upper(): float(m) for sym, _, m in attribution if m is not None}
    holdings: dict[str, ValueHolding] = {}
    for s, v in acc.items():
        held = max(0.0, v["bought"] - v["sold"])
        avg_cost = v["spent"] / v["bought"] if v["bought"] else 0.0
        holdings[s] = ValueHolding(s, held, v["buy"], v["sell"], held * avg_cost, marks.get(s))
    reqs = tuple(
        FundingRequest(int(i), int(p), str(s).upper(), float(n), created, expires)
        for i, p, s, n, c, e in requests
        if (created := _naive(c)) is not None
        and (expires := _naive(e)) is not None
        and expires > now
    )
    return ValueBook(
        holdings=holdings,
        earmarked_usd=float(earmark or 0.0),
        frozen=frozenset(str(sym).upper() for sym, state, _ in attribution if state == "frozen"),
        requests=reqs,
    )


def put_ceiling(symbol: str) -> float | None:
    """Spec §9.1: the highest effective entry ceiling among the lists on which *symbol* is
    READY, WATCH or WAIT (the strike ceiling of a value-suggested put); None when it has none or
    value.db cannot be read. In live while ``value.claude.apply_live`` is off the effective
    verdict is Python's baseline already (``value_effective``)."""
    path = _path()
    if not path.exists():
        return None
    try:
        with _connect(path) as con:
            row = con.execute(
                "SELECT MAX(entry_ceiling) FROM value_effective WHERE symbol = ? "
                "AND verdict IN ('READY', 'WATCH', 'WAIT') AND entry_ceiling IS NOT NULL",
                (symbol.upper(),),
            ).fetchone()
    except sqlite3.Error:
        return None
    return None if row is None or row[0] is None else float(row[0])
```

- [x] **Step 5: Run them to see them pass** — `tests/test_value_view.py tests/test_value_store.py tests/test_value_fence.py`.
- [x] **Step 6: Gates and commit:**

  ```bash
  git add src/value/store.py src/common/value_view.py tests/conftest.py tests/value_book_fixtures.py tests/test_value_view.py
  git commit -m "feat(value): the book's tables and the wheel's read-only window (value_view)"
  ```

---

### Task 3: The attribution rule and the wheel's own share count

**Files:** Modify `src/common/books.py`; create `src/storage/wheel_shares.py`,
`tests/test_value_attribution.py`.

**Interfaces:** `books.VALUE_ORDER_PREFIX`, `is_value_order_ref`, `Attribution`,
`attribute(broker, wheel, holding | None)`, `value_sell_cap(value_filled, broker,
wheel_short_calls)`, `ValueExposure`, `value_exposure()`; `wheel_shares(symbols) ->
dict[str, WheelShares(shares, avg_cost)]`, `split_ratio(description)`.

- [x] **Step 1: Write the failing tests** — create `tests/test_value_attribution.py` (Tasks 10 and
  11 append to it):

```python
"""Share attribution (value book spec §9.2): orderRef through the ledger, the wheel's own count W,
the wheel's view, fail-closed reads and the sell cap. Several of the seven fault drills are pinned
here; tests/test_value_fault_drills.py names all seven."""

from __future__ import annotations

import pytest

from src.common.books import attribute, is_value_order_ref, value_sell_cap
from src.common.value_view import ValueHolding
from tests.value_book_fixtures import order


def test_the_wheel_sees_min_of_its_count_and_broker_less_value() -> None:
    v = ValueHolding("GOOGL", filled=30, pending_buy=10)
    ok = attribute(130, 100, v)
    assert (ok.wheel_view, ok.unexplained) == (90.0, 0.0)  # a pending buy errs short
    untagged = attribute(160, 130, ValueHolding("GOOGL", filled=30))  # a value fill counted twice
    assert untagged.unexplained == 0 and untagged.wheel_view == 130
    missing = attribute(130, 130, ValueHolding("GOOGL", filled=30))
    assert missing.unexplained == -30 and missing.wheel_view == 100  # errs short
    assert attribute(100, 120, ValueHolding("X")).wheel_view == 100  # never above the broker


def test_an_unreadable_value_db_leaves_the_wheel_only_what_the_broker_confirms() -> None:
    assert attribute(100, 100, None).wheel_view == 100
    assert attribute(130, 100, None).wheel_view == 0  # unexplained shares: no covered call


def test_a_value_sell_never_uncovers_a_wheel_call() -> None:
    assert value_sell_cap(30, 130, 1) == 30
    assert value_sell_cap(30, 120, 1) == 20  # the broker holds 20 fewer than the books say
    assert value_sell_cap(30, 100, 1) == 0
    assert is_value_order_ref("value:12") and not is_value_order_ref("CS:7")


def test_a_split_corporate_action_restates_the_wheels_count() -> None:
    from src.storage.wheel_shares import split_ratio

    assert split_ratio("GOOGL(US02079K3059) SPLIT 20 FOR 1 (GOOGL, ...)") == 20.0
    assert split_ratio("XYZ SPLIT 1 FOR 10") == 0.1
    assert split_ratio("XYZ CASH DIVIDEND 0.20 USD") is None


def test_value_exposure_is_nothing_while_the_book_is_off(value_book_db, monkeypatch) -> None:
    from src.common.books import value_exposure
    from src.common.config import get_config

    order("GOOGL", shares=100, filled=100, avg=150.0)
    off = value_exposure()
    assert (off.active, off.claim, off.by_name) == (False, 0.0, {})
    monkeypatch.setattr(get_config().value.book, "enabled", True)
    on = value_exposure()
    assert on.by_name == {"GOOGL": 15_000.0} and on.claim == pytest.approx(11_250.0)
```

- [x] **Step 2: Run them to see them fail** — `ImportError: cannot import name 'attribute'`.
- [x] **Step 3: The rule** — apply to `src/common/books.py`:

```diff
diff --git a/src/common/books.py b/src/common/books.py
index ec30b29..a33c62f 100644
--- a/src/common/books.py
+++ b/src/common/books.py
@@ -1,4 +1,4 @@
-"""Which book a contract belongs to: the wheel, or the daily credit-spread system.
+"""Which book a contract belongs to: the wheel, the daily credit-spread system or the value book.
 
 The two systems share one IBKR account and one Gateway. They never share an underlying —
 ``config/spreads.yaml → book_underlyings`` is disjoint from ``config/universe.yaml``, enforced
@@ -8,11 +8,24 @@ used: they are unique only per clientId, and the two systems place orders from d
 
 This is the only module through which wheel code (portfolio, rules engine, ledger) learns that
 the spreads book exists. It imports nothing from ``src.spreads``.
+
+**The value book (spec §9.2, Part 5) may share a ticker with the wheel**, so there the underlying
+decides nothing: every value order carries ``orderRef = "value:<id>"``, the value book keeps its own
+count V (``src/common/value_view.py``) and the wheel its own count W (from the broker-truth ledger,
+``src/storage/wheel_shares.py``), never "broker minus V". ``attribute`` is the one rule both books
+apply: the wheel sees ``min(W, broker - V claimed)`` shares, never below zero, so a race errs short;
+if value.db cannot be read the wheel uses W alone and nothing where the broker disagrees with it.
+It imports nothing from ``src.value``.
 """
 
 from __future__ import annotations
 
+from dataclasses import dataclass, field
+
 from src.common.config import get_config
+from src.common.value_view import ValueHolding, read_book
+
+VALUE_ORDER_PREFIX = "value:"
 
 # Daily-option trading classes whose statement rows name the class, not the index: an Activity
 # Statement prints an SPX daily as "SPXW 07OCT26 6800 P", so its root parses as SPXW.
@@ -30,3 +43,86 @@ def is_spreads_underlying(symbol: str | None) -> bool:
     book = spreads_underlyings()
     sym = symbol.upper()
     return sym in book or any(sym in _DAILY_ROOTS.get(b, ()) for b in book)
+
+
+def is_value_order_ref(order_ref: str | None) -> bool:
+    """True for an order the value book placed (``value:<id>``): its fills are value shares."""
+    return bool(order_ref) and str(order_ref).startswith(VALUE_ORDER_PREFIX)
+
+
+@dataclass(frozen=True, slots=True)
+class Attribution:
+    """One name's shares by book. ``wheel_view`` is what the wheel may write calls against and
+    count as its own; ``unexplained`` is broker - (W + V filled): anything but zero is a reconcile
+    failure (spec §9.2)."""
+
+    broker: float
+    wheel: float
+    value_filled: float
+    value_claimed: float
+    wheel_view: float
+    unexplained: float
+
+
+def attribute(broker: float, wheel: float, holding: ValueHolding | None) -> Attribution:
+    """Spec §9.2. *holding* None means value.db could not be read: the wheel then uses W alone,
+    and only where the broker agrees with W (no covered call on unexplained shares)."""
+    if holding is None:
+        view = wheel if abs(broker - wheel) < 1e-6 else 0.0
+        return Attribution(broker, wheel, 0.0, 0.0, max(0.0, view), broker - wheel)
+    view = max(0.0, min(wheel, broker - holding.claimed))
+    return Attribution(
+        broker=broker,
+        wheel=wheel,
+        value_filled=holding.filled,
+        value_claimed=holding.claimed,
+        wheel_view=view,
+        unexplained=broker - (wheel + holding.filled),
+    )
+
+
+def value_sell_cap(value_filled: float, broker: float, wheel_short_calls: int) -> float:
+    """Spec §9.2: a value sale never crosses books: at most the value lots, and never so many that
+    the wheel's open short calls (100 shares each) are left uncovered, even when attribution is in
+    doubt."""
+    return max(0.0, min(value_filled, broker - 100.0 * max(0, wheel_short_calls)))
+
+
+@dataclass(frozen=True, slots=True)
+class ValueExposure:
+    """What the wheel's caps must count of the value book (spec §9.3 as amended by revision 4:
+    no cash is reserved; the book's actual holdings and approved-but-unfilled buys are)."""
+
+    active: bool  # value book.enabled: otherwise nothing below applies and the wheel is unchanged
+    readable: bool  # False: value.db could not be read and the book is on (fail closed)
+    claim: float = 0.0  # subtracted from excess liquidity before the wheel's reserve
+    by_name: dict[str, float] = field(default_factory=dict)  # value market value per name
+    earmarked: float = 0.0  # approved value buys not yet filled
+    frozen: frozenset[str] = frozenset()
+
+    @property
+    def gross(self) -> float:
+        return sum(self.by_name.values()) + self.earmarked
+
+
+def value_exposure() -> ValueExposure:
+    """Spec §9.3 item 1: ``claim = Σ value market value x (1 - m) + earmarked buys``, m the
+    maintenance rate (``portfolio.value_maintenance_pct``, 25%: buying $X of stock with cash
+    lowers excess liquidity by only m x X, so subtracting less would hand the wheel the rest).
+    Off (and free of I/O) while ``value.book.enabled`` is false."""
+    cfg = get_config()
+    if not cfg.value.book.enabled:
+        return ValueExposure(active=False, readable=True)
+    book = read_book()
+    if book is None:
+        return ValueExposure(active=True, readable=False)
+    m = float(cfg.risk.get("portfolio", {}).get("value_maintenance_pct", 25.0)) / 100.0
+    by_name = {s: h.market_value for s, h in book.holdings.items() if h.market_value > 0}
+    return ValueExposure(
+        active=True,
+        readable=True,
+        claim=sum(by_name.values()) * (1.0 - m) + book.earmarked_usd,
+        by_name=by_name,
+        earmarked=book.earmarked_usd,
+        frozen=book.frozen,
+    )
```

- [x] **Step 4: W** — create `src/storage/wheel_shares.py`:

```python
"""The wheel's own share count W (value book spec §9.2, Part 5): every stock execution in the
broker-truth ledger that is not the value book's or the spreads book's — the wheel's fills, its
assignments and exercises, and manual trades — never "broker minus the value book".

Read-only (``session_scope`` reads, no write). Average cost by the average-cost method over the
executions in time order; a forward or reverse split the ledger records as a corporate action
("SPLIT 2 FOR 1", "4 FOR 1", ...) multiplies the count at its date (cost unchanged). A corporate
action it cannot read leaves W unadjusted, so the reconcile flags the name (fail closed). The
ledger starts at its first import, so stock held from before it
reads as unexplained on a ticker the value book shares; import the account's history (Flex or an
Activity CSV) before the first value buy (SETUP §19).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select

from src.storage.db import session_scope
from src.storage.models import BrokerCorporateActionRow, BrokerExecutionRow

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class WheelShares:
    shares: float
    avg_cost: float | None  # None when no buy is recorded


def wheel_shares(symbols: list[str]) -> dict[str, WheelShares]:
    """W per symbol (zero shares when the ledger holds none for it)."""
    wanted = sorted({s.upper() for s in symbols})
    out = {s: WheelShares(0.0, None) for s in wanted}
    if not wanted:
        return out
    with session_scope() as s:
        rows = s.execute(
            select(
                BrokerExecutionRow.underlying,
                BrokerExecutionRow.trade_time,
                BrokerExecutionRow.quantity,
                BrokerExecutionRow.price,
            ).where(
                BrokerExecutionRow.sec_type == "STK",
                BrokerExecutionRow.superseded_by.is_(None),
                BrokerExecutionRow.book.not_in(("value", "spreads")),
                BrokerExecutionRow.underlying.in_(wanted),
            )
        ).all()
        actions = s.execute(
            select(
                BrokerCorporateActionRow.underlying,
                BrokerCorporateActionRow.event_date,
                BrokerCorporateActionRow.description,
            ).where(BrokerCorporateActionRow.underlying.in_(wanted))
        ).all()
    events: list[tuple[str, datetime, int, float, float]] = [
        (sym, when, 1, qty, price) for sym, when, qty, price in rows
    ]
    for sym, day, description in actions:
        ratio = split_ratio(description or "")
        if sym and ratio:
            events.append((sym, datetime.combine(day, datetime.min.time()), 0, ratio, 0.0))
    events.sort(key=lambda e: (e[0], e[1], e[2]))
    state: dict[str, tuple[float, float]] = {}  # symbol -> (shares, cost)
    for symbol, _, kind, qty, price in events:
        shares, cost = state.get(symbol, (0.0, 0.0))
        if kind == 0:
            shares *= qty  # a split: the same cost over more (or fewer) shares
        elif qty > 0:
            shares, cost = shares + qty, cost + qty * price
        elif shares > 0:
            sold = min(-qty, shares)
            cost -= cost / shares * sold
            shares -= -qty
        else:
            shares += qty
        state[symbol] = (shares, max(0.0, cost))
    for symbol, (shares, cost) in state.items():
        out[symbol] = WheelShares(shares, cost / shares if shares > 0 else None)
    return out


_SPLIT = re.compile(r"(\d+(?:\.\d+)?)\s*FOR\s*(\d+(?:\.\d+)?)", re.I)


def split_ratio(description: str) -> float | None:
    """The share multiple of a split corporate action ("... SPLIT 2 FOR 1" -> 2.0, "1 FOR 10"
    -> 0.1), or None when the text names no split."""
    if "SPLIT" not in description.upper():
        return None
    m = _SPLIT.search(description)
    if m is None or float(m.group(2)) == 0:
        return None
    return float(m.group(1)) / float(m.group(2))
```

- [x] **Step 5: Run them to see them pass** — `tests/test_value_attribution.py tests/test_ledger_ingest.py tests/test_engine.py`
  (books.py is imported by the engine: the engine suite must stay green).
- [x] **Step 6: Gates and commit:**

  ```bash
  git add src/common/books.py src/storage/wheel_shares.py tests/test_value_attribution.py
  git commit -m "feat(value): the attribution rule and the wheel's own share count from the ledger"
  ```

- [ ] **Section A exit** — full gate (baseline + 12), protected-file diff, `git status --short`
  clean; fill the row; `git commit -m "docs(plan): value book Part 5 Progress log - Section A"`.

---

## Section B — The Rules Engine and capital release (Tasks 4–6) · model: opus · effort: high

**Before this section runs, the operator approves the Rules-Engine edits E1–E3 and E5–E7** (the
table under "Rulings") and answers ruling 7's question (default: a release inherits its buy's
approval). The orchestrator records the answers in the Progress log.

**Spec to read:** §9.1 (the put flow), §9.3 with its revision-4 note, §13 failure mode 1, §21.
Root `CLAUDE.md`: the core invariant, "Analytics tiers" (the `min_credit` paragraph's pattern for a
gate the generator mirrors).

**Files the subagent reads:** `src/engine/capital.py`, `src/engine/risk_engine.py` (lines 150–560),
`src/strategies/cash_secured_put.py` (lines 120–160), `src/engine/regime_limits.py` (lines
505–545), `src/execution/position_manager.py`, `src/execution/profit_take.py` (lines 99–137,
225–300), `src/notify/approval_service.py` (lines 1600–1630), `src/notify/command_drain.py` (lines
272–355), `tests/test_engine.py` (lines 49–130), `tests/test_drain_promote.py` (lines 1–120,
333–370), `docs/web/commands.md` (the promote table).

**Entry checks:**

- [ ] **B1. Section A is in**, the gate green at baseline + 12, the operator's approval recorded.
- [ ] **B2. The code Section B edits** (none of it is Part 4's; `main` at `da5d3c3`):

  ```bash
  grep -nF 'def resolve_caps(account: AccountSnapshot, risk: dict) -> Caps:' src/engine/capital.py   # 79:
  grep -nF '    caps: Caps | None = None,' src/engine/capital.py   # 132:
  grep -nF '    caps = resolve_caps(account, risk)' src/engine/risk_engine.py   # 237:
  grep -nF '            reasons.append("reserved_for_spreads_book")' src/engine/risk_engine.py   # 253:
  grep -nF '        reasons.extend(_cumulative_reasons(cand, sector, check_caps, budgets))' src/engine/risk_engine.py   # 489:
  grep -nF '    caps = resolve_caps(account, risk)' src/strategies/cash_secured_put.py   # 145:
  grep -nF '    caps = resolve_caps(account, cfg.risk)' src/engine/regime_limits.py   # 528:
  grep -nF '  max_new_positions_per_run: 10' config/examples/risk_limits.yaml   # 158:
  grep -nF '    DEFENSIVE = "defensive"  # operator tapped Close' src/common/schemas.py   # 1025:
  grep -nF '            detail=f"buy-to-close ({reason.value})",' src/execution/position_manager.py   # 112:
  grep -nF '            # 1a. Loss-exit check' src/notify/approval_service.py   # 1617:
  grep -nF 'CloseReason: "profit_take" | "loss_exit" | "roll" | "manual" | "defensive";' web/lib/api-types.ts   # 2258:
  grep -nF '        raise CommandFailed("contract_not_priced", {"priced_count": len(priced.quotes)})' src/notify/command_drain.py   # 320:
  grep -nF '| It priced but scored below the floor | `score_below_minimum` | the score and the threshold |' docs/web/commands.md   # 168:
  ```

**Section exit:** three task commits plus `docs(plan)`; full gate with pytest = baseline + 23 (12 + 7 +
3 + 1); protected-file diff; `git diff --stat main...HEAD -- web` lists only
`web/lib/api-types.ts`; the engine, sizer, profit-take and promote suites green.

---

### Task 4: The Rules Engine counts the value book; the release gate and selection

**Files:** Modify `src/engine/capital.py`, `src/engine/risk_engine.py`,
`src/strategies/cash_secured_put.py`, `src/engine/regime_limits.py`,
`config/examples/risk_limits.yaml`; create `tests/test_value_capital_release.py` (Task 5 appends).

**Interfaces:** `resolve_caps(account, risk, *, value_claim=0.0)`; `seed_budgets(..., *, caps=None,
extra_exposure=None)`; `ReleaseCandidate` (`mid`, `profit_pct`, `released`, `given_up`);
`release_reasons(c, release, *, closes_today, released_today, net_liq)`; `select_releases(eligible,
needed, release)`; `validate_release(c, *, right, closes_today, released_today, net_liq)`; new
reasons `book_attribution_mismatch`, `value_book_unreadable`, `gross_notional_cap`,
`combined_name_cap` (all only with `value.book.enabled`); risk keys
`portfolio.max_gross_notional_pct`, `max_combined_name_pct`, `value_maintenance_pct`.

The pinned numbers: a $100,000 account with $60,000 of excess liquidity and a 20% reserve deploys
$48,000; $20,000 of value stock at 25% maintenance claims $15,000, leaving $36,000. The gross cap:
$40,000 of wheel stock + $15,000 of value stock + a $30,000 approved buy + a $16,000 put is $101,000
(refused); a $14,000 put fits. Selection: A (strike 100, credit 2.00, mid 1.00: 50% kept, frees
$10,000), B (150, 2.00, 1.80: 10%, $15,000), C (60, 1.00, 0.20: 80%, $6,000): a $14,000 need takes B
alone; $9,000 takes A (a preferred close, $100 given up); $15,000 takes A and C; $17,000 takes nothing.

- [ ] **Step 1: Write the failing tests** — create `tests/test_value_capital_release.py`:

```python
"""The wheel's side of the value book (value book spec §9.2-§9.3 as amended by revision 4): the
value claim on excess liquidity, the gross and combined caps, the attribution freeze, and
capital release - the selection, the Rules Engine's release gate and the runner."""

from __future__ import annotations

import pytest

from src.common.config import get_config
from src.common.schemas import AccountSnapshot, OptionRight, PositionSnapshot
from src.engine.capital import ReleaseCandidate, resolve_caps, seed_budgets, select_releases
from src.engine.risk_engine import validate_candidates, validate_release
from src.value.store import ValueAttributionRow, value_session
from tests.test_engine import _candidate
from tests.value_book_fixtures import NOW, order, proposal

RELEASE = get_config().value.book.release.model_dump()


@pytest.fixture()
def book_on(monkeypatch):
    monkeypatch.setattr(get_config().value.book, "enabled", True)


def _acct(net_liq: float = 100_000.0, excess: float = 60_000.0) -> AccountSnapshot:
    return AccountSnapshot(
        account="DU1",
        net_liquidation=net_liq,
        total_cash=excess,
        buying_power=excess,
        maintenance_margin=0.0,
        excess_liquidity=excess,
    )


def test_the_value_claim_comes_off_excess_liquidity_before_the_reserve() -> None:
    risk = {"portfolio": {"cash_reserve_pct": 20.0, "cash_reserve_absolute": 0}}
    assert resolve_caps(_acct(), risk).deployable_cash == pytest.approx(48_000.0)
    # $20,000 of value stock at 25% maintenance claims $15,000; reserve 20% of 45,000
    assert resolve_caps(_acct(), risk, value_claim=15_000.0).deployable_cash == pytest.approx(
        36_000.0
    )
    budgets = seed_budgets([], lambda s: None, extra_exposure={"GOOGL": 20_000.0})
    assert budgets.ticker_collateral == {"GOOGL": 20_000.0}


def test_with_the_book_off_the_wheel_is_unchanged(value_book_db) -> None:
    order("AAPL", shares=100, filled=100, avg=150.0)  # a value holding the wheel would count
    big = _candidate(collateral=90_000.0, contracts=1)
    before = validate_candidates([big], _acct(), [])[0].reasons
    assert "gross_notional_cap" not in before and "combined_name_cap" not in before


def test_the_gross_cap_counts_both_books_and_approved_buys(value_book_db, book_on) -> None:
    order("GOOGL", shares=100, filled=100, avg=150.0)  # $15,000 of value stock at cost
    proposal("META", status="funding", cost=30_000.0)  # approved, not yet bought: earmarked
    stock = PositionSnapshot(
        symbol="MSFT",
        sec_type="STK",
        position=100,
        avg_cost=380.0,
        market_value=40_000.0,
        underlying="MSFT",
    )
    # 40,000 wheel stock + 15,000 value + 30,000 earmarked + 16,000 put = 101,000 > 100,000
    out = validate_candidates([_candidate(collateral=16_000.0)], _acct(), [stock])[0].reasons
    assert "gross_notional_cap" in out
    ok = validate_candidates([_candidate(collateral=14_000.0)], _acct(), [stock])[0].reasons
    assert "gross_notional_cap" not in ok


def test_the_combined_name_cap_and_the_freeze(value_book_db, book_on) -> None:
    order("AAPL", shares=50, filled=50, avg=150.0)  # $7,500 of AAPL in the value book
    over = validate_candidates([_candidate(collateral=8_000.0)], _acct(), [])[0].reasons
    assert "combined_name_cap" in over  # 7,500 + 8,000 > 15% of 100,000
    with value_session() as s:
        s.add(
            ValueAttributionRow(
                symbol="AAPL",
                broker=150,
                wheel=100,
                value_filled=50,
                state="frozen",
                updated_at=NOW,
            )
        )
    frozen = validate_candidates([_candidate(collateral=1_000.0)], _acct(), [])[0].reasons
    assert "book_attribution_mismatch" in frozen


def test_an_unreadable_value_db_refuses_new_puts(monkeypatch, tmp_path, book_on) -> None:
    bad = tmp_path / "value.db"
    bad.write_bytes(b"garbage")
    monkeypatch.setattr("src.common.value_view._path", lambda: bad)
    out = validate_candidates([_candidate(collateral=1_000.0)], _acct(), [])[0].reasons
    assert "value_book_unreadable" in out


def _c(key: str, strike: float, credit: float, mid: float, contracts: int = 1) -> ReleaseCandidate:
    return ReleaseCandidate(
        key, key.split(":")[0], strike, contracts, credit, mid - 0.05, mid + 0.05
    )


def test_the_fewest_closes_that_cover_the_need_never_a_partial_one() -> None:
    a = _c("AAA:1", 100.0, 2.0, 1.0)  # 50% kept, frees 10,000
    b = _c("BBB:1", 150.0, 2.0, 1.8)  # 10% kept, frees 15,000
    c = _c("CCC:1", 60.0, 1.0, 0.2)  # 80% kept, frees 6,000
    assert select_releases([a, b, c], 14_000.0, RELEASE) == [b]  # one close covers it
    assert select_releases([a, b, c], 9_000.0, RELEASE) == [a]  # both A-tier would; least given up
    assert select_releases([a, c], 15_000.0, RELEASE) == [a, c]
    assert select_releases([a, c], 17_000.0, RELEASE) == []  # not enough: release nothing
    assert select_releases([a], 0.0, RELEASE) == []


def test_the_release_gate_never_closes_at_a_loss_or_a_call_and_caps_the_day() -> None:
    win = _c("AAA:1", 100.0, 2.0, 1.0)
    loss = _c("BBB:1", 100.0, 2.0, 2.2)
    args = dict(closes_today=0, released_today=0.0, net_liq=100_000.0)
    assert validate_release(win, right=OptionRight.PUT, **args) == []
    assert "release_at_loss" in validate_release(loss, right=OptionRight.PUT, **args)
    assert "release_not_csp" in validate_release(win, right=OptionRight.CALL, **args)
    capped = validate_release(
        win, right=OptionRight.PUT, closes_today=4, released_today=5_000.0, net_liq=100_000.0
    )
    assert capped == ["release_daily_cap", "release_daily_notional"]  # 15,000 > 10% of 100,000
    wide = ReleaseCandidate("W:1", "W", 100.0, 1, 2.0, 0.5, 1.5)
    assert "release_spread_too_wide" in validate_release(wide, right=OptionRight.PUT, **args)
```

- [ ] **Step 2: Run them to see them fail** — `ImportError: cannot import name 'ReleaseCandidate'`.
- [ ] **Step 3: The engine** — apply:

```diff
diff --git a/config/examples/risk_limits.yaml b/config/examples/risk_limits.yaml
index 7995955..63d8e01 100644
--- a/config/examples/risk_limits.yaml
+++ b/config/examples/risk_limits.yaml
@@ -157,6 +157,16 @@ portfolio:
   max_margin_usage_pct: 50.0
   max_new_positions_per_run: 10
 
+  # 4. Both books (value book spec §9.2-§9.3, revision 4). Stock (wheel and value) + CSP collateral
+  #    + cash earmarked for an approved value buy may not exceed this share of net liq: the value
+  #    book's cash-only rule and the wheel's CSPs meet here. And one name's exposure across both
+  #    books (CSP collateral + stock of both) may not exceed max_combined_name_pct of net liq.
+  max_gross_notional_pct: 100.0
+  max_combined_name_pct: 15.0
+  # The maintenance rate m of value stock: the wheel's excess liquidity is reduced by the value
+  # book's market value x (1 - m) (a lower m subtracts more: errs safe). Only with value book.enabled.
+  value_maintenance_pct: 25.0
+
 # --- Market regime (analytics/regime.py -> engine/regime_limits.py) ---
 # A deterministic classification of SPY and QQQ (normal / cautious / stressed / crisis) that
 # shrinks NEW cash-secured puts in a falling market. Covered calls, rolls, closes, profit-takes
diff --git a/src/engine/capital.py b/src/engine/capital.py
index e369be1..042c350 100644
--- a/src/engine/capital.py
+++ b/src/engine/capital.py
@@ -24,6 +24,7 @@ gap.
 
 from __future__ import annotations
 
+import itertools
 import math
 from collections.abc import Callable
 from dataclasses import dataclass, field, replace
@@ -76,16 +77,21 @@ class Budgets:
     large_tickers: set[str] = field(default_factory=set)
 
 
-def resolve_caps(account: AccountSnapshot, risk: dict) -> Caps:
+def resolve_caps(account: AccountSnapshot, risk: dict, *, value_claim: float = 0.0) -> Caps:
     """Resolve config percentages into absolute dollar limits for this account.
 
     Order of application is fixed and deliberately not configurable: the cash reserve comes
     off first, and the CSP budget is a percentage of what remains. Expressing both against
     gross cash would let the two knobs contradict each other.
+
+    *value_claim* (value book spec §9.3 item 1, revision 4; ``books.value_exposure().claim``)
+    comes off excess liquidity before the reserve: the value book's whole contribution to it
+    (its stock at (1 - maintenance) plus approved buys not yet filled), so the wheel is never
+    handed the liquidity value stock bought with cash still appears to leave.
     """
     p = risk.get("portfolio", {})
     net_liq = max(0.0, account.net_liquidation)
-    cash = max(0.0, account.excess_liquidity)
+    cash = max(0.0, account.excess_liquidity - max(0.0, value_claim))
 
     reserve = max(
         cash * float(p.get("cash_reserve_pct", 20.0)) / 100.0,
@@ -130,9 +136,14 @@ def seed_budgets(
     iv_of: Callable[[str], float | None] | None = None,
     *,
     caps: Caps | None = None,
+    extra_exposure: dict[str, float] | None = None,
 ) -> Budgets:
     """Seed running tallies from current positions.
 
+    *extra_exposure* (value book spec §9.2, Part 5: ``books.value_exposure().by_name``) adds the
+    value book's stock in a name to that name's collateral tally, so exposure is counted once
+    across both books though the wheel's positions hold only its own shares.
+
     A short put contributes its assignment liability (strike x 100 x |contracts|), not the
     option's tiny market value — matching exactly how a *new* CSP candidate is charged, so
     existing and proposed positions share one consistent budget (N5). Everything else is
@@ -187,6 +198,8 @@ def seed_budgets(
         if sector:
             budgets.sector_risk[sector] = budgets.sector_risk.get(sector, 0.0) + units
 
+    for key, exposure in (extra_exposure or {}).items():
+        budgets.ticker_collateral[key] = budgets.ticker_collateral.get(key, 0.0) + exposure
     if caps is not None:
         for key, collateral in budgets.ticker_collateral.items():
             if collateral > caps.max_ticker_collateral:
@@ -321,3 +334,112 @@ def charge(
             budgets.sector_risk[sector] = budgets.sector_risk.get(sector, 0.0) + units
     if cum_before + collateral > caps.max_ticker_collateral:
         budgets.large_tickers.add(symbol)
+
+
+# --- Capital release (value book spec revision 4, operator 2026-10-30) ---------------------------
+
+
+@dataclass(frozen=True)
+class ReleaseCandidate:
+    """One wheel cash-secured put that might be closed to fund an approved value buy. Prices are
+    per share; ``entry_credit`` is the roll chain's net credit (``chain_entry_credit_per_share``)."""
+
+    key: str  # the contract, for logs and the close's idempotency
+    underlying: str
+    strike: float
+    contracts: int
+    entry_credit: float
+    bid: float
+    ask: float | None
+
+    @property
+    def mid(self) -> float | None:
+        if self.ask is None or self.ask <= 0:
+            return None
+        return (self.bid + self.ask) / 2 if self.bid > 0 else self.ask
+
+    @property
+    def profit_pct(self) -> float | None:
+        """Share of the entry credit kept by closing at mid now (the profit-take arithmetic)."""
+        mid = self.mid
+        if mid is None or self.entry_credit <= 0:
+            return None
+        return (1.0 - mid / self.entry_credit) * 100.0
+
+    @property
+    def released(self) -> float:
+        """Collateral the close frees: strike x 100 x contracts."""
+        return self.strike * 100.0 * self.contracts
+
+    @property
+    def given_up(self) -> float:
+        """The premium still to earn that closing now forgoes: mid x 100 x contracts."""
+        mid = self.mid
+        return 0.0 if mid is None else mid * 100.0 * self.contracts
+
+
+def release_reasons(
+    c: ReleaseCandidate,
+    release: dict,
+    *,
+    closes_today: int,
+    released_today: float,
+    net_liq: float,
+) -> list[str]:
+    """Why *c* may not be closed for capital, from its quote and the day's counts. Pure. Never
+    at a loss: a close below ``min_profit_pct`` of the entry credit (0: breakeven) is refused."""
+    reasons: list[str] = []
+    mid = c.mid
+    if mid is None:
+        return ["release_no_quote"]
+    ask = c.ask or 0.0
+    if c.bid > 0 and (ask - c.bid) / mid * 100.0 > float(release.get("max_spread_pct", 25.0)):
+        reasons.append("release_spread_too_wide")
+    profit = c.profit_pct
+    if profit is None or profit < float(release.get("min_profit_pct", 0.0)):
+        reasons.append("release_at_loss")
+    if closes_today >= int(release.get("max_closes_per_day", 4)):
+        reasons.append("release_daily_cap")
+    cap = net_liq * float(release.get("max_release_pct_per_day", 10.0)) / 100.0
+    if released_today + c.released > cap:
+        reasons.append("release_daily_notional")
+    return reasons
+
+
+def select_releases(
+    eligible: list[ReleaseCandidate], needed: float, release: dict
+) -> list[ReleaseCandidate]:
+    """The fewest closes whose freed collateral covers *needed*, or ``[]`` when no allowed set
+    does (never a partial release: nothing is closed for a buy that still could not be funded).
+
+    Among sets of the smallest size: fewest closes under ``preferred_profit_pct``, then the least
+    premium given up, then the most capital released per dollar given up. Candidates are the 20
+    best by released per dollar given up, so the search stays small; at most
+    ``max_closes_per_request`` closes. Deterministic: ties break on the contract key."""
+    if needed <= 0:
+        return []
+    preferred = float(release.get("preferred_profit_pct", 25.0))
+    limit = int(release.get("max_closes_per_request", 3))
+
+    def ratio(c: ReleaseCandidate) -> float:
+        return c.released / max(c.given_up, 0.01)
+
+    pool = sorted(eligible, key=lambda c: (-ratio(c), c.key))[:20]
+    for size in range(1, limit + 1):
+        sets = [
+            combo
+            for combo in itertools.combinations(pool, size)
+            if sum(c.released for c in combo) >= needed
+        ]
+        if sets:
+            best = min(
+                sets,
+                key=lambda combo: (
+                    sum(1 for c in combo if (c.profit_pct or 0.0) < preferred),
+                    round(sum(c.given_up for c in combo), 2),
+                    -sum(c.released for c in combo) / max(sum(c.given_up for c in combo), 0.01),
+                    tuple(sorted(c.key for c in combo)),
+                ),
+            )
+            return sorted(best, key=lambda c: c.key)
+    return []
diff --git a/src/engine/regime_limits.py b/src/engine/regime_limits.py
index 5a9b90d..361a5a3 100644
--- a/src/engine/regime_limits.py
+++ b/src/engine/regime_limits.py
@@ -52,6 +52,7 @@ from __future__ import annotations
 import math
 from typing import Literal
 
+from src.common.books import value_exposure
 from src.common.config import (
     ClaudeCutCfg,
     get_cc_timing_cfg,
@@ -525,14 +526,15 @@ def scaled_budget_fit(
     if ticker == 1.0 and book == 1.0 and not floor_lot:
         return None
     cfg = get_config()
-    caps = resolve_caps(account, cfg.risk)
+    vx = value_exposure()  # the value book, counted as the gate counts it (Part 5)
+    caps = resolve_caps(account, cfg.risk, value_claim=vx.claim)
     use = (
         caps
         if floor_lot and floor_left(ctx, cand.underlying, {}) > 0
         else scale_caps(caps, ticker=ticker, book=book)
     )
     sector_of = (cfg.universe.get("sectors") or {}).get
-    budgets = seed_budgets(positions, sector_of, caps=caps)
+    budgets = seed_budgets(positions, sector_of, caps=caps, extra_exposure=vx.by_name)
     fit, _ = max_contracts(
         unit_collateral=cand.strike * 100.0,
         current_iv=cand.current_iv,
diff --git a/src/engine/risk_engine.py b/src/engine/risk_engine.py
index ef5691b..8b53291 100644
--- a/src/engine/risk_engine.py
+++ b/src/engine/risk_engine.py
@@ -14,7 +14,7 @@ the cumulative budgets are consumed greedily in that order.
 
 from __future__ import annotations
 
-from src.common.books import is_spreads_underlying
+from src.common.books import ValueExposure, is_spreads_underlying, value_exposure
 from src.common.config import get_config
 from src.common.market_hours import today_et
 from src.common.schemas import (
@@ -31,7 +31,9 @@ from src.common.schemas import (
 from src.engine.capital import (
     Budgets,
     Caps,
+    ReleaseCandidate,
     charge,
+    release_reasons,
     resolve_caps,
     risk_units,
     scale_caps,
@@ -234,10 +236,21 @@ def validate_candidates(
     min_iv_rv = iv_cfg.get("min_iv_rv_ratio")
     blackout_days = events.get("earnings_blackout_days", 0)
 
-    caps = resolve_caps(account, risk)
+    # The value book (spec §9.2-§9.3, revision 4): off -> nothing below changes the wheel.
+    vx: ValueExposure = value_exposure()
+    caps = resolve_caps(account, risk, value_claim=vx.claim)
     sector_of_fn = get_config().universe.get("sectors", {}).get
     budgets: Budgets = seed_budgets(
-        positions, sector_of_fn, iv_by_symbol.get if iv_by_symbol else None, caps=caps
+        positions,
+        sector_of_fn,
+        iv_by_symbol.get if iv_by_symbol else None,
+        caps=caps,
+        extra_exposure=vx.by_name,
+    )
+    gross_cap = net_liq * float(portfolio.get("max_gross_notional_pct", 100.0)) / 100.0
+    combined_cap = net_liq * float(portfolio.get("max_combined_name_pct", 15.0)) / 100.0
+    wheel_stock = sum(
+        abs(p.market_value or 0.0) for p in positions if p.sec_type == "STK" and p.position
     )
 
     # --- Pass 1: per-candidate gates. No shared budget is read or written here, so these
@@ -251,6 +264,14 @@ def validate_candidates(
         # override could still put one in front of the wheel; it must never reach an order.
         if is_spreads_underlying(cand.underlying):
             reasons.append("reserved_for_spreads_book")
+        # Value book (spec §9.2): a name whose share attribution is frozen takes no new put and
+        # no new call until a human clears it; with the book on and value.db unreadable, no
+        # new put at all (the gross and combined caps cannot be measured: fail closed).
+        if vx.active and cand.strategy in (Strategy.CASH_SECURED_PUT, Strategy.COVERED_CALL):
+            if cand.underlying.upper() in vx.frozen:
+                reasons.append("book_attribution_mismatch")
+            if not vx.readable and cand.strategy == Strategy.CASH_SECURED_PUT:
+                reasons.append("value_book_unreadable")
 
         # --- Income quality gates. Scoped to the income strategies: a ROLL is a defensive
         # repair, not an income trade. A roll that pays a debit to move a challenged short
@@ -487,6 +508,16 @@ def validate_candidates(
             ticker_mult, book_mult = multipliers(sizing, cand.underlying)
             check_caps = scale_caps(caps, ticker=ticker_mult, book=book_mult)
         reasons.extend(_cumulative_reasons(cand, sector, check_caps, budgets))
+        if vx.active and is_csp:
+            # Spec §9.3 item 3: stock of both books + CSP collateral (this batch's accepted lots
+            # included) + approved value buys + this put, within the gross cap of net liq.
+            if wheel_stock + budgets.csp_collateral + vx.gross + cand.collateral > gross_cap:
+                reasons.append("gross_notional_cap")
+            # Spec §9.2: one name across both books, where the value book holds it.
+            if vx.by_name.get(cand.underlying.upper(), 0.0) > 0 and (
+                budgets.ticker_collateral.get(cand.underlying, 0.0) + cand.collateral > combined_cap
+            ):
+                reasons.append("combined_name_cap")
 
         took_floor = False
         if regime_active:
@@ -696,3 +727,30 @@ def validate_live_quote(
         verdict=Verdict.PASS if not reasons else Verdict.REJECT,
         reasons=reasons,
     )
+
+
+def validate_release(
+    c: ReleaseCandidate,
+    *,
+    right: OptionRight | None,
+    closes_today: int,
+    released_today: float,
+    net_liq: float,
+) -> list[str]:
+    """The Rules Engine's gate for a capital-release close (value book spec revision 4): a wheel
+    cash-secured put bought back at breakeven or better to fund an approved value buy.
+    Deterministic, no LLM. Run at decision time and again at send time on a fresh quote
+    (``src/execution/capital_release.py``); an empty list passes. Only a put frees cash, so a
+    call is refused; so is a spreads-book contract (the wheel never touches one)."""
+    release = get_config().value.book.release.model_dump()
+    reasons: list[str] = []
+    if right != OptionRight.PUT:
+        reasons.append("release_not_csp")
+    if is_spreads_underlying(c.underlying):
+        reasons.append("reserved_for_spreads_book")
+    if c.contracts < 1:
+        reasons.append("no_contracts")
+    reasons += release_reasons(
+        c, release, closes_today=closes_today, released_today=released_today, net_liq=net_liq
+    )
+    return reasons
diff --git a/src/strategies/cash_secured_put.py b/src/strategies/cash_secured_put.py
index cc33311..2082cfb 100644
--- a/src/strategies/cash_secured_put.py
+++ b/src/strategies/cash_secured_put.py
@@ -10,6 +10,7 @@ from src.analytics.liquidity import (
     score_liquidity,
     volume_gate_active,
 )
+from src.common.books import value_exposure
 from src.common.config import get_config
 from src.common.schemas import (
     AccountSnapshot,
@@ -142,11 +143,16 @@ def screen_csp_candidates(
     dte_min: int = csp_cfg["dte_min"]
     dte_max: int = csp_cfg["dte_max"]
     hard_max: int = csp_cfg.get("max_contracts", 10)
-    caps = resolve_caps(account, risk)
+    # The value book's holdings and approved buys (value book spec §9.3, revision 4), exactly as
+    # the gate counts them, so the sizer and the gate cannot disagree; off -> no change.
+    vx = value_exposure()
+    caps = resolve_caps(account, risk, value_claim=vx.claim)
     sector_of = cfg.universe.get("sectors", {}).get
     # Budgets are seeded with the UNSCALED caps (so the large-position slots never move with the
     # regime); the scaled caps below are used only for the size checks.
-    budgets: Budgets = seed_budgets(positions or [], sector_of, caps=caps)
+    budgets: Budgets = seed_budgets(
+        positions or [], sector_of, caps=caps, extra_exposure=vx.by_name
+    )
     sector = sector_of(symbol)
     regime_on = active(sizing)
     scaled_caps = caps
```

- [ ] **Step 4: Run them to see them pass** — `tests/test_value_capital_release.py tests/test_engine.py tests/test_capital.py tests/test_config_keys.py tests/test_regime_sizing_integration.py tests/test_scale_in_gate.py tests/test_cc_breakout.py`.
- [ ] **Step 5: Gates and commit:**

  ```bash
  git add src/engine/capital.py src/engine/risk_engine.py src/strategies/cash_secured_put.py src/engine/regime_limits.py config/examples/risk_limits.yaml tests/test_value_capital_release.py
  git commit -m "feat(engine): the Rules Engine counts the value book; the capital-release gate"
  ```

---

### Task 5: The capital-release runner in the trading process

**Files:** Create `src/execution/capital_release.py`; modify `src/common/schemas.py` (the
`CloseReason` enum only), `src/execution/position_manager.py`, `src/notify/approval_service.py`,
`docs/web/openapi.json`, `web/lib/api-types.ts`, `tests/test_value_capital_release.py`.

**Interfaces:** `CloseReason.CAPITAL_RELEASE`; `close_short_position(..., reason, note="")`;
`run_capital_release(ib_scan, ib_exec, bot=None, chat_id=None, *, quote=None, positions_fn=None,
net_liq_fn=None, close=close_short_position) -> int`; `day_counts(orders)`,
`request_progress(orders, request_id)`.

- [ ] **Step 0: `web/` rule.** Invoke the `da-vinci` skill (the operator's rule for any `web/`
  change) and record that the change is one generated type line, no UI. Never run `npm` or `next`.
- [ ] **Step 1: Write the failing tests** — apply:

```diff
diff --git a/tests/test_value_capital_release.py b/tests/test_value_capital_release.py
index ce5b444..17b1bc6 100644
--- a/tests/test_value_capital_release.py
+++ b/tests/test_value_capital_release.py
@@ -4,15 +4,19 @@ capital release - the selection, the Rules Engine's release gate and the runner.
 
 from __future__ import annotations
 
+import asyncio
+from datetime import date, datetime, timedelta
+
 import pytest
 
 from src.common.config import get_config
-from src.common.schemas import AccountSnapshot, OptionRight, PositionSnapshot
+from src.common.schemas import AccountSnapshot, CloseReason, OptionRight, PositionSnapshot
 from src.engine.capital import ReleaseCandidate, resolve_caps, seed_budgets, select_releases
 from src.engine.risk_engine import validate_candidates, validate_release
+from src.execution.position_manager import CloseResult
 from src.value.store import ValueAttributionRow, value_session
 from tests.test_engine import _candidate
-from tests.value_book_fixtures import NOW, order, proposal
+from tests.value_book_fixtures import NOW, funding, order, proposal
 
 RELEASE = get_config().value.book.release.model_dump()
 
@@ -126,3 +130,89 @@ def test_the_release_gate_never_closes_at_a_loss_or_a_call_and_caps_the_day() ->
     assert capped == ["release_daily_cap", "release_daily_notional"]  # 15,000 > 10% of 100,000
     wide = ReleaseCandidate("W:1", "W", 100.0, 1, 2.0, 0.5, 1.5)
     assert "release_spread_too_wide" in validate_release(wide, right=OptionRight.PUT, **args)
+
+
+def _put(symbol: str, strike: float, qty: int = -1) -> PositionSnapshot:
+    return PositionSnapshot(
+        symbol=f"{symbol} P",
+        sec_type="OPT",
+        position=qty,
+        avg_cost=0.0,
+        right=OptionRight.PUT,
+        strike=strike,
+        expiry=date.today() + timedelta(days=20),
+        underlying=symbol,
+    )
+
+
+def test_the_runner_closes_after_a_second_gate_on_a_fresh_quote(
+    value_book_db, book_on, monkeypatch, db
+) -> None:
+    from src.execution import capital_release as cr
+
+    funding("GOOGL", 9_000.0, proposal_id=proposal("GOOGL", status="funding", cost=15_000.0))
+    credits = {"AAA": 2.0, "BBB": 2.0}
+    monkeypatch.setattr(cr, "chain_entry_credit_per_share", lambda s, pos: credits[pos.underlying])
+    monkeypatch.setattr(cr, "is_halted", lambda: False)
+    quotes = {"AAA": [(0.95, 1.05), (0.95, 1.05)], "BBB": [(1.75, 1.85)]}
+    closes: list[tuple[str, CloseReason, str]] = []
+
+    async def quote(pos):
+        return quotes[pos.underlying].pop(0)
+
+    async def close(ib, pos, bid, ask, *, reason, note):
+        closes.append((pos.underlying, reason, note))
+        return CloseResult("filled", pos.symbol, 1, (bid + ask) / 2, 1, (bid + ask) / 2)
+
+    async def net_liq():
+        return 100_000.0
+
+    sent = asyncio.run(
+        cr.run_capital_release(
+            object(),
+            object(),
+            quote=quote,
+            positions_fn=lambda: [_put("AAA", 100.0), _put("BBB", 150.0)],
+            net_liq_fn=net_liq,
+            close=close,
+        )
+    )
+    # AAA (50% kept, frees 10,000) covers the 9,000 need alone; BBB is not touched
+    assert sent == 1 and closes == [("AAA", CloseReason.CAPITAL_RELEASE, closes[0][2])]
+    assert closes[0][2].startswith("capital release request 1 ")
+
+
+def test_the_runner_waits_while_halted_or_with_the_book_off(value_book_db, monkeypatch) -> None:
+    from src.execution import capital_release as cr
+
+    funding("GOOGL", 9_000.0)
+    assert asyncio.run(cr.run_capital_release(object(), object())) == 0  # book off
+    monkeypatch.setattr(get_config().value.book, "enabled", True)
+    monkeypatch.setattr(cr, "is_halted", lambda: True)
+    assert asyncio.run(cr.run_capital_release(object(), object())) == 0
+
+
+def test_request_progress_reads_its_own_closes(db) -> None:
+    from src.execution.capital_release import day_counts, request_progress
+    from src.storage.models import OrderRow
+
+    with db() as s:
+        for state, filled, note in (("filled", 1, "request 3"), ("submitted", 0, "request 4")):
+            s.add(
+                OrderRow(
+                    candidate_id="close:AAA:20261120:100:P",
+                    state=state,
+                    limit_price=1.0,
+                    filled_qty=filled,
+                    detail=f"buy-to-close (capital_release) capital release {note} for GOOGL",
+                    close_reason="capital_release",
+                    created_at=datetime.now(),
+                )
+            )
+    with db() as s:
+        from sqlalchemy import select
+
+        rows = list(s.scalars(select(OrderRow)))
+    assert request_progress(rows, 3) == (False, 10_000.0)
+    assert request_progress(rows, 4) == (True, 0.0)
+    assert day_counts(rows) == (2, 10_000.0)
```

- [ ] **Step 2: Run them to see them fail** — `ModuleNotFoundError: No module named 'src.execution.capital_release'`.
- [ ] **Step 3: The enum, the close note, the hook** — apply:

```diff
diff --git a/src/common/schemas.py b/src/common/schemas.py
index 908ade3..021b62f 100644
--- a/src/common/schemas.py
+++ b/src/common/schemas.py
@@ -1023,6 +1023,9 @@ class CloseReason(StrEnum):
     ROLL = "roll"  # the buy-back leg of an executed roll
     MANUAL = "manual"  # closed outside the system; recorded by external-close reconciliation
     DEFENSIVE = "defensive"  # operator tapped Close on a roll-policy `close` decision
+    # A CSP at breakeven or better closed to fund an approved value-book buy (value book spec
+    # revision 4, 2026-10-30): src/execution/capital_release.py, gated by the Rules Engine.
+    CAPITAL_RELEASE = "capital_release"
 
 
 RollAction = Literal["roll", "assign", "let_called_away", "close", "hold", "defer"]
diff --git a/src/execution/position_manager.py b/src/execution/position_manager.py
index 7cc59d0..48b08d6 100644
--- a/src/execution/position_manager.py
+++ b/src/execution/position_manager.py
@@ -80,6 +80,7 @@ async def close_short_position(
     ask: float,
     *,
     reason: CloseReason,
+    note: str = "",
 ) -> CloseResult:
     """Buy-to-close a short option position at mid, recording the full order/fill lifecycle.
 
@@ -109,7 +110,7 @@ async def close_short_position(
             state=OrderState.QUEUED,
             limit_price=limit_price,
             is_live=cfg.is_live,
-            detail=f"buy-to-close ({reason.value})",
+            detail=f"buy-to-close ({reason.value}){' ' + note if note else ''}",
             close_reason=reason.value,
         )
         session.add(order_row)
diff --git a/src/notify/approval_service.py b/src/notify/approval_service.py
index 682ab98..1fc9798 100644
--- a/src/notify/approval_service.py
+++ b/src/notify/approval_service.py
@@ -1621,6 +1621,17 @@ async def _intraday_scan_loop(
                 except Exception:
                     logger.exception("Intraday loop: loss-exit check failed")
 
+            # 1a'. Capital release (value book revision 4): close CSPs at breakeven or better
+            #     to fund an approved value buy, gated by the Rules Engine. Off unless the value
+            #     book is enabled; idle while halted.
+            if ib_scan.isConnected():
+                try:
+                    from src.execution.capital_release import run_capital_release
+
+                    await run_capital_release(ib_scan, ib_exec, bot, chat_id)
+                except Exception:
+                    logger.exception("Intraday loop: capital release failed")
+
             # 1b. Periodic reconciliation (SYSTEM_REVIEW F7): recover entry fills missed during a
             #     mid-session reconnect, and record manual buy-to-closes done in TWS.
             if ib_exec is not None and ib_exec.isConnected():
diff --git a/web/lib/api-types.ts b/web/lib/api-types.ts
index 630e5ff..9b6f3d4 100644
--- a/web/lib/api-types.ts
+++ b/web/lib/api-types.ts
@@ -2255,7 +2255,7 @@ export interface components {
          *     so profit-takes can be analysed apart from loss exits, rolls and hand-placed closes.
          * @enum {string}
          */
-        CloseReason: "profit_take" | "loss_exit" | "roll" | "manual" | "defensive";
+        CloseReason: "profit_take" | "loss_exit" | "roll" | "manual" | "defensive" | "capital_release";
         /** ClusterOut */
         ClusterOut: {
             /** Id */
```

- [ ] **Step 4: The runner** — create `src/execution/capital_release.py`:

```python
"""Capital release (value book spec revision 4, operator decision 2026-10-30).

The value book holds no cash back: the wheel sells cash-secured puts against the whole account.
When an approved value buy cannot be funded, the value process opens a funding request in
value.db; this module, run by the trading process every intraday cycle, reads the open requests
through the read-only ``src/common/value_view.py`` and closes the fewest wheel CSPs at breakeven or
better that free enough collateral (``capital.select_releases``), each gated by the Rules Engine
(``risk_engine.validate_release``) at decision time and again at send time on a fresh quote, and
sent through the wheel's own close path (``position_manager.close_short_position``: a LimitOrder
at mid, ``qualifyContracts``, cancel on timeout, the order/fill record, idempotent per contract),
stamped ``CloseReason.CAPITAL_RELEASE`` with the request in the order's detail.

It never buys: the value process confirms the freed cash on its own fresh account snapshot and
only then re-gates and sends the buy. A request exists only for an approved buy, so a release
inherits the buy's approval (ruling 15). Nothing here reads an LLM output. Skipped while halted
(the buy could not send) and while the book or release is off.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime

from ib_async import IB
from sqlalchemy import select
from telegram import Bot

from src.common.config import get_config
from src.common.market_hours import today_et
from src.common.schemas import CloseReason, OptionRight, OrderState, PositionSnapshot
from src.common.value_view import FundingRequest, read_book
from src.engine.capital import ReleaseCandidate, select_releases
from src.engine.risk_engine import validate_release
from src.execution.position_manager import CloseResult, close_candidate_id, close_short_position
from src.storage.db import session_scope
from src.storage.models import OrderRow
from src.storage.roll_chains import chain_entry_credit_per_share
from src.storage.system_settings import is_halted

log = logging.getLogger(__name__)
_REQUEST = re.compile(r"capital release request (\d+)\b")
_CLOSE_ID = re.compile(r"^close:[^:]+:\d{8}:([0-9.]+):P$")


def _today_orders() -> list[OrderRow]:
    start = datetime.combine(today_et(), datetime.min.time())
    with session_scope() as s:
        return list(
            s.scalars(
                select(OrderRow).where(
                    OrderRow.close_reason == CloseReason.CAPITAL_RELEASE.value,
                    OrderRow.created_at >= start,
                )
            )
        )


def _strike(candidate_id: str) -> float | None:
    m = _CLOSE_ID.match(candidate_id or "")
    return float(m.group(1)) if m else None


def day_counts(orders: list[OrderRow]) -> tuple[int, float]:
    """(capital-release closes sent today, collateral they released), from today's orders."""
    sent = [o for o in orders if o.state not in (OrderState.REJECTED, OrderState.CANCELLED)]
    released = 0.0
    for o in sent:
        strike = _strike(o.candidate_id)
        if strike is not None:
            released += strike * 100.0 * float(o.filled_qty or 0.0)
    return len(sent), released


def request_progress(orders: list[OrderRow], request_id: int) -> tuple[bool, float]:
    """(a close for this request is still working, collateral already released for it)."""
    working, released = False, 0.0
    for o in orders:
        m = _REQUEST.search(o.detail or "")
        if m is None or int(m.group(1)) != request_id:
            continue
        if o.state in (OrderState.QUEUED, OrderState.SUBMITTED):
            working = True
        strike = _strike(o.candidate_id)
        if strike is not None:
            released += strike * 100.0 * float(o.filled_qty or 0.0)
    return working, released


Quote = Callable[[PositionSnapshot], Awaitable[tuple[float, float | None]]]


async def run_capital_release(
    ib_scan: IB,
    ib_exec: IB | None,
    bot: Bot | None = None,
    chat_id: str | None = None,
    *,
    quote: Quote | None = None,
    positions_fn: Callable[[], list[PositionSnapshot]] | None = None,
    net_liq_fn: Callable[[], Awaitable[float]] | None = None,
    close: Callable[..., Awaitable[CloseResult]] = close_short_position,
) -> int:
    """Service every open funding request once. Returns the closes sent."""
    cfg = get_config()
    book_cfg = cfg.value.book
    if not (book_cfg.enabled and book_cfg.release.enabled) or ib_exec is None or is_halted():
        return 0
    book = read_book()
    if book is None or not book.requests:
        return 0
    from src.execution.profit_take import _quote_short
    from src.ibkr.portfolio import get_account_snapshot_async, get_positions

    async def _net_liq() -> float:
        snap = await get_account_snapshot_async(ib_scan, cfg.secrets.ibkr_account or "")
        return snap.net_liquidation

    quote = quote or (lambda pos: _quote_short(ib_scan, pos))
    positions = (positions_fn or (lambda: get_positions(ib_scan)))()
    puts = [
        p
        for p in positions
        if p.sec_type == "OPT"
        and p.right == OptionRight.PUT
        and p.position < 0
        and p.strike
        and p.expiry is not None
    ]
    if not puts:
        return 0
    net_liq = await (net_liq_fn or _net_liq)()
    sent = 0
    for req in book.requests:
        sent += await _service(req, puts, net_liq, quote, close, ib_exec)
    return sent


async def _candidate(pos: PositionSnapshot, quote: Quote) -> ReleaseCandidate | None:
    with session_scope() as s:
        credit = chain_entry_credit_per_share(s, pos)
    if credit is None or credit <= 0:
        return None
    bid, ask = await quote(pos)
    assert pos.strike is not None
    return ReleaseCandidate(
        key=close_candidate_id(pos),
        underlying=(pos.underlying or pos.symbol).upper(),
        strike=float(pos.strike),
        contracts=int(abs(pos.position)),
        entry_credit=credit,
        bid=bid,
        ask=ask,
    )


async def _service(
    req: FundingRequest,
    puts: list[PositionSnapshot],
    net_liq: float,
    quote: Quote,
    close: Callable[..., Awaitable[CloseResult]],
    ib_exec: IB,
) -> int:
    orders = _today_orders()
    working, released = request_progress(orders, req.id)
    needed = req.needed_usd - released
    if working or needed <= 0:
        return 0
    closes_today, released_today = day_counts(orders)
    by_key: dict[str, PositionSnapshot] = {}
    eligible: list[ReleaseCandidate] = []
    for pos in puts:
        c = await _candidate(pos, quote)
        if c is None:
            continue
        reasons = validate_release(
            c,
            right=pos.right,
            closes_today=closes_today,
            released_today=released_today,
            net_liq=net_liq,
        )
        if not reasons:  # decision-time gate
            eligible.append(c)
            by_key[c.key] = pos
    chosen = select_releases(eligible, needed, get_config().value.book.release.model_dump())
    if not chosen:
        log.info("capital release: request %d (%s) cannot be funded now", req.id, req.symbol)
        return 0
    sent = 0
    for c in chosen:
        pos = by_key[c.key]
        fresh = await _candidate(pos, quote)  # send-time gate on a fresh quote
        reasons = (
            ["release_no_quote"]
            if fresh is None
            else validate_release(
                fresh,
                right=pos.right,
                closes_today=closes_today + sent,
                released_today=released_today,
                net_liq=net_liq,
            )
        )
        if fresh is None or reasons:
            log.warning("capital release: %s refused at send time: %s", c.key, reasons)
            return sent  # the set no longer covers the request: the rest waits a cycle
        result = await close(
            ib_exec,
            pos,
            fresh.bid,
            fresh.ask or 0.0,
            reason=CloseReason.CAPITAL_RELEASE,
            note=f"capital release request {req.id} for {req.symbol}",
        )
        log.info("capital release: %s for request %d -> %s", c.key, req.id, result.status)
        if result.status in ("filled", "partial", "working"):
            sent += 1
        released_today += c.released
    return sent
```

- [ ] **Step 5: The OpenAPI document** (it exposes `CloseReason`) — regenerate from the worktree root:

  ```bash
  .venv/bin/python -c "import json; from src.api.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json
  ```

  `git diff --stat docs/web/openapi.json` shows a 3-line change (the enum gains `capital_release`).
- [ ] **Step 6: Run them to see them pass** — `tests/test_value_capital_release.py tests/test_openapi_current.py tests/test_position_manager.py tests/test_close_fill_recovery.py`.
- [ ] **Step 7: Gates and commit:**

  ```bash
  git add src/execution/capital_release.py src/common/schemas.py src/execution/position_manager.py src/notify/approval_service.py docs/web/openapi.json web/lib/api-types.ts tests/test_value_capital_release.py
  git commit -m "feat(execution): capital release - close CSPs at breakeven or better to fund a value buy"
  ```

---

### Task 6: A value-suggested put is refused above the value ceiling

**Files:** Modify `src/notify/command_drain.py`, `tests/test_drain_promote.py`, `docs/web/commands.md`.

- [ ] **Step 1: The failing test** — apply:

```diff
diff --git a/tests/test_drain_promote.py b/tests/test_drain_promote.py
index aa39ce2..3443925 100644
--- a/tests/test_drain_promote.py
+++ b/tests/test_drain_promote.py
@@ -652,3 +652,24 @@ async def test_a_score_floor_staged_promote_succeeds_despite_the_low_score(
     approval_id = drain_env.result(cid)["approval_id"]
     assert approval_id is not None
     assert drain_env.approval_status(approval_id) == ApprovalStatus.PENDING
+
+
+@pytest.mark.asyncio
+async def test_a_value_put_above_the_value_ceiling_is_refused(
+    drain_env, fake_chain, monkeypatch
+) -> None:
+    """Value book §9.1: a value-suggested promote re-reads the strike ceiling at drain time; it
+    can only narrow what the wheel would send (the gate still runs for any strike under it)."""
+    from src.notify.command_drain import drain_once
+
+    monkeypatch.setattr("src.common.value_view.put_ceiling", lambda symbol: 170.0)
+    drain_env.seed_assessed("c1", stage="top_n", symbol="NVDA", strike=180.0)
+    fake_chain.will_price("NVDA", strike=180.0, gate="pass")
+    cid = drain_env.enqueue("promote", {**_payload(), "value_put": True})
+
+    await drain_once(drain_env.ib, drain_env.bot, "chat")
+
+    assert drain_env.status(cid) == "failed"
+    result = drain_env.result(cid)
+    assert result["reason"] == "above_value_ceiling"
+    assert result["detail"] == {"strike": 180.0, "ceiling": 170.0}
```

- [ ] **Step 2: Run it to see it fail** — the command is `applied`, not `failed`.
- [ ] **Step 3: The refusal and its doc** — apply:

```diff
diff --git a/docs/web/commands.md b/docs/web/commands.md
index 8dd50b4..081d0a3 100644
--- a/docs/web/commands.md
+++ b/docs/web/commands.md
@@ -166,6 +166,7 @@ with the most specific reason available:
 | The contract no longer prices | `contract_not_priced` | how many contracts were priced |
 | The Rules Engine now rejects it | `gate_rejected` | the verdict's `reasons` list, verbatim |
 | It priced but scored below the floor | `score_below_minimum` | the score and the threshold |
+| A value-suggested put (`value_put: true`, value book Part 5) is struck above the value book's ceiling, or the name has none | `above_value_ceiling` | the strike and the ceiling (`null` when none) |
 
 `chain_unavailable` is deliberately one reason covering two internal causes: a chain-fetch
 failure and an analytics/account-fetch failure both mean the same thing to the operator — there
diff --git a/src/notify/command_drain.py b/src/notify/command_drain.py
index 710c4d6..0a8013b 100644
--- a/src/notify/command_drain.py
+++ b/src/notify/command_drain.py
@@ -319,6 +319,16 @@ async def _promote(*, command: Any, ib: Any, bot: Any, chat_id: str, **_: Any) -
     if match is None:
         raise CommandFailed("contract_not_priced", {"priced_count": len(priced.quotes)})
 
+    if command.payload.get("value_put"):
+        # Value book §9.1: a value-suggested put may not be struck above the price worth paying,
+        # read now through the read-only value view (no value book code is imported). Part 6's
+        # strip sets the flag (and adds it to the API model); it can only narrow what is sent.
+        from src.common.value_view import put_ceiling
+
+        ceiling = put_ceiling(payload.symbol)
+        if ceiling is None or match.strike > ceiling:
+            raise CommandFailed("above_value_ceiling", {"strike": match.strike, "ceiling": ceiling})
+
     verdict = priced.verdict_map.get(match.candidate_id)
     if verdict is None or verdict.verdict.value != "pass":
         reasons = list(verdict.reasons) if verdict is not None else []
```

- [ ] **Step 4: Run it to see it pass** — `tests/test_drain_promote.py tests/test_openapi_current.py`.
- [ ] **Step 5: Gates and commit:**

  ```bash
  git add src/notify/command_drain.py tests/test_drain_promote.py docs/web/commands.md
  git commit -m "feat(notify): promote refuses a value put above the value book's ceiling (spec 9.1)"
  ```

- [ ] **Section B exit** — full gate (baseline + 23), protected-file diff, the `web` diff, clean
  status; fill the row; `git commit -m "docs(plan): value book Part 5 Progress log - Section B"`.

---

## Section C — The value gate, the book, the executor (Tasks 7–9) · model: sonnet · effort: high

**Spec to read:** §7 (the exits and "Which fair value an exit reads"), §7.1 ("What a re-evaluation
does" step 1), §9.4, §9.5, §9.6, §9.7, §11, §21.

**Files the subagent reads:** `src/value/exits.py`, `src/value/scorecard.py`, `src/value/store.py`,
`src/value/claude_reads.py` (`queue_read`), `src/common/value_view.py`, `src/common/books.py`,
`src/spreads/executor.py` (the pattern), `src/ibkr/market_data.py` (`req_fresh_mkt_data`'s
docstring), `tests/value_fixtures.py`.

**Entry checks:**

- [ ] **C1. Section B is in**, the gate green at baseline + 23.
- [ ] **C2. The code Section C edits:**

  ```bash
  grep -nF '        "revenue_cagr_5y": cagr([y.revenue for y in years]),' src/value/scorecard.py   # 291:   (Part 4 left it unchanged)
  grep -nF 'def queue_read(' src/value/claude_reads.py   # 152:   (Part 4)
  ```

  `ls src/value/risk.py src/value/book.py` fails (none exists yet).

**Section exit:** three task commits plus `docs(plan)`; full gate with pytest = baseline + 62 (23 +
23 + 14 + 2); `py_compile scripts/run_value.py` silent; protected-file diff; clean status.

---

### Task 7: The value gate and sizing

**Files:** Create `src/value/risk.py`, `src/value/sizing.py`, `tests/test_value_risk.py`; modify
`src/value/scorecard.py` (one metric).

**Interfaces:** `risk.BuyContext`, `risk.validate(ctx, book, *, max_gross_notional_pct,
max_combined_name_pct) -> list[str]`, `risk.FUNDABLE`, `risk.fundable_only`; `sizing.tier_pct`,
`ceiling_usd`, `target_cost`, `tranche_shares`, `tranche_due`, `trend_brake`, `month_end_closes`;
the scorecard's `metrics["adv_dollar_20"]`.

The pinned numbers: a $100,000 account's ceiling is $30,000 and its name cap $2,400; a deep-value
margin of 50% buys 8% of the ceiling ($2,400; $1,200 under the trend brake), in thirds: $800 at $75
is 10 shares, and with $2,000 already held only $400 more (5 shares).

- [ ] **Step 1: Write the failing tests** — create `tests/test_value_risk.py`:

```python
"""The value gate and sizing (value book spec §9.4-§9.6 as amended by revision 4). Pure."""

from __future__ import annotations

from dataclasses import replace

import pytest

from src.common.config import get_config
from src.value import sizing
from src.value.risk import BuyContext, fundable_only, validate

BOOK = get_config().value.book
# A $100,000 account; the book's ceiling is 30% = $30,000; the name cap 8% of it = $2,400.
OK = BuyContext(
    symbol="GOOGL",
    list_name="quality_growth",
    shares=10,
    price=150.0,
    verdict="READY",
    mos=0.25,
    required_mos_pct=10.0,
    mos_review=False,
    health="pass",
    data_quality="pass",
    timing="pass",
    earnings_in_window=False,
    net_liq=100_000.0,
    ceiling=30_000.0,
    book_cost=5_000.0,
    list_cost=5_000.0,
    name_cost=0.0,
    holds_name=False,
    positions_open=3,
    wheel_name_exposure=10_000.0,
    gross_used=80_000.0,
    adv_dollar_20=5_000_000_000.0,
)


def _v(ctx: BuyContext) -> list[str]:
    return validate(ctx, BOOK, max_gross_notional_pct=100.0, max_combined_name_pct=15.0)


def test_a_clean_buy_passes() -> None:
    assert _v(OK) == []


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"verdict": "WATCH"}, "verdict_not_ready"),
        ({"health": "fail"}, "health_gate_failed"),
        ({"mos_review": True}, "data_unreliable"),
        ({"mos": 0.05}, "mos_below_required"),
        ({"timing": "unknown"}, "timing_not_ready"),
        ({"earnings_in_window": None}, "earnings_within_window"),  # unknown is never a pass
        ({"attribution": "pending"}, "book_attribution_mismatch"),
        ({"adds_paused": True}, "adds_paused"),
        ({"trend_brake": True}, "trend_brake"),
        ({"drawdown_stop": True}, "sleeve_breaker"),
        ({"book_cost": 29_000.0}, "sleeve_exhausted"),
        ({"name_cost": 1_000.0}, "name_cap"),  # 1,000 + 1,500 > 2,400
        ({"list_cost": 20_000.0}, "list_share_cap"),  # 20,000 + 1,500 > 21,000
        ({"positions_open": 20}, "max_positions"),
        ({"wheel_name_exposure": 14_000.0}, "combined_name_cap"),
        ({"gross_used": 99_000.0}, "gross_notional_cap"),
        ({"adv_dollar_20": 100_000.0}, "illiquid"),
        ({"quote_age_seconds": 45.0}, "price_stale_at_send"),
        ({"is_live": True}, "not_paper"),
        ({"spreads_underlying": True}, "reserved_for_spreads_book"),
    ],
)
def test_every_reason(change, reason) -> None:
    assert reason in _v(replace(OK, **change))


def test_only_the_gross_cap_is_curable_by_released_capital() -> None:
    assert fundable_only(_v(replace(OK, gross_used=99_000.0)))
    assert not fundable_only(_v(replace(OK, gross_used=99_000.0, timing="fail")))
    assert not fundable_only([])


def test_tiers_tranches_and_the_trend_brake() -> None:
    rows = BOOK.tiers.deep_value
    assert [sizing.tier_pct(m, rows) for m in (20.0, 25.0, 40.0, 50.0, None)] == [
        0.0,
        3.0,
        5.0,
        8.0,
        0.0,
    ]
    # $100,000 net liq: ceiling 30,000; a 50% deep-value margin buys 8% = 2,400, in thirds
    assert sizing.target_cost("deep_value", 0.50, 100_000.0, BOOK, trend_brake=False) == 2_400.0
    assert sizing.target_cost("deep_value", 0.50, 100_000.0, BOOK, trend_brake=True) == 1_200.0
    assert sizing.tranche_shares(2_400.0, 3, 75.0, 0.0) == 10  # 800 / 75
    assert sizing.tranche_shares(2_400.0, 3, 75.0, 2_000.0) == 5  # never past the target
    lows = [10.0, 9.0, 8.5, 8.8, 9.0, 9.1, 9.2, 9.3, 9.4, 9.5]
    assert sizing.tranche_due(0, None, [], 10.0, None, BOOK)
    assert sizing.tranche_due(1, 10, lows, 10.0, None, BOOK)  # 9.1 > 8.5: a higher low
    assert not sizing.tranche_due(1, 3, lows, 10.0, None, BOOK)  # too soon
    assert sizing.tranche_due(2, 6, [], 10.0, 9.5, BOOK) and not sizing.tranche_due(
        2, 6, [], 9.0, 9.5, BOOK
    )
    assert not sizing.tranche_due(3, 10, [], 10.0, 9.0, BOOK)
    assert sizing.trend_brake([100.0] * 9 + [90.0]) is True
    assert sizing.trend_brake([100.0] * 9) is None
```

- [ ] **Step 2: Run them to see them fail** — `ModuleNotFoundError: No module named 'src.value.risk'`.
- [ ] **Step 3: The gate** — create `src/value/risk.py`:

```python
"""The value book's gate (spec §9.4, amended by revision 4). Pure: no I/O, no model call.

Run at decision time (on the close) and again at send time (on a fresh quote). Every reason is a
refusal; ``FUNDABLE`` names the one a released capital can cure (the gross cap: the account's
stock and CSP collateral leave no room for a cash buy). What an LLM produced reaches it only as
the effective verdict and fair value (``value_effective``), which Python computed from bounded
drivers and clamped, and in live only once ``value.claude.apply_live`` is on (the effective
verdict is then Python's baseline); the gate reads no other Claude table.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.common.config import ValueBookCfg

FUNDABLE = frozenset({"gross_notional_cap"})


@dataclass(frozen=True, slots=True)
class BuyContext:
    symbol: str
    list_name: str
    shares: int
    price: float
    verdict: str  # the effective verdict
    mos: float | None  # the effective margin of safety, a fraction
    required_mos_pct: float
    mos_review: bool
    health: str
    data_quality: str
    timing: str
    earnings_in_window: bool | None
    net_liq: float
    ceiling: float  # the book's ceiling in dollars (halved by the trend brake)
    book_cost: float  # the book's cost: filled lots and working buys
    list_cost: float
    name_cost: float
    holds_name: bool
    positions_open: int
    wheel_name_exposure: float  # the wheel's CSP collateral and stock in the name
    gross_used: float  # stock of both books + CSP collateral + other approved buys
    adv_dollar_20: float | None
    attribution: str = "ok"  # ok | pending | frozen
    adds_paused: bool = False
    trend_brake: bool = False
    drawdown_stop: bool = False
    is_live: bool = False
    halted: bool = False
    spreads_underlying: bool = False
    quote_age_seconds: float | None = None  # None at decision time

    @property
    def cost(self) -> float:
        return self.shares * self.price


def validate(
    ctx: BuyContext,
    book: ValueBookCfg,
    *,
    max_gross_notional_pct: float,
    max_combined_name_pct: float,
) -> list[str]:
    reasons: list[str] = []
    if ctx.is_live:
        reasons.append("not_paper")  # Stage 3 is paper only until a separate live plan
    if ctx.halted:
        reasons.append("halted")
    if ctx.spreads_underlying:
        reasons.append("reserved_for_spreads_book")
    if ctx.shares < 1 or ctx.price <= 0:
        reasons.append("no_shares")
    if ctx.verdict != "READY":
        reasons.append("verdict_not_ready")
    if ctx.health != "pass":
        reasons.append("health_gate_failed")
    if ctx.data_quality != "pass" or ctx.mos_review:
        reasons.append("data_unreliable")
    if ctx.mos is None or ctx.mos * 100.0 < ctx.required_mos_pct:
        reasons.append("mos_below_required")
    if ctx.timing != "pass":
        reasons.append("timing_not_ready")
    if ctx.earnings_in_window is not False:
        reasons.append("earnings_within_window")
    if ctx.attribution != "ok":
        reasons.append("book_attribution_mismatch")
    if ctx.adds_paused:
        reasons.append("adds_paused")
    if ctx.trend_brake:
        reasons.append("trend_brake")
    if ctx.drawdown_stop:
        reasons.append("sleeve_breaker")
    cost = ctx.cost
    if ctx.book_cost + cost > ctx.ceiling:
        reasons.append("sleeve_exhausted")
    if ctx.name_cost + cost > ctx.ceiling * book.name_cap_pct / 100.0:
        reasons.append("name_cap")
    if ctx.list_cost + cost > ctx.ceiling * book.max_list_share_pct / 100.0:
        reasons.append("list_share_cap")
    if not ctx.holds_name and ctx.positions_open >= book.max_positions:
        reasons.append("max_positions")
    if ctx.wheel_name_exposure + ctx.name_cost + cost > ctx.net_liq * max_combined_name_pct / 100:
        reasons.append("combined_name_cap")
    if ctx.gross_used + cost > ctx.net_liq * max_gross_notional_pct / 100.0:
        reasons.append("gross_notional_cap")
    if ctx.adv_dollar_20 is None or (ctx.name_cost + cost) > ctx.adv_dollar_20 * (
        book.illiquid_adv_pct / 100.0
    ):
        reasons.append("illiquid")
    if ctx.quote_age_seconds is not None and ctx.quote_age_seconds > book.quote_max_age_seconds:
        reasons.append("price_stale_at_send")
    return reasons


def fundable_only(reasons: list[str]) -> bool:
    """True when released capital would let the buy pass: the gross cap is its only refusal."""
    return bool(reasons) and set(reasons) <= FUNDABLE
```

- [ ] **Step 4: Sizing** — create `src/value/sizing.py`:

```python
"""Sizing and tranches (spec §9.5, §9.6 as amended by revision 4). Pure: no I/O.

The book holds no cash back; its ``ceiling_pct_of_net_liq`` is a ceiling on what it may hold at
cost, and every size is a share of that ceiling: a margin of safety in a list's tier buys that
tier's percentage of the ceiling (8% at most, the name cap), entered in tranches of a third:
the first at READY, the second on a higher low, the third on a close above the 50-day SMA, at
least ``tranche_min_sessions`` apart, each re-gated. A slow trend brake (SPY's month-end close
under its 10-month SMA) halves the ceiling and stops new entries (spec §9.6).
"""

from __future__ import annotations

import math
from datetime import date

from src.common.config import ValueBookCfg

TEN_MONTHS = 10


def tier_pct(mos_pct: float | None, rows: list[tuple[float, float]]) -> float:
    """The size (percent of the ceiling) the margin of safety reaches; 0 below the first row
    or when the margin is unknown."""
    if mos_pct is None:
        return 0.0
    size = 0.0
    for start, pct in rows:
        if mos_pct >= start:
            size = pct
    return size


def ceiling_usd(net_liq: float, cfg: ValueBookCfg, *, trend_brake: bool) -> float:
    cap = max(0.0, net_liq) * cfg.ceiling_pct_of_net_liq / 100.0
    return cap * (cfg.trend_brake_ceiling_pct / 100.0 if trend_brake else 1.0)


def target_cost(
    list_name: str, mos: float | None, net_liq: float, cfg: ValueBookCfg, *, trend_brake: bool
) -> float:
    """The whole position's cost: the tier's share of the ceiling, never above the name cap."""
    ceiling = ceiling_usd(net_liq, cfg, trend_brake=trend_brake)
    rows = getattr(cfg.tiers, list_name)
    pct = min(tier_pct(None if mos is None else mos * 100.0, rows), cfg.name_cap_pct)
    return ceiling * pct / 100.0


def tranche_shares(target: float, tranches: int, price: float, held_cost: float) -> int:
    """Shares for the next tranche: a third of the target (never past it), whole shares."""
    if price <= 0 or tranches < 1:
        return 0
    cost = min(target / tranches, max(0.0, target - held_cost))
    return max(0, math.floor(cost / price))


def tranche_due(
    done: int,
    sessions_since_last: int | None,
    lows_since_last: list[float],
    close: float,
    sma50: float | None,
    cfg: ValueBookCfg,
) -> bool:
    """Whether the next tranche is due: the first at READY; the second on a higher low (the
    last five sessions' low above the low before them, since the last tranche); the third on a
    close above the 50-day SMA. Never two within ``tranche_min_sessions``."""
    if done >= cfg.tranches:
        return False
    if done == 0:
        return True
    if sessions_since_last is None or sessions_since_last < cfg.tranche_min_sessions:
        return False
    if done == 1:
        return len(lows_since_last) >= 10 and min(lows_since_last[-5:]) > min(lows_since_last[:-5])
    return sma50 is not None and close > sma50


def trend_brake(month_end_closes: list[float]) -> bool | None:
    """SPY's last month-end close below the mean of the last ten (spec §9.6); None without ten."""
    if len(month_end_closes) < TEN_MONTHS:
        return None
    window = month_end_closes[-TEN_MONTHS:]
    return month_end_closes[-1] < sum(window) / TEN_MONTHS


def month_end_closes(closes: list[tuple[date, float]]) -> list[float]:
    """The last close of each calendar month in *closes* (ascending), the current month included
    only once it has ended (a later bar exists)."""
    out: list[float] = []
    for i, (day, close) in enumerate(closes):
        nxt = closes[i + 1][0] if i + 1 < len(closes) else None
        if nxt is not None and (nxt.year, nxt.month) != (day.year, day.month):
            out.append(close)
    return out
```

- [ ] **Step 5: The liquidity input** — apply:

```diff
diff --git a/src/value/scorecard.py b/src/value/scorecard.py
index 6ee8414..71306da 100644
--- a/src/value/scorecard.py
+++ b/src/value/scorecard.py
@@ -289,6 +289,8 @@ def build_scorecard(inputs: ValueInputs, cfg: ValueCfg) -> ValueScorecard:
         "roic_median_5y": median_of([roic(y) for y in years]),
         "gross_margin_stdev_5y": stdev_of([y.gross_margin for y in years]),
         "revenue_cagr_5y": cagr([y.revenue for y in years]),
+        # Part 5: the value gate's liquidity check (spec §9.4 `illiquid`), 20-day dollar volume
+        "adv_dollar_20": inputs.price.adv_dollar_20,
     }
     metrics.update(claude_inputs(inputs, years, per_share, v.growth_sbc_share))
     card = card.model_copy(
```

- [ ] **Step 6: Run them to see them pass** — `tests/test_value_risk.py tests/test_value_scorecard.py tests/test_value_fence.py`.
- [ ] **Step 7: Gates and commit:**

  ```bash
  git add src/value/risk.py src/value/sizing.py src/value/scorecard.py tests/test_value_risk.py
  git commit -m "feat(value): the value gate and sizing by the effective margin of safety (spec 9.4-9.6)"
  ```

---

### Task 8: The book's rows, the executor, the night and the cycle

**Files:** Create `src/value/book.py`, `src/value/executor.py`, `src/value/live.py`,
`tests/test_value_live.py`.

**Interfaces:** see each module's docstring; the ones later tasks use: `book.totals`,
`book.reconcile`, `book.clear_attribution`, `book.apply_split`, `book.decide`, `book.get_state` /
`set_state`; `executor.send_order`, `IbkrValueBroker`; `live.Snapshot`, `live.plan_night`,
`live.cycle`, `live.hourly_check`, `live.mirror_reevaluations`, `live.SNAPSHOT`.

The pinned numbers: a READY name at $30 with an effective fair value of $46.85 has a 36% margin,
deep-value tier 5% of the $30,000 ceiling = $1,500, a third = $500: 16 shares. A buy of 20 at an ask
of $30.05 ($601) against $99,800 of CSP collateral on a $100,000 account needs $401 released; after
$10,000 is released it buys.

- [ ] **Step 1: Write the failing tests** — create `tests/test_value_live.py`:

```python
"""The value book's money in paper (value book spec §7, §9, revision 4): the executor, the RTH
cycle (close first, confirm, then buy), the reconcile, the night's proposals, the hourly check."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from sqlalchemy import select

from src.common.config import get_config
from src.common.value_types import DayBar
from src.value import book, live
from src.value.executor import Outcome, Placed, Quote, send_order
from src.value.exits import DayFacts
from src.value.scorecard import build_scorecard
from src.value.store import (
    ValueAttributionRow,
    ValueClaudeReadRow,
    ValueEffectiveRow,
    ValueFundingRow,
    ValueOrderRow,
    ValuePositionRow,
    ValueProposalRow,
    ValueReevaluationRow,
    value_session,
)
from src.value.ticker_file import persist
from tests.value_book_fixtures import NOW, order
from tests.value_fixtures import inputs

CFG = get_config().value
PORTFOLIO = {"max_gross_notional_pct": 100.0, "max_combined_name_pct": 15.0}
CARD = build_scorecard(inputs(symbol="STDY", close=30.0), CFG)  # deep READY, FV 46.85


class FakeBroker:
    def __init__(self, *, fill: float | None = None, price: float = 30.0) -> None:
        self.fill, self.price, self.placed = fill, price, []

    async def quote(self, symbol):
        return Quote(self.price - 0.05, self.price + 0.05, NOW)

    async def place(self, symbol, side, shares, limit, order_ref):
        with value_session() as s:  # the pending row exists before placeOrder (spec §9.2)
            row = s.scalars(select(ValueOrderRow).where(ValueOrderRow.order_ref == order_ref)).one()
            assert row.status == "pending"
        self.placed.append((symbol, side, shares, limit, order_ref))
        return Placed(41, 4100, None)

    async def wait(self, placed, timeout):
        filled = self.placed[-1][2] if self.fill is None else self.fill
        return Outcome(filled, self.price, filled >= self.placed[-1][2])

    async def cancel(self, placed):
        return Outcome(self.fill or 0.0, self.price if self.fill else None, True)


def _effective(symbol="STDY", list_name="deep_value", verdict="READY", fv=46.85, by="python"):
    with value_session() as s:
        s.add(
            ValueEffectiveRow(
                symbol=symbol,
                list_name=list_name,
                as_of=date(2026, 10, 30),
                verdict=verdict,
                decided_by=by,
                python_verdict=verdict,
                fair_value=fv,
                entry_ceiling=fv * 0.75,
                margin_of_safety=(fv - 30.0) / fv,
                updated_at=NOW,
            )
        )
        persist(
            s,
            CARD,
            universe="trading",
            ranks={},
            filed="deep_value",
            cfg=CFG.ticker_file,
            session_row=False,
        )


SNAP = live.Snapshot(net_liq=100_000.0, adv={"STDY": 1e9})


def _cycle(broker, snap=SNAP, now=NOW):
    return asyncio.run(
        live.cycle(
            value_session,
            broker,
            snap,
            wheel={},
            cfg=CFG,
            portfolio=PORTFOLIO,
            now=now,
            halted=False,
            is_live=False,
            trend_brake=False,
        )
    )


def _proposal(kind="buy", shares=20.0, status="approved", reason="tranche 1", cause="python"):
    with value_session() as s:
        row = book.propose(
            s,
            kind=kind,
            symbol="STDY",
            list_name="deep_value",
            shares=shares,
            price=30.0,
            reason=reason,
            cause=cause,
            auto=status == "approved",
            now=NOW,
            ttl_hours=30,
            tranche=1 if kind == "buy" else None,
        )
        assert row is not None
        return row.id


def test_an_order_is_written_before_it_is_placed_and_its_fill_recorded(value_book_db) -> None:
    broker = FakeBroker()
    oid = asyncio.run(
        send_order(
            value_session,
            broker,
            symbol="STDY",
            list_name="deep_value",
            side="buy",
            shares=20,
            limit=30.0,
            reason="tranche 1",
            proposal_id=None,
            tranche=1,
            timeout=1,
        )
    )
    with value_session() as s:
        row = s.get(ValueOrderRow, oid)
        assert (row.status, row.filled, row.order_ref, row.ib_order_id) == (
            "filled",
            20.0,
            f"value:{oid}",
            41,
        )
    assert broker.placed[0][4] == f"value:{oid}"


def test_a_part_fill_keeps_what_filled_and_cancels_the_rest(value_book_db) -> None:
    oid = asyncio.run(
        send_order(
            value_session,
            FakeBroker(fill=7),
            symbol="STDY",
            list_name="deep_value",
            side="buy",
            shares=20,
            limit=30.0,
            reason="t",
            proposal_id=None,
            tranche=1,
            timeout=1,
        )
    )
    with value_session() as s:
        row = s.get(ValueOrderRow, oid)
        assert (row.status, row.filled) == ("cancelled", 7.0)


def test_an_approved_buy_with_room_is_regated_sent_and_opens_a_position(value_book_db) -> None:
    _effective()
    pid = _proposal()
    msgs = _cycle(FakeBroker())
    assert msgs == ["Value book: bought 20 STDY at 30.0 (deep_value)"]
    with value_session() as s:
        assert s.get(ValueProposalRow, pid).status == "done"
        pos = s.scalars(select(ValuePositionRow)).one()
        assert (pos.symbol, pos.tranches_done, pos.status) == ("STDY", 1, "open")


def test_a_buy_short_of_cash_asks_for_capital_then_buys_once_the_room_is_there(
    value_book_db,
) -> None:
    """Close first, confirm, then buy: no order goes out until the fresh snapshot shows room."""
    _effective()
    pid = _proposal()
    full = live.Snapshot(net_liq=100_000.0, csp_by_name={"AAA": 99_800.0}, adv={"STDY": 1e9})
    broker = FakeBroker()
    msgs = _cycle(broker, full)
    assert msgs == ["Value book: STDY needs $401 released (capital release requested)"]
    assert broker.placed == []
    with value_session() as s:
        assert s.get(ValueProposalRow, pid).status == "funding"
        req = s.scalars(select(ValueFundingRow)).one()
        assert (req.status, req.needed_usd) == ("open", 401.0)  # 20 x 30.05 - 200
    released = live.Snapshot(net_liq=100_000.0, csp_by_name={"AAA": 89_800.0}, adv={"STDY": 1e9})
    assert _cycle(broker, released) == ["Value book: bought 20 STDY at 30.0 (deep_value)"]
    with value_session() as s:
        assert s.scalars(select(ValueFundingRow)).one().status == "funded"


def test_a_buy_refused_at_send_time_lapses_its_request_and_nothing_else_happens(
    value_book_db,
) -> None:
    _effective()
    pid = _proposal()
    full = live.Snapshot(net_liq=100_000.0, csp_by_name={"AAA": 99_800.0}, adv={"STDY": 1e9})
    _cycle(FakeBroker(), full)
    with value_session() as s:  # the name froze meanwhile: the buy may not go
        s.add(
            ValueAttributionRow(
                symbol="STDY", broker=0, wheel=0, value_filled=0, state="frozen", updated_at=NOW
            )
        )
    msgs = _cycle(FakeBroker(), full)
    assert "book_attribution_mismatch" in msgs[-1]
    with value_session() as s:
        assert s.get(ValueProposalRow, pid).status == "refused"
        assert s.scalars(select(ValueFundingRow)).one().status == "lapsed"


def test_a_sell_never_uncovers_a_wheel_call(value_book_db) -> None:
    order("STDY", shares=50, filled=50, avg=30.0)
    pid = _proposal(kind="sell", shares=50)
    snap = live.Snapshot(net_liq=100_000.0, shares={"STDY": 150.0}, wheel_short_calls={"STDY": 1})
    broker = FakeBroker()
    _cycle(broker, snap)
    assert broker.placed[0][1:3] == ("sell", 50.0)
    pid2 = _proposal(kind="sell", shares=50)
    short = live.Snapshot(net_liq=100_000.0, shares={"STDY": 100.0}, wheel_short_calls={"STDY": 1})
    msgs = _cycle(FakeBroker(), short)
    with value_session() as s:
        assert s.get(ValueProposalRow, pid).status == "done"
        assert s.get(ValueProposalRow, pid2).status == "refused"
    assert "sell cap" in msgs[-1]


def test_unexplained_shares_are_pending_then_frozen_until_a_human_clears_them(
    value_book_db,
) -> None:
    order("STDY", shares=50, filled=50, avg=30.0)
    with value_session() as s:
        assert (
            book.reconcile(s, {"STDY": 150.0}, {"STDY": 100.0}, {}, now=NOW, grace_hours=36) == []
        )
        assert s.get(ValueAttributionRow, "STDY").state == "ok"
        assert (
            book.reconcile(s, {"STDY": 180.0}, {"STDY": 100.0}, {}, now=NOW, grace_hours=36) == []
        )
        assert s.get(ValueAttributionRow, "STDY").state == "pending"
        later = NOW + timedelta(hours=37)
        assert book.reconcile(
            s, {"STDY": 180.0}, {"STDY": 100.0}, {}, now=later, grace_hours=36
        ) == ["STDY"]
        assert book.clear_attribution(s, "STDY", later) is True
        assert s.get(ValueAttributionRow, "STDY").state == "ok"


def _held(entry: float = 30.0) -> int:
    order("STDY", shares=20, filled=20, avg=entry)
    with value_session() as s:
        o = s.scalars(select(ValueOrderRow)).one()
        pos = book.open_position(
            s,
            o,
            day=date(2026, 10, 1),
            atr14=1.0,
            fair_value=46.85,
            effective_fair_value=60.0,
            fv_accn="a",
            cfg=CFG,
            decided_by="claude",
        )
        return pos.id


def _night(bars, facts=None, **kw):
    with value_session() as s:
        return live.plan_night(
            s,
            cards={"STDY": CARD},
            tags={"STDY": "trading"},
            bars={"STDY": bars},
            facts=facts or {},
            cfg=CFG,
            portfolio=PORTFOLIO,
            now=NOW,
            today=NOW.date(),
            may_auto_open=kw.get("auto_open", lambda sym: True),
            auto_close=True,
            halted=False,
            is_live=False,
            trend_brake=False,
        )


def test_the_night_turns_a_python_exit_into_an_auto_sell_and_claudes_into_a_tap(
    value_book_db,
) -> None:
    _held()
    crash = [DayBar(date=date(2026, 10, 2), close=20.0, open=21.0)]  # 33% under cost
    out = _night(crash)
    assert (out.sells, out.tap) == (1, 0)
    with value_session() as s:
        p = s.scalars(select(ValueProposalRow)).one()
        assert (p.reason, p.cause, p.status, p.shares) == ("catastrophe", "python", "approved", 20)


def test_a_half_sale_only_claudes_value_reaches_waits_for_a_tap(value_book_db) -> None:
    _held()
    up = [DayBar(date=date(2026, 10, 2), close=61.0, open=60.0)]  # past Claude's 60 only
    facts = {
        ("STDY", "deep_value"): DayFacts(
            python_fair_value=70.0, effective_fair_value=60.0, latest_accn="a"
        )
    }
    out = _night(up, facts)
    assert out.tap == 1
    with value_session() as s:
        p = s.scalars(select(ValueProposalRow)).one()
        assert (p.reason, p.cause, p.status, p.shares) == ("half", "claude", "pending", 10)


def test_claudes_broken_review_is_a_tap_only_sell(value_book_db) -> None:
    pid = _held()
    with value_session() as s:
        s.add(
            ValueReevaluationRow(
                shadow_id=0,
                position_id=pid,
                symbol="STDY",
                list_name="deep_value",
                session=date(2026, 10, 2),
                last_session=date(2026, 10, 2),
                severity="major",
                triggers_json="[]",
                plan_before_json="{}",
                plan_after_json="{}",
                verdict_at_entry="READY",
                review_state="BROKEN",
                ruleset_version="v4",
                ruleset_hash="x",
                created_at=NOW,
            )
        )
    out = _night([])
    with value_session() as s:
        p = s.scalars(select(ValueProposalRow)).one()
        assert (p.reason, p.cause, p.needs_tap) == ("claude_broken", "claude", True)
    assert out.tap == 1


def test_the_night_sizes_and_gates_a_ready_name_into_a_buy_proposal(value_book_db) -> None:
    _effective()
    assert _night([]).skipped.startswith("no account snapshot")
    with value_session() as s:
        book.set_state(s, live.SNAPSHOT, {"net_liq": 100_000.0, "adv": {"STDY": 1e9}}, NOW)
    out = _night([], auto_open=lambda sym: False)
    with value_session() as s:
        p = s.scalars(select(ValueProposalRow)).one()
    # MoS (46.85 - 30) / 46.85 = 36% -> 5% of the 30,000 ceiling = 1,500, a third = 500: 16 shares
    assert (out.buys, p.shares, p.status, p.needs_tap) == (1, 16.0, "pending", True)


def test_a_tap_decides_a_pending_proposal_once(value_book_db) -> None:
    pid = _proposal(status="pending")
    with value_session() as s:
        assert book.decide(s, pid, approve=True, now=NOW, by="cli") == "approved"
        assert book.decide(s, pid, approve=False, now=NOW, by="cli") == "already_approved"
        assert book.decide(s, 999, approve=True, now=NOW, by="cli") == "no_such_proposal"


def test_the_hourly_check_opens_a_held_reevaluation_pauses_adds_and_queues_review(
    value_book_db, monkeypatch
) -> None:
    monkeypatch.setattr(CFG.claude, "enabled", True)
    pid = _held()
    snap = live.Snapshot(net_liq=100_000.0, marks={"STDY": 26.5})
    with value_session() as s:
        opened = live.hourly_check(
            s, snap, {"STDY": 30.0}, set(), cfg=CFG, now=NOW, ruleset_version="v4", ruleset_hash="x"
        )
        assert opened == ["STDY"]  # -11.7% against the 30.00 close
        r = s.scalars(select(ValueReevaluationRow)).one()
        assert (r.position_id, r.severity) == (pid, "major")
        assert live.adds_paused(s, "STDY", NOW.date(), 3) is True
        read = s.scalars(select(ValueClaudeReadRow)).one()
        assert (read.kind, read.reevaluation_id) == ("review", r.id)
        assert (
            live.hourly_check(
                s,
                snap,
                {"STDY": 30.0},
                set(),
                cfg=CFG,
                now=NOW,
                ruleset_version="v4",
                ruleset_hash="x",
            )
            == []
        )


def test_on_a_frozen_name_only_a_stop_or_thesis_sale_sends(value_book_db) -> None:
    """Spec §9.2: both books freeze; only a value-book stop or thesis sale may still send."""
    order("STDY", shares=50, filled=50, avg=30.0)
    with value_session() as s:
        s.add(
            ValueAttributionRow(
                symbol="STDY", broker=50, wheel=0, value_filled=50, state="frozen", updated_at=NOW
            )
        )
    tap = _proposal(kind="sell", shares=20, reason="claude_broken", cause="claude")
    with value_session() as s:
        assert book.decide(s, tap, approve=True, now=NOW, by="cli") == "approved"
    snap = live.Snapshot(net_liq=100_000.0, shares={"STDY": 50.0})
    broker = FakeBroker()
    assert _cycle(broker, snap) == [] and broker.placed == []  # waits, never sends
    with value_session() as s:
        s.get(ValueProposalRow, tap).status = "expired"
    _proposal(kind="sell", shares=50, reason="catastrophe")
    _cycle(broker, snap)
    assert broker.placed[0][1:3] == ("sell", 50.0)
```

- [ ] **Step 2: Run them to see them fail** — `ImportError: cannot import name 'book' from 'src.value'`.
- [ ] **Step 3: The book's rows** — create `src/value/book.py`:

```python
"""The value book's held positions, proposals and share reconcile (spec §7, §9.2, §9.5; revision 4).

Writes value.db only. Pure arithmetic lives in ``sizing.py``, ``risk.py`` and ``exits.py``; this
module turns them into rows:

- ``totals``: what the book holds and is buying, from ``value_orders`` (the V of spec §9.2);
- ``reconcile``: broker = wheel (W) + value (V filled) per shared name; unexplained shares are
  ``pending`` for ``attribution_grace_hours`` (the ledger's own lag), then ``frozen`` until a human
  clears them; a freeze stops both books opening on the name (the gate and the Rules Engine read it);
- ``step_held``: each night, each open position's live-policy plan (``rules.exits.live_policy``,
  ``value``) on tonight's bar and Python's numbers; a sale it signals becomes a sell proposal.
  Every sale that sends without a tap reads Python's fair value; one only Claude's value (or
  Claude's review, or its NO) would make is a proposal that **always waits for a tap**;
- ``propose``: a buy or sell proposal, approved at once when the autonomy ladder allows (buys:
  ``may_auto_open``; Python's sells: ``automation.auto_close_enabled``), else pending a tap.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.config import ValueCfg
from src.common.value_types import DayBar
from src.value.exits import DayFacts, LegState, open_leg, step
from src.value.store import (
    ValueAttributionRow,
    ValueBookStateRow,
    ValueFundingRow,
    ValueOrderRow,
    ValuePositionRow,
    ValueProposalRow,
)

WORKING = ("pending", "submitted", "partial")
PYTHON_SELLS = ("stop", "trail", "peak", "thesis", "remark_below", "catastrophe", "time")


@dataclass
class NameTotals:
    filled: float = 0.0
    cost: float = 0.0  # filled shares at their average cost
    working_buy_cost: float = 0.0
    list_name: str = ""


@dataclass
class BookTotals:
    names: dict[str, NameTotals] = field(default_factory=dict)

    @property
    def cost(self) -> float:
        return sum(n.cost + n.working_buy_cost for n in self.names.values())

    def list_cost(self, list_name: str) -> float:
        return sum(
            n.cost + n.working_buy_cost for n in self.names.values() if n.list_name == list_name
        )

    @property
    def positions_open(self) -> int:
        return sum(1 for n in self.names.values() if n.filled > 0 or n.working_buy_cost > 0)


def totals(vs: Session) -> BookTotals:
    out = BookTotals()
    bought: dict[str, tuple[float, float]] = {}
    for o in vs.scalars(select(ValueOrderRow)):
        n = out.names.setdefault(o.symbol, NameTotals(list_name=o.list_name))
        if o.side == "buy":
            q, c = bought.get(o.symbol, (0.0, 0.0))
            bought[o.symbol] = (q + o.filled, c + o.filled * (o.avg_price or 0.0))
            n.filled += o.filled
            if o.status in WORKING:
                n.working_buy_cost += (o.shares - o.filled) * (o.limit_price or 0.0)
        else:
            n.filled -= o.filled
    for symbol, n in out.names.items():
        q, c = bought.get(symbol, (0.0, 0.0))
        n.filled = max(0.0, n.filled)
        n.cost = n.filled * (c / q) if q else 0.0
    return out


def get_state(vs: Session, key: str) -> dict | None:
    row = vs.get(ValueBookStateRow, key)
    return None if row is None else json.loads(row.value)


def set_state(vs: Session, key: str, value: dict, now: datetime) -> None:
    row = vs.get(ValueBookStateRow, key)
    blob = json.dumps(value, sort_keys=True, default=str)
    if row is None:
        vs.add(ValueBookStateRow(key=key, value=blob, updated_at=now))
    else:
        row.value, row.updated_at = blob, now


def reconcile(
    vs: Session,
    broker: dict[str, float],
    wheel: dict[str, float],
    marks: dict[str, float],
    *,
    now: datetime,
    grace_hours: float,
) -> list[str]:
    """Spec §9.2's reconcile, for every name the value book holds or has an attribution row
    for. Returns the names that froze now (for the alert)."""
    t = totals(vs)
    names = {s for s, n in t.names.items() if n.filled > 0 or n.working_buy_cost > 0}
    names |= set(vs.scalars(select(ValueAttributionRow.symbol)))
    frozen_now: list[str] = []
    for symbol in sorted(names):
        n = t.names.get(symbol, NameTotals())
        pending = sum(
            o.shares - o.filled
            for o in vs.scalars(
                select(ValueOrderRow).where(
                    ValueOrderRow.symbol == symbol,
                    ValueOrderRow.side == "buy",
                    ValueOrderRow.status.in_(WORKING),
                )
            )
        )
        b, w = broker.get(symbol, 0.0), wheel.get(symbol, 0.0)
        unexplained = abs(b - (w + n.filled)) > 1e-6
        row = vs.get(ValueAttributionRow, symbol)
        if row is None:
            row = ValueAttributionRow(
                symbol=symbol, broker=b, wheel=w, value_filled=n.filled, updated_at=now
            )
            vs.add(row)
        row.broker, row.wheel, row.value_filled, row.value_pending = b, w, n.filled, pending
        row.mark, row.updated_at = marks.get(symbol, row.mark), now
        if not unexplained:
            if row.state != "frozen":
                row.state, row.since, row.detail = "ok", None, ""
            continue
        row.detail = f"broker {b:g} != wheel {w:g} + value {n.filled:g}"
        if row.state == "ok":
            row.state, row.since = "pending", now
        elif row.state == "pending" and row.since is not None:
            if now - row.since >= timedelta(hours=grace_hours):
                row.state = "frozen"
                frozen_now.append(symbol)
    return frozen_now


def clear_attribution(vs: Session, symbol: str, now: datetime) -> bool:
    """A human clears a freeze (spec §9.2). The next reconcile re-checks the name."""
    row = vs.get(ValueAttributionRow, symbol.upper())
    if row is None or row.state == "ok":
        return False
    row.state, row.since, row.cleared_at = "ok", None, now
    return True


def propose(
    vs: Session,
    *,
    kind: str,
    symbol: str,
    list_name: str,
    shares: float,
    price: float | None,
    reason: str,
    cause: str,
    auto: bool,
    now: datetime,
    ttl_hours: float,
    tranche: int | None = None,
    position_id: int | None = None,
    gate: list[str] | None = None,
) -> ValueProposalRow | None:
    """One proposal, unless the same name already has one open of the same kind. A Claude-caused
    sale is never auto (spec §7)."""
    open_ = vs.scalars(
        select(ValueProposalRow).where(
            ValueProposalRow.symbol == symbol,
            ValueProposalRow.kind == kind,
            ValueProposalRow.status.in_(("pending", "approved", "funding", "sent")),
        )
    ).first()
    if open_ is not None:
        return None
    auto = auto and not (kind == "sell" and cause == "claude")
    row = ValueProposalRow(
        kind=kind,
        symbol=symbol,
        list_name=list_name,
        shares=shares,
        price=price,
        cost_usd=shares * price if kind == "buy" and price else 0.0,
        tranche=tranche,
        position_id=position_id,
        reason=reason,
        cause=cause,
        needs_tap=not auto,
        status="approved" if auto else "pending",
        gate_json=json.dumps(gate or []),
        created_at=now,
        expires_at=now + timedelta(hours=ttl_hours),
        decided_at=now if auto else None,
        decided_by="system" if auto else None,
    )
    vs.add(row)
    vs.flush()
    return row


def decide(vs: Session, proposal_id: int, *, approve: bool, now: datetime, by: str) -> str:
    """A tap (spec §9.7): approve or reject a pending proposal. Returns the new status, or why
    nothing changed."""
    row = vs.get(ValueProposalRow, proposal_id)
    if row is None:
        return "no_such_proposal"
    if row.status != "pending":
        return f"already_{row.status}"
    if now >= row.expires_at:
        row.status = "expired"
        return "expired"
    row.status = "approved" if approve else "rejected"
    row.decided_at, row.decided_by = now, by
    return row.status


def expire(vs: Session, now: datetime) -> int:
    """Pending and approved proposals past their time expire; their funding requests lapse."""
    n = 0
    for row in vs.scalars(
        select(ValueProposalRow).where(
            ValueProposalRow.status.in_(("pending", "approved", "funding")),
            ValueProposalRow.expires_at <= now,
        )
    ):
        row.status = "expired"
        n += 1
    for req in vs.scalars(select(ValueFundingRow).where(ValueFundingRow.status == "open")):
        prop = vs.get(ValueProposalRow, req.proposal_id)
        if now >= req.expires_at or prop is None or prop.status not in ("approved", "funding"):
            req.status, req.closed_at = "lapsed", now
            req.detail = "expired" if now >= req.expires_at else "the buy is no longer approved"
    return n


def open_position(
    vs: Session,
    order: ValueOrderRow,
    *,
    day: date,
    atr14: float | None,
    fair_value: float | None,
    effective_fair_value: float | None,
    fv_accn: str | None,
    cfg: ValueCfg,
    decided_by: str,
) -> ValuePositionRow:
    """The position a first buy fill opens (or the one it adds to), with the live policy's plan
    written at entry (spec §7). A later tranche moves the plan's average cost; no stop is ever
    lowered by it (the live policy's only price exit is the catastrophe floor on the average)."""
    pos = vs.scalars(
        select(ValuePositionRow).where(
            ValuePositionRow.symbol == order.symbol,
            ValuePositionRow.list_name == order.list_name,
            ValuePositionRow.status == "open",
        )
    ).first()
    t = totals(vs).names.get(order.symbol, NameTotals())
    avg = t.cost / t.filled if t.filled else (order.avg_price or 0.0)
    if pos is None:
        plan = open_leg(
            cfg.rules.exits.live_policy,
            entry_date=day,
            entry_price=avg,
            atr14=atr14,
            fair_value=fair_value,
            effective_fair_value=effective_fair_value,
            fv_accn=fv_accn,
            cfg=cfg.rules.exits,
        )
        pos = ValuePositionRow(
            symbol=order.symbol,
            list_name=order.list_name,
            status="open",
            opened_on=day,
            tranches_done=1,
            last_tranche_on=day,
            plan_json=plan.model_dump_json(),
            plan_step=day,
            decided_by=decided_by,
        )
        vs.add(pos)
    else:
        state = LegState.model_validate_json(pos.plan_json or "{}")
        pos.plan_json = state.model_copy(update={"entry_price": avg}).model_dump_json()
        pos.tranches_done += 1
        pos.last_tranche_on = day
    vs.flush()
    return pos


@dataclass(frozen=True, slots=True)
class SellSignal:
    position_id: int
    symbol: str
    list_name: str
    fraction: float  # of the shares held now
    reason: str
    cause: str  # python | claude


def step_held(
    vs: Session,
    bars: dict[str, list[DayBar]],
    facts: dict[tuple[str, str], DayFacts],
    cfg: ValueCfg,
) -> list[SellSignal]:
    """Step every open position's plan over the sessions it has not seen, on Python's numbers
    (``facts`` carries Python's fair value and the effective one for the half-sale). A sale the
    plan signals is returned (the proposal is the caller's); the plan itself never fills."""
    out: list[SellSignal] = []
    for pos in vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open")):
        state = LegState.model_validate_json(pos.plan_json or "{}")
        days = [
            b for b in bars.get(pos.symbol, []) if pos.plan_step is None or b.date > pos.plan_step
        ]
        for b in days:
            fact = facts.get((pos.symbol, pos.list_name)) if b is days[-1] else None
            state, events = step(state, b, fact, cfg.rules.exits)
            for e in events:
                if e.kind == "fill":
                    continue
                if e.kind in PYTHON_SELLS:
                    out.append(SellSignal(pos.id, pos.symbol, pos.list_name, 1.0, e.kind, "python"))
                elif e.kind == "half":
                    python_fv = fact.python_fair_value if fact else state.fair_value
                    cause = "python" if python_fv is not None and b.close >= python_fv else "claude"
                    frac = cfg.rules.exits.half_sell_pct / 100.0
                    out.append(SellSignal(pos.id, pos.symbol, pos.list_name, frac, "half", cause))
                elif e.kind == "proposal":
                    half = "reached" in e.detail
                    frac = cfg.rules.exits.half_sell_pct / 100.0 if half else 1.0
                    out.append(
                        SellSignal(
                            pos.id, pos.symbol, pos.list_name, frac, "claude_value", "claude"
                        )
                    )
            # the live book's sales happen as orders, never inside the plan
            state = state.model_copy(update={"pending": 0.0, "pending_reason": ""})
        pos.plan_json = state.model_dump_json()
        if days:
            pos.plan_step = days[-1].date
    return out


def sell_shares(held: float, fraction: float) -> int:
    return max(0, math.floor(held * min(1.0, fraction) + 1e-9))


def apply_split(vs: Session, symbol: str, ratio: float, now: datetime) -> int:
    """A split the operator confirms (spec §9.2 fault drill "a split"): the value book's orders
    for *symbol* are restated in post-split shares (shares and fills x ratio, prices / ratio) and
    each open plan's price levels rebased, so V matches the broker again. Returns the orders
    restated. The freeze it caused stays until the operator clears it."""
    n = 0
    for o in vs.scalars(select(ValueOrderRow).where(ValueOrderRow.symbol == symbol.upper())):
        o.shares, o.filled = o.shares * ratio, o.filled * ratio
        o.limit_price = None if o.limit_price is None else o.limit_price / ratio
        o.avg_price = None if o.avg_price is None else o.avg_price / ratio
        o.detail = (o.detail + f" split x{ratio:g} restated {now:%Y-%m-%d}").strip()
        n += 1
    for pos in vs.scalars(
        select(ValuePositionRow).where(
            ValuePositionRow.symbol == symbol.upper(), ValuePositionRow.status == "open"
        )
    ):
        if pos.plan_json:
            pos.plan_json = (
                LegState.model_validate_json(pos.plan_json).rebased(1.0 / ratio).model_dump_json()
            )
    return n
```

- [ ] **Step 4: The executor** — create `src/value/executor.py`:

```python
"""The value book's stock-order path (spec §9.7), as ``src/spreads/executor.py`` is for spreads.

Not in ``src/execution/``: importing that loads ``src.claude.memory``, which the value process
must not load. Paper only (the caller refuses in live). Every order:

1. is written to ``value_orders`` as ``pending`` and committed **before** ``placeOrder``, with
   ``orderRef = "value:<id>"`` (spec §9.2: a fill can never arrive for an order value.db does not
   know, and the ref survives restarts and reaches the ledger);
2. is a ``LimitOrder`` at the mid of a fresh quote (``req_fresh_mkt_data``, never ``reqMktData``),
   on a contract ``qualifyContracts`` resolved, sent from clientId 31;
3. waits for its fills up to ``book.fill_timeout_seconds``, then is cancelled; what filled is
   recorded.

``ValueBroker`` is the boundary (``IbkrValueBroker`` wraps ib_async); tests pass a fake.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from src.common.books import VALUE_ORDER_PREFIX
from src.value.store import ValueOrderRow

log = logging.getLogger(__name__)
SessionFactory = Callable[[], AbstractContextManager[Session]]


@dataclass(frozen=True, slots=True)
class Quote:
    bid: float
    ask: float
    at: datetime  # naive UTC

    @property
    def mid(self) -> float:
        return round((self.bid + self.ask) / 2.0, 2)


@dataclass(frozen=True, slots=True)
class Placed:
    ib_order_id: int | None
    perm_id: int | None
    handle: Any


@dataclass(frozen=True, slots=True)
class Outcome:
    filled: float
    avg_price: float | None
    done: bool  # the order reached a terminal state by itself


class ValueBroker(Protocol):
    async def quote(self, symbol: str) -> Quote | None: ...
    async def place(
        self, symbol: str, side: str, shares: float, limit: float, order_ref: str
    ) -> Placed: ...
    async def wait(self, placed: Placed, timeout: float) -> Outcome: ...
    async def cancel(self, placed: Placed) -> Outcome: ...


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def send_order(
    session: SessionFactory,
    broker: ValueBroker,
    *,
    symbol: str,
    list_name: str,
    side: str,
    shares: float,
    limit: float,
    reason: str,
    proposal_id: int | None,
    tranche: int | None,
    timeout: float,
) -> int:
    """Write, place, wait, record. Returns the ``value_orders`` id (its status tells the rest)."""
    with session() as vs:
        row = ValueOrderRow(
            symbol=symbol,
            list_name=list_name,
            side=side,
            tranche=tranche,
            reason=reason,
            proposal_id=proposal_id,
            shares=shares,
            limit_price=limit,
            status="pending",
            created_at=_now(),
        )
        vs.add(row)
        vs.flush()
        row.order_ref = f"{VALUE_ORDER_PREFIX}{row.id}"
        order_id, ref = row.id, row.order_ref
    try:
        placed = await broker.place(symbol, side, shares, limit, ref)
    except Exception as exc:  # noqa: BLE001 - never reached IBKR: record it, never retry blind
        log.exception("value order %s: place failed", ref)
        with session() as vs:
            r = vs.get(ValueOrderRow, order_id)
            assert r is not None
            r.status, r.detail, r.done_at = "error", f"place failed: {exc}", _now()
        return order_id
    with session() as vs:
        r = vs.get(ValueOrderRow, order_id)
        assert r is not None
        r.status, r.sent_at = "submitted", _now()
        r.ib_order_id, r.perm_id = placed.ib_order_id, placed.perm_id
    outcome = await broker.wait(placed, timeout)
    if not outcome.done:
        outcome = await broker.cancel(placed)
    with session() as vs:
        r = vs.get(ValueOrderRow, order_id)
        assert r is not None
        r.filled, r.avg_price = outcome.filled, outcome.avg_price
        # a part-filled order is cancelled for the rest: what filled stands and counts in V
        r.status = "filled" if outcome.filled >= shares - 1e-9 else "cancelled"
        r.done_at = _now()
    log.info("value order %s %s %g %s: %s %g", ref, side, shares, symbol, r.status, outcome.filled)
    return order_id


class IbkrValueBroker:
    """``ValueBroker`` over an ib_async ``IB`` connected as clientId 31."""

    def __init__(self, ib: Any, *, quote_seconds: float = 5.0) -> None:
        self.ib = ib
        self.quote_seconds = quote_seconds

    async def _contract(self, symbol: str) -> Any:
        from ib_async import Stock

        qualified = await self.ib.qualifyContractsAsync(Stock(symbol, "SMART", "USD"))
        if not qualified or not getattr(qualified[0], "conId", 0):
            raise RuntimeError(f"could not qualify {symbol}")
        return qualified[0]

    async def quote(self, symbol: str) -> Quote | None:
        from src.ibkr.market_data import req_fresh_mkt_data

        contract = await self._contract(symbol)
        ticker = req_fresh_mkt_data(self.ib, contract, "", False, False)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.quote_seconds
        try:
            while loop.time() < deadline:
                bid, ask = getattr(ticker, "bid", None), getattr(ticker, "ask", None)
                if bid and ask and bid > 0 and ask > 0 and bid == bid and ask == ask:
                    return Quote(float(bid), float(ask), _now())
                await asyncio.sleep(0.1)
            return None
        finally:
            self.ib.cancelMktData(contract)

    async def place(
        self, symbol: str, side: str, shares: float, limit: float, order_ref: str
    ) -> Placed:
        from ib_async import LimitOrder

        contract = await self._contract(symbol)
        order = LimitOrder(
            "BUY" if side == "buy" else "SELL", shares, limit, tif="DAY", orderRef=order_ref
        )
        trade = self.ib.placeOrder(contract, order)
        return Placed(int(trade.order.orderId) or None, int(trade.order.permId) or None, trade)

    async def wait(self, placed: Placed, timeout: float) -> Outcome:
        trade = placed.handle
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not trade.isDone() and loop.time() < deadline:
            await asyncio.sleep(1.0)
        return self._outcome(trade)

    async def cancel(self, placed: Placed) -> Outcome:
        trade = placed.handle
        if not trade.isDone():
            self.ib.cancelOrder(trade.order)
            await asyncio.sleep(2.0)
        return self._outcome(trade)

    @staticmethod
    def _outcome(trade: Any) -> Outcome:
        filled = float(getattr(trade.orderStatus, "filled", 0.0) or 0.0)
        avg = float(getattr(trade.orderStatus, "avgFillPrice", 0.0) or 0.0)
        return Outcome(filled, avg or None, bool(trade.isDone()))
```

- [ ] **Step 5: The night and the cycle** — create `src/value/live.py`:

```python
"""The value book's money, in paper (spec §9; revision 4): the night's proposals and the RTH cycle.

**The night** (``plan_night``, after scoring): each held position's live-policy plan is stepped
and a sale it signals becomes a sell proposal (Python's: auto when ``auto_close`` is on; Claude's:
always a tap); Claude's BROKEN review or NO on a held name is a tap-only sell; each effective READY
trading name with a tranche due is sized and gated on the close, and passes (or fails only for
cash) into a buy proposal, auto when the autonomy ladder allows. A margin above the review line
is a tap-only proposal, never an automatic one.

**The RTH cycle** (``cycle``, every ``book.cycle_minutes`` on clientId 31): reconcile both books'
shares, expire what is old, send approved sells (capped so no wheel call is uncovered), then each
approved buy: a fresh quote, the gate again; a pass sends; a buy short only of cash opens a
funding request (the wheel's ``capital_release`` closes CSPs at breakeven or better for it) and
waits, re-gated every cycle, until its own fresh snapshot shows the room: **close first, confirm,
then buy**. A buy that lapses or is refused leaves its request lapsed; nothing else happens.

``hourly_check`` (spec §7.1, held names): a raw move at or past ``raw_move_pct`` against the last
close, or a Major 8-K filed today, opens a held re-evaluation (``position_id``), which pauses adds,
and queues Claude's review.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.books import is_spreads_underlying, value_sell_cap
from src.common.config import ValueCfg
from src.common.value_types import DayBar
from src.value import sizing
from src.value.book import expire as expire_proposals
from src.value.book import get_state as book_state
from src.value.book import (
    open_position,
    propose,
    reconcile,
    sell_shares,
    set_state,
    step_held,
    totals,
)
from src.value.claude_reads import queue_read
from src.value.executor import ValueBroker, send_order
from src.value.exits import DayFacts
from src.value.risk import BuyContext, fundable_only, validate
from src.value.schemas import ValueScorecard
from src.value.store import (
    ValueAttributionRow,
    ValueEffectiveRow,
    ValueFundingRow,
    ValueOrderRow,
    ValuePositionRow,
    ValueProposalRow,
    ValueReevaluationRow,
    ValueTickerFileRow,
)

log = logging.getLogger(__name__)
SessionFactory = Callable[[], AbstractContextManager[Session]]
SNAPSHOT = "snapshot"
PYTHON_STOPS = ("stop", "trail", "thesis", "catastrophe", "remark_below")


@dataclass(frozen=True)
class Snapshot:
    """The account as clientId 31 saw it: both books' stock (the broker's truth)."""

    net_liq: float
    shares: dict[str, float] = field(default_factory=dict)
    marks: dict[str, float] = field(default_factory=dict)
    wheel_short_calls: dict[str, int] = field(default_factory=dict)
    csp_by_name: dict[str, float] = field(default_factory=dict)
    adv: dict[str, float] = field(default_factory=dict)  # 20-day dollar volume, from the cards

    @property
    def stock_value(self) -> float:
        return sum(q * self.marks.get(s, 0.0) for s, q in self.shares.items())

    @property
    def csp_collateral(self) -> float:
        return sum(self.csp_by_name.values())


def _card(vs: Session, symbol: str) -> ValueScorecard | None:
    row = vs.get(ValueTickerFileRow, symbol)
    return None if row is None else ValueScorecard.model_validate_json(row.scorecard_json)


def _earnings_in_window(card: ValueScorecard, list_name: str) -> bool | None:
    ev = card.lists.get(list_name)
    check = next((c for c in (ev.timing_checks if ev else []) if c.id == "timing.earnings"), None)
    if check is None or check.state == "unknown":
        return None
    return check.state == "fail"


def adds_paused(vs: Session, symbol: str, today: date, debounce_sessions: int) -> bool:
    """§7.1 step 1: no tranche while a held re-evaluation is open: its last trigger within the
    debounce window, or Claude's review queued, WEAKENED or BROKEN."""
    pos_ids = list(
        vs.scalars(
            select(ValuePositionRow.id).where(
                ValuePositionRow.symbol == symbol, ValuePositionRow.status == "open"
            )
        )
    )
    if not pos_ids:
        return False
    for r in vs.scalars(
        select(ValueReevaluationRow).where(ValueReevaluationRow.position_id.in_(pos_ids))
    ):
        # sessions approximated by calendar days (5 sessions a week), rounded up
        recent = (today - r.last_session).days <= debounce_sessions * 7 // 5 + 1
        if recent or r.review_state in ("WEAKENED", "BROKEN"):
            return True
    return False


def buy_context(
    vs: Session,
    *,
    symbol: str,
    list_name: str,
    shares: int,
    price: float,
    snapshot: Snapshot,
    cfg: ValueCfg,
    portfolio: dict,
    today: date,
    halted: bool,
    is_live: bool,
    trend_brake: bool,
    drawdown_stop: bool,
    exclude_proposal: int | None = None,
    quote_age_seconds: float | None = None,
) -> BuyContext | None:
    """Everything the gate reads for one buy; None when the name has no ticker file or no
    effective verdict (the gate then never runs: nothing is proposed)."""
    eff = vs.get(ValueEffectiveRow, (symbol, list_name))
    card = _card(vs, symbol)
    if eff is None or card is None:
        return None
    ev = card.lists.get(list_name)
    t = totals(vs)
    name = t.names.get(symbol)
    earmark = sum(
        p.cost_usd
        for p in vs.scalars(
            select(ValueProposalRow).where(
                ValueProposalRow.kind == "buy",
                ValueProposalRow.status.in_(("approved", "funding")),
            )
        )
        if p.id != exclude_proposal
    )
    att = vs.get(ValueAttributionRow, symbol)
    wheel_stock = max(
        0.0,
        snapshot.shares.get(symbol, 0.0) - (name.filled if name else 0.0),
    ) * snapshot.marks.get(symbol, price)
    return BuyContext(
        symbol=symbol,
        list_name=list_name,
        shares=shares,
        price=price,
        verdict=eff.verdict,
        mos=(eff.fair_value - price) / eff.fair_value if eff.fair_value else None,
        required_mos_pct=ev.required_mos_pct if ev else 100.0,
        mos_review=eff.mos_review,
        health=card.health,
        data_quality=card.data_quality,
        timing=ev.timing if ev else "unknown",
        earnings_in_window=_earnings_in_window(card, list_name),
        net_liq=snapshot.net_liq,
        ceiling=sizing.ceiling_usd(snapshot.net_liq, cfg.book, trend_brake=trend_brake),
        book_cost=t.cost,
        list_cost=t.list_cost(list_name),
        name_cost=(name.cost + name.working_buy_cost) if name else 0.0,
        holds_name=bool(name and (name.filled > 0 or name.working_buy_cost > 0)),
        positions_open=t.positions_open,
        wheel_name_exposure=snapshot.csp_by_name.get(symbol, 0.0) + wheel_stock,
        gross_used=snapshot.stock_value + snapshot.csp_collateral + earmark,
        adv_dollar_20=snapshot.adv.get(symbol, card.metrics.get("adv_dollar_20")),
        attribution="ok" if att is None else att.state,
        adds_paused=adds_paused(vs, symbol, today, cfg.rules.reevaluation.debounce_sessions),
        trend_brake=trend_brake,
        drawdown_stop=drawdown_stop,
        is_live=is_live,
        halted=halted,
        spreads_underlying=is_spreads_underlying(symbol),
        quote_age_seconds=quote_age_seconds,
    )


def _gate(ctx: BuyContext, cfg: ValueCfg, portfolio: dict) -> list[str]:
    return validate(
        ctx,
        cfg.book,
        max_gross_notional_pct=float(portfolio.get("max_gross_notional_pct", 100.0)),
        max_combined_name_pct=float(portfolio.get("max_combined_name_pct", 15.0)),
    )


@dataclass
class NightSummary:
    sells: int = 0
    buys: int = 0
    tap: int = 0
    refused: dict[str, list[str]] = field(default_factory=dict)
    skipped: str = ""


def plan_night(
    vs: Session,
    *,
    cards: dict[str, ValueScorecard],
    tags: dict[str, str],
    bars: dict[str, list[DayBar]],
    facts: dict[tuple[str, str], DayFacts],
    cfg: ValueCfg,
    portfolio: dict,
    now: datetime,
    today: date,
    may_auto_open: Callable[[str], bool],
    auto_close: bool,
    halted: bool,
    is_live: bool,
    trend_brake: bool,
) -> NightSummary:
    out = NightSummary()
    t = totals(vs)
    ttl = cfg.book.proposal_ttl_hours
    for sig in step_held(vs, bars, facts, cfg):
        held = t.names.get(sig.symbol)
        shares = sell_shares(held.filled if held else 0.0, sig.fraction)
        if shares < 1:
            continue
        row = propose(
            vs,
            kind="sell",
            symbol=sig.symbol,
            list_name=sig.list_name,
            shares=shares,
            price=None,
            reason=sig.reason,
            cause=sig.cause,
            auto=auto_close and sig.cause == "python",
            now=now,
            ttl_hours=ttl,
            position_id=sig.position_id,
        )
        if row is not None:
            out.sells += 1
            out.tap += int(row.needs_tap)
    for pos in vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open")):
        eff = vs.get(ValueEffectiveRow, (pos.symbol, pos.list_name))
        broken = vs.scalars(
            select(ValueReevaluationRow).where(
                ValueReevaluationRow.position_id == pos.id,
                ValueReevaluationRow.review_state == "BROKEN",
            )
        ).first()
        claude_no = eff is not None and eff.decided_by == "claude" and eff.verdict == "NO"
        held = t.names.get(pos.symbol)
        if (broken is not None or claude_no) and held and held.filled >= 1:
            row = propose(
                vs,
                kind="sell",
                symbol=pos.symbol,
                list_name=pos.list_name,
                shares=sell_shares(held.filled, 1.0),
                price=None,
                reason="claude_broken" if broken is not None else "claude_no",
                cause="claude",
                auto=False,
                now=now,
                ttl_hours=ttl,
                position_id=pos.id,
            )
            if row is not None:
                out.sells += 1
                out.tap += 1
    snap_raw = book_state(vs, SNAPSHOT)
    if snap_raw is None:
        out.skipped = "no account snapshot yet (the RTH cycle writes one)"
        return out
    snap = Snapshot(**snap_raw)
    peak = book_state(vs, "high_water") or {}
    drawdown_stop = bool(peak.get("stop", False))
    for eff in vs.scalars(select(ValueEffectiveRow).where(ValueEffectiveRow.verdict == "READY")):
        if tags.get(eff.symbol) != "trading":
            continue
        card = cards.get(eff.symbol)
        if card is None or card.price is None:
            continue
        held_pos = vs.scalars(
            select(ValuePositionRow).where(
                ValuePositionRow.symbol == eff.symbol,
                ValuePositionRow.list_name == eff.list_name,
                ValuePositionRow.status == "open",
            )
        ).first()
        done = held_pos.tranches_done if held_pos else 0
        b = bars.get(eff.symbol, [])
        since = [
            x
            for x in b
            if held_pos and held_pos.last_tranche_on and x.date > held_pos.last_tranche_on
        ]
        lows = [x.low for x in since if x.low is not None]
        if not sizing.tranche_due(
            done,
            len(since) if held_pos else None,
            lows,
            card.price,
            b[-1].sma50 if b else None,
            cfg.book,
        ):
            continue
        mos = (eff.fair_value - card.price) / eff.fair_value if eff.fair_value else None
        target = sizing.target_cost(
            eff.list_name, mos, snap.net_liq, cfg.book, trend_brake=trend_brake
        )
        name = t.names.get(eff.symbol)
        shares = sizing.tranche_shares(
            target, cfg.book.tranches, card.price, name.cost if name else 0.0
        )
        ctx = buy_context(
            vs,
            symbol=eff.symbol,
            list_name=eff.list_name,
            shares=shares,
            price=card.price,
            snapshot=snap,
            cfg=cfg,
            portfolio=portfolio,
            today=today,
            halted=halted,
            is_live=is_live,
            trend_brake=trend_brake,
            drawdown_stop=drawdown_stop,
        )
        if ctx is None:
            continue
        reasons = _gate(ctx, cfg, portfolio)
        review_only = reasons == ["data_unreliable"] and ctx.data_quality == "pass"
        if reasons and not fundable_only(reasons) and not review_only:
            out.refused[f"{eff.symbol}:{eff.list_name}"] = reasons
            continue
        row = propose(
            vs,
            kind="buy",
            symbol=eff.symbol,
            list_name=eff.list_name,
            shares=shares,
            price=card.price,
            reason=f"tranche {done + 1}",
            cause=eff.decided_by,
            auto=may_auto_open(eff.symbol) and not halted and not review_only,
            now=now,
            ttl_hours=ttl,
            tranche=done + 1,
            position_id=held_pos.id if held_pos else None,
            gate=reasons,
        )
        if row is not None:
            out.buys += 1
            out.tap += int(row.needs_tap)
    return out


async def cycle(
    session: SessionFactory,
    broker: ValueBroker,
    snap: Snapshot,
    *,
    wheel: dict[str, float],
    cfg: ValueCfg,
    portfolio: dict,
    now: datetime,
    halted: bool,
    is_live: bool,
    trend_brake: bool,
) -> list[str]:
    """One RTH cycle. Returns the messages to send (fills, freezes, funding)."""
    msgs: list[str] = []
    with session() as vs:
        frozen = reconcile(
            vs,
            snap.shares,
            wheel,
            snap.marks,
            now=now,
            grace_hours=cfg.book.attribution_grace_hours,
        )
        expire_proposals(vs, now)
        set_state(vs, SNAPSHOT, asdict(snap), now)
        _high_water(vs, snap, cfg, now)
        sells = [
            (p.id, p.symbol, p.list_name, p.shares, p.reason)
            for p in vs.scalars(
                select(ValueProposalRow)
                .where(ValueProposalRow.kind == "sell", ValueProposalRow.status == "approved")
                .order_by(ValueProposalRow.id)
            )
        ]
        buys = [
            p.id
            for p in vs.scalars(
                select(ValueProposalRow)
                .where(
                    ValueProposalRow.kind == "buy",
                    ValueProposalRow.status.in_(("approved", "funding")),
                )
                .order_by(ValueProposalRow.id)
            )
        ]
    msgs += [
        f"Value book: share attribution FROZEN on {s} (both books stop opening it)" for s in frozen
    ]
    for pid, symbol, list_name, shares, reason in sells:
        msgs += await _sell(session, broker, snap, pid, symbol, list_name, shares, reason, cfg, now)
    for pid in buys:
        msgs += await _buy(
            session,
            broker,
            snap,
            pid,
            cfg=cfg,
            portfolio=portfolio,
            now=now,
            halted=halted,
            is_live=is_live,
            trend_brake=trend_brake,
        )
    return msgs


def _high_water(vs: Session, snap: Snapshot, cfg: ValueCfg, now: datetime) -> None:
    """The book's value (filled shares at their marks) against its high: the drawdown breaker
    (spec §9.6) stops entries past ``drawdown_stop_pct``; a human resets it."""
    t = totals(vs)
    value = sum(n.filled * snap.marks.get(s, 0.0) for s, n in t.names.items())
    state = book_state(vs, "high_water") or {"high": 0.0, "stop": False}
    high = max(float(state.get("high", 0.0)), value)
    stop = bool(state.get("stop")) or (
        high > 0 and (high - value) / high * 100.0 >= cfg.book.drawdown_stop_pct
    )
    set_state(vs, "high_water", {"high": high, "value": value, "stop": stop}, now)


async def _sell(
    session: SessionFactory,
    broker: ValueBroker,
    snap: Snapshot,
    pid: int,
    symbol: str,
    list_name: str,
    shares: float,
    reason: str,
    cfg: ValueCfg,
    now: datetime,
) -> list[str]:
    with session() as vs:
        held = totals(vs).names.get(symbol)
        cap = value_sell_cap(
            held.filled if held else 0.0,
            snap.shares.get(symbol, 0.0),
            snap.wheel_short_calls.get(symbol, 0),
        )
        prop = vs.get(ValueProposalRow, pid)
        assert prop is not None
        att = vs.get(ValueAttributionRow, symbol)
        if att is not None and att.state == "frozen" and prop.reason not in PYTHON_STOPS:
            return []  # frozen: only a stop or a thesis sale may send (spec §9.2); it waits
        qty = float(int(min(shares, cap)))
        if qty < 1:
            prop.status, prop.detail = "refused", "sell cap: no value share is free to sell"
            return [f"Value book: {symbol} sell refused, the sell cap leaves nothing (spec §9.2)"]
        prop.status = "sent"
    quote = await broker.quote(symbol)
    if quote is None:
        with session() as vs:
            prop = vs.get(ValueProposalRow, pid)
            assert prop is not None
            prop.status = "approved"  # try again next cycle
        return []
    order_id = await send_order(
        session,
        broker,
        symbol=symbol,
        list_name=list_name,
        side="sell",
        shares=qty,
        limit=quote.mid,
        reason=reason,
        proposal_id=pid,
        tranche=None,
        timeout=cfg.book.fill_timeout_seconds,
    )
    with session() as vs:
        order = vs.get(ValueOrderRow, order_id)
        prop = vs.get(ValueProposalRow, pid)
        assert order is not None and prop is not None
        prop.order_id = order_id
        prop.status = "done" if order.filled > 0 else "approved"
        left = totals(vs).names.get(symbol)
        if left is not None and left.filled < 1:
            for pos in vs.scalars(
                select(ValuePositionRow).where(
                    ValuePositionRow.symbol == symbol, ValuePositionRow.status == "open"
                )
            ):
                pos.status, pos.closed_on = "closed", now.date()
        return [f"Value book: sold {order.filled:g} {symbol} ({reason}) at {order.avg_price}"]


async def _buy(
    session: SessionFactory,
    broker: ValueBroker,
    snap: Snapshot,
    pid: int,
    *,
    cfg: ValueCfg,
    portfolio: dict,
    now: datetime,
    halted: bool,
    is_live: bool,
    trend_brake: bool,
) -> list[str]:
    with session() as vs:
        prop = vs.get(ValueProposalRow, pid)
        assert prop is not None
        symbol, list_name, shares, tranche = prop.symbol, prop.list_name, prop.shares, prop.tranche
    quote = await broker.quote(symbol)
    if quote is None:
        return []
    with session() as vs:
        prop = vs.get(ValueProposalRow, pid)
        assert prop is not None
        peak = book_state(vs, "high_water") or {}
        ctx = buy_context(
            vs,
            symbol=symbol,
            list_name=list_name,
            shares=int(shares),
            price=quote.ask,
            snapshot=snap,
            cfg=cfg,
            portfolio=portfolio,
            today=now.date(),
            halted=halted,
            is_live=is_live,
            trend_brake=trend_brake,
            drawdown_stop=bool(peak.get("stop")),
            exclude_proposal=pid,
            quote_age_seconds=(now - quote.at).total_seconds(),
        )
        reasons = ["no_effective_verdict"] if ctx is None else _gate(ctx, cfg, portfolio)
        prop.gate_json = json.dumps(reasons)
        if reasons and ctx is not None and fundable_only(reasons) and cfg.book.release.enabled:
            msg = _fund(vs, prop, ctx, cfg, portfolio, now)
            return [msg] if msg else []
        if reasons:
            prop.status, prop.detail = "refused", ",".join(reasons)
            for req in vs.scalars(
                select(ValueFundingRow).where(
                    ValueFundingRow.proposal_id == pid, ValueFundingRow.status == "open"
                )
            ):
                req.status, req.closed_at, req.detail = "lapsed", now, "the buy was refused"
            return [f"Value book: {symbol} buy refused at send time: {', '.join(reasons)}"]
        prop.status = "sent"
    order_id = await send_order(
        session,
        broker,
        symbol=symbol,
        list_name=list_name,
        side="buy",
        shares=shares,
        limit=quote.mid,
        reason=f"tranche {tranche}",
        proposal_id=pid,
        tranche=tranche,
        timeout=cfg.book.fill_timeout_seconds,
    )
    with session() as vs:
        order = vs.get(ValueOrderRow, order_id)
        prop = vs.get(ValueProposalRow, pid)
        assert order is not None and prop is not None
        prop.order_id = order_id
        prop.status = "done" if order.filled > 0 else "expired"
        for req in vs.scalars(
            select(ValueFundingRow).where(
                ValueFundingRow.proposal_id == pid, ValueFundingRow.status == "open"
            )
        ):
            req.status, req.closed_at = "funded", now
        if order.filled <= 0:
            return [f"Value book: {symbol} buy did not fill; the proposal is closed"]
        card = _card(vs, symbol)
        eff = vs.get(ValueEffectiveRow, (symbol, list_name))
        ev = card.lists.get(list_name) if card else None
        open_position(
            vs,
            order,
            day=now.date(),
            atr14=None,
            fair_value=ev.fair_value if ev else None,
            effective_fair_value=eff.fair_value if eff else None,
            fv_accn=card.fingerprint.latest_accn if card else None,
            cfg=cfg,
            decided_by=eff.decided_by if eff else "python",
        )
        return [f"Value book: bought {order.filled:g} {symbol} at {order.avg_price} ({list_name})"]


def _fund(
    vs: Session,
    prop: ValueProposalRow,
    ctx: BuyContext,
    cfg: ValueCfg,
    portfolio: dict,
    now: datetime,
) -> str | None:
    """A buy short only of cash: open (or keep) its funding request for the shortfall. The
    cooldown keeps a name whose request lapsed from asking again at once (no churn)."""
    room = ctx.net_liq * float(portfolio.get("max_gross_notional_pct", 100.0)) / 100.0
    needed = round(ctx.cost - (room - ctx.gross_used), 2)
    prop.status = "funding"
    open_req = vs.scalars(
        select(ValueFundingRow).where(
            ValueFundingRow.proposal_id == prop.id, ValueFundingRow.status == "open"
        )
    ).first()
    if open_req is not None:
        open_req.needed_usd = needed
        return None
    cool = now - timedelta(days=cfg.book.release.cooldown_days)
    lapsed = vs.scalars(
        select(ValueFundingRow).where(
            ValueFundingRow.symbol == prop.symbol,
            ValueFundingRow.status == "lapsed",
            ValueFundingRow.closed_at >= cool,
        )
    ).first()
    if lapsed is not None:
        prop.status, prop.detail = "refused", "a funding request for this name lapsed recently"
        return f"Value book: {prop.symbol} not funded (cooldown after a lapsed request)"
    vs.add(
        ValueFundingRow(
            proposal_id=prop.id,
            symbol=prop.symbol,
            needed_usd=needed,
            status="open",
            created_at=now,
            expires_at=now + timedelta(hours=cfg.book.release.request_ttl_hours),
        )
    )
    return f"Value book: {prop.symbol} needs ${needed:,.0f} released (capital release requested)"


def hourly_check(
    vs: Session,
    snap: Snapshot,
    last_close: dict[str, float],
    major_8k: set[str],
    *,
    cfg: ValueCfg,
    now: datetime,
    ruleset_version: str,
    ruleset_hash: str,
) -> list[str]:
    """Spec §7.1 for held names during RTH: a raw move past ``raw_move_pct`` against the last
    close, or a Major 8-K filed today, opens a held re-evaluation (adds pause) and queues Claude's
    review. Levels wait for the close: nothing here moves a stop or sells."""
    opened: list[str] = []
    for pos in vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open")):
        mark, close = snap.marks.get(pos.symbol), last_close.get(pos.symbol)
        move = None if not mark or not close else mark / close - 1.0
        big = move is not None and abs(move) * 100.0 >= cfg.rules.reevaluation.raw_move_pct
        if not big and pos.symbol not in major_8k:
            continue
        today = now.date()
        seen = vs.scalars(
            select(ValueReevaluationRow).where(
                ValueReevaluationRow.position_id == pos.id, ValueReevaluationRow.session == today
            )
        ).first()
        if seen is not None:
            continue
        kind = "move" if big else "filing"
        detail = f"raw move {move:+.1%} intraday" if big and move is not None else "Major 8-K"
        row = ValueReevaluationRow(
            shadow_id=0,
            position_id=pos.id,
            symbol=pos.symbol,
            list_name=pos.list_name,
            session=today,
            last_session=today,
            severity="major",
            triggers_json=json.dumps([{"day": today.isoformat(), "kind": kind, "detail": detail}]),
            plan_before_json=pos.plan_json or "{}",
            plan_after_json=pos.plan_json or "{}",
            verdict_at_entry="READY",
            ruleset_version=ruleset_version,
            ruleset_hash=ruleset_hash,
            created_at=now,
        )
        vs.add(row)
        vs.flush()
        if cfg.claude.enabled:
            queue_read(
                vs, pos.symbol, kind="review", reason="review", now=now, reevaluation_id=row.id
            )
        opened.append(pos.symbol)
    return opened


def mirror_reevaluations(vs: Session, day: date, now: datetime) -> int:
    """Each night: a shadow entry's re-evaluation tonight (spec §7.1's full trigger set, any
    track) on a name and list the book holds opens or joins that position's held re-evaluation,
    so adds pause and Claude's review is queued as for the hourly check."""
    n = 0
    for pos in vs.scalars(select(ValuePositionRow).where(ValuePositionRow.status == "open")):
        shadow_rows = vs.scalars(
            select(ValueReevaluationRow).where(
                ValueReevaluationRow.symbol == pos.symbol,
                ValueReevaluationRow.list_name == pos.list_name,
                ValueReevaluationRow.shadow_id > 0,
                ValueReevaluationRow.last_session == day,
            )
        ).all()
        if not shadow_rows:
            continue
        held = vs.scalars(
            select(ValueReevaluationRow).where(
                ValueReevaluationRow.position_id == pos.id,
                ValueReevaluationRow.last_session == day,
            )
        ).first()
        if held is not None:
            continue
        src = shadow_rows[0]
        row = ValueReevaluationRow(
            shadow_id=0,
            position_id=pos.id,
            symbol=pos.symbol,
            list_name=pos.list_name,
            session=day,
            last_session=day,
            severity=max(r.severity for r in shadow_rows),
            triggers_json=src.triggers_json,
            plan_before_json=pos.plan_json or "{}",
            plan_after_json=pos.plan_json or "{}",
            verdict_at_entry="READY",
            verdict_now=src.verdict_now,
            ruleset_version=src.ruleset_version,
            ruleset_hash=src.ruleset_hash,
            created_at=now,
        )
        vs.add(row)
        vs.flush()
        queue_read(vs, pos.symbol, kind="review", reason="review", now=now, reevaluation_id=row.id)
        n += 1
    return n
```

- [ ] **Step 6: Run them to see them pass** — `tests/test_value_live.py tests/test_value_fence.py`.
- [ ] **Step 7: Gates and commit:**

  ```bash
  git add src/value/book.py src/value/executor.py src/value/live.py tests/test_value_live.py
  git commit -m "feat(value): the book's rows, the executor on clientId 31, the night and the RTH cycle"
  ```

---

### Task 9: clientId 31's cycle and the book's messages

**Files:** Create `src/value/stage3.py`, `src/value/notify.py`, `tests/test_value_stage3.py` (Tasks
13 and 14 append).

- [ ] **Step 1: Write the failing tests** — create `tests/test_value_stage3.py`:

```python
"""Stage 3's process side (value book spec §9.7, §7.1; Part 5): the broker snapshot, held
re-evaluations mirrored from the shadow record, held names kept fresh, the notifier, the CLI."""

from __future__ import annotations

import asyncio

from src.common.schemas import OptionRight, PositionSnapshot
from src.value import notify
from src.value.stage3 import build_snapshot


def _p(symbol, sec, qty, **kw) -> PositionSnapshot:
    return PositionSnapshot(
        symbol=symbol,
        sec_type=sec,
        position=qty,
        avg_cost=1.0,
        underlying=kw.pop("underlying", symbol),
        **kw,
    )


def test_the_snapshot_is_the_brokers_whole_view() -> None:
    snap = build_snapshot(
        [
            _p("GOOGL", "STK", 130, market_price=150.0),
            _p("GOOGL C", "OPT", -1, underlying="GOOGL", right=OptionRight.CALL, strike=180.0),
            _p("AAPL P", "OPT", -2, underlying="AAPL", right=OptionRight.PUT, strike=200.0),
        ],
        100_000.0,
    )
    assert snap.shares == {"GOOGL": 130} and snap.marks == {"GOOGL": 150.0}
    assert snap.wheel_short_calls == {"GOOGL": 1} and snap.csp_by_name == {"AAPL": 40_000.0}
    assert (snap.stock_value, snap.csp_collateral) == (19_500.0, 40_000.0)


def test_the_notifier_logs_and_sends_nothing_without_a_token() -> None:
    assert asyncio.run(notify.send(["Value book: test"])) == 0
```

- [ ] **Step 2: Run them to see them fail** — `ModuleNotFoundError: No module named 'src.value.notify'`.
- [ ] **Step 3: The modules** — create `src/value/notify.py`:

```python
"""The value book's plain Telegram messages (spec §9.7), the minimum money needs: fills, a frozen
attribution, a funding request, a proposal waiting for a tap. Cards, buttons and digests are
Part 6. Sends to ``TELEGRAM_THREAD_VALUE`` (the main chat when it is empty). Never raises; every
message is logged whether or not it is sent. Imports nothing from ``src.notify``."""

from __future__ import annotations

import logging

from src.common.config import get_config

log = logging.getLogger(__name__)


async def send(messages: list[str]) -> int:
    """Post each message as plain text; returns how many were sent."""
    s = get_config().secrets
    for m in messages:
        log.info("value notify: %s", m)
    if not messages or not s.telegram_bot_token or not s.telegram_chat_id:
        return 0
    thread = (s.telegram_thread_value or "").strip()
    sent = 0
    try:
        from telegram import Bot

        async with Bot(token=s.telegram_bot_token) as bot:
            for m in messages:
                await bot.send_message(
                    chat_id=s.telegram_chat_id,
                    text=m,
                    message_thread_id=int(thread) if thread.isdigit() else None,
                )
                sent += 1
    except Exception:  # noqa: BLE001 - a failed message never stops the book
        log.exception("value notify failed")
    return sent
```

  …and `src/value/stage3.py`:

```python
"""Stage 3's IBKR side (spec §9.7): one RTH cycle on clientId 31.

Connects (``ibkr.client_ids.value``), reads the account and every position as the broker holds
them (both books: ``get_positions(include_value=True)``), builds the plain ``Snapshot`` the book
reads, takes the wheel's own share count W from the ledger, runs ``live.cycle`` (reconcile, sells,
buys with their funding) and, once an hour, ``live.hourly_check``; then disconnects. Paper only:
the caller never runs it with ``LIVE_TRADING=true``. ib_async and ``src.ibkr`` are imported inside
the function, so importing ``src.value`` loads neither.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from src.common.config import Config
from src.common.schemas import OptionRight, PositionSnapshot
from src.value import live
from src.value.book import get_state, totals
from src.value.store import value_session

log = logging.getLogger(__name__)


def build_snapshot(positions: list[PositionSnapshot], net_liq: float) -> live.Snapshot:
    """The broker's view as plain numbers: stock shares and marks (both books), the wheel's short
    calls per name (the sell cap) and its short puts' collateral per name."""
    shares: dict[str, float] = {}
    marks: dict[str, float] = {}
    calls: dict[str, int] = {}
    puts: dict[str, float] = {}
    for p in positions:
        sym = (p.underlying or p.symbol).upper()
        if p.sec_type == "STK":
            shares[sym] = shares.get(sym, 0.0) + p.position
            if p.market_price:
                marks[sym] = float(p.market_price)
        elif p.sec_type == "OPT" and p.position < 0:
            if p.right == OptionRight.CALL:
                calls[sym] = calls.get(sym, 0) + int(-p.position)
            elif p.right == OptionRight.PUT and p.strike:
                puts[sym] = puts.get(sym, 0.0) + p.strike * 100.0 * -p.position
    return live.Snapshot(
        net_liq=net_liq, shares=shares, marks=marks, wheel_short_calls=calls, csp_by_name=puts
    )


async def run_cycle(cfg: Config, *, now: datetime, hourly: bool) -> list[str]:
    from ib_async import IB

    import src.common.value_inputs as vi
    from src.ibkr.connection import connect_with_retry
    from src.ibkr.portfolio import get_account_snapshot_async, get_positions
    from src.storage.system_settings import is_halted
    from src.storage.wheel_shares import wheel_shares

    ib = IB()
    await connect_with_retry(
        ib,
        cfg.ibkr.host,
        cfg.ibkr_port,
        cfg.ibkr.client_ids["value"],
        timeout=cfg.ibkr.connect_timeout_seconds,
        label="value",
    )
    try:
        ib.reqMarketDataType(cfg.ibkr.market_data_type)
        positions = get_positions(ib, include_value=True)
        account = await get_account_snapshot_async(ib, cfg.secrets.ibkr_account or "")
        snap = build_snapshot(positions, account.net_liquidation)
        with value_session() as vs:
            names = set(snap.shares) | set(totals(vs).names)
            trend = bool((get_state(vs, "trend") or {}).get("brake", False))
        w = {s: x.shares for s, x in wheel_shares(sorted(names)).items()}
        msgs = await live.cycle(
            value_session,
            _broker(ib),
            snap,
            wheel=w,
            cfg=cfg.value,
            portfolio=cfg.risk.get("portfolio", {}),
            now=now,
            halted=is_halted(),
            is_live=cfg.is_live,
            trend_brake=trend,
        )
        if hourly:
            with value_session() as vs:
                held = sorted(totals(vs).names)
            with vi.research_read() as rs:
                yesterday = now.date() - timedelta(days=1)
                closes = {} if rs is None else _last_closes(rs, held, now.date())
                filings = {} if rs is None else vi.filings_between(rs, held, yesterday, now.date())
            major = {
                s
                for s, fs in filings.items()
                for f in fs
                if set(f.items) & set(cfg.value.rules.reevaluation.major_8k_items)
            }
            from src.value.ruleset import ruleset_id

            version, digest = ruleset_id(cfg.value)
            with value_session() as vs:
                opened = live.hourly_check(
                    vs,
                    snap,
                    closes,
                    major,
                    cfg=cfg.value,
                    now=now,
                    ruleset_version=version,
                    ruleset_hash=digest,
                )
            msgs += [f"Value book: {s} re-evaluation opened (adds paused)" for s in opened]
        return msgs
    finally:
        ib.disconnect()


def _broker(ib: object) -> live.ValueBroker:
    from src.value.executor import IbkrValueBroker

    return IbkrValueBroker(ib)


def _last_closes(rs: object, symbols: list[str], today: date) -> dict[str, float]:
    import src.common.value_inputs as vi

    out: dict[str, float] = {}
    for s in symbols:
        day = vi.newest_bar_before(rs, s, today)  # type: ignore[arg-type]
        if day is not None:
            out.update(vi.closes_on(rs, [s], day))  # type: ignore[arg-type]
    return out
```

- [ ] **Step 4: Run them to see them pass** — `tests/test_value_stage3.py tests/test_value_fence.py`
  (Part 2's `sys.modules` probe still loads no `ib_async`: the IBKR imports are inside functions).
- [ ] **Step 5: Gates and commit:**

  ```bash
  git add src/value/stage3.py src/value/notify.py tests/test_value_stage3.py
  git commit -m "feat(value): the book's IBKR cycle on clientId 31 and its plain messages"
  ```

- [ ] **Section C exit** — full gate (baseline + 62), protected-file diff, clean status; fill the row;
  `git commit -m "docs(plan): value book Part 5 Progress log - Section C"`.

---

## Section D — Share attribution end to end, the fault drills (Tasks 10–12) · model: opus · effort: high

**Spec to read:** §9.2 (all of it), §11, §13 failure mode 4, §16 (the "Share attribution" bullet).
Root `CLAUDE.md`: "The `src/ledger/` fence".

**Files the subagent reads:** `src/common/schemas.py` (`ParsedExecution`), `src/storage/models.py`
(`BrokerExecutionRow`), `src/storage/db.py` (`_ADDED_COLUMNS`), `src/ledger/live.py`,
`src/ledger/flex.py` (lines 169–212), `src/ledger/ingest.py` (lines 87–165, 250–300, 400–460),
`src/ibkr/portfolio.py` (lines 100–160), `scripts/healthcheck.py` (line 71),
`tests/test_ledger_ingest.py` (lines 1–70), `src/common/books.py`, `src/storage/wheel_shares.py`.

**Entry checks:**

- [ ] **D1. Section C is in**, the gate green at baseline + 62.
- [ ] **D2. The code Section D edits** (`main` at `da5d3c3`):

  ```bash
  grep -nF 'class ParsedExecution(BaseModel):' src/common/schemas.py   # 1518:
  grep -nF '    book: Mapped[str] = mapped_column(String(8), default="manual")' src/storage/models.py   # 677:
  grep -nF '        "close_reason": "VARCHAR(16)",  # CloseReason on buy-to-close orders (2026-10-11)' src/storage/db.py   # 41:
  grep -nF '        ibkr_realized_pnl=_value(getattr(rep, "realizedPNL", None)) if rep is not None else None,' src/ledger/live.py   # 83:
  grep -nF 'def _tag_books(s: Session, row_ids: set[int]) -> int:' src/ledger/ingest.py   # 269:
  grep -nF '        counts["system"] = _tag_books(s, touched_ids)' src/ledger/ingest.py   # 411:
  grep -nF 'def get_positions(ib: IB, *, include_spreads: bool = False) -> list[PositionSnapshot]:' src/ibkr/portfolio.py   # 113:
  grep -nF '        positions = get_positions(ib, include_spreads=True)  # account truth: both books' scripts/healthcheck.py   # 71:
  ```

**Section exit:** three task commits plus `docs(plan)`; full gate with pytest = baseline + 73 (62 +
2 + 2 + 7); the ledger, portfolio and web-fence suites green; protected-file diff; clean status.

---

### Task 10: `orderRef` through the ledger; value fills tagged

**Files:** Modify `src/common/schemas.py` (`ParsedExecution`), `src/storage/models.py`,
`src/storage/db.py`, `src/ledger/live.py`, `src/ledger/flex.py`, `src/ledger/ingest.py`,
`tests/test_value_attribution.py`.

**Interfaces:** `ParsedExecution.order_ref`; `broker_executions.order_ref` (added by `init_db`);
`ingest._tag_value_book`, the run's `counts["value"]`; a backfilled `orderRef` retags the row.

- [ ] **Step 1: Write the failing tests** — apply:

```diff
diff --git a/tests/test_value_attribution.py b/tests/test_value_attribution.py
index 99cfc7a..bb04cf2 100644
--- a/tests/test_value_attribution.py
+++ b/tests/test_value_attribution.py
@@ -4,10 +4,15 @@ here; tests/test_value_fault_drills.py names all seven."""
 
 from __future__ import annotations
 
+from datetime import UTC, datetime
+from types import SimpleNamespace
+
 import pytest
+from sqlalchemy import select
 
 from src.common.books import attribute, is_value_order_ref, value_sell_cap
 from src.common.value_view import ValueHolding
+from src.ledger.contracts import stock_contract
 from tests.value_book_fixtures import order
 
 
@@ -34,6 +39,85 @@ def test_a_value_sell_never_uncovers_a_wheel_call() -> None:
     assert is_value_order_ref("value:12") and not is_value_order_ref("CS:7")
 
 
+def _exec(qty: float, price: float, when: str, *, ref: str | None = None, exec_id: str):
+    from src.common.schemas import ParsedExecution
+
+    return ParsedExecution(
+        contract=stock_contract("GOOGL", "USD"),
+        trade_time=datetime.fromisoformat(when).replace(tzinfo=UTC),
+        quantity=qty,
+        price=price,
+        proceeds=-qty * price,
+        exec_id=exec_id,
+        account="U0000001",
+        source_kind="exec",
+        order_ref=ref,
+    )
+
+
+def test_an_order_ref_round_trips_live_flex_and_ingest(db) -> None:
+    """Spec §9.2: IBKR keeps orderRef on every execution; a value fill is tagged by it, never by
+    an order id (which collides across clientIds)."""
+    from xml.etree import ElementTree
+
+    from src.common.schemas import ParsedStatement
+    from src.ledger.flex import _flex_trade
+    from src.ledger.ingest import ingest
+    from src.ledger.live import fill_to_execution
+    from src.storage.models import BrokerExecutionRow
+    from src.storage.wheel_shares import wheel_shares
+
+    fill = SimpleNamespace(
+        contract=SimpleNamespace(secType="STK", symbol="GOOGL", currency="USD"),
+        execution=SimpleNamespace(
+            shares=30,
+            side="BOT",
+            time=datetime(2026, 11, 2, 15, 1, tzinfo=UTC),
+            price=150.0,
+            execId="v1",
+            permId=9,
+            orderId=7,
+            acctNumber="U0000001",
+            orderRef="value:7",
+        ),
+    )
+    live = fill_to_execution(fill)
+    assert live is not None and live.order_ref == "value:7"
+    el = ElementTree.fromstring(
+        '<Trade assetCategory="STK" symbol="GOOGL" currency="USD" quantity="30" '
+        'tradePrice="150" dateTime="20261102;100100" ibExecID="v1" orderReference="value:7" '
+        'accountId="U0000001"/>'
+    )
+    flex = _flex_trade(el)
+    assert flex is not None and flex.order_ref == "value:7"
+    wheel = [
+        _exec(100, 140.0, "2026-10-01T15:00:00", exec_id="w1"),  # an assignment at the strike
+        _exec(-20, 160.0, "2026-10-20T15:00:00", exec_id="w2"),
+    ]
+    ingest(ParsedStatement(account="U0000001", executions=[*wheel, live]), source="flex")
+    with db() as s:
+        books = {r.exec_id: r.book for r in s.scalars(select(BrokerExecutionRow))}
+    assert books == {"w1": "manual", "w2": "manual", "v1": "value"}
+    w = wheel_shares(["googl"])["GOOGL"]
+    assert w.shares == 80 and w.avg_cost == 140.0  # the value fill is not the wheel's
+
+
+def test_a_flex_only_fill_backfills_the_order_ref_and_retags(db) -> None:
+    """Drill: a fill that reached the ledger first without its orderRef is retagged when the
+    Flex row carrying it arrives."""
+    from src.common.schemas import ParsedStatement
+    from src.ledger.ingest import ingest
+    from src.storage.models import BrokerExecutionRow
+
+    bare = _exec(30, 150.0, "2026-11-02T15:01:00", exec_id="v1")
+    ingest(ParsedStatement(account="U0000001", executions=[bare]), source="csv")
+    tagged = bare.model_copy(update={"order_ref": "value:7"})
+    ingest(ParsedStatement(account="U0000001", executions=[tagged]), source="flex")
+    with db() as s:
+        row = s.scalars(select(BrokerExecutionRow)).one()
+        assert (row.book, row.order_ref) == ("value", "value:7")
+
+
 def test_a_split_corporate_action_restates_the_wheels_count() -> None:
     from src.storage.wheel_shares import split_ratio
 
```

- [ ] **Step 2: Run them to see them fail** — `ValidationError` (`order_ref` is not a field).
- [ ] **Step 3: The ledger** — apply:

```diff
diff --git a/src/common/schemas.py b/src/common/schemas.py
index 021b62f..c8e0816 100644
--- a/src/common/schemas.py
+++ b/src/common/schemas.py
@@ -1536,6 +1536,9 @@ class ParsedExecution(BaseModel):
     source_kind: LedgerSourceKind
     occurrence_idx: int = 0
     raw: dict[str, Any] = Field(default_factory=dict)
+    # The order's orderRef (live ``Execution.orderRef``; Flex ``orderReference``; an Activity CSV
+    # carries none). ``value:<id>`` marks a value-book fill (value book spec §9.2).
+    order_ref: str | None = None
 
 
 class ParsedCashEvent(BaseModel):
diff --git a/src/ledger/flex.py b/src/ledger/flex.py
index ae5db7e..53d9052 100644
--- a/src/ledger/flex.py
+++ b/src/ledger/flex.py
@@ -206,6 +206,7 @@ def _flex_trade(el: ElementTree.Element) -> ParsedExecution | None:
         ibkr_realized_pnl=float(realized) if realized else None,
         source_kind="exec" if exec_id else "order",
         raw=dict(el.attrib),
+        order_ref=(el.get("orderReference") or "").strip() or None,
     )
 
 
diff --git a/src/ledger/ingest.py b/src/ledger/ingest.py
index 56ea48e..b463a7d 100644
--- a/src/ledger/ingest.py
+++ b/src/ledger/ingest.py
@@ -15,7 +15,7 @@ from datetime import UTC, date, datetime
 from sqlalchemy import select
 from sqlalchemy.orm import Session
 
-from src.common.books import is_spreads_underlying
+from src.common.books import is_spreads_underlying, is_value_order_ref
 from src.common.schemas import (
     LedgerImportResult,
     LedgerSource,
@@ -117,6 +117,10 @@ def _upsert_execution(
         if not row.codes and e.codes:
             row.codes = e.codes
             changed = True
+        if row.order_ref is None and e.order_ref:
+            row.order_ref = e.order_ref
+            changed = True
+            order_id_backfilled = True  # the book pass must see the new orderRef too
         return False, changed, order_id_backfilled, row.id
     c = e.contract
     new_row = BrokerExecutionRow(
@@ -146,6 +150,7 @@ def _upsert_execution(
         occurrence_idx=e.occurrence_idx,
         import_run_id=run_id,
         raw=e.raw,
+        order_ref=e.order_ref,
     )
     s.add(new_row)
     s.flush()
@@ -266,6 +271,20 @@ def _tag_spreads(s: Session, row_ids: set[int]) -> int:
     return tagged
 
 
+def _tag_value_book(s: Session, row_ids: set[int]) -> int:
+    """Tag ``book="value"`` on rows whose orderRef is the value book's (``value:<id>``, spec
+    §9.2). Runs before :func:`_tag_books`: order ids collide across clientIds, an orderRef does
+    not, so a value fill is never taken for a wheel one."""
+    if not row_ids:
+        return 0
+    tagged = 0
+    for r in s.scalars(select(BrokerExecutionRow).where(BrokerExecutionRow.id.in_(row_ids))):
+        if r.book != "value" and is_value_order_ref(r.order_ref):
+            r.book = "value"
+            tagged += 1
+    return tagged
+
+
 def _tag_books(s: Session, row_ids: set[int]) -> int:
     """Tag ``book="system"`` on rows in ``row_ids`` whose ``ib_order_id`` matches a known
     ``OrderRow`` (F17): rows inserted this run, and existing rows whose ``ib_order_id`` was
@@ -280,8 +299,8 @@ def _tag_books(s: Session, row_ids: set[int]) -> int:
         )
     )
     for r in rows:
-        if r.book == "spreads":
-            continue  # an order-id collision with a wheel order must never retag a spreads row
+        if r.book in ("spreads", "value"):
+            continue  # an order-id collision with a wheel order must never retag either
         for order in s.scalars(select(OrderRow).where(OrderRow.ib_order_id == r.ib_order_id)):
             snap = order.snapshot or {}
             if not snap or snap.get("underlying") == r.underlying:
@@ -408,6 +427,7 @@ def ingest(
             affected.add((e.contract.ident, et_date(e.trade_time)))
         counts["superseded"] = supersede_twins(s, affected)
         counts["spreads"] = _tag_spreads(s, touched_ids)
+        counts["value"] = _tag_value_book(s, touched_ids)
         counts["system"] = _tag_books(s, touched_ids)
         for c in statement.cash_events:
             counts[
@@ -431,6 +451,7 @@ def ingest(
             or any_backfill
             or bool(counts["system"])
             or bool(counts["spreads"])
+            or bool(counts["value"])
         )
 
         if source == "live" and not touched:
diff --git a/src/ledger/live.py b/src/ledger/live.py
index 93ef155..9622800 100644
--- a/src/ledger/live.py
+++ b/src/ledger/live.py
@@ -82,6 +82,7 @@ def fill_to_execution(fill: Any) -> ParsedExecution | None:
         account=ex.acctNumber or None,
         ibkr_realized_pnl=_value(getattr(rep, "realizedPNL", None)) if rep is not None else None,
         source_kind="exec",
+        order_ref=(getattr(ex, "orderRef", "") or "").strip() or None,
     )
 
 
diff --git a/src/storage/db.py b/src/storage/db.py
index b3e985d..a7b071e 100644
--- a/src/storage/db.py
+++ b/src/storage/db.py
@@ -40,6 +40,8 @@ _ADDED_COLUMNS: dict[str, dict[str, str]] = {
         "snapshot": "JSON",
         "close_reason": "VARCHAR(16)",  # CloseReason on buy-to-close orders (2026-10-11)
     },
+    # The order's orderRef: "value:<id>" tags a value-book fill (value book Part 5, spec §9.2).
+    "broker_executions": {"order_ref": "VARCHAR(48)"},
     # risk_verdicts existed as an empty, unwired table long before anything wrote to it, so
     # deployed databases already have the original three-column shape. These are the columns
     # added when the assessment audit trail was turned on.
diff --git a/src/storage/models.py b/src/storage/models.py
index e744461..d4088f1 100644
--- a/src/storage/models.py
+++ b/src/storage/models.py
@@ -673,8 +673,9 @@ class BrokerExecutionRow(Base):
     ibkr_realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
     occurrence_idx: Mapped[int] = mapped_column(Integer, default=0)
     superseded_by: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
-    # "system" | "manual" | "spreads"
+    # "system" | "manual" | "spreads" | "value" (an orderRef of "value:<id>", spec §9.2)
     book: Mapped[str] = mapped_column(String(8), default="manual")
+    order_ref: Mapped[str | None] = mapped_column(String(48), nullable=True)
     import_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
     raw: Mapped[dict] = mapped_column(JSON, default=dict)
     created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
```

- [ ] **Step 4: Run them to see them pass** — `tests/test_value_attribution.py tests/test_ledger_ingest.py tests/test_ledger_live.py tests/test_ledger_flex.py tests/test_ledger_models.py tests/test_web_fence.py tests/test_openapi_current.py`.
- [ ] **Step 5: Gates and commit:**

  ```bash
  git add src/common/schemas.py src/storage/models.py src/storage/db.py src/ledger/live.py src/ledger/flex.py src/ledger/ingest.py tests/test_value_attribution.py
  git commit -m "feat(ledger): carry orderRef and tag the value book's fills by it (spec 9.2)"
  ```

---

### Task 11: The wheel sees only its own shares

**Files:** Modify `src/ibkr/portfolio.py`, `scripts/healthcheck.py`, `tests/test_value_attribution.py`.

**Interfaces:** `portfolio.wheel_view(positions)`; `get_positions(ib, *, include_spreads=False,
include_value=False)`.

- [ ] **Step 1: Write the failing tests** — apply:

```diff
diff --git a/tests/test_value_attribution.py b/tests/test_value_attribution.py
index bb04cf2..4e7ef03 100644
--- a/tests/test_value_attribution.py
+++ b/tests/test_value_attribution.py
@@ -11,6 +11,7 @@ import pytest
 from sqlalchemy import select
 
 from src.common.books import attribute, is_value_order_ref, value_sell_cap
+from src.common.schemas import PositionSnapshot
 from src.common.value_view import ValueHolding
 from src.ledger.contracts import stock_contract
 from tests.value_book_fixtures import order
@@ -118,6 +119,44 @@ def test_a_flex_only_fill_backfills_the_order_ref_and_retags(db) -> None:
         assert (row.book, row.order_ref) == ("value", "value:7")
 
 
+def _pos(symbol: str, qty: float, avg: float = 145.0) -> PositionSnapshot:
+    return PositionSnapshot(
+        symbol=symbol,
+        sec_type="STK",
+        position=qty,
+        avg_cost=avg,
+        market_value=qty * 150.0,
+        underlying=symbol,
+    )
+
+
+def test_get_positions_gives_the_wheel_its_own_shares_at_its_own_cost(db, value_book_db) -> None:
+    from src.common.schemas import ParsedStatement
+    from src.ibkr.portfolio import wheel_view
+    from src.ledger.ingest import ingest
+
+    ingest(
+        ParsedStatement(
+            account="U0000001", executions=[_exec(100, 140.0, "2026-10-01T15:00:00", exec_id="w")]
+        ),
+        source="flex",
+    )
+    order("GOOGL", shares=30, filled=30, avg=150.0)
+    out = wheel_view([_pos("GOOGL", 130), _pos("MSFT", 50)])
+    g = next(p for p in out if p.symbol == "GOOGL")
+    assert (g.position, g.avg_cost, g.market_value) == (100.0, 140.0, 15_000.0)
+    assert next(p for p in out if p.symbol == "MSFT").position == 50  # not shared: untouched
+
+
+def test_unreadable_value_db_drops_unexplained_stock(db, monkeypatch, tmp_path) -> None:
+    from src.ibkr.portfolio import wheel_view
+
+    bad = tmp_path / "value.db"
+    bad.write_bytes(b"garbage")
+    monkeypatch.setattr("src.common.value_view._path", lambda: bad)
+    assert wheel_view([_pos("MSFT", 50)]) == []  # W is 0 in an empty ledger: 50 unexplained
+
+
 def test_a_split_corporate_action_restates_the_wheels_count() -> None:
     from src.storage.wheel_shares import split_ratio
 
```

- [ ] **Step 2: Run them to see them fail** — `ImportError: cannot import name 'wheel_view'`.
- [ ] **Step 3: The view** — apply:

```diff
diff --git a/scripts/healthcheck.py b/scripts/healthcheck.py
index 9c6e410..cc924d6 100644
--- a/scripts/healthcheck.py
+++ b/scripts/healthcheck.py
@@ -68,7 +68,7 @@ def main() -> int:
         print(f"  Buying power    : {snap.buying_power:,.2f}")
         print(f"  Excess liquidity: {snap.excess_liquidity:,.2f}")
 
-        positions = get_positions(ib, include_spreads=True)  # account truth: both books
+        positions = get_positions(ib, include_spreads=True, include_value=True)  # account truth
         print(f"\nPositions ({len(positions)}):")
         if not positions:
             print("  (none)")
diff --git a/src/ibkr/portfolio.py b/src/ibkr/portfolio.py
index 65c211f..3763cd3 100644
--- a/src/ibkr/portfolio.py
+++ b/src/ibkr/portfolio.py
@@ -13,7 +13,7 @@ from datetime import date
 
 from ib_async import IB, AccountValue
 
-from src.common.books import is_spreads_underlying
+from src.common.books import attribute, is_spreads_underlying
 from src.common.config import get_config
 from src.common.logging import get_logger
 from src.common.schemas import AccountSnapshot, OptionRight, PositionSnapshot
@@ -110,7 +110,70 @@ def _parse_expiry(yyyymmdd: str) -> date | None:
         return None
 
 
-def get_positions(ib: IB, *, include_spreads: bool = False) -> list[PositionSnapshot]:
+def wheel_view(positions: list[PositionSnapshot]) -> list[PositionSnapshot]:
+    """The wheel's own share of every stock position the value book may share (spec §9.2).
+
+    With value.db readable, only names the value book holds or is buying change: each becomes
+    ``min(W, broker - V claimed)`` shares (never below zero), at the wheel's own average cost from
+    the ledger, so a race in which a value fill lands first makes the wheel see fewer shares, never
+    more, and a value purchase never moves the wheel's covered-call strike floor. With value.db
+    unreadable every stock position is checked against W and kept only where the broker agrees
+    (no covered call on unexplained shares). A name left with no wheel share is dropped.
+    """
+    from src.common.value_view import read_book
+    from src.storage.wheel_shares import wheel_shares
+
+    stock = [p for p in positions if p.sec_type == "STK" and p.position]
+    if not stock:
+        return positions
+    book = read_book()
+    shared = {
+        (p.underlying or p.symbol).upper()
+        for p in stock
+        if book is None
+        or book.holding(p.underlying or p.symbol).claimed > 0
+        or book.holding(p.underlying or p.symbol).pending_sell > 0
+    }
+    if not shared:
+        return positions
+    w = wheel_shares(sorted(shared))
+    out: list[PositionSnapshot] = []
+    for p in positions:
+        sym = (p.underlying or p.symbol).upper()
+        if p.sec_type != "STK" or sym not in shared:
+            out.append(p)
+            continue
+        att = attribute(p.position, w[sym].shares, None if book is None else book.holding(sym))
+        if att.unexplained:
+            log.warning(
+                "value attribution %s: broker %.0f, wheel %.0f, value %.0f: the wheel uses %.0f",
+                sym,
+                att.broker,
+                att.wheel,
+                att.value_filled,
+                att.wheel_view,
+            )
+        if att.wheel_view <= 0:
+            continue
+        ratio = att.wheel_view / p.position
+        out.append(
+            p.model_copy(
+                update={
+                    "position": att.wheel_view,
+                    "avg_cost": w[sym].avg_cost if w[sym].avg_cost is not None else p.avg_cost,
+                    "market_value": None if p.market_value is None else p.market_value * ratio,
+                    "unrealized_pnl": None
+                    if p.unrealized_pnl is None
+                    else p.unrealized_pnl * ratio,
+                }
+            )
+        )
+    return out
+
+
+def get_positions(
+    ib: IB, *, include_spreads: bool = False, include_value: bool = False
+) -> list[PositionSnapshot]:
     """Snapshot current positions (stocks and options) as typed objects.
 
     The daily credit-spread system trades in this same account. Its contracts
@@ -118,6 +181,10 @@ def get_positions(ib: IB, *, include_spreads: bool = False) -> list[PositionSnap
     the intraday monitor, profit-take, rolls, the scan's budget seeding, the approval re-gate,
     the EOD report — ever alerts on, sizes against, or closes a spread leg. Pass
     ``include_spreads=True`` only for an account-truth view (``scripts/healthcheck.py``).
+
+    Stock the value book holds is likewise taken out (``wheel_view``, spec §9.2): the wheel sees
+    only its own shares. ``include_value=True`` is the account-truth view (the healthcheck, and the
+    value process, which reconciles both books itself).
     """
     out: list[PositionSnapshot] = []
     skipped = 0
@@ -151,7 +218,7 @@ def get_positions(ib: IB, *, include_spreads: bool = False) -> list[PositionSnap
             )
         )
     log.info("Fetched %d portfolio positions (%d spreads-book skipped)", len(out), skipped)
-    return out
+    return out if include_value else wheel_view(out)
 
 
 # The account stream's USD exchange rate (base-currency units per USD). A plain account-update
```

- [ ] **Step 4: Run them to see them pass** — `tests/test_value_attribution.py tests/test_ibkr_portfolio.py tests/test_engine.py`, and `py_compile scripts/healthcheck.py`.
- [ ] **Step 5: Gates and commit:**

  ```bash
  git add src/ibkr/portfolio.py scripts/healthcheck.py tests/test_value_attribution.py
  git commit -m "feat(ibkr): the wheel sees only its own shares on a name the value book shares"
  ```

---

### Task 12: The seven fault drills

**Files:** Create `tests/test_value_fault_drills.py`.

- [ ] **Step 1: The drills** — create the file:

```python
"""The seven fault drills of value book spec §9.2, as unit tests (build acceptance: all must pass
before the first paper share purchase; each also has a scripted paper drill, SETUP §19). One test
per drill, named for it; each pins that the wheel never sees more shares than it owns and that an
unexplained count freezes rather than guesses."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from src.common.books import attribute
from src.common.schemas import ParsedExecution, ParsedStatement, PositionSnapshot
from src.common.value_view import read_book
from src.ledger.contracts import stock_contract
from src.value import book
from src.value.store import value_session
from tests.value_book_fixtures import NOW, order


def _exec(qty, price, when, *, exec_id, ref=None, codes=""):
    return ParsedExecution(
        contract=stock_contract("GOOGL", "USD"),
        trade_time=datetime.fromisoformat(when).replace(tzinfo=UTC),
        quantity=qty,
        price=price,
        proceeds=-qty * price,
        exec_id=exec_id,
        account="U0000001",
        source_kind="exec",
        order_ref=ref,
        codes=codes,
    )


def _ingest(*execs, source="flex"):
    from src.ledger.ingest import ingest

    ingest(ParsedStatement(account="U0000001", executions=list(execs)), source=source)


def _w() -> float:
    from src.storage.wheel_shares import wheel_shares

    return wheel_shares(["GOOGL"])["GOOGL"].shares


def _state(broker: float) -> str:
    with value_session() as s:
        book.reconcile(s, {"GOOGL": broker}, {"GOOGL": _w()}, {}, now=NOW, grace_hours=36)
        return book.get_state(s, "x") or s.get(book.ValueAttributionRow, "GOOGL").state


def test_drill_1_assignment_on_a_shared_ticker(db, value_book_db) -> None:
    order("GOOGL", shares=30, filled=30, avg=150.0)
    _ingest(_exec(100, 140.0, "2026-11-02T21:00:00", exec_id="a1", codes="A"))  # assigned put
    att = attribute(130, _w(), read_book(NOW).holding("GOOGL"))
    assert (att.wheel_view, att.unexplained) == (100.0, 0.0)  # wheel stock (spec §9.1)
    assert _state(130) == "ok"


def test_drill_2_a_partial_value_fill(db, value_book_db) -> None:
    order("GOOGL", shares=30, filled=7, avg=150.0, status="partial")
    h = read_book(NOW).holding("GOOGL")
    assert (h.filled, h.pending_buy, h.claimed) == (7.0, 23.0, 30.0)
    assert attribute(7, 0.0, h).wheel_view == 0.0  # errs short while the rest is working
    assert _state(7) == "ok"


def test_drill_3_a_restart_mid_order(db, value_book_db) -> None:
    """The order row was written before placeOrder, so after a restart the book still knows the
    working order (V claims it) and the fill, when the ledger brings it, is tagged by its ref."""
    oid = order("GOOGL", shares=30, filled=0, avg=None, status="submitted")
    assert read_book(NOW).holding("GOOGL").claimed == 30.0
    _ingest(_exec(30, 150.0, "2026-11-02T15:05:00", exec_id="v1", ref=f"value:{oid}"))
    assert _w() == 0.0  # the fill is the value book's, not the wheel's


def test_drill_4_a_split_freezes_until_restated_and_cleared(db, value_book_db) -> None:
    from src.storage.db import session_scope
    from src.storage.models import BrokerCorporateActionRow

    order("GOOGL", shares=30, filled=30, avg=150.0)
    _ingest(_exec(100, 140.0, "2026-10-01T15:00:00", exec_id="w1"))
    assert _state(130) == "ok"
    with session_scope() as s:  # the ledger records the 2-for-1 split as a corporate action
        s.add(
            BrokerCorporateActionRow(
                dedupe_key="ca1",
                event_date=date(2026, 11, 3),
                underlying="GOOGL",
                description="GOOGL(...) SPLIT 2 FOR 1",
                quantity=130,
                source="flex",
            )
        )
    assert _w() == 200.0  # W restated by the split
    with value_session() as s:
        later = NOW + timedelta(days=2)
        book.reconcile(s, {"GOOGL": 260.0}, {"GOOGL": _w()}, {}, now=later, grace_hours=36)
        assert s.get(book.ValueAttributionRow, "GOOGL").state == "pending"  # V still pre-split
        book.reconcile(
            s,
            {"GOOGL": 260.0},
            {"GOOGL": _w()},
            {},
            now=later + timedelta(hours=37),
            grace_hours=36,
        )
        assert s.get(book.ValueAttributionRow, "GOOGL").state == "frozen"
        assert book.apply_split(s, "GOOGL", 2.0, later) == 1
        book.reconcile(s, {"GOOGL": 260.0}, {"GOOGL": _w()}, {}, now=later, grace_hours=36)
        assert s.get(book.ValueAttributionRow, "GOOGL").state == "frozen"  # a human clears it
        assert book.clear_attribution(s, "GOOGL", later)
    assert read_book(NOW).holding("GOOGL").filled == 60.0


def test_drill_5_a_manual_tws_trade(db, value_book_db) -> None:
    """A trade placed by hand is wheel stock once the ledger has it; before then the shares are
    unexplained and the wheel sees fewer, never more."""
    order("GOOGL", shares=30, filled=30, avg=150.0)
    _ingest(_exec(100, 140.0, "2026-10-01T15:00:00", exec_id="w1"))
    before = attribute(150, _w(), read_book(NOW).holding("GOOGL"))
    assert (before.wheel_view, before.unexplained) == (100.0, 20.0)
    _ingest(_exec(20, 151.0, "2026-11-02T16:00:00", exec_id="m1"))  # untagged: manual
    after = attribute(150, _w(), read_book(NOW).holding("GOOGL"))
    assert (after.wheel_view, after.unexplained) == (120.0, 0.0)


def test_drill_6_flex_only_arrival_of_a_fill(db, value_book_db) -> None:
    oid = order("GOOGL", shares=30, filled=30, avg=150.0)
    _ingest(_exec(30, 150.0, "2026-11-02T15:05:00", exec_id="v1"), source="csv")  # no ref
    assert _w() == 30.0  # counted twice (W and V): the reconcile catches it
    assert attribute(30, _w(), read_book(NOW).holding("GOOGL")).unexplained == -30.0
    _ingest(_exec(30, 150.0, "2026-11-02T15:05:00", exec_id="v1", ref=f"value:{oid}"))
    assert _w() == 0.0  # Flex brought the ref: retagged value


def test_drill_7_value_db_unreadable(db, monkeypatch, tmp_path) -> None:
    from src.ibkr.portfolio import wheel_view

    bad = tmp_path / "value.db"
    bad.write_bytes(b"garbage")
    monkeypatch.setattr("src.common.value_view._path", lambda: bad)
    assert read_book(NOW) is None
    _ingest(_exec(100, 140.0, "2026-10-01T15:00:00", exec_id="w1"))
    pos = [
        PositionSnapshot(
            symbol="GOOGL", sec_type="STK", position=p, avg_cost=140.0, underlying="GOOGL"
        )
        for p in (100, 130)
    ]
    assert wheel_view(pos[:1])[0].position == 100  # broker agrees with W: kept
    assert wheel_view(pos[1:]) == []  # 30 unexplained: no covered call at all
```

- [ ] **Step 2: Run them** — `.venv/bin/python -m pytest -q tests/test_value_fault_drills.py`: 7
  passed. A drill that fails is a defect in Tasks 3, 8, 10 or 11: fix it there (TDD), record the
  ruling, never weaken the drill.
- [ ] **Step 3: Gates and commit:**

  ```bash
  git add tests/test_value_fault_drills.py
  git commit -m "test(value): the seven fault drills of spec 9.2 as unit tests"
  ```

- [ ] **Section D exit** — full gate (baseline + 73), protected-file diff, clean status; fill the row;
  `git commit -m "docs(plan): value book Part 5 Progress log - Section D"`.

---

## Section E — The process, the spec amendment, the docs (Tasks 13–15) · model: sonnet · effort: high

**Spec to read:** §9.7, §7.1 (held positions), §18, §21 (Task 15 writes it).

**Files the subagent reads:** `src/value/service.py`, `scripts/run_value.py`,
`tests/test_value_fence.py`, `src/value/live.py`, `src/value/stage3.py`, `src/value/book.py`, and the
docs' value sections (`CLAUDE.md`'s value fence, `ARCHITECTURE.md`'s `src/value/` and `src/common/`
sections, `SETUP.md` §19, `STATUS.md`'s Part 4 entry, the spec's §9.3 and §14).

**Entry checks:**

- [ ] **E1. Section D is in**, the gate green at baseline + 73.
- [ ] **E2. The code Section E edits** (every line below is Part 4's text: re-grep the merged tree):

  ```bash
  grep -nF '        for symbol in followed_names(vs, now, vcfg.ticker_file.follow_days):' src/value/service.py   # 180:   (Part 4)
  grep -nF '            keep_fresh = sorted(shadow_names(vs))' src/value/service.py   # 365:   (Part 4)
  grep -nF '                "claude": {**claude_night, "applied": applied, "breaker": tripped, **queued},' src/value/service.py   # 351:   (Part 4)
  grep -nF 'def _claude_tick() -> None:' scripts/run_value.py   # 74:   (Part 4)
  grep -nF '        "src.value_ai.analyst",' tests/test_value_fence.py   # 283:   (Part 4)
  grep -nF '- Parts 1–4 place, size and gate nothing: every shadow row is hypothetical. Claude' CLAUDE.md   # 440:   (Part 4)
  grep -nF '## Built (2026-10-30 — value book Part 4: Claude as the analyst)' STATUS.md   # 350:   (Part 4)
  grep -nF '### `src/value_ai/` — Claude as the value book' ARCHITECTURE.md   # 1284:   (Part 4)
  grep -nF '### 9.3 The pot — "dedicated" has to mean something' docs/superpowers/specs/2026-10-28-value-swing-book-design.md   # 881:
  ```

**Section exit:** three task commits plus `docs(plan)`; full gate with pytest = baseline + 77;
`py_compile` of `scripts/run_value.py`, `value_book.py`, `value_claude.py`, `value_report.py`,
`healthcheck.py` silent; protected-file diff; clean status.

---

### Task 13: The night's book step

**Files:** Modify `src/value/service.py`, `tests/test_value_stage3.py`.

**Interfaces:** `service.BookHooks(may_auto_open, auto_close, halted, is_live)`,
`service.held_names(vs)`, `run_nightly(..., book=None)`; held names are scored (`held:trading`),
kept fresh and read for filings; the summary gains `"book"`.

- [ ] **Step 1: The failing test** — apply:

```diff
diff --git a/tests/test_value_stage3.py b/tests/test_value_stage3.py
index a7e7989..c870335 100644
--- a/tests/test_value_stage3.py
+++ b/tests/test_value_stage3.py
@@ -4,10 +4,21 @@ re-evaluations mirrored from the shadow record, held names kept fresh, the notif
 from __future__ import annotations
 
 import asyncio
+from datetime import date
+
+from sqlalchemy import select
 
 from src.common.schemas import OptionRight, PositionSnapshot
-from src.value import notify
+from src.value import live, notify
+from src.value.service import held_names
 from src.value.stage3 import build_snapshot
+from src.value.store import (
+    ValueClaudeReadRow,
+    ValuePositionRow,
+    ValueReevaluationRow,
+    value_session,
+)
+from tests.value_book_fixtures import NOW, order
 
 
 def _p(symbol, sec, qty, **kw) -> PositionSnapshot:
@@ -35,5 +46,46 @@ def test_the_snapshot_is_the_brokers_whole_view() -> None:
     assert (snap.stock_value, snap.csp_collateral) == (19_500.0, 40_000.0)
 
 
+def _position() -> int:
+    order("STDY", shares=20, filled=20, avg=30.0)
+    with value_session() as s:
+        pos = ValuePositionRow(symbol="STDY", list_name="deep_value", opened_on=date(2026, 10, 1))
+        s.add(pos)
+        s.flush()
+        return pos.id
+
+
+def test_a_shadow_reevaluation_tonight_is_mirrored_onto_the_held_position(value_book_db) -> None:
+    pid = _position()
+    day = date(2026, 11, 2)
+    with value_session() as s:
+        s.add(
+            ValueReevaluationRow(
+                shadow_id=7,
+                symbol="STDY",
+                list_name="deep_value",
+                session=day,
+                last_session=day,
+                severity="minor",
+                triggers_json='[{"kind": "kill"}]',
+                plan_before_json="{}",
+                plan_after_json="{}",
+                verdict_at_entry="READY",
+                ruleset_version="v4",
+                ruleset_hash="x",
+                created_at=NOW,
+            )
+        )
+    with value_session() as s:
+        assert live.mirror_reevaluations(s, day, NOW) == 1
+        assert live.mirror_reevaluations(s, day, NOW) == 0  # once a session
+        held = s.scalars(
+            select(ValueReevaluationRow).where(ValueReevaluationRow.position_id == pid)
+        ).one()
+        assert (held.shadow_id, held.triggers_json) == (0, '[{"kind": "kill"}]')
+        assert s.scalars(select(ValueClaudeReadRow)).one().kind == "review"
+        assert held_names(s) == {"STDY"}
+
+
 def test_the_notifier_logs_and_sends_nothing_without_a_token() -> None:
     assert asyncio.run(notify.send(["Value book: test"])) == 0
```

- [ ] **Step 2: Run it to see it fail** — `ImportError: cannot import name 'held_names'`.
- [ ] **Step 3: The night** — apply:

```diff
diff --git a/src/value/service.py b/src/value/service.py
index c384006..e45fb3a 100644
--- a/src/value/service.py
+++ b/src/value/service.py
@@ -20,6 +20,7 @@ from __future__ import annotations
 import json
 import logging
 from collections import Counter
+from collections.abc import Callable
 from dataclasses import asdict, dataclass, field
 from datetime import UTC, date, datetime, timedelta
 from typing import Any
@@ -33,12 +34,14 @@ from src.common.config import get_config
 from src.common.value_keep_fresh import write_filing_reads, write_keep_fresh
 from src.common.value_types import Classification, MarketFacts, NewsVolume, ValueInputs
 from src.common.value_universe import build_value_universe
-from src.value import claude_verdicts, reevaluate, shadow
+from src.value import claude_verdicts, live, reevaluate, shadow, sizing
+from src.value.book import set_state
 from src.value.claude_reads import plan_auto_reads, plan_filing_reads
 from src.value.rank import filed_lists, rank_list, rs_cutoff
 from src.value.ruleset import ruleset_id
 from src.value.scorecard import build_scorecard
 from src.value.store import (
+    ValuePositionRow,
     ValueRunRow,
     ValueShadowRow,
     ValueTickerFileRow,
@@ -151,6 +154,23 @@ def previous_regime(vs: Session) -> str | None:
     return regime if isinstance(regime, str) else None
 
 
+@dataclass(frozen=True)
+class BookHooks:
+    """What the night's book step reads from the trading side (Part 5), passed in by the
+    entrypoint so ``src/value/`` stays free of the trading database's settings: the autonomy
+    ladder for buys, the auto-close switch for Python's sells, the kill switch, live or paper."""
+
+    may_auto_open: Callable[[str], bool]
+    auto_close: bool
+    halted: bool
+    is_live: bool
+
+
+def held_names(vs: Session) -> set[str]:
+    """Names the value book holds (Part 5): scored nightly, kept fresh, read for filings."""
+    return set(vs.scalars(select(ValuePositionRow.symbol).where(ValuePositionRow.status == "open")))
+
+
 def plan_run(now: datetime | None = None, universe: dict[str, Any] | None = None) -> RunPlan | None:
     """Tonight's plan, or None when no newly settled session is waiting. *as_of* is SPY's newest
     bar dated before today (ET): a bar dated today may still be forming."""
@@ -179,6 +199,8 @@ def plan_run(now: datetime | None = None, universe: dict[str, Any] | None = None
             tags.setdefault(symbol, f"held:{entered_from}")
         for symbol in followed_names(vs, now, vcfg.ticker_file.follow_days):
             tags.setdefault(symbol, "lookup")
+        for symbol in held_names(vs):
+            tags.setdefault(symbol, "held:trading")  # held by the book, out of the universe
         positions = open_positions(vs)
     companies = [s for s in u.all_names() if s not in u.etfs]
     with vi.research_read() as rs:
@@ -252,6 +274,7 @@ def run_nightly(
     now: datetime | None = None,
     recent_earnings: dict[str, list[date]] | None = None,
     news: dict[str, NewsVolume] | None = None,
+    book: BookHooks | None = None,
 ) -> dict[str, Any]:
     """Score, rank, persist the ticker files, run the shadow record and log the run, all in one
     value.db transaction. Returns the run's summary. *recent_earnings* (report dates up to the
@@ -306,6 +329,7 @@ def run_nightly(
                     for (sym, _), eff in effective.items()
                     if eff.verdict == "READY" and plan.tags.get(sym) == "trading"
                 }
+                | held_names(vs)
             )
             tripped = claude_verdicts.check_breaker(vs, vcfg, claude_night, started)
             kill = claude_verdicts.update_kill_triggers(vs, cards, vcfg, plan.as_of)
@@ -336,6 +360,11 @@ def run_nightly(
                 opinions=ops,
                 kill=kill,
             )
+            book_summary: dict[str, Any] = {}
+            if vcfg.book.enabled and book is not None:
+                book_summary = _book_night(
+                    vs, rs, cards, effective, plan, book, now=started, cfg=vcfg
+                )
             verdicts = {
                 name: dict(Counter(c.verdict_for(name) for c in cards))
                 for name in ("deep_value", "quality_growth")
@@ -349,6 +378,7 @@ def run_nightly(
                 ),
                 "shadow": asdict(record),
                 "claude": {**claude_night, "applied": applied, "breaker": tripped, **queued},
+                "book": book_summary,
             }
             record_run(
                 vs,
@@ -362,10 +392,54 @@ def run_nightly(
                 rs_cutoff_6m=cutoff,
                 summary_json=json.dumps(summary, sort_keys=True),
             )
-            keep_fresh = sorted(shadow_names(vs))
+            keep_fresh = sorted(set(shadow_names(vs)) | held_names(vs))
     # After the commit: a failed night leaves the previous list in place. The research sweep
     # reads this file to keep held names' bars and filings current (spec §6.9).
     write_keep_fresh(keep_fresh)
     write_filing_reads(deep_reads if vcfg.claude.enabled else [])
     log.info("value nightly %s: %d names; %s", plan.as_of, len(cards), json.dumps(summary))
     return summary
+
+
+def _book_night(
+    vs: Session,
+    rs: Session,
+    cards: list[Any],
+    effective: dict[tuple[str, str], Any],
+    plan: RunPlan,
+    hooks: BookHooks,
+    *,
+    now: datetime,
+    cfg: Any,
+) -> dict[str, Any]:
+    """The night's money step (Part 5): mirror tonight's re-evaluations onto held positions, set
+    the trend brake, step the held plans and propose tonight's buys and sells."""
+    by_symbol = {c.symbol: c for c in cards}
+    names = held_names(vs) | {s for (s, _), e in effective.items() if e.verdict == "READY"}
+    bars = shadow.load_bars(rs, names | {shadow.BENCHMARK}, plan.as_of)
+    spy = [(b.date, b.close) for b in bars.get(shadow.BENCHMARK, [])]
+    brake = bool(sizing.trend_brake(sizing.month_end_closes(spy)))
+    set_state(vs, "trend", {"brake": brake, "as_of": plan.as_of.isoformat()}, now)
+    mirrored = live.mirror_reevaluations(vs, plan.as_of, now)
+    facts = {}
+    for (symbol, list_name), eff in effective.items():
+        fact = shadow.day_facts(by_symbol.get(symbol), list_name, None, eff.fair_value)
+        if fact is not None:
+            facts[(symbol, list_name)] = fact
+    night = live.plan_night(
+        vs,
+        cards=by_symbol,
+        tags=plan.tags,
+        bars=bars,
+        facts=facts,
+        cfg=cfg,
+        portfolio=get_config().risk.get("portfolio", {}),
+        now=now,
+        today=plan.as_of,
+        may_auto_open=hooks.may_auto_open,
+        auto_close=hooks.auto_close,
+        halted=hooks.halted,
+        is_live=hooks.is_live,
+        trend_brake=brake,
+    )
+    return {**asdict(night), "trend_brake": brake, "mirrored": mirrored}
```

- [ ] **Step 4: Run them to see them pass** — `tests/test_value_stage3.py tests/test_value_service.py tests/test_value_shadow.py tests/test_value_claude.py`.
- [ ] **Step 5: Gates and commit:**

  ```bash
  git add src/value/service.py tests/test_value_stage3.py
  git commit -m "feat(value): the night's book step - held names, the trend brake, proposals"
  ```

---

### Task 14: The entrypoint, the operator's CLI, the fences

**Files:** Modify `scripts/run_value.py`, `tests/test_value_fence.py`, `tests/test_value_stage3.py`;
create `scripts/value_book.py`.

- [ ] **Step 1: The failing tests** — apply:

```diff
diff --git a/tests/test_value_fence.py b/tests/test_value_fence.py
index 290eaf6..89b5a93 100644
--- a/tests/test_value_fence.py
+++ b/tests/test_value_fence.py
@@ -38,6 +38,8 @@ PURE = (
     "effective",
     "kill_triggers",
     "grounding",
+    "risk",
+    "sizing",
 )
 
 FORBIDDEN_FOR_VALUE = (
@@ -210,6 +212,12 @@ def test_only_src_value_constructs_value_rows() -> None:
         "ValueClaudeFactRow(",
         "ValueEffectiveRow(",
         "ValueClaudeStateRow(",
+        "ValueOrderRow(",
+        "ValuePositionRow(",
+        "ValueProposalRow(",
+        "ValueFundingRow(",
+        "ValueAttributionRow(",
+        "ValueBookStateRow(",
     )
     offenders = []
     for p in [*(ROOT / "src").rglob("*.py"), *(ROOT / "scripts").rglob("*.py")]:
@@ -281,6 +289,12 @@ def test_the_value_entrypoint_imports_only_its_feed_and_the_service() -> None:
         "src.value.claude_reads",
         "src.value.service",
         "src.value_ai.analyst",
+        # Part 5 (Stage 3): the trading side's switches, read for the night; the RTH cycle
+        "zoneinfo",
+        "src.common.market_hours",
+        "src.storage.system_settings",
+        "src.value.notify",
+        "src.value.stage3",
     )
     mods = imported_modules(ROOT / "scripts" / "run_value.py")
     extra = sorted(m for m in mods if not any(m == a or m.startswith(a + ".") for a in allowed))
@@ -388,3 +402,45 @@ def test_the_analyst_loads_no_wheel_layer_and_no_value_code() -> None:
     bad = [m for m in FORBIDDEN_FOR_VALUE_AI if _reaches(loaded, m)]
     assert bad == [] and not _reaches(loaded, "ib_async")
     assert not _reaches(loaded, "src.news.store.session")
+
+
+def test_the_wheel_reads_the_value_book_only_through_the_read_only_view() -> None:
+    """Spec §9.1-§9.2, §16 (Part 5): src/common/value_view.py opens value.db read-only with plain
+    SQL and imports nothing of the value book, and it (with src.common.books) is the only way the
+    engine, execution, strategies and the IBKR readers learn of the book."""
+    mods = imported_modules(ROOT / "src" / "common" / "value_view.py")
+    assert {m.split(".")[0] for m in mods} <= {
+        "__future__",
+        "logging",
+        "sqlite3",
+        "dataclasses",
+        "datetime",
+        "pathlib",
+        "src",
+    }
+    assert all(_reaches({m}, "src.common.config") for m in mods if m.startswith("src."))
+    text = (ROOT / "src" / "common" / "value_view.py").read_text(encoding="utf-8")
+    assert "mode=ro" in text and "INSERT" not in text.upper().replace("INSERTED", "")
+    offenders = [
+        str(p.relative_to(ROOT))
+        for pkg in ("engine", "execution", "strategies", "ibkr", "notify", "orchestrator")
+        for p in sorted((ROOT / "src" / pkg).rglob("*.py"))
+        if "value_db_url" in p.read_text(encoding="utf-8")
+        or _reaches(imported_modules(p), "src.value")
+    ]
+    assert offenders == []  # no other way to the value database's path or code
+
+
+def test_the_money_modules_read_no_claude_prose_or_facts() -> None:
+    """Spec §9.4, §16: the gate and the book read what an LLM produced only as the effective
+    verdict and fair value Python computed and clamped; never notes, kill triggers or facts."""
+    prose = ("ValueClaudeNoteRow", "ValueKillTriggerRow", "ValueClaudeFactRow", "src.value_ai")
+    offenders = [
+        f"{name}: {word}"
+        for name in ("risk", "sizing", "book", "live", "executor", "stage3")
+        for word in prose
+        if word in (ROOT / "src" / "value" / f"{name}.py").read_text(encoding="utf-8")
+    ]
+    assert offenders == []
+    risk_mods = imported_modules(ROOT / "src" / "value" / "risk.py")
+    assert not _reaches(risk_mods, "src.value.store")  # the gate reads nothing itself
diff --git a/tests/test_value_stage3.py b/tests/test_value_stage3.py
index c870335..aee3ef1 100644
--- a/tests/test_value_stage3.py
+++ b/tests/test_value_stage3.py
@@ -10,10 +10,12 @@ from sqlalchemy import select
 
 from src.common.schemas import OptionRight, PositionSnapshot
 from src.value import live, notify
+from src.value.book import totals
 from src.value.service import held_names
 from src.value.stage3 import build_snapshot
 from src.value.store import (
     ValueClaudeReadRow,
+    ValueOrderRow,
     ValuePositionRow,
     ValueReevaluationRow,
     value_session,
@@ -89,3 +91,36 @@ def test_a_shadow_reevaluation_tonight_is_mirrored_onto_the_held_position(value_
 
 def test_the_notifier_logs_and_sends_nothing_without_a_token() -> None:
     assert asyncio.run(notify.send(["Value book: test"])) == 0
+
+
+def test_the_operator_cli_taps_clears_and_restates(value_book_db, capsys) -> None:
+    from scripts.value_book import main
+    from src.value.book import propose
+    from src.value.store import ValueAttributionRow
+
+    order("STDY", shares=20, filled=20, avg=30.0)
+    with value_session() as s:
+        pid = propose(
+            s,
+            kind="buy",
+            symbol="STDY",
+            list_name="deep_value",
+            shares=10,
+            price=30.0,
+            reason="tranche 2",
+            cause="python",
+            auto=False,
+            now=NOW,
+            ttl_hours=1e6,
+        ).id
+        s.add(
+            ValueAttributionRow(
+                symbol="STDY", broker=40, wheel=0, value_filled=20, state="frozen", updated_at=NOW
+            )
+        )
+    assert main(["--approve", str(pid), "--split", "STDY", "2:1", "--clear", "STDY"]) == 0
+    out = capsys.readouterr().out
+    assert f"proposal {pid}: approved" in out and "STDY: cleared" in out
+    with value_session() as s:
+        assert totals(s).names["STDY"].filled == 40.0
+        assert s.scalars(select(ValueOrderRow)).one().avg_price == 15.0
```

- [ ] **Step 2: Run them to see them fail** — `ModuleNotFoundError: No module named 'scripts.value_book'`
  and the entrypoint allowlist (it does not import the new modules yet: the test passes; the CLI
  test fails).
- [ ] **Step 3: The entrypoint** — apply (never import it; `py_compile` it):

```diff
diff --git a/scripts/run_value.py b/scripts/run_value.py
index 79bd152..385afa3 100644
--- a/scripts/run_value.py
+++ b/scripts/run_value.py
@@ -3,14 +3,18 @@
 Usage:
     python -m scripts.run_value
 
-No IBKR connection, no clientId (Parts 1-4). Every ``value.service.poll_seconds`` it asks
+No IBKR connection in Parts 1-4; clientId 31 (``ibkr.client_ids.value``) from Part 5. Every ``value.service.poll_seconds`` it asks
 ``src.value.service.plan_run`` whether a settled session is waiting to be scored; when one is
 (after ``value.service.run_hour_et``), it gathers the plain data ``src/value/`` may not fetch
 itself (``scripts/value_feed.py``: earnings dates, news volume, market facts) and runs the
 night, its §7.1 re-evaluations included. Then, with ``value.claude.enabled``, it runs Claude's
 queued reads (``src.value.claude_reads.run_queue``) through the analyst in ``src.value_ai``
 (spec §8): the operator's requests on every poll, the automatic set after a night, within the
-day's caps. Idles when the ruleset check fails.
+day's caps. With ``value.book.enabled`` (Part 5, paper only) it also passes the night the trading
+side's autonomy, auto-close and halt state, and during RTH runs the book's cycle on clientId 31
+every ``book.cycle_minutes`` (``src.value.stage3``: reconcile, sells, buys funded by capital
+release), its hourly check, and sends the book's messages. Idles when the ruleset check fails;
+the book idles in live (``LIVE_TRADING=true``).
 Runs until SIGINT/SIGTERM. Supervised by scripts.start like the other daemons.
 
 The only module that imports ``src.value_ai`` (spec §5, §16). Never import this file: check it
@@ -21,7 +25,7 @@ import asyncio
 import logging
 import signal
 import threading
-from datetime import UTC, datetime
+from datetime import UTC, datetime, timedelta
 
 import src.common.value_inputs as vi
 from scripts.value_feed import (
@@ -36,7 +40,7 @@ from src.common.logging import setup_logging
 from src.common.value_ai_types import AnalystRequest, AnalystResult, FilingSection
 from src.common.value_types import ValueFinancials
 from src.value.claude_reads import run_queue
-from src.value.service import plan_run, run_nightly, startup_check
+from src.value.service import BookHooks, plan_run, run_nightly, startup_check
 from src.value_ai.analyst import Analyst
 
 log = logging.getLogger("value")
@@ -71,6 +75,65 @@ def _financials(symbol: str) -> ValueFinancials | None:
     return vi.build_value_financials(payload, as_of=datetime.now(UTC).date(), stale_item_days=stale)
 
 
+def _book_hooks() -> BookHooks | None:
+    """The trading side's switches for the night's book step (Part 5), read here so src/value
+    never opens the trading database's settings itself."""
+    cfg = get_config()
+    if not cfg.value.book.enabled:
+        return None
+    from src.storage.system_settings import is_halted, may_auto_open
+
+    return BookHooks(
+        may_auto_open=may_auto_open,
+        auto_close=cfg.automation.auto_close_enabled,
+        halted=is_halted(),
+        is_live=cfg.is_live,
+    )
+
+
+_last_cycle: datetime | None = None
+_last_hourly: datetime | None = None
+
+
+def _in_rth(now_utc: datetime) -> bool:
+    from zoneinfo import ZoneInfo
+
+    from src.common.market_hours import is_early_close, is_trading_day
+
+    et = now_utc.replace(tzinfo=UTC).astimezone(ZoneInfo("America/New_York"))
+    close = 13 if is_early_close(et.date()) else 16
+    minutes = et.hour * 60 + et.minute
+    return is_trading_day(et.date()) and 9 * 60 + 35 <= minutes < close * 60 - 5
+
+
+def _book_tick() -> None:
+    """Stage 3's RTH cycle (paper only)."""
+    global _last_cycle, _last_hourly
+    cfg = get_config()
+    if not cfg.value.book.enabled:
+        return
+    if cfg.is_live:
+        log.critical("value: the book idles in live (paper only until a live plan exists)")
+        return
+    now = datetime.now(UTC).replace(tzinfo=None)
+    if not _in_rth(now):
+        return
+    if _last_cycle is not None and now - _last_cycle < timedelta(
+        minutes=cfg.value.book.cycle_minutes
+    ):
+        return
+    hourly = _last_hourly is None or now - _last_hourly >= timedelta(hours=1)
+    import src.value.notify as notify
+    import src.value.stage3 as stage3
+
+    msgs = asyncio.run(stage3.run_cycle(cfg, now=now, hourly=hourly))
+    _last_cycle = now
+    if hourly:
+        _last_hourly = now
+    if msgs:
+        asyncio.run(notify.send(msgs))
+
+
 def _claude_tick() -> None:
     """Claude's queued reads (spec §8.5): requests first, then the automatic set, within the
     day's caps. Each read commits on its own; a failed read is recorded, never retried blind."""
@@ -104,6 +167,7 @@ def _tick() -> None:
             earnings=earnings_dates(plan.as_of),
             recent_earnings=recent_earnings(plan.as_of, plan.positions),
             news=news_volume(sorted(plan.positions)),
+            book=_book_hooks(),
         )
     except Exception:
         n = _retry.failed(plan.as_of)
@@ -142,6 +206,10 @@ def main() -> None:
             _claude_tick()
         except Exception:  # noqa: BLE001 - a failed read is recorded; the queue waits
             log.exception("value: claude reads failed; the queue waits for the next poll")
+        try:
+            _book_tick()
+        except Exception:  # noqa: BLE001 - a failed cycle sends nothing; the next one retries
+            log.exception("value: the book cycle failed; retrying at the next poll")
         if stop.wait(poll):
             break
 
```

- [ ] **Step 4: The CLI** — create `scripts/value_book.py`:

```python
"""The operator's handle on the value book's money (spec §9; Part 5, paper only).

Usage:
    python -m scripts.value_book                       # holdings, proposals, funding, freezes
    python -m scripts.value_book --approve 12          # a tap: approve a pending proposal
    python -m scripts.value_book --reject 12
    python -m scripts.value_book --clear GOOGL         # clear a frozen share attribution
    python -m scripts.value_book --split GOOGL 2:1     # restate the book after a split
    python -m scripts.value_book --reset-drawdown      # the drawdown breaker (spec §9.6)

Writes value.db only through ``src/value/`` (the one writer). The value process acts on an
approved proposal at its next RTH cycle. Part 6 adds the same taps as Telegram and web buttons.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import select

from src.value.book import apply_split, clear_attribution, decide, get_state, set_state, totals
from src.value.store import (
    ValueAttributionRow,
    ValueFundingRow,
    ValueProposalRow,
    init_value_db,
    value_session,
)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--approve", type=int, metavar="ID")
    ap.add_argument("--reject", type=int, metavar="ID")
    ap.add_argument("--clear", metavar="SYMBOL")
    ap.add_argument("--split", nargs=2, metavar=("SYMBOL", "N:M"))
    ap.add_argument("--reset-drawdown", action="store_true")
    args = ap.parse_args(argv)
    now = datetime.now(UTC).replace(tzinfo=None)
    init_value_db()
    with value_session() as vs:
        if args.approve is not None:
            print(
                f"proposal {args.approve}: {decide(vs, args.approve, approve=True, now=now, by='cli')}"
            )
        if args.reject is not None:
            print(
                f"proposal {args.reject}: {decide(vs, args.reject, approve=False, now=now, by='cli')}"
            )
        if args.clear:
            done = clear_attribution(vs, args.clear, now)
            print(f"{args.clear.upper()}: {'cleared' if done else 'nothing to clear'}")
        if args.split:
            new, old = (float(x) for x in args.split[1].split(":"))
            count = apply_split(vs, args.split[0], new / old, now)
            print(f"{args.split[0].upper()}: {count} order(s) restated x{new / old:g}; --clear it")
        if args.reset_drawdown:
            state = get_state(vs, "high_water") or {}
            set_state(
                vs, "high_water", {**state, "stop": False, "high": state.get("value", 0)}, now
            )
            print("drawdown breaker reset")
        t = totals(vs)
        print("holdings:")
        for s, n in sorted(t.names.items()):
            if n.filled or n.working_buy_cost:
                print(f"  {s:<6} {n.list_name:<15} {n.filled:>8g} sh  cost {n.cost:>12,.2f}")
        print("open proposals:")
        for p in vs.scalars(
            select(ValueProposalRow)
            .where(ValueProposalRow.status.in_(("pending", "approved", "funding")))
            .order_by(ValueProposalRow.id)
        ):
            tap = "TAP" if p.status == "pending" else p.status
            print(
                f"  #{p.id:<4} {p.kind:<4} {p.symbol:<6} {p.shares:g} ({p.reason}, {p.cause}) {tap}"
            )
        for r in vs.scalars(select(ValueFundingRow).where(ValueFundingRow.status == "open")):
            print(
                f"  funding #{r.id} {r.symbol} ${r.needed_usd:,.0f} until {r.expires_at:%m-%d %H:%M}"
            )
        for a in vs.scalars(select(ValueAttributionRow).where(ValueAttributionRow.state != "ok")):
            print(f"  attribution {a.symbol}: {a.state.upper()} ({a.detail})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run them to see them pass** — `tests/test_value_stage3.py tests/test_value_fence.py tests/test_eval_skills.py tests/test_web_fence.py tests/test_spreads_fence.py`, and `py_compile` of the two scripts.
- [ ] **Step 6: Gates and commit:**

  ```bash
  git add scripts/run_value.py scripts/value_book.py tests/test_value_fence.py tests/test_value_stage3.py
  git commit -m "feat(value): the book's RTH cycle in the value process, and the operator's CLI"
  ```

---

### Task 15: Spec revision 4 and the docs

**Files:** Modify `docs/superpowers/specs/2026-10-28-value-swing-book-design.md` (the header's
revision list, a pointer note at §9.3, §14 question 1, a new §21), `CLAUDE.md` (the value fence),
`ARCHITECTURE.md` (`src/value/` money section, `src/common/value_view.py`), `SETUP.md` (§19 step 10,
the scripts table), `STATUS.md` (a Part 5 entry). `docs/web/commands.md` was updated in Task 6.
`README.md` is unchanged: no Telegram command is added (the taps are a CLI, ruling 14).

- [ ] **Step 1: Apply the doc and spec diff:**

```diff
diff --git a/ARCHITECTURE.md b/ARCHITECTURE.md
index ad2eb9d..a94d7ba 100644
--- a/ARCHITECTURE.md
+++ b/ARCHITECTURE.md
@@ -1039,6 +1039,7 @@ outstanding).
 | `value_ai_types.py` | Part 4: the plain shapes between `src/value/` and `src/value_ai/` (`AnalystRequest`, `DriverBounds`, `Drivers`, `AnalystReply`, `KillTrigger`, `ProposedFact`, `FilingSection`, `AnalystCall`, `AnalystResult`). Imports only pydantic, so neither package imports the other. |
 | `value_types.py` | The value book's plain input shapes (`ValueFinancials`, `PriceSeries`, `DayBar` (with `high`/`low` since Part 3), `FilingEvent`, `NewsVolume`, `Classification`, `MarketFacts`, `ValueInputs`). Imports only pydantic, so the scorecard, the loader and (Part 6) the API share them. |
 | `value_inputs.py` | The value book's one read-only input loader: research.db opened `mode=ro` (the raw companyfacts payload through `select_periods(as_of=)` / `select_ttm`, daily bars), the regime through `load_regime_state`, fixed-window technicals through `src/analytics/technicals.py`, and `fetch_market_facts` (yfinance market cap, industry, next earnings, through `src/data`). Part 2 adds `build_day_bars` (one session at a time with its technicals, for the exit engine), `newest_bar_before`, `closes_on`, `filings_coverage` and `symbol_is_etf`; Part 3 `filings_between` (the filing index, trigger 4) and `going_concern_flags` (the newest read periodic filing's flag; a name with none read is absent, never "no doubt"), both empty when the research worker has not created `filing_index` yet. Part 4: `latest_periodic` and `filing_sections` (a filing read's input). Imports no enrichment and no `src.value`. |
+| `value_view.py` | **Part 5.** The wheel's only window onto the value book: value.db read `mode=ro` with plain SQL (`read_book`: holdings with marks, approved-buy earmarks, frozen names, open funding requests; `None` when unreadable, so callers fail closed; `put_ceiling`). Imports only `src.common.config`. |
 | `value_keep_fresh.py` | The "keep fresh" list (stdlib only): `write_keep_fresh` / `read_keep_fresh` over `data/value_keep_fresh.json`, and (Part 4) `write_filing_reads` / `read_filing_reads` over `data/value_filing_reads.json`, the names to slice filings for. The value process writes the symbols of its pending/open shadow entries after each night; the research sweep (`value_names`) reads them so a held name that left the universe keeps getting bars and filings. The only channel between the two: no `src.value` import, no `value.db`, no `research.db` write. |
 | `value_universe.py` | The value book's trading universe (`would_own` + `watchlist` + the S&P 100 snapshot) and evidence universe (the S&P 500 snapshot), share-class aliases mapped to one ticker. |
 
@@ -1275,6 +1276,27 @@ Inputs come from `src/common/value_inputs.py` (read-only) in the plain shapes of
 `src/common/value_types.py`; the universes from `src/common/value_universe.py`. The research
 worker owns every SEC and price fetch for it.
 
+**Money, in paper (Part 5; spec §9 as amended by revision 4, §21).** The book holds no cash back:
+its caps are ceilings (`value.book`), and a valid buy short of cash asks the wheel to release
+capital.
+
+| File | What it does |
+|---|---|
+| `risk.py` | The value gate (spec §9.4), pure: every refusal reason; `FUNDABLE` = the gross cap, the only one released capital can cure. |
+| `sizing.py` | Pure: the tier by the effective margin of safety, the ceiling (halved by the trend brake), thirds, the tranche rules, the trend brake, month-end closes. |
+| `book.py` | value.db's money rows: `totals` (V), `reconcile` (broker = W + V filled; pending, then frozen), `clear_attribution`, `apply_split`, `propose`, `decide` (a tap), `expire`, `open_position` (the live policy's plan at entry), `step_held` (the plan each night; a sale it signals, Python's or Claude's), `sell_shares`. |
+| `executor.py` | The stock-order path on clientId 31: the `value_orders` row and its `orderRef` written before `placeOrder`, a `LimitOrder` at the mid of a fresh quote, wait, cancel, record; `IbkrValueBroker` over ib_async. |
+| `live.py` | `plan_night` (sells from the plans and Claude's BROKEN/NO, buys sized and gated on the close), `cycle` (reconcile, sells under the sell cap, buys re-gated on a fresh quote, funding requests), `hourly_check` and `mirror_reevaluations` (held re-evaluations, adds paused, Claude's review queued), `buy_context`. |
+| `stage3.py` | The IBKR side of one RTH cycle (connect as clientId 31, the broker snapshot, W from the ledger, the cycle, the hourly check, disconnect). |
+| `notify.py` | Plain Telegram messages to `TELEGRAM_THREAD_VALUE`. |
+
+Tables (Part 5): `value_orders`, `value_positions`, `value_proposals`, `value_funding_requests`,
+`value_attribution`, `value_book_state`, and `value_reevaluations.position_id`. The night
+(`service.run_nightly`, with `BookHooks` from the entrypoint) mirrors re-evaluations, sets the trend
+brake and runs `plan_night`; the entrypoint runs `stage3.run_cycle` every `book.cycle_minutes` in
+RTH. `python -m scripts.value_book` lists the book and is the tap (`--approve`, `--reject`,
+`--clear`, `--split`, `--reset-drawdown`).
+
 **Claude's reads (Part 4)** run in the same process after the night, with `value.claude.enabled`:
 `scripts/run_value.py` (the only importer of `src/value_ai/`) passes `claude_reads.run_queue` a
 reader that calls the analyst, and the operator queues a read with `python -m scripts.value_claude
diff --git a/CLAUDE.md b/CLAUDE.md
index 5513324..ecefc97 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -439,7 +439,26 @@ the value book. It is **deterministic tier**:
   through `src/common/value_inputs.py`.
 - Parts 1–4 place, size and gate nothing: every shadow row is hypothetical. Claude's verdict (the
   second written exception under the core invariant) decides the effective verdict, the `claude`
-  shadow track and `value_effective`; Part 5 is the first part where it can reach an order.
+  shadow track and `value_effective`.
+- **Part 5 (Stage 3, paper only) trades.** Its gate is `src/value/risk.py::validate` (pure,
+  deterministic, no model call, run at decision time and again at send time on a fresh quote); its
+  orders go only through `src/value/executor.py` on clientId 31 (`LimitOrder` at mid,
+  `qualifyContractsAsync`, `req_fresh_mkt_data`, `orderRef = "value:<id>"` written before
+  `placeOrder`); `src/value/stage3.py` imports ib_async and `src.ibkr` inside its functions only, so
+  importing `src.value` loads neither; the book idles when `LIVE_TRADING=true`. A sale only Claude's
+  number would make always waits for a tap.
+- **The wheel learns of the value book only through `src/common/value_view.py`** (value.db opened
+  `mode=ro` with plain SQL; imports only `src.common.config`) and `src/common/books.py`
+  (`attribute`, `value_sell_cap`, `value_exposure`); its own share count W comes from the ledger
+  (`src/storage/wheel_shares.py`), never broker minus value. Nothing on the trading path imports
+  `src.value`. While `value.book.enabled` is false every one of these is inert and the wheel is
+  unchanged.
+- **Capital release (revision 4, 2026-10-30)**: the value book holds no cash back; an approved buy
+  short of cash opens a funding request, and the trading process (`src/execution/
+  capital_release.py`, every intraday cycle) closes the fewest wheel cash-secured puts at breakeven
+  or better, each gated by `risk_engine.validate_release` twice and sent through
+  `position_manager.close_short_position` (`CloseReason.CAPITAL_RELEASE`). Deterministic; no LLM
+  output selects, sizes, prices or gates a release; it inherits its buy's approval.
 
 Enforced by `tests/test_value_fence.py` — keep it green.
 
diff --git a/SETUP.md b/SETUP.md
index 9b18062..8a124a2 100644
--- a/SETUP.md
+++ b/SETUP.md
@@ -2101,6 +2101,23 @@ adds **re-evaluations** (spec §7.1) and **Stage 1b**, the point-in-time backtes
    apply again. `python -m scripts.value_report` prints Claude's track beside the baseline's. In
    Claude Code, `/value SYMBOL` runs the interactive skill (`.claude/skills/value/`), which reads
    `python -m scripts.value_report --symbol SYMBOL --json`.
+10. **Money, in paper (Part 5).** Off until you set `book.enabled: true` in `config/value.yaml`
+    (paper only: the book idles with `LIVE_TRADING=true`). Before that: refresh
+    `config/settings.yaml` (`ibkr.client_ids.value: 31`) and `config/risk_limits.yaml`
+    (`portfolio.max_gross_notional_pct`, `max_combined_name_pct`, `value_maintenance_pct`) from
+    their examples; set `TELEGRAM_THREAD_VALUE` in `.env` (optional); import the account's trade
+    history into the ledger (Flex or an Activity CSV) so the wheel's own share count is complete;
+    and run the seven scripted fault drills of the Part 5 plan. Then the night proposes buys for
+    READY names with a tranche due (auto when the autonomy ladder allows, else a tap) and sells from
+    each held position's `value` plan (Python's exits auto with `automation.auto_close_enabled`;
+    anything only Claude's number would sell always waits for a tap), and every 15 minutes in RTH
+    the book reconciles its shares with the wheel's, sends approved orders on clientId 31 and, when a
+    buy is short of cash, asks the wheel to **release capital**: the trading process closes the
+    fewest of the wheel's cash-secured puts at breakeven or better (25% of max profit first), each
+    gated twice by the Rules Engine; the buy goes once the cash is there.
+    `python -m scripts.value_book` shows holdings, proposals, funding requests and freezes;
+    `--approve N` / `--reject N` are the taps; `--clear SYMBOL` clears a frozen share attribution;
+    `--split SYMBOL 2:1` restates the book after a split.
 
 ### Scripts
 
@@ -2111,6 +2128,7 @@ adds **re-evaluations** (spec §7.1) and **Stage 1b**, the point-in-time backtes
 | `python -m scripts.value_universe_snapshot` | Rebuilds the two committed universe CSVs from Wikipedia. |
 | `python -m scripts.run_value` | The value process. Normally started by `scripts.start` / `./ibkr restart`; `--no-value` skips it. Logs to `logs/value.log` (`./ibkr logs value`). |
 | `python -m scripts.value_report [--track baseline\|claude] [--universe all\|trading\|evidence] [--ruleset V] [--postmortems]` | Prints the shadow record from `data/value.db` (read only), with Claude's track beside the baseline's (Part 4). `--symbol NVDA --json` prints one ticker file. |
+| `python -m scripts.value_book [--approve N] [--reject N] [--clear SYMBOL] [--split SYMBOL N:M] [--reset-drawdown]` | The value book's money (Part 5): holdings, proposals, funding requests, freezes; the taps. |
 | `python -m scripts.value_claude [--read SYMBOL] [--reset-breaker]` | Claude's side of the value book (Part 4): the breaker, today's read budget and the queue; queues a read; resets the breaker. |
 | `python -m scripts.value_backtest [--universe evidence\|trading] [--names A,B] [--limit N] [--start D] [--end D] [--bars provider\|research] [--refresh] [--out F]` | Stage 1b: the point-in-time backtest of Python's rules (Part 3). |
 
diff --git a/STATUS.md b/STATUS.md
index 2f26fcc..3855fd6 100644
--- a/STATUS.md
+++ b/STATUS.md
@@ -347,6 +347,28 @@ MCP so the headless `claude -p` subprocess can do ad-hoc lookups (`ib_portfolio`
 
 ---
 
+## Built (2026-10-30 — value book Part 5: money in paper, capital release)
+
+Plan: `docs/superpowers/plans/2026-10-29-value-book-5-money-paper.md`. Paper only; off until
+`value.book.enabled`.
+
+- Spec revision 4 (§21): no reserved pot; the book's caps are ceilings; a valid buy short of cash
+  releases capital by closing wheel CSPs at breakeven or better (the Rules Engine's
+  `validate_release`, twice; `capital.select_releases`; `src/execution/capital_release.py`).
+- The value gate (`risk.py`), sizing and tranches (`sizing.py`), the book's rows (`book.py`), the
+  executor on clientId 31 with `orderRef`, the night's proposals and the RTH cycle (`live.py`,
+  `stage3.py`), plain notifications, `scripts/value_book.py`.
+- Share attribution: `orderRef` through the live, Flex and ledger paths (`book="value"`), the
+  wheel's own count W from the ledger (splits applied), the wheel's view `min(W, broker − V)`,
+  fail-closed reads, the reconcile with a grace and a freeze, the sell cap, the seven fault drills
+  as unit tests. The Rules Engine counts the value book (excess-liquidity claim, gross and combined
+  caps, freezes); `promote` refuses `above_value_ceiling` for a value put.
+- Known limitations: taps are a CLI until Part 6's buttons; the 25% "trim to half" drawdown
+  proposal is Part 6's; a held name with no open shadow entry gets only the hourly check of
+  triggers 1 and 4; W needs the ledger's whole history (import it before the first buy); a split
+  freezes the name until `value_book --split` and `--clear`; not live: a separate live plan is
+  needed.
+
 ## Built (2026-10-30 — value book Part 4: Claude as the analyst)
 
 Plan: `docs/superpowers/plans/2026-10-29-value-book-4-claude-analyst.md`. Record-only: no order,
diff --git a/docs/superpowers/specs/2026-10-28-value-swing-book-design.md b/docs/superpowers/specs/2026-10-28-value-swing-book-design.md
index d6b2d0f..b1a0d79 100644
--- a/docs/superpowers/specs/2026-10-28-value-swing-book-design.md
+++ b/docs/superpowers/specs/2026-10-28-value-swing-book-design.md
@@ -24,6 +24,10 @@ once** (§9.2); the live exit policy defaults to `value` (§7); puts and shares
 - **The go-live section now says what it can and cannot prove,** and the point-in-time backtest
   (Stage 1b) is mandatory.
 - **A calibration dry run is the first build step.**
+**Revision 4 (2026-10-30, operator decision, §21):** the 70/30 pot is dropped. The wheel sells
+cash-secured puts against the whole account; the value book holds no cash back, its caps become
+ceilings, and a valid value buy that cannot be funded **releases capital** by closing wheel CSPs at
+breakeven or better through the Rules Engine. §9.3 is amended in place; §21 records it.
 Builds on: `src/research/` (SEC fundamentals + the 40-check engine), `src/news/dossier.py` ("what
 Claude knows"), `src/regime/` (market regime), `src/spreads/` (the pattern for a second book in the
 same account), `src/strategies/buy_candidates.py` (the covered-call-suitability list this does not
@@ -879,6 +883,13 @@ these rules ship with Stage 3 and are proven by the fault drills below.*
   built (§14).
 
 ### 9.3 The pot — "dedicated" has to mean something
+> **Amended by revision 4 (2026-10-30, §21):** there is no pot and no reservation. The wheel keeps
+> selling CSPs against 100% of the account; the value book's 30% is a **ceiling** on what it may hold
+> at cost, the name cap, the 20 positions and the per-list share cap are ceilings within it, and a
+> valid buy short of cash asks the wheel to **release capital**. `value_liquidity_claim` keeps its
+> arithmetic (value stock at (1 − m)) and adds approved-but-unfilled buys instead of a ready buffer.
+> The text below is the superseded design, kept for the record; §21 is the one that is built.
+
 **Size (operator, 2026-10-29): 70% wheel, 30% value.** `config/value.yaml → sleeve.pct_of_net_liq:
 30` — the pot's capital at cost (unspent cash + cost of open value lots) is capped at 30% of net
 liquidation. My calls, to make 30% cheap to carry:
@@ -1074,7 +1085,8 @@ what "buy near the 52-week low" fights **[Opus]**. Hence §6.6 and §7.
 ## 14. Open decisions — the operator's
 
 1. ~~The pot?~~ **Answered (2026-10-29): 70% wheel / 30% value**, with a ready-buffer reservation, one
-   pot shared by both lists and each list capped at 70% of it (§9.3).
+   pot shared by both lists and each list capped at 70% of it (§9.3). **Superseded (2026-10-30) by revision 4
+   (§21):** no pot, no reservation; the 30% is a ceiling and a short buy releases capital.
 2. ~~May a wheel name be held as shares by the value book?~~ **Answered (revision 2): yes, shared**
    (§9.2).
 3. ~~Claude's adjustments in live?~~ **Answered (revision 2):** Claude decides on healthy names; in live
@@ -1261,3 +1273,54 @@ written. The author verified the code-level claims, all of which held:
 | GOOGL/META only after a ~50% fall? | Loosen the growth valuation now: r = 8%, half of SBC. Rough effect: GOOGL ~$101 → ~$151 Python, ~$227 with the clamp — still a ~30% fall from ~$300; the dry run prints the real numbers | §6.5, §17 |
 | When does ticker sharing switch on? | From the start of share-buying; the fault drills are build acceptance | §9.2 |
 | Whose shares are an assigned value-suggested put? | The wheel's, for v1 | §9.1 |
+
+## 21. Revision 4 — 2026-10-30: no reserved pot; capital release
+
+**The operator's decision (2026-10-30), superseding §14 question 1's 70/30 split and §9.3's ready
+buffer:** "the wheel keeps selling cash-secured puts against 100% of the account; the value book holds
+no cash in reserve. When there is a valid value-investing opportunity and the cash is not available,
+close certain wheel trades that are either at breakeven or 25% in profit, to release capital for the
+value trade." Built in Part 5 (`docs/superpowers/plans/2026-10-29-value-book-5-money-paper.md`);
+its rulings set the details below and the operator may overturn any of them.
+
+**§9.3 as amended.**
+1. **Ceilings, not reservations.** `value.book.ceiling_pct_of_net_liq` (30) caps the book's cost; the
+   name cap (8% of that ceiling), `max_positions` (20) and the per-list share cap (70% of it) are
+   ceilings within it. Nothing is held back from the wheel.
+2. **The wheel's caps count what the value book actually holds.** `resolve_caps` subtracts
+   `books.value_exposure().claim = Σ value market value × (1 − m) + approved value buys not yet
+   filled` from excess liquidity before the reserve (m = `portfolio.value_maintenance_pct`, 25%); the
+   wheel's concentration tallies add the value book's stock per name; a CSP is refused when stock of
+   both books + CSP collateral + approved value buys would pass `portfolio.max_gross_notional_pct`
+   (100%) of net liquidation, and, on a name the value book holds, when one name across both books
+   would pass `portfolio.max_combined_name_pct` (15%). All of it applies only while
+   `value.book.enabled`.
+3. **Cash-only value buys.** A buy must fit inside the same gross cap; it never borrows.
+4. **Capital release.** A buy that passes every value gate except the gross cap (a READY name, every
+   gate passing, a tranche due, approved by the autonomy ladder or a tap) opens a funding request in
+   `value.db` for the shortfall. The trading process (each intraday cycle, `src/execution/
+   capital_release.py`) reads open requests through the read-only `value_view` and closes **the fewest
+   wheel cash-secured puts that free enough collateral**: only puts (a covered call frees no cash);
+   only at breakeven or better (`release.min_profit_pct` 0, never a loss), those at 25% of max profit
+   or more first (`preferred_profit_pct`); then the least premium given up, the most capital per
+   dollar given up; never a partial release (if no allowed set covers the need, nothing is closed); at
+   most 3 closes a request, 4 a day and 10% of net liquidation a day. Each close is gated by the Rules
+   Engine (`risk_engine.validate_release`) at decision time and again at send time on a fresh quote,
+   and sent through the wheel's own close path (`position_manager.close_short_position`: a
+   `LimitOrder` at mid, `qualifyContracts`, `req_fresh_mkt_data` quotes, cancel on timeout),
+   stamped `CloseReason.CAPITAL_RELEASE`. Deterministic Python; no LLM output selects, sizes, prices
+   or gates a release.
+5. **Close first, confirm, then buy.** The value process never buys on a promise: each RTH cycle it
+   re-reads its own fresh account and re-gates the buy; only when the room is there does the buy send.
+   An approved buy's cost is earmarked against the wheel's gross cap while its request is open, so the
+   wheel cannot re-sell into the freed collateral. A request lapses after `request_ttl_hours` (30) or
+   when its buy is refused or expires, and then nothing else happens; a name whose request lapsed asks
+   again only after `cooldown_days` (3).
+6. **Approval.** A release inherits its buy's approval: an auto buy (the autonomy ladder allows it)
+   releases automatically; a buy that waits for a tap opens no request until it is tapped. Halted: no
+   request is serviced.
+7. **Failure mode 1 (§13) under revision 4.** The guard is the gross cap across both books, the value
+   claim on excess liquidity and the earmark, not a reservation; the go-live line "the pot cannot be
+   funded without lowering the wheel's reserve" (§12) reads "a value buy needed a release that lowered
+   the wheel's reserve below its configured floor".
+
```

- [ ] **Step 2: Check them against the code** — every module named exists:
  `ls src/value/risk.py src/value/sizing.py src/value/book.py src/value/executor.py src/value/live.py src/value/stage3.py src/value/notify.py src/common/value_view.py src/storage/wheel_shares.py src/execution/capital_release.py scripts/value_book.py`
  prints eleven paths; `grep -c "^## 21. Revision 4" docs/superpowers/specs/2026-10-28-value-swing-book-design.md` prints 1.
- [ ] **Step 3: Commit:**

  ```bash
  git add docs/superpowers/specs/2026-10-28-value-swing-book-design.md CLAUDE.md ARCHITECTURE.md SETUP.md STATUS.md
  git commit -m "docs: value book Part 5 - money in paper; spec revision 4 (capital release)"
  ```

- [ ] **Section E exit** — the full gate (baseline + 77), protected-file diff, `py_compile` of the five
  scripts, clean status; fill the row; `git commit -m "docs(plan): value book Part 5 Progress log - Section E"`.

---

## Whole-branch review · model: opus · effort: high, then one sonnet fix pass · effort: high

- [ ] **R1.** Spawn one **opus** subagent with `effort: "high"`: "Review branch `feat/value-book-5`
  against `main` for correctness (superpowers:requesting-code-review). Read the plan's Rulings
  (especially the Rules-Engine table and the capital-release rulings 1–7), Global Constraints and
  Review Focus; the spec §§7, 7.1, 9 (all), 11, 13, 16, 21; root `CLAUDE.md`; and
  `git diff main...HEAD`. Check: with `value.book.enabled` false the wheel is byte-for-byte unchanged
  in behaviour (every value branch is gated); the core invariant (no LLM output reaches the value
  gate except the effective verdict and fair value; no Claude-caused sale sends without a tap; a
  release is deterministic and gated twice); close first, confirm, then buy (no order before the
  fresh snapshot shows room; a request that lapses leaves nothing behind; the earmark stops the
  wheel re-selling); the release selection (fewest, never partial, never a loss, never a call) and
  its daily caps; `orderRef` written before `placeOrder` and carried through live, Flex and ingest;
  W from the ledger (splits, superseded rows, the value and spreads books excluded) and its average
  cost on a shared name; the wheel's view (errs short, fails closed); the reconcile's grace and
  freeze and what may still send on a frozen name; the sell cap; the seven drills; paper only (the
  gate and the entrypoint); clientId 31 used only by the value process; `req_fresh_mkt_data` and
  `LimitOrder` only; the fences (nothing on the trading path imports `src.value`; `value_view`
  read-only; the value process loads ib_async only inside `stage3`); the docs and spec §21 against
  the code. Report Critical / Important / Minor with file:line. Do not edit."
- [ ] **R2.** Record the findings; spawn one **sonnet** subagent (`effort: "high"`) to fix every
  Critical and Important in **one** commit (`fix(value): whole-branch review fixes`), TDD, full gate
  green. A change to a Rules-Engine line (E1–E8) is shown to the operator before it is committed.
- [ ] **R3.** Verify the fix commit yourself, then **ask the operator whether to merge and push. Do
  neither without a yes.**

---

## Operator to-dos

**Before Part 5 starts:** Part 4 merged and restarted; a few nights of Claude's reads (or none, if
you keep `value.claude.enabled` off: the book then runs on Python's baseline); the Rules-Engine
edits approved and ruling 7's question answered (Section B's entry); at least 8 GiB free.

**After the merge, before the restart:**

1. Refresh `config/value.yaml`, `config/settings.yaml` (`ibkr.client_ids.value: 31`) and
   `config/risk_limits.yaml` (the three `portfolio` keys) from their examples; the book stays
   `enabled: false`. Optionally set `TELEGRAM_THREAD_VALUE` in `.env`.
2. `./ibkr restart` (daemons do not hot-reload). With the book off the wheel is unchanged.

**Before turning the book on (`book.enabled: true`), in paper:**

3. Import the account's whole trade history into the ledger (`python -m scripts.ledger_import`, or the
   web's CSV upload; and the nightly Flex pull) so W is complete; run `python -m scripts.value_book`
   and check no name shows a frozen or pending attribution.
4. Run the seven scripted paper drills (spec §9.2), each with the book on and one small paper lot,
   reading `python -m scripts.value_book` after each:
   1. *Assignment on a shared ticker*: hold a value lot in a name, let a wheel put on it be assigned
      (or simulate with a paper put at a deep ITM strike); the attribution stays `ok` once the
      ledger has the assignment, and the wheel's covered-call scan sees only its own 100 shares.
   2. *A partial value fill*: a limit buy that fills in part (a thin name, a tight limit): V counts
      the fill; the rest is cancelled; nothing else moves.
   3. *A restart mid-order*: `./ibkr restart` while a value buy is working: the order row exists
      before the restart, the fill is tagged `value` in the ledger, V is right after the restart.
   4. *A split*: a name in the book that splits (or a test name with a reverse split): the
      attribution goes `pending` then `frozen`; `value_book --split SYMBOL N:M`, then `--clear`.
   5. *A manual TWS trade*: buy shares of a book name by hand in TWS: they are wheel stock once the
      ledger has them; until then the wheel sees fewer shares, never more.
   6. *A Flex-only fill*: a value fill the live feed missed arrives by Flex with its `orderReference`:
      it is tagged `value`, W is unchanged.
   7. *value.db unreadable*: `chmod 000 data/value.db` for one wheel scan: no covered call on a name
      where the broker disagrees with W, no new CSP (`value_book_unreadable`); restore the mode.
5. Then set `book.enabled: true` and restart. Watch the first night's `book` summary in
   `logs/value.log`, the RTH cycle's messages, and `python -m scripts.value_book`. Taps:
   `--approve N` / `--reject N`.

**Questions only the operator can answer** (defaults in force until answered):

- Ruling 7: does a capital release inherit its buy's approval (default), or does every release
  wait for its own tap?
- Ruling 9: `max_combined_name_pct` 15% of net liq (the spec left it open)?
- Ruling 2: should the release thresholds differ (breakeven floor 0%, preferred 25%, at most 3
  closes a request, 4 a day, 10% of net liq a day)?
- Ruling 15: is "trim to half" at a 25% book drawdown wanted as an automatic proposal (Part 6) or
  only a card?

---

## Self-review (run by the plan's author, 2026-10-30)

- **Spec coverage.** §9.1 put ceiling → Task 6 (and `value_view.put_ceiling`, Task 2). §9.2 →
  Tasks 3, 10, 11, 12 (attribution, `orderRef`, the wheel's view, drills), Task 8 (the reconcile,
  the sell cap, the freeze). §9.3 as amended (§21) → Tasks 1, 4, 5, 8. §9.4 → Task 7 (+ the
  send-time re-gate, Task 8). §9.5 → Tasks 7, 8. §9.6 → Tasks 7, 8, 13 (trend brake, drawdown stop;
  the trim proposal moved to Part 6). §9.7 → Tasks 8, 9, 14. §7 exits as orders, Claude-caused sales
  a tap → Task 8. §7.1 held steps → Tasks 8, 13. §11 → Tasks 2, 8, 10. §13 failure modes 1 and 4 →
  Tasks 4, 5, 8, 11, 12. §18 docs → Task 15. The operator's 2026-10-30 decision → rulings 1–9,
  Tasks 4, 5, 8, 15.
- **Placeholders.** None. Every block is real code that passed: Part 4's prototype (5382) + Part 5 =
  **5459 passed, 1 skipped**, `ruff check .` clean, `mypy src` clean (348 files), on a code-only
  scratch copy of `main` with Part 4's plan applied first; each of the fifteen tasks was replayed as
  its own commit and its targeted tests run green.
- **Type consistency.** `ValueBookCfg` (T1) is what `sizing`, `risk`, `live` and the release gate
  read; `value_view.ValueBook`/`ValueHolding` (T2) are what `books.attribute`/`value_exposure` (T3),
  the engine (T4), the runner (T5) and `wheel_view` (T11) read; `ReleaseCandidate` (T4) is what the
  runner builds (T5); `BuyContext` (T7) is what `live.buy_context` (T8) builds; `live.Snapshot` (T8)
  is what `stage3.build_snapshot` (T9) returns; `BookHooks` (T13) is what `run_value` (T14) builds.
- **Written against Part 4's plan** — the A1 reconciliation is the guard; every "(Part 4)" grep is
  re-run against the merged tree.
