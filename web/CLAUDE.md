# web/ — Next.js research console

Dark-only in P1. House law for this subtree; the dark token system in `app/globals.css`
is the source of truth for every colour.

## Invariants

- **Dark only.** A light theme later is a token-file change, not a refactor.
- **Semantic tokens only.** Never a raw palette class (`bg-white`, `bg-gray-800`) or a hex
  literal in a component. Consume colours through `bg-background`, `bg-surface`,
  `bg-elevated`, `text-content`, `text-muted`, `border-border`, `text-gain`, `text-loss`,
  `text-unknown`, `ring-focus`.
- **IBM Plex Sans** for prose, **IBM Plex Mono** for tickers and numbers. Apply `.tabular`
  to every numeric column so figures align.
- **Elevation by lightness, never border plus shadow stacked.** A surface change is a
  background change; a border sits on a lightness change, not on top of a shadow.
- **State is never encoded by colour alone.** The unknown state carries texture (`.hatch`)
  as well as `text-unknown`; selected never reads as "up" because focus is blue, not green.
- **Zero em dashes in UI copy.** Use a hyphen with spaces or rephrase.
- **Banned words:** "seamless", "robust", "unlock", "elevate".
- **`prefers-reduced-motion`** is respected globally (see `globals.css`).
- **Charts never animate their data in.** A bar that grows on mount lies about its value
  during the animation.

## Stack

- Next.js (App Router) + TypeScript + Tailwind v4 (CSS-first config in `globals.css`).
- `@tanstack/react-query` for server state (offline-first: `placeholderData` keeps the
  last good response rather than flashing a spinner).
- `cmdk` for the command palette, `lightweight-charts` and `recharts` for charts (later
  milestones).

## API proxy and the Vercel limitation

`web/lib/api.ts` fetches from `/api`, not from the upstream API directly. The proxy at
`app/api/[...path]/route.ts` injects `Authorization: Bearer ${API_TOKEN}` server-side
(`API_TOKEN` has no `NEXT_PUBLIC_` prefix, so Next.js cannot inline it into the client
bundle). This works under `next start` behind Tailscale. It does **not** survive a
Vercel-hosted frontend, because a route handler running in Vercel's cloud cannot reach
a private API at `127.0.0.1:8787`. The proxy fails closed when `API_TOKEN` is unset.

**The proxy fails soft, never with an HTML 500, when the upstream API is unreachable
or slow.** The bare `fetch()` to the upstream is wrapped in a `try`/`catch` with
`AbortSignal.timeout(UPSTREAM_TIMEOUT_MS)` (30s — generous, because
`POST /research/{symbol}/summary` runs a model call and a proxy that gives up too
early would turn a slow success into a fabricated failure). A connection failure
(FastAPI not running, crashed, restarting) returns `502` with `{"detail": "..."}`
JSON; a timeout returns `504` with `{"detail": "..."}` JSON. `apiFetch` (`lib/api.ts`)
surfaces `detail` as the `ApiError` message, so the UI renders a sentence, never a
page of markup. The `detail` text never includes the upstream URL, an exception
stack trace, or the word "Bearer" — the browser has no business seeing any of them.
P3/P4 poll this proxy continuously (portfolio refresh, command polling every 2s), so
this is the failure mode an API restart or outage produces constantly, not an edge
case.

**Response headers go through an explicit two-name allowlist, not a passthrough**
(`FORWARDED_RESPONSE_HEADERS` in `route.ts`): `Content-Type` and
`Content-Disposition`, nothing else. `Content-Disposition` rides along (M5 Task 5.3) so
a `/pnl/ledger.csv` download keeps its dated `pnl-ledger-YYYY-MM-DD.csv` filename
instead of saving as `ledger.csv` only by luck of the URL. Forwarding every upstream
header would leak server details (`Server`, `X-Powered-By`, trace headers) the browser
has no business seeing — the allowlist is the point, and a regression to a copy-all
would pass every other test in `route.test.ts` except the one that pins it. Adding a
third name is a separate decision with its own reason.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Dev server on `:3000` |
| `npm run build` | Production build |
| `npm run lint` | ESLint (next/core-web-vitals) |
| `npm run test` | Vitest (jsdom) |
| `npm run gen:api` | Regenerate `lib/api-types.ts` from the live `/openapi.json` (API must be up) |

## Layout

```
app/                App Router pages and the root layout
  globals.css       The dark token system (source of truth for colour)
  layout.tsx        Fonts, <Rail/>, <Providers/>
  page.tsx          Landing page: search (CommandPalette), then WatchlistTable, then
                    SectorGrid (ordered by IV rank). A client component because the
                    watchlist and sector grid use react-query.
  universe/         Universe page: react-query on GET /universe (M7: `lists[]`, one
                    UniverseListOut per section, replacing the old flat per-list
                    arrays), renders each list through <UniverseList/>. Writable since
                    M7 Task 7.5 (`editable: true`): would_own and watchlist accept add
                    and remove through <AddSymbol/> and each row's remove/revert
                    controls; indexes and actively_wheeling stay read-only with a note
                    that they are managed in config/universe.yaml. Still shows sector
                    tag, strike-band override, and marks which would_own names are
                    actively_wheeling vs dip-watch.
  stock/[symbol]/   Ticker page: react-query on GET /research/{symbol}, polls while
                    fundamentals/technicals/sentiment/news/checks is pending, mounts
                    <SectionShell/> per region, shows the delayed quote (with its age
                    and a "delayed" tag once stale) beside the header. <PriceChart/>
                    is NOT gated behind a Section's state — it fetches its own data
                    from GET /research/{symbol}/bars independently, so a technicals
                    outage must not hide it too
  options/          Options console (P2 M2 + M3 + M4 Task 4.3). <ControlsStrip/> at
                    the top (mode, autonomy rung, halt state, drain health), then a
                    tab bar for Approvals / Assessed / Orders / Fills / Shorts. The
                    Approvals tab renders <ApprovalsList/> (cards linking to the
                    detail page). Since M3 the cards and the detail page carry live
                    Approve / Reject controls through <DecideControls/> - confirm
                    dialog first, one POST, then a <CommandReceipt/> that never
                    overstates what happened. Since M4 Task 4.3 the Assessed tab's
                    <AssessedBrowser/> carries a live Promote control per row
                    (                    <AssessedRow/>) through the same confirm-then-receipt shape.
                    Since M5 Task 5.2 the Shorts tab's <ShortsTable/> carries a live
                    "Propose a roll" control per row (<ShortsRow/>) through the same
                    confirm-then-receipt shape; no_qualifying_roll renders as a plain
                    answer, roll_already_working links to the in-flight approval.
                    Since M6 the strip is live: <HaltControl/> and <AutonomyControl/>
                    sit in it, and a halted system renders an unmissable banner at
                    the top of the console with the reason and the time as text.
  options/[approvalId]/  Approval detail: <ApprovalDetailCard/> with the five review
                    fields as labelled sections (<ReviewPanel/>), the ideal zone bar
                    (<IdealZoneBar/>), humanised gate reasons, the alternatives
                    table, and the same <DecideControls/> as the card — both
                    surfaces decide through one code path. 404 renders a not-found
                    state with a link back to the list.
  portfolio/        Portfolio console (P3 M3 Tasks 3.1-3.5). <PortfolioShell/> mounts
                    <SummaryPanel/> once above the tab bar (stays mounted across tab
                    changes), then tabs between Positions / Campaigns / Calendar. Each
                    panel self-fetches its own data from `GET /portfolio/{summary,
                    positions, campaigns, calendar}`, but what each reads from its
                    response differs: <SummaryPanel/> reads both `source` and
                    `degraded` (and renders <DegradedNotice/> with the backend's own
                    note verbatim); <PositionsPanel/>/<CalendarPanel/> read `source`
                    only, for empty-state wording; `CampaignsResponse` carries
                    neither field (`{as_of, campaigns}` only), so <CampaignsPanel/>
                    reads neither. <RefreshControl/> mounts in the header and fires
                    `POST /commands` with kind "refresh" - one click, no dialog.
  pnl/              P&L console (P4 M5 Tasks 5.4-5.6). <PnlShell/> mounts
                    <SummaryPanel/> (the pnl one, not the portfolio one) and
                    <EquityChart/> above a tab bar (Ledger / Equity curve) that never
                    remounts them. The shell owns ONE filter state and composes it
                    into one query string driving the ledger fetch, the summary
                    fetch, the equity fetch, AND the CSV export href - the export
                    must carry the same filters the table renders, and a second
                    composition would let them drift. `book` starts "all": the
                    ledger may list both books, and when the summary refuses a
                    mixed total (`422 mixed_book`) its panel renders the book
                    choice itself - the shell never guesses the operator's book.
                    No write anywhere on this page; the CSV link is a plain
                    download, not a command.
components/
  shell/            Rail, RailSection
  search/           CommandPalette
  home/             SectorGrid (react-query on GET /research/sectors, renders SectorCard
                    ordered by avg_iv_rank desc; a sector with no IV history sorts last),
                    SectorCard (sector name + count, daily change with sign + colour never
                    colour alone, best/worst movers, avg IV rank with contributing count so a
                    one-name average is visible), WatchlistTable (react-query on
                    GET /watchlist, add/remove via useMutation invalidating the list; an
                    empty watchlist renders one line of text plus the action — no decorative
                    icon circle, per the banned template)
  checks/           CheckRibbon (one segment per check, `data-state` + hatch texture for
                    unknown, `role="img"` + `aria-label`, score line "X of evaluable" never
                    "X of total"), ChecksSection (per-category ribbons behind a
                    `<button aria-expanded>` that expands to CheckRow list on click,
                    collapses on a second click; a not-applicable category is disabled and
                    shows its `note` instead; renders leveraged-ETF decay Warnings above the
                    ribbons), CheckRow (statement + actual + threshold + state; unknown
                    renders `n/a` in `text-unknown`, never `0`)
  stock/            SectionShell (renders pending/unavailable states inline),
                    StatementsTable (normalised statements with filing traceability
                    in a `title` attribute using a hyphen not an em dash; fixed row
                    order; annual and quarterly sections; missing items render "n/a"
                    with `.hatch` texture, never "$0", never colour alone),
                    PriceChart (lightweight-charts candlestick + volume + SMA 50/200,
                    colours read from CSS custom properties at mount, no entry
                    animation), TechnicalsPanel (RSI/MACD/SMA/ATR + phase/regime,
                    null renders "n/a" never "0"), NewsPanel (newest-first, relative
                    age, sentiment chip is label+tint not colour-only), SentimentPanel
                    (composite score + per-source sample count; a source with no
                    tracked count renders "n/a samples", never a fabricated "0")
  options/          ApprovalsList (react-query on GET /options/approvals, renders
                    ApprovalCard per pending approval; empty state is one line of
                    text),                     ApprovalCard (contract label, contracts, premium per share
                    and total, score, DTE, order state; links to the detail page;
                    mounts DecideControls), ControlsStrip (react-query on GET /options/controls,
                    read-only mode/drain pills; since M6 also hosts the live controls -
                    <HaltControl/> and <AutonomyControl/> - plus the halted banner
                    rendered above the strip when halted is true, with the reason and
                    time as text, fill and text never colour alone, and a
                    "the trading service is not draining commands" line beside the
                    controls whenever drain_healthy is false),
                    HaltControl (M6: halt is ONE CLICK, no dialog - speed is the
                    feature, a test name says so; resume requires the typed word
                    RESUME through ConfirmAction and stays disabled until it matches
                    exactly; the deliberate M6 asymmetry, and the test names state
                    why so a later reader does not "fix" it; both disable while
                    their own command is in flight and render a CommandReceipt;
                    live-mode responses route through the same second LIVE
                    confirmation shape as every other control), AutonomyControl
                    (M6: the four rungs render from the API's rungs array, never
                    hardcoded; a rung change click-through confirms showing the
                    current and target rungs; a refused promotion renders
                    "promotion refused" with the blockers through the receipt - the
                    web is not the rung ladder's back door), StageBadge (text label + distinct
                    fill per AssessmentStage, never colour alone — reuses the check
                    ribbon's visual language), EmptyState (one line of text, no icon
                    circle), AssessedBrowser (grouped-by-symbol collapsible list with
                    per-stage counts, filterable by stage and symbol; fetches
                    GET /options/controls itself, same pattern as ApprovalsList, so
                    a promoted row's receipt can state a dead drain in words; each
                    contract renders through AssessedRow), AssessedRow (P2 M4 Task
                    4.3: one assessed-contract row, extracted from AssessedBrowser's
                    Group so the promote control has somewhere to live. A promote
                    button renders only when promotable is true AND strike/expiry
                    are non-null - a promotable row with either unexpectedly null
                    falls through to the non-promotable rendering rather than send
                    null to the API. A non-promotable row renders promote_note as
                    plain text, no control, disabled or otherwise. Clicking Promote
                    opens ConfirmAction first, stating in one sentence that the
                    contract is priced and gated again and an approval appears only
                    if it still passes; a score_floor row's dialog additionally
                    shows the blended score and promote_note's configured-minimum
                    text verbatim. On confirm, submitCommand("promote", {candidate_id,
                    symbol, strategy, strike, expiry}) fires once; in live mode the
                    response routes through the same second LIVE confirmation
                    DecideControls uses. Renders CommandReceipt with order=null
                    (a promote never has the working-order lifecycle approve/reject
                    do) - failed/gate_rejected reasons render through CommandReceipt's
                    existing humaniser unmodified; on applied, a "View approval" link
                    to /options/{approval_id} renders only when result.approval_id is
                    non-null),
                    OrdersTable (working orders, state badge is label+fill never
                    colour alone, null avg_fill_price renders "n/a" never "$0.00"),
                    FillsTable (recent fills with relative age), ShortsTable (open
                    short option positions, delta renders its source, snapshot age as
                    text not a dot, fired roll alerts render as text on the row with
                    the humanised trigger label + age + Claude's view labelled
                    "Model opinion (Claude)"; since M5 Task 5.2 each row carries a
                    "Propose a roll" control through <ShortsRow/> - the same
                    confirm-then-receipt shape AssessedRow uses for promote,
                    no_qualifying_roll renders as a plain answer not red chrome,
                    roll_already_working links to the in-flight approval, live-mode
                    second confirmation wired), ApprovalDetailCard (five review fields as five
                    labelled sections via ReviewPanel, IdealZoneBar with lo/hi/
                    min_credit markers, AlternativesTable, 404 with link back,
                    DecideControls; fetches GET /options/controls itself so the
                    detail page's receipt can state a dead drain in words, same
                    as the list — drain_healthy defaults to true while loading
                    so an unloaded drain is not falsely reported as dead),
                    ReviewPanel (null review renders nothing at all,
                    not a bordered box), IdealZoneBar (bar with premium marked
                    against lo/hi/min_credit, numbers visible, no fabricated
                    precision), AlternativesTable (other contracts assessed on the
                    same run), DecideControls (the shared decide flow for the card
                    and the detail page: Approve/Reject open ConfirmAction before
                    any request, one POST /commands, the returned id drives a
                    CommandReceipt; controls disabled while in flight; a decided
                    approval renders its decision, not controls; 403 renders a
                    permission message; in live mode a distinct, clearly labelled
                    second LIVE confirmation releases the confirm token; reads the
                    orders cache as the OrderListResponse shape <OrdersTable/>
                    stores — NOT a bare OrderSummary[] — and invalidates the
                    orders query when a command goes terminal so the next poll
                    sees the new OrderRow the drain created),                     ConfirmAction
                    (the confirmation dialog: exact contract and contract count in the
                    summary, optional case-sensitive typed-word gate (used by resume
                    in M6: releasing the kill switch re-arms execution; halting does
                    not - halt is one click), Escape/cancel call onCancel, focus
                    trapped while open and returned to the trigger on close,
                    aria-modal + labelled + visible focus ring, reduced motion
                    disables the entry transition), CommandReceipt (P2's signature component: state
                    from receiptState — pending never renders as applied, submitted
                    only when an order is working, filled only when a fill exists,
                    stalled stated in words with no spinner, intent id always
                    visible, failed renders the humanised reason plus detail codes)
  portfolio/        Money (null/NaN renders "n/a" with `.hatch` texture never "$0.00",
                    genuine zero renders "$0", colour never alone, `kind` renders as
                    word), FreshnessLabel (renders age in words - null says "not
                    captured", stale (>freshForMinutes) says "stale", never a dot),
                    PortfolioShell (mounts SummaryPanel once above tabs, swaps
                    Positions/Campaigns/Calendar tab content without remounting,
                    RefreshControl in header stays visible across tabs),
                    SummaryPanel (fetches GET /portfolio/summary, renders page-level
                    freshness and degraded notice once, empty-state renders one line
                    of text not decorative elements), DegradedNotice (renders note
                    verbatim, no paraphrase, styled as notice not error),
                    PositionsPanel (fetches GET /portfolio/positions, renders
                    freshness label unconditionally above content even when empty,
                    empty state distinguishes "no snapshot" from "no positions"),
                    PositionGroup (pure, prop-driven, renders ticker once above stock
                    and option legs), StockLegRow (shows shares, avg_cost always,
                    adjusted cost only when non-null with label in words),
                    OptionLegRow (direction/DTE/moneyness render as word or "n/a"
                    never implied or zeroed, delta renders with source, unknown state
                    renders "Assignment risk" in words), CampaignsPanel (fetches
                    GET /portfolio/campaigns, status/symbol filters flow into URL and
                    query key for real backend refetch not client-side .filter()),
                    CampaignThread (pure, renders symbol + rolled-up financials),
                    CalendarPanel (fetches GET /portfolio/calendar, renders freshness
                    and expiry grid with consequence text per entry, "unknown"
                    consequence is a named state), RefreshControl (one click no dialog,
                    fires POST /commands kind "refresh", invalidates portfolio queries
                    on terminal, `broker_unavailable` renders as plain answer through
                    `CommandReceipt`'s `plainReasons` prop not red failed chrome,
                    reuses submitCommand/useCommandStatus/CommandReceipt).
  universe/         M7 Task 7.5. UniverseList (one GET /universe section: heading with
                    entry count, a row per entry with sector tag, strike-band
                    override, and, for would_own only, a wheeling/dip-watch tag; a
                    non-overridable list renders a config/universe.yaml note instead
                    of controls, gated on `list.overridable` in addition to the
                    backend's own gating), OverrideBadge (author + timestamp +
                    revert for an overridden entry; the YAML base row stays visible,
                    never hidden, even when removed; revert fires the opposite
                    action - add for a removed entry, remove for a present one; purely
                    presentational - onRevert is a callback prop, not a mutation of
                    its own), AddSymbol (typeahead over GET /research/search so a
                    typo cannot reach the write route as a raw symbol; adding to
                    would_own opens a ConfirmAction naming the cash-secured-put/
                    assignment consequence, adding to watchlist fires immediately
                    with no dialog). AddSymbol and UniverseList route mutations
                    through submitUniverseCommand (lib/commands.ts) and render a
                    CommandReceipt.
  pnl/              P4 M5 Tasks 5.4-5.6. PnlShell (the /pnl page frame - one
                    filter state composed into one query string for the ledger,
                    summary, equity and CSV export; SummaryPanel mounts above
                    the tab bar and never remounts, matching PortfolioShell's
                    convention - the tab bar swaps Ledger/Equity curve below
                    it), SummaryPanel
                    (react-query on GET /pnl/summary - the pnl one; headline
                    figures, by-strategy/by-symbol breakdowns, best/worst legs
                    each rendered as a button that jumps the shell to the
                    Ledger tab filtered to that leg's symbol - the ledger has
                    no per-candidate filter, so symbol is the closest real
                    cross-reference; renders as plain text instead when no
                    `onSelectLeg` is wired;
                    `win_rate: null` renders n/a never "0%"; a 422 mixed_book
                    renders a labelled book-choice group and an explanation in
                    plain words, NOT alert chrome - having both books is a
                    normal situation, not a failure; `commissions_complete:
                    false` renders the gross qualifier on the headline realised
                    figure through Money's `complete` prop), BreakdownTable
                    (buckets in build_summary's own order - realised descending,
                    ties by label; a bucket with n_closed 0 renders n/a in its
                    rate columns, never 0%), EquityChart (Recharts line chart
                    over GET /pnl/equity - connectNulls OFF so a gap renders as
                    a gap not a fabricated bridge, isAnimationActive false on
                    every series, colours read from CSS custom properties at
                    mount like PriceChart, premium_cashflow labelled "premium
                    cashflow" never "realised P&L", the start date stated in
                    words beneath since the curve is the system's history, an
                    empty curve renders one line of text not an empty frame;
                    Recharts does not expose connectNulls/isAnimationActive as
                    DOM attributes so each series mirrors its real props onto
                    hidden data-series elements for the tests to read),
                    LedgerTable (the filter echo so a client can prove what it
                    is looking at; marks_as_of null renders "no marks
                    available" beside the unrealised column and every
                    unrealised cell renders n/a; an empty ledger renders one
                    line of text, no icon circle), CampaignRow (one campaign
                    thread collapsed with symbol/status/net/leg count,
                    expanding through <button aria-expanded> to its legs in
                    order; a null option_unrealized renders n/a never $0.00),
                    LegRow (one leg row; an open leg's realised column renders
                    n/a never $0.00 - an open leg has a mark, not a result;
                    commissions_complete false renders the gross qualifier;
                    realised and unrealised are separate columns with distinct
                    headers; every numeric column carries .tabular),
                    LedgerFilters (drives the query string, never client-side
                    array filtering, so the CSV export gets the same rows;
                    upper-cases the symbol; book choices all/paper/live). No
                    second Money component here - pnl/ reuses
                    portfolio/Money, adding a prop if a variant is needed.
lib/
  api.ts            apiFetch + ApiError
  api-types.ts      Generated from /openapi.json by `npm run gen:api`
  commands.ts       submitCommand / confirmCommand / useCommandStatus (polls
                    GET /commands/{id} every 2s while pending, stops at a
                    terminal state — spec §9.4)
  receipt.ts        receiptState, the receipt state machine (spec §9.2) — a
                    pure function, tested exhaustively in receipt.test.ts
  format.ts         formatMoney (compact $391.0B/$1.3M, "n/a" for unknown, "$0"
                    for a real zero), formatPeriod ("Sep 2024"), relativeAge
                    ("5m ago"/"3h ago"/"2d ago"/"1mo ago"), UNKNOWN constant
```