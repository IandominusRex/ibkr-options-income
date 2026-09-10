# P3-P4 M6 — System Performance and Close-Out Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (this plan is executed
> inline, in the same session that wrote it, since all research context is already loaded).
> Steps use checkbox (`- [ ]`) syntax.

**Goal:** Build the one human-facing reader over `src/claude/eval/score_metrics.py`'s
score-vs-outcome evidence (`GET /pnl/system` + a web console panel), lock the fence with tests
instead of intention, and close out the whole P3-P4 phase with docs that match the shipped code.

**Architecture:** A single new read route (`GET /pnl/system`) that calls
`score_outcome_report()` and `ledger.load_records(closed_only=True)` and returns their output
unmodified, behind the same `OwnerUser` gate every P3/P4 route uses. A three-component,
presentational (non-fetching) web panel wired into `PnlShell` as a third tab, owning no state of
its own. Five new fence tests pinning what P3/P4 already guarantees. A verification-driven
close-out pass across nine documentation files.

**Tech Stack:** FastAPI + Pydantic (backend), Next.js/React + TanStack Query + Vitest (frontend),
pytest (backend tests).

**Spec:** `Web plan/milestones/P3-P4/M6-system-performance.md` (the literal task text, followed
verbatim except where noted below), `Web plan/P3-P4-design.md` §7.5 (fence rationale) and §14
(doc obligations), `Web plan/P3-P4-IMPLEMENTATION-PLAN.md` (phase index).

## Global Constraints

- Every route is `owner_only` (403 for a non-owner, via `OwnerUser`).
- The route **never recomputes** a bucket/correlation/note `score_outcome_report` already
  produced — it calls the function once and returns the result.
- `agreement_rate` (and every other "rate" field) is `None` with zero closed rows, **never
  `0.0`**.
- No control anywhere on the new web surface can change a scoring weight — no button, no input,
  no select beyond the two date-window fields.
- `docs/web/openapi.json` and `web/lib/api-types.ts` must regenerate to an empty diff before this
  is done (`tests/test_openapi_current.py` enforces the first half already).
- Full gate before declaring any task done: `python -m pytest -q`, `ruff check .`, `mypy src`,
  `cd web && npx vitest run`, `npm run lint`, `npm run build`.

---

### Task 6.1 — `GET /pnl/system`

**Files:**
- Modify: `src/api/models/pnl.py` (add `VerdictAgreement`, `SystemPerformanceResponse`)
- Modify: `src/api/routers/pnl.py` (add `_win_rate`, `_verdict_agreement`, `pnl_system`)
- Modify: `tests/conftest.py` (add `seed_closed_ledger_rows` fixture, beside `seed_wheel_ledger`)
- Create: `tests/test_api_pnl_system.py`
- Modify: `docs/web/api.md` (new `### GET /pnl/system` section)

**Interfaces:**

```python
# src/api/models/pnl.py additions
from pydantic import BaseModel
from src.common.schemas import ScoreOutcomeReport  # add to existing schemas import

class VerdictAgreement(BaseModel):
    n_closed: int
    n_agreed: int
    agreement_rate: float | None = None
    claude_win_rate: float | None = None
    baseline_win_rate: float | None = None

class SystemPerformanceResponse(Envelope):
    report: ScoreOutcomeReport
    agreement: VerdictAgreement
    since: date | None = None
    until: date | None = None
```

Consumes: `src.claude.eval.score_metrics.score_outcome_report(since, until)`,
`src.claude.eval.ledger.load_records(closed_only=True)`. `VerdictRecord.agreement: bool | None`
(already on the schema — set at scan time by `src/orchestrator/scan.py`) is read directly, never
recomputed.

- [x] **Step 1: `VerdictAgreement` + `SystemPerformanceResponse` in `src/api/models/pnl.py`.**
  Import `BaseModel` from pydantic and `ScoreOutcomeReport` from `src.common.schemas` (add to the
  existing import line). Paste the two classes above, in that order, after `EquityResponse`.

- [x] **Step 2: Write the failing tests in `tests/test_api_pnl_system.py`.**

```python
"""Task 6.1 — GET /pnl/system: the score-vs-outcome report's human reader.

The one P&L route that reads behind the src/claude/eval/ fence — CLAUDE.md says everything
eval/ produces "is read by a human, never auto-applied," and this route is that human's
reader. It must never recompute what score_outcome_report already produced.
"""

from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import OWNER

from src.claude.eval.score_metrics import score_outcome_report


def test_the_reports_notes_pass_through_verbatim(client, seed_closed_ledger_rows) -> None:
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
    assert body["agreement"]["n_closed"] == 0


def test_the_route_does_not_recompute_the_report(client, seed_closed_ledger_rows, monkeypatch) -> None:
    seed_closed_ledger_rows(n=5)
    calls = []
    real = score_outcome_report

    def spy(*a, **k):
        calls.append((a, k))
        return real(*a, **k)

    monkeypatch.setattr("src.api.routers.pnl.score_outcome_report", spy)
    client.get("/pnl/system", headers=OWNER)
    assert len(calls) == 1


def test_the_response_carries_the_reports_buckets_and_correlations_unchanged(
    client, seed_closed_ledger_rows
) -> None:
    seed_closed_ledger_rows(n=12)
    expected = score_outcome_report().model_dump(mode="json")

    body = client.get("/pnl/system", headers=OWNER).json()
    assert body["report"]["blended_score_buckets"] == expected["blended_score_buckets"]
    assert body["report"]["component_buckets"] == expected["component_buckets"]
    assert body["report"]["signal_correlations"] == expected["signal_correlations"]


def test_agreement_rate_is_a_real_number_with_closed_rows(client, seed_closed_ledger_rows) -> None:
    seed_closed_ledger_rows(n=10)
    body = client.get("/pnl/system", headers=OWNER).json()
    assert body["agreement"]["n_closed"] == 10
    assert body["agreement"]["agreement_rate"] is not None
    assert 0.0 <= body["agreement"]["agreement_rate"] <= 1.0
    assert body["agreement"]["claude_win_rate"] is not None
    assert body["agreement"]["baseline_win_rate"] is not None


def test_since_and_until_window_the_report_and_are_echoed_back(
    client, seed_closed_ledger_rows
) -> None:
    seed_closed_ledger_rows(n=4, offset_days=40)
    seed_closed_ledger_rows(n=4, offset_days=2)
    since = date.today() - timedelta(days=10)
    until = date.today()

    body = client.get(
        f"/pnl/system?since={since.isoformat()}&until={until.isoformat()}", headers=OWNER
    ).json()

    assert body["since"] == since.isoformat()
    assert body["until"] == until.isoformat()
    assert body["report"]["n_closed"] == 4
    assert body["agreement"]["n_closed"] == 4


def test_a_non_owner_is_refused(client, monkeypatch) -> None:
    from src.api.auth import Role, User

    viewer = User(id="viewer", role=Role.VIEWER)
    monkeypatch.setattr("src.api.deps.authenticate", lambda token: viewer if token else None)
    assert client.get("/pnl/system", headers=OWNER).status_code == 403
```

- [x] **Step 3: Run to confirm failure** (`seed_closed_ledger_rows` and `/pnl/system` don't exist
  yet): `python -m pytest tests/test_api_pnl_system.py -v` — expect collection/fixture errors.

- [x] **Step 4: Add the `seed_closed_ledger_rows` fixture to `tests/conftest.py`**, immediately
  after `seed_wheel_ledger` (~line 758). Depends on `client` only — `client`'s own monkeypatching
  already binds `src.storage.db` (what `record_verdicts`/`load_records` use via
  `session_scope()`) to the same file `src.api.trading_db` reads, so no `api_db` rebinding is
  needed here, unlike the M5 route-test fixtures.

```python
@pytest.fixture()
def seed_closed_ledger_rows(client):  # noqa: ARG001 - binds storage engine to the client's DB
    """Write `n` closed verdict-ledger rows spanning the blended-score bands (P3-P4 M6 Task 6.1).

    Alternates win/loss and sell/skip so the report's buckets, correlations, and the route's
    agreement figure all have real spread. `offset_days` sets how many days ago `outcome_date`
    falls, and namespaces candidate_id, so a test can call this twice to build two date cohorts
    for a since/until window test without the second call's upsert clobbering the first.
    """

    def _seed(*, n: int = 10, offset_days: int = 1) -> None:
        from src.claude.eval.ledger import record_verdicts
        from src.common.schemas import OptionRight, Strategy, VerdictOutcome, VerdictRecord

        records = []
        for i in range(n):
            win = i % 2 == 0
            score = 55.0 + (i % 5) * 10.0
            records.append(
                VerdictRecord(
                    candidate_id=f"score-{offset_days}-{i}",
                    run_id="run-score",
                    scan_date=date.today() - timedelta(days=offset_days + 30),
                    underlying="NVDA",
                    strategy=Strategy.CASH_SECURED_PUT,
                    right=OptionRight.PUT,
                    strike=170.0,
                    expiry=date.today() - timedelta(days=offset_days),
                    dte=30,
                    signals={
                        "blended_score": score,
                        "iv_rank": 50.0 + i,
                        "delta": 0.25,
                        "vrp": 3.0,
                        "prob_otm": 0.7,
                        "roc_pct": 2.0,
                        "scores": {
                            "iv": score,
                            "technical": score - 5,
                            "fundamental": score - 10,
                            "liquidity": score + 5,
                            "assignment_safety": score,
                            "sentiment": score - 2,
                        },
                    },
                    claude_recommendation="sell" if win else "skip",
                    claude_priority=1,
                    claude_confidence=0.7,
                    claude_rationale="because",
                    baseline_recommendation="sell",
                    baseline_rank=1,
                    baseline_score=score,
                    agreement=win,
                    outcome=(
                        VerdictOutcome.EXPIRED_WORTHLESS if win else VerdictOutcome.ASSIGNED
                    ),
                    outcome_date=date.today() - timedelta(days=offset_days),
                    realized_pnl=150.0 if win else -50.0,
                    filled=True,
                )
            )
        record_verdicts(records)

    return _seed
```

Note: needs `from datetime import date, timedelta` already imported at module scope in
`tests/conftest.py` (it is).

- [x] **Step 5: Implement `src/api/routers/pnl.py`.** Add imports:

```python
from src.claude.eval.ledger import load_records
from src.claude.eval.score_metrics import score_outcome_report
```

and extend the `src.api.models.pnl` / `src.common.schemas` import lines with
`SystemPerformanceResponse, VerdictAgreement` and `VerdictRecord` respectively. Append at the end
of the file:

```python
def _win_rate(records: list[VerdictRecord]) -> float | None:
    """Fraction with positive realized P&L. None with nothing to rate — never 0.0."""
    if not records:
        return None
    wins = sum(1 for r in records if (r.realized_pnl or 0.0) > 0)
    return round(wins / len(records), 4)


def _verdict_agreement(*, since: date | None, until: date | None) -> VerdictAgreement:
    """Claude-vs-baseline agreement over the same closed, since/until-windowed population
    the report windows by outcome_date. Reads the `agreement` flag scan.py already computed
    on each ledger row — never recomputed here.
    """
    records = load_records(closed_only=True)
    if since is not None:
        records = [r for r in records if r.outcome_date and r.outcome_date >= since]
    if until is not None:
        records = [r for r in records if r.outcome_date and r.outcome_date <= until]
    if not records:
        return VerdictAgreement(n_closed=0, n_agreed=0)
    n_agreed = sum(1 for r in records if r.agreement)
    return VerdictAgreement(
        n_closed=len(records),
        n_agreed=n_agreed,
        agreement_rate=round(n_agreed / len(records), 4),
        claude_win_rate=_win_rate([r for r in records if r.claude_recommendation == "sell"]),
        baseline_win_rate=_win_rate([r for r in records if r.baseline_recommendation == "sell"]),
    )


@router.get("/system", response_model=SystemPerformanceResponse)
def pnl_system(
    user: OwnerUser,  # noqa: ARG001
    since: date | None = None,
    until: date | None = None,
) -> SystemPerformanceResponse:
    """The score-vs-outcome evidence's human reader (P3-P4 M6 Task 6.1).

    Reads behind the fence CLAUDE.md draws around src/claude/eval/: this is the one route in
    the phase where that is the intended use, not a breach — score_outcome_report's own notes
    already say the weights must be re-derived by hand, and this route only renders them. It
    calls score_outcome_report and returns exactly what it gets: no bucket recomputed, no
    correlation re-derived, no note filtered. verdict_ledger and scoring_weights.yaml are
    read-only from here — tests/test_web_fence.py (Task 6.3) asserts no module under src/api/
    can write either.
    """
    report = score_outcome_report(since=since, until=until)
    agreement = _verdict_agreement(since=since, until=until)
    return SystemPerformanceResponse(
        as_of=datetime.now(UTC),
        report=report,
        agreement=agreement,
        since=since,
        until=until,
    )
```

- [x] **Step 6: Run the gate.** `python -m pytest tests/test_api_pnl_system.py -v` (all pass),
  then `python -m pytest -q`, `ruff check .`, `mypy src`.

- [x] **Step 7: `docs/web/api.md`.** Append a `### GET /pnl/system` section after the existing
  `### GET /pnl/ledger.csv` section, inside `## P&L (P4 Milestone 5)` — stating the fence
  rationale (why reading here is intended use, not a breach) and the response shape. Content:

  > The score-vs-outcome evidence's human reader — the one P&L route that reads behind the
  > `src/claude/eval/` fence, and the reason is written down here because `CLAUDE.md` requires
  > it: everything `eval/` produces "is read by a human, never auto-applied," and a browser page
  > is exactly that human reader, a better one than `scripts/evaluate_scores.py`. Nothing here
  > closes the loop — the route is a `GET`, the API's only writable table is `app_commands`, and
  > no command kind touches a scoring weight (`tests/test_web_fence.py`, Task 6.3).
  >
  > The route calls `score_outcome_report(since=since, until=until)` and returns exactly what it
  > gets — no bucket recomputed, no correlation re-derived, no note filtered or truncated. Its
  > own `notes` carry, verbatim, "Read-only: re-derive `scoring_weights.yaml` from this evidence
  > by hand (the fence forbids any automatic feedback into the engine)" — the most important
  > sentence on the page, and not the UI's to paraphrase.
  >
  > **Response — `SystemPerformanceResponse`:** `{ as_of, report: ScoreOutcomeReport, agreement: VerdictAgreement, since, until }`.
  > `ScoreOutcomeReport`: `{ n_closed, period_start, period_end, blended_score_buckets: ScoreBucket[], component_buckets: ScoreBucket[], signal_correlations: SignalCorrelation[], notes: string[] }`.
  > `ScoreBucket`: `{ label, n, win_rate, mean_pnl, total_pnl }`. `SignalCorrelation`: `{ signal, n, pearson_r, low_half_mean_pnl, high_half_mean_pnl }`.
  > `VerdictAgreement`: `{ n_closed, n_agreed, agreement_rate, claude_win_rate, baseline_win_rate }`.
  >
  > `agreement` is computed here, beside the report, from
  > `src/claude/eval/ledger.py::load_records(closed_only=True)`, windowed by the same
  > `since`/`until` on `outcome_date` the report uses — `agreement_rate` is `null` with zero
  > closed rows in the window, never `0.0`, matching every other rate in this phase. With no
  > closed trades, the response is the report's own empty case (`n_closed: 0` plus its own
  > "nothing to correlate yet" note) — never a `404` or a hand-written empty message. Owner-only.

- [x] **Step 8: Regenerate `docs/web/openapi.json`.**
  `python -c "import json; from src.api.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json`.
  Leave `web/lib/api-types.ts` for Task 6.2 (needs a live server; do both together).

- [x] **Step 9: Commit.** `git add src/api/models/pnl.py src/api/routers/pnl.py tests/conftest.py tests/test_api_pnl_system.py docs/web/api.md docs/web/openapi.json`.

---

### Task 6.2 — The system performance surface

**Files:**
- Create: `web/components/pnl/SystemPanel.tsx`, `web/components/pnl/ScoreBucketTable.tsx`,
  `web/components/pnl/CorrelationTable.tsx`
- Create: `web/components/pnl/SystemPanel.test.tsx`
- Modify: `web/components/pnl/types.ts` (new type aliases)
- Modify: `web/components/pnl/PnlShell.tsx` (third tab — not in the milestone's literal file
  list, but required for the surface to have a reader at all: an unmounted component is not "the
  score-vs-outcome evidence gets a reader")
- Modify: `web/lib/api-types.ts` (regenerate — needs a live server, see Step 0)
- Modify: `web/CLAUDE.md` (pnl/ component-inventory bullet, per this repo's own "new frontend
  components → web/CLAUDE.md layout section" rule)

**Interfaces:** consumes `GET /pnl/system`. Uses `Money` (`@/components/portfolio/Money`),
`UNKNOWN` (`@/lib/format`).

```ts
// web/components/pnl/types.ts additions
export type SystemPerformanceResponse = components["schemas"]["SystemPerformanceResponse"];
export type ScoreOutcomeReportData = components["schemas"]["ScoreOutcomeReport"];
export type ScoreBucketData = components["schemas"]["ScoreBucket"];
export type SignalCorrelationData = components["schemas"]["SignalCorrelation"];
export type VerdictAgreementData = components["schemas"]["VerdictAgreement"];
```

**Design decision — presentational, not self-fetching.** Unlike `SummaryPanel` (self-fetches via
`useQuery`), `SystemPanel` takes `data: SystemPerformanceResponse` as a prop, matching
`EquityChart`'s convention and the test file's own `render(<SystemPanel data={aReport()} />)`
calls (no `QueryClientProvider`, no `renderWithQuery`). `PnlShell` owns the `useQuery` call and
the since/until window state, exactly as it owns the equity/ledger fetches.

- [x] **Step 0: Regenerate `docs/web/openapi.json` (already done in 6.1) and `web/lib/api-types.ts`.**
  Start the API against a throwaway DB, run `gen:api`, stop it:

```bash
API_TOKEN=devtoken WEB_API_TOKEN=devtoken python -m scripts.run_api &
API_PID=$!
sleep 2
cd web && npm run gen:api
cd ..
kill $API_PID
```

  (Check `scripts/run_api.py` / `.env` for the actual token env var name and DB path before
  running — do not point it at a real trading DB. Confirm `git diff web/lib/api-types.ts` shows
  the five new `SystemPerformanceResponse`/`ScoreOutcomeReport`/`ScoreBucket`/`SignalCorrelation`/
  `VerdictAgreement` schemas and nothing else changed.)

- [x] **Step 1: Add the type aliases to `web/components/pnl/types.ts`** (block above).

- [x] **Step 2: Write the failing tests — `web/components/pnl/SystemPanel.test.tsx`.**

```tsx
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SystemPanel } from "./SystemPanel";
import type {
  ScoreBucketData,
  SignalCorrelationData,
  SystemPerformanceResponse,
  VerdictAgreementData,
} from "./types";

const ISO = new Date().toISOString();
const READONLY_NOTE =
  "Read-only: re-derive scoring_weights.yaml from this evidence by hand (the fence " +
  "forbids any automatic feedback into the engine).";
const CLOSED_ONLY_NOTE =
  "Closed (executed+settled) trades only — rejected/unfilled candidates carry no P&L.";

function aBucket(overrides: Partial<ScoreBucketData> = {}): ScoreBucketData {
  return { label: "70-80", n: 12, win_rate: 0.6, mean_pnl: 45.5, total_pnl: 546, ...overrides };
}

function aCorrelation(overrides: Partial<SignalCorrelationData> = {}): SignalCorrelationData {
  return {
    signal: "blended_score",
    n: 12,
    pearson_r: 0.32,
    low_half_mean_pnl: 10,
    high_half_mean_pnl: 60,
    ...overrides,
  };
}

function anAgreement(overrides: Partial<VerdictAgreementData> = {}): VerdictAgreementData {
  return {
    n_closed: 12,
    n_agreed: 9,
    agreement_rate: 0.75,
    claude_win_rate: 0.7,
    baseline_win_rate: 0.6,
    ...overrides,
  };
}

function aReport(overrides: Partial<SystemPerformanceResponse> = {}): SystemPerformanceResponse {
  const base: SystemPerformanceResponse = {
    as_of: ISO,
    since: null,
    until: null,
    report: {
      n_closed: 12,
      period_start: null,
      period_end: null,
      blended_score_buckets: [aBucket()],
      component_buckets: [aBucket({ label: "iv:high" })],
      signal_correlations: [aCorrelation()],
      notes: [CLOSED_ONLY_NOTE, READONLY_NOTE],
    },
    agreement: anAgreement(),
  };
  return { ...base, ...overrides };
}

function emptyReport(): SystemPerformanceResponse {
  return {
    as_of: ISO,
    since: null,
    until: null,
    report: {
      n_closed: 0,
      period_start: null,
      period_end: null,
      blended_score_buckets: [],
      component_buckets: [],
      signal_correlations: [],
      notes: [CLOSED_ONLY_NOTE, READONLY_NOTE, "No closed trades in window — nothing to correlate yet."],
    },
    agreement: { n_closed: 0, n_agreed: 0, agreement_rate: null, claude_win_rate: null, baseline_win_rate: null },
  };
}

function reportWithBucket(overrides: Partial<ScoreBucketData>): SystemPerformanceResponse {
  const base = aReport();
  return { ...base, report: { ...base.report, blended_score_buckets: [aBucket(overrides)] } };
}

describe("SystemPanel", () => {
  it("renders every note in full and in order", () => {
    render(<SystemPanel data={aReport()} />);
    const notes = aReport().report.notes;
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

  it("renders blended-score buckets as a table with label, n, win rate, mean and total P&L", () => {
    render(<SystemPanel data={aReport()} />);
    expect(screen.getByText("70-80")).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
  });

  it("renders component buckets in their own, separately labelled table", () => {
    render(<SystemPanel data={aReport()} />);
    expect(screen.getByText(/score components/i)).toBeInTheDocument();
    expect(screen.getByText("iv:high")).toBeInTheDocument();
  });

  it("renders a null pearson_r as n/a", () => {
    const base = aReport();
    render(
      <SystemPanel
        data={{
          ...base,
          report: {
            ...base.report,
            signal_correlations: [aCorrelation({ pearson_r: null })],
          },
        }}
      />,
    );
    expect(screen.getAllByText(/n\/a/i).length).toBeGreaterThan(0);
  });

  it("renders the agreement block with claude and baseline win rates side by side", () => {
    render(<SystemPanel data={aReport()} />);
    expect(screen.getByText("70%")).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
  });

  it("renders a null agreement_rate as n/a", () => {
    const base = aReport();
    render(
      <SystemPanel
        data={{ ...base, agreement: anAgreement({ agreement_rate: null }) }}
      />,
    );
    expect(screen.getAllByText(/n\/a/i).length).toBeGreaterThan(0);
  });
});
```

  (`screen.getByText("60%")` appears twice by design in the last two tests as written above —
  fix at implementation time by scoping with `within()` on the specific table/block if two `60%`
  strings collide in one render; adjust the test, not the component, if so — the component must
  not avoid a legitimate coincidence of rendered numbers.)

- [x] **Step 3: Confirm failure.** `cd web && npx vitest run components/pnl/SystemPanel.test.tsx`
  — fails (modules don't exist).

- [x] **Step 4: Implement `ScoreBucketTable.tsx`.**

```tsx
"use client";

import { Money } from "@/components/portfolio/Money";
import type { ScoreBucketData } from "./types";

const SMALL_SAMPLE_THRESHOLD = 5;

/**
 * One score-vs-outcome bucket table (blended-score bands or per-component high/low split).
 * A bucket with n below SMALL_SAMPLE_THRESHOLD is labelled in words — a win rate from a
 * handful of trades is not evidence and must not read as one.
 */
export function ScoreBucketTable({ buckets, label }: { buckets: ScoreBucketData[]; label: string }) {
  if (buckets.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      <h3 className="text-xs uppercase tracking-wide text-muted">{label}</h3>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border text-left text-[10px] uppercase tracking-wide text-muted">
            <th className="px-2 py-1 font-normal">Band</th>
            <th className="px-2 py-1 font-normal">n</th>
            <th className="px-2 py-1 font-normal">Win rate</th>
            <th className="px-2 py-1 font-normal">Mean P&amp;L</th>
            <th className="px-2 py-1 font-normal">Total P&amp;L</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {buckets.map((b) => (
            <tr key={b.label}>
              <td className="px-2 py-1 font-mono text-content">{b.label}</td>
              <td className="px-2 py-1 tabular text-content">
                {b.n}
                {b.n < SMALL_SAMPLE_THRESHOLD && (
                  <span className="ml-1 text-[10px] uppercase tracking-wide text-unknown">
                    small sample
                  </span>
                )}
              </td>
              <td className="px-2 py-1 tabular text-content">{Math.round(b.win_rate * 100)}%</td>
              <td className="px-2 py-1 tabular">
                <Money value={b.mean_pnl} kind="realized" signed />
              </td>
              <td className="px-2 py-1 tabular">
                <Money value={b.total_pnl} kind="realized" signed />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [x] **Step 5: Implement `CorrelationTable.tsx`.**

```tsx
"use client";

import { Money } from "@/components/portfolio/Money";
import { UNKNOWN } from "@/lib/format";
import type { SignalCorrelationData } from "./types";

/** How each signal relates to realized P&L. `pearson_r`/the half-splits render n/a when undefined
 * (n<2 or zero variance) — never a fabricated 0. */
export function CorrelationTable({ correlations }: { correlations: SignalCorrelationData[] }) {
  if (correlations.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      <h3 className="text-xs uppercase tracking-wide text-muted">Signal correlations</h3>
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border text-left text-[10px] uppercase tracking-wide text-muted">
            <th className="px-2 py-1 font-normal">Signal</th>
            <th className="px-2 py-1 font-normal">n</th>
            <th className="px-2 py-1 font-normal">Pearson r</th>
            <th className="px-2 py-1 font-normal">Low-half mean P&amp;L</th>
            <th className="px-2 py-1 font-normal">High-half mean P&amp;L</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {correlations.map((c) => (
            <tr key={c.signal}>
              <td className="px-2 py-1 font-mono text-content">{c.signal}</td>
              <td className="px-2 py-1 tabular text-content">{c.n}</td>
              <td className="px-2 py-1 tabular">
                {c.pearson_r == null ? (
                  <span className="hatch text-unknown">{UNKNOWN}</span>
                ) : (
                  c.pearson_r.toFixed(2)
                )}
              </td>
              <td className="px-2 py-1 tabular">
                {c.low_half_mean_pnl == null ? (
                  <span className="hatch text-unknown">{UNKNOWN}</span>
                ) : (
                  <Money value={c.low_half_mean_pnl} kind="realized" signed />
                )}
              </td>
              <td className="px-2 py-1 tabular">
                {c.high_half_mean_pnl == null ? (
                  <span className="hatch text-unknown">{UNKNOWN}</span>
                ) : (
                  <Money value={c.high_half_mean_pnl} kind="realized" signed />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [x] **Step 6: Implement `SystemPanel.tsx`.**

```tsx
"use client";

import { UNKNOWN } from "@/lib/format";
import { CorrelationTable } from "./CorrelationTable";
import { ScoreBucketTable } from "./ScoreBucketTable";
import type { SystemPerformanceResponse, VerdictAgreementData } from "./types";

/**
 * The score-vs-outcome evidence's reader (P3-P4 M6 Task 6.2) — the human `CLAUDE.md` says must
 * re-derive scoring_weights.yaml by hand from this evidence. Every note score_outcome_report
 * produces renders here in full and in order (the read-only sentence is why this surface is
 * allowed to exist at all); the panel offers no control that could change a weight — no apply
 * button, no suggested weight, no editable field, only the since/until window.
 */
export function SystemPanel({
  data,
  since,
  until,
  onSinceChange,
  onUntilChange,
}: {
  data: SystemPerformanceResponse;
  since?: string;
  until?: string;
  onSinceChange?: (value: string) => void;
  onUntilChange?: (value: string) => void;
}) {
  const { report, agreement } = data;

  return (
    <div className="space-y-5" data-testid="system-panel">
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1 text-xs text-muted">
          Since
          <input
            type="date"
            data-role="window-control"
            aria-label="since"
            value={since ?? ""}
            onChange={(e) => onSinceChange?.(e.target.value)}
            className="rounded border border-border bg-surface px-2 py-1 text-xs text-content"
          />
        </label>
        <label className="flex items-center gap-1 text-xs text-muted">
          Until
          <input
            type="date"
            data-role="window-control"
            aria-label="until"
            value={until ?? ""}
            onChange={(e) => onUntilChange?.(e.target.value)}
            className="rounded border border-border bg-surface px-2 py-1 text-xs text-content"
          />
        </label>
      </div>

      <ul className="space-y-1 text-xs text-muted">
        {report.notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>

      <AgreementBlock agreement={agreement} />

      {report.n_closed > 0 && (
        <>
          <ScoreBucketTable buckets={report.blended_score_buckets} label="Blended score" />
          <ScoreBucketTable buckets={report.component_buckets} label="Score components" />
          <CorrelationTable correlations={report.signal_correlations} />
        </>
      )}
    </div>
  );
}

function AgreementBlock({ agreement }: { agreement: VerdictAgreementData }) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4" data-testid="agreement-block">
      <Headline label="Verdicts agreed">
        <Rate value={agreement.agreement_rate} />
      </Headline>
      <Headline label="Claude win rate">
        <Rate value={agreement.claude_win_rate} />
      </Headline>
      <Headline label="Baseline win rate">
        <Rate value={agreement.baseline_win_rate} />
      </Headline>
      <Headline label="Closed trades compared">
        <span className="tabular text-content">{agreement.n_closed}</span>
      </Headline>
    </div>
  );
}

function Rate({ value }: { value: number | null | undefined }) {
  if (value == null) {
    return <span className="tabular hatch text-unknown">{UNKNOWN}</span>;
  }
  return <span className="tabular text-content">{Math.round(value * 100)}%</span>;
}

function Headline({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-xs text-muted">{label}</span>
      {children}
    </div>
  );
}
```

- [x] **Step 7: Run the component tests.**
  `cd web && npx vitest run components/pnl/SystemPanel.test.tsx` — all pass. Fix any text
  collisions (e.g. two `60%` strings) by scoping assertions with `within(container)` on the
  specific block, per the note in Step 2 — never by changing the component to avoid a legitimate
  coincidence.

- [x] **Step 8: Wire the tab into `PnlShell.tsx`.** Add `"system"` to the `Tab` union and `TABS`
  array (`{ key: "system", label: "System" }`), add `since`/`until` state, a `useQuery` for
  `/pnl/system`, and a `tab === "system"` render block:

```tsx
// additions to PnlShell.tsx
import { SystemPanel } from "./SystemPanel";
import type { SystemPerformanceResponse } from "./types";

// inside PnlShell():
const [systemWindow, setSystemWindow] = useState<{ since: string; until: string }>({
  since: "",
  until: "",
});
const systemQs = new URLSearchParams();
if (systemWindow.since) systemQs.set("since", systemWindow.since);
if (systemWindow.until) systemQs.set("until", systemWindow.until);

const system = useQuery({
  queryKey: ["pnl", "system", systemWindow.since, systemWindow.until],
  queryFn: () => apiFetch<SystemPerformanceResponse>(`/pnl/system?${systemQs.toString()}`),
  placeholderData: (prev) => prev,
  refetchInterval: 30_000,
});

// TABS gains: { key: "system", label: "System" }

// render block, alongside the existing tab === "ledger" / "equity" blocks:
{tab === "system" && (
  <section data-testid="pnl-system-section">
    {system.isLoading ? (
      <p className="text-sm text-muted">Loading the system performance report</p>
    ) : system.isError ? (
      <p className="text-sm text-muted">Could not load the system performance report.</p>
    ) : system.data ? (
      <SystemPanel
        data={system.data}
        since={systemWindow.since}
        until={systemWindow.until}
        onSinceChange={(v) => setSystemWindow((w) => ({ ...w, since: v }))}
        onUntilChange={(v) => setSystemWindow((w) => ({ ...w, until: v }))}
      />
    ) : null}
  </section>
)}
```

  `Tab` type becomes `"ledger" | "equity" | "system"`.

- [x] **Step 9: Run the full frontend gate.**
  `cd web && npx vitest run && npm run lint && npm run build`.

- [x] **Step 10: Update `web/CLAUDE.md`'s `components/pnl/` bullet** in the layout table to add
  `SystemPanel` (fetched by `PnlShell`'s third tab, since/until window state owned by the shell,
  panel itself presentational), `ScoreBucketTable` (small-sample labelling below n=5), and
  `CorrelationTable` (null `pearson_r`/half-splits render n/a). Update the `PnlShell` bullet's
  `app/pnl/` description in the same file to mention the third "System" tab. Update the
  `app/pnl/` line under `app/` too if it names only Ledger/Equity curve tabs.

- [x] **Step 11: Commit.**
  `git add web/components/pnl/{SystemPanel,ScoreBucketTable,CorrelationTable,SystemPanel.test}.tsx web/components/pnl/{types,PnlShell}.tsx web/lib/api-types.ts web/CLAUDE.md`.

---

### Task 6.3 — Fence test extensions

**Files:** Modify `tests/test_web_fence.py`, root `CLAUDE.md`.

- [x] **Step 1: Add the tests below to `tests/test_web_fence.py`, at the end of the file.** The
  milestone's literal `test_the_api_still_writes_exactly_one_table` skips only `commands.py`;
  `src/api/trading_db.py` **defines** `get_command_engine`/`command_session` (it is the module
  the docstring at the top of `test_only_the_command_module_holds_a_write_handle`, line ~104,
  already excludes for exactly this reason), so the literal test as given would false-positive
  there. Add `trading_db.py` to the skip set too — this mirrors the existing P2 test's allowed
  set exactly, it is not a relaxation of the invariant (record this as a ruling in the Task 6.4
  log, not silently).

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
    skip = {"commands.py", "trading_db.py"}  # trading_db.py DEFINES the write handle (P2 test above)
    for path in Path("src/api").rglob("*.py"):
        if path.name in skip:
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

- [x] **Step 2: Run them.**
  `python -m pytest tests/test_web_fence.py -v`. Pre-verified during planning: no file under
  `src/api/` currently contains `record_verdicts`/`update_outcome`/`mark_filled`/
  `VerdictLedgerRow(`/`scoring_weights`, and `save_portfolio_snapshot`'s only two callers outside
  `portfolio_snapshots.py` are already `src/monitor/intraday.py` and
  `src/notify/command_drain.py` — every test is expected to pass immediately. **If any of them
  fails for a reason other than the `trading_db.py` exclusion above, that is a real finding**:
  stop and investigate the offending module before touching the assertion, per the milestone's
  own instruction.

- [x] **Step 3:** `python -m pytest -q`, `ruff check .`, `mypy src`.

- [x] **Step 4: Root `CLAUDE.md`.** In "## The web layer and the trading database" section, add
  one sentence after the existing paragraph: P3 and P4 added no write beyond the `refresh`
  command (Task 1.4), and the API still writes exactly one table
  (`tests/test_web_fence.py::test_the_api_still_writes_exactly_one_table`).

- [x] **Step 5: Commit.** `git add tests/test_web_fence.py CLAUDE.md`.

---

### Task 6.4 — Close out P3 and P4

**This is a verification pass — re-derive every item below by actually running its check before
writing a word of prose about it.** Prior research during planning found most items already
correct (documented below per item); still run the check live, since state may have drifted.

**Files:** `STATUS.md`, `README.md`, `ARCHITECTURE.md`, `CLAUDE.md`, `docs/web/architecture.md`,
`docs/web/commands.md`, `Web plan/P3-P4-IMPLEMENTATION-PLAN.md`, `Web plan/milestones/P3-P4/M6-system-performance.md`.

- [x] **Step 1: Re-derive, do not re-assert.**

```bash
grep -c "^### " docs/web/api.md
python -c "import json; from src.api.main import create_app; \
print('\n'.join(sorted(create_app().openapi()['paths'])))"

grep -oE 'CommandFailed\("[a-z_]+"|_fail\([^,]+, "[a-z_]+"' src/notify/command_drain.py

python -c "import json; from src.api.main import create_app; \
print(json.dumps(create_app().openapi(), indent=2))" > /tmp/openapi.json
diff /tmp/openapi.json docs/web/openapi.json && echo "openapi current"
cd web && npm run gen:api && git diff --exit-code lib/api-types.ts && echo "types current"
```

  Record the actual output of each command in the implementation log (Step 7), not a summary of
  what was expected.

- [x] **Step 2: `STATUS.md`'s web platform table.** Extend the `P4 — Profitability tracker` row's
  heading to add `; M6 — system performance and close-out — built <date>` and append a dense
  paragraph in the same style as the M4/M5 paragraphs already there, describing Task 6.1
  (`/pnl/system`, the fence rationale), 6.2 (the panel + tab), and 6.3 (the five fence tests). Add
  a **"Not built"** sentence to the row (none exists yet in either the P3 or P4 row — confirmed
  during planning) naming exactly: P5 (mobile), operator notes on legs and campaigns, a
  materialised P&L table, intraday equity history beyond the snapshot retention window, and any
  Tailscale or remote hosting. State plainly that the ledger's numbers have not been reconciled
  against a broker statement.

- [x] **Step 3: Root `CLAUDE.md` — confirm, don't duplicate.** The analytics-tier section
  already names `src/reporting/` as the third tier (from M4) — confirm this, do not re-add it.
  Confirm the web-layer section carries Task 6.3's sentence (added in 6.3 Step 4). Add one new
  doc-update trigger row to the table near the top of the file: "New module under
  `src/reporting/` → `ARCHITECTURE.md` folder guide · root `CLAUDE.md` analytics-tier section".

- [x] **Step 4: `README.md`'s layout table.** Confirmed during planning: rows for `src/reporting/`
  (line ~518), `src/storage/portfolio_snapshots.py` (in the `src/storage/` row), `src/api/portfolio_source.py`
  and `src/api/routers/{portfolio,pnl}.py` (in the `src/api/` row), `src/common/assignment_risk.py`
  (in the `src/common/` row), and `web/app/portfolio/`/`web/app/pnl/` (in the `web/` row) all
  already exist. Re-run `grep` for each to confirm still true as of this pass; add whatever is
  actually found missing (expected: nothing).

- [x] **Step 5: `ARCHITECTURE.md`.** Confirmed during planning: `src/monitor/intraday.py`'s entry
  (line ~252) already documents `_maybe_write_snapshot`; `src/notify/command_drain.py`'s entry
  (line ~218) already documents the `refresh`/`_refresh` handler; `src/claude/eval/reconcile.py`'s
  entry (line ~185) already documents the accounting-rule move to `src/reporting/legs.py`.
  Re-read each during this pass to confirm still accurate; fix only what has actually drifted.

- [x] **Step 6: Tick checkboxes.** Confirmed during planning: `M2`-`M5` milestone files are
  already fully ticked; `M1` is fully ticked; `M0-baseline-and-fixes.md` is out of this task's
  literal file scope (six files means M1-M6) and is a pre-existing gap — note it as a deferred
  finding in the log rather than silently fixing or silently ignoring it. Tick all of `M6`'s own
  checkboxes (this plan's tasks 6.1-6.4) as they complete, plus its acceptance list at the
  bottom. Confirm `Web plan/P3-P4-IMPLEMENTATION-PLAN.md` has no stray unticked boxes (confirmed
  none during planning).

- [x] **Step 7: Write the implementation log** at the foot of `Web plan/P3-P4-IMPLEMENTATION-PLAN.md`,
  in the shape `Web plan/P2-IMPLEMENTATION-PLAN.md`'s "## Implementation log — M7" section uses:
  a one-paragraph intro, "### What each task shipped" (one paragraph per task, 6.1-6.4), "### What
  was escalated" (or "none" if truly clean), "### Every ruling made along the way" (numbered —
  must include the `trading_db.py` fence-test-exclusion ruling from Task 6.3, and the M0
  checkbox-scope ruling from Step 6), "### Minor findings deferred, not fixed", and "### Final
  gate (<date>)" with the actual six command outputs.

- [x] **Step 8: Run all six gate commands, record the numbers in the log, and commit.**

```bash
python -m pytest -q
ruff check .
mypy src
cd web && npx vitest run
npm run lint
npm run build
```

---

## Milestone 6 acceptance

- [x] `/pnl/system` renders the score-vs-outcome report and the verdict agreement, read-only.
- [x] Every note the report produces appears on the page in full and in order, including the
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
