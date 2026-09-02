# Audit & Critique

Loaded from `SKILL.md` Step 6 (AUDIT mode). This is the method for "review this," "what's wrong with," "redesign," or "fix the vibe of" an *existing* page, screen, or component — as opposed to `SKILL.md` Steps 1–5, which are for building something new. Two governing rules before anything else:

1. **Evidence in the codebase is the visual authority, not the absence of a design doc.** A project with no `design.md`/style guide is not "greenfield" just because nothing states its direction on paper — the shipped UI, its token usage, its component patterns *are* the direction. Read them before proposing anything.
2. **Refinement preserves, redesign replaces — never split the difference by polishing a discarded approach.** Decide which one this is (see the decision tree below) before touching code. Half-committing produces the worst of both: it neither respects what's there nor commits to something new.

Pick the finer-grained mode first:

- **Critique** — "review this," "what's wrong with this," "audit the UX" → produce a structured findings report (this file's first half). May or may not lead to code changes; if the user wants fixes, propose them but confirm before a large rewrite.
- **Redesign** — "redesign," "overhaul," "modernize" → the decision tree and invariants (this file's second half) govern how much changes and what must not.

## Part 1 — Critique method

Run whichever of these four lenses fit the ask; for a general "review this" with no narrower scope, run all four and combine into one report.

### 1. Nielsen heuristics (usability correctness)

Score each 0–4 (0 = fails badly, 4 = fully satisfied), sum to a /40 total:

| Heuristic | What to check |
|---|---|
| Visibility of system status | Does the user always know what's happening (loading, saved, error, in-progress)? |
| Match between system and real world | Does language/iconography match the user's mental model, not internal jargon? |
| User control and freedom | Is there an obvious undo/back/cancel from any state, including mid-flow? |
| Consistency and standards | Do similar actions look and behave the same way across the app? |
| Error prevention | Are destructive/irreversible actions confirmed or hard to trigger by accident? |
| Recognition rather than recall | Are options visible in context, or does the user have to remember something from an earlier screen? |
| Flexibility and efficiency of use | Do power users have a faster path (shortcuts, bulk actions) without cluttering it for everyone else? |
| Aesthetic and minimalist design | Is every visible element earning its place, or is there decoration competing with function? |
| Help users recognize, diagnose, and recover from errors | Are error messages specific and actionable, not generic ("Something went wrong")? |
| Help and documentation | Where it's needed (complex or infrequent flows), is guidance available without leaving the flow? |

**Severity bands**: 36–40 Excellent · 28–35 Good · 20–27 Acceptable · 12–19 Poor · 0–11 Critical.

### 2. Cognitive load

Three load types to distinguish: **intrinsic** (inherent to the task — filling a tax form is just complex), **extraneous** (added by bad design — a form that could be simpler but isn't), **germane** (effort that actually helps understanding, like a well-placed example). Only extraneous load is unambiguously worth cutting; intrinsic load is sometimes irreducible, and germane load can be worth keeping.

Working-memory rule (Cowan's revision of Miller's Law): **no more than ~4 items should compete for attention at any single decision point.** A form with 12 visible fields and no grouping asks the user to hold more than a working memory can comfortably manage.

Eight named failure patterns to check for:
1. **The Wall of Options** — too many undifferentiated choices presented at once with no default or grouping.
2. **The Memory Bridge** — the user has to remember something from a previous screen to complete this one.
3. **The Hidden Navigation** — a path through the product that exists but isn't discoverable without prior knowledge.
4. **The Jargon Barrier** — internal/technical terms shown to users who don't share that vocabulary.
5. **The Visual Noise Floor** — so much simultaneous visual competition that nothing is actually prioritized.
6. **The Inconsistent Pattern** — the same kind of action implemented differently in different places.
7. **The Multi-Task Demand** — the user has to hold two things in mind and act on both at once (e.g. cross-reference two panels to fill a third).
8. **The Context Switch** — a flow forces the user out to a different mode/app/tab and back, losing state or place.

### 3. Persona pass

Walk the flow as each of these five, in character, and note where they'd stumble:

| Persona | Profile | Test focus | Red flags to watch for |
|---|---|---|---|
| **Alex** | Impatient power user | Speed, shortcuts, tolerance for friction | Any unnecessary confirmation step, unskippable animation, buried frequent action |
| **Jordan** | Confused first-timer | Onboarding clarity, discoverability | Jargon, missing empty-state guidance, unclear next step |
| **Sam** | Accessibility-dependent (screen reader / keyboard-only) | Full keyboard navigation, semantic structure, labels | Unlabeled controls, focus traps, mouse-only interactions, missing `alt`/`accessibilityLabel` |
| **Riley** | Deliberate stress tester | Edge cases — refresh mid-flow, double-submit, empty/huge inputs, slow network | Lost state on refresh, duplicate submissions possible, no loading/error boundary |
| **Casey** | Distracted mobile user | Thumb-zone reachability, interruption recovery, one-handed use | Primary actions out of thumb reach, no state recovery after backgrounding the app |

Not every persona is equally relevant to every surface — for an Operate-mode internal tool, weight Alex and Sam heavily; for a Persuade-mode public page, weight Jordan and Casey; always run Sam and Riley regardless of mode, since accessibility and robustness aren't optional per the craft floor.

### 4. Technical audit

Score each 0–4, sum to a /20 total:

| Dimension | What to check |
|---|---|
| Accessibility | Contrast, keyboard/screen-reader operability, focus order, semantic structure — against `craft-floor.md` |
| Performance | Unnecessary re-renders, unoptimized images, layout-thrash animations (see `motion-physics.md`'s motion-floor note), bundle-relevant imports |
| Theming | Consistent token usage — colors/spacing traced to `packages/tokens` or the app's design system, not one-off hardcoded values. If dark mode applies: run `dark-mode.md`'s completeness checklist — a themed container with unthemed content/states inside it is the most common finding, not a missing `dark:` class at the top level |
| Responsive | Behaves correctly across the breakpoints that actually matter for this surface (and, on mobile, across device sizes/notch/safe-area) |
| Implementation integrity | Does the code actually do what the UI implies — a "Save" button that silently no-ops on error is an integrity failure even if it looks fine |

### Severity tagging and report format

Tag every finding P0–P3:
- **P0** — blocks core functionality, or a critical accessibility failure (unusable for a class of users).
- **P1** — significant usability harm — most users hit this, meaningfully worse experience, but there's a workaround.
- **P2** — moderate — a real issue, but affects a minority of users or a secondary flow.
- **P3** — minor/polish — worth fixing, not worth blocking on.

Report structure:
```
## Findings — [surface name]
Mode(s) run: [Nielsen / Cognitive Load / Persona / Technical]

### P0
- [finding] — [which lens caught it] — [concrete fix]
### P1
...
### Scores
Nielsen: XX/40 (band). Technical: XX/20.
```
Lead a critique report with P0/P1 findings, not the numeric scores — the scores are a summary for tracking trend over time, not the point of the exercise.

## Part 2 — Redesign method

### Decision tree

1. **Greenfield** — nothing meaningful exists yet (a stub page, a TODO). Treat as BUILD mode (`SKILL.md` Steps 1–5) instead of this file.
2. **Preserve** — the existing direction is sound; the ask is fixes, not a new identity. Run the critique lenses above, fix what they surface, keep the visual system. This is refinement — do not introduce a new palette/type system/layout language while "just fixing" something.
3. **Overhaul** — the existing direction is actively working against the goal (stated explicitly by the user, or clearly evidenced by the critique findings — e.g. a Critical Nielsen band plus multiple P0s traceable to the visual system itself, not just isolated bugs). Run full BUILD mode on the new direction, informed by what the audit found was actually broken.

Don't guess silently between 2 and 3 — if it's ambiguous from the request, this is exactly the kind of thing Step 0's "ask exactly one question" applies to.

### What never changes silently, even in an Overhaul

A visual redesign is not license to change things a redesign doesn't need to touch, several of which will break things outside the UI layer if changed without coordination:

- **URL slugs and route paths** — `routes.md` documents every page route; changing one without updating it (and any inbound links) breaks navigation and violates the Documentation Update Protocol in the root `CLAUDE.md`.
- **Form field `name`s and API payload shapes** — a visual rewrite of a form should not silently rename the fields it submits; that's a backend-compatibility change wearing a redesign's clothes.
- **Analytics/notification event identifiers** — renaming a tracked event or notification `type` breaks historical data continuity. `notifications.type` in this codebase is plain TEXT (see the nectie-mvp `CLAUDE.md` Known Gotchas) — a redesign touching notification UI must not casually rename the type strings it reads.
- **Brand wordmark/logo usage** — a redesign can restyle around the mark; it doesn't get to redraw the mark itself as a side effect.
- **Legal/compliance copy** (terms, privacy language, ticket/refund policy text on the events/ticketing surfaces) — restyle its presentation freely; don't rewrite its content as part of a visual pass.
- **Database-facing naming** — if a redesign touches a component that renders a specific column (e.g. `orders.total`, not `total_amount` — see the nectie-mvp `CLAUDE.md` naming traps), the visual pass must not "clean up" the variable name in a way that drifts from the actual schema field it represents.

### Audit-before-touching checklist for an Overhaul

Before writing new code: read the existing brand tokens (`packages/tokens`, or the app's `design.md`), map the current information architecture (what's actually reachable and how), inventory the real content blocks in play (not a hypothetical simplified version), and run the critique lenses above to know specifically what's broken — a redesign informed by "the Nielsen score was 14/40 because of X, Y, Z" replaces the right things; a redesign done by vibes risks replacing things that were fine and leaving the actual P0s untouched.

---

### Provenance
Adapted from pbakaus/impeccable's `critique.md`/`audit.md` reference docs (Nielsen rubric, cognitive-load framework, 5-persona testing, P0–P3/technical-audit rubric — Apache-2.0) and leonxlnx/taste-skill's redesign protocol (decision tree, "what never changes silently" — MIT). The Nectie-specific invariants list (routes.md, notification type strings, `orders.total` naming) is new, cross-referenced against this repo's own `CLAUDE.md` Known Gotchas rather than invented.
