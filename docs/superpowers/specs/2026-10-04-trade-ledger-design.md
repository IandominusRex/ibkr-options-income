# Design — Trade Ledger & Position Tracker

**Date:** 2026-10-04
**Status:** Approved design, pending implementation plan
**Supersedes:** the operator's hand-maintained Google Sheet options log (that sheet is kept; it
becomes a read-only mirror target — see §7). Complements `src/reporting/pnl.py` and the `/pnl`
page, which remain the *system-performance* view; this is the *whole-account* view.

---

## 1. Context and goal

The operator kept a Google Sheet with one row per option trade (Sell/Buy, Put/Call, Order Date,
Expiration, Ticker, Lots, Strike, Premium, Outcome, Capital, DTE, % Profit, Notes) plus header
tiles (Available Capital, Capital Utilised, Total Profit). It is maintained by hand.

The system already records its own executions (`fills`, `orders`, `campaigns`,
`src/reporting/pnl.py`), but **only orders it placed**: manual TWS trades, pre-system 2025
history, and broker-side assignment/expiry records never reach those tables, and nothing there
is user-editable.

**Goal:** a broker-truth ledger of *every* execution ever made on the IBKR account, rolled up into
trades → tickers → portfolio, viewable and editable (notes/tags/outcome overrides) on the web
dashboard with drill-down from all trades to a single ticker, and mirrored automatically to the
operator's Google Sheet.

**Success criteria**

1. Every execution in the account appears exactly once regardless of how many feeds reported it
   (live, Flex, CSV upload).
2. The operator's full 2025-04 → 2026-04 history loads from the Activity Statement CSV
   (`U…_AS_Fv2_….csv` format) with zero parse errors on the real file.
3. The trades table reproduces the sheet's columns and its `% Profit` formula exactly (e.g. NVDA
   138P 6/17→6/27/2025, $131 → **34.65%**; AMZN 207.5P 6/25→7/18/2025, $325 → **24.86%**).
4. A ticker page shows total P&L (options + stock + dividends), wheel-adjusted cost basis, and
   every trade on that ticker.
5. Notes/tags/outcome overrides survive any re-import.
6. The Google Sheet's `(auto)` tabs match the dashboard within ~1 minute of any ledger change.
7. Nothing in this feature is reachable from the risk engine, sizing, or strategies.

**Revisions made while planning (2026-10-05), after reading the real statement file** — these
supersede anything below that disagrees:

- **R1. No `broker_option_events` table.** Expiries/assignments/exercises are execution rows in
  the Activity Statement (`C;Ep` price 0 at 16:20 ET; option `A;C` + stock `A;O`/`A;C`; option
  `C;Ex` + stock `Ex;O`), and in Flex they arrive as Trades rows (`transactionType=BookTrade`,
  codes in `notes`). The Flex *OptionEAE* section is **not used in v1** (its quantity-sign
  convention is unverified); the first Flex pull is run with `--dry-run` against an imported
  CSV to confirm expiries/assignments line up (STATUS.md live-verification item). The builder
  only ever reads executions.
- **R2. Activity Statement rows are order-level** (`DataDiscriminator = Order`), not
  execution-level. A CSV row can be the VWAP of several fills. Rows are one of two
  `source_kind`s: `exec` (has an IBKR execId) or `order` (doesn't — every CSV row, and any Flex
  row lacking `ibExecID`). Cross-source dedupe is an **order-level twin pass**
  (`supersede_twins`), run after every ingest over the affected (contract, ET date) pairs, so
  arrival order doesn't matter:
  1. an `order` row is superseded by an `exec` *group* (same contract, same side, same ET date,
     same `perm_id`, or a single row when it has none) whose summed quantity equals it and whose
     VWAP is within 0.005;
  2. two `order` rows from **different `source`s** (csv vs flex) with the same contract, side,
     date, quantity and price: the later-ingested one is superseded.
  Within one CSV, identical rows are distinct orders (kept apart by `occurrence_idx`).
- **R11. Writes use the generic `POST /commands`** (kinds `ledger_import`, `ledger_annotate`,
  `ledger_ca_reviewed`), so the ledger router is read-only. Uploads accept the **Activity
  Statement CSV only**; Flex data arrives via the Web Service as XML.
- **R3. Trade = one opening order** (no per-close slices). Partial closes are listed under the
  trade; outcome is that of the largest closing quantity, flagged `mixed_close` when closes
  differ. **`order_key`** is source-independent — `sha1(contract ident | ET trade date | side |
  total qty | VWAP to 4dp | ordinal among identical orders that day)[:16]` — so a CSV order and
  its later exec-level twin have the same key. **Annotations are keyed by the opening order's
  `order_key`**; no re-keying is ever needed.
- **R4. Premium is the gross opening credit/debit** (what the sheet records — e.g. AMZN 207.5P
  = 325, not 323.84). `% Profit` = `premium / capital × 365 / DTE` exactly as the sheet.
  Separately, `net_pnl` = opening cash + closing cash + all commissions, and
  `annualised_net_pct` = `net_pnl / capital × 365 / days_held`. Both are shown.
- **R5. Available capital** = contributed capital + realised total P&L − capital utilised (all
  USD). No dependency on a snapshot's base-currency net liquidation.
- **R6. Flex pull runs as a step of the EOD report** (`src/orchestrator/eod_report.py` — the
  scheduler lives in `scripts/start.py`, there is no separate launchd job), plus
  `scripts/ledger_flex_pull.py` for manual runs (`--query-id` for a one-off 365-day backfill
  query, `--dry-run` to print counts without committing).
- **R7. Uploads are JSON** (`{filename, content}`; the browser reads the file as text), because
  the web proxy and `apiFetch` are JSON-only. Cap 5 MB.
- **R8. Account guard.** A statement whose account id differs from `IBKR_ACCOUNT` (when set) is
  rejected (`account_mismatch`). Multi-account is out of scope.
  > **Amended during implementation (controller ruling F4, Task 17):** the shipped guard locks
  > to `ledger.account` (new config key) if set, else the first CSV/Flex import's account (R8's
  > intent preserved, just not tied to `IBKR_ACCOUNT` specifically) — adopted because
  > `IBKR_ACCOUNT` is the **paper** account in this v1 deployment, and locking the ledger to it
  > would have claimed the ledger for paper on the very first import. See `CLAUDE.md`'s
  > "`src/ledger/` fence" note and `STATUS.md`'s trade-ledger entry for the live behaviour.
- **R9. Honest outcomes.** A short closed by a $0.01 buy-back on expiry day is `Bought back`
  (that's what IBKR records — e.g. NVDA 138P 6/27/2025), even though the old sheet called it
  `Expired`. The outcome override exists for exactly this.
- **R10. A trade past expiry with no closing record yet** (live data, Flex not yet run) shows
  outcome `Pending` rather than `Open`.

**Decisions taken in brainstorming**

| Question | Decision |
|---|---|
| Coverage | Everything at IBKR (system + manual + assignments/expiries), plus CSV upload |
| Surface | Web dashboard is master; Google Sheet is a one-way mirror |
| Sheet behaviour | Dashboard wins; system writes its own `(auto)` tabs; original tab untouched |
| History | Imported from IBKR statements (CSV), not from the sheet |
| Upload formats | CSV only (Activity Statement + Flex). PDF rejected with a pointer to the CSV |
| Currency | Native currency per trade/ticker; portfolio totals converted to USD at trade-date FX |
| Sheet "Capital" column | Interpreted as stock gain on a called-away / assigned-away leg |

## 2. Architecture

```
 IBKR TWS ──(execDetails + periodic reqExecutions sweep, exec process)──┐
 IBKR Flex Web Service ──(scripts/ledger_flex_pull.py, nightly launchd)─┼─► src/ledger/ingest.py ──► broker_* tables
 Web upload ──► app_commands(kind=ledger_import) ──► command drain ─────┘          │
 Web inline edit ──► app_commands(kind=ledger_annotate) ──► drain ──► trade_annotations
                                                                                    │
                                     src/reporting/trade_ledger.py (read-only builders)
                                          │                         │
                          src/api/routers/ledger.py           src/ledger/sheets_mirror.py
                                          │                         │
                                   web/app/ledger/*           Google Sheet "(auto)" tabs
```

### New modules

| Path | Tier / role |
|---|---|
| `src/ledger/__init__.py` | package |
| `src/ledger/contracts.py` | Parse IBKR option symbols (`AMD 29AUG25 157.5 P`) and Flex fields into a normalized `ContractKey(underlying, sec_type, right, strike, expiry, multiplier, currency)` |
| `src/ledger/activity_csv.py` | Activity Statement CSV parser → `ParsedStatement` (executions, option events derived from codes, dividends, withholding, deposits, corporate actions, FX rates) |
| `src/ledger/flex.py` | Flex Web Service client (SendRequest → GetStatement with backoff) + Flex XML/CSV parser → same `ParsedStatement` |
| `src/ledger/live.py` | Converts `ib_async` `Fill`/`Execution`/`CommissionReport` to `ParsedExecution` (never passes raw ib_async objects across the boundary) |
| `src/ledger/ingest.py` | The **only writer** of `broker_*` tables: idempotent upsert, cross-source dedupe/supersede, import-run bookkeeping |
| `src/ledger/annotations.py` | Writer for `trade_annotations` (called only from the drain handler) |
| `src/ledger/sheets_mirror.py` | Google Sheets writer (debounced full-tab rewrite) |
| `src/reporting/trade_ledger.py` | Read-only builders: executions → trades (FIFO, outcomes, rolls) → ticker roll-ups → portfolio summary |
| `src/api/routers/ledger.py` | Read endpoints + enqueue `ledger_import` / `ledger_annotate` commands |
| `scripts/ledger_flex_pull.py` | Nightly Flex pull entrypoint (launchd) |
| `scripts/ledger_import.py` | CLI import of a CSV file (same code path as the drain handler; for the initial backfill) |

The reporting builder lives in `src/reporting/` and so obeys that tier's rules: imports nothing
from `src.claude`, never imported by `engine/`, `execution/`, `strategies/`.

## 3. Data model (new ORM classes in `src/storage/models.py`)

### `broker_executions` — one row per IBKR execution

| Column | Notes |
|---|---|
| `id` | PK |
| `dedupe_key` | **unique**. `exec:<execId>` when the source has an execId (live, Flex); `csv:<sha1(contract_key, trade_time_s, qty, price, occurrence_idx)>` otherwise |
| `exec_id` | nullable (CSV has none) |
| `perm_id`, `ib_order_id` | nullable; used for order grouping and system/manual tagging |
| `account` | IBKR account id |
| `trade_time` | UTC datetime, second precision |
| `trade_date` | exchange-local date (for DTE/held-day math) |
| `underlying`, `sec_type` (`OPT`/`STK`), `right` (`P`/`C`/null), `strike`, `expiry`, `multiplier`, `currency` | from `ContractKey` |
| `quantity` | **signed** (+ bought, − sold), contracts or shares |
| `price` | per share |
| `proceeds` | signed cash, statement currency |
| `commission` | signed (negative = cost), statement currency |
| `open_close` | `O`/`C`/null |
| `codes` | raw IBKR code string (`A;O`, `C;Ep`, …) |
| `ibkr_realized_pnl` | from statement, for cross-check; nullable |
| `source` | `live` / `flex` / `csv` |
| `superseded_by` | nullable FK → `broker_executions.id`. Set on a CSV row when an execId-bearing row for the same execution arrives (or vice-versa at insert time). Builders ignore superseded rows |
| `book` | `system` / `manual` — `system` iff `perm_id`/`ib_order_id` matches an `OrderRow` |
| `import_run_id` | FK → `ledger_import_runs` |
| `raw` | JSON of the source record |

**Cross-source matching rule:** two rows are the same execution iff identical `ContractKey`,
`trade_time` within ±1 s, equal `quantity`, and `|price diff| < 1e-6`. When both exist, the
execId-bearing row wins; the other gets `superseded_by`. Within a single CSV, repeated identical
rows are distinguished by `occurrence_idx` (their order in the file), so two genuine identical
fills both survive and re-uploading the same file is a no-op.

Forex rows (`Asset Category = Forex`) are not executions for ledger purposes; they are read only
as FX-rate evidence.

### `broker_option_events` — assignment / exercise / expiry

`id`, `dedupe_key` (unique), `contract fields`, `event_date`, `event_type`
(`assigned`/`exercised`/`expired`), `quantity`, `source`, `import_run_id`, `raw`. From the CSV
these are **derived** from Trades rows whose codes contain `Ep` (expired, price 0), `A`
(assignment), `Ex` (exercise); from Flex, from the *Option Exercises, Assignments and
Expirations* section. The execution rows themselves are still stored (the stock delivery leg
`A;O`/`A;C` is a real share execution).

### `broker_cash_events` — dividends, withholding, deposits/withdrawals, fees, interest

`id`, `dedupe_key` (unique: `sha1(section, date, currency, description, amount)` +
occurrence idx), `event_type` (`dividend`/`withholding`/`deposit`/`withdrawal`/`fee`/
`interest`), `underlying` (nullable; parsed from dividend descriptions like `AAPL(US0378331005)
Cash Dividend …`), `date`, `currency`, `amount` (signed), `description`, `source`,
`import_run_id`.

### `broker_corporate_actions`

`id`, `dedupe_key`, `date`, `underlying`, `description`, `quantity`, `proceeds`, `raw`,
`reviewed` (bool, default false). **Stored and flagged, never auto-applied** to cost basis in v1.

### `fx_rates`

`date`, `currency`, `usd_rate` (unique on date+currency). Seeded from statement data
(Forex trades / Cash Report / Base-currency conversion info) and from Flex `ConversionRate`
records. Lookup falls back to the nearest prior date; if none, the converted total is reported as
`null` with a flag rather than guessed.

### `ledger_import_runs`

`id`, `source`, `filename`/`flex_query_id`, `started_at`, `finished_at`, `status`
(`ok`/`failed`), `counts` JSON (`new`, `duplicate`, `superseded`, `skipped`, `errors`),
`errors` JSON (list of `{line, section, message}` capped at 200), `period_start`, `period_end`.

### `trade_annotations` — operator edits

`trade_key` (unique; see §4 — stable across re-imports), `notes`, `tags` (JSON list),
`outcome_override` (nullable enum), `exclude_from_stats` (bool), `updated_at`, `updated_by`.
Kept separate from executions so no import can overwrite an edit.

Schema creation follows the existing `Base.metadata.create_all` + `_ensure_*` pattern in
`src/storage/db.py`.

## 4. Ledger logic (`src/reporting/trade_ledger.py`)

All functions are pure over rows loaded by a thin query layer; no writes.

### 4.1 Order grouping

Non-superseded executions are grouped into **orders**: same `perm_id` when present; otherwise
(CSV) same `ContractKey`, same `trade_time` to the second, same sign. An order's price is the
quantity-weighted average; commission is summed.

### 4.2 Trades (options)

Per `ContractKey`, FIFO-match opening orders against closing quantity (closing orders, option
events). A **trade** is one opening order plus the closing quantities matched to it; a partially
closed opening order splits into one trade per closing slice, each with proportional premium and
commission.

`trade_key` = `sha1(first execution's dedupe_key of the opening order + slice index)`. When a CSV
row is later superseded by its execId twin, annotation lookup also checks the superseded row's
key (the annotation is re-keyed on first read and the move is idempotent), so edits follow the
trade.

**Outcome** (sheet vocabulary):

| Outcome | Rule |
|---|---|
| `Expired` | closed by an `expired` event / `Ep` code |
| `Assigned` | short put closed by `assigned` |
| `Called away` | short call closed by `assigned` |
| `Exercised` | long option closed by `exercised` |
| `Bought back` / `Sold` | closed by an ordinary closing order |
| `Rolled` | closed by an ordinary order **and** a same-underlying, same-right opening order exists in the same trading session; the two trades are linked (`rolled_from` / `rolled_to`) |
| `Open` | unmatched remainder |

`outcome_override` from annotations replaces the computed outcome for display and statistics and
is shown with an "overridden" marker.

**Per-trade fields**

| Field | Definition |
|---|---|
| Sell/Buy | sign of opening order |
| Put/Call, Ticker, Strike, Expiry, Lots | from contract / opening qty |
| Order Date | opening `trade_date` |
| Close Date | closing event/order date (null if open) |
| DTE | `expiry − order_date` in calendar days (matches the sheet) |
| Days Held | `close_date − order_date`, min 1; for open trades, days to today |
| Premium | net cash on the option legs **after commissions**, in contract currency (opening proceeds + closing proceeds + commissions) |
| Capital | `strike × multiplier × lots` for short options; debit paid for long options |
| Return % | `premium / capital` |
| % Profit (annualised) | `premium / capital × 365 / DTE` when the trade ran to expiry/assignment (reproduces the sheet); `× 365 / days_held` when closed early or rolled |
| Stock gain | for `Assigned`→later-`Called away` share lots: realized stock P&L of the lot (the sheet's "Capital" column) |
| Book | `system` / `manual` |
| Delta / IV at entry | joined from `fills`/`candidates` when `book = system`; else null |
| IBKR Realized P/L | sum of `ibkr_realized_pnl` on the trade's closing executions (cross-check) |
| Notes, Tags | from annotations |

### 4.3 Stock lots

Share executions (including `A;O`/`A;C` deliveries) FIFO into lots per underlying. Each lot
records acquisition date/price/source (`bought` / `assigned`) and its disposal
(`sold` / `called away`) with realized P&L.

### 4.4 Ticker roll-up

Per underlying (native currency):

- Net option premium (all trades, after commissions), realized stock P&L, dividends − withholding,
  **total realized P&L**; unrealized P&L on open options + shares from the latest
  `PortfolioSnapshotRow`/`PositionSnapshotRow`, labelled with its age, `null` when no mark
  exists (never zero).
- Trade count, win rate (`premium > 0` on closed trades, excluding `exclude_from_stats`), average
  premium per trade, best/worst trade.
- Annualised return on capital-days: `Σ premium / Σ (capital × days_held) × 365`.
- Shares held, broker average cost (FIFO open lots), **wheel-adjusted cost basis**:
  `(Σ open-lot cost − net option premium on this underlying since the earliest open lot's
  acquisition date) / shares held`, breakeven = that per-share figure.
- Campaign timeline: contiguous sequences linked by rolls and assignment→CC→called-away.
- Open options with DTE; pending assigned shares awaiting call-away.

### 4.5 Portfolio summary

- Total profit (USD-converted sum of ticker total P&L).
- Contributed capital = Σ deposits − Σ withdrawals (USD-converted).
- Capital utilised now = Σ open short-put collateral (`strike × 100 × lots`) + Σ open stock lots
  at cost.
- Available capital = latest snapshot net liquidation − capital utilised (labelled with snapshot
  age; null if no snapshot).
- Win rate, monthly premium income series, cumulative realized P&L curve (by close date),
  breakdowns by strategy (`CSP` = short put, `CC` = short call, `long`, `stock`) and by book.
- Upcoming expiries (open options sorted by expiry).

## 5. Ingestion

### 5.1 Activity Statement CSV (`activity_csv.py`)

The file is multi-section: column 0 = section name, column 1 = `Header`/`Data`/`SubTotal`/
`Total`/`Notes`. A section can have several `Header` rows (e.g. Trades has one per asset class,
with different columns — the SGD-commission header for Forex). The parser keeps the **most
recent Header for that section** and zips subsequent `Data` rows against it; non-`Data` rows are
ignored. BOM is stripped.

Sections consumed: `Trades` (DataDiscriminator `Order`; asset categories `Stocks`,
`Equity and Index Options`; `Forex` → FX evidence only), `Financial Instrument Information`
(multiplier/expiry/strike/conid confirmation for option symbols), `Dividends`,
`Withholding Tax`, `Deposits & Withdrawals`, `Fees`, `Interest`, `Corporate Actions`,
`Account Information` (account id, base currency). All other sections are ignored.

`Date/Time` is `YYYY-MM-DD, HH:MM:SS` in the statement's timezone (US/Eastern for this account's
statements; confirmed from `Statement` section `Period`/notes at parse time — if absent, Eastern
is assumed and recorded on the import run).

Rows that fail to parse are collected per line; **an import is one transaction** — if any
`Trades` row fails, nothing is committed and the run is `failed` with the error list. Failures in
ignorable sections are reported but don't fail the run.

PDF uploads (by extension or `%PDF` magic) are rejected with: "PDF statements aren't supported —
in Client Portal → Statements, choose CSV as the format for the same statement."

### 5.2 Flex Web Service (`flex.py`, `scripts/ledger_flex_pull.py`)

Operator creates once (documented in SETUP.md) an Activity Flex Query with sections: Trades
(Execution level), Option Exercises/Assignments/Expirations, Cash Transactions, Corporate
Actions, Conversion Rates; format XML; period "Last 7 calendar days" (overlap is harmless —
ingestion is idempotent). `.env`: `IBKR_FLEX_TOKEN`, `IBKR_FLEX_QUERY_ID`.

The script: `SendRequest` → reference code → poll `GetStatement` with backoff (IBKR returns
"statement generation in progress" for up to a few minutes; give up after ~10 min, run `failed`)
→ parse → `ingest`. Scheduled via `scripts/launchd.py` daily at 18:30 America/New_York on
weekdays. Missing token/query id → logs one warning and exits 0 (feature off, not an error).

### 5.3 Live (`live.py`, wired in `approval_service`)

In the exec process (clientId 14), which already owns a connection:

- Subscribe to `ib.execDetailsEvent` / `ib.commissionReportEvent` → `ParsedExecution` →
  `ingest` (commission backfilled onto the row when its report arrives).
- A periodic sweep (every `ledger.live_sweep_minutes`, default 5, during RTH) of
  `reqExecutionsAsync()` reusing `src/execution/reconciliation.py`'s timeout wrapper, ingesting
  everything returned.

**Live-verification item:** whether TWS delivers *other clients'* (manual TWS, clientId 0)
executions to clientId 14 depends on the TWS "Master API client ID" setting. If it does not,
manual trades arrive via the nightly Flex pull instead (same-day, after close). SETUP.md will
document setting the Master API client ID to 14 for intraday visibility. The ledger is correct
either way; only latency differs.

The live hook writes **only** ledger tables and must never raise into order handling: every call
is wrapped, failures logged.

### 5.4 `ingest.py` contract

```python
def ingest(statement: ParsedStatement, *, source: str, filename: str | None) -> ImportResult
```

Single transaction; creates a `ledger_import_runs` row; upserts by `dedupe_key`; applies the
cross-source supersede rule; tags `book`; returns counts. After commit, signals the sheets mirror
(§7). Called from: drain handler (`ledger_import`), `scripts/ledger_import.py`,
`scripts/ledger_flex_pull.py`, and the live hook.

## 6. API and web

### 6.1 API (`src/api/routers/ledger.py`, read-only on the trading DB)

| Endpoint | Returns |
|---|---|
| `GET /ledger/summary` | §4.5 portfolio summary |
| `GET /ledger/tickers` | ticker roll-ups (table rows) |
| `GET /ledger/tickers/{symbol}` | one ticker: roll-up, campaigns, trades, lots, dividends, cost-basis walk |
| `GET /ledger/trades?symbol&right&outcome&book&tag&from&to&sort` | trade rows |
| `GET /ledger/trades/{trade_key}` | trade detail incl. executions and roll chain |
| `GET /ledger/trades.csv` | export with current filters |
| `GET /ledger/imports` | import run history + last Flex pull status + count of unreviewed corporate actions |
| `POST /ledger/import` | multipart CSV (≤ 5 MB) → enqueue `ledger_import` command (payload: filename + text) → returns command id |
| `POST /ledger/trades/{trade_key}/annotation` | enqueue `ledger_annotate` (payload: trade_key + changed fields) |
| `POST /ledger/corporate-actions/{id}/reviewed` | enqueue `ledger_annotate`-family command marking reviewed |

Writes go through `src/api/commands.py` only — the API still writes exactly one table.
The new command kinds are registered in `src/notify/command_drain.py`; `dedupe_key` is `NULL`
for both (repeats are harmless: imports are idempotent, annotations are last-write-wins).

### 6.2 Web (`web/app/ledger/…`, components under `web/components/ledger/`)

- **`/ledger` Overview** — stat tiles (Total profit, Contributed, Capital utilised, Available,
  Win rate, Premium this month), cumulative P&L chart, monthly premium bars, ticker table
  (sortable; click → ticker page), upcoming expiries.
- **`/ledger/trades`** — the sheet as a table: same column order as the sheet, then the extra
  columns; outcome pills coloured like the sheet (Expired green, Assigned red, Called away amber,
  Rolled blue, Open grey); filters; CSV export; row click opens a side panel (executions, roll
  chain, notes editor).
- **`/ledger/[ticker]`** — roll-up header, campaign timeline, trades table pre-filtered, share
  lots, dividends, cost-basis walk (step chart of broker cost → wheel-adjusted cost).
- **`/ledger/import`** — drag-and-drop CSV, live status of the queued command
  (pending → applied with counts / failed with line errors), import history, Flex status,
  corporate actions needing review.
- Inline edits show "saving…" until the command is `applied` (polls command status; existing
  pattern in the Options console).
- Nav entry "Ledger" added to the shell.

## 7. Google Sheet mirror (`src/ledger/sheets_mirror.py`)

- Auth: Google service account JSON. `.env`: `GOOGLE_SHEETS_CREDENTIALS_PATH`,
  `LEDGER_SHEET_ID`. Operator shares the spreadsheet with the service-account email (SETUP.md).
  Library: `gspread` (new dependency).
- Writes three tabs, creating them if absent: **`Ledger (auto)`** (sheet column order: Sell/Buy,
  Put/Call, Order Date, Expiration Date, Ticker, Lots, Strike Price, Premium, Outcome, Capital,
  DTE, % Profit, Notes, then Close Date, Book, Tags, Commission), **`Tickers (auto)`**,
  **`Summary (auto)`** (header tiles incl. Available Capital, Capital Utilised, Total Profit).
  The operator's original tab is never read or written.
- Each sync is a **full rewrite** of each tab (clear + batch update) so overrides and
  corrections propagate. Conditional formatting for outcome colours is applied on tab creation.
- Trigger: `ingest` / annotation commits set a `system_settings` dirty flag; the exec process
  runs a mirror loop that syncs when dirty, at most once per `ledger.sheets_min_interval_seconds`
  (default 60). The Flex script syncs at its end.
- Failures are logged and leave the flag dirty for the next attempt; never block ingestion.
  Missing credentials → mirror disabled with one log line.

## 8. Config

`config/settings.yaml`:

```yaml
ledger:
  live_sweep_minutes: 5
  sheets_min_interval_seconds: 60
  upload_max_bytes: 5242880
  flex_poll_timeout_seconds: 600
```

Secrets only in `.env`: `IBKR_FLEX_TOKEN`, `IBKR_FLEX_QUERY_ID`,
`GOOGLE_SHEETS_CREDENTIALS_PATH`, `LEDGER_SHEET_ID`.

## 9. Fences and invariants

- `src/ledger/` and `src/reporting/trade_ledger.py` are unreachable from `src/engine/`,
  `src/execution/` (except the live hook's wiring site in `approval_service`, which is in
  `src/notify/`), and `src/strategies/`. Add assertions to `tests/test_web_fence.py`.
- `src/ledger/` imports nothing from `src.claude`.
- The API still writes exactly one table (`app_commands`) — existing test stays green.
- No change to `fills`, `orders`, `campaigns`, `risk_limits.yaml`, `scoring_weights.yaml`.
- `ib_async` objects are converted to `ParsedExecution` inside `live.py`; nothing else sees them.

## 10. Error handling summary

| Situation | Behaviour |
|---|---|
| Malformed Trades row in CSV | whole import rolled back; run `failed` with per-line errors shown on the import page |
| Unknown code / unparseable non-trade section row | imported/skipped with a warning in the run's errors; run `ok` |
| Same file uploaded twice | all rows `duplicate`; no change |
| CSV row then live/Flex twin | CSV row superseded; trade and its annotation preserved |
| Corporate action | stored, flagged "needs review"; not applied |
| Missing FX rate | USD total for that item `null` + flagged; native figures still shown |
| No position snapshot | unrealized/available shown as `n/a`, never 0 |
| Flex not configured / times out | warning / run `failed`; live + CSV still work |
| Sheets not configured / API error | mirror disabled / retried on next change |
| Live hook exception | logged; never propagates into order handling |

## 11. Testing

- **Parser:** a scrubbed fixture CSV mirroring the real statement's shapes — multiple Trades
  headers, `O`, `C`, `C;Ep`, `A;C`, `A;O`, `O;P`, `C;P`, `C;IA`, `Ex;O`, `C;Ex`, SGD stock rows,
  Forex row, dividends with withholding, deposits, a corporate action, BOM. A one-off local test
  (skipped in CI if the file is absent) parses the operator's real file and asserts zero errors.
- **Dedupe:** same execution via CSV → live → Flex = one trade; same file twice = no-op; two
  genuine identical fills in one file both kept.
- **Ledger math:** FIFO with partial closes; outcome classification for every row of the table in
  §4.2; roll linking; NVDA example = 34.65%; wheel-adjusted cost basis through
  CSP → assigned → CC → called away with hand-computed numbers; capital utilised; USD conversion.
- **Annotations:** survive re-import and supersede re-keying; override changes outcome + stats.
- **Drain handlers:** `ledger_import` and `ledger_annotate` apply / fail correctly.
- **Sheets mirror:** fake gspread client — tab creation, full rewrite, debounce, failure leaves
  dirty flag.
- **Flex client:** mocked HTTP — in-progress backoff, success, timeout.
- **Fences:** new assertions in `tests/test_web_fence.py`.
- **Web:** Vitest for ledger tables, filters, ticker page, import status flow.
- Full gate: `python -m pytest -q`, `ruff check .`, `mypy src`, web `npm test`.

## 12. Docs to update (per CLAUDE.md)

`ARCHITECTURE.md` (new `src/ledger/`, `src/reporting/trade_ledger.py`, router, ORM classes,
schemas, scripts, config keys, web pages), `SETUP.md` (Flex query setup, Master API client ID,
Google service account, scripts table, `.env` keys), `STATUS.md` (built + live-verification
item §5.3 + out-of-scope list), `docs/web/commands.md` (`ledger_import`, `ledger_annotate`),
`README.md` (one line in the feature pitch), root `CLAUDE.md` reporting-tier section
(`trade_ledger.py`).

## 13. Out of scope (v1)

Two-way sheet sync; PDF parsing; automatic corporate-action cost-basis adjustment; tax-lot /
wash-sale reporting; multi-account aggregation; editing execution data itself (only annotations
are editable).
