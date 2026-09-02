# Motion Physics

Loaded from `SKILL.md` Step 3 (Motion). This is the engineering underneath "add a nice animation" — most AI-generated motion looks off not because the easing curve is ugly, but because it's *physically incoherent*: it doesn't start from where the element actually is, ignores the velocity a gesture handed it, and can't be interrupted. This file is about correctness, not taste; pair it with the Motion Tells in `anti-patterns.md` for the aesthetic side.

**Mobile API caveat**: `nectie-mobile/AGENTS.md` is explicit that Expo has changed fast — verify exact Reanimated/Expo/React Native API shapes against the versioned docs (`docs.expo.dev/versions/v57.0.0/`) before shipping, not against this file. The formulas below are physics and don't change; the exact prop names on `withSpring`/`AccessibilityInfo` etc. do, across library versions.

## The core idea

An interface feels alive when motion starts from the current on-screen value (not a reset-to-zero), inherits the user's velocity, projects momentum forward, and can be grabbed and reversed at any instant. Springs are what makes this possible — they're interruptible and velocity-aware in a way fixed-duration `@keyframes`/`withTiming` curves aren't. This serves four things a good interface owes the user: safety/predictability, understanding of cause and effect, a sense of achievement, and joy.

## Spring parameters

Two numbers, not the raw physics (mass/stiffness/damping) most animation libraries expose:

- **Damping**: `1.0` = critically damped, no bounce — the correct default for almost everything. `~0.8` = slight bounce, used *only* when the motion is inheriting real momentum (a flick, a drag release) — bounce as a default "playful" flourish, unconnected to any actual momentum, is a Motion Tell (see `anti-patterns.md` §6).
- **Response**: seconds to reach the target. This is not duration — springs don't have a fixed duration, response just sets how eagerly they approach the target.

Apple's own reference values:

| Interaction | Damping | Response |
|---|---|---|
| Move / reposition (e.g. drag a card back to rest) | 1.0 | 0.4 |
| Rotation | 0.8 | 0.4 |
| Drawer / sheet | 0.8 | 0.3 |

**Web — Framer Motion:**
```jsx
// Critically damped default: settling after a non-gesture state change
<motion.div animate={{ y: 0 }} transition={{ type: 'spring', bounce: 0, duration: 0.4 }} />

// Slight bounce: the motion is inheriting real momentum (drag released)
<motion.div animate={{ y: target }} transition={{ type: 'spring', bounce: 0.2, duration: 0.4 }} />
```
(Framer Motion's `bounce`/`duration` spring API is a direct reparameterization of damping/response — check the installed version's exact prop names before shipping, APIs move.)

**Mobile — Reanimated:**
```ts
import { withSpring } from 'react-native-reanimated';

// Critically damped default
translateY.value = withSpring(target, { dampingRatio: 1, duration: 400 });

// Slight bounce, momentum-driven (e.g. bottom sheet released mid-drag)
translateY.value = withSpring(target, { dampingRatio: 0.8, duration: 400 });
```
Reanimated's `dampingRatio` + `duration` config (as opposed to the older raw `damping`/`stiffness`/`mass` triple) is the one that maps directly onto this table — confirm it's available in the installed Reanimated version before relying on it, and fall back to the physical params if not.

## Interruptibility — the single most important rule here

Never animate from a reset starting value, and never let a second trigger cancel-and-restart from zero. Animate from the element's **current measured/interpolated position**, not its logical target or its rest state. In practice:

- **Web**: prefer Framer Motion (or any spring-driven library) over CSS `transition`/`@keyframes` for anything that can be interrupted mid-flight (a hover that can re-trigger, a drag, a toast that can be dismissed while animating in) — CSS transitions restart from the DOM's current computed value on interruption, which is usually fine for simple hovers but breaks down for anything gesture-driven, since there's no velocity carried across the interruption.
- **Mobile**: a Reanimated shared value already holds its current value continuously — re-calling `withSpring` on it mid-animation continues from wherever it actually is, which is the behavior you want. The mistake to avoid is re-mounting the component (which resets state) instead of re-driving the shared value.

## Velocity handoff (drag → spring seam)

When a gesture hands off to a spring (releasing a drag, a flick), convert absolute velocity into velocity *relative to the distance still to travel* — the formula Apple's WWDC sample code uses:

```
relativeVelocity = gestureVelocity / (targetValue - currentValue)
```
Worked example: element at y=50, target y=150 (100px to go), finger releases at 50px/s → relative velocity = 0.5.

**Reanimated** accepts velocity directly in the spring config:
```ts
translateY.value = withSpring(target, { dampingRatio: 0.8, duration: 400, velocity: gestureVelocityY });
```
**Framer Motion** spring transitions also accept an initial `velocity` — check the exact unit convention (absolute vs. relative) against the installed version before assuming it matches the formula above verbatim; the formula is the correct *model*, the API's exact expected unit is a detail to verify.

## Momentum projection

Where does a flung scroll/carousel/list actually come to rest? Apple's shipped function — note it explicitly is *not* the physics-textbook `v²/(2·decel)` formula:

```js
function project(initialVelocity, decelerationRate = 0.998) {
  return (initialVelocity / 1000) * decelerationRate / (1 - decelerationRate);
}
```
`decelerationRate` ≈ 0.998 for normal scroll-like deceleration, ≈ 0.99 for a snappier stop. Use this to decide a snap target (nearest carousel item, nearest sheet detent) from a release velocity, rather than always snapping to the nearest static breakpoint regardless of how fast the gesture was moving.

## Rubber-banding

For bounded drags — a sheet that resists past its fully-open position, a swipe-to-dismiss card past its threshold, a custom scroll edge:

```js
function rubberband(overshoot, dimension, constant = 0.55) {
  return (overshoot * dimension * constant) / (dimension + constant * Math.abs(overshoot));
}
```
`overshoot` is how far past the boundary the raw gesture wants to go; `dimension` is the size of the resistant zone. This is directly applicable to this repo's own `ProfileCalendarBottomSheet` and any future custom `BottomSheet`/drag-to-dismiss work — native `ScrollView` bounce gets this for free, hand-rolled drag components (Reanimated `useAnimatedGestureHandler`/`Gesture.Pan()`, or a web drag-to-close panel) need it computed explicitly or they'll feel like they hit a wall instead of resisting.

## Gesture design

- ~10px movement threshold before committing to a drag direction (prevents a slightly-shaky tap from being misread as a swipe).
- ~10px of hit-padding/hysteresis around small tap targets, beyond the visual bounds.
- Design every gesture-driven component's full state set: idle, dragging, released-with-momentum, released-at-rest, cancelled (e.g. a second finger, or the gesture recognizer failing) — not just the idle→dragging→settled happy path.

## Materials & depth (glassmorphism, done with actual hierarchy logic)

**Web** — `backdrop-filter`:
```css
.surface {
  backdrop-filter: blur(20px) saturate(180%);
  border-top: 1px solid rgb(255 255 255 / 0.3); /* catches light at the material's edge */
}
```
**Mobile** — `expo-blur` (not installed in `nectie-mobile` as of this writing — `npx expo install expo-blur` before using):
```tsx
import { BlurView } from 'expo-blur';
<BlurView intensity={40} tint="light" style={styles.surface} />
```
RN's native blur has no `saturate()` control — compensate with a slightly warmer tint color underneath rather than trying to replicate the exact CSS effect.

Rules that apply to both platforms:
- Never stack two translucent surfaces on top of each other — legibility collapses when material is layered on material.
- Bigger surface = thicker blur + deeper shadow (a full-screen sheet reads "heavier" than a small popover, and its material treatment should say so).
- Material communicates hierarchy (this floats above that), not decoration — if there's nothing beneath it worth obscuring/revealing, a translucent surface is the wrong tool; use a solid one.

## Multimodal feedback (mobile-relevant; N/A on web)

Three rules when combining haptics, sound, and motion: **Causality** (feedback only fires because of a real cause, never decoratively), **Harmony** (visual/haptic/sound fire on the same frame, not staggered), **Utility** (don't over-trigger — haptics on every scroll tick fatigues fast). `expo-haptics` is **not installed** in `nectie-mobile` as of this writing; install it (`npx expo install expo-haptics`) before adding haptic feedback rather than assuming the import resolves.

## Reduced motion — three independent signals, three independent fallbacks

Don't collapse these into one "is motion off?" check — they're different accessibility needs:

| Signal | Web | Mobile | Fallback |
|---|---|---|---|
| Reduce motion | `prefers-reduced-motion` media query | `AccessibilityInfo.isReduceMotionEnabled()` | Cross-fade instead of slide/spring/scale; kill parallax and auto-playing motion loops entirely |
| Reduce transparency | `prefers-reduced-transparency` | `AccessibilityInfo.isReduceTransparencyEnabled()` (iOS) | Raise opacity, drop blur radius |
| Increase contrast | `prefers-contrast: more` | check current `AccessibilityInfo` surface for the installed RN version — this API shifts | Near-solid background, clearly defined border instead of a soft shadow-only edge |

Also flag near-0.2Hz oscillating/looping animations (slow pulsing glows, breathing effects) as a vestibular-motion-sensitivity hazard independent of the reduced-motion setting — worth a second look even when reduced-motion is off.

## Typography mechanics (optical sizing, not font choice)

Font *choice* is in `anti-patterns.md` §1; this is what to do once a typeface is picked:

- **Tracking (letter-spacing)** is size-specific: negative at large display sizes (example: `-0.02em` on a hero headline), near-zero to slightly positive at small sizes. The floor from `craft-floor.md` is −0.04em — don't go tighter than that even on very large display type.
- **Leading (line-height)** is inversely related to size: tight on large headings (example: `1.05`–`1.1`), looser on body copy (`1.4`–`1.6`, and see the 65–75ch measure rule in `craft-floor.md`).
- Prefer `rem`/`em` for type-adjacent spacing over hardcoded `px` so the scale holds together if a base size ever changes (web: user font-size preference; mobile: Dynamic Type / system font scaling).

## Quick reference

| Need | Technique | Value |
|---|---|---|
| Settle after a state change (no gesture) | Spring, no bounce | damping 1.0, response 0.4 |
| Settle after a released drag/flick | Spring, slight bounce | damping 0.8, response 0.3–0.4 |
| Convert drag velocity to spring input | Relative velocity | `gestureVelocity / (target − current)` |
| Where does a fling land | Momentum projection | `(v/1000) × decel / (1 − decel)`, decel ≈ 0.998 |
| Resist past a drag boundary | Rubber-band | `(overshoot × dim × 0.55) / (dim + 0.55 × |overshoot|)` |
| Commit to a drag direction | Gesture hysteresis | ~10px threshold |
| Glass/translucent surface | Blur + light-catching edge | `blur(20px) saturate(180%)` + bright top border (web); `BlurView` (mobile) |
| Large display tracking | Negative, size-dependent | ~−0.02em at hero scale, floor −0.04em |
| Large heading leading | Tight | ~1.05–1.1 |
| Body leading | Loose | ~1.4–1.6 |
| Immediate feedback (tap, toggle) | Duration band | 100–150ms |
| Routine state change | Duration band | 150–300ms |
| Layout/overlay transition | Duration band | 300–500ms |
| Authored focal entrance | Duration band | 500–800ms |

Exits should generally be faster than entrances — leaving should feel quicker than arriving.

---

### Provenance
Adapted from emilkowalski/skills' `apple-design` (MIT), itself distilled from Apple's WWDC talks *Designing Fluid Interfaces* (2018), *The Details of UI Typography* (2020), and *Principles of Great Design* (2026). Mobile (Reanimated/Expo) mappings are new — apple-design covers web/CSS translations only, not React Native; verify them against `nectie-mobile`'s installed versions before relying on exact API shapes.
