# Visitor Success Modes

Loaded from `SKILL.md` Step 1. The core idea: "good design" isn't one bar. What makes a landing page succeed (it earns attention, then a click) would make a settings screen worse if applied literally (constant novelty is the opposite of what makes a form trustworthy). Pick a mode before picking an aesthetic direction — the mode sets *what winning even means* here, and the direction in Step 2 is how you execute toward that.

## The rule: mode follows surface, not product category

A tool's own marketing page is still **Persuade** even though the tool itself is **Operate**. A fashion house's documentation page is still **Read** even though the brand is visually maximalist everywhere else. Ask "what is this specific screen for," not "what kind of product is this."

This matters more in a two-sided marketplace like Nectie than in a single-purpose product: **the same route can be a different mode depending on who's looking at it and why.** A nebbie's portfolio page is Operate when *they're* editing it (`/dashboard/portfolio/edit`) and Persuade-shading-into-Experience when an entity is discovering it as a stranger (`/p/[username]/[slug]`). Don't assume a route's mode from its URL alone — ask who's arriving and what they're there to do.

## The four modes

### Persuade
*The design itself is the pitch. Earn attention, then earn action.*

Applies to: the public landing page, `/events/[slug]` public event pages, a public-facing portfolio's landing sections, anything a stranger lands on before they have any relationship with the product.

What wins: a strong, committed point of view; a clear single next action; visual memorability. This is where the boldest end of the `VARIANCE`/`MOTION` dials from `SKILL.md` Step 2 belongs (typical range: variance 6–9, motion 5–8, density 2–4 — airy, not packed, because a stranger has no reason yet to parse density).

### Operate
*Scanability, consistency, and native platform conventions outrank expression. Brand lives in precise details, not loud gestures.*

Applies to: essentially everything under `app/dashboard/**` — gig/event management, applications, the messaging inbox, settings, forms, availability/calendar editing. This is where someone comes back daily to get something done; novelty here is a cost (relearning where things are) not a delight.

What wins: predictable layout, information density tuned to the task (not maximized or minimized reflexively), fast recognition over first impression. Dial range: variance 2–4, motion 2–3 (motion here should almost entirely be *feedback* — confirming an action happened — not *expression*), density 4–6. Brand personality still belongs here, but it shows up in the quality of a hover state, the phrasing of an empty state, the easing on a toast — not in a bold hero moment, because there isn't one.

### Read
*Structure for comprehension first.*

Applies to: profile bios, review threads, long-form text content, documentation-like surfaces. Typography and hierarchy carry the design; anything visually loud competes with the actual content for attention.

What wins: the 65–75ch measure and leading rules from `craft-floor.md`, clear heading hierarchy, restraint everywhere else. Dial range: variance 2–4, motion 1–3, density 3–5.

### Experience
*The content leads from the first viewport; the interface recedes.*

Applies to: portfolio galleries (`/p/[username]/[slug]` once past the pitch), photo albums, event photo galleries — anywhere the actual creative work (a photo, a performance clip, a design piece) is the point and the chrome around it should get out of the way.

What wins: the artifact fills the frame; navigation and UI chrome are minimal and often only appear on interaction (hover/tap-to-reveal). Dial range: variance 7–10, motion 4–7 (motion in service of *presenting* the content — transitions between pieces — not decorating the frame around it), density 1–3.

## Mixed-mode surfaces

A single page frequently hosts more than one mode in different regions — this is normal, not a sign the framework doesn't fit. A dashboard list view (Operate) with an empty state that's making a small pitch for a related feature (a sliver of Persuade) is common and fine. What to avoid is applying one mode's dial settings *uniformly* across a page that actually needs to shift — e.g., building an entire event-management dashboard at `VARIANCE: 8` because the public event page it's paired with is bold, when the organizer using the management view needs `VARIANCE: 3`.

## Worked example: the events domain

Concrete, since this repo has one in progress:
- `app/dashboard/events/**` (create/edit/manage, applicants, check-in) → **Operate**. An organizer running check-in at a door needs speed and legibility, not a mood.
- `app/events/[slug]` (public event page, ticket purchase) → **Persuade**, tipping toward **Experience** if the event has strong photo/video content to lead with.
- `components/events/EventCard`, used inside a feed or search results → **Operate**-leaning even though it may appear on a Persuade page, because its job there is fast scanability across many cards, not individually pitching.

## Mobile note

The mode framework applies identically on `nectie-mobile` — but Operate mode there should lean even harder into native platform convention than its web equivalent, since users bring stronger built-in expectations from the OS (iOS/Android navigation patterns, native gesture conventions) than they do to a web dashboard. `references/motion-physics.md`'s gesture-design section is Operate-relevant on mobile in a way it usually isn't on web, since touch interactions carry more of the "does this feel native" judgment than hover-driven web UI does.

---

### Provenance
Adapted from pbakaus/impeccable's "Visitor Success Modes" concept (Apache-2.0) — the four-mode framework and "surface not category" rule are impeccable's own contribution among the four source repos researched for this skill; the Nectie-specific surface mapping and mixed-mode/mobile notes are new.
