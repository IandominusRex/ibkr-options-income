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
  page.tsx          Landing page (mounts <CommandPalette/>)
  stock/[symbol]/   Ticker page: react-query on GET /research/{symbol}, polls while
                    fundamentals/technicals/sentiment/news is pending, mounts
                    <SectionShell/> per region, shows the delayed quote (with its age
                    and a "delayed" tag once stale) beside the header. <PriceChart/>
                    is NOT gated behind a Section's state — it fetches its own data
                    from GET /research/{symbol}/bars independently, so a technicals
                    outage must not hide it too
components/
  shell/            Rail, RailSection
  search/           CommandPalette
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
lib/
  api.ts            apiFetch + ApiError
  api-types.ts      Generated from /openapi.json by `npm run gen:api`
  format.ts         formatMoney (compact $391.0B/$1.3M, "n/a" for unknown, "$0"
                    for a real zero), formatPeriod ("Sep 2024"), relativeAge
                    ("5m ago"/"3h ago"/"2d ago"/"1mo ago"), UNKNOWN constant
```