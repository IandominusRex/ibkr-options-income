# Milestone 6 — System performance and close-out

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The score-vs-outcome evidence the system already produces gets a reader, the two new
fences are enforced by tests rather than by intention, and the phase closes out with docs that
match the code.

**Spec:** `Web plan/P3-P4-design.md` §7.5 and §14. **Index:**
`Web plan/P3-P4-IMPLEMENTATION-PLAN.md`. **Depends on:** Milestone 5.

**The shape of this milestone in one sentence:** `CLAUDE.md` says everything `src/claude/eval/`
produces "is read by a human, never auto-applied" — this milestone builds the human's reading
surface, and the tests that prove it stayed a reading surface.

---

## Task 6.1 — `GET /pnl/system` `[SONNET]`

**Reads behind the fence. The one route in the phase where the reason it is allowed has to be
written down.**

**Context.** `src/claude/eval/score_metrics.py::score_outcome_report()` already exists and already
returns a `ScoreOutcomeReport`: blended-score buckets against realised win rate and P&L,
per-component buckets, signal correlations, and a `notes` list. Today it is read only by
`scripts/evaluate_scores.py`.

Its own `notes` already carry the sentence:

> "Read-only: re-derive scoring_weights.yaml from this evidence by hand (the fence forbids any
> automatic feedback into the engine)."

**That sentence renders on the page verbatim.** It is the most important sentence on the surface
and it is not the UI's to paraphrase or shorten.

**Files:** Modify `src/api/routers/pnl.py`, `src/api/models/pnl.py`, `docs/web/api.md`. Test
`tests/test_api_pnl_system.py`.

**Interfaces:**

```python
class VerdictAgreement(BaseModel):
    """How often Claude's verdict matched the deterministic baseline, and how each did."""

    n_closed: int
    n_agreed: int
    agreement_rate: float | None = None     # None when n_closed is 0, never 0.0
    claude_win_rate: float | None = None
    baseline_win_rate: float | None = None


class SystemPerformanceResponse(Envelope):
    report: ScoreOutcomeReport
    agreement: VerdictAgreement
    since: date | None = None
    until: date | None = None
```

Consumes: `score_outcome_report(since=..., until=...)` and
`src/claude/eval/ledger.py::load_records(closed_only=True)`.

**Design points that are not negotiable:**

1. **The route calls `score_outcome_report` and returns what it gets.** It does not recompute a
   bucket, re-derive a correlation, or filter the `notes`. If the report is wrong, the fix is in
   `score_metrics.py` where the trading side can see it, not in a web router.
2. **`notes` passes through in full and in order.** No truncation, no dedupe, no "the UI only shows
   the first two". A test asserts the response's `notes` equals the report's.
3. **The empty case is the report's own empty case.** With no closed trades,
   `score_outcome_report` returns `n_closed=0` with a note saying so. Return it. Do not substitute
   a `404` or a hand-written empty message.
4. **`agreement_rate` is `None` with zero closed trades**, never `0.0`. Same rule as everywhere
   else in this phase.
5. **The API cannot write any of this.** `verdict_ledger` and `scoring_weights.yaml` are read-only
   from here, and Task 6.3 asserts it.
6. `owner_only`.

Required behaviours, each with a test:
- With closed ledger rows, the response carries the report's buckets and correlations unchanged.
- **The response's `notes` list equals `score_outcome_report`'s exactly**, including the read-only
  sentence. Its own test.
- With no closed rows, `n_closed: 0`, status `200`, and the report's own "nothing to correlate yet"
  note.
- `agreement_rate` is `None` with zero closed rows and a real rate with some.
- `since` and `until` window the report and are echoed back.
- A non-owner gets `403`.

- [x] **Step 1: Write the failing test**

```python
"""The fence's own words reach the page unedited."""

from __future__ import annotations

from src.claude.eval.score_metrics import score_outcome_report


def test_the_reports_notes_pass_through_verbatim(client, seed_closed_ledger_rows) -> None:
    """The read-only sentence is the most important text on the surface."""
    seed_closed_ledger_rows(n=12)
    expected = score_outcome_report().notes

    body = client.get("/pnl/system", headers=OWNER).json()
    assert body["report"]["notes"] == expected
    assert any("forbids any automatic feedback" in note for note in body["report"]["notes"])


def test_no_closed_trades_returns_the_reports_own_empty_case(client) -> None:
    r = client.get("/pnl/system", headers=OWNER)
    assert r.status_code == 200
    body = r.json()
    assert body["report"]["n_closed"] == 0
    assert any("No closed trades in window" in note for note in body["report"]["notes"])
    assert body["agreement"]["agreement_rate"] is None


def test_the_route_does_not_recompute_the_report(client, seed_closed_ledger_rows,
                                                 monkeypatch) -> None:
    """If the report is wrong, it is fixed in score_metrics.py, not in a router."""
    seed_closed_ledger_rows(n=5)
    calls = []
    real = score_outcome_report

    def spy(*a, **k):
        calls.append((a, k))
        return real(*a, **k)

    monkeypatch.setattr("src.api.routers.pnl.score_outcome_report", spy)
    client.get("/pnl/system", headers=OWNER)
    assert len(calls) == 1


def test_a_non_owner_is_refused(client) -> None:
    assert client.get("/pnl/system", headers=VIEWER).status_code == 403
```

- [x] **Step 2: Confirm failure. Step 3: Implement. Step 4: Run the gate.**

- [x] **Step 5:** `docs/web/api.md` documents the route **and states why reading a fenced table
  here is the intended use**: the fence forbids the loop closing automatically, and this route is a
  `GET` that closes nothing. Commit.

---

## Task 6.2 — The system performance surface `[GLM]`

**Files:** Create `web/components/pnl/{SystemPanel,ScoreBucketTable,CorrelationTable}.tsx`. Test
`web/components/pnl/SystemPanel.test.tsx`.

**Interfaces:** consumes `GET /pnl/system`. Uses `Money` (M3 Task 3.1).

Required behaviours, each with a test:
- **Every note in `report.notes` renders, in order, in full.** Its own test — the read-only
  sentence is the reason the surface is allowed to exist and it must be on the page, not in a
  tooltip and not behind a disclosure.
- Blended-score buckets render as a table: label, `n`, win rate, mean P&L, total P&L.
- **A bucket with `n` below a small threshold is labelled as a small sample** in words. A win rate
  from three trades is not evidence and the page should not let it read as one.
- Component buckets render in their own table, separately labelled.
- Correlations render with `pearson_r` and the low/high split; `pearson_r: null` renders `n/a`.
- `n_closed: 0` renders the report's own note and **no buckets and no correlation table at all** —
  not empty tables with `n/a` rows.
- The agreement block renders Claude's and the baseline's win rates side by side, with
  `agreement_rate: null` rendering `n/a`.
- **No control anywhere on this surface changes a weight.** There is no "apply" button, no
  suggested weight, and no editable field. Asserted by a test that queries for any button or input
  in the panel and finds none beyond the date-window controls.

- [x] **Step 1: Write the failing tests**

```typescript
it("renders every note in full and in order", () => {
  const notes = ["Closed (executed+settled) trades only ...",
                 "Read-only: re-derive scoring_weights.yaml from this evidence by hand ..."];
  render(<SystemPanel data={{ ...aReport(), report: { ...aReport().report, notes } }} />);
  notes.forEach((n) => expect(screen.getByText(n)).toBeInTheDocument());
});

it("offers no way to change a weight", () => {
  const { container } = render(<SystemPanel data={aReport()} />);
  const controls = container.querySelectorAll("button, input, select");
  const windowControls = container.querySelectorAll('[data-role="window-control"]');
  expect(controls.length).toBe(windowControls.length);
});

it("says when a bucket is too small to be evidence", () => {
  render(<SystemPanel data={reportWithBucket({ label: "80-90", n: 3 })} />);
  expect(screen.getByText(/small sample/i)).toBeInTheDocument();
});

it("renders nothing but the note when no trades have closed", () => {
  render(<SystemPanel data={emptyReport()} />);
  expect(screen.queryByRole("table")).toBeNull();
  expect(screen.getByText(/no closed trades in window/i)).toBeInTheDocument();
});
```

- [x] **Step 2: Confirm failure. Step 3: Implement. Step 4: All six gate commands. Step 5: Commit.**

---

## Task 6.3 — Fence test extensions `[SONNET]`

**Enforces the invariants this phase introduced.** Task 4.1 already landed the two
`src/reporting/` import rules; this task adds the write-side assertions and pins the surface.

**Files:** Modify `tests/test_web_fence.py`.

- [x] **Step 1: Add these tests**

```python
def test_no_web_module_can_write_the_verdict_ledger() -> None:
    """P4 reads the outcome ledger. Nothing in the web layer may write it."""
    writers = ("record_verdicts", "update_outcome", "mark_filled", "VerdictLedgerRow(")
    for path in Path("src/api").rglob("*.py"):
        text = path.read_text()
        for writer in writers:
            assert writer not in text, f"{path} can write the verdict ledger via {writer}"


def test_no_web_module_can_write_a_scoring_weight() -> None:
    """The fence's whole point: the loop does not close automatically."""
    for path in Path("src/api").rglob("*.py"):
        text = path.read_text()
        assert "scoring_weights" not in text, f"{path} references scoring weights"


def test_the_api_still_writes_exactly_one_table() -> None:
    """P3 and P4 add no write. The P2 guarantee is unchanged, re-asserted here because
    this is the phase that had the most reason to relax it."""
    for path in Path("src/api").rglob("*.py"):
        if path.name == "commands.py":
            continue
        text = path.read_text()
        assert "get_command_engine" not in text
        assert "command_session" not in text


def test_reporting_never_writes_anything() -> None:
    """src/reporting/ computes. It does not persist, and a cache is not an exception."""
    for path in Path("src/reporting").rglob("*.py"):
        text = path.read_text()
        for writer in ("session.add", "session.merge", "session.delete", "session.commit"):
            assert writer not in text, f"{path} writes to the database"


def test_the_portfolio_snapshot_writers_are_the_two_we_intended() -> None:
    """A third writer means a third cadence nobody reasoned about."""
    callers = [
        path for path in Path("src").rglob("*.py")
        if "save_portfolio_snapshot" in path.read_text()
        and path.name != "portfolio_snapshots.py"
    ]
    assert {p.as_posix() for p in callers} == {
        "src/monitor/intraday.py",
        "src/notify/command_drain.py",
    }
```

- [x] **Step 2: Run them.** Every one must pass against the code as built. A failure here is a real
  finding, not a test to adjust — investigate the module that trips it before touching the
  assertion.

- [x] **Step 3:** Run the full suite, `ruff check .`, `mypy src`.

- [x] **Step 4:** Root `CLAUDE.md`'s "The web layer and the trading database" section gains one
  sentence: P3 and P4 added no write beyond the `refresh` command, and the API still writes exactly
  one table. Commit.

---

## Task 6.4 — Close out P3 and P4 `[GLM]`

**Files:** Modify `STATUS.md`, `README.md`, `ARCHITECTURE.md`, `CLAUDE.md`,
`docs/web/architecture.md`, `docs/web/api.md`, `docs/web/commands.md`,
`Web plan/P3-P4-IMPLEMENTATION-PLAN.md`, `Web plan/milestones/P3-P4/M1`-`M6`.

This is a verification pass, not a writing pass. **Check each item rather than assuming the task
that owned it did its job** — a previous phase's close-out found stale entries, an unregistered
handler documented as working, and schema artifacts three endpoints out of date.

- [x] **Step 1: Re-derive, do not re-assert.** For each of the following, run the check and record
  the result:

```bash
# Every new route is in the docs.
grep -c "^### " docs/web/api.md
python -c "import json; from src.api.main import create_app; \
print('\n'.join(sorted(create_app().openapi()['paths'])))"

# Every command failure reason in the code appears in commands.md.
grep -oE 'CommandFailed\("[a-z_]+"|_fail\([^,]+, "[a-z_]+"' src/notify/command_drain.py

# The schema artifacts are current.
python -c "import json; from src.api.main import create_app; \
print(json.dumps(create_app().openapi(), indent=2))" > /tmp/openapi.json
diff /tmp/openapi.json docs/web/openapi.json && echo "openapi current"
cd web && npm run gen:api && git diff --exit-code lib/api-types.ts && echo "types current"
```

- [x] **Step 2:** `STATUS.md`'s web platform table: P3 and P4 rows written in the same dense style
  P2's rows use, covering every milestone. The "Not built" sentence names what is still deferred:
  **P5 (mobile), operator notes on legs and campaigns, a materialised P&L table, intraday equity
  history beyond the snapshot retention window, and any Tailscale or remote hosting.** State
  plainly that the ledger's numbers have not been reconciled against a broker statement.

- [x] **Step 3:** Root `CLAUDE.md`: confirm the analytics-tier section names `src/reporting/` (Task
  4.1) and the web-layer section carries Task 6.3's sentence. Add a doc-update trigger row: **"New
  module under `src/reporting/` → `ARCHITECTURE.md` folder guide · root `CLAUDE.md` analytics-tier
  section"**, so the next person extending the reporting layer has the same obligation the other
  layers already carry.

- [x] **Step 4:** `README.md`'s layout table: confirm rows exist for `src/reporting/`,
  `src/storage/portfolio_snapshots.py`, `src/api/portfolio_source.py`,
  `src/common/assignment_risk.py`, `src/api/routers/portfolio.py`, `src/api/routers/pnl.py`,
  `web/app/portfolio/` and `web/app/pnl/`. Add whatever is missing.

- [x] **Step 5:** `ARCHITECTURE.md`: confirm the folder guide describes what shipped, not what was
  planned mid-flight. Check the entries for `src/monitor/intraday.py` (it writes snapshots now),
  `src/notify/command_drain.py` (it has a `refresh` handler now), and
  `src/claude/eval/reconcile.py` (its accounting moved).

- [x] **Step 6:** Tick the checkboxes in all six milestone files and in this plan's index. A
  closed-out phase whose milestone files show zero completed tasks misrepresents its own status to
  the next reader.

- [x] **Step 7:** Write an implementation log at the foot of
  `Web plan/P3-P4-IMPLEMENTATION-PLAN.md`, in the shape P2's M7 log uses: what each task shipped,
  what was escalated, every ruling made along the way, minor findings deferred rather than fixed,
  and the final gate numbers for all six commands.

- [x] **Step 8:** Run all six gate commands, record the numbers in the log, and commit.

---

## Milestone 6 acceptance

- [x] `/pnl/system` renders the score-vs-outcome report and the verdict agreement, read-only.
- [x] **Every note the report produces appears on the page in full and in order**, including the
  sentence saying the weights must be re-derived by hand.
- [x] The surface offers no control that could change a weight, asserted by a test that counts
  controls.
- [x] A small bucket is labelled as a small sample rather than presented as evidence.
- [x] No module under `src/api/` can write `verdict_ledger` or reference `scoring_weights`.
- [x] `src/reporting/` writes nothing to the database.
- [x] `save_portfolio_snapshot` has exactly two callers, and they are the monitor and the drain.
- [x] The API still writes exactly one table.
- [x] `docs/web/openapi.json` and `web/lib/api-types.ts` regenerate to an empty diff, verified by
  running the regeneration rather than by trusting a previous task.
- [x] `STATUS.md` records P3 and P4 as built, names what is still deferred, and states that the
  ledger has not been reconciled against a broker statement.
- [x] Every milestone file's checkboxes reflect what actually landed.
- [x] Full gate green, all six commands, with the numbers recorded in the implementation log.
