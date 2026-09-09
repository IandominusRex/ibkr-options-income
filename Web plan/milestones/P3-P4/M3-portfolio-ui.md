# Milestone 3 — Portfolio UI

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or
> superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The operator can open `/portfolio` and see what they hold, what it is worth, what is at
risk, and how old the answer is — with no number on the page claiming more than the API said.

**Spec:** `Web plan/P3-P4-design.md` §9. **Index:** `Web plan/P3-P4-IMPLEMENTATION-PLAN.md`.
**Depends on:** Milestone 2.

**The shape of this milestone in one sentence:** P1's differentiator was the check ribbon and P2's
was the command receipt; this milestone's is the **money cell**, and its job is to make it
impossible for an unknown value to render as `$0.00`.

Read `web/CLAUDE.md` in full before writing a component. Every rule in it binds here, and two bind
hardest: `None` renders as `n/a` with `.hatch` texture, and state is never encoded by colour alone.

---

## Task 3.1 — The money cell and the freshness label `[SONNET]`

**The signature component of this phase.**

**Files:** Create `web/components/portfolio/Money.tsx`,
`web/components/portfolio/FreshnessLabel.tsx`, `web/lib/money.ts`. Test
`web/components/portfolio/Money.test.tsx`, `web/lib/money.test.ts`.

**Interfaces:**

```typescript
// web/lib/money.ts
export type MoneyKind = "realized" | "unrealized" | "value" | "basis";

export interface MoneyProps {
  value: number | null | undefined;
  kind: MoneyKind;
  /** When false, the figure excludes commissions and says so. */
  complete?: boolean;
  /** Render a leading + on positives. Off for values, on for P&L. */
  signed?: boolean;
  asOf?: string | null;
}

/** "$1,234.56", "-$1,234.56", or UNKNOWN. Never "$0.00" for a null. */
export function formatMoneyCell(value: number | null | undefined): string;

/** "12m ago" / "3h ago" / "yesterday". Null-safe. */
export function freshnessText(asOf: string | null | undefined): string;

/** True when as_of is older than the threshold the API's `stale` flag uses. */
export function isStale(asOf: string | null | undefined, freshForMinutes: number): boolean;
```

`web/lib/format.ts` already exports `formatMoney`, `relativeAge` and an `UNKNOWN` constant. **Read
it first and reuse what is there.** `formatMoneyCell` exists only if `formatMoney` does not already
do the job — if it does, export it and skip the new function. Do not create a second money
formatter.

**Rules the component enforces, each with a test:**

1. **`null` and `undefined` render `UNKNOWN` with the `.hatch` texture. Never `$0.00`.** A genuine
   zero renders `$0`. This distinction is the reason the component exists and it gets two tests, one
   per direction.
2. **A negative figure carries a minus sign as well as `text-loss`.** Colour alone is not the
   signal. Asserted by reading the rendered text, not the class.
3. **`kind` is rendered, not implied.** A realised figure and an unrealised figure are visually and
   textually distinguishable. A test asserts the two do not produce identical output for the same
   number.
4. **`complete: false` renders a "gross" qualifier** next to the figure, in words.
5. **`.tabular` is applied** to every numeric output, so columns align.
6. **`FreshnessLabel` states the age in text**, never as a coloured dot. A stale reading says it is
   stale in words.
7. **`asOf: null` renders "not captured", not "just now".**

- [ ] **Step 1: Write the failing test**

```typescript
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Money } from "./Money";
import { FreshnessLabel } from "./FreshnessLabel";

describe("Money", () => {
  it("renders null as unknown, never as a zero", () => {
    render(<Money value={null} kind="realized" />);
    expect(screen.queryByText("$0.00")).toBeNull();
    expect(screen.queryByText("$0")).toBeNull();
    expect(screen.getByText(/n\/a/i)).toBeInTheDocument();
  });

  it("renders a real zero as a zero", () => {
    render(<Money value={0} kind="realized" />);
    expect(screen.getByText("$0")).toBeInTheDocument();
  });

  it("carries the sign in the text, not only in the colour", () => {
    render(<Money value={-125.5} kind="unrealized" signed />);
    expect(screen.getByText(/-\$125\.50/)).toBeInTheDocument();
  });

  it("distinguishes a realized figure from an unrealized one", () => {
    const { container: a } = render(<Money value={100} kind="realized" />);
    const { container: b } = render(<Money value={100} kind="unrealized" />);
    expect(a.textContent).not.toEqual(b.textContent);
  });

  it("says so when a figure excludes commissions", () => {
    render(<Money value={100} kind="realized" complete={false} />);
    expect(screen.getByText(/gross/i)).toBeInTheDocument();
  });

  it("applies tabular figures", () => {
    const { container } = render(<Money value={1234.5} kind="value" />);
    expect(container.querySelector(".tabular")).not.toBeNull();
  });
});

describe("FreshnessLabel", () => {
  it("states the age in words", () => {
    const when = new Date(Date.now() - 12 * 60 * 1000).toISOString();
    render(<FreshnessLabel asOf={when} freshForMinutes={30} />);
    expect(screen.getByText(/12m ago/)).toBeInTheDocument();
  });

  it("says stale in words when it is stale", () => {
    const when = new Date(Date.now() - 4 * 60 * 60 * 1000).toISOString();
    render(<FreshnessLabel asOf={when} freshForMinutes={30} />);
    expect(screen.getByText(/stale/i)).toBeInTheDocument();
  });

  it("renders nothing-captured distinctly from just-now", () => {
    render(<FreshnessLabel asOf={null} freshForMinutes={30} />);
    expect(screen.getByText(/not captured/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2:** `cd web && npx vitest run components/portfolio` — confirm failure.

- [ ] **Step 3: Implement.** Semantic tokens only. No hex literals, no `text-gray-*`.

- [ ] **Step 4:** `npx vitest run` · `npm run lint` · `npm run build`. Commit.

---

## Task 3.2 — The portfolio shell and summary panel `[SONNET]`

**Sets every frontend convention the rest of the section copies.**

**Files:** Create `web/app/portfolio/page.tsx`,
`web/components/portfolio/{PortfolioShell,SummaryPanel,DegradedNotice}.tsx`. Test
`web/components/portfolio/SummaryPanel.test.tsx`,
`web/components/portfolio/DegradedNotice.test.tsx`.

**Interfaces:** consumes `GET /portfolio/summary` through `web/lib/api.ts`'s `apiFetch`, typed from
`web/lib/api-types.ts`. Uses TanStack Query with `placeholderData` to keep the last good response
rather than flashing a spinner, exactly as P1's pages do.

Produces, for Tasks 3.3-3.5: `PortfolioShell` (the page frame with tabs), `DegradedNotice` (the
component every panel uses to state a degraded reading), and the convention that every panel reads
`source`/`degraded`/`note` from its own response rather than inheriting a page-level assumption.

**Design points that are not negotiable:**

1. **`source: "none"` renders the empty state, not zeros.** One line of plain text saying no
   snapshot has been captured, plus the refresh control from Task 3.5 once it exists. **No
   decorative icon circle** — that is on `web/CLAUDE.md`'s banned list.
2. **`degraded: true` renders `DegradedNotice` above the numbers**, carrying the API's own `note`
   verbatim. The UI does not compose its own explanation of a degradation the backend named.
3. **The freshness label is at the top of the page and applies to the whole panel**, so a reader
   cannot see a number without seeing its age.
4. **Tabs, not routes**, for Positions / Campaigns / Calendar — matching how `/options` does it, so
   the two consoles feel like one product.
5. Every `Sourced` value renders through `Money` with its `stale` flag honoured.

Required behaviours, each with a test:
- A fresh response renders the five account values through `Money`.
- `source: "none"` renders the empty state and **no account figures at all**. Asserted by querying
  for a currency string and finding none.
- `degraded: true` renders the API's `note` text verbatim.
- A stale response renders the stale wording.
- `buying_power_utilisation_pct: null` renders `n/a`, not `0%`.
- The tab bar renders three tabs and switching does not refetch the summary.

- [ ] **Step 1: Write the failing test**

```typescript
it("renders the empty state and no figures when nothing has been captured", () => {
  renderWithQuery(<SummaryPanel />, {
    "/portfolio/summary": { source: "none", degraded: true, account: null,
                            exposure: null, note: "No portfolio snapshot has been captured yet.",
                            as_of: new Date().toISOString() },
  });
  expect(screen.getByText(/no portfolio snapshot/i)).toBeInTheDocument();
  expect(screen.queryByText(/\$/)).toBeNull();
});

it("renders the backend's own note for a degraded reading", () => {
  renderWithQuery(<SummaryPanel />, {
    "/portfolio/summary": { source: "eod", degraded: true, note: "Values are from the last "
      + "end-of-day run.", account: anAccount(), exposure: anExposure(),
      as_of: new Date().toISOString() },
  });
  expect(screen.getByText(/last end-of-day run/i)).toBeInTheDocument();
});

it("renders unknown utilisation as n/a, not as zero percent", () => {
  renderWithQuery(<SummaryPanel />, {
    "/portfolio/summary": { source: "monitor", degraded: false, account: anAccount(),
      exposure: { ...anExposure(), buying_power_utilisation_pct: null },
      as_of: new Date().toISOString() },
  });
  expect(screen.queryByText("0%")).toBeNull();
  expect(screen.getAllByText(/n\/a/i).length).toBeGreaterThan(0);
});
```

Reuse the query-wrapper helper P1 and P2's component tests already use; grep
`web/components/options/*.test.tsx` for it rather than writing a second one.

- [ ] **Step 2: Confirm failure. Step 3: Implement. Step 4: All six gate commands. Step 5: Commit.**

---

## Task 3.3 — Position groups `[GLM]`

**Files:** Create `web/components/portfolio/{PositionsPanel,PositionGroup,OptionLegRow,StockLegRow}.tsx`.
Test `web/components/portfolio/PositionGroup.test.tsx`.

**Interfaces:** consumes `GET /portfolio/positions`. Uses `Money` and `FreshnessLabel` (Task 3.1)
and `DegradedNotice` (Task 3.2). Do not build a second money formatter or a second degraded
notice.

Required behaviours, each with a test:
- A group renders the underlying once, the stock leg above its option legs.
- **Both cost bases render when `adjusted_cost_basis` is present**, each labelled, with the
  premium-adjusted one identified as such in words.
- **`adjusted_cost_basis: null` renders no adjusted row at all**, rather than an `n/a` row that
  implies the concept applies. Its own test.
- A short leg is labelled short in text, not only by a negative contract count.
- `assignment_risk: true` renders a text label, not a coloured dot. `web/CLAUDE.md` bans decorative
  status dots.
- `dte: null` renders `n/a`, never `0`.
- `moneyness: null` renders `n/a`, never `otm`.
- `delta` renders with its `delta_source` beside it, matching how `ShortsTable` already does it.
- An empty `groups` array with `source: "none"` renders the empty state; with `source: "monitor"`
  it renders "no open positions". **These two are different strings** and each has a test.

- [ ] **Step 1: Write the failing tests, one per bullet.**

```typescript
it("renders no adjusted-basis row when the shares did not come from an assignment", () => {
  render(<PositionGroup group={{ underlying: "AAPL",
    stock: { shares: 100, avg_cost: 200, adjusted_cost_basis: null,
             unrealized_pnl: 500, unrealized_pnl_adjusted: null, ... },
    options: [] }} />);
  expect(screen.queryByText(/adjusted/i)).toBeNull();
});

it("distinguishes an empty account from an uncaptured one", () => {
  const { rerender } = render(<PositionsPanel data={{ source: "none", groups: [] }} />);
  const uncaptured = screen.getByRole("status").textContent;
  rerender(<PositionsPanel data={{ source: "monitor", groups: [] }} />);
  expect(screen.getByRole("status").textContent).not.toEqual(uncaptured);
});
```

- [ ] **Step 2: Confirm failure. Step 3: Implement. Step 4: All six gate commands. Step 5: Commit.**

---

## Task 3.4 — Campaign threads `[GLM]`

**Files:** Create `web/components/portfolio/{CampaignsPanel,CampaignThread}.tsx`. Test
`web/components/portfolio/CampaignThread.test.tsx`.

**Interfaces:** consumes `GET /portfolio/campaigns`. Uses `Money` (Task 3.1).

A campaign is a **thread**: the symbol and its rolled-up financials on one line, expanding to the
legs in order. This is the shape a Telegram message cannot produce and is the reason the surface
exists.

Required behaviours, each with a test:
- A campaign renders its symbol, status, net premium and leg count collapsed.
- Clicking expands to the legs in order; clicking again collapses. Use `<button aria-expanded>`,
  matching `ChecksSection`'s existing pattern.
- A leg with `known: false` renders as an unavailable leg with its `candidate_id`, **not omitted**.
  Its own test — the leg count on the collapsed row must match the expanded list.
- An assigned campaign renders its adjusted cost basis and realised stock P&L; a non-assigned one
  renders neither row.
- `realized_stock_pnl: null` on an assigned campaign renders `n/a`, not `$0`.
- Filters for status and symbol drive the query, not client-side array filtering.
- Empty renders one line of text, no icon circle.

- [ ] **Step 1: Write the failing tests. Step 2: Confirm failure. Step 3: Implement. Step 4: All
  six gate commands. Step 5: Commit.**

---

## Task 3.5 — Calendar panel and the refresh control `[GLM]`

**Files:** Create `web/components/portfolio/{CalendarPanel,RefreshControl}.tsx`. Test
`web/components/portfolio/{CalendarPanel,RefreshControl}.test.tsx`.

**Interfaces:** consumes `GET /portfolio/calendar` and, for the refresh control, P2's existing
`submitCommand` / `useCommandStatus` from `web/lib/commands.ts` and `CommandReceipt` from
`web/components/options/CommandReceipt.tsx`.

**The refresh control reuses P2's command machinery unchanged.** Do not write a second receipt, a
second poller, or a second submit helper. If `CommandReceipt` needs a prop it does not have, add
the prop; do not fork the component.

Required behaviours, each with a test:
- Days render nearest first, each with its date and DTE.
- **`consequence: "unknown"` renders as its own wording**, distinct from `expires_worthless`. Its
  own test — this is the value the API was told not to default away, and the UI must not default it
  back.
- `called_away` and `assigned` render as distinct wordings.
- The horizon control changes the query parameter.
- The refresh control fires one `POST /commands` with `kind: "refresh"` and renders
  `CommandReceipt`.
- **A `broker_unavailable` failure renders as a plain answer**, not as red error chrome. The
  broker being down is an ordinary state, matching how `no_qualifying_roll` is rendered on the
  shorts list.
- On a terminal command status, the portfolio queries invalidate so the next poll sees the new
  snapshot.
- Polling stops at a terminal status.

- [ ] **Step 1: Write the failing tests**

```typescript
it("renders an unknown consequence distinctly from expires-worthless", () => {
  render(<CalendarPanel data={dayWith([
    { consequence: "unknown", ... }, { consequence: "expires_worthless", ... },
  ])} />);
  const texts = screen.getAllByTestId("consequence").map((n) => n.textContent);
  expect(new Set(texts).size).toBe(2);
});

it("renders a missing broker as an answer, not as an error", () => {
  render(<RefreshControl />);
  // ... submit, resolve the command as failed/broker_unavailable
  expect(screen.getByText(/not connected/i)).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});
```

- [ ] **Step 2: Confirm failure. Step 3: Implement. Step 4: All six gate commands. Step 5: Commit.**

---

## Task 3.6 — Nav flip and documentation `[GLM]`

**Files:** Modify `src/api/routers/meta.py`, `web/CLAUDE.md`, `README.md`, `STATUS.md`,
`docs/web/architecture.md`. Test `tests/test_api_meta.py`.

- [ ] **Step 1:** Flip the `portfolio` section in `src/api/routers/meta.py`'s `_SECTIONS` to
  `available: True` and drop its `"Arrives in P3"` note. Leave `pnl` alone — it flips in Milestone
  5, not here.

```python
("portfolio", "Portfolio", True, None),
("pnl", "P&L", False, "Arrives in P4"),
```

- [ ] **Step 2:** Update `tests/test_api_meta.py`'s expectation. If no test asserts the section
  states, add one — the nav manifest is what the rail renders, and a section flipped early would
  route an operator to a page that does not exist.

- [ ] **Step 3:** `web/CLAUDE.md`'s Layout section gains `app/portfolio/` and
  `components/portfolio/`, described in the same detail as the existing `components/options/`
  entry. Name every component and say what each one refuses to do — the existing entries do this
  and it is what makes the file useful.

- [ ] **Step 4:** `README.md`'s layout table gains `web/app/portfolio/`. `STATUS.md`'s P3 row
  records M1-M3 as built with the portfolio surface live. `docs/web/architecture.md` gains the
  snapshot spine in its data-flow description.

- [ ] **Step 5:** Run all six gate commands and commit.

---

## Milestone 3 acceptance

- [ ] `/portfolio` renders account values, positions grouped by underlying, campaign threads and
  the expiry calendar.
- [ ] **No unknown value anywhere on the page renders as `$0.00` or `0`.** Proven by the `Money`
  tests and by the panel tests for `dte`, `moneyness`, `utilisation` and `realized_stock_pnl`.
- [ ] The page states how old its data is, in words, at the top.
- [ ] An uncaptured portfolio renders an explicit empty state that reads differently from an empty
  account.
- [ ] A degraded reading renders the backend's own note verbatim.
- [ ] Assigned shares show both cost bases; ordinary shares show only one.
- [ ] `consequence: "unknown"` is visible and distinct on the calendar.
- [ ] The refresh control reuses P2's `submitCommand` and `CommandReceipt` without forking either.
- [ ] The rail shows Portfolio as available and P&L as still arriving in P4.
- [ ] No raw `bg-gray-*`, no hex literals, no em dashes in UI copy, no decorative status dots, no
  banned words. Checked by reading the diff, not assumed.
- [ ] Full gate green, all six commands.
