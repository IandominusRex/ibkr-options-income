---
version: alpha
name: IBKR Income
description: A private options-income console for one operator who approves deterministic covered-call and cash-secured-put proposals, checked at a desk during US hours (Singapore night) and on a phone in daylight.
colors:
  primary: "#a6eb6e"
  primary-deep: "#8fdb55"
  on-primary: "#111410"
  on-primary-dark: "#0f110f"
  ground: "#f2f4ef"
  surface: "#ffffff"
  sunk: "#e6eadf"
  sunk-deep: "#d9ded3"
  ink: "#111410"
  ink-muted: "#575d55"
  control-edge: "#7a8276"
  hairline: "#dce0d7"
  perforation: "#c9cfc2"
  gain: "#187a42"
  loss: "#c8322f"
  flag: "#fff1d6"
  on-flag: "#6b4500"
  unknown: "#61685d"
  ground-dark: "#0f110f"
  surface-dark: "#191c19"
  sunk-dark: "#232723"
  sunk-deep-dark: "#2c312c"
  ink-dark: "#eef1eb"
  ink-muted-dark: "#a3aa9f"
  control-edge-dark: "#7d8579"
  hairline-dark: "#262a26"
  perforation-dark: "#3a4038"
  gain-dark: "#5bd58a"
  loss-dark: "#ff7468"
  flag-dark: "#3a2e12"
  on-flag-dark: "#f5cf7a"
  unknown-dark: "#8a9286"
typography:
  display:
    fontFamily: "Hanken Grotesk, system-ui, sans-serif"
    fontSize: 2.875rem
    fontWeight: 800
    lineHeight: 1.05
    letterSpacing: -0.025em
  headline:
    fontFamily: "Hanken Grotesk, system-ui, sans-serif"
    fontSize: 1.5rem
    fontWeight: 800
    lineHeight: 1.15
    letterSpacing: -0.015em
  title:
    fontFamily: "Hanken Grotesk, system-ui, sans-serif"
    fontSize: 1.0625rem
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: -0.01em
  body:
    fontFamily: "Hanken Grotesk, system-ui, sans-serif"
    fontSize: 0.875rem
    fontWeight: 400
    lineHeight: 1.5
  caption:
    fontFamily: "Hanken Grotesk, system-ui, sans-serif"
    fontSize: 0.8125rem
    fontWeight: 400
    lineHeight: 1.45
  control:
    fontFamily: "Hanken Grotesk, system-ui, sans-serif"
    fontSize: 0.84375rem
    fontWeight: 600
    lineHeight: 1.5
  label:
    fontFamily: "Hanken Grotesk, system-ui, sans-serif"
    fontSize: 0.75rem
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: 0.04em
  figure:
    fontFamily: "Red Hat Mono, ui-monospace, monospace"
    fontSize: 0.84375rem
    fontWeight: 500
    lineHeight: 1.45
    fontFeature: '"tnum" 1'
rounded:
  sm: 6px
  md: 12px
  lg: 18px
  sheet: 24px
  full: 999px
spacing:
  xxs: 2px
  xs: 4px
  sm: 8px
  md: 12px
  lg: 16px
  xl: 24px
  2xl: 32px
  3xl: 48px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
    typography: "{typography.title}"
    rounded: "{rounded.full}"
    padding: 11px 18px
  button-primary-hover:
    backgroundColor: "{colors.primary-deep}"
    textColor: "{colors.on-primary}"
  button-secondary:
    backgroundColor: "{colors.sunk}"
    textColor: "{colors.ink}"
    typography: "{typography.title}"
    rounded: "{rounded.full}"
    padding: 11px 18px
  button-secondary-hover:
    backgroundColor: "{colors.sunk-deep}"
    textColor: "{colors.ink}"
  button-quiet:
    textColor: "{colors.ink}"
    typography: "{typography.title}"
    rounded: "{rounded.full}"
    padding: 11px 18px
  button-quiet-hover:
    backgroundColor: "{colors.sunk}"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: 16px 18px
  disclosure:
    backgroundColor: "{colors.sunk}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: 10px 12px
  stub:
    textColor: "{colors.ink}"
    typography: "{typography.figure}"
  status-word:
    backgroundColor: "{colors.sunk}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: 1px 8px
  status-word-flag:
    backgroundColor: "{colors.flag}"
    textColor: "{colors.on-flag}"
  status-word-today:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
  strategy-switch:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.control}"
    rounded: "{rounded.full}"
    padding: 4px
  strategy-switch-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ground}"
  range-chip:
    textColor: "{colors.ink-muted}"
    typography: "{typography.label}"
    rounded: "{rounded.full}"
    padding: 4px 11px
  range-chip-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ground}"
  filter-chip:
    backgroundColor: "{colors.sunk}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.label}"
    rounded: "{rounded.full}"
    padding: 4px 11px
  filter-chip-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ground}"
  meter:
    backgroundColor: "{colors.sunk}"
    rounded: "{rounded.full}"
    height: 8px
  meter-fill:
    backgroundColor: "{colors.primary}"
  rail:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.body}"
    width: 200px
  tab-bar:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.label}"
    height: 64px
  sheet:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sheet}"
    padding: 24px
  bot-card:
    backgroundColor: "{colors.sunk}"
    textColor: "{colors.ink}"
    typography: "{typography.caption}"
    rounded: "{rounded.md}"
    padding: 10px
    halted-banner:
    backgroundColor: "{colors.flag}"
    textColor: "{colors.on-flag}"
    typography: "{typography.body}"
  field:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.md}"
    padding: 8px 12px
  calendar-day:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-muted}"
    typography: "{typography.label}"
    rounded: "{rounded.md}"
    height: 52px
  calendar-day-selected:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.ground}"
---
<!-- da-vinci schema=1 status=ratified updated=2026-10-19 -->
# Design System: IBKR Income

## Overview

**The payslip.** Options income is a wage your capital earns, so the console reads like one: every
proposed trade and every month ends in a short perforated stub (premium in, buybacks and
commissions out, net, and what that is a year). The account value still leads the home screen, as
in any brokerage app, but the payslip is what this console has that a brokerage app does not. It
shows the money the system is *earning*, line by line, in sums you can check by eye.

The mood is calm, plain and exact: sage-tinted paper, white cards, near-black ink, and one bright
lime that only ever means "act here". It borrows Robinhood's quiet hierarchy (one huge number, a
chart, rows without table chrome), Wise's transparent arithmetic and consequence-first sentences,
and Puthouse's trade-at-a-glance cards with the reasoning beside them. It refuses the casino
(confetti, celebratory flashes, streaks), the marketing page, the SaaS KPI-tile grid, crypto neon,
and pages crammed with everything at once.

Key characteristics: one bold number per region; everything secondary collapsed behind a
disclosure until asked for; math as a visible sum, never a bare percentage; words for states, not
colours; nothing animated except the thing you just touched.

## Colors

**Restrained.** Tinted neutrals carry the whole interface; lime is reserved for primary actions;
green, red and amber are reserved for meaning. Every light token has a `-dark` twin with the same
role.

- **Sage paper** (`ground` / `ground-dark`): the page itself. A green-grey tint, so white cards sit
  on it by lightness alone.
- **Card white** (`surface` / `surface-dark`): every card, the rail, the tab bar, sheets.
- **Pressed sage** (`sunk`, `sunk-deep` / `sunk-dark`): fills *inside* a card: the Why disclosure,
  secondary buttons, unselected chips, the meter track.
- **Ink** (`ink` / `ink-dark`): text, the hero chart line, the selected chip fill, the focus ring.
  **Muted ink** (`ink-muted` / `ink-muted-dark`) for labels and secondary lines (6.1:1 on paper,
  6.8:1 on white, 5.5:1 on pressed sage; 6.4:1 and up in dark).
- **Lime** (`primary`, hover `primary-deep`, label `on-primary`): primary buttons (Review, and the
  phone's proposals banner Open), the pending-count badge, the pay meter fill, and the one "Expires
  today" status. Nothing decorative: text selection is an ink fill, never lime.
- **Gain / Loss** (`gain`, `loss` and dark twins): signed money only, always paired with a `+`/`−`
  sign or the words "open P&L", never as the only signal.
- **Flag amber** (`flag` with `on-flag`): warnings that need attention without being a loss,
  such as "Assignment likely", a degraded data source, or a stale quote.
- **Unknown** (`unknown` / `unknown-dark`): the hatch texture behind "n/a". Unknown is never zero.
  As text the grey passes AA anywhere small "n/a" sits: 5.76:1 on white, 5.20:1 on paper and
  4.72:1 on pressed sage (dark: 5.35:1 on the card, 5.90:1 on the page, 4.72:1 on the pressed
  fill). Only the hover fill (`sunk-deep`) falls to AA-large (4.21:1 light, 4.13:1 dark), and a
  hover is transient. The hatch carries the state either way.
- **Control edge** (`control-edge`): input and checkbox borders (3.6:1 on paper, 4.0:1 on white).
  **Hairline** and **perforation** are decorative separators only and never the sole boundary of a
  control.

**The Lime Means Act Rule.** Lime appears only where tapping does something primary. A screen with
lime on two competing buttons has one too many.

**The Words First Rule.** No state is shown by colour alone: gain carries a sign, flags carry a
word, unknown carries texture and "n/a", selected carries an ink fill. This keeps the existing
`web/CLAUDE.md` honesty rule intact.

## Typography

**Hanken Grotesk** carries everything: display and headings at 800 (the hero number included, at
every size), titles at 700, UI and body at 400 to 600. Its default figures are tabular (verified: "1111"
and "0000" set at equal width), so money columns align without a second face. **Red Hat Mono** is
the stub voice: every perforated sum, the ledger, and fill prices, where the typewriter cadence says
"this is arithmetic".

Scale (fixed rem, ratio about 1.2, no fluid headings on these Operate surfaces): display 46px for
the hero number (38px on phones), headline 24px for page titles, title 17px for card titles and
buttons, body 14px, caption 13px for secondary lines (sub-lines under a row or a figure, the
"Account value" label, the pay pace line, the bot card), control 13.5px semibold for the strategy switcher and the theme toggle (four
segments at 17px do not fit a 390px phone), label 12px semibold with slight tracking for eyebrows,
chips and status words, figure 13.5px mono at 500. Prose (the Explain pages, Claude's review text, news explanations) keeps a 65 to
75 character measure; tables may run wider.

Replaces IBM Plex Sans and Mono, which `web/CLAUDE.md` currently names. That file changes with
the build.

## Layout

Desktop: a 200px rail on the left with Home, Trades, Portfolio, Activity, Research, News, More, and
the bot card pinned at its foot. From 1024px up, Home adds a 340px right column for "needs you" with "Done today" under it; below 1024px the first becomes a one-line proposals banner under the hero and the second moves to the foot of the page. Content max width is
1200px. Below 768px the rail disappears, and a bottom tab bar (Home, Trades, Portfolio, Activity,
More) takes its place. Everything is one column, in this order on Home: strategy switcher, hero,
proposals banner, October pay, positions, Done today.

Spacing runs on a 4px base (2, 4, 8, 12, 16, 24, 32, 48). Cards pad 16 to 18px; card stacks gap
16px; sections inside a page gap 24px. Touch targets are at least 44px on phones: compact pills
(the strategy switcher, range and filter chips, the theme toggle) keep their look and carry a
centred 44px hit area below 768px, with row gaps wide enough that wrapped rows never overlap, and
the range chips spread across the phone's width. The one exception is a stub line (24px, WCAG
2.5.8 AA): a 44px line would break the payslip's arithmetic rhythm. DENSITY 5: rows
are compact (about 11px vertical padding), but every card shows one idea, and anything secondary
sits behind a disclosure.

**The One Idea Per Card Rule.** A card answers one question (what am I earning this month, what
needs me, what do I hold). A second question gets a second card or a disclosure, never a cramped
second half.

## Elevation & Depth

Tonal layering only: paper ground, white surface, pressed-sage fills inside. No drop shadows on
cards, buttons or rows, and never a border plus a shadow on one element. A hairline separates rows
inside a card. The single exception is the review **sheet** and the confirm dialog, which rise over
a black scrim at 50% (light) or 60% (dark). The sheet carries one soft ambient shadow so it reads as
lifted off the page beneath: the `--shadow-sheet` token (`0 -8px 40px` black at 18% light, 50%
dark, where lightness does the lifting and the shadow only separates the sheet from the scrim).

## Shapes

Gently rounded throughout: 6px for status words, 12px for inner blocks (the Why disclosure,
inputs), 18px for cards, 24px for the top corners of sheets, fully round for buttons, chips, the
count badge and the meter. The recurring silhouette is the **perforation**: a 2px dashed rule that
opens every stub, the console's only ornament.

## Components

**Proposal card** (Trades and Home): eyebrow with the strategy in words (CASH-SECURED PUT, COVERED
CALL, CREDIT SPREAD), expiry and days left at the right, then a title ("AAPL · Sell $180 put"), then
one consequence-first sentence. Below it, the **Why this trade** disclosure (Claude's review,
collapsed by default, sitting *above* the stub; it carries For, Against and If challenged lines and
is labelled as Claude's view), then the stub, then Review (primary, opens the review sheet) and
Details (secondary, the full approval page). A roll's title names both legs
("NVDA · Roll $250 put Oct 23 → Oct 28", or "$250 → $245 put" when the strike moves), its
sentence says what it buys back and what it sells, and its stub sums Buy back, Sell and the
Net credit (or Net debit) at the quotes it was priced at, which the stub says, so a quote
never reads as a fill. A roll frozen before the 2026-10-11 redesign carries no legs and says
so. Approve and reject happen only inside the sheet,
behind the existing confirmation, so the card itself never decides anything in one tap. Review says
it opens a dialog (`aria-haspopup`). States: loading (a labelled block), empty ("Nothing needs you
right now."), error (a sentence that names the retry), pending, submitted (the receipt replaces the
buttons), decided (the decision line replaces them), and decided elsewhere or expired (a flag
sentence in the review sheet, from the approval's own status, which the open sheet polls). There is
no "stale data" state: the API carries no stale signal for a proposal, and its premium is the
frozen scan quote, which the card never presents as a live price.

**Stub**: the perforation, then two to four `figure` lines, then a total line with a hairline above.
Each line is a button (at least 24px tall) that toggles a one-sentence explanation beneath it. Unknown inputs render
"n/a" with hatch; a total built on an unknown says so in words instead of summing.

**October pay card** (Home): collapsible. Closed, it shows the title (never wrapped; on a narrow
phone the whole figure drops below the title, and "of $target" never splits from its amount), net so far against target, the lime
meter, and "71% of target · 18 days left". Open, it shows the month's stub. The target is set on
More (see the **Income target card**): a fixed amount, a percent of the month-start account value,
or a percent of an amount the operator names. With no target it says "No target set" and links to
More ("Set a target in More", below the disclosure, because a link inside the disclosure's button
would nest interactive elements); a percent of the account with no month-start value (the first
month after install, a journal gap) says "Target n/a · needs the month's opening account value"
(hatched n/a); either way the meter is hatched. An unknown progress reads "n/a of target" (hatched
n/a). One day left reads "1 day left". When the spreads book cannot be read, a flag word "Spreads
unavailable" and a sentence say so: a spreads-only month shows n/a, never $0, keeps its target and
reads "n/a of target", and an all-strategies month says its total leaves spreads out.

**Strategy switcher**: a segmented control on a white pill track, one button per kind of trade:
All, CSPs, CCs, Credit spreads, each with its live count. It sits at the very top of Home and
Trades. The selected button takes an ink fill (never lime or green) and `aria-pressed`. It scopes
everything below the hero: proposals, October pay (that strategy's premium and stub), and
positions. The account-value hero stays account-wide, because account value cannot be split by
strategy honestly. The choice is kept in the URL (`?strategy=csp`), so a link or reload keeps it.
On Trades it also picks which views exist: the wheel (All, CSPs, CCs) gets Proposals, History and
Assessed; Credit spreads gets Spreads only, so the view chips are hidden there.
The Positions card carries the same tabs as smaller chips, plus Shares.

**Account hero** (Home): "Account value", the number (display, 38px on phones, 46px from 768px),
then today's signed change in words ("+$1,234.50 (0.50%) today"; a genuine zero is neutral ink; an
unknown change reads "n/a today · last value <date>", hatched n/a), then the line chart (ink, no
fill, never animated in) and the range chips, with a **calendar button** at the end of the chip row (it opens the realised P&L calendar). The chart library's licence link is the Credits card on More, and its own logo is off so nothing sits on the line. The chart scrubs by pointer and, as a slider, by
keyboard (arrows, Home, End); the number follows the scrub. Loading is a hero-shaped skeleton.
In market hours (09:30-16:00 New York time, weekdays) a headline older than 30 minutes, the
positions card's rule, shows the flag word "Delayed" and its age beside "Account value"; a last
close after 16:00 or at a weekend is the right headline and is never flagged.

**Positions card** (Home): the title, "Sorted by expiry", a search field (the **Search field**), filter chips (All, CSPs, CCs, Credit spreads, Shares, each with its count, which follows the search), then position rows. A delayed portfolio snapshot shows a
flag word "Delayed" and its age; an unreadable spreads book is said in words ("Credit spreads are
unavailable right now."), never shown as "none open".

**Position row**: the whole row is a link to the position's page (a muted chevron at its right edge says so). Ticker and contract bold, then a status word, then a muted sub-line (expiry,
coverage, % of premium kept); value right-aligned with its label beneath ("sold for", "open P&L").
Status words: Expires today (lime); Assignment likely and In the money (flag); At the money and
Out of the money (sunk). They come only from fields the API returns (expiry, assignment risk,
moneyness). A position with none of those known shows no status word rather than a guessed one.

**Roll card** (Position page, a held short option only): "Roll", then each alert the monitor
fired on this contract (the trigger as a flag word, its age, the detail, and Claude's stored
view labelled "Claude's view"), or "No roll alert has fired on this contract."; one sentence
("Proposing a roll prices one now and raises it for your approval. Nothing trades until you
approve it."); then **Propose a roll** (secondary, never lime), which opens the existing
confirmation; the command receipt follows, and "No qualifying roll" is a plain answer, not an
error. Home's position rows carry a flag word **Roll alert** when an alert has fired on that
contract.

**Needs you** (Home, from 1024px): a right column of proposal cards under "Needs you · N
proposals". Below 1024px it becomes the **proposals banner**: one card, "2 proposals need you",
the first names, and a lime Open that goes to Trades.

**Review sheet**: a bottom sheet on phones, a right-side sheet on desktop, portaled to the page so
a resize across a breakpoint never hides it. One step at a time:
(1) the trade, its stub and Why, with Approve; (2) the existing confirmation (exact contract and
count); (3) in live mode only, the separate LIVE confirmation. Then the command receipt in place.
Focus is trapped, Escape closes, and focus returns to the trigger; when the focused control leaves
the page (a confirmed decision disables Approve), focus goes back to the sheet, which shows an
inset ink ring only to keyboard users. **Exception (2026-10-14):** Approve, Reject and both
confirmations are the existing protected safety components (`DecideControls`, `ConfirmAction`),
which keep their legacy bordered `rounded-sm` buttons, so Approve in the sheet is not lime and not
round. Restyling them is a separate, reviewed change to safety files; until then the sheet's own
type and spacing frame them.

**Bot card** (rail foot; on phones, on More): running or halted in words ("Bot running · paper",
"Wheel halted · paper"), mode (paper or live), the autonomy rung, and a flag line when the trading
service is not draining commands; a labelled loading block holds its place. It opens the Bot sheet
(`aria-haspopup`): Halt is one tap; Resume needs the typed word RESUME; rung changes confirm first;
the not-draining warning sits above the controls. The same exception as the review sheet applies:
`HaltControl`, `AutonomyControl` and `RollModeControl` (Auto-execute or Propose only; a native select like the rung's, confirmed only when moving to Auto-execute) keep their legacy bordered Halt and native selects. Halted
state also shows a full-width flag banner on every page, worded for the wheel ("Wheel trading is
halted"), since credit spreads have their own halt.

**Rail and tab bar**: the 200px white rail lists the seven destinations with an ink-on-sage
current row and the lime pending count on Trades; the phone tab bar (64px, white, hairline above)
holds Home, Trades, Portfolio, Activity and More, and marks More current on Research, Universe,
stock and News pages, which a phone reaches through More.

**More**: the bot card, the theme toggle (Light, Dark, Follow OS, on the strategy-switch track), the income target card, links to Research, Universe, News, Ledger, How it works, What Claude knows and statement import, system status, and Credits (the chart library's licence link).

**Regime and limits card** (What Claude knows): "Regime and limits", with when it was recorded at the right of the title. Per index (SPY, QQQ) a heading, the regime as a status word (flag amber above normal, neutral at normal), one plain line (the daily base, what raised it today, a bottoming-signal ease, or "Matches the daily base") and the CSP limits as figure lines under a perforation: Budget and Per trade as a percent of the normal limit, New puts a day ("No limit" or the count), Guaranteed lots a day. Up to three flag lines come first when they apply, each a flag word with one sentence beside it, in this order: "Off in config", "Suspended today" (`/regime off`, the limits shown are not applied) and "Cuts paused today" (today's circuit breaker has tripped: "The circuit breaker tripped, so Claude's size cuts are recorded but not applied until tomorrow"). Below the indices, the leveraged-ETF ceilings grouped by multiple ("3x (TQQQ, SOXL): 60% of the regime's size when calm, 30% when the name or its market is under stress") and Claude's size cuts as a sentence ("applied (paper)", "recorded only (live)"). When today's circuit breaker has tripped (Claude zeroed most of the day's auto puts) the cut sentence says so itself ("applied (paper), paused today.") so it is true when read alone, and the flag line above carries the state. The breaker is a flag word, not a plain sentence: it is the one state on the card besides `/regime off` that changes what happens today, so it joins that stack, in the first screen at phone width, instead of sitting below both indices. What the limits mean sits in a closed plain Disclosure. No regime yet: "No regime recorded yet" with a hatched n/a.

**Picture card** (What Claude knows): the stories first, each a bold title, "since Oct 12", and, when Claude wrote one, a "Claude's description" line and its evidence ids in the figure face; a stale picture says so above them in a flag line with the time and says to treat the stories as out of date. The numbers (figure lines numbered F1, F2 to match the evidence ids), SPY's seasonality (with a neutral "Weak signal" word) and the coming events sit in a closed plain Disclosure. The card's header says when it was rebuilt, in New York time; the other cards put their own time or window ("Recorded", "Last 7 days", a count) in the same place.

**Call row** (What Claude knows): the call's name in bold and its blocks as a wrapping row of neutral status-word chips. The chips are not controls: they are list items, with no hover state and no pointer.

**Dropped row** (What Claude knows): the story's headline, a muted line "Claude's reason: ..." with the judgement time, and for a story the market promoted afterwards a flag word "Promoted" with "The market moved +1.2% after it." The first five show; "Show all N" reveals the rest. A line says how many stories nobody reviewed.

**Name row** (What Claude knows): ticker bold, then words (Held; Stock, ETF or Leveraged ETF; Health with its first reason on the next line, flag amber for weak, "Health" with a hatched n/a when a stock's fundamentals could not be read, and no health word at all for a fund, which has none), then an inline "Claude's story" label ahead of the story and its evidence ids (or a hatched n/a and "No story right now."), a small label "Reported in news (not computed by the system)" above a short list of figures Claude quoted from the cited news (at most three, one per line with a gap between them, each ending in "Evidence: C8123" in the figure face on one unbroken run; the list is a labelled `ul`), shown only when there are some and never inside the story's own line, an inline "Upcoming" label ahead of each verified date and title, and a muted line "Notes rebuilt 1:00 PM ET" or, when the last rebuild failed, a flag word "Stale" with the time of the notes. A plain Disclosure ("Profile and numbers") holds "Claude's summary, general knowledge" and the numbered facts.

**Disclosure**: a summary row with a round chevron chip that rotates 180°, `aria-expanded` on a
real button, focus ring in ink. The whole pressed-sage block is the button (at least 44px tall);
the panel appears in place beneath it.

**Buttons**: primary lime, secondary pressed sage, quiet (no fill, sage on hover, e.g. the sheet's
44px Close), all fully round, 17px title type. Hover deepens one step;
focus-visible draws a 2px ink ring at 3px offset; pressed scales to 0.98 when motion is allowed;
disabled drops to muted ink on sunk with no lime; loading keeps the label and adds "…" (no spinner when the wait is a
command poll, since the receipt already states progress).

**Range chips** (1D 1W 1M 3M YTD All): selected is an ink fill, never lime or green, so selected
never reads as "up".

**Status word**: label type on a 6px-rounded fill: neutral (muted on sage), flag (amber), today
(lime, "Expires today" only).

**Trade card** (Home, "Done today", and the Position page): a proposal card's anatomy for a trade that
has happened. Eyebrow in words (OPENED, CLOSED or ROLLED, then the kind of trade) with the fill's
clock time (New York) or, on the Position page, its date; a title ("AAPL · Sold $180 put",
"KO · Bought back $68 put", "NVDA · Rolled $160 call to $165"); one sentence (an opened trade: what
you collected and the consequence; a closed or rolled one: the reason); the reasoning collapsed
above the stub (an opened trade: Claude's review, labelled; a close or roll: "Why it closed" or
"Why it was rolled", "the system's rules", plus "and Claude's view" when a line is Claude's, which
carries Claude's name in its label); then the stub, which sums the whole trade (opened: Premium,
Commission, On $X held, A year; closed: Premium collected, Bought back, Commissions, Net P&L, with
"Net on this leg" for a roll). An opened or rolled card says who approved it under its sentence
("Approved by the system", "Approved by you, on the web", "Approved by you, in Telegram"), from
the stored record only; a card whose decider was not recorded says nothing rather than guess.
Details (secondary) links to the approval when there is one. No
lime: nothing on it decides anything. The filter pills above the stack are filter chips.

**In-flight order row** (Trades, History, today only): the ticker and the contract bold, then a
state word (Queued, Submitted; Partial is the one flag word), then one line in the figure face:
the limit price, the filled count, the time it was sent (New York) and paper or live, with n/a
hatched where a price is unknown. The humanised detail sits beneath when there is one. A row with
an approval is a link to it (a muted chevron says so). Under the list, one sentence says a working
order is cancelled in IBKR for now, because the web cannot cancel one until Part 5 (Order control).
No lime, no button.

**Not-traded row** (Trades, History): the Position row's anatomy. The whole row opens the approval's
detail page. Title in bold with the outcome as a status word (Expired, Rejected, Order cancelled,
Order rejected), then a muted line saying who decided and when it was raised ("Approved by the
system · raised 2:39 AM ET", "Rejected by you, in Telegram · raised 2:39 AM ET", "Expired
unanswered"), from the stored record only; the premium is right-aligned with its label beneath, or
a roll's net labelled "net, as priced".

**History** (Trades): one New York day. The day line ("Mon, Oct 19 · today") with previous and next
(the nearest day with wheel activity, 44px) and Today when the day is not today; then In flight
(today only: the cards you approved in this browser, with their receipts, then the working
orders), Traded (Home's trade cards, two columns from 1024px; this section says so when the
day had none) and Not traded, in that order. A section with nothing in it is left out, except
Traded. Under All, one line sends credit spreads to their switcher.

**Spreads books** (Trades, Credit spreads): the day's spreads as rows grouped by book, each in its
own card: the paper book first, the baseline book (simulated, always the deterministic pick) beside
it from 1024px, then the shadow book when it has rows. A row is "SPY 763/758 put spread", a status
word, the contracts and credit, and the credit taken or the P&L realised at the right; only a
paper spread links to its position page. A paper spread carries **The menu Claude saw**, collapsed
(a Disclosure): the outcome sentence, "Claude's view:" with Claude's reason, then the lettered menu
under a perforation, each row a letter, the strikes, Baseline, Claude's pick and what became of the
chosen item as words (Sent only when the spread filled; otherwise "Chosen, did not trade" with the
stored reason, or "Chosen, no result recorded yet"), and its figures in the stub face. **Other picks** follow as short cards (a skip, a fallback with
nothing sent, a send refusal, a pick whose spread is not on record), each with its menu collapsed.
A menu that no longer parses says "This menu could not be read." beside a small hatched mark, never
with the hatch drawn over the sentence. No lime.

**Assessed card** (Trades, Assessed): one card per symbol. The symbol, its stage counts in words
("score floor: 1 · risk gate: 2", never colour alone) and a chevron open the contracts; each row is
a stage word (Gate rejected is the one flag word), the contract, the reasons in plain sentences
and the score and premium in the figure face. **Promote** is secondary, and only on a row the
system says can be promoted; a row that cannot says why in a sentence instead of a disabled
button. Two labelled filters (Stage, Symbol) sit above the cards.

**Realised calendar** (Home chart, a sheet): each day's realised P&L for a month, as a labelled
table (Mon to Sun), a month total ("Realised in October"), previous and next month (44px). A day
with closes is a `calendar-day` button (no fill at rest, because gain and loss at 12px need white
under them to clear 4.5:1; a ring on hover; an ink fill when selected) showing the day and a
signed figure without the currency sign, which the month total carries ("+413", "−231", "+1.7K", "+12K"; the gain and loss colours never carry it alone); a day
nothing closed is plain text, never "$0". A tapped day lists what closed with each reason and its
result. A footnote says it is options and credit spreads after commissions, that share sales are
not included, and that a blank day is not a flat one.

**Search field** (Positions card): a `field` with a magnifier, a screen-reader label (never the
placeholder alone), 16px text so iOS does not zoom, and a Clear button once it has text. Commas
ask for several names; the chips' counts say what each would show with the search applied.

**Field** (More's income target, the search): white `surface` with a `control-edge` border (an
error draws it in loss), 12px radius, the label above, the error below in words, an ink focus ring
on the wrapper when the input has keyboard focus.

**Income target card** (More): "Monthly income target": none, a fixed amount, a percent of the
account, or a percent of an amount you name (chips); the fields of the chosen mode with a
plain-English line saying what it means this month ("2% of $100,000 is $2,000 a month."); Save
(primary lime: it is the card's one action), disabled until the draft differs from what is stored;
the command receipt beneath. It says where a config value comes from. Display only: nothing here
reaches an order, so no confirmation step.

**Meter**: an 8px sage track with a lime fill; unknown is the hatched track with no fill, never 0%.

## Do's and Don'ts

- Do end every trade and every income figure in a stub or a sentence; never a bare percentage.
- Do collapse secondary detail (Claude's review, the month's breakdown, alternatives) behind a
  disclosure, closed by default.
- Do write consequences in plain English: "If AAPL closes under $180 on Nov 21, you buy 100 shares
  at $180."
- Do render unknown values as "n/a" with hatch, never "$0" or "0%".
- Don't use lime for anything that is not a primary action, the pay meter, the count badge or
  "Expires today".
- Don't celebrate: no confetti, flashes, streaks or sounds on fills.
- Don't animate chart data in, and don't use a shadow anywhere except the sheet and dialog.
- Don't put an em dash in UI copy, and don't use "seamless", "robust", "unlock" or "elevate".
- Don't let Claude's text look like a decision: it is always labelled as Claude's view and never
  sits on a button.
- Approved exceptions to da-vinci tells: none.

## Motion

MOTION 2. Only touched things move: disclosures (the chevron rotates 180ms ease-out; the panel
appears in place, with no height animation),
sheets (slide in 240ms ease-out; they close immediately for now, see Open Decisions), button press
(scale 0.98, 90ms). Exits are faster than entrances. Charts never animate their data in; scrubbing updates the hero number instantly. Under
`prefers-reduced-motion` every transition is removed, the press scale is dropped, and sheets appear
in place.

## Brief

A private web console for a semi-autonomous options-income system on Interactive Brokers. Python
scans, scores and gates covered calls and cash-secured puts deterministically; a separate process
trades daily SPY credit spreads. Claude reviews proposals but can never place, size or gate an order.
The web proposes intents (approve, promote, roll, halt) that the trading service drains; it never
trades directly.

**Mechanism:** a deterministic Rules Engine proposes each trade and you approve it, so the screen
has to show why the gate let it through and exactly what happened after you approved, not sell the
trade.

**Users and scene:** one operator in Singapore. At a desk during US market hours (21:30 to 04:00
SGT), in long sessions in a dim room. On a phone in daylight for quick checks and approvals. Often
tired at night, so states must be unambiguous and the destructive or irreversible paths deliberate.

| Setting | Value |
|---|---|
| Platform | web (responsive: desktop rail, phone tab bar) |
| Stack | Next.js 15 App Router, React 19, Tailwind CSS v4, react-query, cmdk, lightweight-charts, recharts |
| Design system | none (own components on Tailwind v4 tokens; lucide-react icons) |
| Dials | VARIANCE 3, MOTION 2, DENSITY 5 |
| Theme | both: light default, dark toggle, and a "follow OS" option |
| Accessibility | WCAG 2.2 AA; 44px touch targets on phone; no state by colour alone |

**Evidence on hand:** real account, position, P&L, ledger, approval and news data through the API.
No logo, favicon or brand assets yet. Must not fabricate: prices, fills, targets, probabilities or
any figure the API does not return; mockups label their data synthetic.

**Brand commitments:** the product name in the shell is "IBKR Income" (inferred). Lime on primary
actions is the user's explicit choice.

**Must remain untouched:** the honesty rules (n/a with hatch, never colour alone, receipts never
overstate, charts never animate in); the safety friction (confirm before any order intent, one-tap
halt, typed RESUME, the second LIVE confirmation); stable URLs (`/options/[id]`, `/stock/[symbol]`,
`/ledger/...` keep working or redirect); copy rules (no em dashes, the banned words).

## Inspirations

- **Robinhood.** Take: one huge number over a scrubbable chart with range chips; quiet list rows
  without table chrome; a focused review step before an order. Leave: true-black canvas, neon
  green, Capsule Sans, celebratory motion.
- **Wise.** Take: transparent line-by-line math; consequence-first plain English; one bright accent
  on chunky round buttons; one decision per step. Leave: the marketing-scale 900-weight display
  type and its exact lime.
- **Puthouse.** Take: each proposed trade as a card judged at a glance; income progress as the
  headline goal; the AI's reason beside the trade; a clearly visible bot state. Leave: any claim of
  autonomy the system does not have.
- **Anti-references:** casino or gamified brokerage; marketing-page layouts; generic SaaS KPI-tile
  grids; crypto neon, glow and glassmorphism; cluttered pages that show everything at once.

## Surfaces

### Home
Operate. Dials as the project default.
- **THESIS:** the account as a payslip: value on top, this month's earnings as a stub, then what
  you hold. Refuses the brokerage home where account value is the only number.
- **OWN-WORLD:** sage paper, white cards, ink hero line, perforated stubs, lime only on Review (and
  the phone banner's Open), the pay meter, the pending count and "Expires today".
- **STORY:** you see what the account is worth, whether this month's income is on pace, what needs
  you, and which positions need watching, in that order of glance.
- **FIRST VIEWPORT:** desktop: the strategy switcher (All, CSPs, CCs, Credit spreads) across the
  very top; hero number, delta and 1M chart with range chips top-left; collapsed
  October pay card below it; positions card below that; the "Needs you" column of proposal cards on the right with "Done today" under it. Phone: strategy switcher, hero, chart, one-line proposals banner, October pay,
  positions, Done today.
- **FORM:** the payslip, candidate 1 of 7 (Claude's pick), roll seed 1090290943, revised by the
  user: Why collapsible above the stub, pay card collapsible, positions beneath it.
- **FINISH:** unreviewed and undocumented is unfinished.

### Position
Operate. Dials as the project default. Added 2026-10-15 at the operator's request: pressing a
Positions row opens the contract itself. The composition is the operator's (chart on top, the
news directly under it), so da-vinci's structure workshop was skipped: pinned beats roll.
- **THESIS:** a position is the trade it began as. The underlying's chart leads, with your strike
  drawn across it; the initial trade is summed in a stub; the headlines sit under the chart.
  Refuses the greeks table: what you were paid, what it is worth now and what the stock is doing
  are the three things this page answers.
- **OWN-WORLD:** the payslip. Sage paper, an ink chart line with a dashed strike line (the
  perforation, as a rule across the chart), white cards, a stub that sums the initial trade. No
  lime. Its one action, Propose a roll on a held short option, is secondary: it raises a roll for
  approval and never trades.
- **STORY:** where the stock is against your strike, what you were paid and what that is as a
  return, what the position is doing now, and what the news says, in that order of glance.
- **FIRST VIEWPORT:** desktop: back link, the contract as a title with its status words, then two
  columns: the chart with its range chips (1M, 3M, 6M, 1Y) and the headlines directly beneath it
  on the left; the initial trade card (the Why disclosure, the stub) and the "Now" card in a
  340px column on the right. Phone: title, chart, the trade, now, headlines (the trade is worth
  more than the news on a small screen, so it comes before it).
- **FORM:** one grid placed by CSS so the DOM order is the phone order: chart, trade, headlines.
  Mirrors Home's two columns (content left, a 340px column right).
- **FINISH:** unreviewed and undocumented is unfinished.

### Trades
Operate. Dials as the project default. Built in web overhaul Part 2
(docs/superpowers/plans/2026-10-19-web-overhaul-2-trades.md).
- **THESIS:** what the wheel did and why, a day at a time, and the few things that wait on you.
  The account runs on full autonomy, so the page leads with what happened, not with an empty
  queue. Refuses the order-management grid: a proposal is a card you judge, a trade is the card
  Home shows, an order or a passed-over proposal is a sentence with a state word, and a spreads
  menu is the menu Claude saw, kept as the reason under the spread it opened.
- **OWN-WORLD:** the payslip. Proposal and trade cards exactly as on Home (lime only on Review);
  in-flight orders and not-traded proposals as rows without table chrome; who approved a trade
  in words ("Approved by the system"), from the record only; the spreads menu as a lettered list
  under a perforation, its figures in the stub face. Nothing on History or Spreads is an action
  apart from the unchanged decide flow inside a sent card's receipt.
- **STORY:** what needs me (Proposals), what the wheel did today or on any day (History: in
  flight, traded, not traded), what the scan passed over and why (Assessed), and, under Credit
  spreads, what each book traded and the menu behind it (Spreads).
- **FIRST VIEWPORT:** the title, the strategy switcher (All, CSPs, CCs, Credit spreads, with
  pending counts), the view chips (Proposals, History, Assessed; Proposals carries the pending
  count, History the in-flight count), a flag line when the trading service is not draining
  commands, then the view. With no view in the URL the page opens on Proposals when something
  waits on you and on History otherwise, decided once per visit. Proposals: ticker chips (from
  two tickers up), then proposal cards, one column below 1024px and two from 1024px. History: the
  day with previous, next and Today, then In flight (today only), Traded, Not traded. Credit
  spreads has one view, so its chips are hidden and Spreads shows.
- **FORM:** one page; the view and the day live in the URL (`?view=history&day=2026-10-09`)
  beside the strategy (`?strategy=csp`), so a link or a reload keeps all three. Review opens the
  review sheet exactly as on Home; approving moves the card to History's In flight at once, and
  a failed command hands it back.
- **FINISH:** unreviewed and undocumented is unfinished.

### Portfolio
Operate. Positions, Campaigns, Expiry calendar. Position rows as on Home; "Propose a roll" moves
onto the short-option rows.

### Activity
Operate. Pay (P&L summary and equity curve), Ledger, Fills and orders, System (score-vs-outcome).
Ledger and stubs use the figure face.

### Research
Read. Search, watchlist, sectors, the stock page, and Universe. VARIANCE 3, DENSITY 6.

### News
Read. Feed and calendar; ticker briefs.

### More
Read and Operate. How it works (the System Explanation pages), What Claude knows (a link to its own surface), Bot controls, Theme, the monthly income target, Ledger import, Credits.

### What Claude knows
Read. Dials as the project default; the only thing that moves is a disclosure. Added 2026-10-22 for
the market picture build (docs/superpowers/plans/2026-10-20-market-picture.md, Task 22), reached from
a row on More at `/more/claude`. The composition is the operator's: the spec (section 11) pinned
"mockup option A" (the picture and the limits on top, one tile per Claude call, the dropped stories,
then the names), so da-vinci's structure workshop was skipped: pinned beats roll.
- **THESIS:** Claude is only as good as what it is shown, so show the operator exactly that. The
  page answers, in order: what does the system think the market is and what does that do to new
  puts; what is the picture Claude reads; which Claude call reads which blocks; what did Claude
  throw away; what is on file about each name. Refuses a settings-page look, a tile grid and every
  control: it shows, and nothing on it changes a limit, a size or an order.
- **OWN-WORLD:** the payslip, read as a reference sheet. Sage paper, white cards, one idea per card;
  Python's numbers in the stub face (figure lines under a perforation); regimes and states as words
  (a regime is a status word, flag amber for anything above normal); every piece of Claude's prose
  carries a label that says it is Claude's ("Claude's description", "Claude's reason", "Claude's
  story", "Claude's summary, general knowledge"), and a figure Claude quoted from the news carries
  the label "Reported in news (not computed by the system)" and sits apart from the story, which
  holds only the system's numbers; none of it sits on a button; a story Claude has not
  written, a health label that could not be worked out and a missing number are hatched `n/a`, never blank
  and never zero (only the "n/a" token is hatched, never the words around it). No lime: there is
  nothing here to act on.
- **STORY:** the regime and the limits it puts on new puts, with whether they are suspended today;
  the picture (stories first, the numbers behind them closed); the seven Claude calls and the
  blocks each reads; the stories dropped as noise, with Claude's reason and any the market later
  promoted; then one row per name.
- **FIRST VIEWPORT:** a back link to More, the title and a one-sentence dek, then the Regime and
  limits card: the flag lines that apply first (off in config, suspended today, cuts paused today),
  then SPY and QQQ as status words with a plain line each (base, raised today, eased) and each
  index's CSP limits as figure lines (budget, per trade, new puts a day, guaranteed lots), then the leveraged-ETF
  ceilings and Claude's cut mode as sentences (the cut sentence adds "paused today" when the circuit
  breaker has tripped). One column up to 720px wide at every size; two limit blocks side by side from 640px.
- **FORM:** one column in this DOM order on every viewport: Regime and limits, Market picture, What
  each call reads (a row per call, its blocks as non-interactive status-word chips, not a tile
  grid), Dropped as noise (the first five rows, the rest on request), Names (a row per name: ticker,
  words, Claude's story, the figures quoted from the news under their own label when there are
  any, upcoming dates, with the profile and the numbers behind a plain disclosure). Data arrives from one request, `GET /claude/context`; the page is read-only.
  Degrades by section: no news service says so in a sentence and the regime still shows; no regime
  says "No regime recorded yet" with a hatched n/a; a failed request is a sentence naming the retry.
- **FINISH:** unreviewed and undocumented is unfinished.

## Agent Prompt Guide

Quick reference: paper `#f2f4ef` with white `#ffffff` cards, ink `#111410`, muted `#575d55`, lime
`#a6eb6e` for primary actions only, gain `#187a42`, loss `#c8322f`, flag `#fff1d6`/`#6b4500`; dark twins
end in `-dark`. Hanken Grotesk (800 headings, tabular by default) and Red Hat Mono for stubs. Tonal
elevation, no shadows except the sheet; 18px cards, round buttons; dashed perforation opens every
stub.

- "Build the Trades proposals list per web/DESIGN.md: Operate, payslip world, proposal cards with
  the Why disclosure above the stub, lime only on Review."
- "Restyle the Ledger table per web/DESIGN.md: Red Hat Mono figures, hairline rows, n/a with hatch
  for unknowns, no table borders."

Iteration: change one component at a time and name it by its `components:` key; add variants as
sibling keys; re-run the check after edits.

## Open Decisions

- **Monthly income target: RESOLVED 2026-10-15.** The operator sets it on More (none, a fixed amount, a percent of the account, or a percent of an amount); `web.monthly_income_target_pct` remains the fallback. The meter reads "No target set" until one is set.
- **Product name in the shell:** "IBKR Income" is inferred; confirm or rename.
- **Logo and favicon:** none exist; a wordmark set in Hanken Grotesk 800 is the interim.
- **Icons:** lucide-react, as built; confirm.
- **Sheet exit:** a 180ms slide out. The sheet closes immediately today because the review sheet
  unmounts with its approval; adding the exit means keeping the approval through it.
- **The decide controls' look:** a lime, round primary Approve (and round Reject, Halt and dialog
  buttons) needs a reviewed restyle of the protected `DecideControls`, `ConfirmAction`,
  `HaltControl` and `AutonomyControl`.
- **A disabled quiet button (proposed 2026-10-19):** the Buttons rule drops every disabled button to
  muted ink on sunk, so a quiet button that cannot be pressed (History's and Spreads' day arrows at
  the end of the range) shows a filled circle while the live one is bare, which reads backwards.
  Proposed: a disabled quiet button stays transparent and only dims. It changes a shared
  component's rule, so it waits for the operator.
- **The unknown grey: RESOLVED 2026-10-14.** The light `unknown` is now `#61685d` (4.72:1 on
  pressed sage, 5.20:1 on paper, 5.76:1 on white), so small "n/a" passes AA anywhere, including the
  legacy pages that Parts 2-4 have yet to restyle.

## Decision Log

- 2026-10-22 (later still): **What Claude knows**, Regime and limits card: today's circuit breaker is
  now an amber flag word, "Cuts paused today", with "The circuit breaker tripped, so Claude's size
  cuts are recorded but not applied until tomorrow" beside it, replacing the plain sentence added
  earlier today (operator decision in the open-items walk-through, plan Task 23 Step 0c; the
  earlier entry's "if it proves easy to miss, a flag word is the next step" is taken). It reuses
  `StatusWord` in the flag tone, as "Suspended today" does; no new component, colour, font, radius,
  elevation or token. The critique first placed it where the sentence was, after the cut-mode line;
  rendered at 390px that put it about a screen below the fold, under both index blocks, while
  "Suspended today" is in the first screen. So it joins the flag stack at the top (order: Off in
  config, Suspended today, Cuts paused today) and the cut-mode sentence gains ", paused today" when
  the breaker has tripped, so the standing line never says "applied" on its own while the pill says
  otherwise. Contrast measured: flag word 7.59:1 light (`#6b4500` on `#fff1d6`) and 8.92:1 dark
  (`#f5cf7a` on `#3a2e12`), the sentence 15.08:1 on the dark card; no horizontal scroll at 390.
- 2026-10-22 (later): **What Claude knows** gained two things, both from the operator's open-items
  walk-through (docs/superpowers/plans/2026-10-20-market-picture.md, Task 23 Step 0b). (1) The
  Regime and limits card says "Cuts paused today: the circuit breaker tripped." after the cut-mode
  sentence when today's breaker has tripped (`claude_cut_breaker_tripped_today`, read from the
  sender's day state). The operator asked for a plain sentence and no new component, so it is a
  `p` in body ink, not an amber status word like "Suspended today"; if it proves easy to miss, a
  flag word is the next step. (2) A Names row shows the figures Claude quoted from the cited news
  (`reported`, each already checked in Python against the cited cluster's text) under the label
  "Reported in news (not computed by the system)", apart from "Claude's story", with each item's
  cluster id as its evidence; nothing is shown when there are none. The critique found the items
  ran together when they wrapped at 390px and "Evidence:" split from its id; fixed with a gap
  between items and a non-breaking evidence run. No new component, colour, font, radius,
  elevation or token.
- 2026-10-22: Added the **What Claude knows** surface (`/more/claude`, a row on More) for the market
  picture build (docs/superpowers/plans/2026-10-20-market-picture.md, Task 22). Read mode over one
  request, `GET /claude/context`: the regime and its CSP limits, the picture, a row per Claude call
  with its prompt blocks, the stories dropped as noise, and a row per name. The composition was
  pinned by the operator's spec (mockup option A), so the structure workshop was skipped. The
  operator's plan said "tiles" for the calls; a grid of equal tiles is the KPI-tile grid this file
  refuses, so each call is a row with its blocks as chips. The plan's single top card is two cards
  (Regime and limits, Market picture), because it asked two questions. New components: Regime and
  limits card, Picture card, Call row, Dropped row, Name row. No new colour, font, radius,
  elevation or token. Claude's prose is labelled everywhere it appears; no lime.
- 2026-10-19: Web overhaul Part 2, Trades, built
  (docs/superpowers/plans/2026-10-19-web-overhaul-2-trades.md) and revised by the operator the same
  day for the account's full autonomy. `/trades` is the strategy switcher and three wheel views,
  Proposals, History and Assessed (Credit spreads has Spreads only), kept in `?view=`, with a smart
  default (Proposals when something waits on you, History otherwise, decided once per visit) and
  History's day in `?day=`. Who approved each trade is recorded (`approvals.decided_by`: the
  system, the web or Telegram) and shown in words, never guessed. A roll names both legs on the
  card, the History rows and the detail page, and sums to its net at the quotes it was priced at.
  The spreads books are trade-first, with the menu Claude saw kept as the reason, over the new
  `GET /spreads/picks`. The approval detail page is restyled, and its ideal zone no longer plots a
  premium on a strike axis (the strike against the strike zone; the premium against the least
  credit worth taking). Propose a roll moved from the Shorts table to the short option's own page
  (the **Roll card**), with a **Roll alert** word on Home's position rows; the controls strip left
  Trades (the bot card has them) and only the not-draining line stayed. New components: In-flight
  order row, Not-traded row, History, Spreads books, Assessed card, Roll card. No new colour, font,
  radius, elevation or token. The da-vinci finish moved the hatch off whole sentences (an
  unreadable menu, the IV-rank-unavailable tag) onto a small mark beside the words, since
  same-coloured lines through every letter made them hard to read. Open and proposed, not decided:
  a disabled quiet button (the day arrows) takes the sunk fill, so the one you cannot press looks
  more solid than the one you can; keeping it transparent would change the Buttons rule for every
  variant. Protected files unchanged, and the decide controls' look stays the recorded exception.
- 2026-10-15: Web Home follow-ups, at the operator's request
  (docs/superpowers/plans/2026-10-15-web-home-followups.md). Added the Trade card ("Done today" under
  Needs you, filter pills All / Opened / Closed / Rolled; Closed and Rolled give their reason and a
  stub that sums the whole trade to its realised P&L), the Realised calendar (a calendar button
  replaces "Chart by TradingView" at the end of the chart's range row), the Search field on the
  Positions card, row links to a new **Position** surface (chart on top, headlines directly under
  it, as the operator composed it, so the structure workshop was skipped: pinned beats roll), and
  the Income target card on More. New tokens: `field`, `calendar-day`, `calendar-day-selected` (no
  new colour, font, radius or elevation). The TradingView licence link moved from the chart to
  More's Credits card (the licence needs a link somewhere users can reach; deleting it would breach
  it). Lime appears once more: Save on the income target card, the card's one action.
- 2026-10-14: Ratified. The operator approved this file on 2026-10-14 after the Section E
  reconcile of the Part 1 build (web overhaul Part 1: Home, the three read-only routes, the shell
  and the primitives), including the `unknown` darkening below. Two recorded exceptions to the
  contract stand: the legacy bordered Approve, Reject and Halt buttons (and the native rung select)
  inside the sheets, which are protected safety files, and the 24px stub lines (WCAG 2.5.8). Two
  decisions stay open: the sheet's 180ms exit animation and the restyle of the decide controls.
- 2026-10-14: The operator darkened the light `unknown` token from `#6e7569` to `#61685d`
  (5.20:1 on paper, 4.72:1 on pressed sage, 5.76:1 on white, up from 4.30, 3.90 and 4.76), so small
  "n/a" text passes AA on every surface, including about 30 legacy files that set it on paper or
  sage. The dark twin `#8a9286` is unchanged (4.72:1 or better on the page, card and pressed fill).
  The `.hatch` stripes read slightly stronger in light. Resolves the "unknown grey" open decision.
- 2026-10-14: Section E review: added the `caption` type step (13px, the size every secondary
  line and the bot card already use; the `bot-card` token said 14px); the pay figure drops below
  its title as a whole on a narrow phone, never splitting "of" from its amount; the chart's
  TradingView credit is a text link beside the range chips instead of a logo over the line.
- 2026-10-14: Reconciled to the Part 1 build (web overhaul Task 14 Step 7), awaiting the
  operator's ratification: added the `control` type token (13.5px/600, the strategy switcher and
  theme toggle; 17px does not fit four segments at 390px) and the tokens `on-primary-dark`,
  `sunk-deep-dark`, `button-quiet`, `filter-chip`, `meter`, `bot-card`, `halted-banner`; the hero
  is 800 at every size; recorded the 44px phone hit areas and the 24px stub-line exception, the
  `--shadow-sheet` token, the legacy decide and bot controls as an exception inside the sheets, the
  proposal card's real states (no "stale data" state: the API has no stale signal), the account
  hero, positions card, needs-you column and banner, rail, tab bar and More; lime on the phone
  banner's Open; ink text selection; the sheet's immediate close (180ms exit moved to Open
  Decisions); spreads data resolved by `GET /spreads/positions`.
- 2026-10-13: Added the strategy switcher (All, CSPs, CCs, Credit spreads) at the top of Home and
  Trades, plus the same tabs on the Positions card, at the user's request. It scopes everything
  below the hero; the hero stays account-wide.
- 2026-10-13: Created from the thorough interview, replacing the dark-only IBM Plex world. Direction:
  the payslip (candidate 1 of 7, Claude's pick, roll seed 1090290943), revised by the user with a
  collapsible Why above the stub, a collapsible October pay card, and positions beneath it. Theme:
  light default with a dark toggle and a follow-OS option. Navigation: Home, Trades, Portfolio,
  Activity, Research, News, More. Monthly target is a percentage of account value.
- 2026-10-15: Added `RollModeControl` (Auto-execute or Propose only) beside `AutonomyControl` in the
  controls strip and the Bot sheet, at the user's request. It reuses the rung select's native
  styling and receipt, no new tokens.
