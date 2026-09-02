# Anti-Pattern Catalogue

Loaded from `SKILL.md` Step 4. This is the specific, current version of "avoid generic AI aesthetics" — mined from real generation failures across several independent design-taste projects (see provenance at the bottom), not theorized from first principles. That's why it's this granular: vague advice like "avoid clichés" gets ignored by a model that doesn't know what today's clichés actually look like.

Two tiers, and the difference matters:
- **Hard bans** — structurally wrong regardless of aesthetic direction. Break these in brutalist work exactly as much as in soft/luxury work.
- **Current tells** — over-saturated *right now* because every model reaches for them by default, not because they're inherently bad. A genuinely brutalist or retro-futurist brief might deliberately want a "cyan on dark" moment — the point is it should be a deliberate choice sourced from the brief, not the unexamined default. This list will go stale; if a "tell" here stops being everyone's default, it stops being a tell.

## Contents
1. Typography tells
2. Color & palette tells
3. Layout & component tells
4. Structural chrome tells (fake status/version UI)
5. Copy & content tells
6. Motion tells
7. Hard numeric caps
8. Consistency locks

---

## 1. Typography tells

**Hard ban**: none here are structural — font choice is direction-dependent — but these are so saturated they need a deliberate reason to use:

- `Inter`, `Roboto`, `Arial`, `Space Grotesk`, `Geist`, `Plus Jakarta Sans`, system font stacks — the default-of-defaults. If the brief doesn't specifically call for a neutral system-feel (e.g. dense internal tooling in Operate mode), skip these.
- `Fraunces` and `Instrument Serif` specifically — "the two LLM-favorite display serifs." If a serif display face is right for the direction, rotate through less-reached-for options instead (Canela, Reckless, Söhne, Editorial New, GT Sectra, Tiempos, Domaine, Freight Display, National, Signifier, or similar — the point is variety project to project, not this specific list).
- Italic serif set at display size as the default "elegant" signal — reach for weight, size, and spacing contrast instead of leaning on italics alone.
- **Extreme negative tracking** on headlines as a reflexive "modern" signal — tracking should follow the typography-mechanics logic in `motion-physics.md` §Typography (negative at large sizes is fine; the tell is applying it *without* the optical-sizing reasoning behind it).
- Don't reuse the same display font across consecutive unrelated projects — if the last thing you built used a given serif or display face, treat it as unavailable for this one.

## 2. Color & palette tells

**Hard ban**:
- Purple/violet gradients on white or near-white backgrounds. The single most recognizable AI-generated-UI tell that exists. No exceptions, no "but it's more subtle here."
- Cyan-on-dark as an unexamined default "techy" palette.

**Current tells**, avoid without a specific reason:
- The "premium consumer" cliché family — beige/cream ground + brass/gold accent + oxblood or espresso dark tone (roughly `#f5f1ea` / `#b08947` / `#9a2436` / `#1a1714` territory). Oversaturated for anything positioned as artisanal, wellness, or luxury-adjacent.
- Cream-as-default "tasteful" surface color — has itself become a tell, not a safe neutral choice.
- Gradient text (text-fill gradient on headlines) — reach for weight/size/color-block contrast instead.
- Dark-glow / radial-halo / radial-spotlight-glow backgrounds behind hero content — the generic "AI SaaS hero" background.
- Repeating diagonal stripe gradients as a texture filler.
- If a palette family was used on the last project generated in this direction, use a different family this time — rotate, don't repeat.

## 3. Layout & component tells

**Hard ban**:
- **Ghost cards**: a 1px border *and* a soft outer shadow on the same surface to declare elevation. Pick one — border or shadow, never both stacked.
- **Icon-tile-stack feature cards**: small rounded-square icon container sitting above a heading, repeated in a 3-or-4-up grid. This is the single most universal AI feature-card template — if a feature grid is needed, vary the internal composition (icon inline with heading, asymmetric card sizes, a different visual anchor per card) instead of stamping the same icon-over-heading-over-body cell repeatedly.
- **Side-tab cards**: a thick colored border on exactly one side of a card as a category/status indicator. Immediately recognizable as AI output; use a genuinely designed status treatment instead (badge, icon, background tint) if status needs marking.
- **Nested-box / "prison of containers"**: a card inside a card inside a padded section inside a bordered container. A section should read as one primary framing move, not layered frames. If you find yourself nesting a bordered `div` more than one level deep for pure visual structure (not semantic grouping), collapse it.
- Animating an image (or its parent container) on hover as a default "interactive" signal — scale/tilt-on-hover for images specifically has become a tell. If hover feedback is warranted, animate something more specific to the interaction than "the whole photo moves."

**Current tells**:
- Monotonous, unvaried spacing between every section — real composition has rhythm (tight, then generous, then tight), not one repeated gap value used everywhere.
- Marquee/ticker scrolling text as a generic "modern" motion signal, used decoratively rather than because content genuinely needs a scrolling strip (e.g. a real logo wall).
- A repeating grid-line or dot-grid background pattern applied indiscriminately as texture ("codex grid background") — fine if it's load-bearing to the direction (e.g. genuinely blueprint/schematic-themed), a tell if it's just default atmosphere.
- Two CTAs on one page with the same underlying intent under different words ("Get in touch" / "Contact us" / "Let's talk" are all "contact" — collapse to one before shipping).
- More than 2 consecutive left-image/right-text (or reverse) alternating sections — the 3rd repeat reads as a template, not a composition. Break the pattern.
- An 8-ish-section page using fewer than 4 distinct layout families across those sections — repetition of the same section shape end to end reads as a generated page, not a designed one.

## 4. Structural chrome tells (fake status/version UI)

**Hard ban** unless the product is genuinely versioned software with a real reason to surface this to the user:
- Section-number "eyebrows" (`01 /`, `00 · INDEX`) above headings.
- Fake version/status footers (`v1.4.2`, `BETA`, build hashes) with no actual versioning system behind them.
- Decorative pulsing/glowing status dots implying "live" state with nothing live behind them.
- Locale/weather status strips (`LIS 14:23 · 18°C`) as pure decoration.
- "Quietly in use at [logos]" social-proof headers with no real customer logos to show.
- Scroll-cue chevrons/arrows (`↓ scroll`) as a default hero-bottom decoration.
- Photo-credit-style captions used as pure decorative typography rather than actual attribution.
- Uppercase-tracked "eyebrow" labels above every section heading — cap it at roughly one per three sections; if you're using more, the eyebrow has become a tic, not a hierarchy device.
- A kicker label directly above the main heading as the default way to add "context" — this is one of the most-flagged tells across every source project reviewed here. If context is needed, integrate it into the heading or subhead instead of bolting on a label line.

## 5. Copy & content tells

**Hard ban**:
- **Em dash (`—`) anywhere in shipped copy.** Not "used sparingly," not "fine in body text" — zero. Models default to it heavily enough that any nonzero count reads as unedited AI output. If a sentence structurally wants an em dash, restructure the sentence.
- Fake-precise invented numbers ("Trusted by 12,847 teams," "99.97% uptime") with no real source — pick a number that's true, round, or explicitly a placeholder marked as such.

**Current tells**:
- Marketing buzzword soup — "seamless," "robust," "delve," "moreover," "unlock," "elevate your workflow" — without a concrete claim underneath.
- The "not just X, it's Y" negation-pivot sentence structure, overused as a rhetorical device.
- Aphoristic cadence: three or more sections each landing on a short, punchy rebuttal-style closing line. Reads as AI cadence when it's the section's structural default rather than an earned moment.
- Mechanical triads — reaching for exactly three parallel items/adjectives as the default list length regardless of what the content actually has to say.
- A genericness test worth running on any headline or tagline: swap the product/brand name for a direct competitor's. If nothing in the sentence becomes false, the copy hasn't said anything specific enough yet.

## 6. Motion tells

Covered in depth in `motion-physics.md`; the two that belong on this list specifically because they're visual/aesthetic rather than physics-correctness issues:

- Bounce/elastic easing applied reflexively to routine UI transitions (menu opens, tooltips, card hovers) — reserve genuine bounce for moments where the *content* has momentum (a drag-released element, a toast that overshoots slightly), not as a default "playful" signal on everything.
- One well-orchestrated page-load with staggered reveals communicates more intent than a dozen small, scattered micro-interactions competing for attention. If every element on a page animates independently, none of them read as meaningful.

## 7. Hard numeric caps

From hero-section discipline specifically — these are genuinely testable, not vibes:

- Headline: 2 lines max.
- Subtext: ≤ 20 words / 4 lines.
- Max 4 distinct text elements in a hero (eyebrow + headline + subtext + CTA is already at the ceiling — don't add a 5th).
- No CTA button text that wraps to a second line at any supported viewport width.

## 8. Consistency locks

Audit these as a pass, not just a rule to keep in mind while building:

- **Color Consistency Lock**: the palette established in Step 2 doesn't drift section to section — no surprise unrelated accent color showing up once, halfway down the page.
- **Shape Consistency Lock**: corner radii, border weights, and shadow treatments stay from one system throughout — don't mix sharp-cornered cards with pill-shaped ones without a reason.
- **Page Theme Lock**: no unannounced light-to-dark (or dark-to-light) flip mid-page. A deliberate full-bleed dark section within a light page is a composition choice; an accidental one two-thirds down because a component was copied from a dark-mode example is a bug.

---

### Provenance
Synthesized and generalized from: leonxlnx/taste-skill's "Production-Test Tells," hero discipline, consistency-lock, and serif/palette-rotation rules (MIT); pbakaus/impeccable's 59-rule anti-pattern detector, `craft-floor.md`, and `docs/STYLE.md` copy rules (Apache-2.0). Rules stated as house-specific bans in the sources (e.g. specific banned hex codes, specific banned icon libraries) were generalized here into the underlying pattern rather than copied as literal law, since this skill needs to support many aesthetic directions rather than enforce one studio's taste.
