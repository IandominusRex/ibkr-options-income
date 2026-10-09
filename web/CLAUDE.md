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
  layout.tsx        Fonts, <Rail/>, <Providers/>. The root row is `h-screen
                    overflow-hidden`, not `min-h-screen` — Rail and `<main/>`
                    each own their own `overflow-y-auto` instead of the whole
                    document scrolling as one, so the left rail stays pinned
                    in place (2026-09-23), and `Rail.tsx` (2026-09-23) is itself now `flex flex-col`: the nav list keeps its own
                    `overflow-y-auto` inside a `flex-1` wrapper, with `<SystemStatusCard/>` below it as a
                    sibling, outside the scroll area, so the status card stays visible regardless of nav-list
                    length while a page's own content scrolls
                    underneath it.
  page.tsx          Landing page: a header row with the page title and a visible
                    search-bar button (opens the same <CommandPalette/> ⌘K does — the
                    page owns `searchOpen` state and passes it as controlled
                    `open`/`onOpenChange` props), then WatchlistTable, then SectorGrid
                    (ordered by IV rank). A client component because the watchlist and
                    sector grid use react-query.
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
                    tab bar for Approvals / Submitted / Decided / Assessed /
                    Orders / Fills / Shorts. The Approvals tab renders <ApprovalsList/> (cards linking
                    to the detail page). Since M3 the cards and the detail page carry
                    live Approve / Reject controls through <DecideControls/> - confirm
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
                    The page owns a `submitted: Map<approvalId, CommandStatus>` state:
                    the Approvals tab's <ApprovalsList/> filters OUT any id present in
                    the map, the new Submitted tab's <ApprovalsList/> filters IN only
                    those ids, and both pass the same map down as `initialCommands` so
                    a card's in-flight receipt survives the unmount/remount the tab
                    switch causes. `onApprovalSubmitted` (fired by <DecideControls/>
                    the instant Approve is confirmed, before the network call even
                    resolves) adds to the map; `onApprovalSettled` (fired when the
                    command ends up failed/expired — it never left "pending"
                    server-side) removes from it, returning the card to Approvals.
                    `submitted` is also seeded from `loadAllPersistedCommands()`
                    (lib/commands.ts) in a `useEffect` after mount — not a `useState`
                    lazy initializer, which would run during SSR (no `localStorage`
                    there) and diverge from the client's first paint — so a page
                    reload while a command is mid-flight restores the card's Submitted
                    placement, not just its receipt (the receipt itself is restored
                    independently, inside <DecideControls/> — see components/options/
                    below).
                    Below the Approvals tab's list, <TickerPillBar/> renders a
                    scrollable row of pills — one per distinct `underlying` present in
                    the (visible, not-yet-submitted) approvals list, with its count.
                    It is purely presentational, driven by the same approvals array
                    the page already queries (`["options","approvals","pending"]` —
                    the identical key/queryFn <ApprovalsList status="pending"/> uses
                    internally, so react-query dedupes to one request), never a
                    separate dataset that could be empty while approvals are not.
                    Picking a pill sets the page's `symbolFilter` state, which
                    composes into <ApprovalsList>'s `filter` alongside the
                    `submitted` exclusion — the list narrows to that ticker; picking
                    the same pill again clears it. The pill row itself is unaffected
                    by the filter (it always lists every ticker currently visible),
                    so switching straight to a different ticker needs only one click.
                    The Decided tab renders <ApprovalsList status="all"/>, filtered
                    client-side to `status !== "pending"` — every terminal outcome
                    (approved, rejected, expired), not just rejected/expired, since an
                    approved approval drops out of both the Approvals and Submitted
                    views the moment its command applies and otherwise had nowhere
                    left to be tracked. The only tab that fetches every status rather
                    than pending-only; each row renders through the same
                    <DecideControls/>, which already renders a decided approval's
                    `Decision: …` line instead of controls.
  options/[approvalId]/  Approval detail: <ApprovalDetailCard/> with the five review
                    fields as labelled sections (<ReviewPanel/>), the ideal zone bar
                    (<IdealZoneBar/>), humanised gate reasons, the alternatives
                    table, a Fills section (rendered only when `detail.fills` is
                    non-empty — the approval-to-order-to-fill lineage the API now
                    carries on this one response, so tracing a candidate to its fill
                    price needs no second/third request to the Orders/Fills tabs),
                    and the same <DecideControls/> as the card — both surfaces decide
                    through one code path, including in-flight-command restoration
                    from `localStorage` (this page never receives `initialCommand`
                    from a parent, unlike the card, so it depends entirely on that
                    fallback). 404 renders a not-found state with a link back to the
                    list.
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
  pnl/              P&L console (P4 M5 Tasks 5.4-5.6; P3-P4 M6 Task 6.2 adds the
                    System tab). <PnlShell/> mounts <SummaryPanel/> (the pnl one,
                    not the portfolio one) and <EquityChart/> above a tab bar
                    (Ledger / Equity curve / System) that never remounts them. The
                    shell owns ONE filter state and composes it into one query
                    string driving the ledger fetch, the summary fetch, the
                    equity fetch, AND the CSV export href - the export must carry
                    the same filters the table renders, and a second composition
                    would let them drift. `book` lives inside that same filter
                    state, not a second `useState` - it used to be a separate
                    variable that a trailing `qs.set("book", book)` forced into
                    every query string, silently overwriting whatever
                    <LedgerFilters/>'s own Book dropdown had just emitted, which
                    made that dropdown a complete no-op (the request, and the
                    filter echo <LedgerTable/> renders back, always said "all"
                    no matter what was selected); and <SummaryPanel/> used to
                    fetch `?book=${book}` alone, ignoring every other filter, so
                    the headline totals stayed unfiltered while the ledger rows
                    below them narrowed to match a symbol/strategy/outcome/date
                    filter - `qsString` is now passed into it directly, the
                    same one string every consumer shares. `book` starts "all":
                    the ledger may list both books, and when the summary
                    refuses a mixed total (`422 mixed_book`) its panel renders
                    the book choice itself, writing back into the same filter
                    state via `onBookChange` - the shell never guesses the
                    operator's book. No write
                    anywhere on this page; the CSV link is a plain download, not
                    a command. The System tab is a second, independent filter
                    axis owned by the shell (since/until on outcome_date, not the
                    ledger's filters) driving its own `GET /pnl/system` fetch;
                    <SystemPanel/> itself is presentational (data prop in, like
                    <EquityChart/>, unlike the self-fetching <SummaryPanel/>) and
                    renders the score-vs-outcome report's notes in full and in
                    order, the blended-score and per-component buckets through
                    <ScoreBucketTable/> (n below 5 labelled "small sample" in
                    words), signal correlations through <CorrelationTable/> (null
                    `pearson_r`/half-splits render n/a), and the Claude-vs-
                    baseline agreement block - no control anywhere on the tab can
                    change a scoring weight, only the two date-window inputs.
  news/             News thread (docs/superpowers/specs/2026-10-09-news-thread-design.md
                    §7.6). `/news` mounts <NewsFeed/>: group chips (All / Macro /
                    Market / Tickers / Earnings / Briefs, `aria-pressed`) and a symbol
                    filter over GET /news/feed, each post a <NewsCard/>, with
                    <CalendarColumn/> (GET /news/calendar?days=7: economic events and
                    earnings, held names marked "held" in words) beside it.
                    `news/[symbol]` mounts <NewsTicker/>: the latest brief (its chart
                    inlined from GET /news/posts/{id}), the last 72 h of story clusters,
                    the next earnings date, and <BriefRequest/>, which POSTs a
                    `news_brief` command and shows a <CommandReceipt/> (polls the ticker
                    every 3 s while the request is pending or running). A missing
                    news.db (`available: false`) reads "The news service has not written
                    anything yet", never an error. Read-only otherwise.
  explain/          System Explanation console. Static content - no react-query, no
                    fetch anywhere on the page - a plain-English walkthrough of how the
                    pipeline works, adapted from ARCHITECTURE.md's "The pipeline, stage by
                    stage" section, so
                    a non-technical reader can visualise the system without reading the
                    .md files directly. <ExplainShell/> owns one `useState<TabKey>` (same
                    shape as PortfolioShell/PnlShell's tab bar) across eight subtabs -
                    Overview, Data In, Finding Trades, The Risk Gate, Claude's Role,
                    Approval & Execution, Watching & Adjusting, This Dashboard - mapped
                    1:1 to `TabKey`/`TAB_META`/`TAB_ORDER` in `components/explain/types.ts`,
                    the one place every other piece (tab bar, pipeline map, ties-into
                    chips) reads labels from so they can't drift apart.
components/
  shell/            Rail, RailSection, SystemStatusCard (react-query on GET /system/status,
                    `refetchInterval` 20s; renders one row per system with a state dot -
                    `bg-gain` for ok, a `border-loss` outline for down, `.hatch` texture
                    for both degraded and unknown, per this app's tri-tone rule - and,
                    below the label on every row (not just the clickable ones), a second
                    muted line rendering that row's `detail` text, since `degraded` and
                    `unknown` are distinguished only by it; a row with `log_key: null` is
                    not clickable; a failed fetch renders one `text-unknown` line, "Status
                    unavailable", instead of the row list),
                    SystemLogPanel (the per-row slide-over: focus-trapped `role="dialog"`
                    matching `ConfirmAction`'s pattern, rendered behind a `ConfirmAction`-
                    style `bg-scrim` backdrop so the inert-background implied by
                    `aria-modal` is also true visually, and mounted with `key={openRow.key}`
                    so switching rows never reuses stale level/focus state across an
                    instance; fetches `GET /system/{log_key}/log` on open only - no
                    auto-poll inside it - with a Warnings+/Info+ toggle and a manual
                    Refresh button; a fetch error renders "Could not load the log";
                    otherwise the response's `file_exists` flag picks the empty-state
                    message - "No log file yet" when the file itself is missing, "No
                    matching lines at this level" when it exists but nothing matched -
                    so a healthy daemon's clean log is never reported as if it had never
                    run)
  search/           CommandPalette (⌘K/Escape as before; controlled if `open`/
                    `onOpenChange` props are passed — the home page's visible search-bar
                    button drives it that way — otherwise falls back to its own internal
                    open state so ⌘K still works standalone anywhere it's mounted with
                    no parent wiring it up. Renders `role="dialog"`/`aria-modal`/
                    `aria-labelledby` and traps Tab the same way `ConfirmAction` does
                    (mirrors its focus-trap code exactly). The component itself never
                    unmounts on close — it renders `null` so the global ⌘K listener
                    keeps working — so unlike `ConfirmAction`'s unmount-cleanup trick it
                    watches the `open` prop's true→false edge directly: that edge clears
                    the search term/results (reopening starts fresh, never shows a stale
                    search) and returns focus to whatever had it when the palette opened.
                    The input is focused imperatively via a ref in that same open-edge
                    effect, not the native `autoFocus` attribute — `autoFocus` fires
                    during React's commit, before any effect can run, so it would steal
                    focus out from under the open-edge effect's own capture of the prior
                    trigger before that capture ever happened)
  home/             SectorGrid (react-query on GET /research/sectors, renders SectorCard
                    ordered by avg_iv_rank desc; a sector with no IV history sorts last),
                    SectorCard (sector name + count, daily change with sign + colour never
                    colour alone, best/worst movers, avg IV rank with contributing count so a
                    one-name average is visible), WatchlistTable (react-query on
                    GET /watchlist, add/remove via useMutation invalidating the list; the
                    add half is a typeahead over GET /research/search — the same pattern
                    universe/AddSymbol uses — so a typo can't reach the write route as a
                    raw symbol; a pick fires immediately with no confirmation dialog, this
                    per-user watchlist has no order consequence; the add input disables
                    while `addMutation.isPending` and a row's remove button disables while
                    `removeMutation.isPending && removeMutation.variables === thatSymbol`
                    (one shared mutation for the whole table, scoped to the row actually in
                    flight, not every row) — without this a fast double-click could fire
                    two POSTs/DELETEs with no feedback either was in flight, unlike every
                    other write control in this app (universe/AddSymbol, universe/
                    UniverseList's remove/revert) which already disable this way; an empty
                    watchlist renders one line of text plus the action — no decorative icon
                    circle, per the banned template)
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
  options/          ApprovalsList (react-query on GET /options/approvals?status=,
                    `status` prop is `"pending"` (default) or `"all"` — the latter is
                    how the Decided tab reaches decided approvals, since the
                    default query never returns them; renders ApprovalCard per row;
                    empty state is one line of text, customisable via `emptyText`; an
                    optional `filter` predicate narrows the one query client-side —
                    Approvals/Submitted each pass a complementary filter over
                    `submitted` (plus the page's `symbolFilter` on Approvals) rather
                    than issuing more fetches, and Decided filters `status`
                    itself (`!== "pending"`) since `status="all"` alone isn't narrow
                    enough; `initialCommands` (id → CommandStatus) and the
                    `onApprovalSubmitted`/`onApprovalSettled` callbacks pass straight
                    through to each card),
                    ApprovalCard (contract label, contracts, premium per share
                    and total, score, DTE, order state, the exact raise date/time via
                    `formatDateTime(approval.created_at)` — never a relative age, which
                    would read "just now" forever since `as_of` is a per-request
                    freshness stamp, not when the approval was raised; a why/risks
                    preview from `approval.review` when non-null, so triage from the
                    list needs no click-through to the detail page for the two most
                    load-bearing review fields; links to the detail page; mounts
                    DecideControls, forwarding `initialCommand`/
                    `onApprovalSubmitted`/`onApprovalSettled`), ControlsStrip (react-query on GET /options/controls,
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
                    their own command is in flight - including while a live
                    confirmation dialog is open, before it has a command id to
                    poll yet - and render a CommandReceipt; persists its in-flight
                    command to localStorage under the fixed key `halt-resume`
                    (singleton control, unlike the per-item decide flows, so no
                    id namespacing is needed) so a page reload does not drop a
                    pending halt/resume or strand its live confirmation; live-mode
                    responses route through the same second LIVE confirmation
                    shape as every other control), AutonomyControl
                    (M6: the four rungs render from the API's rungs array, never
                    hardcoded; a rung change click-through confirms showing the
                    current and target rungs; disables the same way and persists
                    to localStorage the same way as HaltControl, under the fixed
                    key `autonomy`; a refused promotion renders "promotion
                    refused" with the blockers through the receipt - `CommandReceipt`'s
                    `failedReason` reads `result.detail.blockers` as well as
                    `.reasons`/`.reason`, since `set_autonomy`'s `promotion_refused`
                    failure uses a different detail key than promote's
                    `gate_rejected` does; without that, every blocker silently
                    vanished and the receipt said only "promotion refused" with
                    no explanation - the
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
                    DecideControls uses, including the same `liveStep`-counts-
                    toward-`inFlight` fix (Promote stays disabled for the whole
                    window between the first confirm and the live release, not
                    just once a command id exists to poll) and the same
                    localStorage persistence (lib/commands.ts), keyed by
                    `promote:{candidate_id}` — namespaced so it never collides
                    with a DecideControls approval id or a ShortsRow
                    `short:{position_symbol}` entry, restored on a mount-only
                    effect so a page reload during a pending or
                    needs-confirmation promote does not silently drop it back
                    to a bare Promote button. Renders CommandReceipt with
                    order=null (a promote never has the working-order lifecycle
                    approve/reject do) - failed/gate_rejected reasons render
                    through CommandReceipt's existing humaniser unmodified; on
                    applied, a "View approval" link to /options/{approval_id}
                    renders only when result.approval_id is non-null),
                    OrdersTable (Working/All/Rejected filter buttons — Working is the
                    default and the only state this table fetched before rejected
                    orders (e.g. a live order-send-time re-gate rejection) had no
                    view anywhere in the web console; state badge is label+fill never
                    colour alone, null avg_fill_price renders "n/a" never "$0.00", a
                    Detail column renders `o.detail` (humanised, never a raw reason
                    code or Python list repr) or "n/a"),
                    FillsTable (recent fills with relative age), ShortsTable (open
                    short option positions, delta renders its source, snapshot age as
                    text not a dot, fired roll alerts render as text on the row with
                    the humanised trigger label + age + Claude's view labelled
                    "Model opinion (Claude)"; since M5 Task 5.2 each row carries a
                    "Propose a roll" control through <ShortsRow/> - the same
                    confirm-then-receipt shape AssessedRow uses for promote,
                    including the same liveStep-in-`inFlight` fix and the same
                    localStorage persistence keyed by `short:{position_symbol}`,
                    no_qualifying_roll renders as a plain answer not red chrome,
                    roll_already_working links to the in-flight approval, live-mode
                    second confirmation wired), ApprovalDetailCard (five review fields as a
                    two-column grid of tagged cards via ReviewPanel, IdealZoneBar with lo/hi/
                    min_credit markers, AlternativesTable, a Fills section rendered
                    only when `detail.fills` is non-empty (the approval-to-order-to-
                    fill lineage the API carries on this one response), 404 with
                    link back, DecideControls; fetches GET /options/controls itself
                    so the detail page's receipt can state a dead drain in words,
                    same as the list — drain_healthy defaults to true while loading
                    so an unloaded drain is not falsely reported as dead),
                    ReviewPanel (2026-09-23: rebuilt on explain/FactCard + Tag instead of
                    five plain `<h3>`/`<p>` sections, so why-attractive/risks/tradeoffs/
                    assignment/rolling read as five distinct, tri-tone-tagged ideas
                    ("Bull case"/"Bear case"/"Balance"/"Watch for"/"If challenged") rather
                    than one undifferentiated block - the same visual language the System
                    Explanation tab's ClaudePanel uses to describe this exact payload
                    shape; passes `bodyClass="text-sm text-content"` since this is Claude's
                    actual review a human is deciding on, not incidental caption text, so it
                    keeps FactCard's original, more prominent body weight rather than the
                    explain tab's smaller caption default; null review, or a review whose
                    fields are all empty strings, renders nothing at all, not a bordered
                    box), IdealZoneBar (bar with premium marked
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
                    sees the new OrderRow the drain created; accepts an optional
                    `initialCommand` — a command already known in flight when the
                    component first mounts, read once as the initial state like any
                    React initial-state value — so a card that moves between the
                    Approvals and Submitted tabs (which unmounts and remounts it)
                    restores its receipt instead of starting blank. A
                    `needs_confirmation` `initialCommand` restores into `liveStep`
                    (reopening the LIVE confirmation dialog), not `command` (a plain
                    receipt) — the instant-move-to-Submitted design means Approve can
                    resolve with `needs_confirmation: true` before the card has even
                    unmounted, and without this split that dialog was stranded on the
                    old mount with no control anywhere to release or cancel it.
                    `liveStep` also counts toward `inFlight`, disabling Approve/Reject
                    while that dialog is open — before its release there is no
                    command id yet to poll, so `current` alone missed this window.
                    When no `initialCommand` prop is given at all (a fresh mount, not
                    a tab-switch remount — the detail page, or a full page reload),
                    a mount-only effect falls back to `lib/commands.ts`'s
                    `loadPersistedCommand(approval.id)` (localStorage), applying the
                    same needs_confirmation split. A second effect mirrors whichever
                    of `liveStep`/`current` is the in-flight one to that same storage
                    key on every change, and clears it once `current` goes terminal —
                    keyed off `current` (the polled value), not the raw `command`
                    state, so a command that goes terminal purely via polling (no
                    further `setCommand` call in this component) still clears
                    correctly. Fires `onApprovalSubmitted(id, command)` the instant
                    Approve is confirmed and `onApprovalSettled(id)` if the command
                    ends up failed/expired),                     TickerPillBar (pure, prop-driven — no fetch of its own; takes
                    `approvals: ApprovalSummary[]`, `selected`, `onSelect` from the
                    page. A scrollable row below the Approvals list, one pill per
                    distinct `underlying` present in that array with its count;
                    picking a pill calls `onSelect(symbol)`, picking the same one
                    again calls `onSelect(null)` — the page composes `selected` into
                    <ApprovalsList>'s `filter`, so a pill filters the list rather
                    than expanding a second, separate contracts browser. Renders
                    nothing when `approvals` is empty — deliberately not an
                    <EmptyState/>, since <ApprovalsList>'s own empty state already
                    covers that case one element up),                     ConfirmAction
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
  pnl/              P4 M5 Tasks 5.4-5.6; P3-P4 M6 Task 6.2 adds System. PnlShell
                    (the /pnl page frame - one filter state composed into one
                    query string for the ledger, summary, equity and CSV
                    export; a second, independent since/until window state for
                    the System tab's own GET /pnl/system fetch; SummaryPanel
                    mounts above the tab bar and never remounts, matching
                    PortfolioShell's convention - the tab bar swaps
                    Ledger/Equity curve/System below it), SummaryPanel
                    (react-query on GET /pnl/summary - the pnl one; fetches
                    `?${qsString}`, the exact query string the shell passes in
                    as a prop, NOT its own `?book=${book}` composition - that
                    used to be the bug: every filter except book was silently
                    ignored, so the headline totals never matched a filtered
                    ledger; headline
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
                    upper-cases the symbol; book choices all/paper/live; local
                    `useState` per field, seeded once from the `filters` prop
                    via a lazy initializer - NOT a live-sync effect, which
                    would risk a slightly-stale response clobbering a value
                    mid-typed. `filters` is `PnlShell`'s own live filter draft,
                    not the backend's echoed response (`LedgerTable` renders
                    that echo separately) - seeding from an echo would lag the
                    fields one round trip behind every edit. The one thing
                    that needs the inputs to change without a keystroke of
                    their own - `SummaryPanel`'s "view in ledger" link setting
                    `symbol` externally - works by `PnlShell` remounting this
                    component with a fresh `key` (bumped only on that jump),
                    not a sync effect),
                    SystemPanel (P3-P4 M6 Task 6.2: presentational - takes
                    `data: SystemPerformanceResponse` as a prop like
                    EquityChart, not self-fetching like SummaryPanel, since
                    PnlShell owns the GET /pnl/system query and the
                    since/until window state; renders every note in
                    report.notes in full and in order - the read-only
                    "re-derive scoring_weights.yaml by hand" sentence is why
                    the surface is allowed to exist - then the agreement
                    block, then ScoreBucketTable/CorrelationTable only when
                    n_closed > 0 (no empty tables, no n/a rows, just the
                    note); the two date inputs carry
                    `data-role="window-control"` and are the ONLY
                    button/input/select anywhere in the panel - no apply
                    button, no suggested weight, no editable field),
                    ScoreBucketTable (blended-score bands or per-component
                    high/low split; a bucket with n below 5 renders "small
                    sample" in words beside the count - a win rate from a
                    handful of trades is not evidence), CorrelationTable
                    (signal, n, pearson_r, low/high-half mean P&L; null
                    pearson_r or either half-mean renders n/a, never a
                    fabricated correlation or average). No second Money
                    component here - pnl/ reuses portfolio/Money, adding a
                    prop if a variant is needed.
  news/             NewsCard (title, SGT+ET time, headline line with up to 3 inline
                    source links opening in a new tab, the textbook-vs-actual grid,
                    the 🧠 read with bull/bear, <VerdictPill/> - verdict as text plus an
                    icon, never colour alone - book and setup impact, digest sections,
                    update lines, optional chart), NewsFeed, CalendarColumn,
                    NewsTicker, BriefRequest (mirrors RefreshControl), `types.ts`
                    (mirrors src/api/models/news.py and the CardPayload schema) and
                    `format.ts` (SGT/ET time labels, verdict labels). Plain <img> for
                    the chart data URI and third-party thumbnails (`no-referrer`):
                    next/image would need every news host in remotePatterns.
  explain/          PipelineMap (the "you are here" diagram every subtab mounts at its
                    top: the five straight-line pipeline stages - data/ideas/gate/claude/
                    execution - as clickable boxes with the active one aria-current, plus
                    the watching loop and this-dashboard side nodes below, each a real nav
                    control via `onNavigate`, not decoration - this is what makes "every
                    subtab shows how it ties into the others" literally true rather than a
                    line of copy), PanelShell (the shared per-subtab layout: PipelineMap,
                    title + dek, freeform children, then TiesInto and SourceRefs - kept in
                    one place so no panel can forget a piece; runs the full width of the
                    main pane, no `max-w` cap - a first pass capped it at 70ch for prose
                    readability, matching the rest of this app's body-text convention, but
                    that same cap was also squeezing every FactCard grid and RangeBar down
                    to prose width, so it was dropped for all eight subtabs rather than
                    left in for some and not others), TiesInto (a reasoned chip
                    per related subtab - not just a label, a sentence on WHY they connect -
                    clicking one calls the same `onNavigate` the tab bar and the map use),
                    SourceRefs ("under the hood": the real file paths behind the plain-
                    English version, for anyone who wants to go past it), Callout (a
                    raised-by-lightness box for a hard invariant or notable guarantee -
                    "no LLM can place an order" - elevation marks it as load-bearing, per
                    this app's own rule; a `tone` prop - info/positive/caution, default
                    info - layers a second, deliberate accent on top by REUSING the app's
                    existing semantic tokens rather than inventing new ones: info=focus
                    (general emphasis, the app's one existing accent), positive=gain
                    (a safety guarantee - "paper by default"), caution=unknown (a
                    limitation or a "not yet automatic" caveat) - each tone also changes
                    the border treatment, not just the colour, so it still reads without
                    colour, same rule StageBadge/CheckRibbon already follow elsewhere in
                    this app), Tag (the small mono uppercase eyebrow a `<FactCard/>` or an
                    Overview card carries, coloured by the same three-tone palette),
                    FactCard (one bordered box per scannable fact - a tag, a title, a short
                    body - what every panel's enumerated content renders as instead of a
                    bullet list, since a list reads as one undifferentiated block and a
                    card grid reads as several distinct facts at a glance; an optional
                    `bodyClass` overrides the default caption-weight body text for a caller
                    whose content is substantive rather than incidental - reused this way by
                    `components/options/ReviewPanel.tsx`, the same cross-domain-reuse
                    convention `pnl/` already follows for `portfolio/Money`), RangeBar (a
                    labelled 0-100 range - "CSP delta target: 0.15-0.30" against "0.0 (deep
                    OTM) .. 1.0 (deep ITM)" - GatePanel's strike-targeting visual: the bound
                    labels sit ABOVE the track rather than inside the filled region, so a
                    narrow band's own two numbers can never collide into each other, which
                    a first pass with inline labels did), and one content panel per
                    `TabKey` (OverviewPanel/DataPanel/IdeasPanel/GatePanel/ClaudePanel/
                    ExecutionPanel/WatchingPanel/WebLayerPanel) - each panel's prose is
                    sourced from ARCHITECTURE.md's matching "The pipeline, stage by stage"
                    section (WebLayerPanel
                    instead mirrors docs/web/architecture.md's two-engine-model description,
                    since that mechanism isn't in README.md), built from FactCard grids and
                    Callouts rather than plain paragraphs wherever the content is a set of
                    parallel facts (ExecutionPanel additionally draws the four-rung
                    autonomy ladder as an increasing-fill bar row; WatchingPanel and
                    WebLayerPanel render their enumerated lists - the monitor's six
                    triggers, what this dashboard can propose - as a wrapped row of
                    `rounded-full border-focus/40 text-focus` chips). Every `SourceRefs`
                    file path is a real path checked against the tree at write time, not a
                    guess.
lib/
  api.ts            apiFetch + ApiError
  api-types.ts      Generated from /openapi.json by `npm run gen:api`
  commands.ts       submitCommand / confirmCommand / useCommandStatus (polls
                    GET /commands/{id} every 2s while pending, stops at a
                    terminal state — spec §9.4); loadPersistedCommand /
                    savePersistedCommand / loadAllPersistedCommands persist a
                    per-subject in-flight command to localStorage (key prefix
                    `ibkr-options:command:`) so every one of the three
                    confirm-then-receipt decide flows (DecideControls — the
                    approval card and the detail page; ShortsRow's roll
                    proposal; AssessedRow's promote) survives a full page
                    reload, not just a tab-switch remount. `subject` is a bare
                    approval id (number) for DecideControls, or a namespaced
                    string for the other two — `short:{position_symbol}`,
                    `promote:{candidate_id}` — so the three can never collide
                    in the same storage; `loadAllPersistedCommands` (approval
                    ids only, for the options page's `submitted` map) skips the
                    namespaced ones for free since they don't parse as a
                    number. Only ever holds a `status: "pending"` command
                    (including one awaiting the live second confirmation) — a
                    terminal command is removed, not stored. Every read/write
                    is wrapped in try/catch and fails silently to a no-op — a
                    private window, cleared site data, or a browser that
                    blocks storage access must not break the decide flow, only
                    its reload-survival.
  receipt.ts        receiptState, the receipt state machine (spec §9.2) — a
                    pure function, tested exhaustively in receipt.test.ts
  format.ts         formatMoney (compact $391.0B/$1.3M, "n/a" for unknown, "$0"
                    for a real zero), formatPeriod ("Sep 2024"), relativeAge
                    ("5m ago"/"3h ago"/"2d ago"/"1mo ago"), formatDateTime (the exact
                    moment, always rendered in labelled UTC regardless of viewer
                    timezone — "Sep 12, 2026, 2:05 PM UTC" — for places a relative age
                    would misleadingly decay to "just now" forever), UNKNOWN constant
```