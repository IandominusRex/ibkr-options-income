# Milestone 0 — Baseline and pre-existing defects

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [x]`) syntax.

**Goal:** Fix the things P3 and P4 would otherwise be built on top of, and start the phase from a
tree whose state is known.

**Spec:** `Web plan/P3-P4-design.md`. **Index:** `Web plan/P3-P4-IMPLEMENTATION-PLAN.md`.
**Depends on:** nothing. **Blocks:** everything.

> **EXECUTED — all ten tasks (0.1–0.10), committed to `main` 2026-09-09, ten commits:** `3ef1026`
> (Task 0.1 baseline decision), `919af6b` (0.2 idempotent EOD), `5f43f89` (0.3 one assignment-risk
> predicate), `4e5ea77` (0.4 campaign gross/net pin), `6d9cd96` (0.5 openapi freshness test),
> `79ee64c` (0.6 refresh runbook fix), `bd8c9ac` (0.7 P2 deferred-findings cleanup), `965a7b7` +
> `67ecd3d` (0.8 proxy fails soft, plus a mid-response follow-up fix), `55b5ec1` (0.9 one `as_utc`),
> `faa135f` + `e57e8c0` (0.10 fence consolidation, plus a second duplicate-pair/glob hole found in
> `eval_skills` while doing it), `6f15e36` (final-review doc fixes: `STATUS.md`, a stale threshold
> docstring, an M2 plan note, the shorts API doc).
>
> **This file's own checkboxes were left unticked when the work landed** — the tasks were executed
> individually across that session rather than closed out as a milestone, and M6 Task 6.4 later
> found the gap and deliberately left it alone (M6's own doc step named "all six milestone files",
> M1–M6, and M0 predates that count — see `P3-P4-IMPLEMENTATION-PLAN.md`'s "Every ruling made along
> the way" item 6). **Closed out here, 2026-09-11**, by verifying each task's deliverable against
> the tree rather than re-asserting the commit log: `src/common/assignment_risk.py`,
> `tests/test_eod_idempotency.py`, `tests/test_assignment_risk.py`,
> `tests/test_campaign_rollup_semantics.py` and `tests/test_openapi_current.py` all exist and pass;
> `src/api/routers/options.py` imports `is_assignment_risk`/`assignment_risk_thresholds` rather than
> hardcoding a threshold; no `def _as_utc` remains anywhere under `src/api/`;
> `tests/test_web_fence.py` has one copy of the checks-engine test and every directory walk in the
> file uses `rglob`; the BFF proxy returns JSON `502`/`504` and the missing-`API_TOKEN` `500` is
> unchanged (`web/app/api/[...path]/route.ts`); `docs/web/commands.md`'s `refresh` section describes
> the real handler; `src/storage/universe_overrides.py` carries no dead logger; `CampaignRow` and
> `_rollup` both document `net_premium` as gross of commissions. Final gate, re-run 2026-09-11:
> `python -m pytest -q` — **2187 passed**; `ruff check .` — clean; `mypy src` — clean (163 source
> files); `cd web && npx vitest run` — **347 passed (43 files)**; `npm run lint` — clean; `npm run
> build` — clean, all routes compile. Identical to M6's own recorded final-gate numbers, confirming
> nothing has drifted since.

**Why this milestone exists.** Writing the P3/P4 design meant reading the code the design sits on,
then auditing what P0, P1 and P2 actually shipped. That turned up nine defects that predate this
phase. None of them is P3/P4 work. All of them are load-bearing for it:

| # | Finding | Task | What it breaks in P3/P4 |
|---|---|---|---|
| 1 | A repeated EOD run raises before the reconciler and the position snapshot run | 0.2 | P4's realised-P&L cross-check and M1's `eod` fallback rung both depend on those two steps |
| 2 | Assignment risk is defined twice, disagreeing by 14 days of DTE | 0.3 | M2 adds three more consumers of the signal |
| 3 | `campaigns.net_premium` is gross of commissions; the reporting layer nets them | 0.4 | M4's campaign-versus-leg cross-check fails by construction |
| 4 | `docs/web/openapi.json` is stale, for the third time | 0.5 | M2, M5 and M6 each end with a regeneration step that is currently unverifiable |
| 5 | `docs/web/commands.md` documents a `refresh` handler that does not exist | 0.6 | M1 registers the real one against a runbook entry that is already wrong |
| 6 | Four deferred findings from P2's close-out, still open | 0.7 | Small, but they are in files this phase edits |
| 7 | The BFF proxy throws when the API is down, so the browser gets an HTML 500 | 0.8 | M3 and M5 poll continuously; every API restart surfaces an HTML blob as an error message |
| 8 | `_as_utc` is implemented twice, with different signatures | 0.9 | Every P3/P4 router needs the same coercion, and a third copy is the obvious next step |
| 9 | `tests/test_web_fence.py` holds a duplicated test and globs non-recursively | 0.10 | M4 and M6 both extend this file, and `CLAUDE.md` calls it load-bearing |

**A note on what the audit did *not* find.** The bare-insert defect behind finding 1 is **not** a
pattern: every other unique-constrained table is written through a check-then-insert helper in
`src/storage/` (`positions.py`, `iv_history.py`, `system_settings.py` all guard correctly). The
journal is the one write done inline in the orchestrator instead of through a storage module, and
that is exactly why it is the one that is wrong. Do not go looking for siblings; there are none.

Two things were found and deliberately **not** fixed here, because M0 is for correctness and they
are neither incorrect nor blocking:

- `src/api/routers/research.py:205` loads every `QuoteRow` with `select(QuoteRow)` and no filter to
  build a lookup used for ~46 universe symbols, then issues one IV query per symbol. Inefficient,
  bounded in practice, not wrong.
- `web/lib/api.ts` has no trailing newline. It is already being edited in the in-flight work Task
  0.1 reports on; leave it to that change.

**The shape of this milestone in one sentence:** none of this is new capability, so if a task here
grows a feature, it has escaped its scope.

**Measured baseline, 2026-09-09**, before any task in this milestone:

```
python -m pytest -q          1944 passed
ruff check .                 All checks passed
mypy src                     Success: no issues found in 153 source files
cd web && npx vitest run     209 passed (29 files)
```

Every task below must leave those green, and the Python count must only ever go **up**.

**Baseline as executed, 2026-09-09.** At execution time `git status` was already clean on `main`
(commit `b72d9e4`, "feat: IBKR market data fallback chain + research ingest fixes"). Diffing that
commit's file list against Task 0.1's "17 modified files and 2 untracked paths" table shows an
exact match — every file named there (`ARCHITECTURE.md`, `How the scan works.md`, `README.md`,
`SETUP.md`, `STATUS.md`, `docs/web/architecture.md`, `src/common/config.py`,
`src/ibkr/market_data.py`, `src/notify/approval_service.py`, `src/research/ingest/jobs.py`,
`src/research/ingest/quotes.py`, `tests/test_ingest_quotes.py`, `tests/test_market_data.py`,
`tests/test_notify.py`, `web/app/api/[...path]/route.ts`, `web/app/api/[...path]/route.test.ts`,
`web/lib/api.ts`, `web/lib/api.test.ts`, `web/data/`) is present in that commit. The operator chose
**option 1** (commit the in-flight work themselves first) before this milestone began executing.
Re-measuring the six gate commands against that commit gives:

```
python -m pytest -q          1944 passed
ruff check .                 All checks passed
mypy src                     Success: no issues found in 153 source files
cd web && npx vitest run     209 passed (29 files)
cd web && npm run lint       No ESLint warnings or errors
cd web && npm run build      Compiled successfully, 7 routes generated
```

Identical to the pre-execution numbers above. This milestone proceeds from that baseline; every
later task's gate re-run compares against these six results.

---

## Task 0.1 — Establish a known baseline `[SONNET]`

**This task has a human checkpoint in it and cannot be completed by an agent alone.**

**Context.** `git status` at the time this plan was written showed **17 modified files and 2
untracked paths** of work unrelated to this phase:

```
 M ARCHITECTURE.md              M src/ibkr/market_data.py
 M How the scan works.md        M src/notify/approval_service.py
 M README.md                    M src/research/ingest/jobs.py
 M SETUP.md                     M src/research/ingest/quotes.py
 M STATUS.md                    M tests/test_ingest_quotes.py
 M docs/web/architecture.md     M tests/test_market_data.py
 M src/common/config.py         M tests/test_notify.py
 M web/app/api/[...path]/route.ts   M web/lib/api.ts
 M web/app/api/[...path]/route.test.ts
?? web/data/                   ?? web/lib/api.test.ts
```

**This is not junk, and it must not be discarded.** Reading the diff shows it is an active bug-fix
stream. `web/app/api/[...path]/route.ts` gains two real fixes: the proxy was **dropping the query
string entirely** (`target` was built from the path alone, so every filtered request — a research
search, an assessed-stage filter — reached the API with its parameters stripped), and a `204`,
`304` or empty body was being passed to a `Response` constructor that throws on it, turning a
successful live-mode confirm into a 500. `web/lib/api.ts` gains the matching `204` handling.

Three of the modified files are ones this plan also modifies: **`src/common/config.py`** (M1 Task
1.2 adds two config keys), **`web/app/api/[...path]/route.ts`** (Task 0.8 below adds fail-soft
error handling, and M5 Task 5.3 adds the response-header allowlist), and
**`web/app/api/[...path]/route.test.ts`** alongside it. Starting a 45-task build on top means the
first `git add` sweeps in work nobody in this phase wrote, and a later bisect cannot tell the two
apart.

The suite is green with that work in place, so nothing is broken — it is simply unattributed, and
it overlaps.

**Files:** none. This is a checkpoint.

- [x] **Step 1: Re-measure.** The numbers above were taken on 2026-09-09 and the tree has moved
  since if anyone has worked in it. Run all six and record what you actually get:

```bash
python -m pytest -q
ruff check .
mypy src
cd web && npx vitest run && npm run lint && npm run build
```

- [x] **Step 2: Report the tree state to the operator and stop.** List what is modified and
  untracked, and say plainly that the web-proxy changes look like a deliberate bug fix (the query
  string and the `204` handling), not stray edits. **Do not commit it, do not stash it, and do not
  revert it** — it is somebody's in-flight work and an agent cannot know its intent. Ask which of
  these they want:

  1. Commit the in-flight work themselves first, so this phase starts from a clean tree.
     **Recommended**, because Task 0.8 and M5 Task 5.3 both edit the same proxy function.
  2. Explicitly accept that P3/P4 commits may carry it, and say so.
  3. Stash it themselves.

  If they choose 2 or 3, say out loud that Task 0.8 will then either conflict with or silently
  revert the query-string fix, and that whoever runs 0.8 must re-read the file rather than working
  from this plan's quoted version of it.

- [x] **Step 3: Only after the operator answers**, record the decision and the six gate numbers at
  the top of this file under a "Baseline as executed" heading, with the date. Every later
  milestone compares against these numbers, so a milestone that reports "the suite still passes"
  has something concrete to have passed against.

- [x] **Step 4:** No commit. This task produces a recorded decision, not a change.

---

## Task 0.2 — Make the EOD run idempotent `[SONNET]`

**Trading-system code, and the most consequential fix in this milestone.**

**Context.** `src/orchestrator/eod_report.py::_write_journal` (line 264) does a bare
`session.add(JournalRow(...))`. `JournalRow` carries `UniqueConstraint("entry_date")`
(`src/storage/models.py:385`). `session_scope` rolls back and **re-raises** (`src/storage/db.py:160`).
The call site at line 379 is unguarded.

And the steps that follow it, at line 381 onward, are:

> `# 6b. Reconcile the verdict outcome ledger ... Assignment is auto-detected by diffing the prior
> position snapshot against today's positions (Phase 4) ... Today's snapshot is then saved as
> tomorrow's baseline.`

So a second EOD run on the same ET day raises `IntegrityError` at step 6 and **the reconciler,
assignment auto-detection, and `save_position_snapshot` never run.** The day's outcomes are never
back-filled and tomorrow's assignment baseline is never written.

The asymmetry is visible in the code itself: `save_position_snapshot`'s docstring says
"Upsert the snapshot for *snapshot_date* (**idempotent if the EOD run repeats**)". The journal
write in the same run is not, and it sits upstream of the snapshot it was written to protect.

This matters directly to this phase. M1's fallback chain reads `position_snapshots` and
`journal.payload` on its `eod` rung. M4's cross-check compares `PnlLeg.net_pnl` against
`verdict_ledger.realized_pnl`, which only the reconciler fills.

**Files:** Modify `src/orchestrator/eod_report.py`, `ARCHITECTURE.md`, `SETUP.md`. Test
`tests/test_eod_idempotency.py`.

**Interfaces:**

```python
def _write_journal(summary: EODSummary, narrative: str | None, fill_ids: list[int]) -> None:
    """Upsert the journal row for summary.date (idempotent if the EOD run repeats).

    Deliberately mirrors src/storage/positions.py::save_position_snapshot, which is already
    idempotent for exactly this reason: an EOD run that repeats must not lose the steps that
    follow it (the reconciler, assignment auto-detection, tomorrow's position baseline).
    """
```

**Design points that are not negotiable:**

1. **Upsert, do not catch-and-continue.** Wrapping the call in `try/except` would stop the
   exception but leave the day's journal holding the *first* run's numbers, which are the stale
   ones. A re-run exists to produce better numbers; it should replace, not be ignored.
2. **Every field is replaced**, including `narrative` and `payload`. A partial upsert that keeps
   the old narrative beside new metrics produces a journal entry that describes a different day's
   numbers.
3. **`created_at` is left at the original value.** The row's identity is its date; when it was
   first written is real history.
4. **Do not change the ordering of steps 6 and 6b.** The fix is that step 6 stops throwing, not
   that step 6b moves. Reordering would change which failures still block the reconciler, and this
   task is not the place to decide that.

Required behaviours, each with a test:
- Running the journal write twice for the same date leaves **one** row, carrying the second run's
  values.
- **A repeated EOD run reaches the reconciler and `save_position_snapshot`.** Its own test, and the
  one that matters — assert those two are called on the second run, not just that no exception
  escaped.
- A different date creates a second row.
- `created_at` is unchanged by the second write; `payload` and `narrative` are replaced.

- [x] **Step 1: Write the failing test**

```python
"""A repeated EOD run must not silently skip reconciliation and tomorrow's baseline."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from src.storage.models import JournalRow


def test_a_repeated_journal_write_upserts_rather_than_raising(db, session, an_eod_summary) -> None:
    from src.orchestrator.eod_report import _write_journal

    summary = an_eod_summary(entry_date=date(2026, 9, 9), unrealized_pnl=100.0)
    _write_journal(summary, "first narrative", [1])

    summary_again = an_eod_summary(entry_date=date(2026, 9, 9), unrealized_pnl=250.0)
    _write_journal(summary_again, "second narrative", [1, 2])   # must not raise

    rows = session.query(JournalRow).filter_by(entry_date=date(2026, 9, 9)).all()
    assert len(rows) == 1
    assert rows[0].unrealized_pnl == 250.0
    assert rows[0].narrative == "second narrative"
    assert rows[0].payload["fills"] == [1, 2]


def test_a_repeated_eod_run_still_reconciles_and_snapshots(db, eod_env) -> None:
    """The real defect: step 6 raised, so steps 6b never ran, so the day was never reconciled."""
    with patch("src.orchestrator.eod_report.reconcile") as reconcile, \
         patch("src.orchestrator.eod_report.save_position_snapshot") as snapshot:
        await_eod_run(eod_env)      # first run
        await_eod_run(eod_env)      # second run, same ET day

    assert reconcile.call_count == 2
    assert snapshot.call_count == 2


def test_created_at_survives_an_upsert(db, session, an_eod_summary) -> None:
    from src.orchestrator.eod_report import _write_journal

    _write_journal(an_eod_summary(entry_date=date(2026, 9, 9)), "first", [])
    original = session.query(JournalRow).filter_by(entry_date=date(2026, 9, 9)).one().created_at

    _write_journal(an_eod_summary(entry_date=date(2026, 9, 9)), "second", [])
    assert session.query(JournalRow).filter_by(
        entry_date=date(2026, 9, 9)
    ).one().created_at == original


def test_a_different_date_creates_a_second_row(db, session, an_eod_summary) -> None:
    from src.orchestrator.eod_report import _write_journal

    _write_journal(an_eod_summary(entry_date=date(2026, 9, 9)), "a", [])
    _write_journal(an_eod_summary(entry_date=date(2026, 9, 10)), "b", [])
    assert session.query(JournalRow).count() == 2
```

Build `an_eod_summary` and `eod_env` as fixtures. Grep `tests/` for existing EOD fixtures first —
`tests/test_phase6.py` and whichever file already exercises `run_eod` will have most of what you
need, and a second EOD harness is how the two end up disagreeing.

- [x] **Step 2: Run the tests and confirm they fail.** The first should fail with `IntegrityError`,
  which is the defect reproducing. If it fails some other way, you have not reproduced it.

- [x] **Step 3: Implement the upsert.**

- [x] **Step 4: Run the FULL suite.** This modifies the EOD orchestrator, which the reconciler,
  assignment detection and the Telegram EOD report all run through. The count must go up by the
  number of tests you added and nothing may fail.

- [x] **Step 5: Docs.** `ARCHITECTURE.md`'s `src/orchestrator/` section notes that the EOD run is
  idempotent and why (a repeat must not lose reconciliation or tomorrow's baseline).
  `SETUP.md`'s troubleshooting table gains a row: re-running `python -m scripts.run_eod` for a day
  that already has a journal entry replaces it rather than failing.

- [x] **Step 6: Commit.**

```bash
git add src/orchestrator/eod_report.py tests/test_eod_idempotency.py ARCHITECTURE.md SETUP.md
git commit -m "fix(eod): upsert the journal row so a repeated run still reconciles"
```

---

## Task 0.3 — One assignment-risk predicate `[SONNET]`

**Trading-system code. Moved here from what was M2 Task 2.1, because it is a pre-existing
inconsistency rather than P3 work.**

**Context.** Assignment risk is defined twice today, with different thresholds:

- `src/monitor/triggers.py::check_assignment_risk` reads `assignment_alert_delta` (0.70) and
  `assignment_alert_dte` (**21**) from config, and fires the Telegram alerts the operator acts on.
- `src/api/routers/options.py:834-844` hardcodes `abs(delta) >= 0.70 and dte <= 7`, under a comment
  that reads:

  > `# assignment_risk: deep-ITM short near expiry. |delta| >= 0.70 and dte <= 7`
  > `# is the monitor's default.`

  **It is not the monitor's default.** `config/settings.yaml:271` sets `assignment_alert_dte: 21`.

So `/options/shorts` reports `assignment_risk: false` for any position between 8 and 21 days from
expiry that the monitor is actively alerting on. M2 is about to add three more consumers of this
signal, so it gets one definition first.

**Files:** Create `src/common/assignment_risk.py`. Modify `src/monitor/triggers.py`,
`src/api/routers/options.py`, `README.md`, `ARCHITECTURE.md`. Test
`tests/test_assignment_risk.py`.

**Interfaces:**

```python
# src/common/assignment_risk.py
def is_assignment_risk(
    *,
    position: float,
    delta: float | None,
    dte: int | None,
    delta_threshold: float,
    dte_threshold: int,
) -> bool:
    """True when a SHORT option is deep enough in the money, close enough to expiry.

    The single definition. src/monitor/triggers.py fires alerts on it and the API reports
    it; before this function they disagreed by 14 days of DTE.

    Missing delta or missing dte is data-unavailable and returns False — never True, and
    never a fabricated signal from an absent field.
    A non-negative `position` is not a short and returns False.
    """


def assignment_risk_thresholds(cfg: Config) -> tuple[float, int]:
    """(delta_threshold, dte_threshold) from config, so no caller hardcodes either."""
```

**Design points that are not negotiable:**

1. **`src/common/` is the home**, not `src/monitor/` and not `src/api/`. The monitor is a trading
   process the API may not import; the API is the web layer the monitor may not import.
   `src/common/` is the only place both can reach. It takes plain values, not a `PositionSnapshot`
   and not an `OptionQuote`, so neither caller has to construct the other's type.
2. **The monitor's thresholds win.** 0.70 delta and 21 DTE. The API's 7 was never a deliberate
   choice — its own comment shows it was an attempt to copy the monitor that copied the wrong
   number.
3. **The API stops hardcoding.** `src/api/routers/options.py` reads through
   `assignment_risk_thresholds`, so a future config change moves both surfaces together.
4. **`check_assignment_risk` keeps its signature and its alert construction.** It delegates the
   *decision* and keeps owning the `RollAlert` it builds. Do not move alert construction into
   `src/common/`.
5. **This changes `/options/shorts`'s output**, and that is the fix. Positions between 8 and 21 DTE
   will flip from `false` to `true`. P2's shorts tests may assert the old value; correct their
   expectations with a comment naming this task, and **never restore the old threshold to keep a
   test green**.

Required behaviours, each with a test:
- A short at delta 0.75 with 10 DTE is at risk. (The case the two surfaces disagreed on.)
- A short at delta 0.75 with 25 DTE is not.
- A short at delta 0.50 with 3 DTE is not.
- A **long** position at delta 0.75 with 3 DTE is not.
- `delta is None` is False; `dte is None` is False; neither raises.
- `check_assignment_risk` still returns a `RollAlert` with the same fields for a qualifying
  position, and `None` otherwise.
- **The API and the monitor agree**, asserted over a matrix of (delta, dte) pairs.

- [x] **Step 1: Write the failing test**

```python
"""One definition. Before this file, /options/shorts and the monitor disagreed by 14 days."""

from __future__ import annotations

import pytest

from src.common.assignment_risk import is_assignment_risk

DELTA_T, DTE_T = 0.70, 21


def _risk(position: float, delta: float | None, dte: int | None) -> bool:
    return is_assignment_risk(
        position=position, delta=delta, dte=dte,
        delta_threshold=DELTA_T, dte_threshold=DTE_T,
    )


def test_the_case_the_two_surfaces_disagreed_on() -> None:
    """delta 0.75, 10 DTE: the monitor alerted, /options/shorts said false."""
    assert _risk(-1.0, -0.75, 10) is True


def test_far_from_expiry_is_not_at_risk() -> None:
    assert _risk(-1.0, -0.75, 25) is False


def test_low_delta_near_expiry_is_not_at_risk() -> None:
    assert _risk(-1.0, -0.50, 3) is False


def test_a_long_position_is_never_at_risk() -> None:
    assert _risk(1.0, -0.75, 3) is False


@pytest.mark.parametrize("delta,dte", [(None, 3), (-0.9, None), (None, None)])
def test_missing_data_is_never_a_signal(delta, dte) -> None:
    assert _risk(-1.0, delta, dte) is False


def test_the_api_and_the_monitor_agree(client, seed_short_position) -> None:
    """The regression this task exists to prevent from recurring."""
    for delta, dte, expected in [(-0.75, 10, True), (-0.75, 25, False), (-0.50, 3, False)]:
        seed_short_position(delta=delta, dte=dte)
        body = client.get("/options/shorts", headers=AUTH).json()
        assert body["shorts"][0]["assignment_risk"] is expected
        assert expected == _risk(-1.0, delta, dte)
```

- [x] **Step 2: Run the tests and confirm they fail.**

- [x] **Step 3: Implement**, then rewire both callers. **Delete the inline expression in
  `src/api/routers/options.py` and its now-wrong comment.**

- [x] **Step 4: Run the FULL suite.** This modifies a trading process and changes an existing API
  response.

- [x] **Step 5: Docs.** `README.md` layout table and `ARCHITECTURE.md` folder guide gain
  `src/common/assignment_risk.py`. `ARCHITECTURE.md`'s `/options/shorts` description notes the flag
  now uses the monitor's configured thresholds, and that this widened what it reports.

- [x] **Step 6: Commit.**

---

## Task 0.4 — Pin the campaign rollup's commission semantics `[SONNET]`

**Trading-system code, and a semantics ruling that M4 depends on.**

**Context.** `src/storage/campaigns.py::_rollup` computes:

```python
value = float(f.avg_price or 0.0) * float(f.filled_qty or 0.0) * 100
...
row.net_premium = round(collected - paid, 2)
```

**There is no commission term.** `campaigns.net_premium` is gross.

Meanwhile `src/claude/eval/reconcile.py::_classify` — which M4 Task 4.1 moves into
`src/reporting/legs.py` and which is the accounting rule the whole P&L ledger is built on —
computes `credit - debit - commissions`. It is net.

So a campaign's stored `net_premium` and the sum of its legs' realised P&L differ by exactly the
commission total, and M4 Task 4.7's cross-check would fail by construction unless it compares like
with like.

**This task does not change the arithmetic.** Changing `_rollup` would alter stored values across
the trading system and change what Telegram's `/campaigns` reports, which is a trading-behaviour
decision that does not belong inside a plan about building a web surface. What it does instead is
make the semantics explicit and un-driftable, so that P4 can reconcile against it honestly and so
that a future decision to net commissions is a deliberate one.

**Files:** Modify `src/storage/campaigns.py`, `src/storage/models.py`, `ARCHITECTURE.md`,
`docs/web/api.md`. Test `tests/test_campaign_rollup_semantics.py`.

- [x] **Step 1: Write the pinning test**

```python
"""campaigns.net_premium is GROSS of commissions. Pinned so it cannot drift silently.

If a future change decides commissions belong in the rollup, this test fails first and the
change becomes deliberate — which is the point. It is not a test to quietly update.
"""

from __future__ import annotations

import pytest

from src.storage.campaigns import attach_fill_to_campaign, load_campaigns


def test_net_premium_is_gross_of_commissions(db) -> None:
    attach_fill_to_campaign(symbol="NVDA", candidate_id="c1", action="SELL",
                            filled_qty=2, avg_price=1.50, commission=1.30)
    attach_fill_to_campaign(symbol="NVDA", candidate_id="c1", action="BUY",
                            filled_qty=2, avg_price=0.40, commission=1.30)

    campaign = load_campaigns(symbol="NVDA")[0]
    assert campaign["total_premium_collected"] == 300.0
    assert campaign["total_debit_paid"] == 80.0
    assert campaign["net_premium"] == 220.0          # NOT 217.40 — commissions are excluded


def test_the_gross_and_net_figures_differ_by_exactly_the_commissions(db) -> None:
    """The relationship M4's cross-check relies on."""
    attach_fill_to_campaign(symbol="NVDA", candidate_id="c1", action="SELL",
                            filled_qty=1, avg_price=2.00, commission=0.65)
    campaign = load_campaigns(symbol="NVDA")[0]
    commissions = 0.65
    net_of_commissions = campaign["net_premium"] - commissions
    assert campaign["net_premium"] == 200.0
    assert net_of_commissions == pytest.approx(199.35)
```

- [x] **Step 2: Run them.** They should **pass immediately** against the current code. That is
  expected — this task pins existing behaviour rather than fixing it. If either fails, the rollup
  does something other than what this task documents, and that is a finding to report before going
  further.

- [x] **Step 3: Make the semantics explicit in the code.** `CampaignRow`'s docstring
  (`src/storage/models.py:469`) currently says the fields let "the operator see cumulative income
  per symbol". Amend it to state plainly that `total_premium_collected`, `total_debit_paid` and
  `net_premium` are **gross of commissions**, that `FillRow.commission` is deliberately not
  subtracted, and that `src/reporting/` (from M4) reports the same trades net. Add the same
  sentence to `_rollup`'s own docstring.

- [x] **Step 4: Docs.** `ARCHITECTURE.md`'s `src/storage/` section records the gross/net
  distinction beside the `campaigns` entry. `docs/web/api.md`'s `/portfolio/campaigns` section
  (once M2 writes it) must say the same; if that section does not exist yet, note the obligation in
  M2's task rather than writing it early.

- [x] **Step 5: Run the gate.** `python -m pytest -q` · `ruff check .` · `mypy src`

- [x] **Step 6: Commit.**

```bash
git add src/storage/campaigns.py src/storage/models.py \
        tests/test_campaign_rollup_semantics.py ARCHITECTURE.md
git commit -m "docs(campaigns): pin net_premium as gross of commissions"
```

> **Note for whoever runs this milestone:** netting commissions into `_rollup` is a defensible
> change and this task deliberately does not make it. If the operator wants it, it is its own
> change with its own review, because it alters stored financial values and Telegram's
> `/campaigns` output. Raise it; do not fold it in here.

---

## Task 0.5 — Enforce schema-artifact freshness with a test `[SONNET]`

**Enforces an invariant, and converts three later regeneration steps from trusted to checked.**

**Context.** `docs/web/openapi.json` is stale right now. Regenerating in-process and diffing
against the checked-in file shows the paths and schemas match, but two route descriptions do not:

```
/universe/{list_name}/{symbol}  post   description
/universe/{list_name}/{symbol}  delete description
```

The docstrings changed after the last regeneration and the artifact was never refreshed. This is
the **third** recurrence of this class: P0/P1's M7 close-out found `web/lib/api-types.ts` stale by
three entire endpoints, predating that milestone.

M2, M5 and M6 each end with a regeneration step. Those steps are only as good as whoever remembers
to run them, and the record says they are forgotten. A test makes the check automatic.

**Files:** Modify `docs/web/openapi.json`. Test `tests/test_openapi_current.py`.

**Interfaces:**

```python
# tests/test_openapi_current.py
def test_the_checked_in_openapi_matches_the_live_app() -> None:
    """The artifact is generated. A stale one is a lie the whole frontend reads from.

    Regenerate with:
      python -c "import json; from src.api.main import create_app; \
                 print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json
      cd web && npm run gen:api
    """
```

**Design points:**

1. **The failure message names the fix.** A developer who trips this test should not have to go
   looking for the regeneration command; put it in the assertion message.
2. **Compare parsed JSON, not text.** Key order and trailing whitespace are not drift.
3. **`web/lib/api-types.ts` is not checked by this test.** It is generated by a Node tool from the
   JSON, so pinning the JSON pins its input; asserting on generated TypeScript from pytest would
   couple the Python suite to the Node toolchain. The milestone acceptance still requires
   regenerating it.

- [x] **Step 1: Write the test.**

```python
"""A generated artifact that drifts is worse than no artifact: the frontend reads it."""

from __future__ import annotations

import json
from pathlib import Path

from src.api.main import create_app

REGEN = (
    'python -c "import json; from src.api.main import create_app; '
    'print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json'
    "  &&  cd web && npm run gen:api"
)


def test_the_checked_in_openapi_matches_the_live_app() -> None:
    live = create_app().openapi()
    disk = json.loads(Path("docs/web/openapi.json").read_text())
    assert live == disk, f"docs/web/openapi.json is stale. Regenerate:\n  {REGEN}"
```

- [x] **Step 2: Run it and confirm it FAILS**, naming the two universe route descriptions. If it
  passes, someone regenerated the file between this plan being written and you running it — say so
  and move on.

- [x] **Step 3: Regenerate both artifacts.**

```bash
python -c "import json; from src.api.main import create_app; \
print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json
cd web && npm run gen:api
```

- [x] **Step 4: Run the test again** and confirm it passes. Then run all six gate commands —
  `web/lib/api-types.ts` may have changed, so the frontend build must be re-run.

- [x] **Step 5: Commit.**

---

## Task 0.6 — Correct the `refresh` runbook entry `[GLM]`

**Documentation only. No code, no tests.**

**Context.** `docs/web/commands.md`'s `refresh` section currently says:

> "Applied by: M6. Triggers a full scan on the next cycle."

Both halves are false. There is no `refresh` handler registered in
`src/notify/command_drain.py` — `CommandKind.REFRESH` and `RefreshPayload` exist in
`src/api/models/commands.py`, so the API happily accepts a `refresh` command and it then sits
`pending` forever. And the handler M1 Task 1.4 builds captures a portfolio snapshot; it does not
trigger a scan. `STATUS.md`'s P2 row already flags the unregistered handler.

`docs/web/commands.md` is described in the P2 plan as "the runbook for the one part of the web
layer that can move money". A runbook entry that describes a feature that does not exist is worse
than a missing one.

- [x] **Step 1:** Rewrite the `refresh` section to describe **what is true today**: the kind is
  accepted by `POST /commands`, carries an empty payload and no dedupe key, and **has no registered
  handler**, so a submitted `refresh` stays `pending` indefinitely. Say that M1 of the P3/P4 phase
  registers it.

- [x] **Step 2:** Check the rest of the file the same way rather than assuming only `refresh` is
  wrong. For each documented kind, confirm a `@register("<kind>")` exists in
  `src/notify/command_drain.py`:

```bash
grep -oE '@register\("[a-z_]+"\)' src/notify/command_drain.py | sort
grep -oE '^### `[a-z_]+`' docs/web/commands.md | sort
```

Report any other mismatch rather than silently fixing it — a second undocumented or unimplemented
kind is a finding, not a typo.

- [x] **Step 3:** Run the full gate (documentation changes still get the gate run; a stray edit to
  a fenced code block can break nothing, and confirming that costs a minute) and commit.

---

## Task 0.7 — Clear P2's deferred findings `[GLM]`

**Context.** P2's M7 close-out log recorded seven minor findings as "deferred, not fixed". Four are
in files this phase edits, and all four are trivial. Two of the seven were judged reasonable
divergences at the time and stay closed. One (`README.md`'s missing row) was fixed in that pass.

Each item below has been re-verified against the current code — these are open now, not just open
when the log was written.

**Files:** Modify `src/storage/universe_overrides.py`, `src/orchestrator/eod_report.py`,
`tests/test_universe_consumers.py`, `web/CLAUDE.md`.

- [x] **Step 1: Dead logger.** `src/storage/universe_overrides.py` defines
  `log = logging.getLogger(__name__)` at line 17 and never uses it — `grep -c "log\." ` returns 0.
  Ruff does not flag it because the name is assigned. Remove both the assignment and the
  `import logging` at line 10.

- [x] **Step 2: Unused, untyped parameter.** `src/orchestrator/eod_report.py:105`:

```python
def _universe_symbols(cfg) -> list[str]:
    u = effective_universe()
    ...
```

`cfg` is never read — the function calls `effective_universe()` instead — and it carries no type
annotation, which `CLAUDE.md`'s "type-hint everything" forbids. Drop the parameter and update both
call sites (lines 334 and 343).

- [x] **Step 3: Redundant fixture.** `tests/test_universe_consumers.py` has a local autouse
  cache-reset fixture made redundant by the global one M7 Task 7.3 added to `tests/conftest.py`.
  Remove the local one and confirm the file still passes — if it does not, the global fixture does
  not cover this case and the local one stays, which is a finding to record.

- [x] **Step 4: Doc over-attribution.** `web/CLAUDE.md`'s `components/universe/` bullet attributes
  `submitUniverseCommand` and `CommandReceipt` behaviour to `OverrideBadge`, which is purely
  presentational. Correct the attribution to `AddSymbol` and `UniverseList`.

- [x] **Step 5:** Run all six gate commands. The Python count must be unchanged except for any test
  removed in Step 3, and nothing may fail.

- [x] **Step 6:** Commit as one change with a message naming it as P2 deferred-findings cleanup.

---

## Task 0.8 — The proxy fails soft when the API is down `[SONNET]`

**Touches the P2 security boundary, and it is a degradation-judgment call.**

**Read the file before you edit it.** It has uncommitted changes (Task 0.1) and M5 Task 5.3 edits
the same function later. The version quoted below is from the committed tree; the working tree may
differ.

**Context.** `web/app/api/[...path]/route.ts` calls the upstream API like this:

```typescript
const upstream = await fetch(target, init);
const body = await upstream.text();
```

There is no `try`, and there is no timeout. When the FastAPI process is not running — a restart, a
crash, a machine that has not started it yet — `fetch` rejects with a connection error, the route
handler throws, and **Next.js returns its own HTML error page with status 500.** `apiFetch` then
does `res.text()` on that HTML and throws `ApiError(500, "<!DOCTYPE html>…")`, so the UI renders a
page of markup where an error message belongs.

P1 and P2 hit this occasionally. **P3 and P4 poll continuously** — the portfolio refreshes on the
snapshot cadence and a `refresh` command polls every two seconds — so every API restart during
development, and every API outage in use, produces this.

The right behaviour is the one P2 already established for the missing-token case two lines above:
return a JSON body with a `detail` the client can render.

**Files:** Modify `web/app/api/[...path]/route.ts`, `web/CLAUDE.md`. Test
`web/app/api/[...path]/route.test.ts`.

**Interfaces:**

```typescript
const UPSTREAM_TIMEOUT_MS = 30_000;

// Inside proxy(), replacing the bare fetch:
//   502 + {detail} when the upstream cannot be reached
//   504 + {detail} when it does not answer within UPSTREAM_TIMEOUT_MS
```

**Design points that are not negotiable:**

1. **The failure body is JSON**, shaped like every other error the client already handles:
   `{"detail": "..."}`. `apiFetch` surfaces `detail` as the `ApiError` message, so the UI gets a
   sentence rather than markup.
2. **The message says the API is not reachable**, in words an operator can act on. It must not
   include the upstream URL or the exception's stack — the browser has no business seeing either.
   Never include the token, obviously.
3. **`502` for unreachable, `504` for timeout.** Two distinct states an operator debugs
   differently.
4. **A timeout is bounded but generous.** 30 seconds: `POST /research/{symbol}/summary` runs a
   model call, and a proxy that gives up before the backend does would turn a slow success into a
   fabricated failure.
5. **Nothing else about the proxy changes.** Not the method allowlist, not the token injection, not
   the `204`/`304` handling. This task adds a `try`/`catch` and a signal; it does not refactor.

Required behaviours, each with a test:
- An upstream connection failure returns `502` with a JSON `detail`, not an HTML page.
- The `detail` does not contain the upstream URL or the word `Bearer`.
- A timeout returns `504` with a JSON `detail`.
- **A successful request is byte-identical to before**, including status, `Content-Type`, and body.
  Its own test — the regression risk here is breaking the working path while handling the broken
  one.
- The missing-`API_TOKEN` `500` from P2 still fires and is unchanged.

- [x] **Step 1: Write the failing test**

```typescript
it("returns a JSON 502 when the API cannot be reached", async () => {
  mockFetchRejects(new TypeError("fetch failed"));
  const res = await GET(req("/api/portfolio/summary"), ctx);

  expect(res.status).toBe(502);
  expect(res.headers.get("Content-Type")).toContain("application/json");
  const body = await res.json();
  expect(body.detail).toMatch(/not reachable/i);
  expect(body.detail).not.toMatch(/127\.0\.0\.1|localhost|Bearer/);
});

it("returns a JSON 504 when the API does not answer in time", async () => {
  mockFetchNeverResolves();
  const res = await GET(req("/api/portfolio/summary"), ctx);
  expect(res.status).toBe(504);
  expect((await res.json()).detail).toMatch(/timed out/i);
});

it("leaves a successful response untouched", async () => {
  mockUpstream({ status: 200, body: '{"ok":true}', headers: { "Content-Type": "application/json" } });
  const res = await GET(req("/api/portfolio/summary"), ctx);
  expect(res.status).toBe(200);
  expect(await res.text()).toBe('{"ok":true}');
});
```

Use fake timers for the timeout test rather than waiting 30 seconds.

- [x] **Step 2: Run and confirm failure.**

- [x] **Step 3: Implement** with `AbortSignal.timeout(UPSTREAM_TIMEOUT_MS)` and a `try`/`catch`
  distinguishing an abort from a connection error.

- [x] **Step 4:** Run all six gate commands. Every pre-existing proxy test must still pass.

- [x] **Step 5:** `web/CLAUDE.md`'s "API proxy" section gains the failure contract: `502`
  unreachable, `504` timeout, JSON `detail` in both, never markup. Commit.

---

## Task 0.9 — One `as_utc` `[SONNET]`

**Routed to Sonnet by this plan's own criterion 6: the deliverable is reuse, not new code.** The
recorded failure mode it guards against is a worker writing a third implementation instead of
noticing the first two.

**Context.** SQLite returns naive datetimes, and a naive datetime serialised without an offset is
read by a browser's `Date` parser as *local* time — silently shifting a displayed age by the
viewer's UTC offset. The codebase knows this and coerces, in two places:

- `src/api/models/common.py:26` — `def _as_utc(dt: datetime) -> datetime`, used by `Sourced.of`,
  with the reasoning written out in that method's docstring.
- `src/api/routers/options.py:110` — `def _as_utc(dt: datetime | None) -> datetime | None`, the
  same coercion with a nullable signature.

Same rule, two implementations, both private. Every P3/P4 router reads stored timestamps and needs
this, so the default outcome is a third copy.

**Files:** Modify `src/api/models/common.py`, `src/api/routers/options.py`. Test
`tests/test_api_provenance.py`.

**Interfaces:**

```python
# src/api/models/common.py — promoted from private to the module's public surface
def as_utc(dt: datetime) -> datetime:
    """Treat a naive datetime as UTC rather than raising.

    SQLite returns naive datetimes. A naive datetime serialises without an offset, which a
    browser's Date parser reads as LOCAL time — silently shifting a displayed age by the
    viewer's UTC offset instead of reporting it correctly.
    """


def as_utc_opt(dt: datetime | None) -> datetime | None:
    """as_utc, passing None through. The shape router code actually needs."""
```

**Design points:**

1. **Both names are public.** The nullable variant exists because router code overwhelmingly has
   `datetime | None`; forcing every call site to write its own `None` guard is how the second
   implementation appeared in the first place.
2. **`as_utc_opt` is defined in terms of `as_utc`**, not as a parallel implementation.
3. **`Sourced.of` keeps its current behaviour exactly.** It already calls the private helper; it
   now calls the public one. No test in `tests/test_api_provenance.py` should need editing — if one
   does, behaviour changed.
4. Delete the local copy in `options.py` and import instead. Leave no alias behind.

Required behaviours, each with a test:
- `as_utc` on a naive datetime returns the same wall-clock time, tz-aware, UTC.
- `as_utc` on an aware datetime returns it unchanged, including a non-UTC offset.
- `as_utc_opt(None)` is `None`; `as_utc_opt(naive)` matches `as_utc(naive)`.
- **`tests/test_api_provenance.py` passes unchanged.** The existing tests are the regression net.
- No module under `src/api/` defines a local `_as_utc` any more, asserted by grep in the test.

- [x] **Step 1: Record the baseline.** `python -m pytest tests/test_api_provenance.py -q` and note
  the count. It must be identical afterwards.

- [x] **Step 2: Write the failing test**

```python
def test_no_module_defines_its_own_as_utc() -> None:
    """Two implementations became two signatures. A third would become three."""
    offenders = [
        str(p) for p in Path("src/api").rglob("*.py")
        if "def _as_utc" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"local _as_utc copies remain: {offenders}"


def test_an_aware_datetime_survives_unchanged() -> None:
    aware = datetime(2026, 9, 9, 12, 0, tzinfo=timezone(timedelta(hours=-4)))
    assert as_utc(aware) is aware or as_utc(aware) == aware


def test_the_optional_variant_passes_none_through() -> None:
    assert as_utc_opt(None) is None
```

- [x] **Step 3: Confirm failure. Step 4: Implement and rewire. Step 5:** Re-run the provenance
  baseline; the count must match. **Step 6:** Run the gate and commit.

---

## Task 0.10 — Consolidate and strengthen the fence tests `[SONNET]`

**Enforces an invariant.** `CLAUDE.md` calls `tests/test_web_fence.py` load-bearing and says
explicitly that if a fence test is deleted, the guarantee is gone. M4 Task 4.1 and M6 Task 6.3 both
add tests to this file, so it is worth arriving in good order.

**Context.** Two problems, both from P0/P1's M7 hardening pass, where Sonnet landed the spec's form
of a test beside a GLM stand-in.

**One duplicated test.** `test_checks_engine_never_imports_the_summary_layer` (line 41) and
`test_the_checks_engine_never_imports_the_summary_layer` (line 84) assert the same thing over the
same glob with the same substring. The second one's own docstring says "Already covered above".

**A non-recursive glob.** Both use `checks_dir.glob("*.py")`, which does not descend into
subpackages. `src/research/checks/` and `src/research/summary/` are both flat today, so the fence
holds — but adding `src/research/checks/rules/thing.py` would move that file outside the fence's
coverage **silently**, and the test would keep passing. This is not a live bug; it is a latent one
in the file whose entire job is catching this class of mistake.

**Files:** Modify `tests/test_web_fence.py`.

- [x] **Step 1: Prove the gap before closing it.** Create a throwaway
  `src/research/checks/_fence_probe/leak.py` containing the line
  `from src.research.summary import service`, run the two checks tests, and confirm **both pass** —
  demonstrating the fence does not see it. Delete the probe file immediately afterwards. Record the
  result in the task notes; do not commit the probe.

- [x] **Step 2: Delete the duplicate.** Keep the line-41 version, which has the better docstring and
  the `checks_dir.is_dir()` assertion that stops the test passing vacuously if the package is ever
  renamed. Delete the line-84 version.

- [x] **Step 3: Switch every directory walk in the file to `rglob`.** Check each test, not just the
  two: any `glob("*.py")` over a package directory has the same hole.

- [x] **Step 4: Re-run the probe from Step 1** and confirm the fence now **fails**. Delete the probe
  again. This is the only evidence that the change did anything.

- [x] **Step 5:** Run the full suite. The count drops by exactly one (the deleted duplicate) and
  nothing else changes. **A drop of more than one means `rglob` caught a real violation** — stop and
  report it rather than reverting to `glob`.

- [x] **Step 6:** Run the gate and commit.

---

## Milestone 0 acceptance

- [x] The six gate numbers are recorded at the top of this file under "Baseline as executed", with
  a date, and the operator has ruled on the in-flight working-tree changes.
- [x] A repeated EOD run for the same ET day leaves one journal row and **still runs the reconciler
  and `save_position_snapshot`**, proven by a test that asserts those two were called on the second
  run.
- [x] One definition of assignment risk exists in `src/common/assignment_risk.py`, used by both the
  monitor and the API, reading thresholds from config in both.
- [x] `/options/shorts` now flags a 10-DTE, 0.75-delta short as at risk where it previously did
  not, and the false comment claiming 7 DTE was "the monitor's default" is gone.
- [x] `campaigns.net_premium` is documented as gross of commissions, in the model docstring, in
  `_rollup`'s docstring, and in `ARCHITECTURE.md`, with a test pinning it.
- [x] `tests/test_openapi_current.py` passes, and it failed before the artifacts were regenerated.
- [x] `docs/web/commands.md`'s `refresh` section describes what is true today, and every other
  documented kind has been checked against `@register` in `command_drain.py`.
- [x] P2's four open deferred findings are closed.
- [x] The BFF proxy returns a JSON `502` when the API is unreachable and a `504` when it times out,
  and neither body leaks the upstream URL or the token. A successful response is unchanged.
- [x] Exactly one `as_utc` implementation exists under `src/api/`, asserted by a test, and
  `tests/test_api_provenance.py` passes unchanged.
- [x] `tests/test_web_fence.py` has no duplicated test and walks packages recursively, **proven by
  a probe file that passed the fence before the change and fails it after**.
- [x] Full gate green, all six commands, with the Python count up by the tests this milestone added
  and down by exactly two removals: the redundant fixture in Task 0.7 and the duplicated fence test
  in Task 0.10.
