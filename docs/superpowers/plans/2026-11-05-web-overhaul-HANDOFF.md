# Web overhaul - ledger and handoff for the next session (2026-11-05)

Written by the Sonnet ledger agent the value book HANDOFF ("Flow after Part 5", step 3) asked for, after
value book Part 6 merged. A fresh session (Sonnet is fine as the orchestrator) can carry on from this file
without the conversation that produced it. Every status line below was checked against the code on `main`
(`ca14c40`, clean tree, equal to `origin/main`), not copied from a plan. Read it top to bottom.

## 0. Headline

- **Web overhaul Parts 1-3 are done and pushed**, and so are the value book's four web sections (F-I). The
  numbered programme is about **two thirds built by page count**: Home, Trades (two routes), Portfolio,
  Activity, Position, More, What Claude knows and the three ledger sub-routes are on the payslip system (11 of
  17 routes); Research, Universe, Stock, News (two routes) and How it works (6 of 17) are not recomposed.
- **Part 4 (as originally written: Research, News, More and cleanup) has not started**, and neither has the old
  Part 5 (order control: cancel a working order from the web). Both are re-cut below.
- **Three things the value book created need fixing soon**, one before `value.book.enabled`: a capital-release
  close would read "the reason was not recorded" on Done today (a false sentence); a dead value process shows a
  receipt that never resolves (no health signal); the ledger and Portfolio do not know the `value` book.
- **Recommendation:** keep all four Part 6 web pieces and extend them; cut the "fold every `components/<domain>`
  into `features/`" goal; cut the `/recommendations` page; rebuild "How it works" small (or cut it, Q1). New
  order: Part 4 cleanup and value gaps, Part 5 stock page, Part 6 Research/Universe/search, Part 7 News/More/How
  it works, Part 8 value record (gated), order control on its own track. **Part 4 is next.**
- Six operator questions are in section 5.3; each has a default the rest of this file assumes.

## 1. Where things stand

| Part | Plan / source | State | Merge | What shipped (verified in code) |
|---|---|---|---|---|
| 1 - Foundation, shell, Home | `plans/2026-10-13-web-overhaul-1-foundation-home.md` | **Merged, pushed** | `ab7339c` (2026-10-14) | Payslip tokens/fonts/theme (`web/app/globals.css`, `lib/theme.ts`); ten `components/ui/` primitives (Button, Card, Disclosure, Meter, SegmentedControl, Sheet, StatusWord, Stub, + Select and DatePicker from the 10-28 pass); shell (`components/shell/`: Rail, TabBar, BotCard, BotSheet, HaltedBanner, ThemeToggle, RefreshButton, SystemStatusCard); strategy switcher (`lib/strategy.ts`); `features/home/` (hero, pay card, positions card, proposal cards, review sheet); `GET /portfolio/value`, `GET /pnl/month`, `GET /spreads/positions`; routes + redirects (`next.config.ts`); `web/DESIGN.md` ratified 2026-10-14 |
| 1b - Home follow-ups | `plans/2026-10-15-web-home-followups.md` | **Merged, pushed** | `bb34b58` (2026-10-15) | Done today (`TodayTrades`, `TradeCard`, `GET /pnl/day`), realised calendar (`RealisedCalendar`, `GET /pnl/calendar`), positions search + row links, position pages (`app/positions/[underlying]/[slug]`, `features/position/`), settable income target (`features/more/TargetCard`, `set_income_target`) |
| (market picture web, outside the numbered parts) | `plans/2026-10-20-market-picture.md` Tasks 22-23 | **On main** | in `ee87286` (2026-10-22) and `353cdd8` (2026-10-27) | What Claude knows (`app/more/claude`, `features/claude-context/`), Market card, name notes, "Weak health"/"Event" words, Held back or trimmed (`features/market/`) |
| 2 - Trades | `plans/2026-10-19-web-overhaul-2-trades.md` | **Merged, pushed** | `4872a77` (2026-10-19) | `/trades` (Proposals, History, Assessed, Spreads; `features/trades/`), approval detail restyled (`app/trades/[approvalId]`), roll moved to the position page (`features/position/RollCard`), `approvals.decided_by`, `GET /spreads/picks` |
| 3 - Portfolio, Activity | `plans/2026-10-23-web-overhaul-3-portfolio-activity.md` | **Merged, pushed** | `378970d` (2026-10-28) | `/portfolio` (Account card, Positions, Campaigns, Calendar; `features/portfolio/`), `/activity` (Pay, Ledger, Fills and orders, System; `features/activity/`), `/ledger` redirects in; `GET /pnl/sizing`, `GET /ledger/executions`, `GET /spreads/orders` |
| 3b - post-Part-3 pass | commits `e2bf506` (10-28), `1dad9dc` (10-30) | **On main** | direct on main | Account donut, name cards with price and open P&L, Today-left day stepper, Select and DatePicker, RefreshButton on seven pages (`underlying_price` on `/portfolio/positions`); fix for the broker-refresh invalidation loop |
| Value F - Home Value card + decide flow | `plans/2026-10-29-value-book-6-web-telegram.md` Task 16 | **Merged, pushed** | `2d55bd7` (2026-11-05) | `components/value/` (`ValueCard`, `ValueProposalRow`, `ValueDecide`, `useValueBook`, `format`); `value_approve`/`value_reject` with the fingerprint |
| Value G - stock page value block | Task 17 | **Merged, pushed** | `dda50c1` | `features/stock-value/` (`ValueBlock`, `BusinessBlock`, `WorthBlock`, `SizeBlock`, `ClaudeBlock`, `AnalyseButton`); mounted by one line in `app/stock/[symbol]/page.tsx` |
| Value H - Research Top opportunities | Task 18 | **Merged, pushed** | `f3622ca` | `features/research/` (`TopOpportunities`, `OpportunityCard`, `PriceBar`); `?symbol=` seeds Assessed |
| Value I - `value` kind across Home | Task 19 | **Merged, pushed** | `1efcddc`, then fixes `6045d2f` | `lib/strategy.ts` `value` kind + `WHEEL_FILTERS`; pay card and Activity Pay get a second "Value book, realised" stub; Positions, Done today, realised calendar, Needs you carry it |
| 4 - Research, News, More, cleanup (old definition) | Part 1/2/3 Roadmaps | **Not started** | - | Re-cut in section 5 |
| 5 - Order control (old definition) | Part 2 Roadmap | **Not started, no spec** | - | `grep cancel_order` finds nothing; History says "A working order is cancelled in IBKR for now" (`features/trades/HistoryView.tsx:174`) |

**Verified today (2026-11-05):**

- `git status` clean; `main` = `origin/main` = `ca14c40`; the only leftover is the merged worktree `.claude/worktrees/value-book-6`.
- `cd web && npx vitest run`: **152 files, 1485 tests passed** (matches the Part 6 final row). Part 6's recorded Python gate: pytest 5665 passed + 1 skipped, ruff and mypy clean (not re-run here).
- da-vinci `design_md_check.py web/DESIGN.md` exits 0 (`status=ratified`, but `updated=2026-10-28` lags the 2026-11-05 Decision Log entries); da-vinci `lint.py` over `web/app web/components web/features` finds one non-test hit (`components/explain/SourceRefs.tsx:21`, an em dash) and em dashes in legacy test titles.
- All seven daemons restarted **2026-11-05 14:08**, after the last commit (13:55), so the backend runs Part 6; the live API serves `/value/book|top|positions|{symbol}`, `/pnl/sizing`, `/ledger/executions`, `/spreads/picks`, `/claude/sizing` (66 paths). The private `config/value.yaml` already carries `telegram:` and `prompt_note:` and `config/settings.yaml` carries `value_grace_hours`. `next dev` (pid started Oct 30) still serves `web/`.
- Routes today (17 pages): `/`, `/trades`, `/trades/[approvalId]`, `/portfolio`, `/activity`, `/positions/[underlying]/[slug]`, `/research`, `/research/universe`, `/stock/[symbol]`, `/news`, `/news/[symbol]`, `/explain`, `/more`, `/more/claude`, `/ledger/trades`, `/ledger/ticker/[symbol]`, `/ledger/import`; redirects `/options`, `/options/:id`, `/pnl`, `/ledger`, `/universe` (`web/next.config.ts`).

## 2. What the overhaul intended, and how much is done

Sources: `web/DESIGN.md` (Brief, Surfaces), the Roadmap sections of the Part 1/2/3 plans, the Home follow-ups,
and the earlier P0-P5 programme (`docs/Web plan/OVERVIEW.md`) whose end state the overhaul re-skins.

### 2.1 Pages

| Surface | Route | State | Evidence / what is missing |
|---|---|---|---|
| Home | `/` | **DONE** | `features/home/HomePage.tsx`; Value card at the foot of the left column (`components/value/ValueCard`) |
| Trades | `/trades`, `/trades/[approvalId]` | **DONE** | `features/trades/`, `components/options/ApprovalDetail`; cancel not built |
| Portfolio | `/portfolio` | **DONE for the wheel** | `features/portfolio/`; no value-book holdings (the wheel's view only, Part 6 ruling 27) |
| Activity | `/activity` | **DONE for the wheel** | `features/activity/`; Pay knows the value book, Fills/Ledger chips do not (section 3.3) |
| Position | `/positions/...` | **DONE** | `features/position/`; value holdings have no page (`href: null`, `features/home/positions.ts:180`) |
| More | `/more` | **DONE** (minor polish) | `app/more/page.tsx` on `Card`; no favicon, per-route titles or error pages |
| What Claude knows | `/more/claude` | **DONE** | `features/claude-context/` |
| Ledger sub-routes | `/ledger/trades`, `/ledger/ticker/[symbol]`, `/ledger/import` | **DONE** (restyled in Part 3) | `components/ledger/` (`TickerView.tsx:48` still sets a `font-mono` `h1`) |
| Research | `/research` | **PARTIAL** | Top opportunities strip is new and on the payslip; the frame (`font-mono text-2xl`, `px-8 py-6`, bordered buttons), `WatchlistTable`, `SectorGrid`, `CommandPalette` are not (`app/research/page.tsx`) |
| Stock | `/stock/[symbol]` | **PARTIAL** | Name notes and the Value block sit in a legacy frame; Checks, Technicals, Statements, Sentiment, News, AI summary are old `SectionShell` blocks; no fair value/ceiling/stop on the chart (spec section 10) |
| Universe | `/research/universe` | **NOT DONE** (restyle) | `app/research/universe/page.tsx`, `components/universe/` (974 lines, legacy) |
| News | `/news`, `/news/[symbol]` | **NOT DONE** (restyle) | `components/news/NewsFeed.tsx` has no page title, old chips and inputs; only the Market card is new |
| How it works | `/explain` | **NOT DONE and stale** | 8-tab shell, 1,491 lines, last edited 2026-09-30; no word on spreads, the value book, regime sizing, capital release, the news thread or the roll redesign |
| Recommendations | `/recommendations` | **NEVER BUILT** | P1 design (`docs/Web plan/P0-P1-design.md` section 9) planned it; `GET /research/recommendations` exists, no web caller |
| Order control | (History) | **NOT DONE** | Section 3.6 |
| Native mobile app | - | **CUT** earlier | `STATUS.md` "P5 - Mobile": the responsive web is the mobile answer |

### 2.2 Cross-cutting intent

| Intent | State | Evidence |
|---|---|---|
| Payslip design system, light/dark/follow-OS | **DONE** | `web/DESIGN.md` (1,239 lines), `app/globals.css` |
| Shell: rail, phone tab bar (Home, Trades, Portfolio, Activity, More), bot card | **DONE** | `lib/nav.ts`, `components/shell/` |
| Safety friction unchanged; web only proposes intents | **HELD** | the six protected controls + `lib/commands.ts`, `lib/receipt.ts` untouched by any overhaul part (last changes 2026-09-06 to 2026-10-15; `git log -1 -- <path>`); `tests/test_web_fence.py` (23 tests) |
| Unknown is `n/a` + hatch, never `0` | **HELD on rebuilt pages**, broken in two spots on Trades | History's In flight and Not traded return `null` when their fetch fails (`features/trades/HistoryView.tsx:152,193`) |
| Old URLs keep working | **DONE** | `next.config.ts` redirects |
| Delete what Parts 2-3 left unmounted | **NOT DONE** | 15 components, section 3.2 |
| Remove unused `GET /nav` | **NOT DONE** | `src/api/routers/meta.py:99` |
| Fold legacy `components/<domain>` into `features/` | **NOT DONE; recommended CUT** | section 4 |
| Trades History and Activity Fills link to each other in one sentence | **NOT DONE** | `STATUS.md` Part 3 limitations |
| Global search | **NOT DONE** | `CommandPalette` is mounted only on `/research` |
| Every page has a title, a 404 and an error state | **NOT DONE** | `app/layout.tsx` sets one title; no `not-found`/`error`/`loading` files |

## 3. Remaining work, itemised

IDs are used by the recommendations in section 4 and by the part list in section 5.

### 3.1 Legacy surfaces still to be recomposed (L)

| ID | Item | Size (code today) |
|---|---|---|
| L1 | Research landing frame, `WatchlistTable`, `SectorGrid`/`SectorCard`, `CommandPalette` | `app/research/page.tsx` 46, `components/home` 578, `components/search` 267 lines |
| L2 | Stock page: header/price, chart, sections, `Checks`, `Technicals`, `Statements`, `Sentiment`, `News`, `AI summary` | `app/stock/[symbol]/page.tsx` 115, `components/stock` 1,029, `components/checks` 518 |
| L3 | Universe page and its three components (edit flows and `ConfirmAction` consequence text stay) | `components/universe` 974 |
| L4 | News feed and News ticker (`NewsCard` content stays) | `components/news` 449 |
| L5 | How it works (Q1) | `components/explain` 1,491 |
| L6 | More: add nothing structural; per-route titles and a value mention | `app/more/page.tsx` 81 |

### 3.2 Dead code and cleanup (D)

| ID | Item |
|---|---|
| D1 | Unmounted legacy components (verified by import grep): `components/options/{ApprovalsList,ApprovalCard,ShortsTable,ShortsRow}`, the `ControlsStrip` component (its `DrainWarning` is live: `BotSheet.tsx:4`, `TradesPage.tsx:4`), `components/portfolio/{PortfolioShell,SummaryPanel,PositionsPanel,PositionGroup,StockLegRow,OptionLegRow,CampaignsPanel,CampaignThread,CalendarPanel}`, `components/pnl/PnlShell`, `components/ledger/LedgerNav`. **Survivors that live pages import:** `components/portfolio/{types,Money,FreshnessLabel,DegradedNotice,RefreshControl,useBrokerRefresh}`, `components/options/{EmptyState,StageBadge,RationaleTags,RollModeControl}` |
| D2 | Tests to port first: `ApprovalCard.test.tsx` (17 tests) is `DecideControls`' only coverage (there is no `DecideControls.test.tsx`; `ReviewSheet.test` and `ValueDecide.test` cover their own flows); `ShortsTable.test.tsx` (22) is the roll flow's full regression suite beside `RollCard.test` (7). `ApprovalsList.test.tsx` (10), `ControlsStrip.test.tsx` (3) and the portfolio/pnl/ledger panel tests go with their files |
| D3 | `GET /nav` + `NavResponse`/`NavSection`, `tests/test_api_meta.py` cases, `docs/web/api.md`, `openapi.json`, `api-types.ts` |
| D4 | Folding `components/<domain>` into `features/` (Part 1's roadmap) |
| D5 | Other routes with no web caller: `GET /research/recommendations`, `GET /options/assessed/runs`, `GET /news/status`. Documented contracts; not promised for removal |
| D6 | Stale docs: `STATUS.md:949` (the "Web overhaul (Parts 1-4)" row), `ARCHITECTURE.md:1596-1597`, `web/CLAUDE.md` lines 534, 540, 578, 689, 706 ("until Part 4"), `docs/web/architecture.md` drain list (no value process drain), `web/DESIGN.md` marker `updated=2026-10-28` |

### 3.3 Gaps the value book (and other late builds) left on existing surfaces (V)

| ID | Gap | Evidence | Urgency |
|---|---|---|---|
| V1 | A capital-release close (a wheel put bought back to fund a value buy) has no entry in `_CLOSE_RULE`, so Done today, History and the position page would say "Bought back; the reason was not recorded. This close predates the reason stamp." - false (`CloseReason.CAPITAL_RELEASE` is stamped, `src/execution/capital_release.py:279`) | `src/reporting/day.py:266-286, 396-399` | **Before `value.book.enabled`** |
| V2 | No value-process health signal: `ValueDecide`'s `drainHealthy` is always true, so a dead process shows a Queued receipt forever (Part 6 F ruling 5; same for `AnalyseButton`) | `components/value/ValueDecide.tsx`; no heartbeat in `src/api/routers/value.py` | Before the book is on |
| V3 | A tap-waiting value proposal is invisible in "Needs you" and the phone banner; it shows only as a count on the switcher and as the lime Review on the Value card at the foot of Home's left column | `features/home/NeedsYou.tsx` (Value: "Value proposals wait in the Value book card.") | With V2 |
| V4 | The ledger knows `book: "value"` (API and `api-types.ts`) but the hand-written ledger type and every filter do not: Activity At IBKR chips, the ledger Trades filter, `bookWord("value")` falls back to lowercase "value" | `components/ledger/types.ts:24`, `components/ledger/TradesView.tsx:23`, `features/activity/{ExecutionsList,fills}.ts`, `LedgerOverview.tsx:135` heading | Small |
| V5 | Portfolio does not show value holdings (Home's Positions card has a Value chip; the register does not); a value holding's row has no link (`href: null`) | `features/portfolio/`, `features/home/positions.ts:162-180` | Small |
| V6 | Stock page: no fair value, entry ceiling, half sale or stop drawn on the chart (spec section 10); tranche plan and size tier not exposed by `GET /value/{symbol}` (G3); "what changed since last time" has no field of its own | `components/stock/PriceChart.tsx`; STATUS Part 6 deferred | Part 5 |
| V7 | Top opportunities: no Claude one-line note (`ValueTopItem` has no field, H2); stop always null (H3); "Sell a put" shows on a scan's `passed` stage, not a re-gate (H4) | `features/research/` | Part 5 backend + Part 6 |
| V8 | `value_available=false` shows a "Value book unavailable" flag under All on installs that never ran the value process (I ruling 4). Not noisy on this install (value.db exists); fix by gating on `/value/book`'s `enabled` | `features/home/PayCard.tsx` | Low |
| V9 | A value sale whose realised P&L is unknown is left out of the month sum with no "incomplete" flag (`MonthPay` has only the commissions flag); the calendar's value split costs one extra request per month | STATUS Part 6 deferred | Part 8 |
| V10 | Process debt from F-I: no fresh reviewer agent ran (da-vinci critique and audit ran in-thread), and dark captures are missing for F (1440 dark), G (390 dark), H and I (all states) | Progress log rulings F9, G11, H9, I10 | Part 4 finish |

### 3.4 Shell and design-system debt (S)

| ID | Item |
|---|---|
| S1 | Global search: `CommandPalette` is mounted only on `/research` (`app/research/page.tsx:27`); on a phone it is reachable only by More, Research, search button. With the stock page now the hub for wheel and value work, search should be one tap everywhere |
| S2 | Page `<title>` is "IBKR Income" on every route (`app/layout.tsx`); no favicon (`DESIGN.md` Open Decision) |
| S3 | No `not-found.tsx`, `error.tsx` or `loading.tsx` anywhere in `web/app` except the trades detail page's own states |
| S4 | `web/DESIGN.md` Open Decisions (all operator calls, none blocking): product name, logo/favicon, icons (lucide), sheet 180ms exit, restyle of the protected decide controls, the disabled quiet button (month stepper and day arrows draw a filled circle) |
| S5 | Surfaces in `DESIGN.md` for Universe, News, Explain and Stock are one line or absent; each recomposed page writes its own paragraph through da-vinci |

### 3.5 Deferred minors, by part (M)

- **Part 1** (`STATUS.md`, Part 1 section): a holiday or early close reads "Delayed" on the hero (documented, accepted); the 180ms sheet exit and the decide controls' look (S4). The operator's memory notes also mention a Telegram `/halt` wording follow-up and a narrower fence test; neither is recorded in any plan log, so treat them as unverified.
- **Part 2** (Progress log, review fix pass): the smart default can open on an empty Proposals on a client-side navigation when the only pending proposal has an Approve in flight; History's In flight and Not traded render nothing when their fetch fails (**unknown looks like none**, `HistoryView.tsx:152,193`) and Not traded's `limit=200` over three UTC days can drop a past day's older rows; `activity_days` loads every approval snapshot per `/pnl/day`; the Spreads view keeps its day in local state (`?day=` ignored, "Next" onto today pins a date, `positionHref` hard-codes `paper`); `BackToTrades` drops `?view`, `?day`, `?strategy`.
- **Part 3** (Progress log, review row): the spread-fills list has no `truncated` flag (cap 200); `/ledger/executions` covers days+1 calendar days; a name card's open P&L under a type chip sums the visible legs only; with `source: none` and open spreads, Positions shows only the spreads card; da-vinci-finish tests assert class names; `SpreadFills` shows the raw `mode`; `?month=` before the system start is not clamped; Pay's by-strategy table prints the raw label `cash_secured_put`; a ledger trade's null stock gain reads blank where `n/a` is meant; `Trades History <-> Activity Fills` one-sentence cross-links were not built.
- **Part 6 web (F-I)**: see V2, V3, V6-V10; also the Home card's "at up to" wording was already fixed in `6045d2f`; `components/value/` uses a legacy folder name on purpose (below).

### 3.6 Features never built (F)

| ID | Item |
|---|---|
| F1 | **Order control**: cancel a working order from Trades, History. Needs a `cancel_order` kind, a drain handler (cancel at IBKR through the execution connection, reconcile the `OrderRow`), `ConfirmAction` plus the second LIVE confirmation, a receipt. Reaches the execution path, so it starts with its own spec (superpowers:brainstorming) |
| F2 | The three items `STATUS.md` Part 3 lists as needing trading-side computation and a spec: the scale-in ladder's next-lot zone per held name, a "room left under the regime budget" card, a governing regime per held name |
| F3 | Cross-links between Trades History and Activity Fills (M, Part 3) |
| F4 | The `/recommendations` page (P1 design) |
| F5 | A web surface for the value book's go-live evidence (shadow record, Claude vs baseline, clamp frequency, drawdown vs SPY): today only `python -m scripts.value_report` and `value_backtest` |

### 3.7 Owed by the operator or by an install step (O)

See section 7.2.

## 4. Recommendations

BUILD ON = extend what exists. CUT = drop, with the reason. ADD = new need.

| ID | Call | What, and why |
|---|---|---|
| L1 | **BUILD ON** | Recompose `/research` with `Card`, `SegmentedControl`, `Stub` and the payslip frame. Keep `TopOpportunities` as the lead card (it is already on the system) and `WatchlistTable`'s add typeahead and mutation logic; replace the table with rows. Sectors by IV rank become cards like the Market card. Part 6 |
| L2 | **BUILD ON** | Recompose the stock page around what exists: keep `ValueBlock`, `NameNotes`, `PriceChart` (add price lines), `ChecksSection`, `StatementsTable`, `TechnicalsPanel`, `SentimentPanel`, `NewsPanel`, `SummaryPanel` content and tests; change the frame, the header (name, price, delayed word, Back link, RefreshButton), the section shells (Card + Disclosure) and the order (verdict first for a name on a value list). Part 5 |
| L3 | **BUILD ON** | Restyle only. `UniverseList`, `AddSymbol`, `OverrideBadge` keep their logic, tests and the `ConfirmAction` consequence sentence. `sectors` stays file-only. Part 6 |
| L4 | **BUILD ON** | Give `/news` a title, `SegmentedControl` chips, a `Field` symbol filter and `Card` posts; `NewsCard` content and the grounding labels stay untouched. Part 7 |
| L5 | **REBUILD SMALL (Q1 default); CUT the 8-tab shell** | The page is a hand copy of `ARCHITECTURE.md` that went stale by construction (nothing in the doc-update table covers it): 1,491 lines describing a system without spreads, the value book, regime sizing, the news thread or capital release. Replace with one payslip-styled "How it works" page: who decides what (Python gates, Claude advises, you tap), the three books, where to look in the console, a "reviewed on" date, and `SourceRefs` into `ARCHITECTURE.md`. If the operator would rather cut the page, delete it and its More link |
| L6 | **BUILD ON** | Add per-route titles (S2) and error/not-found pages (S3); no other change |
| D1-D2 | **BUILD** (cleanup) | Port the tests, then delete. Move `DrainWarning` to `components/shell/DrainWarning.tsx` first. Part 4 |
| D3 | **BUILD** | Remove `GET /nav` and its tests and docs, as promised since Part 1. Part 4 |
| D4 | **CUT** | Folding is churn with a cost and no gain: `components/options/` holds the protected files whose "diff against main is empty" checks are path-based, and `components/value/` is a command site kept outside `features/` on purpose so `grep -rn "submitCommand\|confirmCommand" web/features` stays a two-site list. Rule instead: **new code goes in `features/`; `components/` keeps shared primitives (`ui`, `shell`), the protected controls (`options`), the value flow (`value`) and the survivors in D1**. Delete the dead; do not move the living |
| D5 | **CUT** (leave) | Not worth a removal pass; revisit only if one gets in the way |
| D6 | **BUILD** | Part 4 rewrites each reference when it ships |
| V1 | **ADD** | One `_CLOSE_RULE` entry for `CAPITAL_RELEASE` ("Closed to fund a value-book buy, at breakeven or better") with a rule line naming the funding request; check `src/api/routers/options.py` and `src/notify/formatters.py` (they already name it) agree. Part 4, backend |
| V2 | **ADD** | The value process writes a heartbeat each loop; `GET /value/book` gains `drain_healthy` (and its last-seen time); `ValueDecide` and `AnalyseButton` pass it to the receipt so a dead process is said in words. Part 4, backend + web |
| V3 | **ADD** | Show tap-waiting value proposals in "Needs you" and the phone banner, reusing `ValueProposalRow`/`ReviewSheet` flow, under All and Value. Open design question for da-vinci in Part 4: a compact row beside the wheel's cards, or a count that jumps to the Value card |
| V4 | **BUILD ON** | Add `value` to the ledger type, the three book filters, the heading text and `bookWord`. Part 4 |
| V5 | **BUILD ON** | A Value chip on Portfolio, Positions that reuses `buildValueRows`; link a value row to `/stock/SYM#value-block-SYM`. Do not add a Value tab to Campaigns or Calendar (nothing to put there). Part 4 |
| V6 | **BUILD ON** | Draw fair value, entry ceiling, half sale and stop on `PriceChart` as dashed price lines (the position page's strike line, `features/position/UnderlyingChart.tsx`, is the pattern); expose the tranche plan and size tier on `ValueListOut`. Part 5 |
| V7 | **BUILD ON** | Add the optional one-line Claude note to `ValueTopItem` (labelled Claude's, never on a button) and show it; leave the always-null stop alone until a policy sets one. Backend in Part 5, card in Part 6 |
| V8 | **ADD** (small) | Gate the flag on `/value/book` `enabled`. Part 4 |
| V9 | **DEFER** | Needs a contract change (a realised-complete flag on `MonthPay`); fold into Part 8 where the record view reads value realised anyway. Keep the two-request calendar (CUT the `value_realized` field idea: one request per month is cheap) |
| V10 | **ADD** | Part 4's finish runs a fresh reviewer agent over F, G, H, I and takes the missing dark captures |
| S1 | **ADD** | Mount the command palette in the shell (⌘K everywhere, a search entry in the Rail and on More for phones), restyled onto `Field`/`Sheet` tokens. Part 6 |
| S2-S3 | **ADD** | Part 4 |
| S4 | **OPERATOR** | Q6; defaults in section 5.3 |
| M (Part 2, 3) | **BUILD** the honesty ones in Part 4 (In flight/Not traded unknown-is-not-none, `BackToTrades` params, Spreads day in the URL, raw `cash_secured_put`, null stock gain, `?month=` clamp, spread-fills `truncated`); **leave** the rest | The rest are cosmetic or cost more than they return |
| F1 | **BUILD, own track** | Spec first, plan second; it is the only remaining feature that reaches the execution path |
| F2 | **DEFER** | Needs trading-side computation and its own spec; revisit when the regime sizing has a month of live record |
| F3 | **BUILD** (one task) | One sentence on each page linking to the other, in Part 4 |
| F4 | **CUT** | The value book's Top opportunities and Trades, Assessed answer "what should I own"; the scan's buy-to-own list is a 3-factor pre-Phase-4 model (`STATUS.md:147`) and the Telegram card still serves it. Keep the API route |
| F5 | **ADD, later** | Part 8: a read-only "Value record" next to the sizing record on Activity, System |

### 4.1 Reconciling Part 6's web pieces with the overhaul

| Piece | Overlap | Call |
|---|---|---|
| F - Home Value card (`components/value/`) | Home is done; Part 4 only adds V2, V3, V8 and the dark captures | **Keep and extend.** Do not move it to `features/` (D4). Do not give it a tab on Trades (`WHEEL_FILTERS`): Trades has no value history, so a tab would read as an empty book. Revisit in Part 8 |
| G - Stock page value block (`features/stock-value/`) | Part 5 recomposes the page that hosts it | **Keep and extend**: it is already one self-contained component mounted by one line; Part 5 moves the line, adds V6, and may reorder so a name on a value list leads with the verdict. Preserve `AnalyseButton` as the page's one command site |
| H - Research strip (`features/research/`) | Part 6 recomposes the page that hosts it | **Keep and extend**: it becomes the lead card of the new Research page; add V7's note |
| I - `value` kind across Home | Done across Home and Activity Pay; Portfolio, Fills, Ledger missing | **Keep**; V4 and V5 finish the spread of the kind |

## 5. Proposed parts after Part 3

Every part is one plan of the Part 1-3 shape (Execution model with Model and Effort columns, Progress log,
Roadmap, Rulings, Global Constraints, Review Focus, sections with entry checks, TDD tasks, whole-branch review).
"Part N" below always means **web overhaul Part N**, never a value book part.

| Part | Scope | Items | Depends on | Size |
|---|---|---|---|---|
| **4 - Cleanup, honesty and the value gaps (NEXT)** | Section A backend (opus): V1, V2, D3. Section B web cleanup (sonnet): port tests, delete D1, move `DrainWarning`. Section C web gaps (sonnet): V3, V4, V5, V8, the Part 2/3 honesty minors, F3. Section D shell (sonnet): S2, S3. Finish: V10 reviewer + dark captures, D6 docs, Opus whole-branch review | D1-D3, D6, V1-V5, V8, V10, S2, S3, M, F3 | none | 4 sections + finish, ~11 tasks |
| **5 - The stock page** | Backend (opus): tranche plan and size tier on `ValueListOut`, optional note on `ValueTopItem`. Web: header and hero price, chart with value lines, section shells on Card/Disclosure, Checks/Technicals/Statements/Sentiment/News/AI summary restyled in place, Value block reordered for value-listed names | L2, V6, V7 (backend), S5 (Stock paragraph) | Part 4 | 2 sections + finish, ~9 tasks |
| **6 - Research, Universe and search** | Research page on the payslip with Top opportunities leading and V7's note; Watchlist rows; Sectors cards; Universe restyle; shell-level search | L1, L3, S1, V7 (card) | Parts 4, 5 | 2 sections + finish, ~7 tasks |
| **7 - News, More and How it works** | News feed and ticker on the payslip; How it works rebuilt small (Q1) or cut; More polish; DESIGN.md Open Decisions closed (Q6); favicon/name | L4, L5, L6, S4, S5 | Part 6 | 2 sections + finish, ~8 tasks |
| **8 - The value record (gated)** | `GET /value/record` over `value_db.py` (plain SQL, no `src.value`), an Activity view or a System section reading it: baseline vs Claude track, horizon returns, clamp frequency, breaker state, paper sleeve drawdown vs SPY; the `MonthPay` realised-complete flag | F5, V9 | Part 4; a month or more of nightly record; Q4 | 2 sections + finish, ~6 tasks |
| **Order control (own track)** | Spec via superpowers:brainstorming, then a plan: `cancel_order` kind, drain handler, Cancel behind `ConfirmAction` and the LIVE second confirmation, receipt, History copy | F1 | Part 4 (History fixes) | spec, then ~7 tasks |

**Order:** 4, 5, 6, 7, then 8 when the record is worth reading. Order control can be specced in parallel with
Part 4 and built whenever the operator chooses (Q2). Stock goes before Research because the value block is the
page the operator will actually read when a READY name appears, and Part 5's backend work feeds Part 6's card.

### 5.1 Rulings (conventional choices made here; the operator may overturn any)

1. **Numbering.** The old Part 4 is split into Parts 4-7; old Part 5 (order control) loses its number and is "Order control". Plans, STATUS, `web/CLAUDE.md` and `ARCHITECTURE.md` that say "until Part 4" are reworded by Part 4's docs task (the legacy deletions are in Part 4 either way). *Cost if wrong: wording.*
2. **No fold of `components/` into `features/`** (D4). New code goes in `features/`. *Cost if wrong: a later rename pass.*
3. **`components/value/` stays**, and the command-site grep stays: `grep -rn "submitCommand\|confirmCommand" web/features` prints only `features/more/TargetCard.tsx`, `features/stock-value/AnalyseButton.tsx` and their tests. *Cost: none.*
4. **Delete the dead after porting tests.** `DecideControls.test.tsx` and the roll-flow cases are written from `ApprovalCard.test.tsx` and `ShortsTable.test.tsx` and mutation-checked before the old files go. *Cost: none.*
5. **`GET /nav` is removed; the other unused routes stay** (D5).
6. **Capital-release words land before `value.book.enabled`** (V1). If Part 4 is not merged first, the operator must not enable the book.
7. **The value book gets no top-level nav destination, no Trades tab and no new page** until Part 8 (Q3 default).
8. **The calendar keeps its second request** for the value split; no `value_realized` field.
9. **`/recommendations` is cut** (Q5 default); the API route and Telegram card stay.
10. **Titles and boundaries use Next route-segment metadata/`layout.tsx` wrappers**, since most pages are client components that cannot export `metadata`; Part 4 chooses the pattern and tests it.
11. **No new token, colour, font, radius or elevation** is planned in any part; if da-vinci proposes one it waits for the operator (existing rule).

### 5.2 What each part must not do

- Part 4: change a protected file, a Rules Engine path or any wheel/value gate. V1, V2 and D3 are read-side Python (`src/reporting`, `src/api`, one heartbeat write in `scripts/run_value.py` / `src/value`).
- Parts 5-7: add a command site. Part 8: add a write.

### 5.3 Questions for the operator (defaults shown; the plan writer assumes the defaults)

1. **How it works (`/explain`)**: rebuild small, rebuild in full, or cut? *Default: rebuild small (Part 7).*
2. **Order control**: build it before the Research/Stock parts, after Part 7, or leave it? *Default: spec in parallel with Part 4; build after Part 6.*
3. **A "Value" destination** (own nav item and page) or the current spread across Home, Stock, Research and a record view in Activity? *Default: no new destination.*
4. **When should the value record view (Part 8) be built**: now (data exists since Part 2's shadow record), or after the paper sleeve has run a month with `value.book.enabled`? *Default: after.*
5. **Confirm cutting the `/recommendations` page** that the P1 design planned. *Default: cut.*
6. **Close the `DESIGN.md` Open Decisions.** *Defaults: keep "IBKR Income" with a text wordmark and a simple favicon; keep lucide icons; keep the immediate sheet close; leave the legacy bordered decide controls inside sheets as the recorded exception; a disabled quiet button stays transparent and only dims.*

## 6. Binding rules for any plan writer

- **Core invariant.** The Rules Engine is the only path to an order; nothing the web or Claude produces gates, sizes or prices anything. The two written exceptions in `CLAUDE.md` (the CSP contract cut; the value verdict) are untouched and the web only displays them, with Claude's words labelled as Claude's and never on a button.
- **Web fence.** The API reads the trading database read-only and writes exactly one table, `app_commands`, through `src/api/commands.py` (the only importer of `get_command_engine`). Every web action is an intent drained by `approval_service` (or, for the six `value_*` kinds, by the value process). `tests/test_web_fence.py`, `test_eval_skills.py`, `test_regime_fence.py`, `test_news_fence.py`, `test_spreads_fence.py`, `test_value_fence.py` and `test_wheel_spreads_isolation.py` stay green and are never weakened.
- **Value fence.** The API imports from `src.value` only `scorecard` and `schemas`; only `src/api/value_db.py` opens value.db (`mode=ro`, plain SQL); a heartbeat or a record reads through it. `src/reporting/` imports nothing from `src.claude` or `src.value`.
- **Protected files:** `web/components/options/{DecideControls,ConfirmAction,CommandReceipt,HaltControl,AutonomyControl,RollModeControl}.tsx`, `web/lib/commands.ts`, `web/lib/receipt.ts`: `git diff --stat main -- <paths>` prints nothing at every section exit. Deleting an unmounted sibling is allowed; moving or editing these is not.
- **da-vinci.** Every UI task invokes the `da-vinci` skill first (and says so in every subagent prompt); the finish runs `critique` + `audit` + `polish` at 320/390/1440px, light and dark, by a **fresh reviewer agent** (the step F-I skipped). `web/DESIGN.md` is the visual authority: tokens only, lime only on the primary act, unknown is a hatched `n/a`, no state by colour alone, no shadow except the sheet and confirm dialog, charts never animate in, 44px phone targets, zero em dashes and none of "seamless/robust/unlock/elevate" in UI copy. New surfaces get a Surfaces paragraph and a Decision Log entry; `design_md_check.py web/DESIGN.md` exits 0 and the marker date is bumped.
- **Never build inside `web/`.** The operator's `next dev` shares `web/.next`. Gate builds run in a scratch copy: `S="$(mktemp -d)/web" && rsync -a --exclude node_modules --exclude .next web/ "$S/" && ln -s "$PWD/web/node_modules" "$S/node_modules" && (cd "$S" && npm run build)`; remove symlink first when cleaning up. Part 3 used the session scratchpad instead of `mktemp`.
- **Gates.** After every web task `cd web && npx vitest run && npx tsc --noEmit && npm run lint`; after Python `python -m pytest -q && ruff check . && mypy src` from the worktree root (4 ledger/openapi/web-fence tests fail spuriously from elsewhere). After any API contract change regenerate the contract with `IBKR_CONFIG_USE_EXAMPLES=1 python -c "import json; from src.api.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json` and then `cd web && npx openapi-typescript ../docs/web/openapi.json -o lib/api-types.ts` (offline; `npm run gen:api` needs the live API); `tests/test_openapi_current.py` stays green. Baselines: pytest 5665 + 1 skipped, vitest 1485 in 152 files, mypy 360 files (recompute from `git log`, counts go stale).
- **Execution model (token-light, operator-mandated).** Work in a worktree `.claude/worktrees/web-overhaul-N` on `feat/web-overhaul-N` (symlink `.venv` and `web/node_modules`, run `init_db()` with `IBKR_CONFIG_USE_EXAMPLES=1`). The main session is a Sonnet orchestrator at high effort; it runs each section's entry checks itself, spawns **one subagent per section** with the model and effort the plan's Execution model table gives, verifies the report itself (`git log main..HEAD`, `git status`, gate counts, protected-file diff), and **stops and asks before the next section**. After the last code section: one Opus whole-branch review (high), then one Sonnet fix pass (high); ask before merge or push. Opus for Python that touches a fence or money-shaped data; Sonnet for UI.
- **Progress log.** The plan carries one; after every task tick its boxes and fill its row (status, commit, gate, date, every ruling with its cost-if-wrong) in the same commit. A new session resumes from the log and `git log`, never from memory.
- **Doc-update table (`CLAUDE.md`).** New file/module: `ARCHITECTURE.md` folder guide; new config key: the committed example + `ARCHITECTURE.md` + `SETUP.md`; feature built/deferred: `STATUS.md`; UI surface: `web/DESIGN.md`, `web/CLAUDE.md`, `docs/web/api.md` for any route, `docs/web/commands.md` for any kind; a user-visible behaviour change: `SETUP.md` troubleshooting if relevant. Tests accompany behaviour.
- **Gotchas.** Never import `scripts.run_*` (py_compile instead); never copy `research.db`; worktree sessions cannot edit private `config/*.yaml` (new keys go to `config/examples/`, the private copy becomes an operator to-do); daemons do not hot-reload (`./ibkr restart`, trading service before the API); never add an `AGENTS.md` anywhere; `df -h .` as an entry check (20 GiB free at 96% today); pin `now` in tests that compare fixture times with expiries; worktree sessions refuse compound Bash that names git paths.

## 7. Briefs and to-dos

### 7.1 Brief for the Opus plan writer, Part 4

Do this now (Parts 1-3 and the value book are merged). Spawn one `general-purpose` agent with `model: opus`,
`run_in_background: true`, with this prompt:

```
You are the plan writer for **Web overhaul Part 4 (Cleanup, honesty and the value gaps)** in a live trading
repo. Write one implementation plan file. Do NOT commit, do NOT spawn subagents, do NOT touch running services,
the main checkout's data/*.db, or web/.next (the operator's next dev shares it).

Read first: CLAUDE.md; web/CLAUDE.md; web/DESIGN.md (Surfaces, Open Decisions, Decision Log);
docs/superpowers/plans/2026-11-05-web-overhaul-HANDOFF.md IN FULL (sections 3, 4, 5, 6 are your scope and
rules; section 5.1 rulings and 5.3 defaults bind you); docs/superpowers/plans/2026-10-23-web-overhaul-3-
portfolio-activity.md (reproduce its format exactly: header, Execution model with Model and Effort columns and
the orchestrator procedure that passes effort on every spawn, Progress log, Roadmap, Rulings made up front,
Global Constraints, Review Focus, File structure, sections with entry checks, TDD tasks, whole-branch review,
operator to-dos, self-review) and its Progress log; docs/superpowers/plans/2026-10-19-web-overhaul-2-trades.md
rulings (legacy files that stay until Part 4, the DecideControls and roll-flow test coverage) and its review
row; docs/superpowers/plans/2026-10-29-value-book-6-web-telegram.md Sections F-I and its Progress log rulings
(F5, F9, G3, G11, H2-H4, H9, I2, I4, I10); STATUS.md "Built (2026-11-05 - value book Part 6)" and "Built
(2026-10-28 - web overhaul Part 3)"; docs/web/api.md, docs/web/commands.md. Read merged code with
`git show main:<path>` / a `git archive main` scratch copy, never the working tree.

Scope (HANDOFF section 5, Part 4): Section A backend (opus/high): V1 capital-release words in
src/reporting/day.py (+ agreement with src/api/routers/options.py and src/notify/formatters.py), V2 value-process
heartbeat -> GET /value/book drain_healthy (scripts/run_value.py writes, src/api/value_db.py reads, no new
src.value import in the API), D3 remove GET /nav. Section B web cleanup (sonnet/high): port DecideControls and
roll-flow tests first (mutation-check them), move DrainWarning to components/shell, delete the D1 files and
their tests, keep the survivors listed in D1. Section C (sonnet/high): V3 (value taps in Needs you and the phone
banner - decide the design with da-vinci, record the ruling), V4, V5, V8, the Part 2/3 honesty minors listed in
HANDOFF 4 (In flight / Not traded unknown-is-not-none first), F3 cross-links. Section D (sonnet/high): S2 route
titles, S3 not-found/error/loading boundaries (client pages cannot export metadata: choose and test a pattern).
Finish: V10 fresh reviewer agent over F, G, H, I and the missing dark captures, D6 doc rewrites (every "until
Part 4" reference, STATUS.md:949, ARCHITECTURE.md:1596, docs/web/architecture.md drain list, DESIGN.md marker),
Opus whole-branch review, Sonnet fix pass.

Re-check every boundary against the current tree (line numbers in the HANDOFF were read 2026-11-05); rule on any
move with a reason and record each as a ruling with cost-if-wrong. Fold in any deferred minor that Part 4's code
touches; record fixed or deferred. If a design choice is the operator's (e.g. where value taps surface), hand
back a numbered question with your recommendation instead of guessing.

Specificity: complete code for every module, test and command; exact paths; every edited existing line verified
by grep in the CURRENT tree and quoted with line numbers; numeric fixtures you computed yourself. Prototype the
whole part first in a CODE-ONLY scratch copy of main (exclude data/, .claude/worktrees/, web/node_modules,
web/.next, .venv - symlink node_modules and the venv) so every code block passed pytest, vitest, tsc, eslint,
ruff and mypy src; delete the copy after. Token economy: cite spec/plan sections instead of restating; each
section lists exactly the files its subagent reads; targeted gates per task, the full gate at section exits;
3-5 tasks per section. Encode HANDOFF section 6 (fences, protected files, da-vinci in every UI task and every
subagent prompt, never build inside web/, scratch-copy build command, Progress log, doc-update table, gotchas).

Output: docs/superpowers/plans/2026-11-05-web-overhaul-4-cleanup-and-value-gaps.md (do not commit). Invoke
superpowers:writing-plans first. Final message <= 400 words: path and line count; sections with task counts,
model and effort; main rulings; minors fixed/deferred; scope moved; prototype results; operator to-dos; any
question only the operator can answer.
```

Then verify the file exists and its line count, read its Roadmap and Execution model, and relay the summary.
Don't commit the plan; its first task does that.

### 7.2 Operator to-dos

1. Answer Q1-Q6 (section 5.3); none blocks Part 4.
2. **Do not set `value.book.enabled: true` until Part 4 has merged** (V1, V2), and not before the Part 5 (value) fault drills and the ledger history import.
3. Housekeeping: `git worktree remove .claude/worktrees/value-book-6`, then `git branch -d` the merged branches (`feat/value-book-1` to `-6`, `feat/web-home-followups`, `feat/web-overhaul-2`, `feat/web-overhaul-3`, `feat/contract-cache`, `feat/news-thread`, `feat/spreads-claude-picker`, `fix/breaker-ack-auto-roll`, `fix/qualify-partial-chunks`, `fix/spreads-gex-map-spot-wait`, `perf/claude-token-slim`; all are merged into `main`).
4. Disk: `df -h .` shows 20 GiB free at 96%; `research.db` is 2 GB and the value process reads about 1 GB of SEC data a night (Part 2 M13). Check before each long run.
5. Live checks the value book Part 6 still owes (paper): a Telegram tap on a value card reaches the value process and the next RTH cycle sends; the trim card's button; the first digest night; the watchdog's value line; a stale card answers "out of date" (`SETUP.md` section 19, step 14). The restart is done (14:08 today).
6. Look at Home's Value card, the stock page's value block and Research's Top opportunities on a phone in dark mode once (the F-I captures missed dark); Part 4's finish repeats it with a reviewer agent.
7. Ratify or amend `DESIGN.md` Open Decisions (Q6) before Part 7.
8. Leave the `next dev` server running; no plan builds inside `web/`.
