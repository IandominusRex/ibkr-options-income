# Milestone 5 — P&L surfaces

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The operator can open `/pnl`, read every trade the system has opened and closed, see what
it earned, watch the equity curve, and take the whole thing to a spreadsheet.

**Spec:** `Web plan/P3-P4-design.md` §7.1-7.4 and §9. **Index:**
`Web plan/P3-P4-IMPLEMENTATION-PLAN.md`. **Depends on:** Milestone 4.

**The shape of this milestone in one sentence:** every route here is a thin renderer over
`src/reporting/` — if a route computes a P&L figure of its own, the single-accounting-rule
invariant Milestone 4 established has already been broken.

---

## Task 5.1 — `GET /pnl/ledger` and `GET /pnl/summary` `[SONNET]`

**The first `/pnl` routes. Sets the pattern for 5.2 and 5.3.**

**Files:** Create `src/api/routers/pnl.py`, `src/api/models/pnl.py`. Modify `src/api/main.py`,
`docs/web/api.md`. Test `tests/test_api_pnl_ledger.py`.

**Interfaces:**

```python
# src/api/models/pnl.py
class LedgerFilters(BaseModel):
    """Echoed back on every response so the client can prove what it is looking at."""

    symbol: str | None = None
    strategy: str | None = None
    outcome: str | None = None
    since: date | None = None
    until: date | None = None
    book: Literal["paper", "live", "all"] = "all"


class LedgerResponse(Envelope):
    filters: LedgerFilters
    campaigns: list[CampaignPnl]
    marks_as_of: datetime | None # the snapshot backing every unrealised figure; None when absent
    n_legs: int                  # every leg, across every campaign; the client checks the sum


class SummaryResponse(Envelope):
    filters: LedgerFilters
    summary: PnlSummary
    marks_as_of: datetime | None
```

Consumes: `build_legs`, `build_campaigns`, `build_summary` (M4), `read_portfolio` (M1 Task 1.5),
`OwnerUser` and `TradingDb`.

**Design points that are not negotiable:**

1. **`book` defaults to `"all"` on the ledger and is *required to be explicit* on the summary.**
   `build_summary` raises on a mixed list (M4 Task 4.5). So `/pnl/summary` with `book=all` and both
   kinds of fill present must return **two summaries or a `422`**, never a mixed total. Choose the
   `422` with a reason naming the problem: `{"reason": "mixed_book", "detail": "..."}`. The ledger
   may list both; only the total is refused.
2. **Marks come from `read_portfolio`, not a second query.** `marks_as_of` is that reading's
   `as_of`, so the ledger's unrealised figures and the portfolio page's agree by construction.
   When the reading is the `none` rung, pass `snapshot=None` into `build_campaigns` and return
   `marks_as_of: null`.
3. **Filters are echoed back.** A client that sent `since` and got a full history has a bug it
   cannot see otherwise.
4. **Both routes are `owner_only`.**
5. **`as_of` is request time here**, because the ledger is computed on read. `marks_as_of` is the
   snapshot time, coerced through `as_utc_opt` (M0 Task 0.9) like every other stored timestamp.
   Two different fields, both present, documented as different.

Required behaviours, each with a test:
- An empty database returns `campaigns: []`, `n_legs: 0`, and a valid envelope.
- A seeded wheel returns its campaign with its legs.
- `symbol`, `strategy`, `outcome`, `since` and `until` each filter, one test apiece.
- **`book=all` on `/pnl/summary` with both paper and live fills returns `422` with
  `reason: "mixed_book"`.** Its own test — this is where M4's `ValueError` becomes a user-facing
  answer instead of a 500.
- `book=paper` and `book=live` each return a summary, and their `realized_total` values differ.
- With no snapshot, `marks_as_of` is `null` and every `option_unrealized` is `null`.
- With a snapshot, `marks_as_of` equals the snapshot's `captured_at`.
- Filters are echoed back unchanged.
- **`n_legs` equals the sum of every campaign's leg count.** Its own test: M4 Task 4.4 guarantees
  every leg lands in exactly one thread, including the synthetic ones, and this is where that
  guarantee is checked at the boundary the client actually reads.
- A non-owner gets `403` on both routes.

- [ ] **Step 1: Write the failing test**

```python
def test_a_mixed_book_summary_is_refused_not_totalled(client, seed_leg) -> None:
    """M4's ValueError becomes an answer here, never a 500 and never a wrong number."""
    seed_leg(candidate_id="p1", sold=(1, 1.0), is_live=False, expiry_in_days=-1)
    seed_leg(candidate_id="l1", sold=(1, 1.0), is_live=True, expiry_in_days=-1)

    r = client.get("/pnl/summary?book=all", headers=OWNER)
    assert r.status_code == 422
    assert r.json()["detail"]["reason"] == "mixed_book"

    paper = client.get("/pnl/summary?book=paper", headers=OWNER).json()["summary"]
    live = client.get("/pnl/summary?book=live", headers=OWNER).json()["summary"]
    assert paper["realized_total"] != live["realized_total"]


def test_marks_come_from_the_same_snapshot_the_portfolio_renders(client, seed_leg,
                                                                 seed_portfolio_snapshot) -> None:
    when = datetime.now(UTC) - timedelta(minutes=5)
    seed_portfolio_snapshot(captured_at=when)
    seed_leg(candidate_id="c1", sold=(1, 1.5), expiry_in_days=30)

    ledger = client.get("/pnl/ledger", headers=OWNER).json()
    portfolio = client.get("/portfolio/summary", headers=OWNER).json()
    assert ledger["marks_as_of"] == portfolio["as_of"]


def test_no_snapshot_means_null_marks_not_zero_marks(client, seed_leg) -> None:
    seed_leg(candidate_id="c1", sold=(1, 1.5), expiry_in_days=30)
    body = client.get("/pnl/ledger", headers=OWNER).json()
    assert body["marks_as_of"] is None
    assert all(c["option_unrealized"] is None for c in body["campaigns"])


def test_filters_are_echoed_back(client) -> None:
    body = client.get("/pnl/ledger?symbol=NVDA&book=paper", headers=OWNER).json()
    assert body["filters"]["symbol"] == "NVDA"
    assert body["filters"]["book"] == "paper"
```

- [ ] **Step 2: Confirm failure. Step 3: Implement. Step 4: Gate. Step 5:** `docs/web/api.md`,
  documenting the `as_of` versus `marks_as_of` distinction explicitly. **Commit.**

---

## Task 5.2 — `GET /pnl/equity` `[GLM]`

**Files:** Modify `src/api/routers/pnl.py`, `src/api/models/pnl.py`, `docs/web/api.md`. Test
`tests/test_api_pnl_equity.py`.

**Interfaces:**

```python
class EquityResponse(Envelope):
    filters: LedgerFilters
    curve: EquityCurve
```

Consumes: `equity_curve` and `build_legs` (M4), the same `book` filter Task 5.1 defined.

**Design points:**

1. **The route computes nothing.** It calls `build_legs`, passes the result to `equity_curve`, and
   returns it. If you write a loop over journal rows in the router, you are reimplementing M4.
2. `gaps` and `starts_at` pass through untouched.
3. `book=all` is fine here — the curve's `cumulative_realized` sums `net_pnl`, and mixing books in
   a *curve* is a display choice the client makes, unlike a headline total. Document the asymmetry
   with Task 5.1 so a later reader does not "fix" one to match the other.
4. `owner_only`.

Required behaviours, each with a test:
- No journal rows returns `points: []`, `gaps: []`, `starts_at: null`, status `200`.
- Three journal days with one missing trading day between them returns that day in `gaps`.
- `starts_at` is the first point's date.
- `since` trims leading points and moves `starts_at`.
- Every point carries `premium_cashflow`, and no field anywhere in the response is named
  `realized_pnl`. Its own test.
- A non-owner gets `403`.

- [ ] **Step 1: Write the failing tests. Step 2: Confirm failure. Step 3: Implement. Step 4:
  Gate. Step 5:** `docs/web/api.md`, **commit.**

---

## Task 5.3 — `GET /pnl/ledger.csv` and the proxy header allowlist `[SONNET]`

**Touches the P2 security boundary.** `web/app/api/[...path]/route.ts` is the reason the bearer
token is not in the browser bundle. Change it carefully and change only what this task needs.

**Files:** Modify `src/api/routers/pnl.py`, `web/app/api/[...path]/route.ts`, `docs/web/api.md`,
`web/CLAUDE.md`. Test `tests/test_api_pnl_csv.py`, `web/app/api/[...path]/route.test.ts`.

**Context.** The proxy currently forwards exactly one response header:

```typescript
const contentType = upstream.headers.get("Content-Type");
if (contentType) { headers.set("Content-Type", contentType); }
```

So a `text/csv` body arrives with the right type and **no filename**, and the browser saves it as
`ledger.csv` only by luck of the URL. The fix is to add `Content-Disposition` to a small explicit
allowlist — not to forward every header, which would leak upstream server details the client has no
business seeing.

**Interfaces:**

```python
# src/api/routers/pnl.py
@router.get("/ledger.csv", response_class=Response)
def ledger_csv(user: OwnerUser, db: TradingDb, ...) -> Response:
    """The same rows /pnl/ledger returns, under the same filters, as CSV.

    Content-Type: text/csv; charset=utf-8
    Content-Disposition: attachment; filename="pnl-ledger-YYYY-MM-DD.csv"
    """
```

```typescript
// web/app/api/[...path]/route.ts
const FORWARDED_RESPONSE_HEADERS = ["Content-Type", "Content-Disposition"] as const;
```

**Design points that are not negotiable:**

1. **An explicit allowlist, not a passthrough.** Two names. Adding a third is a separate decision
   with its own reason.
2. **The CSV is built from the same `build_legs` call the JSON route uses**, with the same filters.
   A second query would let the two drift.
3. **`None` serialises as an empty cell, never as `0`.** A spreadsheet reading `0` where the value
   was unknown is the same lie as `$0.00` on the page, and it is harder to spot.
4. **The header row names the units.** `credit_usd`, `debit_usd`, `net_pnl_usd`, `roc_pct`,
   `days_held`. A column called `credit` in a CSV is ambiguous once it leaves the app.
5. **`book` is a column**, so a paper row is identifiable after export. There is no mixed-book
   refusal here because a CSV has no headline total to be wrong.
6. `owner_only`, like every other route in this milestone.

Required behaviours, each with a test:
- The CSV's row count equals the JSON route's `n_legs` under the same filters.
- **An open leg's `net_pnl_usd` cell is empty, not `0`.** Its own test.
- The header row contains the unit-suffixed names.
- `Content-Disposition` is present with a dated filename.
- The `book` column distinguishes paper from live rows.
- A non-owner gets `403`.
- **Proxy:** a `text/csv` upstream response arrives at the client with both `Content-Type` and
  `Content-Disposition` intact.
- **Proxy:** an upstream header outside the allowlist (`Server`, `X-Powered-By`) is **not**
  forwarded. Its own test — the allowlist is the point, and a regression to a passthrough would
  pass every other test in this file.

- [ ] **Step 1: Write the failing tests**

```python
def test_an_open_legs_net_pnl_cell_is_empty_not_zero(client, seed_leg) -> None:
    """A zero in a spreadsheet is harder to spot than a zero on a page."""
    seed_leg(candidate_id="c1", sold=(1, 1.50), expiry_in_days=30)
    rows = list(csv.DictReader(io.StringIO(
        client.get("/pnl/ledger.csv", headers=OWNER).text
    )))
    assert rows[0]["net_pnl_usd"] == ""


def test_the_csv_row_count_matches_the_json_route(client, seed_wheel) -> None:
    seed_wheel()
    n_legs = client.get("/pnl/ledger", headers=OWNER).json()["n_legs"]
    rows = list(csv.DictReader(io.StringIO(
        client.get("/pnl/ledger.csv", headers=OWNER).text
    )))
    assert len(rows) == n_legs
```

```typescript
it("forwards Content-Disposition so a download keeps its filename", async () => {
  mockUpstream({ headers: { "Content-Type": "text/csv",
                            "Content-Disposition": 'attachment; filename="x.csv"' } });
  const res = await GET(req("/api/pnl/ledger.csv"), ctx);
  expect(res.headers.get("Content-Disposition")).toContain("x.csv");
});

it("does not forward headers outside the allowlist", async () => {
  mockUpstream({ headers: { "Content-Type": "text/csv", "Server": "uvicorn",
                            "X-Powered-By": "something" } });
  const res = await GET(req("/api/pnl/ledger.csv"), ctx);
  expect(res.headers.get("Server")).toBeNull();
  expect(res.headers.get("X-Powered-By")).toBeNull();
});
```

- [ ] **Step 2: Confirm failure. Step 3: Implement both sides.**

- [ ] **Step 4: Run all six gate commands.** The proxy has its own existing test file; every test
  in it must still pass.

- [ ] **Step 5:** `docs/web/api.md` documents the CSV route. `web/CLAUDE.md`'s "API proxy" section
  gains the allowlist and why it is an allowlist. **Commit.**

---

## Task 5.4 — The ledger table `[GLM]`

**Files:** Create `web/app/pnl/page.tsx`,
`web/components/pnl/{PnlShell,LedgerTable,CampaignRow,LegRow,LedgerFilters}.tsx`. Test
`web/components/pnl/{LedgerTable,LegRow}.test.tsx`.

**Interfaces:** consumes `GET /pnl/ledger`. Uses `Money` and `FreshnessLabel` from
`web/components/portfolio/` (M3 Task 3.1) and `DegradedNotice` from M3 Task 3.2. **Do not create a
second money component in `web/components/pnl/`.** If the ledger needs a variant, add a prop.

Required behaviours, each with a test:
- A campaign renders collapsed with its symbol, status, net and leg count; expanding shows the legs
  in order, using `<button aria-expanded>`.
- **An open leg's realised column renders `n/a`, not `$0.00`.** Its own test.
- Realised and unrealised are separate columns with distinct headers.
- **A leg with `commissions_complete: false` renders the gross qualifier.**
- `marks_as_of: null` renders "no marks available" beside the unrealised column, and every
  unrealised cell renders `n/a`.
- Filters drive the query string, not client-side array filtering, so the CSV export gets the same
  rows.
- An empty ledger renders one line of text, no icon circle.
- Every numeric column carries `.tabular`.

- [ ] **Step 1: Write the failing tests**

```typescript
it("renders an open leg's realised cell as unknown, never as zero", () => {
  render(<LegRow leg={{ ...aLeg(), net_pnl: null, outcome: "still_open" }} />);
  expect(screen.queryByText("$0.00")).toBeNull();
  expect(within(screen.getByTestId("realized")).getByText(/n\/a/i)).toBeInTheDocument();
});

it("says the figure is gross when commission data is incomplete", () => {
  render(<LegRow leg={{ ...aLeg(), commissions_complete: false }} />);
  expect(screen.getByText(/gross/i)).toBeInTheDocument();
});

it("states that no marks are available rather than showing zeros", () => {
  render(<LedgerTable data={{ ...aLedger(), marks_as_of: null }} />);
  expect(screen.getByText(/no marks available/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Confirm failure. Step 3: Implement. Step 4: All six gate commands. Step 5: Commit.**

---

## Task 5.5 — The equity curve chart `[GLM]`

**Files:** Create `web/components/pnl/EquityChart.tsx`. Test
`web/components/pnl/EquityChart.test.tsx`.

**Interfaces:** consumes `GET /pnl/equity`. Uses Recharts, which is already a dependency
(`web/CLAUDE.md` names it). Do not add `lightweight-charts` here — it is loaded for the research
price chart and is the wrong tool for a few dozen daily points.

**Rules, each with a test:**

1. **A gap renders as a gap.** A `null` value in the series, with `connectNulls` off. A straight
   line across days nobody measured is a fabricated claim, and this is the assertion that stops it.
2. **The chart never animates its data in.** `isAnimationActive={false}` on every series.
   `web/CLAUDE.md` states the rule and the reason: a line that draws itself lies about its value
   during the animation.
3. **The start date is stated in words** beneath the chart: the curve is the system's history, not
   the account's.
4. **Colours are read from CSS custom properties at mount**, matching how `PriceChart` already does
   it, so the chart follows the dark token system rather than hardcoding hex.
5. **`premium_cashflow` and `cumulative_realized` are separate, separately labelled series**, and
   the legend names them in full. They will disagree, and the label is what makes that legible
   rather than alarming.
6. `prefers-reduced-motion` is respected — with animation already off, this means no transition on
   hover either.
7. An empty curve renders one line of text, not an empty chart frame.

- [ ] **Step 1: Write the failing tests**

```typescript
it("does not connect across a gap", () => {
  const { container } = render(<EquityChart curve={curveWithGap()} />);
  const line = container.querySelector('[data-series="net_liquidation"]');
  expect(line?.getAttribute("connect-nulls")).not.toBe("true");
});

it("never animates its data in", () => {
  const { container } = render(<EquityChart curve={aCurve()} />);
  container.querySelectorAll("[data-series]").forEach((el) => {
    expect(el.getAttribute("is-animation-active")).not.toBe("true");
  });
});

it("labels premium cashflow as premium cashflow, never as realised", () => {
  render(<EquityChart curve={aCurve()} />);
  expect(screen.getByText(/premium cashflow/i)).toBeInTheDocument();
  const legend = screen.getByRole("list", { name: /legend/i });
  expect(within(legend).queryByText(/^realised p&l$/i)).toBeNull();
});

it("states when the curve begins", () => {
  render(<EquityChart curve={{ ...aCurve(), starts_at: "2026-03-02" }} />);
  expect(screen.getByText(/since 2 March 2026/i)).toBeInTheDocument();
});
```

Recharts does not expose `connect-nulls` as a DOM attribute; add `data-*` attributes to your own
wrapper elements so these assertions read real props rather than Recharts internals, and say so in
a comment.

- [ ] **Step 2: Confirm failure. Step 3: Implement. Step 4: All six gate commands. Step 5: Commit.**

---

## Task 5.6 — Breakdown panels `[GLM]`

**Files:** Create `web/components/pnl/{SummaryPanel,BreakdownTable}.tsx`. Test
`web/components/pnl/{SummaryPanel,BreakdownTable}.test.tsx`.

**Interfaces:** consumes `GET /pnl/summary`. Uses `Money` (M3 Task 3.1).

Required behaviours, each with a test:
- The headline figures render: realised total, unrealised total, open count, closed count, win
  rate.
- **`win_rate: null` renders `n/a`, not `0%`.** Its own test.
- **A `422` with `reason: "mixed_book"` renders a book selector and an explanation in plain
  words**, not an error state. The operator has paper and live trades and needs to pick one; that
  is a normal situation, not a failure. Its own test.
- `by_strategy` and `by_symbol` render as tables with `n_closed`, realised, win rate and mean days
  held.
- A bucket with `n_closed: 0` renders `n/a` in its rate columns.
- `commissions_complete: false` renders the gross qualifier on the headline realised figure.
- `best` and `worst` link to their legs in the ledger.
- Empty renders one line of text.

- [ ] **Step 1: Write the failing tests**

```typescript
it("treats a mixed book as a choice to make, not as an error", () => {
  renderWithQuery(<SummaryPanel />, {
    "/pnl/summary": { status: 422, body: { detail: { reason: "mixed_book" } } },
  });
  expect(screen.getByRole("group", { name: /book/i })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

it("renders an unknown win rate as unknown, not as zero percent", () => {
  render(<SummaryPanel summary={{ ...aSummary(), win_rate: null }} />);
  expect(screen.queryByText("0%")).toBeNull();
  expect(screen.getByText(/n\/a/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Confirm failure. Step 3: Implement. Step 4: All six gate commands. Step 5: Commit.**

---

## Task 5.7 — Nav flip, docs and schema regeneration `[GLM]`

**Files:** Modify `src/api/routers/meta.py`, `tests/test_api_meta.py`, `docs/web/api.md`,
`docs/web/openapi.json`, `web/lib/api-types.ts`, `web/CLAUDE.md`, `README.md`, `STATUS.md`.

- [ ] **Step 1:** Flip the `pnl` section to `available: True` and drop its `"Arrives in P4"` note.

```python
("pnl", "P&L", True, None),
```

Update `tests/test_api_meta.py`. Both `portfolio` and `pnl` are now available; no section carries
a note.

- [ ] **Step 2:** Confirm every route from Tasks 5.1-5.3 is in `docs/web/api.md`, including the
  `as_of` versus `marks_as_of` distinction and the `mixed_book` refusal.

- [ ] **Step 3:** Regenerate the schema artifacts and confirm the new routes and models appear in
  both:

```bash
python -c "import json; from src.api.main import create_app; \
print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json
cd web && npm run gen:api
```

- [ ] **Step 4:** `web/CLAUDE.md`'s Layout section gains `app/pnl/` and `components/pnl/`, in the
  same detail as the existing entries, naming every component and what each refuses to do.
  `README.md`'s layout table gains `web/app/pnl/` and `src/api/routers/pnl.py`.

- [ ] **Step 5:** `STATUS.md` records P4's ledger, summary, equity curve and export as built, with
  the reconciliation-against-a-broker-statement caveat from M4 Task 4.7 still standing.

- [ ] **Step 6:** Run all six gate commands and commit.

---

## Milestone 5 acceptance

- [ ] `/pnl` renders the ledger grouped by campaign, the summary breakdowns, and the equity curve.
- [ ] **No unknown value on the page or in the CSV renders as a zero.** Proven for `net_pnl`,
  `win_rate`, unrealised marks, and the CSV's empty cells.
- [ ] A mixed paper-and-live total is refused at the API with `mixed_book` and rendered in the UI
  as a book choice, never as a wrong number and never as an error.
- [ ] The ledger's unrealised marks and the portfolio page's come from the same snapshot, proven by
  a test comparing the two responses.
- [ ] The equity curve renders gaps as gaps, does not animate, and labels `premium_cashflow` under
  that name.
- [ ] The CSV export downloads with a dated filename, and the proxy forwards exactly two response
  headers.
- [ ] No route computes a P&L figure of its own; every number comes from `src/reporting/`.
- [ ] The rail shows both Portfolio and P&L as available.
- [ ] `docs/web/openapi.json` and `web/lib/api-types.ts` regenerate to an empty diff.
- [ ] Full gate green, all six commands.
