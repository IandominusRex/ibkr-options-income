# Dark Mode

Loaded from `SKILL.md` Step 3 (BUILD, whenever the surface has theming) and Step 6 / `audit-and-critique.md`'s Technical Audit "Theming" row (AUDIT). Dark mode is not an inverted palette — it's a second, fully-specified design, and the most common failure mode in this codebase has been a themed *shell* around unthemed *content*, not a missing toggle.

## Principles

- **Base is soft black, not true black.** `#121212`, not `#000000`. True black crushes shadow-based depth cues (a shadow can't read against a background already at maximum darkness) and produces harsher edge contrast against elevated surfaces than intended. This is nectie-mvp's actual `--bg-primary` value in dark mode.
- **Elevation is communicated by lightness, not shadow.** Shadows barely register on a dark background (`rgba(0,0,0,0.08)`-style light-mode shadows go functionally invisible past a `#1a1a1a`-ish surface — a real gap this codebase had in `Card.tsx`/`Button.tsx`'s hover shadows). Instead, each layer up gets measurably *lighter*: page → card → elevated (modal/dropdown/popover/toast). nectie-mvp's three dark surface tokens:

  | Token | Value | Use |
  |---|---|---|
  | `--bg-primary` | `#121212` | page background |
  | `--bg-secondary` / `--surface-primary` | `#181818` | cards, panels |
  | `--surface-elevated` | `#282828` | modals, dropdowns, popovers, toasts — anything that should visibly "lift" off the page |

  If a shadow is still used alongside this (e.g. to separate a sticky header), increase its opacity/spread over the light-mode value rather than reusing the same rgba string — a light-tuned shadow constant is a silent dark-mode bug, not a shared asset.
- **Text is off-white, not pure white.** `#F5F5F5`-class primary text, `#A7A7A7`-class secondary — pure `#FFFFFF` on `#121212` overshoots to a harsher contrast than intended and reads as glare on OLED displays.
- **Don't reflexively desaturate brand accent colors.** The general principle (saturated colors can vibrate against a dark background) is real, but check it against the actual color before softening it — nectie-mvp's brand orange (`--color-primary-500`, used for links/focus rings/CTAs) was checked and kept fully saturated in both themes; it reads fine on `#121212`. Don't silently invent a "dark mode accent" that drifts from the token the light theme uses.
- **Contrast minimums don't relax for dark mode.** Same 4.5:1 body / 3:1 large-text floor as `craft-floor.md` — check it against the actual dark token pairing, not the light-mode pairing's known-good numbers.

## The semantic/status-color convention

Pastel status colors (success/warning/error/info badges, alert banners, inline status chips) need an explicit dark pairing — they do not fall out of the neutral bg/text/border tokens above. Two formulas, both already correct in `components/ui/Badge.tsx` and the pattern every other status-color usage in the app should match:

**Formula 1 — status badges/pills/alert banners** (pastel-50/100 background + 700 text):
```
bg-{color}-50    dark:bg-{color}-900/30
bg-{color}-100   dark:bg-{color}-900/30
text-{color}-700 dark:text-{color}-300
text-{color}-600 dark:text-{color}-400
border-{color}-200 dark:border-{color}-800
border-{color}-300 dark:border-{color}-800
```

**Formula 2 — icon-circle pattern** (round icon-chip avatars, pastel-100 background + 600 text; 21 occurrences, 13 alone in `NotificationsSidebar.tsx`'s `getNotificationIcon`):
```
bg-{color}-100  dark:bg-{color}-900/30
text-{color}-600 dark:text-{color}-400
```
(400, not 300 — preserves the relatively brighter contrast the 600-vs-700 base already implies.)

A flat `bg-green-50 text-green-700` with no `dark:` pair is the single most common miss in this codebase — it showed up independently in gig/event/project/group status maps and every CRUD vertical's success/error banners, not in one isolated spot. If you're styling a status indicator and this pairing isn't present, add it — don't invent a one-off dark treatment per instance, since that's how five different verticals end up with five slightly different dark reds.

**Not a gap — leave unchanged:** solid `bg-{color}-500` fills (status dots, filled buttons, badges) — saturated enough to read on both themes already. Don't reflexively desaturate accents.

## Completeness checklist (run this per component, not per page)

The most common defect is a themed container with unthemed children — e.g. `Card.tsx` correctly flips its background, but a hardcoded `text-gray-900` inside it doesn't, so the card goes dark while its text stays near-black. Checking "does this component have a `dark:` class" is not sufficient; check that **every element type and every interactive state** inside it does:

- Background, text (all tiers: primary/secondary/tertiary), borders/outlines
- Buttons — **every variant** (primary/secondary/outline/ghost/danger/...) × **every state** (default/hover/focus-visible/active/disabled)
- Form inputs — every type, including the error/invalid state (a red border/text pairing needs its own dark check, same as any other status color)
- Status badges, pills, tags, inline alert banners — see the convention above
- Dropdowns, menus, popovers, tooltips, modals, toasts, sidebars/drawers, bottom sheets — these are frequently styled as raw one-off markup (`bg-white shadow-lg`) instead of going through a themed primitive, so they're disproportionately likely to be missed entirely
- Skeleton/loading placeholders, empty states
- Avatars, icons (check `currentColor` is actually being inherited, not a hardcoded fill)
- Scrollbar styling, focus ring color, `::selection` (see `craft-floor.md`'s browser-chrome list — these need a dark equivalent too, not just a themed instance)

**Prefer migrating hand-rolled markup onto the shared `components/ui/` primitive over patching ad-hoc `dark:` classes onto a duplicate.** A raw `<input>`/`<select>`/`<button>` styled from scratch is both a dark-mode gap and a duplicated implementation of something `Input`/`Select`/`Button` already solve correctly in both themes — fixing the call site to use the primitive closes the gap and removes the duplication in one move.

**The `dark:`-prefix trap.** A `dark:` pair being present does not mean the dark value is *correct*. The single most expensive defect class this codebase's dark-theme remediation found was `bg-white dark:bg-gray-800` on `components/ui/` primitives: it passes any grep gate that counts `dark:` prefixes, but Tailwind's `gray-800` is `#1f2937` (bluish), not the neutral `#181818` the palette re-key established as `--surface-primary` — so every `<Card>` rendered bluish against a neutral page. The fix is to prefer semantic tokens (`bg-surface`, `text-content`, `border-border`, `bg-background`) which auto-adapt and can't drift to the wrong palette, and to gate dark-theme work on *semantic-token adoption* (no raw `bg-white`/`bg-gray-*`/`bg-cream-50` on a swept surface), not on `dark:` presence. `bg-cream-50` is a separate trap of the same kind: it's a fixed `#FFFBF5` from `packages/tokens`, not theme-aware, so it stays cream in dark mode with no `dark:` pair at all.

## This app's theming mechanics

- Mechanism: `<html data-theme="light"|"dark">`, driven by `lib/hooks/useTheme.ts` (persisted to `localStorage['nectie-theme']`) plus a pre-hydration inline script in `app/layout.tsx` to avoid a flash of the wrong theme. A third piece, `components/shell/ThemeRouteSync.tsx` (mounted once in `app/layout.tsx`), re-applies the same resolution on every client-side navigation — the pre-hydration script only runs on a hard load, and `useTheme()`'s own reactive effect only fires while it happens to be mounted (today, only the settings page). All three must agree on the light-only route list; update together. Tailwind's `darkMode` config keys off `[data-theme="dark"]`.
- Prefer the semantic Tailwind aliases (`bg-surface`, `text-content`, `border-border`, `bg-background`) over `dark:`-prefixing a raw palette class — they resolve to the CSS custom properties above and adapt automatically, no `dark:` variant needed. Reach for an explicit `dark:` pair only for values with no semantic token yet (most commonly the status-color convention above).
- **Public/marketing surfaces stay permanently light by design**, not by omission: landing (`/`), `/explore`, public event pages (`/events/[slug]`), public portfolio pages (`/p/*`), plus the auth pages `/login` and `/signup` (added after the original remediation plan closed — OAuth-button and brand-consistency reasons). `/forgot-password`, `/reset-password`, and `/onboarding` are **not** in this list — they keep the dark styling Phase 7 gave them. Don't add dark styling to the exempt list above or "fix" their lack of `dark:` classes — that's the intended state, not a gap.
- Per-portfolio content (`components/portfolio/renderers/*`) renders a portfolio owner's own chosen `theme.backgroundColor`/`theme.textColor`, independent of the viewer's app-level theme preference. That's a separate, intentional theming system — don't conflate a portfolio's own palette with app dark mode. The *editor chrome* around that content (`BlockEditor`, toolbar, the dashboard list/edit UI) is a normal app surface and does need standard dark coverage.
- `nectie-mobile` has no dark mode yet — `packages/tokens` ships light-mode values only. The principles above still apply whenever that work starts; the values should flow through `packages/tokens`/NativeWind rather than CSS custom properties.

---

### Provenance
Elevation-via-lightness and accent-desaturation framing informed by the `dark-mode-design` skill (sickn33/agentic-awesome-skills, MIT) — reviewed as reference material, not installed. The concrete palette values, token names, convention formula, and completeness checklist are this project's own, derived from a full dark-mode coverage audit of `nectie-mvp` (see `.claude/docs/plans/archive/2026-08-24-dark-theme-remediation.md`).
