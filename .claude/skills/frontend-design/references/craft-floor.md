# Craft Floor

Loaded from `SKILL.md` Step 5. Boldness and craft aren't a tradeoff — this is the set of minimums that hold regardless of which aesthetic direction was chosen in Step 2. A maximalist, chaotic, `VARIANCE: 9` design still needs 4.5:1 body contrast; a restrained minimalist one still needs every interactive state designed. Treat this as a pass to run near the end of a BUILD task, not something to hold in your head while making creative choices.

Reduced-motion handling has its own detailed table in `motion-physics.md` — not repeated here.

## Contrast

- Body text: **4.5:1** minimum against its actual rendered background (WCAG AA). Large text (≈18px+/bold ≈14px+): **3:1**.
- Check this against the *real* composited background, not the nominal token name — text sitting on a semi-transparent surface over an image needs the contrast check run against the worst-case image region behind it, not the surface color alone.
- **Secondary text on a colored surface must be a tint of that surface's hue**, not a flat desaturated gray dropped on top. Gray-on-color is a specific, common failure: it looks "safe" but reads as muddy and lower-contrast than intended. Derive the secondary tone from the surface's own hue (lighter/darker along the same hue, not toward gray).

## Elevation

- Choose **either** a border **or** a shadow to declare a surface is raised — never both on the same element. Stacking a 1px border with a soft outer shadow produces a "ghost card": visually busier than either technique alone and the single most common over-engineered-elevation tell.
- A shadow needs both **offset and blur** to read as depth. A colored halo with no offset is decoration, not elevation — it doesn't communicate "this is above that," just "this has a glow."

## Typography floor

- Body text: never below **12px** (web) / equivalent on mobile accounting for system font scaling.
- UI/label text: never below **11px** even for secondary chrome.
- Leading: never tighter than **1.3×** the font size for any multi-line text block (display headlines at the tight end of `motion-physics.md`'s 1.05–1.1 range are a deliberate exception for *single-line* headings, not paragraphs).
- Tracking: never tighter than **−0.04em**, even on large display type.
- Body copy measure: **65–75 characters** per line. Wider columns hurt readability regardless of how good the type looks.
- Never justify body text (produces uneven, distracting word-spacing) unless a hyphenation engine is actually running to compensate.
- No skipped heading levels (`h1` straight to `h3`) — screen reader users navigate by heading structure, and a skipped level breaks that navigation even when it looks fine visually.

## Component states

Every interactive element needs its full state set designed, not just the resting/happy-path appearance:

- **Web**: default, `:hover`, `:focus-visible` (a real focus ring, not `outline: none` with nothing replacing it), `:active`, `:disabled`, loading, error, empty.
- **Mobile**: default, pressed (`TouchableOpacity`'s `activeOpacity` or `Pressable`'s `pressed` state — actually implemented, not left at the platform default), disabled, loading, error, empty. There's no hover state to design for touch, but there is a pressed state, and it's the one most often skipped.

An empty state is not "hide the component" — it's a designed state with its own copy and, where useful, an action (e.g. "No applications yet — browse open gigs").

## Browser/platform chrome (web-specific, easy to forget)

Even the parts of the page not directly "designed" should carry the theme:

- Text selection color (`::selection`)
- Caret color on inputs
- Scrollbar styling where the platform allows it
- Focus ring color/shape (see component states above — this must exist, themed or not)
- Tabular numerals (`font-variant-numeric: tabular-nums`) on any numeric data that updates or lines up in a column (prices, counters, timers) — without it, digits of different widths cause visible jitter/misalignment.

## Motion floor

- Every non-trivial animation has a reduced-motion fallback — see `motion-physics.md`'s three-signal table. This is a floor requirement, not an enhancement to add if time allows.
- Layout-triggering CSS properties (`width`, `height`, `padding`, `margin`, `top`/`left` on non-`position: absolute` elements) should not be the animated property when a `transform`-based equivalent exists — animating layout properties forces repaint/reflow on every frame and is the most common cause of janky, dropped-frame "animations" that were meant to feel physical per `motion-physics.md`.

## Refused patterns (craft-floor specific, distinct from `anti-patterns.md`'s aesthetic tells)

These are refused because they actively harm usability, not because they're visually overused:

- Same-size icon + heading + body text cards repeated with no visual hierarchy between them (distinct from the icon-tile-stack *aesthetic* tell in `anti-patterns.md` — this is about the usability cost of zero hierarchy, not the look).
- Hard-offset "neobrutalist" shadows applied outside an actual neobrutalist direction — using the technique as a generic "modern" flourish rather than because the chosen direction calls for it.
- Monospace font used purely as a "this is technical/techy" costume on content that isn't code or data.
- Emoji used as functional icons (inconsistent rendering across platforms/OSes, no accessible label by default, breaks at a glance for screen reader users).
- Theme (light/dark) chosen by content category habit ("dashboards are dark now") instead of by asking who uses this, where, and under what light — see the Visitor Mode framing in `visitor-modes.md` for how to actually decide.

---

### Provenance
Adapted from pbakaus/impeccable's `craft-floor.md` reference (Apache-2.0) — the "quality gate beneath the bold direction" concept is impeccable's own framing, generalized here to not assume its specific brand tokens.
