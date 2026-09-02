---
name: frontend-design
description: Create distinctive, production-grade frontend interfaces, and audit or redesign existing ones, with high design quality — for nectie-mvp (web), nectie-mobile (React Native/Expo), or standalone artifacts. Use this skill when the user asks to build web components, pages, artifacts, posters, or applications; style or beautify any UI; add or tune animation, gestures, or transitions; or review, critique, redesign, or "fix the vibe of" an existing page, screen, or component. Generates creative, polished, platform-correct code that avoids generic AI aesthetics and passes a real craft floor, not just a bold first impression.
---

This skill covers two modes — **BUILD** (make something new) and **AUDIT** (review or redesign something that exists) — across two platforms this repo ships to: `nectie-mvp` (Next.js/Tailwind/Framer Motion web) and `nectie-mobile` (Expo/NativeWind/Reanimated). It also works standalone, for artifacts and one-off pages with no repo context. Determine mode and platform in Step 0 before doing anything else.

Four reference files hold the material that would otherwise bloat this router; each is named at the point it's needed. Don't preload them — pull each in only when the step that needs it is reached.

## Step 0 — Read the Brief, Choose Mode and Platform

Before any dial-setting, aesthetic direction, or code, state your read of the request in one line. Most bad AI design output isn't a bad aesthetic choice — it's skipping straight to a default aesthetic instead of reading the room. Something like:

> *Reading this as: a public event page for a ticketed gig — Persuade mode, web, needs to convert a stranger into a buyer in one scroll.*

If the brief is genuinely ambiguous on something that changes the output materially (audience, platform, tone), ask **exactly one** clarifying question — never a checklist of them. If it's decidable from context, decide and move on.

**Mode:**
- **BUILD** — new component, page, or app; "make this," "add," "build," "style this." → Steps 1–7 below.
- **AUDIT** — "review," "critique," "what's wrong with," "redesign," "fix the vibe of," an *existing* page/screen/component. → jump to Step 6 and `references/audit-and-critique.md`. Don't run the BUILD steps' aesthetic-direction machinery on an audit — the existing direction is the baseline to evaluate against, not something to override on sight (impeccable's rule: *refinement preserves, redesign replaces — never split the difference by polishing a discarded approach*).

**Platform** — check which tree the files under discussion live in, or ask if there's no existing file to anchor on:
- **`nectie-mvp/`** or no repo context (standalone artifact) → web: Tailwind CSS, Framer Motion, `next/image`, CSS custom properties.
- **`nectie-mobile/`** → React Native via Expo SDK 57: NativeWind v4 (Tailwind classes) *or* inline `style={{}}` objects using `@nectie/tokens` (both patterns are in use — match the file you're editing), `react-native-reanimated` 4.x + `react-native-gesture-handler` for motion, `expo-router` for navigation. No CSS: no `backdrop-filter`, no `@font-face`, no CSS gradients, no `box-shadow` string syntax. Before reaching for a translucency, gradient, or haptics effect, check it's installed — as of this writing `expo-linear-gradient`, `expo-blur`, and `expo-haptics` are **not** in `nectie-mobile/package.json`; say so and offer `npx expo install <pkg>` rather than writing code against an import that will fail to resolve.
- If touching either app, prefer the tokens already defined in `packages/tokens/src/index.ts` (`colors`, `semantic`, `fontSizes`) over inventing a new palette from scratch — both apps' visual identity is supposed to converge there.

## Step 1 — Choose the Visitor Success Mode

Not every surface should be judged by the same standard. A settings screen and a landing page failing to meet the same "bold and memorable" bar is not a design failure — it's the wrong bar. Pick one of four modes by **what the surface is for**, not what product category it belongs to (a tool's own marketing page is still Persuade even though the tool itself is Operate):

| Mode | Surface examples in this repo | What wins |
|---|---|---|
| **Persuade** | `/`, `/events/[slug]` public page, portfolio landing sections | The design *is* the pitch. Earn attention, then action. |
| **Operate** | `app/dashboard/**`, gig/event management, forms, the messaging inbox | Scanability, consistency, native platform conventions outrank expression. Brand shows up in *precise details*, not loud gestures. |
| **Read** | Long-form profile bios, review threads, docs-like content | Structure for comprehension first; typography and hierarchy do the work. |
| **Experience** | Portfolio pages (`/p/[username]/[slug]`), photo albums, event photo galleries | The content leads from the first viewport; the chrome recedes. |

Full definitions and worked calibration guidance: `references/visitor-modes.md`.

## Step 2 — Commit to a Bold Aesthetic Direction (BUILD only)

Understand the context, then commit:
- **Purpose**: What problem does this interface solve? Who uses it?
- **Tone**: Pick a distinct direction — brutally minimal, maximalist chaos, luxury/refined, lo-fi/zine, dark/moody, soft/pastel, editorial/magazine, brutalist/raw, retro-futuristic, handcrafted/artisanal, organic/natural, art deco/geometric, playful/whimsical, industrial/utilitarian, and endless variations beyond this list. Use these as inspiration, not a menu to pick from verbatim — the final design should feel singular, every detail working in service of one cohesive direction.
- **Constraints**: framework, performance, accessibility, the platform limits from Step 0.
- **Differentiation**: what makes this unforgettable — the one thing someone remembers an hour later. If the honest answer to "what would they describe an hour later?" is just a mood, the direction hasn't committed yet.

**Calibrate with three dials**, each 1–10, and let the Visitor Mode set your starting range before you adjust for the specific brief:

- `VARIANCE` (1 = perfectly symmetric/systematic, 10 = artsy chaos) — Operate 2–4, Read 2–4, Persuade 6–9, Experience 7–10.
- `MOTION` (1 = static, 10 = cinematic/physics-driven) — Operate 2–3, Read 1–3, Persuade 5–8, Experience 4–7.
- `DENSITY` (1 = airy/gallery, 10 = packed/cockpit) — Operate 4–6, Read 3–5, Persuade 2–4, Experience 1–3.

**Choose a clear conceptual direction and execute it vigorously.** Bold maximalism and refined minimalism both work — the key is intentionality, not intensity. Match implementation complexity to the vision: a maximalist direction needs elaborate code with layered effects; a minimalist one needs restraint and precision. Both need meticulous attention to spacing, typography, and detail — excellence is in the execution, not the amount of stuff.

## Step 3 — Frontend Aesthetics Guidelines

- **Typography**: carries the design's voice. Default fonts signal default thinking — see `references/anti-patterns.md` for the current over-saturated list (it's grown well past Arial/Roboto). Display type should be expressive, even risky; body text legible and refined; pair them like actors in a scene. Work the full range — size, weight, case, spacing — for hierarchy. Web: `next/font` or a `<link>` load. Mobile: bundle the font file and load via `expo-font` (`useFonts`) — there's no `@font-face`.
- **Color & Theme**: commit to a position — bold and saturated, moody and restrained, or high-contrast and minimal — never a timid, non-committal distribution. Lead with a dominant color, punctuate with sharp accents. Web: CSS custom properties. Mobile: `@nectie/tokens` objects, or NativeWind theme extension if the palette is net-new. If the surface has (or should have) dark-mode support, `references/dark-mode.md` has this app's actual token values, the semantic/status-color pairing convention, and the completeness checklist — a themed container with unthemed content inside it is the most common failure, not a missing toggle.
- **Motion**: the physics, not just the vibe, is in `references/motion-physics.md` — spring parameters, interruptibility, velocity handoff, rubber-banding, and reduced-motion handling, all with both web (Framer Motion/CSS) and mobile (Reanimated) code. The one-line version: prioritize CSS-only for HTML, Framer Motion for React web, Reanimated for React Native; one well-orchestrated page-load with staggered reveals beats scattered micro-interactions; every animation should be *motivated* — if you can't name what it communicates (hierarchy, feedback, state transition, storytelling), don't add it.
- **Spatial Composition**: unexpected layouts within the chosen Visitor Mode's constraints — asymmetry, overlap and z-depth, diagonal flow, grid-breaking elements, dramatic scale jumps, full-bleed moments, generous negative space or controlled density (per your `DENSITY` dial).
- **Backgrounds & Visual Details**: build atmosphere rather than defaulting to solid colors — gradient meshes, noise/grain overlays, geometric patterns, layered transparency, dramatic or soft shadows and glows, decorative borders, print-inspired textures (halftone, duotone, stipple). Web: CSS gradients and `backdrop-filter` are free. Mobile: gradients need `expo-linear-gradient`, translucency needs `expo-blur`'s `<BlurView>` (`backdrop-filter` doesn't exist in React Native) — confirm installed before writing the import.

## Step 4 — Never Ship a Generic AI Aesthetic

The full, current catalogue — over-saturated fonts, palette clichés, layout tells, and copy-cadence tells — is `references/anti-patterns.md`. It's long because it's been mined from real generation failures across several independent projects, not theorized; skim it before finishing any BUILD task, and treat these five as non-negotiable regardless of direction:

1. No purple/violet gradients on white or near-white — the single most recognizable AI tell.
2. No em dash (`—`) anywhere in shipped copy, in any context. Not "sparingly." Zero.
3. Pick one elevation technique per surface — border **or** shadow, never both stacked (that's a "ghost card").
4. No icon-in-a-rounded-square sitting above a heading as the default feature-card template.
5. No section-number eyebrows (`01 /`, `00 · INDEX`) or fake version/status chrome (`v1.4.2`, pulsing status dots, locale/weather strips) unless the product is genuinely versioned software with a real reason to show it.

## Step 5 — The Craft Floor (mandatory, in every direction)

Boldness is not an excuse to skip the baseline. Full checklist — contrast minimums, measure, elevation, motion-reduction fallbacks, component states — is `references/craft-floor.md`. The parts that are easy to silently skip:

- Body text ≥ 4.5:1 contrast, large text ≥ 3:1 (WCAG AA) — check this against your actual background, not the nominal token name.
- Secondary text on a colored surface is a *tint of that surface's hue*, never a flat desaturated gray dropped on top.
- Line measure 65–75 characters for body copy.
- Every interactive element has hover *(web)* or pressed *(mobile, via `TouchableOpacity`/`Pressable` state)*, focus, disabled, loading, and empty states designed — not just the happy path.
- Respect `prefers-reduced-motion` (web) — three separate signals matter (motion, transparency, contrast), see `references/craft-floor.md` for the fallback per signal.

## Step 6 — Reviewing or Redesigning an Existing Surface (AUDIT mode)

Don't run Steps 1–5 blind on something that already exists — evidence in the codebase is the visual authority, not the absence of a design doc. `references/audit-and-critique.md` has the full method: a Nielsen-heuristics usability rubric, a cognitive-load checklist, a five-persona pass (impatient power user, confused first-timer, accessibility-dependent, edge-case stress tester, distracted mobile user), P0–P3 severity tagging, and — when the ask is closer to "redesign this" than "review this" — a redesign protocol with an explicit list of what must never change silently (URL slugs, form field names, analytics event names, legal copy).

## Step 7 — Pre-Flight Check

Before calling BUILD work done, honestly tick each of these — if one can't be ticked, it isn't done:

- [ ] Stated a one-line Design Read before writing code (Step 0).
- [ ] Picked a Visitor Mode and it matches what the surface is actually for (Step 1).
- [ ] The direction is committed and singular — no hedging between two aesthetics.
- [ ] Zero em dashes; zero purple-gradient-on-white; zero stacked border+shadow.
- [ ] Ran the five-item list in Step 4 and skimmed `references/anti-patterns.md` for anything direction-specific.
- [ ] Contrast, measure, and all interactive states pass the Step 5 craft floor.
- [ ] Reduced-motion fallback exists if the build has any non-trivial animation.
- [ ] If dark mode applies to this surface: ran the `references/dark-mode.md` completeness checklist — every element type and every interactive state, not just the container's base colors.
- [ ] Platform-correct: no CSS-only APIs in RN code, no missing-package imports (gradient/blur/haptics) on mobile.
- [ ] If working inside `nectie-mvp` or `nectie-mobile`: colors and type scale trace back to `packages/tokens` (or a deliberate, stated departure from it).

Claude is capable of extraordinary, award-worthy creative work. Don't hold back — but "unforgettable" and "meets the craft floor" are both required, not a tradeoff between them.

---
*Synthesized from leonxlnx/taste-skill (MIT), pbakaus/impeccable (Apache-2.0), and emilkowalski/skills' apple-design (MIT), plus this repo's own token system and known platform constraints. See `references/*.md` for per-topic detail and provenance.*
