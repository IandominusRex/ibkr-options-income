# web/ — Next.js research console

House law for this subtree; the token system in `app/globals.css`
is the source of truth for every colour.

## Invariants

- **Light by default, dark by choice.** `data-theme` on `<html>` is set before paint by
  `THEME_INIT_SCRIPT` (`lib/theme.ts`); the preference (light / dark / system) lives in
  `localStorage` key `ibkr-theme`. `web/DESIGN.md` is the visual authority.
- **Semantic tokens only.** Never a raw palette class (`bg-white`, `bg-gray-800`) or a hex
  literal in a component. Consume colours through `bg-background`, `bg-surface`,
  `bg-elevated`, `text-content`, `text-muted`, `border-border`, `text-gain`, `text-loss`,
  `text-unknown`, `ring-focus`.
- **Hanken Grotesk** for everything; **Red Hat Mono** for stub and ledger figures. Apply
  `.tabular` to every numeric column so figures align.
- **Lime means act.** `bg-primary` only on primary actions, the pending-count badge, the pay
  meter and the "Expires today" status word.
- **No shadows** except the review sheet and the confirm dialog; elevation is tonal
  (`background` → `surface` → `sunk`).
- **Elevation by lightness, never border plus shadow stacked.** A surface change is a
  background change; a border sits on a lightness change, not on top of a shadow.
- **State is never encoded by colour alone.** The unknown state carries texture (`.hatch`)
  as well as `text-unknown`; selected never reads as "up" because focus is ink, not green.
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
| `npx openapi-typescript ../docs/web/openapi.json -o lib/api-types.ts` | The same, offline, from the committed contract (`tests/test_openapi_current.py` keeps that file current) |

## Layout

```
app/                App Router pages and the root layout
  globals.css       The payslip token system, light (`:root`) and dark
                    (`[data-theme="dark"]`), the source of truth for colour; the old
                    semantic names are re-pointed, plus `--shadow-sheet`, `.hatch`,
                    `.tabular`, the ink `::selection` and the sheet keyframe
  layout.tsx        Fonts (Hanken Grotesk, Red Hat Mono via next/font),
                    THEME_INIT_SCRIPT in <head> (no theme flash), <Providers/>, then
                    the shell: <Rail/> (from 768px) beside a column holding
                    <HaltedBanner/> and <main/>, and <TabBar/> (phones). The root row
                    is `h-dvh overflow-hidden`: Rail and `<main/>` each own their own
                    scroll, so the rail stays pinned while a page scrolls.
                    Its `metadata.title` is `{ default: "IBKR Income", template: "%s · IBKR Income" }`
                    (web overhaul Part 4), so a route sets only its own name.
  not-found.tsx     The root not-found page (web overhaul Part 4): one Card, "This page does not
                    exist", one secondary "Go to Home" link, `metadata.title` "Not found".
  error.tsx         The root error page (client component): one Card, "This page could not be
                    shown", the error's `digest` as "Reference <digest>" in the stub face when it has
                    one (the error's own message is never printed), and one secondary "Try again"
                    that calls `reset`. No `loading.tsx` (every page draws its own `role="status"`
                    skeleton) and no `global-error.tsx` (the root layout renders no data). Both are
                    pinned by `boundaries.test.tsx`.
  titles            Every route has its own title (`titles.test.ts` pins them; since web overhaul Part 6 a
                    dynamic segment is decoded through lib/segment.ts, so a malformed `%` keeps the raw
                    segment instead of throwing): a server page exports
                    `metadata`; a client page gets a sibling server `layout.tsx` that renders
                    `children` and exports `metadata`, or `generateMetadata` for a dynamic segment
                    (`more`, `more/claude`, `research`, `research/universe`, `stock/[symbol]`,
                    `news/[symbol]`, `ledger/ticker/[symbol]`, `positions/[underlying]/[slug]`,
                    `trades/[approvalId]`). Home keeps the default.
  page.tsx          Home (web overhaul Part 1): <HomePage/> (features/home/) inside a
                    Suspense boundary (the strategy switcher reads `?strategy=` through
                    useSearchParams). The old landing page moved to research/.
  positions/[underlying]/[slug]/  A position's page (web Home follow-ups, 2026-10-15), reached
                    from a row of Home's Positions card: <PositionPage/> (features/position/).
                    The slug is `2026-11-21_P180` (an option contract), `shares` or
                    `spread-<id>`.
  trades/           Trades (web overhaul Part 2). `page.tsx` mounts <TradesPage/>
                    (features/trades/) inside a Suspense boundary: the strategy switcher
                    (the view chips follow it: the wheel, All / CSPs / CCs, gets Proposals,
                    History and Assessed; Credit spreads gets Spreads only and hides the
                    chips), the view in `?view=` with a smart default (Proposals when
                    something in the strategy waits on you, History otherwise, decided once
                    per visit; `?view=working` and `?view=decided` open History), History's
                    New York day in `?day=` (Today sits left of the previous and next arrows so they
                    never move; next from a past day goes to the following day with trades, or back
                    to today when none is left), and the "not draining commands" warning
                    (<DrainWarning/>) above the view. The old tab bar, the controls strip,
                    <TickerPillBar/>, the Working and Decided tabs and the Shorts tab are
                    gone (the strip's file was deleted in Part 4): halt, resume, the autonomy rung and roll mode live in the bot
                    card, Propose a roll on the short option's position page.
  activity/         Activity (web overhaul Part 3; `/pnl` redirects here). `page.tsx` mounts
                    <ActivityPage/> (features/activity/) inside a Suspense boundary: the view chips
                    and the view in `?view=pay|ledger|fills|system` (default Pay; a junk value is
                    Pay), and Pay's month in `?month=YYYY-MM`. Pay is a month as a stub, then the
                    totals since the system began, the equity curve and the legs under one set of
                    filters; Ledger is the broker-truth ledger's overview (components/ledger/);
                    Fills and orders is three lists that are never merged (the system's orders and
                    fills, IBKR's executions); System is the sizing record above the score against
                    outcome. Nothing on the page sends a command: the CSV links are downloads and
                    the refresh icon beside the title only asks for the page's queries again.
  more/             More: the bot card (opens Bot controls), the theme toggle (Light /
                    Dark / Follow OS), <TargetCard/> (features/more/: the monthly income
                    target as none, a fixed amount, a percent of the account or a percent
                    of an amount, saved through the `set_income_target` command), links to
                    Research, Universe, News, Ledger, How it works, What Claude knows and
                    statement import,
                    <SystemStatusCard/> (system health lives here now, not in the rail)
                    and Credits (the chart library's licence link to tradingview.com, which
                    left the chart's corner).
  more/claude/      What Claude knows (market picture build, 2026-10-22): `page.tsx` mounts
                    <ClaudeContextPage/> (features/claude-context/), reached from a row on More.
                    Read-only: one request, `GET /claude/context`, and five cards (Regime and
                    limits, Market picture, What each Claude call reads, Dropped as noise, Names).
                    No news service says so in a sentence and the regime still shows.
  research/         Research (web overhaul Part 6): page.tsx only mounts
                    features/research/ResearchPage (the title with Search, which calls
                    lib/search.ts `openSearch` to open the shell's one palette, and a Universe
                    link; Top opportunities; then Your watchlist and the Sectors card).
  research/universe/  (moved from universe/; `/universe` redirects here) Universe page; since web overhaul
                    Part 6 page.tsx only mounts features/universe/UniversePage (a back link to Research,
                    one card per list, two columns from 1024px, loading and failure in words). What
                    follows is unchanged: react-query on GET /universe (M7: `lists[]`, one
                    UniverseListOut per section, replacing the old flat per-list
                    arrays), renders each list through <UniverseList/>. Writable since
                    M7 Task 7.5 (`editable: true`): would_own and watchlist accept add
                    and remove through <AddSymbol/> and each row's remove/revert
                    controls; indexes and actively_wheeling stay read-only with a note
                    that they are managed in config/universe.yaml. Still shows sector
                    tag, strike-band override, and marks which would_own names are
                    actively_wheeling vs dip-watch.
  stock/[symbol]/   Ticker page: page.tsx mounts features/stock/StockPage (web overhaul Part 5);
                    the sibling layout.tsx sets the title. <PriceChart/> is NOT gated
                    behind a Section's state: it fetches GET /research/{symbol}/bars
                    itself, so a technicals outage must not hide it too
  options/          (RETIRED) The old tabbed options console. `/options` and `/options/:id`
                    redirect (307) to `/trades` and `/trades/:id` in next.config.ts; what it
                    did lives under trades/ above and features/trades/ below, and its
                    components stay in components/options/.
  trades/[approvalId]/  The approval detail page, restyled in Part 2 (a payslip shell with its
                    own loading and not-found states around <ApprovalDetailCard/>,
                    components/options/ApprovalDetail.tsx): <BackToTrades/>, then the
                    trade (the title, a status word and where it came from, one
                    consequence-first sentence, the stub, the facts and the IV-rank tag; a
                    roll shows its two legs and the net at the quotes it was priced at,
                    labelled as the quote and never a fill; who decided, in words, from
                    `decided_by` only), Claude's review (<ReviewPanel/>, labelled as
                    Claude's), the decision in a 340px column from 1024px (the unchanged
                    <DecideControls/>, still fed from GET /options/controls so the receipt
                    can say a drain is dead), the ideal zone as two sentences (the strike
                    against the strike zone, the premium against the least credit worth
                    taking; the two units are never plotted on one axis), and the
                    alternatives and fills as rows. The same in-flight-command restoration
                    from `localStorage` as before, since this page never receives
                    `initialCommand` from a parent.
  portfolio/        Portfolio (web overhaul Part 3). `page.tsx` mounts <PortfolioPage/>
                    (features/portfolio/) inside a Suspense boundary: the title with <RefreshControl/>
                    at its right (the page's one write: `POST /commands` kind "refresh", one click,
                    no dialog), the Account card, the view chips and the view in
                    `?view=positions|campaigns|calendar` (default Positions; a junk value is
                    Positions). Positions groups the book by name over Home's rows, Campaigns keeps
                    its Status and Symbol filters in the request, Calendar its horizon. The old
                    portfolio page frame was deleted in Part 4 (see components/portfolio/).
  ledger/           The ledger's own routes. `/ledger` has no page: next.config.ts redirects it (307)
                    to `/activity?view=ledger`. `ledger/trades`, `ledger/ticker/[symbol]` and
                    `ledger/import` keep their routes, sit in <LedgerShell/> (components/ledger/),
                    lead back with <BackToLedger/> in place of the old sub-navigation, and open a trade
                    in the Sheet. The rail still marks Activity current on them.
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
                    shape as the old Portfolio and P&L tab bars, since deleted) across eight subtabs -
                    Overview, Data In, Finding Trades, The Risk Gate, Claude's Role,
                    Approval & Execution, Watching & Adjusting, This Dashboard - mapped
                    1:1 to `TabKey`/`TAB_META`/`TAB_ORDER` in `components/explain/types.ts`,
                    the one place every other piece (tab bar, pipeline map, ties-into
                    chips) reads labels from so they can't drift apart.
components/          Where new code goes (web overhaul Part 4, HANDOFF D4): `features/`. `components/`
                    keeps `ui`, `shell`, the protected `options` controls, `value` and the survivors
                    below; the earlier idea of folding the domain folders into `features/` was cut.
  ui/               Web overhaul Part 1: the data-free payslip primitives (web/DESIGN.md
                    Components). Button (primary lime / secondary / quiet, fully round,
                    17px/700, 0.98 press only under motion-safe), Card (white on paper, no
                    border, no shadow), SegmentedControl (track / chips / quiet; selected
                    is an ink fill with aria-pressed, never lime; below 768px each pill gets
                    a centred 44px hit area), StatusWord (neutral / flag / today), Meter
                    (unknown is hatched, never 0%), Disclosure (a real button with
                    aria-expanded; the whole pressed-sage block is the target; the panel
                    appears in place), Stub (the perforated sum; each explained line is a
                    button at least 24px tall; unknown is n/a + hatch) and Sheet (bottom
                    sheet on phones, right sheet from 640px, portaled to <body>, focus
                    trapped by lib/useFocusTrap.ts, which hands Escape and Tab to a nested
                    ConfirmAction; the only shadow besides the confirm dialog). field.ts holds
                    FIELD and FIELD_LABEL, the `field` component's classes, shared by every labelled
                    input and select (Portfolio, Activity and the ledger's forms). Select (the
                    dropdown drawn in the console's face: the trigger is the `field`, the list a white
                    panel on a control edge with no shadow, the chosen option a check; arrows, Home,
                    End, type-ahead, Enter or Space, Escape; flips up when there is no room below;
                    pair it with a `<label htmlFor>`) and DatePicker (a drop-in for `<input
                    type="date">`: `YYYY-MM-DD` or `""`, a Monday-first month grid in 40px circles
                    (44px on a phone), the chosen day an ink fill, today a ring, `min`/`max` grey
                    days out, Today and Clear in the foot; dates.ts is its UTC day arithmetic).
                    Activity's Book, Outcome, Since and Until and the ledger Trades page's filters use
                    them; a test drives them with `lib/test-pick.ts` (`chooseOption`, `chooseDay`).
  shell/            Web overhaul Part 1: Rail (desktop, from 768px: since Part 6 a Search row under the
                    wordmark that calls `openSearch()`, then the lib/nav.ts destinations, the lime pending-count badge on Trades, BotCard at its
                    foot), TabBar (phones: five tabs; Research and News mark More
                    current), BotCard (running or halted in words, mode, rung, the
                    not-draining line; aria-haspopup; a loading block) and BotSheet (the
                    unchanged HaltControl and AutonomyControl, with the DrainWarning above
                    them), DrainWarning (the "trading service is not draining commands" line,
                    moved here unchanged from the deleted controls strip in Part 4, with its own
                    2-case test; BotSheet and TradesPage import it), HaltedBanner (global; wheel-scoped wording), ThemeToggle. And
                    RefreshButton (2026-10-28: the refresh icon, quiet and round, 44px on a phone,
                    spinning while it works. `scope="broker"` on Home's hero and a position's
                    page sends the `refresh` command through portfolio/useBrokerRefresh, then asks
                    for every query again, and says in words beside the icon when the broker is
                    not connected, the command failed or the trading service is not draining;
                    `scope="page"` on Stock, News, News ticker, Trades and Activity sends nothing
                    and refetches the page's queries. Never lime). And
                    from before: SystemStatusCard (now mounted on More; react-query on GET /system/status,
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
  search/           CommandPalette. Since web overhaul Part 6 it is mounted ONCE, in app/layout.tsx, and
                    nothing else mounts it: the rail's Search row, More's Search row and Research's
                    Search button call lib/search.ts `openSearch()`, whose event it listens for. It
                    lists the console's pages (features/search/pages.ts, no request) above the tickers
                    (GET /research/search), is a combobox (aria-activedescendant; the arrow keys move,
                    Enter opens, Escape or a tap on the scrim closes, Close on a phone), and says its
                    state in one always-mounted `role="status"` line. The older notes follow: (⌘K/Escape as before; controlled if `open`/
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
  home/             Restyled in place in web overhaul Part 6: WatchlistTable is the "Your watchlist" card
                    (rows, not a table; the move signed and never green or red; a hatched n/a for
                    every unknown; loading, a failed read, add or remove in words; a line pointing to
                    the scan's own watchlist on Universe) and SectorGrid is one "Sectors by IV rank"
                    card whose rows are SectorCard (an `li`, no green or red). The older notes follow:
                    SectorGrid (react-query on GET /research/sectors, renders SectorCard
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
                    ribbons, each with a "Caution" (flag) or "Note" word), CheckRow (the
                    statement and its state as a StatusWord, Fail in the flag tone, then
                    "Reads <actual> · bar <threshold>" on its own line; unknown renders a
                    hatched `n/a`, never `0`). Since web overhaul Part 5 the ribbon fills a
                    passed check and outlines a failed one in ink: no green or red
  stock/            StatementsTable (normalised statements with filing traceability
                    in a `title` attribute using a hyphen not an em dash; fixed row
                    order; annual and quarterly sections; missing items render "n/a"
                    with `.hatch` texture, never "$0", never colour alone),
                    PriceChart (lightweight-charts: a year of ink candles, up hollow and
                    down filled, light volume, SMA 50 ink and SMA 200 muted, the caller's
                    `lines` as dashed price lines; colours from the tokens at mount and on
                    a theme change, no entry animation, attribution logo off; a role="img"
                    sentence and a line of words name every series), TechnicalsPanel
                    (figure lines; null renders a hatched "n/a" never "0"), NewsPanel
                    (newest-first, relative age, the tone as a neutral StatusWord word,
                    never green or red; `sentimentTint` stays exported for
                    features/position/Headlines), SentimentPanel (composite score, the
                    day's change signed but not coloured, per-source sample count; a
                    source with no tracked count renders "n/a samples", never a
                    fabricated "0"), SummaryPanel ("Generate summary" is a secondary
                    Button; the foot line says "Written by <model>, a language model that
                    decides nothing"). Web overhaul Part 5 deleted SectionShell (replaced
                    by features/stock/StockSection)
  options/          Web overhaul Part 4 deleted the unmounted ApprovalsList, ApprovalCard, ShortsTable,
                    ShortsRow and ControlsStrip (their live coverage moved first: the decide flow's cases
                    to DecideControls.test.tsx, the roll flow's to RollCard.test.tsx, the drain line's to
                    components/shell/DrainWarning.test.tsx). The halt and resume, autonomy and roll-mode
                    controls live in the bot card's sheet (components/shell/BotSheet), and the halted
                    banner is components/shell/HaltedBanner. What stays here:                     HaltControl (M6: halt is ONE CLICK, no dialog - speed is the
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
                    with a DecideControls approval id or a RollProposal
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
                    FillsTable (recent fills with relative age), ApprovalDetailCard (five review fields as a
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
                    same run), DecideControls (the shared decide flow for Home's review sheet
                    and the detail page; its own suite is DecideControls.test.tsx, ported in Part 4
                    from the deleted ApprovalCard.test.tsx, with one known gap: no case pins that a
                    pending command is saved to storage, only restored and cleared: Approve/Reject open ConfirmAction before
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
                    ends up failed/expired),
                    ConfirmAction
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
                    Web overhaul Part 2 (2026-10-19): RollProposal.tsx holds the roll-proposal
                    flow lifted out of the Shorts table's row (`useRollProposal`: the confirm, the one
                    `roll_request` command, the live second confirmation, the receipt and the
                    `short:{position_symbol}` persistence; `RollReceipt`; `RollDialogs`), used by
                    features/position/RollCard.tsx; the roll flow's cases are on RollCard.test.tsx
                    (Part 4 ported them there; they too leave the save side unpinned).
                    AssessedBrowser (a
                    `strategy` prop), AssessedRow (markup only), StageBadge (a StatusWord;
                    `STAGE_LABEL` exported), ReviewPanel, IdealZoneBar, AlternativesTable,
                    RationaleTags and ApprovalDetail are restyled on the payslip tokens under
                    their existing tests. OrdersTable
                    and FillsTable are mounted on Activity (Part 3, Fills and orders), restyled in
                    place under their tests: OrdersTable keeps its Working / All / Rejected filter
                    and takes a `days` window and an order's sizing words ("Claude's cut", "Sent 1
                    of 3 contracts"), FillsTable names each fill's contract. TickerPillBar is
                    deleted. DecideControls, ConfirmAction, CommandReceipt, HaltControl,
                    AutonomyControl and RollModeControl are unchanged (protected: they stay
                    byte-identical to main, and a few of their comments still name the deleted
                    ControlsStrip and ApprovalCard.test.tsx).
  portfolio/        Money (null/NaN renders "n/a" with `.hatch` texture never "$0.00",
                    genuine zero renders "$0", colour never alone, `kind` renders as
                    word), FreshnessLabel (renders age in words - null says "not
                    captured", stale (>freshForMinutes) says "stale", never a dot),
                    DegradedNotice (renders note verbatim, no paraphrase, styled as notice
                    not error), useBrokerRefresh (2026-10-28: the refresh command's flow,
                    shared by the Portfolio button and the refresh icon) and RefreshControl
                    (one click no dialog, fires POST /commands kind "refresh", invalidates
                    portfolio queries on terminal, `broker_unavailable` renders as plain answer
                    through `CommandReceipt`'s `plainReasons` prop not red failed chrome, reuses
                    submitCommand/useCommandStatus/CommandReceipt). Money, DegradedNotice and
                    RefreshControl are restyled in place under their tests (classes only), and
                    FreshnessLabel stays mounted unchanged. Web overhaul Part 4 deleted the
                    legacy panels Part 3 had unmounted (PortfolioShell, SummaryPanel,
                    PositionsPanel, PositionGroup, StockLegRow, OptionLegRow, CampaignsPanel,
                    CampaignThread, CalendarPanel); their live replacements are
                    features/portfolio/ (PortfolioPage, SummaryCard, PositionsView,
                    CampaignsView, CalendarView), and the rules they carried (n/a never "$0.00",
                    the degraded note verbatim, filters in the request, an unknown consequence
                    named) are those views' tests.
  universe/         Restyled in place in web overhaul Part 6: each UniverseList is a Card (17px title, the
                    count, one line on what the list is for), Wheeling and Dip-watch are status words,
                    Remove and Revert are 44px on a phone, AddSymbol has a visible label on the `field`,
                    and a failure is plain words, never red; the behaviour below is unchanged.
                    M7 Task 7.5. UniverseList (one GET /universe section: heading with
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
  pnl/              P4 M5 Tasks 5.4-5.6; P3-P4 M6 Task 6.2 adds System. The old /pnl
                    page frame, PnlShell, was deleted in Part 4; its job is features/activity/
                    now: useLegFilters composes one filter state into one query string for the
                    ledger, summary, equity and CSV export, and SystemView owns the System
                    tab's own since/until window and GET /pnl/system fetch. SummaryPanel
                    (react-query on GET /pnl/summary - the pnl one; fetches
                    `?${qsString}`, the exact query string the page passes in
                    as a prop, NOT its own `?book=${book}` composition - that
                    used to be the bug: every filter except book was silently
                    ignored, so the headline totals never matched a filtered
                    ledger; headline
                    figures, by-strategy/by-symbol breakdowns, best/worst legs
                    each rendered as a button that sets the page's symbol
                    filter to that leg's symbol (`onSelectLeg`, useLegFilters'
                    `viewLeg`) - the ledger has no per-candidate filter, so
                    symbol is the closest real cross-reference; renders as plain text instead when no
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
                    mid-typed. `filters` is `useLegFilters`' own live filter draft,
                    not the backend's echoed response (`LedgerTable` renders
                    that echo separately) - seeding from an echo would lag the
                    fields one round trip behind every edit. The one thing
                    that needs the inputs to change without a keystroke of
                    their own - `SummaryPanel`'s "view in ledger" link setting
                    `symbol` externally - works by features/activity/Legs.tsx remounting this
                    component with a fresh `key` (`formKey`, bumped only on that jump),
                    not a sync effect),
                    SystemPanel (P3-P4 M6 Task 6.2: presentational - takes
                    `data: SystemPerformanceResponse` as a prop like
                    EquityChart, not self-fetching like SummaryPanel, since
                    features/activity/SystemView owns the GET /pnl/system query and the
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
                    Web overhaul Part 3: SummaryPanel, BreakdownTable, EquityChart, CampaignRow, LegRow,
                    LedgerFilters, SystemPanel, ScoreBucketTable and CorrelationTable are restyled in
                    place under their existing tests (same text and test ids) and mounted by
                    features/activity/: SystemPanel takes `windowControls={false}` and a
                    `WindowControls` export, so System owns its window. A table that scrolls on a
                    phone says "Scroll sideways to see every column.". Part 4: BreakdownTable takes an
                    optional `labelOf`, and Pay's by-strategy table passes `strategyWord` (SummaryPanel.tsx:
                    "Cash-secured puts", "Covered calls"; any other label passes through as the API names
                    it); the by-symbol table is unchanged.
  ledger/           The broker-truth ledger in the figure face (web overhaul Part 3): LedgerOverview (the
                    Ledger view on Activity: Totals as figure lines, the two charts, the buckets by
                    strategy and by book, the ticker table and the upcoming expiries, with links to
                    Trades and Import and no sub-navigation of its own), Tile / TileList (figure
                    lines in the stub face, a figure we do not have a hatched n/a), OutcomePill (an
                    outcome as a status word), Charts (PnlCurve and MonthlyBars: each figure is a flex
                    column so the chart takes the room under its caption, and the monthly chart
                    carries a legend), TickerTable, TradesTable, TradesView and TradePanel (a trade
                    opens in the Sheet, with the unchanged `ledger_annotate` flow), TickerView,
                    ImportView (the unchanged `ledger_import` and `ledger_ca_reviewed` flows),
                    LedgerShell (the page frame of the three routes) and BackToLedger (the link back
                    to Activity, Ledger). The old LedgerNav tab strip was deleted in Part 4. Every
                    view root is one `grid-cols-1` column: a page-level grid with no column template
                    is sized by its widest table and would clip the page on a phone.
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
  value/            The value book (value book Part 6, Section F). ValueCard (react-query on
                    GET /value/book, key ["value","book"]: the ceiling as a sum and a Stub, the
                    breakers as words, the held names with their next exit, the open proposals;
                    shown on Home under All and Value (Part 6, Section I added the Value filter: `lib/strategy.ts`
                    has the `value` kind, label "Value", eyebrow "Value book", `WHEEL_FILTERS` for the pages
                    that have no Value; `useValueBook` shares the query and `waitingOnTap` is the switcher's
                    count; the Home cards read the value book through `strategy=value` on `/pnl/*` and
                    `GET /value/positions`, show "Value book, realised" apart from the options net, and say
                    an unread book in words); `available: false` and `enabled: false` each read as a
                    sentence, an unknown figure is a hatched n/a), ValueProposalRow (Review, lime on the first waiting one only,
                    only while a proposal waits on a tap, opening the sheet), ValueDecide (the
                    approve and reject flow, a NEW component that mirrors the shape of the protected
                    options/DecideControls and does not edit it: ConfirmAction first, one
                    `POST /commands` of `value_approve` or `value_reject` carrying the proposal id
                    and the fingerprint from the book response, CommandReceipt, both buttons
                    disabled in flight, the in-flight command persisted under `value:<proposal id>`
                    through lib/commands.ts's helpers, the live second confirmation handled like
                    DecideControls), `types.ts` (aliases over the generated api-types) and
                    `format.ts` (the sentences: the sum, the next exit, the confirm text naming the
                    wheel puts a buy may close, the reason codes in words), and (web overhaul Part 4)
                    ValueDrainNote (under a value tap's receipt, only while the command is pending: when
                    `GET /value/book` says the value process's drain is stale it shows a "Not checking"
                    word and when the process last checked, or that it has not yet; nothing when the
                    drain is healthy or the book has not been read. `ValueDecide` and
                    features/stock-value/AnalyseButton always give the protected CommandReceipt a
                    healthy drain, because it would name "the trading service", the wrong process for a
                    value tap, and render this line instead). The value flow lives here
                    so `grep -rn "submitCommand\|confirmCommand" web/features` prints only
                    features/more/TargetCard, features/stock-value/AnalyseButton (Section G) and their
                    tests. A trim has no web button (plan ruling 10): the card
                    says it is offered in Telegram. Claude's words never sit on a button.
features/
  stock/            The stock page (web overhaul Part 5). StockPage (react-query on GET /research/{symbol},
                    key ["analysis",SYMBOL], polling every 5 s while a section is pending, no retry on a
                    404; it also reads GET /value/{symbol} under ValueBlock's own key ["value","ticker",
                    SYMBOL], so no second fetch, to place the value block and draw its levels), StockSection
                    (a Card per section: the title, then the content, or the API's reason / "Building this
                    section." in words), and stock.ts (`valueLeads`, `valueLines`, `nameLine`, the
                    `Analysis` alias over the generated AnalysisResponse). The page reads; its only command
                    is AnalyseButton inside the value block. Since web overhaul Part 6 the value block
                    mounts only once GET /value/{symbol} has answered (or failed), in the slot the
                    answer picks, so it never mounts at the foot and moves.
  search/           Web overhaul Part 6: pages.ts (PAGES, the console's own pages, and `matchPages`: every
                    typed word must match a page's name, hint or words; at most five). The palette is
                    components/search/CommandPalette; the open event is lib/search.ts.
  universe/         Web overhaul Part 6: UniversePage (see app/research/universe above).
  stock-value/      The value book's view of one name on the stock page (value book Part 6, Section G).
                    ValueBlock (react-query on GET /value/{symbol}, key ["value","ticker",SYMBOL]:
                    the verdict per list first, then BusinessBlock, WorthBlock and SizeBlock for the spec's
                    three questions, a held name's re-evaluations, ClaudeBlock; it asks again every 5 s
                    while `computed` is "pending" and every 15 s for ten minutes after a Claude read is
                    queued), AnalyseButton ("Run Claude's analysis": a confirm-less one-click
                    `value_analyse` with a CommandReceipt, persisted under `value-analyse:<SYMBOL>`; the
                    ONLY command site in this folder, so `grep -rn "submitCommand\|confirmCommand"
                    web/features` prints `features/more/TargetCard.tsx`, its test, this file and its test),
                    parts.tsx (Hatched, Segments, ClaudeLabel), `types.ts` (aliases over the generated
                    api-types) and `format.ts` (sentences and the poll rule `refetchMs`). Every piece of
                    Claude's text carries a "Claude's ..." label with the date it was read against; a
                    hatched n/a is an unknown; Claude's words never sit on a button. Mounted by
                    features/stock/StockPage: first under the chart when `valueLeads` (a priced list or a
                    held name), else at the foot of the left column. Since web overhaul Part 5 SizeBlock
                    says the size tier per priced list (`sizeSegment`) and a held name's tranche plan
                    (`trancheWords`).
  research/         ResearchPage (web overhaul Part 6, the `/research` page) and Top opportunities (value
                    book Part 6, Section H), the strip above the watchlist; since Part 6 OpportunityCard
                    shows `claude_note` after Python's reasons, labelled "Claude's note", never on a button.
                    TopOpportunities (two tabs on a SegmentedControl, Deep value and Quality growth; react-query
                    on GET /value/top?list=, key ["value","top",list], only the list on view is fetched; a second
                    query, key ["value","top","assessed-passed"], reads `GET /options/assessed?run=latest&stage=
                    passed&limit=1000` only when a shown name has a `put_ceiling`), OpportunityCard (name, list,
                    verdict and who decided it, PriceBar, margin of safety, Python's reasons, the age, and two
                    links), PriceBar (one static bar: price, entry ceiling, fair value with the half sale, the stop
                    when the API has one; labels in rows so none overlaps; unknown levels are not drawn), `format.ts`
                    (`readyFirst`, `layoutBar`, `reasonSentence`, `sellPutAvailable`, the two hrefs) and `types.ts`
                    (aliases over the generated api-types). Reads and links only: "See the value file" is a link to
                    `/stock/SYM#value-block-SYM`, "Sell a put up to $C" a link to `/trades?view=assessed&strategy=
                    csp&symbol=SYM` shown only when a passed CSP candidate at or under the ceiling is in the latest
                    scan. The strip never reaches `submitCommand` or `confirmCommand`. `?symbol=` is read by
                    TradesPage and seeds AssessedBrowser's Symbol filter (`initialSymbol`).
  home/             Web overhaul Part 1: the Home page. HomePage (strategy switcher with
                    pending counts, then AccountHero, ProposalsBanner below 1024px, PayCard,
                    PositionsCard; the NeedsYou column from 1024px; renders the bare page
                    until hydration is over, because the rail's approvals query shares its
                    key), AccountHero + HeroChart + hero.ts (GET /portfolio/value: the
                    number, the signed day change or "n/a today · last value <date>", a
                    "Delayed" word and age on a headline older than 30 minutes in New York
                    market hours (heroDelay: the positions card's FRESH_FOR_MINUTES, `now`
                    injectable), a lightweight-charts line that never animates in,
                    scrubbable by pointer and by keyboard as a slider, one point per
                    second), PayCard (GET
                    /pnl/month: a Disclosure whose summary is net vs target and the lime
                    meter, whose panel is the month's Stub; "No target set" only without
                    the setting, "Target n/a · needs the month's opening account value"
                    without a month-start value; spreads unavailable is said, never shown
                    as $0), PositionsCard + positions.ts (GET
                    /portfolio/positions and GET /spreads/positions?status=open: rows with
                    status words from API fields only, chips per kind, a Delayed word on
                    a stale snapshot, unreadable spreads stated, never "none open"),
                    ProposalCard + proposal.ts + WhyDisclosure (Claude's review collapsed
                    and labelled, above the stub; Review opens the sheet, Details links to
                    /trades/{id}; the card decides nothing), ReviewSheet (the trade, then
                    the unchanged DecideControls inside the Sheet: ConfirmAction, the LIVE
                    second confirmation and the receipt; polls the approval's status and
                    says when it was decided elsewhere or expired), NeedsYou +
                    usePendingApprovals, ProposalsBanner, types.ts (hand-written mirrors
                    of the three new API models).
                    Web Home follow-ups (2026-10-15): TodayTrades ("Done today", GET /pnl/day,
                    All / Opened / Closed / Rolled pills) with TradeCard (the proposal card's
                    anatomy for an executed trade: eyebrow, title, one sentence, the reasoning
                    collapsed above the stub, a stub that sums the whole trade; `when="date"` and
                    `heading="none"` let the position page reuse it) and trades.ts (title,
                    sentence, stub, time label); RealisedCalendarButton + calendar.ts (the
                    calendar sheet over GET /pnl/calendar, New York months, Monday-first, a
                    tapped day's closes from GET /pnl/day?date=); PositionsCard gained a search
                    (`matchesQuery`: commas for several names, only the ticker and contract's own
                    words) and links each row to its page; `optionStatus` is the shared status-word
                    rule. HomePage is one CSS grid, so there is one copy of each card.
                    Web overhaul Part 2 additions: a "Roll alert" flag word on a position row
                    (positions.ts, from GET /options/shorts through PositionsCard); proposal.ts
                    gained `rollTitle`, `rollSentence`, `rollStub` (a roll names both legs and
                    sums to its net at the quotes it was priced at) and `decisionWords` (who
                    approved, from `decided_by` only); TradeCard says who approved an opened or
                    rolled trade; ReviewSheet takes optional `onSubmitted` / `onSettled`
                    callbacks; and the realised calendar's day panel links "Open this day in
                    History".
                    Web overhaul Part 3: PositionRowItem (the position row, extracted from
                    PositionsCard so Home and Portfolio draw one row; `flags` and `detail` are the
                    Portfolio additions).
                    Web overhaul Part 4: ValueWaiting (the value proposals that wait on a tap, as
                    compact rows in NeedsYou under All and Value: the eyebrow "Value book", the trade,
                    cost, time left and a secondary "Review in the Value book" link that jumps to the
                    Value card, which keeps the one decide flow and its one lime Review; an
                    unreadable book is said, an off book that never wrote says nothing; ProposalsBanner
                    counts and names the same proposals through `waitingProposals`, with a secondary
                    Show when only value proposals wait). A value position row now links to the stock
                    page's value block, and the "Value book unavailable" flag hides only when
                    `GET /value/book` says `enabled: false` and `available: false`.
features/position/  PositionPage (GET /portfolio/positions/{underlying}/{slug}: title and status
                    words, then one grid whose DOM order is the phone order, chart, the trade,
                    headlines), UnderlyingChart (the close as an ink line, a dashed rule at the
                    strike or the cost basis, a Sold marker, 1M / 3M / 6M / 1Y over the stock
                    page's own bars request), Headlines (GET /research/{symbol}/headlines,
                    sentiment as a word), position.ts (slugs, chart lines, the Now figures),
                    RollCard (web overhaul Part 2: on a held short option with a known strike and
                    right only; the alerts the monitor fired on this contract with Claude's stored
                    view labelled as Claude's, then Propose a roll through useRollProposal, the
                    flow the Shorts table used to run).
features/trades/    Web overhaul Part 2: TradesPage (the strategy switcher with pending counts, the
                    view chips, the drain warning, then the view), views.ts (the views a strategy
                    has, `explicitView`, `defaultView`, `tickerCounts`), useTradesView +
                    useTradesDay (`?view=` and `?day=` through router.replace; the smart default is
                    decided once per visit, when the pending count first loads, or History when
                    that load failed; `?day=` accepts only a real calendar date),
                    useSubmittedApprovals (the Map of approvals whose Approve this browser sent,
                    seeded after mount from `loadAllPersistedCommands()` so a reload mid-command
                    keeps the card in flight; Approve commands only), SubmittedWatcher (one
                    null-rendering component per approval in flight, mounted by TradesPage whatever
                    the view: follows the command and, when it ends failed or expired, hands the
                    card back and clears its persisted entry), ProposalsView (ticker chips from two tickers up,
                    then Home's ProposalCard and ReviewSheet), HistoryView + useInFlightCount +
                    useWorkingOrders (one New York day: In flight, Traded, Not traded), history.ts
                    (`notTradedRows`, `orderContract`, `IN_FLIGHT_STATES`), time.ts (New York
                    clock times, day labels and shifts; `whenET` writes "Wed, Oct 28 · 2:46 AM ET"
                    for the Activity lists), SpreadsView + spreads.ts (GET
                    /spreads/picks: the day's books, the menu Claude saw, Other picks), types.ts
                    (hand-written mirrors of the spreads-picks models). Part 4: a card's Details link carries the Trades view, day (not today)
                    and strategy (not All), and BackToTrades returns to them
                    (`viewReturnQuery`, `tradesReturnQuery`, `detailHref` in
                    useTradesView.ts); SpreadsView keeps its day in `?day=` through useTradesDay;
                    HistoryView says "could not be loaded right now" for a failed In flight or Not
                    traded read, and when a read hit the 200-proposal limit. Assessed is
                    components/options/AssessedBrowser. Nothing here reaches `submitCommand` or
                    `confirmCommand`: an order intent goes through DecideControls inside the review
                    sheet, a promote through AssessedRow, a roll through RollCard.
features/claude-context/  What Claude knows (read-only): ClaudeContextPage (react-query on
                    GET /claude/context, refetched every minute; the loading block, the error with
                    its retry, then the cards), RegimeCard (SPY and QQQ regimes as words, the CSP
                    limits as figure lines, the leveraged-ETF ceilings, Claude's cut mode, and a
                    stack of amber flag words at the top when they apply: `Off in config`,
                    `Suspended today` and `Cuts paused today` (today's cut breaker has tripped,
                    from `claude_cut_breaker_tripped_today`; the cut-mode line then ends ", paused
                    today")),
                    PictureCard (stories first; the numbers, seasonality as a weak signal and the
                    events behind a disclosure; stale says so), CallsCard (a row per Claude call,
                    its prompt blocks as non-interactive chips), DroppedCard (the first five, the
                    rest on request, promotions, the unreviewed count), NamesCard (a row per name:
                    Python's health, Claude's story and summary labelled as Claude's, the figures
                    Claude quoted from the news under "Reported in news (not computed by the
                    system)" apart from the story, each with its cluster id as evidence, and
                    upcoming events: the date found in the news, the title labelled as Claude's), FigureLines (the perforated figure lines), format.ts (New York times,
                    percents, the regime line, the leveraged sentences) and types.ts (aliases of
                    the generated api-types). Nothing here writes or reaches a command.
features/market/    The market picture where the work happens (2026-10-23), read-only. MarketCard (the SPY and
                    QQQ regimes as words with what each does to new puts, the flag words, and the picture's
                    stories: three on Home, six with Claude's description and the 7-day triage line on News,
                    none on Trades' Proposals view), NameNotes (one name's notes: the claude-context `Name`
                    row on the position page, the stock page and a news ticker page; silent while loading,
                    "No notes yet" when the name has none), NameFlags ("Weak health" and a "Event <date>" word
                    on a Home position row), HeldBack (Trades History: the day's `GET /claude/sizing` rows
                    as "Held back or trimmed", kinds and reason codes in words) and market.ts (the pure
                    rules, including `eventBefore`: the verified event date, if any, that falls
                    before an expiry, for Portfolio's Calendar). All share `useClaudeContext` (features/claude-context/), one query key.
features/portfolio/ Web overhaul Part 3: the Portfolio page. PortfolioPage (the title, <RefreshControl/>,
                    the Account card, the view chips, then the view; the Account card sits outside the
                    switched view, so a view change never refetches it), views.ts (PORTFOLIO_VIEWS and
                    labels), SummaryCard (the Account card: `GET /portfolio/summary`, the age in words,
                    "Delayed" at 30 minutes or when degraded, the API's note verbatim, then
                    AccountDonut + donut.ts: net liquidation at the centre of a two-ring donut, the
                    outer ring buying power used and the inner ring cash as a share of the account,
                    each percent written out with the sum behind it, a ring we cannot draw an empty
                    track and an n/a; the rest as two blocks of figure lines under it), format.ts (`usd`, `shortDate`, `weekdayDate`, read as
                    written so no date shifts with the viewer's zone), PositionsView + positions.ts (one
                    name card per underlying from Home's `buildPositionRows`: the price at the top right
                    (`Last price`, or `Close <date>` for a name held only through options, from the
                    API's `underlying_price`), the name's open P&L as the card's hero, a figure strip
                    (`nameFigures`: value and cost basis of the shares, net delta in shares, next
                    expiry, cash secured), then each option with a figure line (`legDetail`); `rowsPnl` adds a name's rows only when every one is known, else
                    n/a; a search, the type chips with counts, the "Weak health" and "Event" words from
                    the notes Home reads; an unreadable spreads book says so), CampaignsView +
                    campaigns.ts (Status and Symbol go to `GET /portfolio/campaigns` in the request; the
                    money is labelled before commissions; an assigned thread shows its adjusted basis
                    and realised stock P&L; a pruned leg is "Leg unavailable"), CalendarView +
                    calendar.ts (the horizon, 14 to 180 days, in the request; one card per expiry day;
                    `consequenceSentence` names an unknown consequence as one; `eventBefore` puts
                    "Event <date> before expiry" on a short with a verified date). Part 4: a Value chip
                    (between Credit spreads and Shares) and a "Value book" card after the spreads card,
                    rows through PositionRowItem with `flags={false}` and a link to the stock page's value
                    block (`useValueOut`, `countByFilter`'s optional fourth argument). Nothing here reaches
                    `submitCommand`.
features/activity/  Web overhaul Part 3: the Activity page. ActivityPage + views.ts (the four views in
                    `?view=`). Pay: PayView, month.ts and useMonthParam (New York months in `?month=`;
                    junk or a future month is this month), MonthStepper, PayMonth (the month as a stub,
                    `GET /pnl/month`), useLegFilters and Legs.tsx (LegsFilters and LegsCard: one set of
                    filters composed into one query string for the totals, the curve and the legs, and
                    the CSV link), useEquity and Curve (the equity curve; a journal gap is a gap in the
                    line). Fills and orders: FillsView (three lists under one window, never merged),
                    fills.ts (windows, titles, book and source words), types.ts (aliases of the
                    generated contract), ExecutionsList (IBKR's executions, `GET /ledger/executions`; a
                    commission of 0 reads "none recorded"), SpreadFills (`GET /spreads/orders`;
                    "unavailable" is not "none"). System: SystemView (one window over both),
                    SizingRecord + sizing.ts (`GET /pnl/sizing`: kinds, counts and the two marks in
                    words; Claude's cut as applied or recorded only, from `GET /claude/context`).
                    Ledger is components/ledger/LedgerOverview. Part 4: a month before the record's first opens the first month; Pay's by-strategy
                    table says words; SpreadFills says "Only the newest 200 are listed." when
                    `truncated`; ExecutionsList gains a Value chip and "Value book" on a row; History and
                    Fills and orders end with a link to each other. Nothing here sends a command.
features/more/      TargetCard + target.ts (the income-target form's rules: text in, a validated
                    `set_income_target` payload out, mirroring `IncomeTarget` and its bounds).
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
                    review sheet and the detail page; RollProposal's roll
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
  theme.ts          ThemePref (light / dark / system), parse/resolve/read/write with
                    every storage access wrapped, applyTheme, and THEME_INIT_SCRIPT (runs
                    before paint; also re-applies "follow OS" app-wide on an OS flip)
  useThemePref.ts   The theme toggle's hook (hydration-safe: server and first client
                    render agree, then the stored preference)
  useFocusTrap.ts   The Sheet's focus trap (nested-dialog safe; onEscape through a ref;
                    puts focus back on the panel when a focused control leaves the page)
  useHydrated.ts    `useHydrated()` (moved out of HomePage; Home and Trades both use it): false for
                    the server render and the hydration pass, so a page whose query shares a key
                    with the rail renders its bare shell until hydration is over
  search.ts         Web overhaul Part 6: OPEN_SEARCH_EVENT and `openSearch()`, the one way to open the
                    shell's search palette.
  segment.ts        Web overhaul Part 6: `decodeSegment`, a dynamic segment decoded for a title, the raw
                    segment when the escape is malformed.
  nav.ts            NAV (the seven destinations, which five sit on the phone tab bar; Research's
                    icon is a telescope since Part 6, so the magnifier means search),
                    activeKey and phoneActiveKey
  strategy.ts       StrategyKind / StrategyFilter, labels and eyebrows, kindOf (a roll
                    files under the side it rolls; unknown strategies only under All),
                    parseStrategyFilter (a junk value is All)
  useStrategyFilter.ts  The `?strategy=` URL state (router.replace, scroll kept)
  useViewParam.ts   A page's `?view=` (Portfolio and Activity): no value or an unknown one is the
                    fallback, choosing one keeps every other parameter; the page renders inside
                    <Suspense>
  receipt.ts        receiptState, the receipt state machine (spec §9.2) — a
                    pure function, tested exhaustively in receipt.test.ts
  format.ts         formatMoney (compact $391.0B/$1.3M, "n/a" for unknown, "$0"
                    for a real zero), formatPeriod ("Sep 2024"), relativeAge
                    ("5m ago"/"3h ago"/"2d ago"/"1mo ago"), formatDateTime (the exact
                    moment, always rendered in labelled UTC regardless of viewer
                    timezone — "Sep 12, 2026, 2:05 PM UTC" — for places a relative age
                    would misleadingly decay to "just now" forever), UNKNOWN constant
```