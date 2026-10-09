# Design — P3 Portfolio and P4 Profitability Tracker

**Date:** 2026-09-09
**Status:** design, approved in outline, pending written review
**Context:** `OVERVIEW.md` holds the end-state vision and the P0–P5 decomposition.
`P0-P1-design.md` designs the foundation and the research tier; `P2-design.md` designs the
options console. All three are shipped.
**Prior art re-used, not redesigned:** P2's provenance envelope, its command queue and drain,
its write fence, and its receipt component. P3 and P4 add no new machinery of that kind.

---

## 1. Scope

**P3 — Portfolio.** OVERVIEW §1.3: "positions, account, campaigns, assignment risk."
**P4 — Profitability tracker.** OVERVIEW §1.4: "an Excel-shaped ledger of every position opened
and closed, with realised/unrealised P&L, an equity curve, and system performance over time."

They are designed together, the way P0 and P1 were, because they share one thing that does not
exist yet: **a record of what the account held and what it was worth, captured more than once a
day.** P3 needs it to render a portfolio; P4 needs it to mark open legs and to plot an equity
curve. Designing P3 alone would mean specifying that plumbing twice, and specifying it the second
time under P4's requirements after the first version had already shipped.

Together they ship seven things:

1. **The portfolio summary** — account values, exposure, and what is at risk right now.
2. **Positions** — every holding, grouped by underlying, stock leg beside its option legs.
3. **Campaigns** — the wheel thread per symbol, from first CSP to called-away shares.
4. **The expiry calendar** — what expires when, and what that would mean.
5. **The profitability ledger** — one row per option contract opened and closed, grouped under
   campaign threads, with realised P&L, ROC, days held, and outcome.
6. **The equity curve and performance breakdown** — by symbol, by strategy, over time.
7. **System performance** — the existing score-vs-outcome evidence, rendered for a human.

**Out of scope, by phase:** mobile (P5). Its rail entry does not exist yet and does not need to.

**Out of scope, by decision:** any new path that can reach an order. The entire phase adds one
write, and it is a command kind P2 already designed. See §4.6.

**Out of scope, by decision:** operator notes and trade annotations. A trade journal wants them
and they are a reasonable future ask, but they mean a new command kind, a new table, and a new
write surface, for a feature that does nothing the existing `journal` narrative cannot approximate.
Not in this phase.

---

## 2. Decisions this design implements

Each was taken explicitly during the P3/P4 brainstorm on 2026-09-09.

| Decision | Value |
|---|---|
| Phase scoping | **P3 and P4 designed together**, one design, one plan, one milestone folder. |
| Portfolio freshness | **A new `portfolio_snapshots` table**, written periodically by a process that already holds an IB connection, plus the on-demand `refresh` command P2 left unregistered. |
| P&L accounting home | **A new deterministic module, `src/reporting/`.** Pure functions returning Pydantic schemas. The API renders; it does not compute. |
| Ledger unit | **Leg rows grouped under campaign threads.** The atomic row is one option contract opened and closed; the campaign is the wheel cycle that gives it meaning. |
| System performance | **Surfaced, read-only**, over `verdict_ledger` and `score_metrics.py`. |
| Export | **CSV export of the ledger**, same filters as the on-screen table. |
| New write paths | **`refresh` and nothing else.** |

---

## 3. Inherited invariants

From `CLAUDE.md`, `P0-P1-design.md` §3, and `P2-design.md` §3. P3 and P4 are read surfaces, so
most of these are satisfied by construction rather than by care — but two of them get genuinely
harder in this phase, and §4 and §6 are where that is dealt with.

1. **The Rules Engine is the only path to order execution.** P3 and P4 add no intent that can
   reach an order. `refresh` fetches and writes a snapshot; it cannot create a candidate, an
   approval, or an order.
2. **The API writes exactly one table.** P2 relaxed "the API never writes" to "the API writes
   `app_commands`". **P3 and P4 do not relax it further.** The new `portfolio_snapshots` table is
   written by trading processes only, and the API reads it through the `mode=ro` engine like
   everything else.
3. **The fence.** Nothing in `src/claude/eval/` reaches the engine, the weights, the risk limits,
   or sizing. P4 reads two things that live behind that fence — `verdict_ledger` and
   `score_metrics.py` — and §6.2 and §7.5 explain why reading them is the intended use rather
   than a breach, and what enforces the distinction.
4. **Analytics tiers.** The enrichment tier still may not be imported by `engine/`, `execution/`,
   or `strategies/`. §6.2 adds `src/reporting/` to the same one-way list.
5. **Pydantic at every boundary.** No raw `ib_async` object crosses a module line. The new
   snapshot writer serialises `PositionSnapshot` and `AccountSnapshot`, both of which already
   exist in `src/common/schemas.py`, and stores their `model_dump(mode="json")`.
6. **One clientId per process.** P3 and P4 add **no new process**, so they add no clientId. The
   snapshot writer runs inside the monitor (clientId 12) and the drain (clientId 15), both of
   which already hold connections.

---

## 4. The freshness spine

### 4.1 Why the API cannot simply ask IBKR

`src/api/` constructs no `IB` object and holds no clientId. That is not an implementation detail
to be relaxed when a portfolio screen makes it inconvenient — it is the property that makes it
impossible for the web process to contend with the four trading processes for a market-data line
or an order path. It stays.

So the portfolio screen is exactly as fresh as the last thing a trading process wrote into SQLite.
Today that is **once a day**:

- `position_snapshots` holds one JSON row per ET trading day, written only by the EOD run
  (`src/orchestrator/eod_report.py:398`).
- `AccountSnapshot` — net liquidation, cash, buying power, maintenance margin, excess liquidity —
  is **persisted nowhere at all**, except incidentally inside `journal.payload.eod_summary.account`.

OVERVIEW §6 records P3 as "largely a rendering of data `approval_service` already persists". That
turns out to be half true. The campaigns, fills, orders and roll alerts are all there. The
positions are a day stale and the account values are a by-product of a narrative table.

### 4.2 The table

```
portfolio_snapshots(
  id             PK
  captured_at    datetime, indexed      when the broker was actually asked
  source         monitor | refresh | eod
  account_json   AccountSnapshot.model_dump(mode="json")
  positions_json list[PositionSnapshot.model_dump(mode="json")]
  created_at
)
```

Append-only. No unique constraint: two writers may legitimately capture within the same minute and
the newest row simply wins. Pruned to `storage.portfolio_snapshot_retention_days` (default 30) by
the EOD run, alongside the 14-day `risk_verdicts` prune that already exists.

Sizing is worth stating rather than assuming. At the 15-minute floor of §4.3 that is roughly 26
rows per trading day; a portfolio of 30-40 positions serialises to something on the order of 10KB
per row, so 30 days is single-digit megabytes. If a future operator wants a year of intraday
history, the answer is a separate rollup, not a longer retention on this table.

### 4.3 Two writers, both already connected

**The monitor** (`src/monitor/intraday.py`, clientId 12) runs a `_refresh_loop` every
`scheduler.intraday_poll_seconds` and already calls `get_positions(self._ib)` on each pass to
maintain its tick subscriptions. It gains an account fetch and a snapshot write, subject to two
guards:

- **Rate limit.** At most one snapshot per `market_data.portfolio_snapshot_interval_minutes`
  (default 15), regardless of how often the refresh loop runs. This matches OVERVIEW §2's
  "delayed intraday, 15-30 min" decision and keeps the table small.
- **Market hours only.** A monitor left running overnight must not write 900 identical rows.

**The drain** (`src/notify/command_drain.py`, running in `approval_service` with `ib_scan`,
clientId 15) gains the `refresh` handler, which captures immediately and ignores the rate limit —
an operator who clicks refresh is asking for a fetch, and telling them to wait fourteen minutes
would make the button a lie.

The critical requirement on the monitor writer: **a snapshot failure must never interrupt tick
handling or roll alerts.** The monitor's job is to fire assignment and roll alerts on live ticks;
writing a portfolio row for a web page is strictly secondary. The write is wrapped, logged on
failure, and never propagates. This mirrors how `save_position_snapshot` already swallows and logs
its own exceptions.

### 4.4 Why `position_snapshots` is not reused

It would be less code, and it would be wrong.

`position_snapshots` carries `UniqueConstraint("snapshot_date")`, and
`load_latest_position_snapshot(before=...)` is consumed by
`src/claude/eval/assignment.py::detect_assignments`, which diffs the most recent **prior-day** row
against current positions to distinguish an assignment from an expiry. That detector decides
whether a campaign gets marked assigned and whether the outcome ledger records `ASSIGNED` or
`EXPIRED_WORTHLESS`.

Writing intraday rows into that table would put a trading-critical detector on top of data whose
contract changed underneath it. The prior-day lookup would still work by accident, because it
filters on strictly earlier dates — but "works by accident" is the wrong foundation for
assignment detection, and the day's row would be repeatedly overwritten by intraday state,
including after the EOD run had written the row the detector actually wants.

A separate table costs one migration and removes the question entirely.

### 4.5 Degradation: the fallback chain

The API reads the newest `portfolio_snapshots` row, sets `as_of = captured_at`, and derives
`stale` through the existing `Sourced.of` helper. When the table is empty — before the monitor has
ever run, or on a fresh database — it falls back:

```
portfolio_snapshots (newest)            source="monitor" | "refresh"   as_of = captured_at
        │ empty
        ▼
position_snapshots (newest) +           source="eod"                   as_of = created_at
journal.payload.eod_summary.account
        │ empty
        ▼
an explicit empty state                 "no snapshot has been captured yet"
```

The third rung matters. A portfolio page that renders zeros because nothing has been written yet
is indistinguishable from a portfolio that is genuinely empty, and the difference is the whole
account. It says which it is.

### 4.6 `refresh` — the one write in the phase

P2 §6.6 designed `refresh` and P2 shipped without registering a handler for it; `STATUS.md`'s own
P2 row flags this, and `docs/web/commands.md` still describes a behaviour that does not exist. P3
registers it and corrects the doc.

Payload `{}`. No `dedupe_key`, because repeating it is harmless. The handler:

1. Fails with `broker_unavailable` if `ib is None`. A refresh with no connection cannot be served
   honestly and must not silently write a stale row.
2. Fetches positions and the account snapshot.
3. Writes one `portfolio_snapshots` row with `source="refresh"`.
4. Marks the command `applied` with `captured_at` in `result_json`, so the receipt can say what it
   actually got.

It creates no candidate, no approval, and no order, so it needs no live-mode confirm token. It is
the least dangerous command kind in the system and is deliberately the only one this phase adds.

---

## 5. P3 read surfaces

All read routes serve from SQLite through the `mode=ro` engine, carry a top-level `as_of`, and
inherit P1's provenance envelope. None reaches IBKR.

### 5.1 `GET /portfolio/summary`

The account block — net liquidation, total cash, buying power, maintenance margin, excess
liquidity — each as a `Sourced` value so a stale figure is visibly stale rather than merely old.
Beside it, the exposure the operator actually needs before deciding anything:

- open positions, open short options, open campaigns
- net delta exposure (the same `Σ delta × position × 100` the EOD summary computes)
- cash secured against open puts, and what fraction of buying power that represents
- how many short options are inside the assignment-risk band of §5.5

### 5.2 `GET /portfolio/positions`

Every position, **grouped by underlying**, because that is the unit the operator thinks in: the
stock leg and its option legs are one situation, not three rows that happen to share a ticker.

Each group carries the stock position with its cost basis — and where the shares came from an
assignment, `campaigns.adjusted_cost_basis_for(symbol)` rather than the raw fill price, because
the premium already collected is what makes an assigned position profitable. Each option leg
carries strike, expiry, DTE, delta with its source, market value, unrealised P&L, moneyness, and
the assignment-risk flag.

This is deliberately wider than P2's `/options/shorts`, which returns only the positions a roll
can apply to. The two coexist; §5.5 is what stops them disagreeing.

### 5.3 `GET /portfolio/campaigns`

From `src/storage/campaigns.py::load_campaigns()`, with each `leg_candidate_ids` entry joined to
`candidates` for the contract detail the campaign row does not store. Per campaign: symbol,
status, opened and closed dates, the legs in order, total premium collected, total debit paid, net
premium, whether it was assigned, the adjusted cost basis, and realised stock P&L.

This is the surface Telegram's `/campaigns` renders as text and renders badly — a multi-leg wheel
cycle is a table with a thread through it, not a chat message.

### 5.4 `GET /portfolio/calendar`

Option expiries grouped by date over a configurable horizon, each entry naming the contract, the
contracts held, current moneyness, and what expiry would mean if nothing changes: assignment,
called away, or expires worthless. Telegram's `/calendar` equivalent, with the "what would happen"
column a chat message has no room for.

### 5.5 One definition of assignment risk

Assignment risk is currently defined in two places, and they disagree:

- `src/monitor/triggers.py::check_assignment_risk` — the trigger that fires the Telegram alerts the
  operator acts on. Reads `assignment_alert_delta` (0.70) and `assignment_alert_dte` (**21**) from
  config.
- `src/api/routers/options.py:834-844` — an inline `abs(delta) >= 0.70 and dte <= 7`, under a
  comment claiming 0.70/7 "is the monitor's default". `config/settings.yaml:271` sets
  `assignment_alert_dte: 21`, so the comment is wrong and so is the threshold.

The practical effect: `/options/shorts` reports `assignment_risk: false` for any position between 8
and 21 days from expiry that the monitor is actively alerting on.

P3 renders assignment risk on positions, on the calendar, and in the summary count. **It must not
add a third definition to two that already disagree**, so unifying them is pulled forward into
**Milestone 0** rather than carried as P3 work: one shared predicate in `src/common/assignment_risk.py`,
both existing callers rewired, thresholds read from config on both sides. The monitor's rule wins,
because it is the one that fires real alerts.

Three surfaces disagreeing about whether a position is at risk of assignment is a correctness bug
the operator discovers at the worst possible moment.

---

## 6. The P&L engine

### 6.1 There is no complete P&L record today

The system has three partial records and no complete one:

- **`campaigns`** rolls up premium collected, debits paid and net premium per symbol from
  `FillRow`, recomputed on every attach. Real, live, and per-symbol — but it aggregates, so the
  individual contract that went wrong is invisible. It is also **gross of commissions**:
  `_rollup` computes `collected - paid` with no commission term, while the accounting rule §6.2
  adopts nets them. Milestone 0 pins that semantic with a test and documents it rather than
  changing it, and §11's campaign cross-check compares gross to gross so the two rollups can be
  reconciled instead of silently differing by the commission total.
- **`verdict_ledger.realized_pnl`** is back-filled per candidate by the reconciler on close. It is
  the closest thing to a per-leg P&L that exists — but it only covers **Claude-reviewed
  candidates**, so it is a sample, not a ledger.
- **`journal.realized_pnl`** is, by its own column comment and the `EODSummary` docstring, the net
  option **premium cashflow** for the day (SELL credits minus BUY debits), **not** a paired
  realised P&L. Assignment stock-leg P&L is excluded. The field name is retained for back-compat
  and the system already surfaces it to the user as "premium cashflow" (N13).

So P4 defines paired realised P&L across the whole book for the first time. That is the substance
of this half of the phase, and it belongs in tested Python, not in a route handler.

### 6.2 `src/reporting/`, and a dependency inversion

A new package, `src/reporting/`. Pure functions over `fills`, `candidates`, `campaigns`,
`orders`, `approvals` and `portfolio_snapshots`, returning Pydantic schemas defined in
`src/common/schemas.py` like every other cross-module type.

**The important discovery is that the accounting rule already exists and is already pure.**
`src/claude/eval/reconcile.py` contains `_fill_economics` (credit, debit, commissions, entry
premium, entry quantity from a list of `FillRow`) and `_classify` (the outcome decision:
closed-early, expired-worthless, assigned, still-open, never-filled, and the realised P&L for
each). These are exactly P4's accounting rules, written and tested, sitting behind the fence
because that is where the reconciler happens to live.

There are three ways to handle that and only one of them is right.

- **Fork it into `src/reporting/`.** Two implementations of paired realised P&L in one repo, which
  will drift, and the drift will be silent because both will look plausible.
- **Import it from `src/claude/eval/`.** Works, but it makes a web-facing report depend on a
  fenced module, and every future reader has to re-derive why that is allowed.
- **Invert the dependency.** Move `_fill_economics` and `_classify` **down** into
  `src/reporting/legs.py` as public functions, and have `reconcile.py` import them.

The third is the design. It gives:

- `src/reporting/` imports nothing from `src/claude/` — the fenced module depends on the neutral
  one, not the reverse.
- One implementation of the accounting rule, used by both the outcome ledger and the ledger UI, so
  the two can never disagree about whether a trade made money.
- **The reconciler's existing test suite becomes the regression net for the move.** If the
  extraction changes behaviour, tests that were written months ago fail. That is a better safety
  property than any test written specifically for this refactor.

And it adds one rule to the fence test: **`src/engine/`, `src/execution/` and `src/strategies/`
may never import `src.reporting`.** Reporting reads the whole book, including enrichment-side
tables; it must stay on the read side of the line, exactly as `src/api/` and `src/research/` do.

### 6.3 What a leg is

A leg is **one option contract position, identified by `candidate_id`**, from the fill that opened
it to whatever closed it.

```python
class PnlLeg(BaseModel):
    candidate_id: str
    campaign_id: str | None
    symbol: str
    strategy: Strategy
    right: OptionRight
    strike: float
    expiry: date
    contracts: int
    opened_at: datetime
    closed_at: datetime | None
    credit: float          # Σ SELL fills × 100
    debit: float           # Σ BUY fills × 100
    commissions: float
    commissions_complete: bool
    net_pnl: float | None        # None while open
    unrealized_pnl: float | None  # None unless open AND a mark is available
    days_held: int
    roc_pct: float | None
    annualized_pct: float | None
    outcome: VerdictOutcome
    is_live: bool
```

Points that need stating because they are where a P&L table quietly lies:

- **`net_pnl` is `None` while the leg is open, never `0.0`.** An open leg has an unrealised mark,
  not a realised result, and a zero in a realised column is a claim.
- **Commissions may be missing.** `FillRow.commission` is nullable. A missing commission is summed
  as zero and `commissions_complete` goes false, so the UI can say the figure is gross rather than
  quietly overstating profit.
- **A rolled leg closes and a new leg opens.** The roll's buy-to-close debit belongs to the leg
  being closed; the new credit belongs to the new leg. The campaign is what makes them one story.
- **`outcome` is `VerdictOutcome`**, the enum the reconciler already uses. P4 does not invent a
  second outcome vocabulary.
- **Paper and live are never mixed.** `FillRow.is_live` carries through, and the ledger filters on
  it. A paper win must never appear in a total beside a live one.

### 6.4 What a campaign is

```python
class CampaignPnl(BaseModel):
    campaign_id: str
    symbol: str
    status: Literal["open", "closed"]
    opened_date: date
    closed_date: date | None
    legs: list[PnlLeg]
    option_realized: float           # Σ closed legs
    option_unrealized: float | None  # open legs marked at the latest snapshot
    stock_realized: float | None     # campaigns.realized_stock_pnl
    stock_unrealized: float | None   # marked at the latest snapshot
    assigned: bool
    adjusted_cost_basis: float | None
    total_net: float
```

The stock leg is not recomputed. `campaigns.realized_stock_pnl` and
`campaigns.adjusted_cost_basis` already exist, are already maintained on assignment, and are
already the numbers the rest of the system uses. P4 reads them.

Unrealised marks come from the newest `portfolio_snapshots` row — the same source the portfolio
screen renders, so the two surfaces agree by construction rather than by coincidence. When no
snapshot exists, unrealised is `None` and the UI says so; it does not fall back to a stale mark
without saying which one it used.

### 6.5 The equity curve, and what it cannot claim

One point per `JournalRow`: `entry_date`, `payload.eod_summary.account.net_liquidation`,
`unrealized_pnl`, and cumulative realised summed from legs closed on or before that date.

Three honesty constraints, all of which have to survive into the UI:

1. **The curve starts at the first journal row.** It is not the account's history, it is the
   system's history. The chart states its start date rather than implying a beginning at zero.
2. **A missed EOD run is a gap, not a line.** No interpolation between points. A straight segment
   across a week the system was down is a fabricated claim about a week nobody measured.
3. **`journal.realized_pnl` renders as "premium cashflow", never as "realised P&L".** P4's own
   paired realised figure sits beside it and the two will visibly disagree, because they measure
   different things. That disagreement is correct and is labelled, not reconciled away.

### 6.6 Computed on read, not materialized

Every figure above is derived on request. No `pnl_ledger` table, no EOD write, no backfill.

The reason is scale: the whole input is a few hundred `FillRow`s joined to a few hundred
`CandidateRow`s. Materialising that is optimising a query that has never been slow, and it buys a
new write path in trading code, a backfill for existing history, and a table that can silently
drift from `fills` the moment the accounting rule is corrected.

If the ledger is ever slow enough to matter, the fix is a cache keyed on the newest `FillRow.id`
and the newest snapshot's `captured_at` — cheap, invalidating itself correctly, and still not a
write.

---

## 7. P4 read surfaces

### 7.1 `GET /pnl/ledger`

Leg rows, filterable by symbol, strategy, outcome, live/paper and date range, sortable, and
grouped under their campaign threads. This is OVERVIEW's "Excel-shaped ledger of every position
opened and closed", and the grouping is what stops an assignment reading as a leg that ended for
no reason.

### 7.2 `GET /pnl/summary`

Realised total, unrealised total, and the breakdowns: by strategy (covered call versus
cash-secured put versus roll), by symbol, win rate, average days held, average ROC, best and worst
legs. Every one of these is computed from the same `PnlLeg` list the ledger renders, so a total
can never disagree with the rows above it.

### 7.3 `GET /pnl/equity`

The curve of §6.5, plus the gaps it knows about, so the chart can render them as gaps.

### 7.4 `GET /pnl/ledger.csv`

The same rows the JSON route returns under the same filters, as `text/csv` with a
`Content-Disposition` filename. This makes the "Excel-shaped" promise real for a spreadsheet
cross-check or a tax return.

One concrete obstacle: `web/app/api/[...path]/route.ts` forwards only `Content-Type` from the
upstream response. `Content-Disposition` is dropped, so the download would arrive without a
filename. The export task extends that allowlist rather than working around it in the client.

### 7.5 `GET /pnl/system`

`src/claude/eval/score_metrics.py::score_outcome_report()` already returns a `ScoreOutcomeReport`:
blended-score buckets against realised win rate and P&L, per-component buckets, signal
correlations, and its own notes. Beside it, Claude-verdict-versus-baseline agreement from
`verdict_ledger`.

**Why this is not a fence breach.** `CLAUDE.md` is explicit that everything `eval/` produces "is
read by a human, never auto-applied", and that a human decides by hand whether
`scoring_weights.yaml` should change. A browser page is precisely that human reader, and a better
one than `scripts/evaluate_scores.py`. What the fence forbids is the loop closing automatically,
and nothing here closes it: the route is `GET`, the API's only writable table is `app_commands`,
and no command kind touches weights.

`score_outcome_report`'s own `notes` list already carries the sentence "Read-only: re-derive
`scoring_weights.yaml` from this evidence by hand (the fence forbids any automatic feedback into
the engine)". **That note renders on the page verbatim.** It is the most important sentence on the
surface and it is not the UI's to paraphrase.

The fence test gains an assertion that no module under `src/api/` can write `verdict_ledger` or
any scoring configuration.

---

## 8. Auth

Every `/portfolio/*` and `/pnl/*` route is `owner_only` and depends on `OwnerUser`. This needs no
new machinery — `src/api/deps.py::require_owner` carries the docstring "Gate for anything exposing
the book. **Applied to P3/P4 routes when they land.**" These are the routes it was written for.

The token stays out of the client bundle exactly as P2 left it. Nothing about the auth seam
changes.

---

## 9. Frontend

### 9.1 Routes and shell

`/portfolio` and `/pnl` are new. `src/api/routers/meta.py` flips both sections to
`available: true` and drops their "Arrives in P3" / "Arrives in P4" notes — `portfolio` in
milestone 3, `pnl` in milestone 5, each at the point the section actually works.

Every convention from `P0-P1-design.md` §8 and `web/CLAUDE.md` is inherited verbatim: dark only,
semantic tokens only, IBM Plex Sans and Mono with tabular figures, elevation by lightness,
state never encoded by colour alone, `prefers-reduced-motion`, zero em dashes in UI copy, and the
banned-words list.

### 9.2 The signature component: the money cell

P1's differentiator was the check ribbon and P2's was the command receipt. P3 and P4 render more
numbers than both put together, and the failure mode they invite is different from either: not
"did this happen?" but **"is this number what I think it is?"**

So the phase has one shared primitive, and every financial figure goes through it:

- **A realised figure and an unrealised figure never look alike.** They are different columns with
  different labels, and a total that mixes them says so.
- **`None` renders as `n/a` with the `.hatch` texture, never as `$0.00`.** This is `web/CLAUDE.md`
  law already; a P&L table is where breaking it is most expensive, because a fabricated zero in a
  money column reads as a real result.
- **Sign is carried by the number and a label, not only by colour.** `text-gain` and `text-loss`
  exist and are used, but a red figure is also a negative figure with a minus sign.
- **A gross figure says it is gross.** Where `commissions_complete` is false, the cell carries the
  qualifier rather than presenting an incomplete net as a net.
- **Every figure inherits the snapshot's `as_of`.** An unrealised mark from a snapshot two hours
  old is labelled with its age.

### 9.3 Charts

`recharts` for the equity curve and the breakdown panels; `lightweight-charts` is already loaded
for the price chart on the research page but is the wrong tool here, where the data is dozens of
daily points and developer ergonomics matter more than frame rate.

Two rules from `web/CLAUDE.md` bind hard in this phase. **Charts never animate their data in** — a
bar that grows on mount lies about its value during the animation. And a gap in the equity curve
renders as a gap.

### 9.4 Polling

TanStack Query, as P1 and P2. The portfolio refreshes on the snapshot cadence, because that is the
cadence the data actually has; a faster poll would return identical rows and imply a liveness the
system does not have. A `refresh` command polls `GET /commands/{id}` every two seconds until it
resolves, through P2's existing `useCommandStatus`, and the portfolio query invalidates when it
goes terminal.

---

## 10. Error handling and degradation

| Failure | Behaviour |
|---|---|
| No snapshot has ever been written | The explicit empty state of §4.5. Never zeros. |
| The monitor is down | The newest snapshot ages and is rendered stale with its real age. The portfolio does not claim to be current. |
| `refresh` with no broker connection | The command fails with `broker_unavailable` and the receipt says so. No row is written. |
| A snapshot write fails | Logged, swallowed, tick handling and roll alerts unaffected. The previous snapshot stays newest. |
| `journal` has gaps | The equity curve renders gaps. No interpolation. |
| `FillRow.commission` is null | Summed as zero, `commissions_complete` false, the figure labelled gross. |
| A campaign has legs whose candidates were pruned | The leg renders with the detail it has and is marked incomplete rather than dropped, so a total never silently loses a row. |
| No closed trades yet | `/pnl/system` returns `score_outcome_report`'s own empty-window report, whose `notes` already say "No closed trades in window". Rendered verbatim. |
| SQLite lock contention | Bounded backoff, then `503` carrying the last known `as_of`, per P2 §10. The client falls back to its cache. |
| The API process is down | The BFF proxy returns a JSON `502` with a readable `detail`, and a `504` if it times out. Before Milestone 0 it threw, and the browser got an HTML error page rendered as an error message. Both surfaces poll, so this is a routine state, not an exceptional one. |

---

## 11. Testing

**Python.**

- **The extraction is proven by the tests that already exist.** `reconcile.py`'s suite must pass
  unchanged after `_fill_economics` and `_classify` move to `src/reporting/legs.py`. Not adapted,
  not relaxed — unchanged.
- **Wheel scenarios, hand-built.** A CSP that expires worthless. A CSP assigned, then covered
  calls written, then called away. A roll chain of three legs. A leg with a null commission. A
  paper leg beside a live one. Each with its expected leg rows, campaign totals and outcomes
  written out by hand in the test, because a test that computes its expectation the same way the
  code does proves nothing.
- **`net_pnl` is `None` for every open leg**, asserted directly. The single most valuable
  assertion in P4.
- **The fence.** `src/engine/`, `src/execution/` and `src/strategies/` never import
  `src.reporting`. No module under `src/api/` can write `verdict_ledger` or a scoring config.
  `src/reporting/` never imports `src.claude`.
- **The snapshot writer.** A write failure does not propagate out of the monitor's refresh loop,
  asserted by making the write raise. The rate limit holds. Nothing is written outside market
  hours.
- **The fallback chain**, all three rungs, including the empty state.
- **`owner_only`** on every new route, asserted with a non-owner role.
- **The campaign cross-check compares gross to gross.** `campaigns.net_premium` excludes
  commissions and `PnlLeg.net_pnl` includes them (§6.1), so the reconciliation sums the legs'
  `credit - debit` before commissions, and a second test asserts the two views differ by exactly
  the commission total. A naive comparison would fail by that amount and prove nothing.
- **Regression.** Milestones 0, 1 and 4 touch trading code — the EOD orchestrator, the monitor
  triggers, the monitor, the drain, and the reconciler. Each runs the **full** suite, because a
  regression there is a trading regression.

**Frontend.** Vitest for the money cell's rules, including that `None` never renders as `$0.00`
and that a gross figure is labelled. React Testing Library for the ledger's grouping and filters.
Playwright for the one flow where a mistake is expensive: reading the portfolio and confirming
what it claims about freshness matches what the API said.

---

## 12. Risks and limitations

1. **The monitor becomes a database writer.** It is a live event loop whose real job is firing
   assignment and roll alerts. A snapshot write that blocks or throws inside the refresh loop is a
   trading incident, not a web bug. §4.3's guards are the mitigation and the test that makes the
   write raise is what keeps them honest.
2. **The reconciler inversion touches code that back-fills the outcome ledger.** The mitigation is
   that its existing tests must pass unchanged, which is a strong net — but the move is real and
   it is the highest-risk single edit in the phase.
3. **Two P&L numbers will visibly disagree.** `journal`'s premium cashflow and P4's paired
   realised P&L measure different things and will differ, sometimes substantially, whenever an
   assignment is involved. This is correct. Labelling is the entire mitigation, and an operator
   who reads the two as the same number will draw wrong conclusions.
4. **The equity curve is only as good as the journal.** Gaps are rendered as gaps, but a system
   that was down for a week has a curve with a week missing, and no amount of UI honesty makes
   that data exist.
5. **Snapshot freshness is a floor, not a guarantee.** Fifteen minutes is the *minimum* interval,
   not a promise. If the monitor is not running, the portfolio is as old as the last EOD run, and
   the only thing the design guarantees is that the screen says so.
6. **Commission data is incomplete by construction.** `FillRow.commission` is nullable and paper
   fills frequently carry none. Realised P&L in paper mode is closer to gross than net, and the
   `commissions_complete` flag is the only thing standing between that and a misleading total.
7. **`portfolio_snapshots` retention is a product decision in a config key.** Thirty days of
   intraday history supports the portfolio screen and nothing longer. An operator who later wants a
   year of intraday equity history needs a rollup, and this design does not build one.
8. **Milestone 0 changes behaviour that already exists.** Unifying the assignment-risk predicate
   widens what `/options/shorts` reports (positions 8 to 21 days out flip from `false` to `true`),
   and making the EOD run idempotent means a re-run now replaces the day's journal entry instead of
   failing. Both are corrections, both are tested, and both will look like regressions to anyone
   who reads the old behaviour as intended. The milestone file states each one explicitly so the
   change is attributable when someone notices.

---

## 13. Sequencing

| # | Milestone | Ends with |
|---|---|---|
| 0 | Baseline and pre-existing defects | A recorded baseline, an idempotent EOD run, one assignment-risk predicate, the campaign rollup's commission semantics pinned, a schema-freshness test, and P2's deferred findings closed. **No new capability.** |
| 1 | Portfolio spine | `portfolio_snapshots`, the monitor writer, the `refresh` handler, pruning, config keys. Nothing user-visible. |
| 2 | Portfolio read API | `/portfolio/summary`, `/positions`, `/campaigns`, `/calendar`. |
| 3 | Portfolio UI | The `/portfolio` page. Nav flips `portfolio` to available. |
| 4 | The P&L engine | `src/reporting/`, the dependency inversion, the accounting rules, the wheel-scenario suite. No UI. |
| 5 | P&L API and ledger UI | `/pnl/*`, the ledger page, the equity curve, CSV export. Nav flips `pnl`. |
| 6 | System performance and close-out | `/pnl/system`, the fence extensions, docs, `STATUS.md`. |

Milestones are strictly sequential and each ends green on the full quality gate. Milestones 1 and
4 are deliberately inert: 1 builds the data spine with no UI, 4 builds the accounting with no
routes. Both exist so that the first screen renders real numbers on its first day rather than
placeholders that get replaced.

**Milestone 0 builds nothing and comes first anyway.** Writing this design meant reading the code
it sits on, then auditing what P0, P1 and P2 shipped. That found nine defects that predate the
phase and are load-bearing for it.
The most consequential: `src/orchestrator/eod_report.py::_write_journal` does a bare
`session.add` against a table with a unique constraint on `entry_date`, `session_scope` re-raises,
and the call is unguarded — so a **repeated EOD run for the same ET day raises before the
reconciler, assignment auto-detection, and `save_position_snapshot` ever run.** §4.5's `eod`
fallback rung reads two of those outputs and §11's realised-P&L cross-check reads the third.
Building on that and fixing it afterwards would mean diagnosing failures in new code that new code
did not cause. The full list is in `milestones/P3-P4/M0-baseline-and-fixes.md`.

---

## 14. Documentation obligations

Per `CLAUDE.md`'s mandatory doc-update rule:

| Trigger | Files |
|---|---|
| New storage model `PortfolioSnapshotRow` | `ARCHITECTURE.md` `src/storage/` + data-flow sections |
| New package `src/reporting/` and modules `src/storage/portfolio_snapshots.py` | `README.md` layout table, `ARCHITECTURE.md` folder guide |
| New Pydantic schemas (`PnlLeg`, `CampaignPnl`, `PnlSummary`, `EquityPoint`, …) | `ARCHITECTURE.md` `src/common/` + data-flow sections |
| New API endpoints | `docs/web/api.md`, regenerate `docs/web/openapi.json` and `web/lib/api-types.ts` |
| `refresh` becomes a registered command kind | `docs/web/commands.md` — correcting the stub that already describes it |
| New config keys (`portfolio_snapshot_interval_minutes`, `portfolio_snapshot_retention_days`) | `ARCHITECTURE.md` config section, `SETUP.md` |
| The `src/reporting/` import fence | root `CLAUDE.md`, `docs/web/architecture.md` |
| P3 and P4 built, P5 still deferred | `STATUS.md` web platform table |

`CLAUDE.md`'s "Analytics tiers" section gains `src/reporting/` alongside the existing two tiers —
a third category, read-only, downstream of everything and upstream of nothing.
