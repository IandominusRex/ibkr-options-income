# Web Overhaul, Part 6: Research, Universe and Search (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task
> (one Sonnet subagent per section, at the effort the Execution model gives, with a stop between sections: the
> operator's token-light method). Each section opens with **entry checks** that must all pass before its first task
> starts. **Every task that touches UI starts by invoking the `da-vinci` skill**, and so does any subagent given one of
> those tasks (say so in its prompt). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the last two Research pages on the payslip, make search a console-wide act, and close the carried
minors the HANDOFF assigned to this part:

- **Search in the shell** (HANDOFF S1): one search dialog mounted in the root layout, opened by ⌘K or Ctrl+K anywhere,
  by a Search row in the rail, a Search row on More (a phone has neither) and Research's Search button. It finds
  tickers and, by the operator's ruling, the console's own pages from a fixed list in the web (no API change).
- **Research** (L1, V7 card): the Stock page's frame; Top opportunities first with **Claude's one-line note** on each
  card (labelled as Claude's, never on a button); **"Your watchlist"** as a card of rows (the operator's ruling: it is
  apart from the scan's own watchlist, which is on Universe, and says so); the sectors as one card of rows.
- **Universe** (L3): the same frame, one card per list; the add and remove commands, the would-own confirmation and
  its consequence text unchanged; `sectors` stays file-only.
- **Carried fixes**: the `generateMetadata` guard (Part 4 nit; five layouts), the save-side tests for a pending decide
  or roll command (Part 4 gap), the stock page's value block mounting once (Part 5 minor; the operator's ruling: hold
  it until `GET /value/{symbol}` answers), and the position page's untemplated grid column and short headline links
  (Part 5 Task 11 (b)).

**Architecture:** Web only. Section A is four small fixes (`lib/segment.ts`, two test files, `features/stock/StockPage`,
`features/position/`). Section B adds `features/search/pages.ts` and `lib/search.ts`, rewrites
`components/search/CommandPalette.tsx` in place as a combobox, mounts it once in `app/layout.tsx`, and adds the Search
rows to `components/shell/Rail.tsx` and `app/more/page.tsx`. Section C restyles `components/home/{WatchlistTable,
SectorGrid,SectorCard}` in place, adds `features/research/ResearchPage.tsx` (the route only mounts it) and Claude's note
on `features/research/OpportunityCard.tsx`. Section D adds `features/universe/UniversePage.tsx` and restyles
`components/universe/*` in place. No API route or field, no Python file, no command site, no protected file, no token,
colour, font, radius or elevation changes. Nothing reaches the Rules Engine, a gate, sizing or the value book's logic.

**Tech Stack:** Next.js 15 App Router, React 19, Tailwind CSS v4, @tanstack/react-query, lucide-react, Vitest + Testing
Library. (Python is untouched; its gate runs to prove it.)

**Spec:** `docs/superpowers/plans/2026-11-05-web-overhaul-HANDOFF.md` (updated 2026-11-06 after Part 5: sections 3-6
bind this plan; 5.4 holds the operator's three answers), `web/DESIGN.md` (the visual authority), `web/CLAUDE.md`, root
`CLAUDE.md` (the web fence, the doc-update table, the Progress-log rule).

## How the code is given (read this first)

**Every change in this plan is a `git diff` patch embedded below, one per task**, generated from a per-task git
history of a prototype (see the Plan written row) and applied with `git apply`. A patch is the complete, exact code:
new files appear in full, deleted files in full, edits with their surrounding lines. So:

- **Never retype a patch.** Extract it with the helper written in A0 (`<S>/p6/plan_block.py`, `<S>` = the session's
  scratchpad directory, written out in full each time), check its SHA-256 against the table below, then
  `git apply --check` it. **`git apply --check` is the entry check that re-verifies every line a task edits**: if
  `main` moved under a patch, it fails and the section stops.
- The helper restores a blank context line an editor may have stripped (a diff's blank context line is one space);
  everything else is byte for byte. Edit this plan only with the Edit tool (Progress log rows, checkboxes), which
  leaves the patch blocks alone.
- Two blocks are not patches: `mock6` (the synthetic API for Task 15) and `capture6` (the capture harness).

| Block | SHA-256 of the extracted file | Applies on top of |
|---|---|---|
| `T1` | `9238631a75ea617c801b41cf34ab39f18b7822e5343f606c3810e30dc8d25e33` | `main` at A0 (`d3d1e28` + the plan commit) |
| `T2` | `602febf08bab162b8413ecd8d65a78775776d9771b98bbc2762ded7095f23cf9` | T1 |
| `T3` | `9833df6358fea04d0b1048ec4296c7803cab34972c968b9e1e325d7c66e67795` | T2 |
| `T4` | `e0d9fe2add8a6b2eff787f01d5e2890d804d31c88ab809aecdab67c0dc171c5a` | T3 |
| `T5` | `5ec7a577cc34b530fe04996ec89fd057e3547397c068be0baa52b5564d1ad3ae` | T4 |
| `T6` | `a533f9b06ba2d3b2a69d3b46fb4ed74e56c2eb430d8c94b3fa81be9122d502c5` | T5 |
| `T7` | `db8ac3ae67b2fd0bb63a601d762245df72c9fb90b6cf7f5d6bc4347abf8d8043` | T6 |
| `T8` | `61c607e957ea79eb612bc417f9020203c729167f8a087f08a996d54fd09858cd` | T7 |
| `T9` | `a0a808148fad7290bdfbc80a6d884f901607921ac68aa6cc2863a8d8c615361c` | T8 |
| `T10` | `c6e54f0fa8abd10c0f7ee653ed3094ba4ee24cb5632f8318b8d37aa614e4600f` | T9 |
| `T11` | `124d4e142d5190f3c7b3417a37194a2d0b0979c4a0f62b949d641ea86caad635` | T10 |
| `T12` | `7109309b556377976c7b11805f87f2e6c3f083ba9765f41910deb75ad9d5bc13` | T11 |
| `T13` | `edb06f84c974ea8808fe1530111f18920f2f2d3621087b09d28f1a1c4b4fc743` | T12 |
| `T14` | `b2ad0ea76b9d8055afaf7b6bfe7448ce133d7e494a77d1998c6c198c57a9a390` | T13 |
| `mock6` | `7953b7b513e5dc42f92a71ea3ab89609c33e983201872ae0ba5c4355d2f3767f` | (a script, not a patch) |
| `capture6` | `b3a19ccf9785ef04dc6eeeec7c9c252e5d5705724fcff9598e0b4ab6d19dc7a3` | (a script, not a patch) |

## Execution model

| Section | Tasks | Model | Effort | Why this model and effort |
|---|---|---|---|---|
| **A, Carried fixes** | 1-4 | **sonnet** | medium | Four small, disjoint patches, each with its red check; Tasks 3 and 4 touch layout (da-vinci first, nothing to decide). |
| **B, Search in the shell** | 5-7 | **sonnet** | high | Shared state across the whole shell (one palette, one open event, the root layout) and a combobox's keyboard model; T7 builds on T6. |
| **C, Research** | 8-11 | **sonnet** | high | Four patches that each edit `app/research/page.tsx` in turn and build one page; da-vinci first. |
| **D, Universe** | 12-13 | **sonnet** | medium | A restyle in place under a 481-line suite, with the command flow and `ConfirmAction` untouched; two disjoint patches. |
| **E, Finish** | 14-15 | **sonnet** medium (Task 14, docs), **sonnet** high, a fresh agent (Task 15, the da-vinci finish) | as listed | Then one **opus** whole-branch review (high) and one **sonnet** fix pass (high). |

**How a section runs (the orchestrator).** The main session is a Sonnet orchestrator (effort high). For each section:

1. Run the section's **entry checks** yourself, in order. **Any check fails: stop**, report the output, do not start
   the section. A failure that belongs to the previous section is fixed there (record the ruling) first.
2. All pass: add a "Section X entry" row to the Progress log (gate result, date) in the worktree.
3. Spawn **one** subagent for the section with `model` and `effort` from the table (pass `effort` on every spawn). Its
   prompt: "You are executing Section X of `docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md`
   in the worktree `<W>` (the absolute path). The session scratchpad is `<S>` (the absolute path); the patch helper is
   `<S>/p6/plan_block.py`. Read the plan's 'How the code is given', 'Global Constraints' and your section only, plus
   the files the section lists under Reads. Apply each task's patch exactly as its steps say; never retype a patch;
   never edit a protected file; never build or run `next dev` inside `web/`. Invoke the `da-vinci` skill before any
   UI step and give it the section's Spec for da-vinci paragraph. Commit each task with its message, ticking its boxes
   and filling its Progress log row in the same commit (status, commit, gate, date, every ruling with its
   cost-if-wrong). Stop on any red gate you cannot attribute to your own change."
4. Verify the report yourself: `git log --oneline main..HEAD`, `git status --short`, the gate counts against the
   section exit, G1, G2 and G7.
5. **Stop and ask the operator before the next section.**

After Section E's Task 15: one **opus** whole-branch review (superpowers:requesting-code-review, effort high) over
`main..HEAD` with the Review Focus below, as a subagent; the orchestrator confirms each finding in the code; one
**sonnet** fix pass (high), each fix test first. Ask before merge or push; fill the Merge, Push and Restart rows after
each happens.

**Commit counts.** A0 adds one commit on `main` (this plan and the HANDOFF). Each task is one commit and fills its own
Progress log row; a "Section X entry" row rides in the next task's commit. A review fix pass adds one commit.

## Progress log

| Section / task | Status | Commits | Gate | Date | Rulings |
|---|---|---|---|---|---|
| **Plan written** | done | (plan file only) | Prototyped on a code-only copy of `main` at `d3d1e28` (`git archive`, `.venv` and `web/node_modules` symlinked, session scratchpad), as a per-task git history from which every patch was generated (two fixes found by looking were folded back into T6 and T8 with `--fixup`). **Each task's commit re-checked in a second worktree:** `tsc --noEmit` clean at T1-T14; full vitest 1567, 1571, 1573, 1575, 1583, 1591, 1593, 1597, 1601, 1603, 1605, 1608, 1611, 1611 across T1-T14 (152 files to T4, 153 to T8, 154 to T11, 155 at T12, 156 from T13). **Full gates on the final tree:** vitest **1611 in 156 files** (1562 + 49); `tsc --noEmit` and `npm run lint` clean; pytest **5767 passed, 1 skipped** (no Python file changes; equal to `main`); `ruff check .` clean; `mypy src` 361 files clean; da-vinci `lint.py` over every touched folder: no finding (it first flagged the palette input's `outline-none`, now a `focus-visible` outline); `design_md_check.py web/DESIGN.md` exit 0; G1 empty, G2 the four files, G7 the one layout line; scratch `npm run build` green on the first try (18 routes plus `/_not-found`; `○ /research` 9.8 kB, `○ /research/universe` 3.87 kB). **Red checks run** (each new test against the old code, by stashing the task's source files): T1 5 failed / 20 passed; T2 by mutation of the two protected save calls, then restored (4 failed / 33 passed, ruling 16); T3 1 / 7; T4 2 / 15; T6 12 / 5; T7 3 / 12; T8 6 / 7; T9 4 / 4; T11 1 / 10; T12 2 / 19; T13 3 / 0; T5 and T10 are new modules (red = module missing). **Rendered** with `next start` from the prototype's build against `mock6` and a headless Chromium (`capture6`): Research, Universe and More at 320, 390 and 1440 px, light and dark, plus the palette with "a" typed: `hscroll` measured on `main` 0 everywhere, no page error, the `h2` orders as Task 15 expects, the palette's two groups and 7 options. **Two fixes came from looking** (both in the patches): the palette input's focus ring sat 2 px off the input and clipped against Close (now offset 0); the watchlist's facts line doubled the space before each dot and began a wrapped line with a dot (now one inline run). **Not run:** a fresh-eyes da-vinci critique and audit (Task 15 does it), the live API, the stock and position pages rendered (Tasks 3 and 4 are pinned by tests only), the Opus review. | 2026-11-06 | Written from the HANDOFF (updated 2026-11-06 after Part 5) section 5's Part 6 row and the operator's three answers (HANDOFF 5.4); rulings 1-20 below. |
| **A0 setup** | done | plan commit affa316 on main over d3d1e28 | worktree <W> with .venv and web/node_modules symlinks, init_db run; free disk 21 GiB (floor 10) | 2026-11-07 | all 16 block hashes match the table |
| **Section A entry** | done | - | A1 git log shows affa316 over d3d1e28, status clean; A2 git apply --check silent for T1-T4; A3 baseline: pytest 5767 passed 1 skipped, ruff clean, mypy 361 files clean, vitest 1562 in 152 files, tsc and lint clean | 2026-11-07 | none |
| **Task 1: the title guard** | done | 725f26b | red check (5 layouts stashed): titles.test.ts 5 failed / 20 passed; with the patch 25 passed; full vitest 1567 in 152 files; tsc and lint clean | 2026-11-07 | none: patch applied as given |
| **Task 2: the save-side tests** | done | 61f503a | 37 passed in the two files; full vitest 1571 in 152 files; tsc, lint clean; G1 prints nothing; no red check (ruling 16) | 2026-11-07 | none |
| **Task 3: the value block mounts once** | done | 496127f | red check: StockPage 1 failed / 7 passed; with patch 8 passed; features/stock 53 passed; full vitest 1573 in 152 files; tsc, lint clean | 2026-11-07 | da-vinci invoked with the section Spec: no change |
| **Task 4: the position page's column and headline links** | done | 8104abd | red check: PositionPage 2 failed / 15 passed; with patch 17 passed; full vitest 1575 in 152 files; tsc, lint clean; G1 empty, G2 the four files, G5 no non-test line | 2026-11-07 | da-vinci invoked with the section Spec: no change |
| **Section A exit** | done | - | vitest 1575 in 152 files; tsc and lint clean; G1 empty; G2 the four files; G5 no non-test finding (lint.py rejects the not-yet-created paths web/features/search and web/features/universe, so it was run over the existing ones); status clean after commit | 2026-11-07 | G5 run on existing paths only (cost if wrong: none, those folders do not exist yet) |
| **Section B entry** | done | - | B1 `git log main..HEAD` shows the four Section A commits (725f26b, 61f503a, 496127f, 8104abd), vitest 1575 in 152 files, tsc and lint clean, G1 empty, G2 four files; B2 `git apply --check` printed nothing for T5 and T6; B3 neither web/features/search nor web/lib/search.ts exists and the openSearch grep printed nothing. Baseline pytest/ruff/mypy green at A3, no Python file changed | 2026-11-07 | none |
| **Task 5: pages and the open event** | done | (this commit) | features/search 8 passed (new module: red = module missing); full vitest 1583 in 153 files; tsc, lint clean | 2026-11-07 | patch applied as given; Task 4's row hash filled in (8104abd, was "(this commit)"; cost if wrong: none, a log cell) |
| **Task 6: the palette** | | | | | |
| **Task 7: the palette in the shell** | | | | | |
| **Section B exit** | | | | | |
| **Section C entry** | | | | | |
| **Task 8: Your watchlist** | | | | | |
| **Task 9: the Sectors card** | | | | | |
| **Task 10: the Research page** | | | | | |
| **Task 11: Claude's note** | | | | | |
| **Section C exit** | | | | | |
| **Section D entry** | | | | | |
| **Task 12: the Universe page** | | | | | |
| **Task 13: the add field and the override badge** | | | | | |
| **Section D exit** | | | | | |
| **Section E entry** | | | | | |
| **Task 14: docs** | | | | | |
| **Task 15: the da-vinci finish by a fresh reviewer** | | | | | |
| **Whole-branch review (opus)** | | | | | |
| **Review fix pass (sonnet)** | | | | | |
| **Merge** (fast-forward onto `main`, on the operator's yes) | | | | | |
| **Push** (on the operator's yes) | | | | | |
| **Restart** (`./ibkr restart`; fill this row when it happens, with the `ps` start time) | | | | | |

*(Rows are filled as each task lands; a ruling is any deviation from the task text, and why, with its cost if wrong.)*

## Roadmap (this plan is Part 6 of 8, HANDOFF section 5)

- **Parts 1-5** and the value book's web sections F-I: done, merged, pushed and restarted.
- **Part 6, Research, Universe and search.** This plan.
- **Part 7, News, More and How it works** (L4, L5, L6, S4, S5). **Part 8, The value record** (F5, V9), gated.
  **Order control** on its own track (spec first).

## Rulings made up front (the operator may overturn any of them)

**Scope:**

1. **Scope is the HANDOFF's Part 6 row plus the operator's three answers (5.4)**: L1, L3, S1, V7 (card), S5
   (Research and Universe paragraphs), the save-side tests, the `generateMetadata` guard, the position page's two
   fixes and the value block's hold. The guard covers **five** layouts, not the HANDOFF's four (`stock/[symbol]`,
   `news/[symbol]`, `ledger/ticker/[symbol]`, `positions/[underlying]/[slug]`, `trades/[approvalId]`). No API route or
   field: `claude_note` has been served since Part 5. *Cost if wrong: none.*

**The operator's answers (2026-11-06, HANDOFF 5.4), as rulings:**

2. **Search finds tickers and the console's own pages**, the pages from a fixed list in the web
   (`features/search/pages.ts`), no request and no API change. Held positions and waiting proposals are not listed.
   *Cost if wrong: one more group and one or two reads per open.*
3. **Both watchlists stay.** Research's per-user list is titled "Your watchlist" with one line saying the scan's own
   watchlist is on Universe (a link). Copy only. *Cost: copy.*
4. **The stock page holds its value block until `GET /value/{symbol}` has answered** (react-query `isPending` is
   false: data or an error), then mounts it once, in the slot the answer picks; a failed read places it at the foot,
   as before. While the read is pending (in the app, with react-query's default retries, up to about seven seconds on a
   failing API) there is no block and no placeholder. The rare remount when Claude's read flips the lead while the page
   is open stays (a terminal receipt is then lost; a pending one is restored from storage): STATUS records it.
   *Cost if wrong: a placeholder.*

**Search (Section B):**

5. **One palette, mounted once in `app/layout.tsx`**, opened by ⌘K/Ctrl+K and by the event `ibkr:open-search`
   (`lib/search.ts::openSearch`). Research no longer mounts its own: two mounted palettes would both toggle on ⌘K and
   cancel out. The controlled `open`/`onOpenChange` props stay (tested; no caller uses them). G7 pins one mount.
   *Cost: none.*
6. **Restyled in place, still hand-built** (not `cmdk`, which is installed but unused; ARCHITECTURE's sentence that
   said otherwise is corrected in Task 14). It becomes a combobox: the input has `role="combobox"` and
   `aria-activedescendant`, the results are a `listbox` of `option`s in two labelled groups, the options are not
   focusable (focus stays in the input), and the Tab trap stays. *Cost if wrong: a later move to cmdk.*
7. **Pages first, at most five, then tickers.** `matchPages` needs every typed word in a page's name, hint or words,
   ranks a name that starts with the term first, and finds nothing for a blank term. The first result is active, so
   Enter opens it. *Cost: an order.*
8. **No shadow** (DESIGN.md allows one only on the sheet and the confirm dialog; the scrim lifts the panel); a 16px input
   so iOS does not zoom; on a phone, which has no Escape key, a quiet **Close** and a tap on the scrim close it. A
   status line, always mounted as `role="status"`, says the state in words; "No ticker or page matches ..." appears only
   once the ticker search has answered for that term; a failed ticker search says so while the pages still list.
   *Cost: copy.*
9. **The rail gets a pressed-sage Search row under the wordmark** (magnifier, "Search", a muted "⌘K",
   `aria-keyshortcuts`), and **Research's nav icon becomes lucide `Telescope`**, so the magnifier means search alone.
   **More gets a Search row first in its links card.** *Cost if wrong: an icon.*

**Research (Section C):**

10. **The Stock page's frame** (`mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4`, the 24px/800 title): a muted line
    under the title; Search (secondary, it opens the palette) and Universe (a secondary pill link) at the right; Top
    opportunities full width; then Stock's grid (`lg:grid-cols-[minmax(0,1fr)_340px]`, each column one `grid-cols-1`
    track): Your watchlist left, the Sectors card right. No lime on the page. *Cost: classes.*
11. **Your watchlist is a card of rows, not a table** (the payslip's quiet rows): the ticker bold and the company muted,
    a muted line "IV rank 80.0 · 3 of 5 checks pass · Earnings Nov 19, 2026", the price right with "-1.25% today"
    under it, signed and never green or red (a price move is not money, HANDOFF ruling 7), "Delayed" as a flag word on a
    stale quote, a quiet Remove (44px on a phone). Every unknown is a hatched n/a, and "0 of 0" becomes "Checks n/a".
    **Two honesty fixes ride along:** it used to say "Your watchlist is empty" while still loading (now a labelled
    loading block, and a failed read is a sentence), and a failed add or remove used to be silent (now a sentence).
    The per-user watchlist's add and remove still write research.db directly, as before (not the trading DB, so the
    web fence is unaffected). *Cost: classes and copy.*
12. **The sectors are one card of rows** ("Sectors by IV rank", like the Market card), not a tile grid (DESIGN.md's
    anti-references include the KPI-tile grid). `SectorCard.tsx` keeps its name and props and renders an `li`; the
    move is signed and never green or red. *Cost: classes.*
13. **Claude's note** sits after Python's reasons in a pressed-sage block: "Claude's note" with "its reading, not a
    gate" beside it (`features/stock-value/parts::ClaudeLabel`), the text at most 65 characters wide. The API carries
    no date for it, so none is shown; a name Claude has not read for the list shows no label. Never on a link or a
    button. *Cost: copy.*

**Universe (Section D):**

14. **`features/universe/UniversePage.tsx` is the page** (`page.tsx` only mounts it): a back link to Research, the
    title, one muted line on what can be changed here, then one Card per list in two `minmax(0,1fr)` columns from
    1024px. `components/universe/*` are restyled in place: each list says what it is for in one line; "Would own -
    CSP allowlist" becomes "Would own" (the purpose line carries the rest); "wheeling" and "dip-watch" become the
    status-word-styled "Wheeling" and "Dip-watch" (two test strings change); a failed command is a plain sentence,
    never red; AddSymbol's `aria-label` is removed so its new visible label names the field (WCAG 2.5.3). The
    would-own confirmation (`ConfirmAction`, protected) and its consequence text, the commands and the receipts are
    unchanged. *Cost: copy and classes.*

**The carried fixes (Section A):**

15. **The title guard is one helper**, `lib/segment.ts::decodeSegment` (the raw segment when `decodeURIComponent`
    throws), used by all five layouts. *Cost: none.*
16. **The save-side tests pin existing behaviour**, so their red check cannot be run against `main` without editing a
    protected file. It was run in the prototype instead (the two save calls in `DecideControls.tsx` and
    `RollProposal.tsx` replaced by `void 0`, then restored: 4 failed, 33 passed); the plan does not repeat it.
    *Cost: none.*
17. **The position page gets the stock page's two fixes**: its trade column is `grid min-w-0 grid-cols-1`, and a
    headline link is `flex min-h-11 items-center ... md:inline md:min-h-0` (it already said "(opens in a new tab)").
    *Cost: classes.*

**Standing rules:**

18. **Protected files are byte-identical to `main`** (G1), **the command-site grep is unchanged** (G2) and **one
    palette is mounted** (G7). A test file beside a protected component may change (Task 2 adds cases to
    `DecideControls.test.tsx`).
19. **No new token, colour, font, radius or elevation.** **Docs**: `web/DESIGN.md` lands with the UI (the Search
    palette, Rail and More lines in Task 7; the Research surface and the Decision Log entry in Task 10; the Top
    opportunities line in Task 11; the Universe surface in Task 12); `STATUS.md`, `ARCHITECTURE.md` and `web/CLAUDE.md`
    in Task 14. No route, field, config key, script, command kind or Telegram command is added, so `docs/web/api.md`,
    `docs/web/commands.md`, `SETUP.md` and `README.md` do not change.
20. **Effort per section** follows the operator's 2026-11-06 instruction (medium for mechanical edits, high for UI and
    shared state). **Never build inside `web/`** (G4).

## Global Constraints

- Core invariant, the fences and the two written exceptions in root `CLAUDE.md` are untouched. Nothing here places,
  sizes, prices or gates anything; Claude's words stay labelled and never sit on a button.
- The API is not touched: it still writes exactly one trading-DB table (`app_commands`); `src/api/` imports from
  `src.value` only `scorecard` and `schemas`. `tests/test_web_fence.py`, `test_eval_skills.py`, `test_regime_fence.py`,
  `test_news_fence.py`, `test_spreads_fence.py`, `test_value_fence.py` and `test_wheel_spreads_isolation.py` stay green
  and unweakened.
- UI: tokens only (no raw palette class, no hex); `.tabular` on numbers; lime only on the primary act (these pages have
  none); unknown is a hatched `n/a`, never `$0` or blank; no state by colour alone; green and red only on signed money;
  no shadow; 44px phone targets; zero em dashes and none of "seamless", "robust", "unlock", "elevate" in UI copy.
- Gates run from the worktree root. Web: `cd web && npx vitest run && npx tsc --noEmit && npm run lint`. Python:
  `python -m pytest -q && ruff check . && mypy src`. `tests/test_scan_timeout.py` is a known flake: if it is the only
  failure, re-run it alone; green means "scan timeout flake" in the log. The repo is not prettier-formatted: never run
  `prettier --write` on a file.
- In a Bash call, `cd` does not persist and environment variables do not either: write `<S>` and `<W>` out as absolute
  paths in every command. A red check stashes named source files with `git stash push -- <paths>` (untracked new files
  stay in place) and always ends with `git stash pop`.

**Shared checks (referenced by every section exit):**

- **G1, protected files:** `git diff --stat main -- web/components/options/DecideControls.tsx web/components/options/ConfirmAction.tsx web/components/options/CommandReceipt.tsx web/components/options/HaltControl.tsx web/components/options/AutonomyControl.tsx web/components/options/RollModeControl.tsx web/lib/commands.ts web/lib/receipt.ts` prints nothing.
- **G2, command sites:** `grep -rln "submitCommand\|confirmCommand" web/features | sort` prints exactly
  `web/features/more/TargetCard.test.tsx`, `web/features/more/TargetCard.tsx`,
  `web/features/stock-value/AnalyseButton.test.tsx`, `web/features/stock-value/AnalyseButton.tsx`.
- **G3, design spec:** `python3 ~/.claude/skills/da-vinci/scripts/design_md_check.py web/DESIGN.md` exits 0.
- **G4, scratch build** (never inside `web/`; the `mktemp` + `rm -rf "$(dirname ...)"` form is refused by the sandbox,
  so use the scratchpad by literal path):
  `rm -rf <S>/p6/build && mkdir -p <S>/p6/build && rsync -a --exclude node_modules --exclude .next web/ <S>/p6/build/web/ && ln -s <W>/web/node_modules <S>/p6/build/web/node_modules`
  then `cd <S>/p6/build/web && npm run build`. Expect the route table with `○ /research` and `○ /research/universe`
  among **18 routes plus `/_not-found`** (19 rows). If it fails with `Cannot read properties of null (reading '1')` in
  `next/font/google`, that is the known transient font fetch: run the build again, up to three tries. Then
  `rm <S>/p6/build/web/node_modules` and `rm -rf <S>/p6/build` (Task 15 keeps it until its own Step 5).
- **G5, da-vinci lint:** `python3 ~/.claude/skills/da-vinci/scripts/lint.py web/features/research web/features/search web/features/universe web/features/stock web/features/position web/components/search web/components/home web/components/universe web/components/shell web/app/research web/app/more web/lib`
  prints no line for a non-test file.
- **G6, fences:** `python -m pytest -q tests/test_web_fence.py tests/test_value_fence.py tests/test_eval_skills.py tests/test_openapi_current.py` passes.
- **G7, one palette** (from Task 7 on): `grep -rn "<CommandPalette" web/app web/components web/features | grep -v "\.test\."`
  prints exactly one line, `web/app/layout.tsx:55:          <CommandPalette />`.

**Extracting and applying a patch.** A0 extracts every block to `<S>/p6/<name>.out` and checks the hashes. A task
step "Check and apply `Tn`" means, from `<W>`:

```bash
git apply --check <S>/p6/Tn.out      # prints nothing; any error: stop and report it
git apply <S>/p6/Tn.out
```

If `<S>/p6/Tn.out` is missing (a new session), re-extract it first and check its hash:
`python3 <S>/p6/plan_block.py docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md Tn > <S>/p6/Tn.out && shasum -a 256 <S>/p6/Tn.out`
(the helper itself is written in A0; write it again from A0 if the scratchpad is new).

## Review Focus

1. **One palette, and it only navigates**: G7; the palette calls `router.push` and nothing else; `openSearch` is the
   only way in from the rail, More and Research → Tasks 5-7.
2. **Claude's note is Claude's**: labelled, never on a link or button, absent with no label when null → Task 11.
3. **Unknown is never none**: the watchlist's loading and failure states, the hatched n/a in the watchlist, the sectors
   and the override badge; "0 of 0 checks" gone → Tasks 8, 9, 13.
4. **No colour carries a state, no green or red off money**: watchlist and sector moves, Universe failures →
   Tasks 8, 9, 12, 13.
5. **Universe's safety friction is unchanged**: a would-own add still opens `ConfirmAction` with the put and the
   assignment named before any command; a watchlist add still fires at once; `sectors` stays file-only → Tasks 12-13
   (the 481-line `UniverseList.test.tsx` passes with two test strings changed).
6. **The value block's hold** reads `isPending` (no data and no error), so an error still places the block → Task 3.
7. **Nothing reaches the trading path**: G1, G2, G6 at every exit; no file under `src/` changes.

---

## File structure

```
docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md, the HANDOFF      COMMIT (A0, on main)
web/lib/segment.ts                                         CREATE  decodeSegment                                 (T1)
web/app/{stock/[symbol],news/[symbol],ledger/ticker/[symbol],positions/[underlying]/[slug],trades/[approvalId]}/layout.tsx
                                                           MODIFY  decodeSegment                                 (T1)
web/app/titles.test.ts                                     MODIFY  +5 cases                                      (T1)
web/components/options/DecideControls.test.tsx             MODIFY  +2 cases (test only; the component is protected) (T2)
web/features/position/RollCard.test.tsx                    MODIFY  +2 cases                                      (T2)
web/features/stock/StockPage.tsx (+ test)                  MODIFY  hold the value block until it is known        (T3)
web/features/position/PositionPage.tsx, Headlines.tsx (+ PositionPage.test.tsx)   MODIFY                         (T4)
web/lib/search.ts, web/features/search/pages.ts (+ pages.test.ts)                 CREATE                         (T5)
web/components/search/CommandPalette.tsx (+ test)          REWRITE in place; app/research/page.test.tsx one regex (T6)
web/app/layout.tsx, web/lib/nav.ts, web/components/shell/Rail.tsx (+ test), web/app/more/page.tsx (+ test),
web/app/research/page.tsx (+ test), web/DESIGN.md          MODIFY                                                (T7)
web/components/home/WatchlistTable.tsx (+ test), web/app/research/page.tsx (+ test)   MODIFY                     (T8)
web/components/home/SectorCard.tsx, SectorGrid.tsx (+ SectorCard.test.tsx; SectorGrid.test.tsx CREATE),
web/app/research/page.tsx                                  MODIFY                                                (T9)
web/features/research/ResearchPage.tsx (+ test)            CREATE; app/research/page.tsx one mount; app/research/page.test.tsx DELETE;
web/DESIGN.md                                              MODIFY                                                (T10)
web/features/research/OpportunityCard.tsx (+ test), web/DESIGN.md                     MODIFY                     (T11)
web/features/universe/UniversePage.tsx (+ test)            CREATE; app/research/universe/page.tsx one mount;
web/components/universe/UniverseList.tsx (+ test), web/DESIGN.md                      MODIFY                     (T12)
web/components/universe/AddSymbol.tsx, OverrideBadge.tsx  MODIFY; components/universe/restyle.test.tsx CREATE    (T13)
STATUS.md, ARCHITECTURE.md, web/CLAUDE.md                  MODIFY                                                (T14)
```

---

## Section A: Carried fixes (Tasks 1-4) · model: sonnet (effort medium)

**Reads:** this section; `web/app/stock/[symbol]/layout.tsx`; `web/features/stock/StockPage.tsx` (lines 70-125);
`web/features/position/PositionPage.tsx` (lines 180-200); `web/features/position/Headlines.tsx` (lines 45-60);
`web/components/options/DecideControls.tsx` (lines 105-125, read only: protected).

**Spec for da-vinci (Tasks 3 and 4; give it this, so it has little to decide):** no visual change beyond the classes
in the patches. Task 3: the value block appears once, in its slot, after the value read answers. Task 4: the position
page's trade column is one `minmax(0,1fr)` track and a headline link is a 44px row on a phone and an inline link from
768px, as `components/stock/NewsPanel.tsx`'s. da-vinci changes nothing; record "no change" in the row.

**A0. Setup (orchestrator, before the entry checks).**

- [x] In the main checkout (`/Users/ianlim/Desktop/IBKR Investments`, on `main`): `git status --short` shows only
  ` M docs/superpowers/plans/2026-11-05-web-overhaul-HANDOFF.md`,
  `?? docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md` and `?? data/value_filing_reads.json`
  (a runtime file: leave it alone). Commit the two docs:
  `git add docs/superpowers/plans/2026-11-05-web-overhaul-HANDOFF.md docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md`
  then `git commit -m "docs(plan): web overhaul Part 6 plan and the updated handoff"` (with the session's attribution
  lines). `git log --oneline -2` shows it over `d3d1e28` (if `main` moved past `d3d1e28`, stop and ask: the patches were
  cut against it).
- [x] `df -h .` shows at least 10 GiB free (23 GiB at 95% on 2026-11-06). Below that, stop and ask.
- [x] Create the worktree, one command per call:
  `git worktree add .claude/worktrees/web-overhaul-6 -b feat/web-overhaul-6 main`;
  `ln -s "/Users/ianlim/Desktop/IBKR Investments/.venv" "/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/web-overhaul-6/.venv"`;
  `ln -s "/Users/ianlim/Desktop/IBKR Investments/web/node_modules" "/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/web-overhaul-6/web/node_modules"`;
  then from the worktree root
  `IBKR_CONFIG_USE_EXAMPLES=1 .venv/bin/python -c "from src.storage.db import init_db; init_db()"`.
  `<W>` = `/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/web-overhaul-6`.
- [x] Write the patch helper (`<S>` = this session's scratchpad, absolute):

```bash
mkdir -p <S>/p6 && cat > <S>/p6/plan_block.py <<'PY'
"""Print one fenced block of the web overhaul Part 6 plan, found by its marker comment.

Usage: python3 plan_block.py <plan.md> <NAME> > out
The block is the first four-backtick fence after the marker line for NAME. For a patch (NAME starts
with "T") an empty line is written back as one space: a diff's blank context line is a single space,
and an editor may have stripped it.
"""
import sys

plan, name = sys.argv[1], sys.argv[2]
text = open(plan, encoding="utf-8").read()
mark = text.index("<!-- block " + name + " -->\n")
fence = text.index("\n" + "`" * 4, mark) + 1
body = text.index("\n", fence) + 1
end = text.index("\n" + "`" * 4 + "\n", body)
lines = text[body:end].split("\n")
if name.startswith("T"):
    lines = [line if line else " " for line in lines]
sys.stdout.write("\n".join(lines) + "\n")
PY
```

- [x] From `<W>`, extract all fourteen patches and the two other blocks, and check every hash against the table:
  `for b in T1 T2 T3 T4 T5 T6 T7 T8 T9 T10 T11 T12 T13 T14 mock6 capture6; do python3 <S>/p6/plan_block.py docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md $b > <S>/p6/$b.out; done; shasum -a 256 <S>/p6/*.out`
  Every line matches the table. Any mismatch: stop.
- [x] Record A0 in the Progress log (commit hash, worktree path, hashes OK) in Task 1's commit.

**Entry checks:**

- [x] **A1. Starting point.** In `<W>`: `git log --oneline -2` shows the A0 commit over `d3d1e28`; `git status --short`
  is empty.
- [x] **A2. Every patch of the section applies on the tree as it is** (they touch disjoint files):
  `git apply --check <S>/p6/T1.out`, `T2.out`, `T3.out`, `T4.out`: each prints nothing.
- [x] **A3. Baseline green.** `python -m pytest -q && ruff check . && mypy src`;
  `cd web && npx vitest run && npx tsc --noEmit && npm run lint`. Expected on 2026-11-06: pytest **5767 passed, 1
  skipped**; mypy **361 files**; vitest **1562 in 152 files**. Record the counts.

**Section exit:** four task commits after A0; vitest **1575 in 152 files**; tsc, lint clean; G1, G2, G5; `git status
--short` clean.

### Task 1: The title guard

**Files:** Create `web/lib/segment.ts`; modify the five `generateMetadata` layouts and `web/app/titles.test.ts`; this
plan (Progress log).

**What it does (ruling 15):** a stray `%` in a hand-typed URL no longer throws in a page title; the title keeps the raw
segment. Five new cases, one per layout.

- [x] **Step 1: Check and apply `T1`.** `git status --short` shows six `M` files and `?? web/lib/segment.ts`.
- [x] **Step 2: Red check.** `git stash push -- web/app/ledger web/app/news web/app/positions web/app/stock web/app/trades`,
  then `cd web && npx vitest run app/titles.test.ts` ends `5 failed | 20 passed (25)`, then `git stash pop` (the five
  layouts come back).
- [x] **Step 3: Gate.** `npx vitest run app/titles.test.ts`: 25 passed. Full vitest **1567 in 152 files**; tsc, lint
  clean.
- [x] **Step 4: Commit** `fix(web): a malformed escape in a URL keeps the raw segment in the page title` with the
  Progress log row (and the A0 and Section A entry rows).

<!-- block T1 -->
````diff
diff --git a/web/app/ledger/ticker/[symbol]/layout.tsx b/web/app/ledger/ticker/[symbol]/layout.tsx
index b4a9443..7bcd826 100644
--- a/web/app/ledger/ticker/[symbol]/layout.tsx
+++ b/web/app/ledger/ticker/[symbol]/layout.tsx
@@ -1,9 +1,10 @@
 import type { Metadata } from "next";
+import { decodeSegment } from "@/lib/segment";
 
 // The page is a client component, which cannot export metadata (web overhaul Part 4, ruling 23).
 export async function generateMetadata({ params }: { params: Promise<{ symbol: string }> }): Promise<Metadata> {
   const { symbol } = await params;
-  return { title: `${decodeURIComponent(symbol).toUpperCase()} ledger` };
+  return { title: `${decodeSegment(symbol).toUpperCase()} ledger` };
 }
 
 export default function Layout({ children }: { children: React.ReactNode }) {
diff --git a/web/app/news/[symbol]/layout.tsx b/web/app/news/[symbol]/layout.tsx
index 72bd0f0..ec63d69 100644
--- a/web/app/news/[symbol]/layout.tsx
+++ b/web/app/news/[symbol]/layout.tsx
@@ -1,9 +1,10 @@
 import type { Metadata } from "next";
+import { decodeSegment } from "@/lib/segment";
 
 // The page is a client component, which cannot export metadata (web overhaul Part 4, ruling 23).
 export async function generateMetadata({ params }: { params: Promise<{ symbol: string }> }): Promise<Metadata> {
   const { symbol } = await params;
-  return { title: `${decodeURIComponent(symbol).toUpperCase()} news` };
+  return { title: `${decodeSegment(symbol).toUpperCase()} news` };
 }
 
 export default function Layout({ children }: { children: React.ReactNode }) {
diff --git a/web/app/positions/[underlying]/[slug]/layout.tsx b/web/app/positions/[underlying]/[slug]/layout.tsx
index edeb9e2..d4e5707 100644
--- a/web/app/positions/[underlying]/[slug]/layout.tsx
+++ b/web/app/positions/[underlying]/[slug]/layout.tsx
@@ -1,9 +1,10 @@
 import type { Metadata } from "next";
+import { decodeSegment } from "@/lib/segment";
 
 // The page is a client component, which cannot export metadata (web overhaul Part 4, ruling 23).
 export async function generateMetadata({ params }: { params: Promise<{ underlying: string; slug: string }> }): Promise<Metadata> {
   const { underlying } = await params;
-  return { title: `${decodeURIComponent(underlying).toUpperCase()} position` };
+  return { title: `${decodeSegment(underlying).toUpperCase()} position` };
 }
 
 export default function Layout({ children }: { children: React.ReactNode }) {
diff --git a/web/app/stock/[symbol]/layout.tsx b/web/app/stock/[symbol]/layout.tsx
index d64b210..eca31f1 100644
--- a/web/app/stock/[symbol]/layout.tsx
+++ b/web/app/stock/[symbol]/layout.tsx
@@ -1,9 +1,10 @@
 import type { Metadata } from "next";
+import { decodeSegment } from "@/lib/segment";
 
 // The page is a client component, which cannot export metadata (web overhaul Part 4, ruling 23).
 export async function generateMetadata({ params }: { params: Promise<{ symbol: string }> }): Promise<Metadata> {
   const { symbol } = await params;
-  return { title: decodeURIComponent(symbol).toUpperCase() };
+  return { title: decodeSegment(symbol).toUpperCase() };
 }
 
 export default function Layout({ children }: { children: React.ReactNode }) {
diff --git a/web/app/titles.test.ts b/web/app/titles.test.ts
index b1609ce..e191b41 100644
--- a/web/app/titles.test.ts
+++ b/web/app/titles.test.ts
@@ -81,6 +81,21 @@ describe("route titles (web overhaul Part 4, ruling 23)", () => {
     expect((await proposal({ params: Promise.resolve({ approvalId: "42" }) })).title).toBe("Proposal 42");
   });
 
+  // A stray "%" in a hand-typed URL is a malformed escape: the title falls back to the raw segment
+  // instead of throwing (web overhaul Part 6).
+  it.each([
+    ["stock", () => stock({ params: Promise.resolve({ symbol: "ab%zz" }) }), "AB%ZZ"],
+    ["news ticker", () => newsTicker({ params: Promise.resolve({ symbol: "ab%zz" }) }), "AB%ZZ news"],
+    ["ledger ticker", () => ledgerTicker({ params: Promise.resolve({ symbol: "ab%zz" }) }), "AB%ZZ ledger"],
+    ["position", () => position({ params: Promise.resolve({ underlying: "ab%zz", slug: "x" }) }), "AB%ZZ position"],
+    ["proposal", () => proposal({ params: Promise.resolve({ approvalId: "4%2" }) }), "Proposal 4%2"],
+  ] as [string, () => Promise<Metadata>, string][])(
+    "a %s title survives a malformed escape and keeps the raw segment",
+    async (_name, meta, title) => {
+      expect((await meta()).title).toBe(title);
+    },
+  );
+
   it("no title carries an em dash", async () => {
     const all = [activity, explain, ledgerImport, ledgerTrades, news, portfolio, trades, more, claude, research, universe];
     for (const m of all) expect(String(m.title)).not.toContain("—");
diff --git a/web/app/trades/[approvalId]/layout.tsx b/web/app/trades/[approvalId]/layout.tsx
index d3ea888..24ea10e 100644
--- a/web/app/trades/[approvalId]/layout.tsx
+++ b/web/app/trades/[approvalId]/layout.tsx
@@ -1,9 +1,10 @@
 import type { Metadata } from "next";
+import { decodeSegment } from "@/lib/segment";
 
 // The page is a client component, which cannot export metadata (web overhaul Part 4, ruling 23).
 export async function generateMetadata({ params }: { params: Promise<{ approvalId: string }> }): Promise<Metadata> {
   const { approvalId } = await params;
-  return { title: `Proposal ${decodeURIComponent(approvalId)}` };
+  return { title: `Proposal ${decodeSegment(approvalId)}` };
 }
 
 export default function Layout({ children }: { children: React.ReactNode }) {
diff --git a/web/lib/segment.ts b/web/lib/segment.ts
new file mode 100644
index 0000000..34974de
--- /dev/null
+++ b/web/lib/segment.ts
@@ -0,0 +1,12 @@
+/**
+ * A dynamic route segment, decoded for a page title. A malformed escape (a stray "%" in a hand-typed
+ * URL) makes `decodeURIComponent` throw, which would fail the title rather than the page; the raw
+ * segment is the honest fallback (web overhaul Part 6, from a Part 4 review nit).
+ */
+export function decodeSegment(raw: string): string {
+  try {
+    return decodeURIComponent(raw);
+  } catch {
+    return raw;
+  }
+}
````

### Task 2: The save-side tests

**Files:** Modify `web/components/options/DecideControls.test.tsx`, `web/features/position/RollCard.test.tsx`; this
plan.

**What it does (ruling 16):** two cases each: a confirmed pending command is written to storage under its subject
(`42` for an approval, `short:<symbol>` for a roll), and an open live confirmation is written with
`needs_confirmation` and its token before it is released. The components are unchanged (one is protected).

- [x] **Step 1: Check and apply `T2`.** `git status --short` shows the two test files as `M`.
- [x] **Step 2: Gate.** `cd web && npx vitest run components/options/DecideControls.test.tsx features/position/RollCard.test.tsx`:
  37 passed. Full vitest **1571 in 152 files**; tsc, lint clean; **G1 prints nothing** (the protected component did
  not change). No red check here (ruling 16: it was run in the prototype).
- [x] **Step 3: Commit** `test(web): pin that a pending decide or roll command is saved for a reload`.

<!-- block T2 -->
````diff
diff --git a/web/components/options/DecideControls.test.tsx b/web/components/options/DecideControls.test.tsx
index 0cb3cba..c32acc7 100644
--- a/web/components/options/DecideControls.test.tsx
+++ b/web/components/options/DecideControls.test.tsx
@@ -179,6 +179,42 @@ describe("DecideControls — localStorage persistence (no initialCommand, e.g. t
   });
 });
 
+describe("DecideControls - saving an in-flight command (web overhaul Part 6)", () => {
+  // The cases above restore what a test wrote to storage by hand; these pin the write itself.
+  it("saves a pending approve command under the approval id once it is confirmed", async () => {
+    localStorage.clear();
+    submitCommand.mockResolvedValueOnce({
+      id: 41, kind: "approve", status: "pending", result: null,
+      needs_confirmation: false, confirm_token: null,
+      created_at: "x", applied_at: null, as_of: "x", created: true,
+    });
+    withClient(<DecideControls approval={approval()} />);
+    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
+    fireEvent.click(dialogConfirm());
+    await screen.findByTestId("command-receipt");
+    const { loadPersistedCommand } = await import("@/lib/commands");
+    await waitFor(() => expect(loadPersistedCommand(42)).toMatchObject({ id: 41, status: "pending" }));
+  });
+
+  it("saves the open live confirmation, with its token, before it is released", async () => {
+    localStorage.clear();
+    submitCommand.mockResolvedValueOnce({
+      id: 41, kind: "approve", status: "pending", result: null,
+      needs_confirmation: true, confirm_token: "tok-abc",
+      created_at: "x", applied_at: null, as_of: "x", created: true,
+    });
+    withClient(<DecideControls approval={approval()} />);
+    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
+    fireEvent.click(dialogConfirm());
+    await screen.findAllByText(/LIVE/);
+    const { loadPersistedCommand } = await import("@/lib/commands");
+    await waitFor(() =>
+      expect(loadPersistedCommand(42)).toMatchObject({ id: 41, needs_confirmation: true, confirm_token: "tok-abc" }),
+    );
+    expect(confirmCommand).not.toHaveBeenCalled();
+  });
+});
+
 describe("DecideControls — decide controls (M3)", () => {
   it("opens ConfirmAction before any request is made", () => {
     withClient(<DecideControls approval={approval()} />);
diff --git a/web/features/position/RollCard.test.tsx b/web/features/position/RollCard.test.tsx
index 256b12b..8225296 100644
--- a/web/features/position/RollCard.test.tsx
+++ b/web/features/position/RollCard.test.tsx
@@ -5,7 +5,7 @@ import { beforeEach, describe, expect, it } from "vitest";
 // imports apiFetch (lib/commands, RollCard) resolves.
 import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
 import { ApiError } from "@/lib/api";
-import { savePersistedCommand } from "@/lib/commands";
+import { loadPersistedCommand, savePersistedCommand } from "@/lib/commands";
 import { RollCard } from "./RollCard";
 
 const SYMBOL = "AAPL  261121P00180000";
@@ -269,5 +269,26 @@ describe("RollCard - the roll flow (ported from the Shorts table)", () => {
       const dialog = await screen.findByRole("dialog");
       expect(dialog.textContent).toContain("LIVE");
     });
+
+    // The save side (web overhaul Part 6): the cases above only restore what a test wrote by hand.
+    it("saves a pending roll command under short:<symbol>, so a reload can restore it", async () => {
+      mountRoll();
+      await proposeAndConfirm();
+      await screen.findByTestId("command-receipt");
+      await waitFor(() => expect(loadPersistedCommand(`short:${SYMBOL}`)).toMatchObject({ id: 51, status: "pending" }));
+    });
+
+    it("saves an open live confirmation, needs_confirmation and its token, before it is released", async () => {
+      mountRoll({ post: async () => command({ needs_confirmation: true, confirm_token: "tok-abc" }) });
+      await proposeAndConfirm();
+      await screen.findAllByText(/LIVE/);
+      await waitFor(() =>
+        expect(loadPersistedCommand(`short:${SYMBOL}`)).toMatchObject({
+          id: 51,
+          needs_confirmation: true,
+          confirm_token: "tok-abc",
+        }),
+      );
+    });
   });
 });
````

### Task 3: The value block mounts once

**Files:** Modify `web/features/stock/StockPage.tsx`, `web/features/stock/StockPage.test.tsx`; this plan.

**What it does (ruling 4):** `valueBlock` is `null` while `GET /value/{symbol}` is pending, so the block mounts once, in
the slot the answer picks. The test stand-in for `ValueBlock` counts its mounts. Two new cases (held until the answer,
mounted once under the chart; a failed read places it at the foot); the "every list No" case waits for the block.

- [x] **Step 1: da-vinci** with the section's Spec (no visual change).
- [x] **Step 2: Check and apply `T3`.** `git status --short` shows the two files as `M`.
- [x] **Step 3: Red check.** `git stash push -- web/features/stock/StockPage.tsx`, then
  `cd web && npx vitest run features/stock/StockPage.test.tsx` ends `1 failed | 7 passed (8)` (the hold case), then
  `git stash pop`.
- [x] **Step 4: Gate.** `npx vitest run features/stock`: StockPage 8 passed. Full vitest **1573 in 152 files**; tsc,
  lint clean.
- [x] **Step 5: Commit** `fix(web): the stock page's value block mounts once, where its answer puts it`.

<!-- block T3 -->
````diff
diff --git a/web/features/stock/StockPage.test.tsx b/web/features/stock/StockPage.test.tsx
index 8cca7f5..58929c4 100644
--- a/web/features/stock/StockPage.test.tsx
+++ b/web/features/stock/StockPage.test.tsx
@@ -1,4 +1,4 @@
-import { cleanup, render, screen } from "@testing-library/react";
+import { cleanup, render, screen, waitFor } from "@testing-library/react";
 import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
 import { afterEach, describe, expect, it, vi } from "vitest";
 import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
@@ -10,9 +10,19 @@ vi.mock("@/components/stock/PriceChart", () => ({
     <div data-testid="chart">{`${symbol} chart: ${lines.map((l) => l.title).join("; ")}`}</div>
   ),
 }));
-vi.mock("@/features/stock-value/ValueBlock", () => ({
-  ValueBlock: ({ symbol }: { symbol: string }) => <section aria-label={`Value book on ${symbol}`} data-testid="value" />,
-}));
+// The stand-in counts its mounts, so a test can tell a block that moved (a remount) from one that did not.
+const valueMounts = vi.hoisted(() => ({ n: 0 }));
+vi.mock("@/features/stock-value/ValueBlock", async () => {
+  const { useEffect } = await import("react");
+  return {
+    ValueBlock: function ValueBlock({ symbol }: { symbol: string }) {
+      useEffect(() => {
+        valueMounts.n += 1;
+      }, []);
+      return <section aria-label={`Value book on ${symbol}`} data-testid="value" />;
+    },
+  };
+});
 vi.mock("@/features/market/NameNotes", () => ({ NameNotes: () => <section data-testid="notes" /> }));
 vi.mock("@/components/stock/SummaryPanel", () => ({ SummaryPanel: () => <p>summary stand-in</p> }));
 
@@ -82,10 +92,49 @@ describe("StockPage", () => {
     expect(order().slice(0, 3)).toEqual(["GOOGL price chart", "VALUE", "Checks"]);
   });
 
+  it("holds the value block until the value book answers, then mounts it once in the slot the answer picks", async () => {
+    let release: (v: unknown) => void = () => {};
+    apiFetchMock.mockImplementation(async (path: string) => {
+      if (path === "/research/GOOGL") return ANALYSIS;
+      if (path === "/value/GOOGL") return new Promise((r) => (release = r));
+      throw new Error(`unexpected fetch ${path}`);
+    });
+    valueMounts.n = 0;
+    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+    render(
+      <QueryClientProvider client={qc}>
+        <StockPage symbol="GOOGL" />
+      </QueryClientProvider>,
+    );
+    await screen.findByText("Alphabet Inc. · NASDAQ");
+    expect(screen.queryByTestId("value")).toBeNull();
+    release(VALUE_READY);
+    await waitFor(() => expect(order().slice(0, 2)).toEqual(["GOOGL price chart", "VALUE"]));
+    expect(valueMounts.n).toBe(1);
+  });
+
+  it("places the value block at the foot when the value book cannot be read", async () => {
+    apiFetchMock.mockImplementation(async (path: string) => {
+      if (path === "/research/GOOGL") return ANALYSIS;
+      throw new ApiError(500, "value.db unreadable");
+    });
+    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+    render(
+      <QueryClientProvider client={qc}>
+        <StockPage symbol="GOOGL" />
+      </QueryClientProvider>,
+    );
+    await screen.findByText("Alphabet Inc. · NASDAQ");
+    await waitFor(() => expect(screen.getByTestId("value")).toBeInTheDocument());
+    const o = order();
+    expect(o.indexOf("VALUE")).toBe(o.indexOf("Financial statements") + 1);
+  });
+
   it("puts the value block at the foot of the left column when every list is No", async () => {
     renderWithQuery(<StockPage symbol="GOOGL" />, { "/research/GOOGL": ANALYSIS, "/value/GOOGL": VALUE_NO });
     await screen.findByText("Alphabet Inc. · NASDAQ");
     expect(await screen.findByText("GOOGL chart:")).toBeInTheDocument();
+    await screen.findByTestId("value");
     const o = order();
     expect(o.indexOf("VALUE")).toBe(o.indexOf("Financial statements") + 1);
   });
diff --git a/web/features/stock/StockPage.tsx b/web/features/stock/StockPage.tsx
index 9a2b744..ff3745b 100644
--- a/web/features/stock/StockPage.tsx
+++ b/web/features/stock/StockPage.tsx
@@ -83,7 +83,7 @@ export function StockPage({ symbol }: { symbol: string }) {
     retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2,
   });
   // The value block reads the same request under the same key, so this costs no second fetch.
-  const { data: value } = useQuery({
+  const { data: value, isPending: valuePending } = useQuery({
     queryKey: ["value", "ticker", upper],
     queryFn: () => apiFetch<ValueTicker>(`/value/${upper}`),
   });
@@ -119,7 +119,10 @@ export function StockPage({ symbol }: { symbol: string }) {
     state: data?.[key]?.state ?? "pending",
     reason: data?.[key]?.reason ?? null,
   });
-  const valueBlock = <ValueBlock symbol={upper} />;
+  // Held back until GET /value/{symbol} has answered (or failed), so the block mounts once, in the
+  // slot its answer picks: before, it mounted at the foot and moved under the chart when a priced
+  // answer arrived, a layout shift and a remount (web overhaul Part 6).
+  const valueBlock = valuePending ? null : <ValueBlock symbol={upper} />;
 
   return (
     <Shell>
````

### Task 4: The position page's column and headline links

**Files:** Modify `web/features/position/PositionPage.tsx`, `web/features/position/Headlines.tsx`,
`web/features/position/PositionPage.test.tsx`; this plan.

**What it does (ruling 17):** the trade column is `grid min-w-0 grid-cols-1`; a headline link is a 44px row on a phone.

- [x] **Step 1: da-vinci** with the section's Spec (classes only).
- [x] **Step 2: Check and apply `T4`.** `git status --short` shows the three files as `M`.
- [x] **Step 3: Red check.** `git stash push -- web/features/position/PositionPage.tsx web/features/position/Headlines.tsx`,
  then `cd web && npx vitest run features/position/PositionPage.test.tsx` ends `2 failed | 15 passed (17)`, then
  `git stash pop`.
- [x] **Step 4: Gate.** `npx vitest run features/position/PositionPage.test.tsx`: 17 passed. Full vitest **1575 in 152
  files**; tsc, lint clean; G1, G2, G5.
- [x] **Step 5: Commit** `fix(web): the position page's column never widens the page; headline links are 44px on a phone`.

<!-- block T4 -->
````diff
diff --git a/web/features/position/Headlines.tsx b/web/features/position/Headlines.tsx
index ee78f4d..52c0682 100644
--- a/web/features/position/Headlines.tsx
+++ b/web/features/position/Headlines.tsx
@@ -53,7 +53,7 @@ export function Headlines({ symbol }: { symbol: string }) {
                     href={h.url}
                     target="_blank"
                     rel="noopener noreferrer"
-                    className="font-semibold underline-offset-2 hover:underline"
+                    className="flex min-h-11 items-center font-semibold underline-offset-2 hover:underline md:inline md:min-h-0"
                   >
                     {h.title}
                     <span className="sr-only"> (opens in a new tab)</span>
diff --git a/web/features/position/PositionPage.test.tsx b/web/features/position/PositionPage.test.tsx
index 33bcd7c..b9108c9 100644
--- a/web/features/position/PositionPage.test.tsx
+++ b/web/features/position/PositionPage.test.tsx
@@ -190,6 +190,18 @@ describe("PositionPage", () => {
     expect(screen.getByText("n/a")).toHaveClass("hatch"); // unknown sentiment is unknown, with texture
   });
 
+  it("makes a headline link a 44px target on a phone, inline from 768px", async () => {
+    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve());
+    const link = await screen.findByRole("link", { name: /Apple unveils a new chip/ });
+    expect(link).toHaveClass("min-h-11", "md:inline", "md:min-h-0");
+  });
+
+  it("sizes the trade column to one minmax(0,1fr) track, so a wide child never widens the page", async () => {
+    renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve());
+    const trade = await screen.findByRole("article");
+    expect(trade.parentElement).toHaveClass("grid-cols-1", "min-w-0");
+  });
+
   it("says so when there are no headlines, or they cannot load", async () => {
     const { unmount } = renderWithQuery(<PositionPage underlying="AAPL" slug={SLUG} />, serve(detail(), { "/research/AAPL/headlines": { as_of: "", symbol: "AAPL", items: [] } }));
     expect(await screen.findByText("No recent headlines for AAPL.")).toBeInTheDocument();
diff --git a/web/features/position/PositionPage.tsx b/web/features/position/PositionPage.tsx
index dab2b5d..4f3d66c 100644
--- a/web/features/position/PositionPage.tsx
+++ b/web/features/position/PositionPage.tsx
@@ -188,7 +188,9 @@ export function PositionPage({ underlying, slug }: { underlying: string; slug: s
           <UnderlyingChart symbol={symbol} lines={chartLines(data)} openedOn={openedOn(data)} onLastClose={setLastClose} />
         </div>
 
-        <div className="grid gap-4 lg:col-start-2 lg:row-span-2 lg:row-start-1">
+        {/* One minmax(0,1fr) track: a grid with no column template is sized by its widest child and
+            would widen the page on a phone (the stock page's lesson, web overhaul Parts 5 and 6). */}
+        <div className="grid min-w-0 grid-cols-1 gap-4 lg:col-start-2 lg:row-span-2 lg:row-start-1">
           {data.kind === "shares" ? (
             <SharesCard d={data} />
           ) : data.opened ? (
````

---

## Section B: Search in the shell (Tasks 5-7) · model: sonnet (effort high)

**Reads:** this section; `web/DESIGN.md` (Layout; Components: Rail and tab bar, More, Buttons, Status word; the new
Search palette paragraph is in T7's patch); `web/components/search/CommandPalette.tsx`; `web/components/shell/Rail.tsx`;
`web/app/layout.tsx`; `web/app/more/page.tsx`; `web/app/research/page.tsx`; `web/lib/nav.ts`.

**Spec for da-vinci (give it this, so it has little to decide):** the Search palette paragraph and the Rail and More
lines in T7's DESIGN.md hunk are the spec. Classes and copy are fixed by the patches: the scrim
`fixed inset-0 z-50 flex items-start justify-center bg-scrim px-4 pt-[12vh]`; the panel
`w-full max-w-xl rounded-[18px] bg-surface p-2` (no shadow); the input row (lucide `Search` 18 muted, the 16px input,
a quiet `Button` "Close" `md:hidden`); a hairline, then the groups (label `text-xs font-semibold tracking-[0.04em]
text-muted`, options `min-h-11 rounded-xl px-3 md:min-h-10`, the active one `bg-sunk`, an ETF as a neutral
`StatusWord`); the status line; the foot line "Arrow keys to move, Enter to open, Esc to close" from 768px. The rail row
`mb-3 flex items-center gap-2.5 rounded-[10px] bg-sunk px-2.5 py-2 text-sm text-muted` with `Search` 17 and a mono
`⌘K`. da-vinci may tune spacing inside those and must record each change as a ruling; it may not add a token, colour,
font, radius, shadow or lime, change copy, or change the keyboard model.

**Entry checks:**

- [x] **B1. Section A landed.** `git log --oneline main..HEAD` shows the four task commits; vitest 1575 in 152 files at
  the last gate.
- [x] **B2. The first two patches apply** (T7 edits a file T6 edits, so it is checked at its own Step 1):
  `git apply --check <S>/p6/T5.out` and `T6.out`: each prints nothing.
- [x] **B3. Nothing already named what B adds.** `ls web/features/search web/lib/search.ts` fails (no such file);
  `grep -rn "openSearch\|OPEN_SEARCH_EVENT" web/app web/components web/features web/lib` prints nothing (the shell is
  zsh: never pass an unquoted `--include=*.ts`, which zsh expands and refuses).

**Section exit:** three task commits; vitest **1593 in 153 files**; tsc, lint clean; G1, G2, G3, G4, G5, G7.

### Task 5: Pages and the open event

**Files:** Create `web/lib/search.ts`, `web/features/search/pages.ts`, `web/features/search/pages.test.ts`; this plan.

**What it does (rulings 2, 5, 7):** `PAGES` (nineteen of the console's pages, each with a hint and the words someone
might type), `matchPages(term)`, and `openSearch()`, which dispatches `ibkr:open-search`. The test also pins that every
page links to a route the console has and that no label carries an em dash.

- [x] **Step 1: Check and apply `T5`.** `git status --short` shows `?? web/features/search/` and `?? web/lib/search.ts`.
- [x] **Step 2: Gate.** `cd web && npx vitest run features/search`: 8 passed (a new module: red is "module missing").
  Full vitest **1583 in 153 files**; tsc, lint clean.
- [x] **Step 3: Commit** `feat(web): the console's pages for search, and one event that opens it`.

<!-- block T5 -->
````diff
diff --git a/web/features/search/pages.test.ts b/web/features/search/pages.test.ts
new file mode 100644
index 0000000..7346806
--- /dev/null
+++ b/web/features/search/pages.test.ts
@@ -0,0 +1,47 @@
+import { describe, expect, it, vi } from "vitest";
+import { OPEN_SEARCH_EVENT, openSearch } from "@/lib/search";
+import { PAGES, matchPages } from "./pages";
+
+describe("matchPages", () => {
+  it("finds nothing for a blank term", () => {
+    expect(matchPages("")).toEqual([]);
+    expect(matchPages("   ")).toEqual([]);
+  });
+
+  it("puts a page whose name starts with the term first", () => {
+    expect(matchPages("trad").map((p) => p.label).slice(0, 2)).toEqual(["Trades", "Trades, History"]);
+  });
+
+  it("matches a page's words, not only its name", () => {
+    expect(matchPages("regime").map((p) => p.href)).toEqual(["/more/claude"]);
+  });
+
+  it("needs every word typed, in any order", () => {
+    expect(matchPages("ledger activity").map((p) => p.href)).toEqual(["/activity?view=ledger"]);
+  });
+
+  it("ignores case and lists at most five", () => {
+    expect(matchPages("ACTIVITY").length).toBeLessThanOrEqual(5);
+    expect(matchPages("a").length).toBe(5);
+  });
+
+  it("links only to routes the console has, and never to a write", () => {
+    const routes = ["/", "/trades", "/portfolio", "/activity", "/research", "/research/universe", "/news", "/more", "/more/claude", "/explain", "/ledger/import"];
+    for (const p of PAGES) expect(routes).toContain(p.href.split("?")[0]);
+    expect(new Set(PAGES.map((p) => p.href)).size).toBe(PAGES.length);
+  });
+
+  it("carries no em dash in a label or a hint", () => {
+    for (const p of PAGES) expect(`${p.label} ${p.hint}`).not.toContain("—");
+  });
+});
+
+describe("openSearch", () => {
+  it("dispatches the one event the palette listens for", () => {
+    const seen = vi.fn();
+    window.addEventListener(OPEN_SEARCH_EVENT, seen);
+    openSearch();
+    window.removeEventListener(OPEN_SEARCH_EVENT, seen);
+    expect(seen).toHaveBeenCalledTimes(1);
+  });
+});
diff --git a/web/features/search/pages.ts b/web/features/search/pages.ts
new file mode 100644
index 0000000..65e74c1
--- /dev/null
+++ b/web/features/search/pages.ts
@@ -0,0 +1,55 @@
+/**
+ * The console's own pages, for the search palette (web overhaul Part 6, operator ruling: tickers plus
+ * the console's pages, from a fixed list in the web, no API change). Each entry is a place you can go,
+ * named as the page names itself, with the words someone might type for it.
+ */
+export type PageHit = { label: string; href: string; hint: string; words: string[] };
+
+export const PAGES: PageHit[] = [
+  { label: "Home", href: "/", hint: "Account value, pay and positions", words: ["account", "dashboard"] },
+  { label: "Trades", href: "/trades", hint: "Proposals, history and assessed", words: ["approve", "proposals"] },
+  { label: "Trades, History", href: "/trades?view=history", hint: "One day's trades", words: ["orders", "fills", "working"] },
+  { label: "Trades, Assessed", href: "/trades?view=assessed", hint: "Every contract the last scan looked at", words: ["scan", "candidates", "promote"] },
+  { label: "Trades, Credit spreads", href: "/trades?strategy=spread", hint: "The day's spreads by book", words: ["spreads", "spy", "picks"] },
+  { label: "Portfolio", href: "/portfolio", hint: "Positions by name", words: ["positions", "holdings", "account"] },
+  { label: "Portfolio, Campaigns", href: "/portfolio?view=campaigns", hint: "Each wheel from first put", words: ["wheel", "campaign"] },
+  { label: "Portfolio, Calendar", href: "/portfolio?view=calendar", hint: "What expires when", words: ["expiry", "expiries"] },
+  { label: "Activity, Pay", href: "/activity", hint: "A month's pay as a stub", words: ["income", "pnl", "month"] },
+  { label: "Activity, Ledger", href: "/activity?view=ledger", hint: "IBKR's trades and per-ticker roll-ups", words: ["broker", "trades"] },
+  { label: "Activity, Fills and orders", href: "/activity?view=fills", hint: "Orders, fills and executions", words: ["orders", "executions", "fills"] },
+  { label: "Activity, System", href: "/activity?view=system", hint: "Sizing record and score against outcome", words: ["sizing", "score"] },
+  { label: "Research", href: "/research", hint: "Top opportunities, your watchlist, sectors", words: ["value", "watchlist", "sectors"] },
+  { label: "Universe", href: "/research/universe", hint: "The names the scan covers", words: ["would own", "watchlist", "scan"] },
+  { label: "News", href: "/news", hint: "Feed and calendar", words: ["headlines", "earnings", "calendar"] },
+  { label: "What Claude knows", href: "/more/claude", hint: "The market picture and what each call reads", words: ["regime", "picture", "limits"] },
+  { label: "How it works", href: "/explain", hint: "The pipeline in plain English", words: ["explain", "help"] },
+  { label: "Import a statement", href: "/ledger/import", hint: "Upload an IBKR activity CSV", words: ["csv", "upload"] },
+  { label: "More", href: "/more", hint: "Bot, theme, income target, system status", words: ["settings", "halt", "target", "theme"] },
+];
+
+const MAX_PAGES = 5;
+
+/**
+ * The pages whose name or words contain every word typed (case ignored), best first: a name that
+ * starts with the term, then a name that contains it, then a match on the words alone. A blank term
+ * finds nothing, as the ticker search does.
+ */
+export function matchPages(term: string, pages: PageHit[] = PAGES): PageHit[] {
+  const q = term.trim().toLowerCase();
+  if (!q) return [];
+  const parts = q.split(/\s+/);
+  const rank = (p: PageHit): number => {
+    const label = p.label.toLowerCase();
+    const all = [label, p.hint.toLowerCase(), ...p.words].join(" ");
+    if (!parts.every((w) => all.includes(w))) return -1;
+    if (label.startsWith(q)) return 0;
+    if (label.includes(q)) return 1;
+    return 2;
+  };
+  return pages
+    .map((p, i) => ({ p, i, r: rank(p) }))
+    .filter((x) => x.r >= 0)
+    .sort((a, b) => a.r - b.r || a.i - b.i)
+    .slice(0, MAX_PAGES)
+    .map((x) => x.p);
+}
diff --git a/web/lib/search.ts b/web/lib/search.ts
new file mode 100644
index 0000000..f956d9b
--- /dev/null
+++ b/web/lib/search.ts
@@ -0,0 +1,10 @@
+/**
+ * The console's one search palette is mounted once, in the root layout (web overhaul Part 6). Anything
+ * that offers search (the rail, More, Research) opens it through this event instead of mounting a
+ * second palette, so ⌘K and every Search button reach the same dialog.
+ */
+export const OPEN_SEARCH_EVENT = "ibkr:open-search";
+
+export function openSearch(): void {
+  window.dispatchEvent(new Event(OPEN_SEARCH_EVENT));
+}
````

### Task 6: The palette

**Files:** Rewrite `web/components/search/CommandPalette.tsx` and its test in place; modify
`web/app/research/page.test.tsx` (one placeholder regex); this plan.

**What it does (rulings 5-8):** the palette described in the Spec: a combobox over Pages (from `matchPages`) and
Tickers (`GET /research/search`, debounced 200 ms, an answer kept per term so a stale one never shows), the arrow keys,
Enter, Escape, a tap on the scrim, Close on a phone, the status line, the `openSearch` event. The ⌘K toggle, the focus
return, the Tab trap and the controlled props are kept. Seventeen cases.

- [ ] **Step 1: da-vinci** with the Spec above.
- [ ] **Step 2: Check and apply `T6`.** `git status --short` shows the three files as `M`.
- [ ] **Step 3: Red check.** `git stash push -- web/components/search/CommandPalette.tsx`, then
  `cd web && npx vitest run components/search` ends `12 failed | 5 passed (17)`, then `git stash pop`.
- [ ] **Step 4: Gate.** `npx vitest run components/search app/research`: 17 + 3 passed. Full vitest **1591 in 153
  files**; tsc, lint clean; G5.
- [ ] **Step 5: Commit** `feat(web): the search palette finds pages and tickers, by keyboard or touch`.

<!-- block T6 -->
````diff
diff --git a/web/app/research/page.test.tsx b/web/app/research/page.test.tsx
index 29e83af..fe08ca9 100644
--- a/web/app/research/page.test.tsx
+++ b/web/app/research/page.test.tsx
@@ -29,9 +29,9 @@ describe("Home — visible search bar", () => {
 
   it("opens the same command palette as ⌘K when clicked", () => {
     withClient(<Home />);
-    expect(screen.queryByPlaceholderText(/search a ticker or company/i)).toBeNull();
+    expect(screen.queryByPlaceholderText(/search a ticker, company or page/i)).toBeNull();
     fireEvent.click(screen.getByRole("button", { name: /search a ticker/i }));
-    expect(screen.getByPlaceholderText(/search a ticker or company/i)).toBeDefined();
+    expect(screen.getByPlaceholderText(/search a ticker, company or page/i)).toBeDefined();
   });
 
   it("puts Top opportunities above the watchlist", () => {
diff --git a/web/components/search/CommandPalette.test.tsx b/web/components/search/CommandPalette.test.tsx
index 849a9f8..8c6231b 100644
--- a/web/components/search/CommandPalette.test.tsx
+++ b/web/components/search/CommandPalette.test.tsx
@@ -1,21 +1,33 @@
-import { fireEvent, render, screen, waitFor } from "@testing-library/react";
+import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
 import { describe, expect, it, vi, beforeEach } from "vitest";
+import { apiFetch } from "@/lib/api";
+import { openSearch } from "@/lib/search";
 import { CommandPalette } from "./CommandPalette";
 
 vi.mock("@/lib/api", () => ({
-  apiFetch: vi.fn(async () => ({
+  apiFetch: vi.fn(async (path: string) => ({
     as_of: "2026-09-02T00:00:00Z",
-    query: "AAP",
-    results: [
-      { symbol: "AAP", name: "Advance Auto Parts", exchange: "NYSE", is_etf: false },
-      { symbol: "AAPL", name: "Apple Inc.", exchange: "Nasdaq", is_etf: false },
-    ],
+    query: path,
+    results: path.includes("q=AAP")
+      ? [
+          { symbol: "AAP", name: "Advance Auto Parts", exchange: "NYSE", is_etf: false },
+          { symbol: "AAPL", name: "Apple Inc.", exchange: "Nasdaq", is_etf: false },
+        ]
+      : path.includes("q=SPY")
+        ? [{ symbol: "SPY", name: "SPDR S&P 500 ETF", exchange: "NYSE Arca", is_etf: true }]
+        : [],
   })),
 }));
 
 const push = vi.fn();
 vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
 
+const input = () => screen.getByRole("combobox", { name: "Search a ticker, company or page" });
+
+function openWithShortcut() {
+  fireEvent.keyDown(window, { key: "k", metaKey: true });
+}
+
 describe("CommandPalette", () => {
   beforeEach(() => push.mockClear());
 
@@ -24,42 +36,112 @@ describe("CommandPalette", () => {
     expect(screen.queryByPlaceholderText(/search/i)).toBeNull();
   });
 
-  it("opens on meta+k", () => {
+  it("opens on meta+k and on ctrl+k", () => {
+    const { unmount } = render(<CommandPalette />);
+    openWithShortcut();
+    expect(screen.getByPlaceholderText(/search/i)).toBeDefined();
+    unmount();
     render(<CommandPalette />);
-    fireEvent.keyDown(window, { key: "k", metaKey: true });
+    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
     expect(screen.getByPlaceholderText(/search/i)).toBeDefined();
   });
 
-  it("shows results and navigates on select", async () => {
+  it("opens when anything calls openSearch(), so the rail, More and Research reach this one dialog", () => {
     render(<CommandPalette />);
-    fireEvent.keyDown(window, { key: "k", metaKey: true });
-    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: "AAP" } });
+    act(() => openSearch());
+    expect(input()).toHaveFocus();
+  });
+
+  it("shows ticker results and navigates on select", async () => {
+    render(<CommandPalette />);
+    openWithShortcut();
+    fireEvent.change(input(), { target: { value: "AAP" } });
     await waitFor(() => expect(screen.getByText("Apple Inc.")).toBeDefined());
     fireEvent.click(screen.getByText("Apple Inc."));
     expect(push).toHaveBeenCalledWith("/stock/AAPL");
   });
 
+  it("lists the console's pages above the tickers, and opens a page", async () => {
+    render(<CommandPalette />);
+    openWithShortcut();
+    fireEvent.change(input(), { target: { value: "trades" } });
+    const pages = screen.getByRole("group", { name: "Pages" });
+    expect(pages).toHaveTextContent("Trades");
+    fireEvent.click(screen.getAllByRole("option")[0]!);
+    expect(push).toHaveBeenCalledWith("/trades");
+  });
+
+  it("marks an ETF in words", async () => {
+    render(<CommandPalette />);
+    openWithShortcut();
+    fireEvent.change(input(), { target: { value: "SPY" } });
+    expect(await screen.findByText("ETF")).toBeInTheDocument();
+  });
+
+  it("moves through the results with the arrow keys and opens the active one with Enter", async () => {
+    render(<CommandPalette />);
+    openWithShortcut();
+    fireEvent.change(input(), { target: { value: "AAP" } });
+    await screen.findByText("Apple Inc.");
+    const options = screen.getAllByRole("option");
+    expect(options[0]).toHaveAttribute("aria-selected", "true");
+    expect(input()).toHaveAttribute("aria-activedescendant", options[0]!.id);
+    fireEvent.keyDown(input(), { key: "ArrowDown" });
+    expect(input()).toHaveAttribute("aria-activedescendant", options[1]!.id);
+    fireEvent.keyDown(input(), { key: "ArrowDown" });
+    expect(input()).toHaveAttribute("aria-activedescendant", options[0]!.id);
+    fireEvent.keyDown(input(), { key: "ArrowUp" });
+    fireEvent.keyDown(input(), { key: "Enter" });
+    expect(push).toHaveBeenCalledWith("/stock/AAPL");
+  });
+
+  it("says nothing matches only once the search has answered", async () => {
+    render(<CommandPalette />);
+    openWithShortcut();
+    expect(screen.getByRole("status")).toHaveTextContent("Type a ticker, a company or a page.");
+    fireEvent.change(input(), { target: { value: "zzzz" } });
+    expect(screen.getByRole("status")).toHaveTextContent("");
+    expect(await screen.findByText('No ticker or page matches "zzzz".')).toBeInTheDocument();
+  });
+
+  it("says the ticker search failed in words, and still lists the pages", async () => {
+    vi.mocked(apiFetch).mockRejectedValueOnce(new Error("down"));
+    render(<CommandPalette />);
+    openWithShortcut();
+    fireEvent.change(input(), { target: { value: "news" } });
+    expect(await screen.findByText("Tickers could not be searched right now.")).toBeInTheDocument();
+    expect(screen.getByRole("group", { name: "Pages" })).toHaveTextContent("News");
+  });
+
+  it("closes on a tap on the scrim and on Close, which a phone has instead of Escape", () => {
+    render(<CommandPalette />);
+    openWithShortcut();
+    fireEvent.mouseDown(screen.getByTestId("search-scrim"));
+    expect(screen.queryByRole("dialog")).toBeNull();
+    openWithShortcut();
+    fireEvent.mouseDown(screen.getByRole("dialog"));
+    expect(screen.getByRole("dialog")).toBeInTheDocument();
+    fireEvent.click(screen.getByRole("button", { name: "Close" }));
+    expect(screen.queryByRole("dialog")).toBeNull();
+  });
+
   it("renders as a labelled dialog", () => {
     render(<CommandPalette />);
-    fireEvent.keyDown(window, { key: "k", metaKey: true });
-    const dialog = screen.getByRole("dialog");
+    openWithShortcut();
+    const dialog = screen.getByRole("dialog", { name: "Search the console" });
     expect(dialog.getAttribute("aria-modal")).toBe("true");
-    expect(dialog.hasAttribute("aria-labelledby")).toBe(true);
   });
 
   it("clears the search term and results on reopen, not stale from last time", async () => {
-    // Regression: the component never unmounts on close (it renders `null`,
-    // not a conditional mount), so term/hits used to persist across a
-    // close/reopen — reopening showed the previous search.
     render(<CommandPalette />);
-    fireEvent.keyDown(window, { key: "k", metaKey: true });
-    fireEvent.change(screen.getByPlaceholderText(/search/i), { target: { value: "AAP" } });
+    openWithShortcut();
+    fireEvent.change(input(), { target: { value: "AAP" } });
     await waitFor(() => expect(screen.getByText("Apple Inc.")).toBeDefined());
 
     fireEvent.keyDown(window, { key: "Escape" });
-    fireEvent.keyDown(window, { key: "k", metaKey: true });
+    openWithShortcut();
 
-    expect((screen.getByPlaceholderText(/search/i) as HTMLInputElement).value).toBe("");
+    expect((input() as HTMLInputElement).value).toBe("");
     expect(screen.queryByText("Apple Inc.")).toBeNull();
   });
 
@@ -72,17 +154,22 @@ describe("CommandPalette", () => {
     );
     const trigger = screen.getByRole("button", { name: "Trigger" });
     trigger.focus();
-    expect(document.activeElement).toBe(trigger);
-
-    fireEvent.keyDown(window, { key: "k", metaKey: true });
-    expect(screen.getByPlaceholderText(/search/i)).toBeDefined();
-
+    openWithShortcut();
+    expect(input()).toHaveFocus();
     fireEvent.keyDown(window, { key: "Escape" });
     expect(document.activeElement).toBe(trigger);
   });
+
+  it("carries no em dash in what it says", async () => {
+    render(<CommandPalette />);
+    openWithShortcut();
+    fireEvent.change(input(), { target: { value: "zzzz" } });
+    await screen.findByText('No ticker or page matches "zzzz".');
+    expect(screen.getByRole("dialog").textContent).not.toContain("—");
+  });
 });
 
-describe("CommandPalette — controlled open (visible search bar trigger)", () => {
+describe("CommandPalette, controlled open", () => {
   it("renders open when the open prop is true, with no shortcut needed", () => {
     render(<CommandPalette open onOpenChange={() => {}} />);
     expect(screen.getByPlaceholderText(/search/i)).toBeDefined();
@@ -99,4 +186,4 @@ describe("CommandPalette — controlled open (visible search bar trigger)", () =
     fireEvent.keyDown(window, { key: "Escape" });
     expect(onOpenChange).toHaveBeenCalledWith(false);
   });
-});
\ No newline at end of file
+});
diff --git a/web/components/search/CommandPalette.tsx b/web/components/search/CommandPalette.tsx
index 8896631..5ef1c76 100644
--- a/web/components/search/CommandPalette.tsx
+++ b/web/components/search/CommandPalette.tsx
@@ -1,27 +1,39 @@
 "use client";
 
-import { useEffect, useId, useRef, useState } from "react";
+import clsx from "clsx";
+import { Search } from "lucide-react";
+import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
 import { useRouter } from "next/navigation";
+import { Button } from "@/components/ui/Button";
+import { StatusWord } from "@/components/ui/StatusWord";
+import { matchPages } from "@/features/search/pages";
 import { apiFetch } from "@/lib/api";
+import { OPEN_SEARCH_EVENT } from "@/lib/search";
 
 type Hit = { symbol: string; name: string; exchange: string | null; is_etf: boolean };
 type SearchResponse = { as_of: string; query: string; results: Hit[] };
 
+/** One row of the list: a page of the console or a ticker's stock page. */
+type Option = { key: string; group: "Pages" | "Tickers"; href: string; title: string; sub: string; etf: boolean };
+
+/** What the ticker search last answered, for the term it answered (so a stale answer is never shown). */
+type Answer = { term: string; hits: Hit[]; failed: boolean };
+
 /**
- * Controlled if `open`/`onOpenChange` are passed (the visible search-bar
- * trigger on the home page owns the state so it can open the same modal);
- * otherwise falls back to managing its own state so ⌘K keeps working
- * anywhere the palette is mounted without a parent wiring it up.
+ * The console's search (web overhaul Part 6): one dialog, mounted once in the root layout, that finds
+ * a ticker (`GET /research/search`, a pick opens `/stock/SYM`) or one of the console's own pages
+ * (`features/search/pages.ts`, no request). ⌘K or Ctrl+K toggles it anywhere; the rail, More and
+ * Research open it through `openSearch()` (`lib/search.ts`). Pages are listed above tickers.
+ *
+ * The input is a combobox: the arrow keys move through the results, Enter opens the active one, Escape
+ * closes, and a tap on the scrim or Close (phones) closes. It reads and navigates; it sends nothing.
  *
- * Never unmounts on close (it renders `null`, same component instance stays
- * mounted so the global ⌘K listener keeps working) — so unlike
- * `ConfirmAction` (which returns focus to the trigger via an unmount
- * cleanup), this component watches `open` itself: on the true->false edge it
- * clears the search term/results (reopening starts fresh, never shows a
- * stale search from last time) and returns focus to whatever had it when the
- * palette opened. `role="dialog"`/`aria-modal`/a Tab focus trap mirror
- * `ConfirmAction`'s pattern — every overlay in this app traps focus and
- * returns it on close, this one is no exception.
+ * Controlled if `open`/`onOpenChange` are passed, otherwise it keeps its own state. It never unmounts on
+ * close (it renders `null`), so the shortcut and the open event keep working; it watches the open edge
+ * itself instead: on close it clears the search (reopening starts fresh) and returns focus to whatever
+ * had it when it opened. The input is focused imperatively in that same effect, after the capture, not
+ * with `autoFocus` (which would steal focus before the trigger could be remembered). Tab is trapped
+ * inside, as `ConfirmAction` traps it.
  */
 export function CommandPalette({
   open: openProp,
@@ -35,12 +47,15 @@ export function CommandPalette({
   const open = openProp ?? internalOpen;
   const setOpen = onOpenChange ?? setInternalOpen;
   const [term, setTerm] = useState("");
-  const [hits, setHits] = useState<Hit[]>([]);
+  const [answer, setAnswer] = useState<Answer | null>(null);
+  const [active, setActive] = useState(0);
   const dialogRef = useRef<HTMLDivElement>(null);
   const inputRef = useRef<HTMLInputElement>(null);
   const triggerRef = useRef<Element | null>(null);
   const wasOpen = useRef(false);
-  const labelId = useId();
+  const titleId = useId();
+  const inputId = useId();
+  const listId = useId();
 
   useEffect(() => {
     const onKey = (e: KeyboardEvent) => {
@@ -50,32 +65,30 @@ export function CommandPalette({
       }
       if (e.key === "Escape" && open) setOpen(false);
     };
+    const onOpen = () => setOpen(true);
     window.addEventListener("keydown", onKey);
-    return () => window.removeEventListener("keydown", onKey);
+    window.addEventListener(OPEN_SEARCH_EVENT, onOpen);
+    return () => {
+      window.removeEventListener("keydown", onKey);
+      window.removeEventListener(OPEN_SEARCH_EVENT, onOpen);
+    };
   }, [open, setOpen]);
 
-  // The open/close edges: remember the trigger and focus the input on open,
-  // reset the search and return focus to the trigger on close. Deliberately
-  // NOT the native `autoFocus` prop on the input: that attribute focuses the
-  // input during React's DOM-mutation commit, which runs BEFORE this effect —
-  // by the time this effect could read `document.activeElement` to capture
-  // the trigger, autoFocus would have already overwritten it with the input
-  // itself. Focusing the input imperatively here, in the same effect and
-  // strictly after the capture, keeps the ordering correct.
   useEffect(() => {
     if (open && !wasOpen.current) {
       triggerRef.current = document.activeElement;
       inputRef.current?.focus();
     } else if (!open && wasOpen.current) {
       setTerm("");
-      setHits([]);
+      setAnswer(null);
+      setActive(0);
       const trigger = triggerRef.current;
       if (trigger instanceof HTMLElement) trigger.focus();
     }
     wasOpen.current = open;
   }, [open]);
 
-  // Tab focus trap, active only while open — mirrors ConfirmAction exactly.
+  // Tab focus trap, active only while open, as ConfirmAction's.
   useEffect(() => {
     if (!open) return;
     function onKeyDown(e: KeyboardEvent) {
@@ -101,18 +114,14 @@ export function CommandPalette({
   }, [open]);
 
   useEffect(() => {
-    if (!term.trim()) {
-      setHits([]);
-      return;
-    }
+    const q = term.trim();
+    if (!q) return;
     const id = setTimeout(async () => {
       try {
-        const data = await apiFetch<SearchResponse>(
-          `/research/search?q=${encodeURIComponent(term)}`,
-        );
-        setHits(data.results);
+        const data = await apiFetch<SearchResponse>(`/research/search?q=${encodeURIComponent(q)}`);
+        setAnswer({ term: q, hits: data.results, failed: false });
       } catch {
-        setHits([]);
+        setAnswer({ term: q, hits: [], failed: true });
       }
     }, 200);
     return () => clearTimeout(id);
@@ -120,48 +129,133 @@ export function CommandPalette({
 
   if (!open) return null;
 
+  const q = term.trim();
+  const current = answer !== null && answer.term === q ? answer : null;
+  const options: Option[] = [
+    ...matchPages(q).map((p): Option => ({ key: `page:${p.href}`, group: "Pages", href: p.href, title: p.label, sub: p.hint, etf: false })),
+    ...(current?.hits ?? []).map((h): Option => ({
+      key: `ticker:${h.symbol}`,
+      group: "Tickers",
+      href: `/stock/${h.symbol}`,
+      title: h.symbol,
+      sub: h.name,
+      etf: h.is_etf,
+    })),
+  ];
+  const activeIndex = options.length === 0 ? -1 : Math.min(active, options.length - 1);
+  const optionId = (i: number) => `${listId}-${i}`;
+
+  function go(o: Option) {
+    setOpen(false);
+    router.push(o.href);
+  }
+
+  function onInputKey(e: ReactKeyboardEvent<HTMLInputElement>) {
+    if (options.length === 0) return;
+    if (e.key === "ArrowDown") {
+      e.preventDefault();
+      setActive((activeIndex + 1) % options.length);
+    } else if (e.key === "ArrowUp") {
+      e.preventDefault();
+      setActive((activeIndex - 1 + options.length) % options.length);
+    } else if (e.key === "Enter" && activeIndex >= 0) {
+      e.preventDefault();
+      go(options[activeIndex]!);
+    }
+  }
+
+  let status: string | null = null;
+  if (!q) status = "Type a ticker, a company or a page.";
+  else if (current?.failed) status = "Tickers could not be searched right now.";
+  else if (current && options.length === 0) status = `No ticker or page matches "${q}".`;
+
+  const groups = (["Pages", "Tickers"] as const)
+    .map((g) => ({ g, rows: options.map((o, i) => ({ o, i })).filter((x) => x.o.group === g) }))
+    .filter((x) => x.rows.length > 0);
+
   return (
     <div
-      ref={dialogRef}
-      role="dialog"
-      aria-modal="true"
-      aria-labelledby={labelId}
-      className="fixed inset-0 z-50 flex items-start justify-center bg-scrim pt-[15vh]"
+      className="fixed inset-0 z-50 flex items-start justify-center bg-scrim px-4 pt-[12vh]"
+      onMouseDown={(e) => {
+        if (e.target === e.currentTarget) setOpen(false);
+      }}
+      data-testid="search-scrim"
     >
-      <div className="w-full max-w-xl rounded-lg bg-elevated p-2">
-        <label htmlFor={labelId} className="sr-only">
-          Search a ticker or company
-        </label>
-        <input
-          id={labelId}
-          ref={inputRef}
-          value={term}
-          onChange={(e) => setTerm(e.target.value)}
-          placeholder="Search a ticker or company"
-          className="w-full bg-transparent px-3 py-2 font-mono text-sm text-content outline-none placeholder:text-muted"
-        />
-        <ul className="max-h-80 overflow-y-auto">
-          {hits.map((h) => (
-            <li key={h.symbol}>
-              <button
-                type="button"
-                onClick={() => {
-                  setOpen(false);
-                  router.push(`/stock/${h.symbol}`);
-                }}
-                className="flex w-full items-baseline gap-3 rounded px-3 py-2 text-left hover:bg-surface focus-visible:bg-surface"
-              >
-                <span className="tabular font-mono text-sm text-content">{h.symbol}</span>
-                <span className="truncate text-sm text-muted">{h.name}</span>
-                {h.is_etf && <span className="ml-auto text-[11px] text-muted">ETF</span>}
-              </button>
-            </li>
-          ))}
-          {term.trim() && hits.length === 0 && (
-            <li className="px-3 py-2 text-sm text-muted">No match</li>
-          )}
-        </ul>
+      <div
+        ref={dialogRef}
+        role="dialog"
+        aria-modal="true"
+        aria-labelledby={titleId}
+        className="w-full max-w-xl rounded-[18px] bg-surface p-2"
+      >
+        <h2 id={titleId} className="sr-only">
+          Search the console
+        </h2>
+        <div className="flex items-center gap-2 px-2">
+          <Search aria-hidden="true" size={18} className="shrink-0 text-muted" />
+          <label htmlFor={inputId} className="sr-only">
+            Search a ticker, company or page
+          </label>
+          <input
+            id={inputId}
+            ref={inputRef}
+            value={term}
+            onChange={(e) => {
+              setTerm(e.target.value);
+              setActive(0);
+            }}
+            onKeyDown={onInputKey}
+            placeholder="Search a ticker, company or page"
+            role="combobox"
+            aria-expanded={options.length > 0}
+            aria-controls={listId}
+            aria-autocomplete="list"
+            aria-activedescendant={activeIndex >= 0 ? optionId(activeIndex) : undefined}
+            autoComplete="off"
+            spellCheck={false}
+            className="min-h-11 w-full rounded-lg bg-transparent px-1 text-base text-content placeholder:text-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-focus"
+          />
+          <Button variant="quiet" className="shrink-0 md:hidden" onClick={() => setOpen(false)}>
+            Close
+          </Button>
+        </div>
+        <div className="border-t border-border">
+          <div id={listId} role="listbox" aria-label="Results" className="max-h-[60vh] overflow-y-auto py-1">
+            {groups.map(({ g, rows }) => (
+              <div key={g} role="group" aria-labelledby={`${listId}-${g}`}>
+                <div id={`${listId}-${g}`} className="px-3 pb-1 pt-2 text-xs font-semibold tracking-[0.04em] text-muted">
+                  {g}
+                </div>
+                {rows.map(({ o, i }) => (
+                  <div
+                    key={o.key}
+                    id={optionId(i)}
+                    role="option"
+                    aria-selected={i === activeIndex}
+                    onMouseMove={() => setActive(i)}
+                    onClick={() => go(o)}
+                    className={clsx(
+                      "flex min-h-11 cursor-pointer items-center gap-3 rounded-xl px-3 md:min-h-10",
+                      i === activeIndex && "bg-sunk",
+                    )}
+                  >
+                    <span className={clsx("shrink-0 font-semibold", o.group === "Tickers" && "tabular")}>{o.title}</span>
+                    <span className="min-w-0 flex-1 truncate text-sm text-muted">{o.sub}</span>
+                    {o.etf && <StatusWord>ETF</StatusWord>}
+                  </div>
+                ))}
+              </div>
+            ))}
+          </div>
+          {/* Always mounted, so a screen reader hears each change of the line. */}
+          <p role="status" className={clsx("px-3 text-sm text-muted", status && "py-2")}>
+            {status}
+          </p>
+          <p className="hidden px-3 pb-1 pt-2 text-xs text-muted md:block">
+            Arrow keys to move, Enter to open, Esc to close
+          </p>
+        </div>
       </div>
     </div>
   );
-}
\ No newline at end of file
+}
````

### Task 7: The palette in the shell

**Files:** Modify `web/app/layout.tsx`, `web/lib/nav.ts`, `web/components/shell/Rail.tsx` (+ test),
`web/app/more/page.tsx` (+ test), `web/app/research/page.tsx` (+ test), `web/DESIGN.md`; this plan.

**What it does (rulings 5, 9):** `<CommandPalette />` once in the root layout; the rail's Search row; Research's icon a
telescope; More's Search row first in its links card (the first link row gains a top hairline); Research's button calls
`openSearch` and the page no longer mounts a palette. DESIGN.md: the Search palette paragraph, the Rail and More lines.

- [ ] **Step 1: da-vinci** with the Spec above.
- [ ] **Step 2: Check and apply `T7`.** `git status --short` shows nine `M` files.
- [ ] **Step 3: Red check.** `git stash push -- web/components/shell/Rail.tsx web/app/more/page.tsx web/app/research/page.tsx`,
  then `cd web && npx vitest run components/shell/Rail.test.tsx app/more app/research` ends `3 failed | 12 passed (15)`,
  then `git stash pop`.
- [ ] **Step 4: Gate.** `npx vitest run components/shell app/more app/research app/titles.test.ts lib/nav.test.ts`: 89
  passed. Full vitest **1593 in 153 files**; tsc, lint clean; G1, G2, G3 exit 0, G4 green (route table as G4 says), G5,
  **G7 prints exactly the layout line**.
- [ ] **Step 5: Commit** `feat(web): search from anywhere: one palette in the shell, a Search row in the rail and on More`.

<!-- block T7 -->
````diff
diff --git a/web/DESIGN.md b/web/DESIGN.md
index 76235e8..33d7038 100644
--- a/web/DESIGN.md
+++ b/web/DESIGN.md
@@ -453,12 +453,14 @@ the not-draining warning sits above the controls. The same exception as the revi
 state also shows a full-width flag banner on every page, worded for the wheel ("Wheel trading is
 halted"), since credit spreads have their own halt.
 
-**Rail and tab bar**: the 200px white rail lists the seven destinations with an ink-on-sage
-current row and the lime pending count on Trades; the phone tab bar (64px, white, hairline above)
+**Rail and tab bar**: the 200px white rail opens with the wordmark, then a pressed-sage **Search** row
+(the magnifier, "Search" and a muted "⌘K") that opens the search palette, then the seven destinations
+with an ink-on-sage current row and the lime pending count on Trades (Research's icon is a telescope, so
+the magnifier means search alone); the phone tab bar (64px, white, hairline above)
 holds Home, Trades, Portfolio, Activity and More, and marks More current on Research, Universe,
 stock and News pages, which a phone reaches through More.
 
-**More**: the bot card, the theme toggle (Light, Dark, Follow OS, on the strategy-switch track), the income target card, links to Research, Universe, News, Ledger, How it works, What Claude knows and statement import, system status, and Credits (the chart library's licence link).
+**More**: the bot card, the theme toggle (Light, Dark, Follow OS, on the strategy-switch track), the income target card, a Search row first in the links card (a phone has no rail and no shortcut), links to Research, Universe, News, Ledger, How it works, What Claude knows and statement import, system status, and Credits (the chart library's licence link).
 
 **Regime and limits card** (What Claude knows): "Regime and limits", with when it was recorded at the right of the title. Per index (SPY, QQQ) a heading, the regime as a status word (flag amber above normal, neutral at normal), one plain line (the daily base, what raised it today, a bottoming-signal ease, or "Matches the daily base") and the CSP limits as figure lines under a perforation: Budget and Per trade as a percent of the normal limit, New puts a day ("No limit" or the count), Guaranteed lots a day. Up to three flag lines come first when they apply, each a flag word with one sentence beside it, in this order: "Off in config", "Suspended today" (`/regime off`, the limits shown are not applied) and "Cuts paused today" (today's circuit breaker has tripped: "The circuit breaker tripped, so Claude's size cuts are recorded but not applied until tomorrow"). Below the indices, the leveraged-ETF ceilings grouped by multiple ("3x (TQQQ, SOXL): 60% of the regime's size when calm, 30% when the name or its market is under stress") and Claude's size cuts as a sentence ("applied (paper)", "recorded only (live)"). When today's circuit breaker has tripped (Claude zeroed most of the day's auto puts) the cut sentence says so itself ("applied (paper), paused today.") so it is true when read alone, and the flag line above carries the state. The breaker is a flag word, not a plain sentence: it is the one state on the card besides `/regime off` that changes what happens today, so it joins that stack, in the first screen at phone width, instead of sitting below both indices. What the limits mean sits in a closed plain Disclosure. No regime yet: "No regime recorded yet" with a hatched n/a.
 
@@ -664,6 +666,20 @@ that is wider than a phone scrolls inside its own card and says "Scroll sideways
 phone, and a chart names each series in words. The pages lead back to Activity, Ledger with a back link in
 place of a sub-navigation.
 
+**Search palette** (the whole console, web overhaul Part 6): one dialog, mounted once in the root layout,
+opened by ⌘K or Ctrl+K anywhere and by the rail's Search row, More's Search row and Research's Search button.
+A white 18px panel at most 576px wide, 12vh from the top over the scrim (no shadow: the scrim does the
+lifting), with 16px gutters on a phone. The input row is the magnifier, a 16px input ("Search a ticker,
+company or page", so iOS does not zoom) and, on a phone, a quiet Close. Under a hairline, the results in two
+labelled groups, **Pages** first (the console's own pages from a fixed list in the web: "Trades, History",
+"Activity, Ledger", "What Claude knows" ..., at most five) then **Tickers** (`GET /research/search`, the
+symbol bold and the company muted, "ETF" as a neutral status word); each row is 44px on a phone and 40px from
+768px, and the active one is pressed sage. The arrow keys move, Enter opens, Escape or a tap on the scrim
+closes, focus goes back where it was. One status line says what is going on in words: "Type a ticker, a
+company or a page.", "No ticker or page matches "xyz"." (only once the search has answered), "Tickers could
+not be searched right now." (pages still listed). A muted foot line from 768px names the keys. It reads and
+navigates; it sends nothing. No lime.
+
 **Not-found and error pages** (the whole console, web overhaul Part 4): one `not-found.tsx` and one `error.tsx` at
 the root, each a single Card on the 720px page frame. The words are fixed. Not found: "This page does not exist",
 "The address may be old or mistyped. Nothing was changed.", and one secondary pill link to Home. Error: "This page
diff --git a/web/app/layout.tsx b/web/app/layout.tsx
index d647b38..d3dd840 100644
--- a/web/app/layout.tsx
+++ b/web/app/layout.tsx
@@ -1,6 +1,7 @@
 import type { Metadata } from "next";
 import { Hanken_Grotesk, Red_Hat_Mono } from "next/font/google";
 import "./globals.css";
+import { CommandPalette } from "@/components/search/CommandPalette";
 import { HaltedBanner } from "@/components/shell/HaltedBanner";
 import { Rail } from "@/components/shell/Rail";
 import { TabBar } from "@/components/shell/TabBar";
@@ -50,6 +51,8 @@ export default function RootLayout({ children }: { children: React.ReactNode })
             </div>
             <TabBar />
           </div>
+          {/* The console's one search dialog: ⌘K anywhere, and openSearch() from the rail, More and Research. */}
+          <CommandPalette />
         </Providers>
       </body>
     </html>
diff --git a/web/app/more/page.test.tsx b/web/app/more/page.test.tsx
index 3b9c6df..188fa78 100644
--- a/web/app/more/page.test.tsx
+++ b/web/app/more/page.test.tsx
@@ -1,6 +1,7 @@
 import { fireEvent, screen } from "@testing-library/react";
-import { describe, expect, it } from "vitest";
+import { describe, expect, it, vi } from "vitest";
 import { renderWithQuery } from "@/lib/test-query";
+import { OPEN_SEARCH_EVENT } from "@/lib/search";
 import { THEME_STORAGE_KEY } from "@/lib/theme";
 import MorePage from "./page";
 
@@ -38,6 +39,14 @@ describe("More page", () => {
     expect(screen.getByRole("link", { name: /News/ })).toHaveAttribute("href", "/news");
     expect(screen.getByRole("link", { name: /Import a statement/ })).toHaveAttribute("href", "/ledger/import");
   });
+  it("offers Search first, for a phone, which has no rail and no shortcut", () => {
+    renderWithQuery(<MorePage />, served);
+    const seen = vi.fn();
+    window.addEventListener(OPEN_SEARCH_EVENT, seen);
+    fireEvent.click(screen.getByRole("button", { name: /^Search/ }));
+    window.removeEventListener(OPEN_SEARCH_EVENT, seen);
+    expect(seen).toHaveBeenCalledTimes(1);
+  });
   it("links to What Claude knows, the page that shows the market picture and what each call reads", () => {
     renderWithQuery(<MorePage />, served);
     expect(screen.getByRole("link", { name: /What Claude knows/ })).toHaveAttribute("href", "/more/claude");
diff --git a/web/app/more/page.tsx b/web/app/more/page.tsx
index 506dd11..8f127da 100644
--- a/web/app/more/page.tsx
+++ b/web/app/more/page.tsx
@@ -1,12 +1,13 @@
 "use client";
 
 import Link from "next/link";
-import { ChevronRight } from "lucide-react";
+import { ChevronRight, Search } from "lucide-react";
 import { BotCard } from "@/components/shell/BotCard";
 import { SystemStatusCard } from "@/components/shell/SystemStatusCard";
 import { ThemeToggle } from "@/components/shell/ThemeToggle";
 import { Card } from "@/components/ui/Card";
 import { TargetCard } from "@/features/more/TargetCard";
+import { openSearch } from "@/lib/search";
 
 const LINKS = [
   { href: "/research", label: "Research", sub: "Search, watchlist, sectors, universe" },
@@ -39,8 +40,17 @@ export default function MorePage() {
 
       <Card className="mt-4" as="div">
         <ul>
+          <li>
+            <button type="button" onClick={openSearch} className="flex w-full items-center justify-between gap-3 py-3 text-left">
+              <span>
+                <span className="block font-bold">Search</span>
+                <span className="block text-[0.8125rem] text-muted">A ticker, a company or a page</span>
+              </span>
+              <Search aria-hidden="true" size={18} className="text-muted" />
+            </button>
+          </li>
           {LINKS.map((l) => (
-            <li key={l.href} className="border-t border-border first:border-t-0">
+            <li key={l.href} className="border-t border-border">
               <Link href={l.href} className="flex items-center justify-between gap-3 py-3">
                 <span>
                   <span className="block font-bold">{l.label}</span>
diff --git a/web/app/research/page.test.tsx b/web/app/research/page.test.tsx
index fe08ca9..6744249 100644
--- a/web/app/research/page.test.tsx
+++ b/web/app/research/page.test.tsx
@@ -1,6 +1,7 @@
 import { fireEvent, render, screen } from "@testing-library/react";
 import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
 import { describe, expect, it, vi } from "vitest";
+import { OPEN_SEARCH_EVENT } from "@/lib/search";
 import Home from "./page";
 
 vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
@@ -27,11 +28,14 @@ describe("Home — visible search bar", () => {
     expect(screen.getByRole("button", { name: /search a ticker/i })).toBeDefined();
   });
 
-  it("opens the same command palette as ⌘K when clicked", () => {
+  it("opens the console's one palette when clicked, instead of mounting its own", () => {
     withClient(<Home />);
-    expect(screen.queryByPlaceholderText(/search a ticker, company or page/i)).toBeNull();
+    const seen = vi.fn();
+    window.addEventListener(OPEN_SEARCH_EVENT, seen);
     fireEvent.click(screen.getByRole("button", { name: /search a ticker/i }));
-    expect(screen.getByPlaceholderText(/search a ticker, company or page/i)).toBeDefined();
+    window.removeEventListener(OPEN_SEARCH_EVENT, seen);
+    expect(seen).toHaveBeenCalledTimes(1);
+    expect(screen.queryByRole("dialog")).toBeNull();
   });
 
   it("puts Top opportunities above the watchlist", () => {
diff --git a/web/app/research/page.tsx b/web/app/research/page.tsx
index 564c66b..974a40a 100644
--- a/web/app/research/page.tsx
+++ b/web/app/research/page.tsx
@@ -1,21 +1,18 @@
 "use client";
 
-import { useState } from "react";
-import { CommandPalette } from "@/components/search/CommandPalette";
 import { SectorGrid } from "@/components/home/SectorGrid";
 import { WatchlistTable } from "@/components/home/WatchlistTable";
 import { TopOpportunities } from "@/features/research/TopOpportunities";
+import { openSearch } from "@/lib/search";
 
 export default function Home() {
-  const [searchOpen, setSearchOpen] = useState(false);
-
   return (
     <div className="px-8 py-6">
       <div className="flex items-center justify-between gap-4">
         <h1 className="font-mono text-2xl text-content">Research</h1>
         <button
           type="button"
-          onClick={() => setSearchOpen(true)}
+          onClick={openSearch}
           className="flex items-center gap-2 rounded border border-border bg-surface px-3 py-1.5 text-sm text-muted hover:text-content focus-visible:ring-focus"
         >
           <span>Search a ticker</span>
@@ -24,7 +21,6 @@ export default function Home() {
           </kbd>
         </button>
       </div>
-      <CommandPalette open={searchOpen} onOpenChange={setSearchOpen} />
 
       <section className="mt-10">
         <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">Top opportunities</h2>
diff --git a/web/components/shell/Rail.test.tsx b/web/components/shell/Rail.test.tsx
index 039b3cb..4134e3b 100644
--- a/web/components/shell/Rail.test.tsx
+++ b/web/components/shell/Rail.test.tsx
@@ -1,9 +1,10 @@
-import { screen } from "@testing-library/react";
+import { fireEvent, screen } from "@testing-library/react";
 import { describe, expect, it, vi } from "vitest";
 import { renderWithQuery } from "@/lib/test-query";
 
 vi.mock("next/navigation", () => ({ usePathname: () => "/trades/41" }));
 
+import { OPEN_SEARCH_EVENT } from "@/lib/search";
 import { Rail } from "./Rail";
 
 const controls = {
@@ -44,4 +45,14 @@ describe("Rail", () => {
     renderWithQuery(<Rail />, { "/options/controls": controls, "/options/approvals": approvals(0) });
     expect(await screen.findByRole("link", { name: "Trades" })).toBeInTheDocument();
   });
+  it("offers Search under the wordmark, which opens the console's one palette", async () => {
+    renderWithQuery(<Rail />, { "/options/controls": controls, "/options/approvals": approvals(0) });
+    const seen = vi.fn();
+    window.addEventListener(OPEN_SEARCH_EVENT, seen);
+    const button = screen.getByRole("button", { name: "Search" });
+    expect(button).toHaveAttribute("aria-keyshortcuts", "Meta+K Control+K");
+    fireEvent.click(button);
+    window.removeEventListener(OPEN_SEARCH_EVENT, seen);
+    expect(seen).toHaveBeenCalledTimes(1);
+  });
 });
diff --git a/web/components/shell/Rail.tsx b/web/components/shell/Rail.tsx
index 06ecd50..9cb9379 100644
--- a/web/components/shell/Rail.tsx
+++ b/web/components/shell/Rail.tsx
@@ -3,9 +3,11 @@
 import clsx from "clsx";
 import Link from "next/link";
 import { usePathname } from "next/navigation";
+import { Search } from "lucide-react";
 import { useQuery } from "@tanstack/react-query";
 import { apiFetch } from "@/lib/api";
 import { NAV, activeKey } from "@/lib/nav";
+import { openSearch } from "@/lib/search";
 import type { ApprovalListResponse } from "@/components/options/types";
 import { BotCard } from "./BotCard";
 
@@ -27,6 +29,19 @@ export function Rail() {
   return (
     <nav aria-label="Sections" className="hidden w-[200px] shrink-0 flex-col bg-surface px-3 py-[18px] md:flex">
       <div className="px-2.5 pb-4 text-[0.9375rem] font-extrabold">IBKR Income</div>
+      {/* Opens the one palette the root layout mounts; ⌘K does the same from anywhere. */}
+      <button
+        type="button"
+        onClick={openSearch}
+        aria-keyshortcuts="Meta+K Control+K"
+        className="mb-3 flex items-center gap-2.5 rounded-[10px] bg-sunk px-2.5 py-2 text-sm text-muted hover:bg-sunk-deep hover:text-content"
+      >
+        <Search aria-hidden="true" size={17} strokeWidth={2} />
+        <span className="flex-1 text-left">Search</span>
+        <kbd aria-hidden="true" className="font-mono text-[11px]">
+          ⌘K
+        </kbd>
+      </button>
       <ul className="flex flex-1 flex-col gap-0.5 overflow-y-auto">
         {NAV.map((item) => {
           const on = item.key === current;
diff --git a/web/lib/nav.ts b/web/lib/nav.ts
index 77f9641..a49e350 100644
--- a/web/lib/nav.ts
+++ b/web/lib/nav.ts
@@ -1,5 +1,5 @@
 import type { LucideIcon } from "lucide-react";
-import { ArrowLeftRight, Ellipsis, Home, Newspaper, PieChart, Receipt, Search } from "lucide-react";
+import { ArrowLeftRight, Ellipsis, Home, Newspaper, PieChart, Receipt, Telescope } from "lucide-react";
 
 export type NavItem = {
   key: string;
@@ -17,7 +17,7 @@ export const NAV: NavItem[] = [
   { key: "trades", label: "Trades", href: "/trades", match: ["/trades"], icon: ArrowLeftRight, phone: true },
   { key: "portfolio", label: "Portfolio", href: "/portfolio", match: ["/portfolio"], icon: PieChart, phone: true },
   { key: "activity", label: "Activity", href: "/activity", match: ["/activity", "/ledger"], icon: Receipt, phone: true },
-  { key: "research", label: "Research", href: "/research", match: ["/research", "/stock"], icon: Search, phone: false },
+  { key: "research", label: "Research", href: "/research", match: ["/research", "/stock"], icon: Telescope, phone: false },
   { key: "news", label: "News", href: "/news", match: ["/news"], icon: Newspaper, phone: false },
   { key: "more", label: "More", href: "/more", match: ["/more", "/explain"], icon: Ellipsis, phone: true },
 ];
````

---

## Section C: Research (Tasks 8-11) · model: sonnet (effort high)

**Reads:** this section; `web/DESIGN.md` (Colors: the Words First Rule; Layout; Components: Card, Field, Status word,
Buttons; Surfaces: Research, Stock; the new Research surface is in T10's patch); `web/components/home/WatchlistTable.tsx`,
`SectorGrid.tsx`, `SectorCard.tsx`; `web/features/research/TopOpportunities.tsx`, `OpportunityCard.tsx`;
`web/features/stock/StockPage.tsx` (lines 30-45, the frame this page copies); `web/features/stock-value/parts.tsx`.

**Spec for da-vinci (give it this, so it has little to decide):** the Research surface paragraph in T10's DESIGN.md hunk
and the Top opportunities sentence in T11's are the spec. Classes and copy are fixed by the patches: the frame and
title as Stock's; the header actions a secondary `Button` (Search, lucide `Search` 18) and a secondary pill link
(Universe); each card a `Card` with an `h2` `text-[1.0625rem] font-bold` and a muted `text-[0.8125rem]` line; rows
`border-t border-border py-2.5 first:border-t-0`; the add field the `field` (`components/ui/field.ts`) with its label;
the move `tabular` in muted ink, never `text-gain`/`text-loss`; unknown `features/stock-value/parts::Hatched`; Claude's
note `rounded-xl bg-sunk px-3 py-2` with `ClaudeLabel`. da-vinci may tune spacing inside those and must record each
change as a ruling; it may not add a token, colour, font, radius, shadow or lime, change copy, or move a section.

**Entry checks:**

- [ ] **C1. Section B landed.** Three task commits since Section A; vitest 1593 in 153 files; G7 prints the layout line.
- [ ] **C2. The first patch applies** (T8-T11 each edit `app/research/page.tsx` or `DESIGN.md` after the one before,
  so each is checked at its own Step 1): `git apply --check <S>/p6/T8.out` prints nothing.
- [ ] **C3. Test counts as written.** `grep -c "^  it(" web/components/home/WatchlistTable.test.tsx web/components/home/SectorCard.test.tsx web/features/research/OpportunityCard.test.tsx`
  prints `6`, `4` and `9`; `ls web/features/research/ResearchPage.tsx` fails.

**Section exit:** four task commits; vitest **1605 in 154 files**; tsc, lint clean; G1-G5, G7; the Research surface is
in `web/DESIGN.md`.

### Task 8: Your watchlist

**Files:** Modify `web/components/home/WatchlistTable.tsx` (+ test), `web/app/research/page.tsx` (+ test); this plan.

**What it does (rulings 3, 11):** the "Your watchlist" card of rows, the line to Universe, the labelled add field,
loading and failure in words, a failed add or remove in words. The research page drops its "Watchlist" section heading
(the card has its own). Five new cases; two existing ones change (the empty line is awaited, Remove is found by its name
"Remove NVDA").

- [ ] **Step 1: da-vinci** with the Spec above.
- [ ] **Step 2: Check and apply `T8`.** `git status --short` shows four `M` files.
- [ ] **Step 3: Red check.** `git stash push -- web/components/home/WatchlistTable.tsx web/app/research/page.tsx`, then
  `cd web && npx vitest run components/home/WatchlistTable.test.tsx app/research` ends `6 failed | 7 passed (13)`, then
  `git stash pop`.
- [ ] **Step 4: Gate.** `npx vitest run components/home app/research`: 17 passed. Full vitest **1597 in 153 files**;
  tsc, lint clean; G5.
- [ ] **Step 5: Commit** `feat(web): Your watchlist, a card of rows that says unknown, loading and failure in words`.

<!-- block T8 -->
````diff
diff --git a/web/app/research/page.test.tsx b/web/app/research/page.test.tsx
index 6744249..284e501 100644
--- a/web/app/research/page.test.tsx
+++ b/web/app/research/page.test.tsx
@@ -38,10 +38,10 @@ describe("Home — visible search bar", () => {
     expect(screen.queryByRole("dialog")).toBeNull();
   });
 
-  it("puts Top opportunities above the watchlist", () => {
+  it("puts Top opportunities above the watchlist", async () => {
     withClient(<Home />);
     const top = screen.getByRole("heading", { name: "Top opportunities" });
-    const watch = screen.getByRole("heading", { name: "Watchlist" });
+    const watch = await screen.findByRole("heading", { name: "Your watchlist" });
     expect(top.compareDocumentPosition(watch) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
     expect(screen.getByRole("group", { name: "Opportunity list" })).toBeDefined();
   });
diff --git a/web/app/research/page.tsx b/web/app/research/page.tsx
index 974a40a..570b618 100644
--- a/web/app/research/page.tsx
+++ b/web/app/research/page.tsx
@@ -27,10 +27,9 @@ export default function Home() {
         <TopOpportunities />
       </section>
 
-      <section className="mt-10">
-        <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">Watchlist</h2>
+      <div className="mt-10">
         <WatchlistTable />
-      </section>
+      </div>
 
       <section className="mt-10">
         <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">
diff --git a/web/components/home/WatchlistTable.test.tsx b/web/components/home/WatchlistTable.test.tsx
index fde8f21..4a4c7e7 100644
--- a/web/components/home/WatchlistTable.test.tsx
+++ b/web/components/home/WatchlistTable.test.tsx
@@ -21,7 +21,7 @@ describe("WatchlistTable", () => {
     const { apiFetch } = await import("@/lib/api");
     (apiFetch as any).mockResolvedValue({ as_of: "x", items: [] });
     withClient(<WatchlistTable />);
-    expect(screen.getByText(/Your watchlist is empty/i)).toBeDefined();
+    expect(await screen.findByText(/Your watchlist is empty/i)).toBeDefined();
     expect(screen.queryByRole("img")).toBeNull();
   });
 
@@ -151,9 +151,76 @@ describe("WatchlistTable", () => {
       };
     });
     withClient(<WatchlistTable />);
-    const remove = await screen.findByText("remove");
+    const remove = await screen.findByRole("button", { name: "Remove NVDA" });
     fireEvent.click(remove);
     await waitFor(() => expect((remove as HTMLButtonElement).disabled).toBe(true));
     resolveDelete(undefined);
   });
-});
\ No newline at end of file
+
+  it("is titled Your watchlist and points to the scan's own watchlist on Universe", async () => {
+    const { apiFetch } = await import("@/lib/api");
+    (apiFetch as any).mockResolvedValue({ as_of: "x", items: [] });
+    withClient(<WatchlistTable />);
+    expect(screen.getByRole("heading", { level: 2, name: "Your watchlist" })).toBeDefined();
+    expect(screen.getByRole("link", { name: "Universe" }).getAttribute("href")).toBe("/research/universe");
+  });
+
+  it("holds its place while loading and says a failed read in words, never an empty list", async () => {
+    const { apiFetch } = await import("@/lib/api");
+    (apiFetch as any).mockImplementation(() => new Promise(() => {}));
+    const { unmount } = withClient(<WatchlistTable />);
+    expect(screen.getByRole("status", { name: "Loading your watchlist" })).toBeDefined();
+    expect(screen.queryByText(/Your watchlist is empty/i)).toBeNull();
+    unmount();
+    (apiFetch as any).mockRejectedValue(new Error("down"));
+    withClient(<WatchlistTable />);
+    expect(await screen.findByText("Your watchlist could not be loaded right now.")).toBeDefined();
+  });
+
+  it("writes a row as words: the price, the day's move signed but not coloured, IV rank, checks and earnings", async () => {
+    const { apiFetch } = await import("@/lib/api");
+    (apiFetch as any).mockResolvedValue({
+      as_of: "x",
+      items: [
+        {
+          symbol: "NVDA", name: "NVIDIA",
+          price: { value: 120.0, source: "yfinance", as_of: "x", stale: true },
+          change_pct: -1.25, iv_rank: 80.0, checks: { passed: 3, evaluable: 5, unknown: 1 },
+          next_earnings: "2026-11-19",
+        },
+        {
+          symbol: "KO", name: "Coca-Cola", price: null, change_pct: null, iv_rank: null,
+          checks: { passed: 0, evaluable: 0, unknown: 4 }, next_earnings: null,
+        },
+      ],
+    });
+    withClient(<WatchlistTable />);
+    expect(await screen.findByText("$120.00")).toBeDefined();
+    const move = screen.getByText("-1.25% today");
+    expect(move.className).not.toMatch(/text-(gain|loss)/);
+    expect(screen.getByText("Delayed")).toBeDefined();
+    expect(screen.getByText("IV rank 80.0")).toBeDefined();
+    expect(screen.getByText("3 of 5 checks pass")).toBeDefined();
+    expect(screen.getByText("Earnings Nov 19, 2026")).toBeDefined();
+    expect(screen.getByRole("link", { name: /NVDA/ }).getAttribute("href")).toBe("/stock/NVDA");
+    // KO: every unknown is a hatched n/a, never $0 or 0 of 0.
+    expect(screen.getAllByText("n/a").length).toBe(4);
+    expect(screen.queryByText("0 of 0 checks pass")).toBeNull();
+    expect(document.querySelector(".text-gain, .text-loss")).toBeNull();
+  });
+
+  it("says a failed add in words", async () => {
+    const { apiFetch } = await import("@/lib/api");
+    (apiFetch as any).mockImplementation(async (path: string, init?: RequestInit) => {
+      if (path.startsWith("/research/search")) {
+        return { as_of: "x", query: "AAP", results: [{ symbol: "AAPL", name: "Apple Inc.", exchange: "Nasdaq", is_etf: false }] };
+      }
+      if (init?.method === "POST") throw new Error("down");
+      return { as_of: "x", items: [] };
+    });
+    withClient(<WatchlistTable />);
+    fireEvent.change(screen.getByPlaceholderText(/add a symbol/i), { target: { value: "AAP" } });
+    fireEvent.click(await screen.findByText("Apple Inc."));
+    expect(await screen.findByText("That name could not be added. Nothing changed.")).toBeDefined();
+  });
+});
diff --git a/web/components/home/WatchlistTable.tsx b/web/components/home/WatchlistTable.tsx
index 2e856c0..8bbac64 100644
--- a/web/components/home/WatchlistTable.tsx
+++ b/web/components/home/WatchlistTable.tsx
@@ -1,10 +1,15 @@
 "use client";
 
-import { useEffect, useState } from "react";
+import { useEffect, useId, useState, type ReactNode } from "react";
 import Link from "next/link";
 import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
+import { Card } from "@/components/ui/Card";
+import { StatusWord } from "@/components/ui/StatusWord";
+import { FIELD, FIELD_LABEL } from "@/components/ui/field";
+import { shortDate } from "@/features/portfolio/format";
+import { Hatched } from "@/features/stock-value/parts";
 import { apiFetch } from "@/lib/api";
-import { relativeAge } from "@/lib/format";
+import { formatMoneyCell } from "@/lib/money";
 
 type SearchHit = { symbol: string; name: string; exchange: string | null; is_etf: boolean };
 type SearchResponse = { as_of: string; query: string; results: SearchHit[] };
@@ -21,9 +26,23 @@ type WatchlistItem = {
 
 type WatchlistResponse = { as_of: string; items: WatchlistItem[] };
 
+/** "+1.50%": a price move is signed but never green or red, because it is not money (web/DESIGN.md Colors). */
+function signedPct(v: number): string {
+  return `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
+}
+
+/**
+ * "Your watchlist" on Research (web overhaul Part 6): the names the operator follows here, kept in
+ * research.db so their quotes stay warm. It is not the scan's own watchlist (that one is on Universe and
+ * changes through a command), and the card says so. Add is a typeahead over `GET /research/search`, so a
+ * typo never reaches the write route; a pick adds at once (no order consequence, no dialog), and the
+ * input is disabled while an add is in flight. Each row links to the stock page and has its own Remove,
+ * disabled while that row's remove is in flight. Unknown is a hatched n/a; a failed read or write is a
+ * sentence, never an empty list.
+ */
 export function WatchlistTable() {
   const qc = useQueryClient();
-  const { data } = useQuery({
+  const { data, isError } = useQuery({
     queryKey: ["watchlist"],
     queryFn: () => apiFetch<WatchlistResponse>("/watchlist"),
     placeholderData: (prev) => prev,
@@ -38,150 +57,171 @@ export function WatchlistTable() {
   });
 
   const removeMutation = useMutation({
-    mutationFn: (symbol: string) =>
-      apiFetch<void>(`/watchlist/${symbol}`, { method: "DELETE" }),
+    mutationFn: (symbol: string) => apiFetch<void>(`/watchlist/${symbol}`, { method: "DELETE" }),
     onSuccess: () => qc.invalidateQueries({ queryKey: ["watchlist"] }),
   });
 
   const items = data?.items ?? [];
 
-  return (
-    <div>
-      <AddSymbol
-        onPick={(symbol) => addMutation.mutate(symbol)}
-        disabled={addMutation.isPending}
-      />
+  let body;
+  if (!data && isError) {
+    body = <p className="mt-3 text-sm">Your watchlist could not be loaded right now.</p>;
+  } else if (!data) {
+    body = <div role="status" aria-busy="true" aria-label="Loading your watchlist" className="mt-3 h-24 rounded-xl bg-sunk" />;
+  } else if (items.length === 0) {
+    body = <p className="mt-3 text-sm">Your watchlist is empty. Add a ticker above to start tracking it here.</p>;
+  } else {
+    body = (
+      <ul className="mt-2">
+        {items.map((item) => (
+          <WatchRow
+            key={item.symbol}
+            item={item}
+            removing={removeMutation.isPending && removeMutation.variables === item.symbol}
+            onRemove={() => removeMutation.mutate(item.symbol)}
+          />
+        ))}
+      </ul>
+    );
+  }
 
-      {items.length === 0 ? (
-        <p className="mt-3 text-sm text-muted">
-          Your watchlist is empty. Add a ticker above to start tracking it here.
+  return (
+    <Card aria-labelledby="watchlist-title">
+      <div className="flex items-baseline justify-between gap-3">
+        <h2 id="watchlist-title" className="text-[1.0625rem] font-bold">
+          Your watchlist
+        </h2>
+        {items.length > 0 && <span className="tabular text-[0.8125rem] text-muted">{items.length === 1 ? "1 name" : `${items.length} names`}</span>}
+      </div>
+      <p className="mt-1 text-[0.8125rem] text-muted">
+        Names you follow here, so their quotes stay fresh. The scan&apos;s own watchlist is on{" "}
+        <Link href="/research/universe" className="font-semibold text-content underline underline-offset-2">
+          Universe
+        </Link>
+        .
+      </p>
+      <AddSymbol onPick={(symbol) => addMutation.mutate(symbol)} disabled={addMutation.isPending} />
+      {addMutation.isError && (
+        <p role="alert" className="mt-2 text-sm">
+          That name could not be added. Nothing changed.
         </p>
-      ) : (
-        <table className="mt-3 w-full text-sm">
-          <thead>
-            <tr className="text-left text-xs text-muted">
-              <th className="py-2 font-medium">Symbol</th>
-              <th className="py-2 font-medium">Price</th>
-              <th className="py-2 font-medium">Day</th>
-              <th className="py-2 font-medium">IV rank</th>
-              <th className="py-2 font-medium">Checks</th>
-              <th className="py-2 font-medium"></th>
-            </tr>
-          </thead>
-          <tbody className="divide-y divide-border">
-            {items.map((item) => (
-              <tr key={item.symbol}>
-                <td className="py-2">
-                  <Link
-                    href={`/stock/${item.symbol}`}
-                    className="font-mono text-content underline-offset-2 hover:underline"
-                  >
-                    {item.symbol}
-                  </Link>
-                  <div className="text-xs text-muted">{item.name}</div>
-                </td>
-                <td className="py-2 tabular">
-                  {item.price?.value != null ? (
-                    <span className="text-content">
-                      ${item.price.value.toFixed(2)}
-                      <span className="ml-1 text-xs text-unknown">
-                        {relativeAge(item.price.as_of)}
-                        {item.price.stale ? " · delayed" : ""}
-                      </span>
-                    </span>
-                  ) : (
-                    <span className="text-unknown">n/a</span>
-                  )}
-                </td>
-                <td className="py-2 tabular">
-                  {item.change_pct == null ? (
-                    <span className="text-unknown">n/a</span>
-                  ) : (
-                    <ChangePct value={item.change_pct} />
-                  )}
-                </td>
-                <td className="py-2 tabular">
-                  {item.iv_rank == null ? (
-                    <span className="text-unknown">n/a</span>
-                  ) : (
-                    <span className="text-content">{item.iv_rank.toFixed(1)}</span>
-                  )}
-                </td>
-                <td className="py-2 text-xs text-muted">
-                  {item.checks.passed} of {item.checks.evaluable}
-                </td>
-                <td className="py-2 text-right">
-                  <button
-                    type="button"
-                    disabled={removeMutation.isPending && removeMutation.variables === item.symbol}
-                    onClick={() => removeMutation.mutate(item.symbol)}
-                    className="text-xs text-muted enabled:hover:text-loss disabled:cursor-default disabled:opacity-50"
-                  >
-                    remove
-                  </button>
-                </td>
-              </tr>
-            ))}
-          </tbody>
-        </table>
       )}
-    </div>
+      {removeMutation.isError && (
+        <p role="alert" className="mt-2 text-sm">
+          That name could not be removed. It is still on your watchlist.
+        </p>
+      )}
+      {body}
+    </Card>
+  );
+}
+
+function WatchRow({ item, removing, onRemove }: { item: WatchlistItem; removing: boolean; onRemove: () => void }) {
+  const price = item.price?.value;
+  const facts: ReactNode[] = [
+    item.iv_rank == null ? (
+      <span key="iv">
+        IV rank <Hatched />
+      </span>
+    ) : (
+      <span key="iv" className="tabular">{`IV rank ${item.iv_rank.toFixed(1)}`}</span>
+    ),
+    item.checks.evaluable === 0 ? (
+      <span key="checks">
+        Checks <Hatched />
+      </span>
+    ) : (
+      <span key="checks" className="tabular">{`${item.checks.passed} of ${item.checks.evaluable} checks pass`}</span>
+    ),
+  ];
+  if (item.next_earnings) facts.push(<span key="earn">{`Earnings ${shortDate(item.next_earnings)}`}</span>);
+
+  return (
+    <li className="flex items-center gap-3 border-t border-border py-2.5 first:border-t-0">
+      <Link href={`/stock/${item.symbol}`} className="min-w-0 flex-1 py-1">
+        <span className="flex items-baseline gap-2">
+          <span className="font-bold">{item.symbol}</span>
+          <span className="truncate text-[0.8125rem] text-muted">{item.name}</span>
+        </span>
+        <span className="mt-0.5 block text-[0.8125rem] text-muted">
+          {facts.map((f, i) => (
+            <span key={i}>
+              {i > 0 && " · "}
+              {f}
+            </span>
+          ))}
+        </span>
+      </Link>
+      <div className="shrink-0 text-right">
+        <div className="tabular font-semibold">{price == null ? <Hatched /> : formatMoneyCell(price)}</div>
+        <div className="mt-0.5 flex items-center justify-end gap-1.5 text-[0.8125rem] text-muted">
+          {item.price?.stale && <StatusWord tone="flag">Delayed</StatusWord>}
+          {item.change_pct == null ? (
+            <span>
+              Day <Hatched />
+            </span>
+          ) : (
+            <span className="tabular">{`${signedPct(item.change_pct)} today`}</span>
+          )}
+        </div>
+      </div>
+      <button
+        type="button"
+        disabled={removing}
+        onClick={onRemove}
+        aria-label={`Remove ${item.symbol}`}
+        className="inline-flex min-h-11 shrink-0 items-center rounded-full px-3 text-[0.8125rem] font-semibold text-muted enabled:hover:bg-sunk enabled:hover:text-content disabled:opacity-50 md:min-h-9"
+      >
+        Remove
+      </button>
+    </li>
   );
 }
 
 /**
- * Typeahead over the research symbol directory (`GET /research/search`), the
- * same pattern `components/universe/AddSymbol.tsx` uses for `would_own`/
- * `watchlist` there — a typo cannot reach the write route because the
- * caller only ever picks a real hit. Unlike that universe watchlist, this
- * per-user watchlist has no order consequence, so a pick fires immediately
- * with no confirmation dialog, matching the existing `remove` control.
- * `disabled` (driven by the caller's `addMutation.isPending`) blanks the
- * input while an add is in flight — without it, a fast double-pick could
- * fire two POSTs for the same or different symbols with no feedback that
- * either was already in flight.
+ * Typeahead over the research symbol directory (`GET /research/search`), the same pattern
+ * `components/universe/AddSymbol.tsx` uses: a typo cannot reach the write route because the caller only
+ * ever picks a real hit. This per-user list has no order consequence, so a pick fires at once with no
+ * dialog. `disabled` blanks the input while an add is in flight, so a fast double-pick cannot fire two
+ * POSTs.
  */
-function AddSymbol({
-  onPick,
-  disabled = false,
-}: {
-  onPick: (symbol: string) => void;
-  disabled?: boolean;
-}) {
+function AddSymbol({ onPick, disabled = false }: { onPick: (symbol: string) => void; disabled?: boolean }) {
   const [term, setTerm] = useState("");
   const [hits, setHits] = useState<SearchHit[]>([]);
+  const id = useId();
 
   useEffect(() => {
     if (!term.trim()) {
       setHits([]);
       return;
     }
-    const id = setTimeout(async () => {
+    const t = setTimeout(async () => {
       try {
-        const data = await apiFetch<SearchResponse>(
-          `/research/search?q=${encodeURIComponent(term)}`,
-        );
+        const data = await apiFetch<SearchResponse>(`/research/search?q=${encodeURIComponent(term)}`);
         setHits(data.results);
       } catch {
         setHits([]);
       }
     }, 200);
-    return () => clearTimeout(id);
+    return () => clearTimeout(t);
   }, [term]);
 
   return (
-    <div>
+    <div className="mt-3 max-w-sm">
+      <label htmlFor={id} className={FIELD_LABEL}>
+        Follow a name
+      </label>
       <input
+        id={id}
         value={term}
         disabled={disabled}
         onChange={(e) => setTerm(e.target.value)}
         placeholder="Add a symbol"
-        aria-label="Add a symbol to your watchlist"
         autoComplete="off"
-        className="w-full max-w-xs rounded-sm border border-border bg-background px-2 py-1 font-mono text-sm text-content outline-none placeholder:text-muted focus-visible:border-focus disabled:opacity-50"
+        className={`${FIELD} mt-1 w-full disabled:opacity-50`}
       />
       {hits.length > 0 && (
-        <ul className="mt-1 max-w-xs rounded-sm border border-border bg-surface">
+        <ul className="mt-1 rounded-xl border border-control bg-surface py-1">
           {hits.map((h) => (
             <li key={h.symbol}>
               <button
@@ -191,25 +231,17 @@ function AddSymbol({
                   setHits([]);
                   onPick(h.symbol);
                 }}
-                className="flex w-full items-baseline gap-3 px-2 py-1 text-left text-sm hover:bg-elevated focus-visible:bg-elevated"
+                className="flex min-h-11 w-full items-center gap-3 px-3 text-left text-sm hover:bg-sunk focus-visible:bg-sunk md:min-h-9"
               >
-                <span className="tabular font-mono text-content">{h.symbol}</span>
-                <span className="truncate text-xs text-muted">{h.name}</span>
-                {h.is_etf && <span className="ml-auto text-[11px] text-muted">ETF</span>}
+                <span className="tabular font-semibold">{h.symbol}</span>
+                <span className="min-w-0 flex-1 truncate text-muted">{h.name}</span>
+                {h.is_etf && <StatusWord>ETF</StatusWord>}
               </button>
             </li>
           ))}
         </ul>
       )}
-      {term.trim() && hits.length === 0 && (
-        <p className="mt-1 text-xs text-muted">No match</p>
-      )}
+      {term.trim() && hits.length === 0 && <p className="mt-1 text-[0.8125rem] text-muted">No ticker matches yet.</p>}
     </div>
   );
 }
-
-function ChangePct({ value }: { value: number }) {
-  const sign = value > 0 ? "+" : "";
-  const cls = value > 0 ? "text-gain" : value < 0 ? "text-loss" : "text-muted";
-  return <span className={cls}>{`${sign}${value.toFixed(2)}%`}</span>;
-}
\ No newline at end of file
````

### Task 9: The Sectors card

**Files:** Modify `web/components/home/SectorCard.tsx`, `SectorGrid.tsx`, `SectorCard.test.tsx`; create
`web/components/home/SectorGrid.test.tsx`; modify `web/app/research/page.tsx`; this plan.

**What it does (ruling 12):** one "Sectors by IV rank" card; each sector a row; no green or red; loading, empty and
failure in words. The research page drops its sectors heading.

- [ ] **Step 1: da-vinci** with the Spec above.
- [ ] **Step 2: Check and apply `T9`.** `git status --short` shows four `M` files and `?? web/components/home/SectorGrid.test.tsx`.
- [ ] **Step 3: Red check.** `git stash push -- web/components/home/SectorCard.tsx web/components/home/SectorGrid.tsx`,
  then `cd web && npx vitest run components/home/Sector` ends `4 failed | 4 passed (8)`, then `git stash pop`.
- [ ] **Step 4: Gate.** `npx vitest run components/home app/research`: 21 passed. Full vitest **1601 in 154 files**;
  tsc, lint clean; G5.
- [ ] **Step 5: Commit** `feat(web): the sectors as one card of rows, moves signed and never green or red`.

<!-- block T9 -->
````diff
diff --git a/web/app/research/page.tsx b/web/app/research/page.tsx
index 570b618..d2a5002 100644
--- a/web/app/research/page.tsx
+++ b/web/app/research/page.tsx
@@ -31,12 +31,9 @@ export default function Home() {
         <WatchlistTable />
       </div>
 
-      <section className="mt-10">
-        <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">
-          Sectors by IV rank
-        </h2>
+      <div className="mt-10">
         <SectorGrid />
-      </section>
+      </div>
     </div>
   );
 }
\ No newline at end of file
diff --git a/web/components/home/SectorCard.test.tsx b/web/components/home/SectorCard.test.tsx
index 2d73ce5..1e0afd6 100644
--- a/web/components/home/SectorCard.test.tsx
+++ b/web/components/home/SectorCard.test.tsx
@@ -65,4 +65,43 @@ describe("SectorCard", () => {
     );
     expect(screen.getByText("(3)")).toBeDefined();
   });
-});
\ No newline at end of file
+});
+describe("SectorCard, restyled (web overhaul Part 6)", () => {
+  it("never colours a move green or red: a sector's move is a price, not money", () => {
+    const { container } = render(
+      <ul>
+        <SectorCard
+          sector="tech"
+          count={3}
+          changePct={-1.5}
+          best={{ symbol: "MSFT", change_pct: 2.0 }}
+          worst={{ symbol: "AAPL", change_pct: -1.0 }}
+          avgIvRank={42.0}
+          ivRankCount={3}
+        />
+      </ul>,
+    );
+    expect(container.querySelector(".text-gain, .text-loss")).toBeNull();
+    expect(screen.getByRole("heading", { level: 3, name: "tech" })).toBeDefined();
+    expect(container.textContent).toContain("3 names · -1.50% today");
+    expect(container.textContent).toContain("Best MSFT +2.00% · worst AAPL -1.00%");
+  });
+
+  it("hatches every unknown, so n/a never reads as zero", () => {
+    const { container } = render(
+      <ul>
+        <SectorCard
+          sector="bonds"
+          count={1}
+          changePct={null}
+          best={{ symbol: "TLT", change_pct: null }}
+          worst={{ symbol: "TLT", change_pct: null }}
+          avgIvRank={null}
+          ivRankCount={0}
+        />
+      </ul>,
+    );
+    expect(container.querySelectorAll(".hatch").length).toBe(4);
+    expect(container.textContent).toContain("1 name");
+  });
+});
diff --git a/web/components/home/SectorCard.tsx b/web/components/home/SectorCard.tsx
index c8a4e02..dbedca8 100644
--- a/web/components/home/SectorCard.tsx
+++ b/web/components/home/SectorCard.tsx
@@ -1,4 +1,4 @@
-import clsx from "clsx";
+import { Hatched } from "@/features/stock-value/parts";
 
 type SectorMover = { symbol: string; change_pct: number | null };
 
@@ -12,72 +12,57 @@ type Props = {
   ivRankCount: number;
 };
 
-export function SectorCard({
-  sector,
-  count,
-  changePct,
-  best,
-  worst,
-  avgIvRank,
-  ivRankCount,
-}: Props) {
+/**
+ * One sector as a row of the Sectors card (web overhaul Part 6, restyled in place): the name and its
+ * average IV rank with how many names it averages, then the day's move and the count, then the best and
+ * worst movers. A move is signed but never green or red, because a sector's move is a price, not money
+ * (web/DESIGN.md Colors). Unknown is a hatched n/a, never 0.
+ */
+export function SectorCard({ sector, count, changePct, best, worst, avgIvRank, ivRankCount }: Props) {
   return (
-    <div className="bg-surface p-4">
-      <header className="flex items-baseline justify-between">
-        <h3 className="text-sm font-medium text-content">{sector}</h3>
-        <span className="text-xs text-muted">{count} names</span>
-      </header>
-
-      <div className="mt-3 flex items-baseline gap-2">
+    <li className="border-t border-border py-3 first:border-t-0">
+      <div className="flex items-baseline justify-between gap-3">
+        <h3 className="min-w-0 truncate text-[0.9375rem] font-bold">{sector}</h3>
+        <span className="shrink-0 text-sm">
+          IV rank{" "}
+          {avgIvRank == null ? (
+            <Hatched />
+          ) : (
+            <>
+              <span className="tabular font-semibold">{avgIvRank.toFixed(1)}</span>{" "}
+              <span className="tabular text-[0.8125rem] text-muted">{ivRankCount === 1 ? "(1 name)" : `(${ivRankCount})`}</span>
+            </>
+          )}
+        </span>
+      </div>
+      <p className="mt-0.5 text-[0.8125rem] text-muted">
+        <span className="tabular">{count === 1 ? "1 name" : `${count} names`}</span>
+        {" · "}
         {changePct == null ? (
-          <span className="tabular text-sm text-unknown">n/a</span>
+          <>
+            day <Hatched />
+          </>
         ) : (
-          <span className={clsx("tabular text-sm", changeClass(changePct))}>
-            {signedPct(changePct)}
-          </span>
+          <>
+            <span className="tabular">{signedPct(changePct)}</span> today
+          </>
         )}
-        <span className="text-xs text-muted">day</span>
-      </div>
-
-      <dl className="mt-3 space-y-1 text-xs text-muted">
-        <div className="flex justify-between">
-          <dt>best</dt>
-          <dd className="flex items-center gap-1">
-            <span className="font-mono text-content">{best.symbol}</span>
-            <ChangePct value={best.change_pct} />
-          </dd>
-        </div>
-        <div className="flex justify-between">
-          <dt>worst</dt>
-          <dd className="flex items-center gap-1">
-            <span className="font-mono text-content">{worst.symbol}</span>
-            <ChangePct value={worst.change_pct} />
-          </dd>
-        </div>
-        <div className="flex justify-between">
-          <dt>avg IV rank</dt>
-          <dd>
-            {avgIvRank == null ? (
-              <span className="text-unknown">n/a</span>
-            ) : (
-              <>
-                <span className="tabular text-content">{avgIvRank.toFixed(1)}</span>
-                <span className="ml-1 text-unknown">
-                  {ivRankCount === 1 ? "(1 name)" : `(${ivRankCount})`}
-                </span>
-              </>
-            )}
-          </dd>
-        </div>
-      </dl>
-    </div>
+      </p>
+      <p className="mt-0.5 text-[0.8125rem] text-muted">
+        Best <Mover m={best} />
+        {" · "}
+        worst <Mover m={worst} />
+      </p>
+    </li>
   );
 }
 
-function ChangePct({ value }: { value: number | null }) {
-  if (value == null) return <span className="text-unknown">n/a</span>;
+function Mover({ m }: { m: SectorMover }) {
   return (
-    <span className={clsx("tabular", changeClass(value))}>{signedPct(value)}</span>
+    <>
+      <span className="font-semibold text-content">{m.symbol}</span>{" "}
+      {m.change_pct == null ? <Hatched /> : <span className="tabular">{signedPct(m.change_pct)}</span>}
+    </>
   );
 }
 
@@ -85,9 +70,3 @@ function signedPct(v: number): string {
   const sign = v > 0 ? "+" : "";
   return `${sign}${v.toFixed(2)}%`;
 }
-
-function changeClass(v: number): string {
-  if (v > 0) return "text-gain";
-  if (v < 0) return "text-loss";
-  return "text-muted";
-}
\ No newline at end of file
diff --git a/web/components/home/SectorGrid.test.tsx b/web/components/home/SectorGrid.test.tsx
new file mode 100644
index 0000000..bdeff08
--- /dev/null
+++ b/web/components/home/SectorGrid.test.tsx
@@ -0,0 +1,47 @@
+import { screen } from "@testing-library/react";
+import { describe, expect, it } from "vitest";
+import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
+import { SectorGrid } from "./SectorGrid";
+
+const sector = (name: string, iv: number | null) => ({
+  sector: name, count: 2, change_pct: 0.5, best: { symbol: "A", change_pct: 1 }, worst: { symbol: "B", change_pct: 0 },
+  avg_iv_rank: iv, iv_rank_count: iv == null ? 0 : 2,
+});
+
+describe("SectorGrid", () => {
+  it("is one card, Sectors by IV rank, with a row per sector in the API's order", async () => {
+    renderWithQuery(<SectorGrid />, { "/research/sectors": { as_of: "x", sectors: [sector("Semis", 70), sector("Banks", 30), sector("Bonds", null)] } });
+    expect(screen.getByRole("heading", { level: 2, name: "Sectors by IV rank" })).toBeInTheDocument();
+    await screen.findByText("Semis");
+    expect(screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent)).toEqual(["Semis", "Banks", "Bonds"]);
+  });
+
+  it("holds its place while loading, and says an empty or failed read in words", async () => {
+    apiFetchMock.mockImplementation(() => new Promise(() => {}));
+    const { QueryClient, QueryClientProvider } = await import("@tanstack/react-query");
+    const { render } = await import("@testing-library/react");
+    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+    const first = render(
+      <QueryClientProvider client={qc}>
+        <SectorGrid />
+      </QueryClientProvider>,
+    );
+    expect(screen.getByRole("status", { name: "Loading the sectors" })).toBeInTheDocument();
+    first.unmount();
+
+    const empty = renderWithQuery(<SectorGrid />, { "/research/sectors": { as_of: "x", sectors: [] } });
+    expect(await screen.findByText("No sector data yet.")).toBeInTheDocument();
+    empty.unmount();
+
+    apiFetchMock.mockImplementation(async () => {
+      throw new Error("down");
+    });
+    const qc2 = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+    render(
+      <QueryClientProvider client={qc2}>
+        <SectorGrid />
+      </QueryClientProvider>,
+    );
+    expect(await screen.findByText("The sectors could not be loaded right now.")).toBeInTheDocument();
+  });
+});
diff --git a/web/components/home/SectorGrid.tsx b/web/components/home/SectorGrid.tsx
index 228d302..5f766fb 100644
--- a/web/components/home/SectorGrid.tsx
+++ b/web/components/home/SectorGrid.tsx
@@ -1,4 +1,5 @@
 import { useQuery } from "@tanstack/react-query";
+import { Card } from "@/components/ui/Card";
 import { apiFetch } from "@/lib/api";
 import { SectorCard } from "./SectorCard";
 
@@ -19,30 +20,50 @@ type SectorsResponse = {
   sectors: SectorCardData[];
 };
 
+/**
+ * The Sectors card on Research (web overhaul Part 6): one white card, "Sectors by IV rank", a row per
+ * sector in the API's order (highest average IV rank first; a sector with no IV history last). Loading
+ * holds its place; a failed read and an empty answer are sentences.
+ */
 export function SectorGrid() {
-  const { data } = useQuery({
+  const { data, isError } = useQuery({
     queryKey: ["sectors"],
     queryFn: () => apiFetch<SectorsResponse>("/research/sectors"),
   });
 
-  if (!data?.sectors?.length) {
-    return <p className="text-sm text-muted">No sector data yet.</p>;
+  let body;
+  if (!data && isError) {
+    body = <p className="mt-2 text-sm">The sectors could not be loaded right now.</p>;
+  } else if (!data) {
+    body = <div role="status" aria-busy="true" aria-label="Loading the sectors" className="mt-3 h-40 rounded-xl bg-sunk" />;
+  } else if (!data.sectors?.length) {
+    body = <p className="mt-2 text-sm">No sector data yet.</p>;
+  } else {
+    body = (
+      <ul className="mt-1">
+        {data.sectors.map((s) => (
+          <SectorCard
+            key={s.sector}
+            sector={s.sector}
+            count={s.count}
+            changePct={s.change_pct}
+            best={s.best}
+            worst={s.worst}
+            avgIvRank={s.avg_iv_rank}
+            ivRankCount={s.iv_rank_count}
+          />
+        ))}
+      </ul>
+    );
   }
 
   return (
-    <div className="grid grid-cols-2 gap-4 md:grid-cols-3 lg:grid-cols-4">
-      {data.sectors.map((s) => (
-        <SectorCard
-          key={s.sector}
-          sector={s.sector}
-          count={s.count}
-          changePct={s.change_pct}
-          best={s.best}
-          worst={s.worst}
-          avgIvRank={s.avg_iv_rank}
-          ivRankCount={s.iv_rank_count}
-        />
-      ))}
-    </div>
+    <Card aria-labelledby="sectors-title">
+      <h2 id="sectors-title" className="text-[1.0625rem] font-bold">
+        Sectors by IV rank
+      </h2>
+      <p className="mt-1 text-[0.8125rem] text-muted">The names the scan covers, by sector. A move is today&apos;s price change.</p>
+      {body}
+    </Card>
   );
-}
\ No newline at end of file
+}
````

### Task 10: The Research page

**Files:** Create `web/features/research/ResearchPage.tsx` (+ test); rewrite `web/app/research/page.tsx` to one mount;
delete `web/app/research/page.test.tsx` (its cases move into `ResearchPage.test.tsx`); modify `web/DESIGN.md` (the
Research surface, the Decision Log entry); this plan.

**What it does (ruling 10):** the frame, Search and Universe at the right, Top opportunities, then the two cards in
Stock's grid.

- [ ] **Step 1: da-vinci** with the Spec above; it reads the Research surface in the T10 patch.
- [ ] **Step 2: Check and apply `T10`.** `git status --short` shows `M web/DESIGN.md`, `M web/app/research/page.tsx`,
  `D web/app/research/page.test.tsx` and `?? web/features/research/ResearchPage.test.tsx`,
  `?? web/features/research/ResearchPage.tsx`.
- [ ] **Step 3: Gate.** `cd web && npx vitest run features/research`: 34 passed (ResearchPage 5 is a new module: red is
  "module missing"). Full vitest **1603 in 154 files**; tsc, lint clean; G3 exit 0; G4 green; G5.
- [ ] **Step 4: Commit** `feat(web): Research on the payslip: Top opportunities, Your watchlist and the sectors`.

<!-- block T10 -->
````diff
diff --git a/web/DESIGN.md b/web/DESIGN.md
index 33d7038..c076be5 100644
--- a/web/DESIGN.md
+++ b/web/DESIGN.md
@@ -979,7 +979,29 @@ the figure face.
   live-cutover gate asks for. Claude's cut is labelled as Claude's wherever its reason shows.
 
 ### Research
-Read. Search, watchlist, sectors, the stock page, and Universe. VARIANCE 3, DENSITY 6.
+Read. Search, watchlist, sectors, the stock page, and Universe. VARIANCE 3, DENSITY 6. Recomposed 2026-11-06 (web
+overhaul Part 6) on the Stock page's frame.
+
+- **THESIS:** what is worth a look today. The value book's candidates lead; the names the operator follows and
+  how each sector is doing follow them.
+- **FIRST VIEWPORT:** the title "Research" (24px, 800) with one muted line ("What the value book would buy, the
+  names you follow, and how each sector is doing."), Search (secondary, the magnifier; it opens the search
+  palette) and Universe (a secondary pill link) at the right, wrapping under the title on a phone; then
+  "Top opportunities" (17px, 700) with one muted line and the strip.
+- **FORM:** the 1200px frame (`px-4` on a phone, `px-7` from 768px). Top opportunities full width; then one grid
+  as Stock's: "Your watchlist" left and the Sectors card in a 340px column right from 1024px, each column one
+  `minmax(0,1fr)` track; the DOM order is the phone order.
+- **Your watchlist:** a white card. The title, the count at the right ("3 names"), one muted line ("Names you
+  follow here, so their quotes stay fresh. The scan's own watchlist is on Universe.", Universe a link), the
+  field "Follow a name" (a typeahead over the symbol directory; a pick adds at once: no order consequence, so no
+  dialog), then a row per name: the ticker bold and the company muted, a muted line "IV rank 80.0 · 3 of 5 checks
+  pass · Earnings Nov 19, 2026", the price at the right with "-1.25% today" under it (signed, never green or red:
+  a price move is not money) and "Delayed" as a flag word on a stale quote, and a quiet "Remove". The row is a
+  link to the stock page. Unknowns are hatched n/a (never "0 of 0"); loading holds its place; a failed read, add
+  or remove is a sentence.
+- **Sectors by IV rank:** one white card, a row per sector in the API's order: the name bold with "IV rank 42.0
+  (3)" at the right, then "3 names · +1.50% today", then "Best MSFT +2.00% · worst AAPL -1.00%", all in muted ink
+  apart from the names; no green or red. Loading holds its place; empty and failed are sentences.
 
 - **Top opportunities (2026-11-05):** a strip above the watchlist, headed "Top opportunities", with two tabs on
   the strategy-switch track, Deep value and Quality growth (only the list on view is fetched). Up to ten white
@@ -1159,6 +1181,14 @@ sibling keys; re-run the check after edits.
 
 ## Decision Log
 
+- 2026-11-06: **Research, Universe and the search palette on the payslip** (web overhaul Part 6). Added the Search
+  palette component (one dialog in the root layout: pages and tickers, the arrow keys, a status line in words),
+  the rail's Search row (Research's icon became a telescope so the magnifier means search alone), More's Search
+  row, and the Research and Universe Surfaces. The operator ruled that search finds tickers and the console's own
+  pages from a fixed list (no API change) and that Research's list is "Your watchlist", apart from the scan's own
+  on Universe. A watchlist or sector move is a price, not money, so it is signed and never green or red. No new
+  token, colour, font, radius or elevation.
+
 - 2026-11-06: **The stock page on the payslip** (web overhaul Part 5). Added the Stock surface. The chart keeps its
   candles (the HANDOFF's call: keep `PriceChart`, add the value book's levels) but draws them in ink with direction
   by shape, and the levels as dashed rules; every section is a card; the value block leads for a priced or held
diff --git a/web/app/research/page.test.tsx b/web/app/research/page.test.tsx
deleted file mode 100644
index 284e501..0000000
--- a/web/app/research/page.test.tsx
+++ /dev/null
@@ -1,48 +0,0 @@
-import { fireEvent, render, screen } from "@testing-library/react";
-import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
-import { describe, expect, it, vi } from "vitest";
-import { OPEN_SEARCH_EVENT } from "@/lib/search";
-import Home from "./page";
-
-vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
-
-vi.mock("@/lib/api", () => ({
-  apiFetch: vi.fn(async (path: string) => {
-    if (path.startsWith("/research/search")) {
-      return { as_of: "x", query: "", results: [] };
-    }
-    if (path === "/watchlist") return { as_of: "x", items: [] };
-    if (path === "/research/sectors") return { as_of: "x", sectors: [] };
-    return {};
-  }),
-}));
-
-function withClient(ui: React.ReactElement) {
-  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
-  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
-}
-
-describe("Home — visible search bar", () => {
-  it("renders a search bar trigger to the right of the Research heading", () => {
-    withClient(<Home />);
-    expect(screen.getByRole("button", { name: /search a ticker/i })).toBeDefined();
-  });
-
-  it("opens the console's one palette when clicked, instead of mounting its own", () => {
-    withClient(<Home />);
-    const seen = vi.fn();
-    window.addEventListener(OPEN_SEARCH_EVENT, seen);
-    fireEvent.click(screen.getByRole("button", { name: /search a ticker/i }));
-    window.removeEventListener(OPEN_SEARCH_EVENT, seen);
-    expect(seen).toHaveBeenCalledTimes(1);
-    expect(screen.queryByRole("dialog")).toBeNull();
-  });
-
-  it("puts Top opportunities above the watchlist", async () => {
-    withClient(<Home />);
-    const top = screen.getByRole("heading", { name: "Top opportunities" });
-    const watch = await screen.findByRole("heading", { name: "Your watchlist" });
-    expect(top.compareDocumentPosition(watch) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
-    expect(screen.getByRole("group", { name: "Opportunity list" })).toBeDefined();
-  });
-});
diff --git a/web/app/research/page.tsx b/web/app/research/page.tsx
index d2a5002..6dc1ec2 100644
--- a/web/app/research/page.tsx
+++ b/web/app/research/page.tsx
@@ -1,39 +1,5 @@
-"use client";
+import { ResearchPage } from "@/features/research/ResearchPage";
 
-import { SectorGrid } from "@/components/home/SectorGrid";
-import { WatchlistTable } from "@/components/home/WatchlistTable";
-import { TopOpportunities } from "@/features/research/TopOpportunities";
-import { openSearch } from "@/lib/search";
-
-export default function Home() {
-  return (
-    <div className="px-8 py-6">
-      <div className="flex items-center justify-between gap-4">
-        <h1 className="font-mono text-2xl text-content">Research</h1>
-        <button
-          type="button"
-          onClick={openSearch}
-          className="flex items-center gap-2 rounded border border-border bg-surface px-3 py-1.5 text-sm text-muted hover:text-content focus-visible:ring-focus"
-        >
-          <span>Search a ticker</span>
-          <kbd className="rounded border border-border bg-elevated px-2 py-0.5 font-mono text-xs text-content">
-            ⌘K
-          </kbd>
-        </button>
-      </div>
-
-      <section className="mt-10">
-        <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">Top opportunities</h2>
-        <TopOpportunities />
-      </section>
-
-      <div className="mt-10">
-        <WatchlistTable />
-      </div>
-
-      <div className="mt-10">
-        <SectorGrid />
-      </div>
-    </div>
-  );
-}
\ No newline at end of file
+export default function Page() {
+  return <ResearchPage />;
+}
diff --git a/web/features/research/ResearchPage.test.tsx b/web/features/research/ResearchPage.test.tsx
new file mode 100644
index 0000000..7376ab4
--- /dev/null
+++ b/web/features/research/ResearchPage.test.tsx
@@ -0,0 +1,55 @@
+import { fireEvent, screen } from "@testing-library/react";
+import { describe, expect, it, vi } from "vitest";
+import { renderWithQuery } from "@/lib/test-query";
+import { OPEN_SEARCH_EVENT } from "@/lib/search";
+import { ResearchPage } from "./ResearchPage";
+
+const served = {
+  "/value/top": { as_of: "x", available: true, list_name: "deep_value", items: [] },
+  "/watchlist": { as_of: "x", items: [] },
+  "/research/sectors": { as_of: "x", sectors: [] },
+};
+
+describe("ResearchPage", () => {
+  it("is titled Research, with a line saying what the page holds", () => {
+    renderWithQuery(<ResearchPage />, served);
+    expect(screen.getByRole("heading", { level: 1, name: "Research" })).toBeInTheDocument();
+    expect(screen.getByText("What the value book would buy, the names you follow, and how each sector is doing.")).toBeInTheDocument();
+  });
+
+  it("opens the console's one search palette instead of mounting its own", () => {
+    renderWithQuery(<ResearchPage />, served);
+    const seen = vi.fn();
+    window.addEventListener(OPEN_SEARCH_EVENT, seen);
+    const search = screen.getByRole("button", { name: "Search" });
+    expect(search).toHaveAttribute("data-variant", "secondary");
+    fireEvent.click(search);
+    window.removeEventListener(OPEN_SEARCH_EVENT, seen);
+    expect(seen).toHaveBeenCalledTimes(1);
+    expect(screen.queryByRole("dialog")).toBeNull();
+  });
+
+  it("links to Universe, the scan's own lists", () => {
+    renderWithQuery(<ResearchPage />, served);
+    expect(screen.getAllByRole("link", { name: "Universe" })[0]).toHaveAttribute("href", "/research/universe");
+  });
+
+  it("puts Top opportunities first, then Your watchlist, then the Sectors card, which is the phone's order", async () => {
+    renderWithQuery(<ResearchPage />, served);
+    const top = screen.getByRole("heading", { level: 2, name: "Top opportunities" });
+    const watch = await screen.findByRole("heading", { level: 2, name: "Your watchlist" });
+    const sectors = screen.getByRole("heading", { level: 2, name: "Sectors by IV rank" });
+    const follows = (a: Element, b: Element) => (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
+    expect(follows(top, watch)).toBe(true);
+    expect(follows(watch, sectors)).toBe(true);
+    expect(screen.getByRole("group", { name: "Opportunity list" })).toBeInTheDocument();
+  });
+
+  it("sizes both columns to one minmax(0,1fr) track, so a wide row never widens the page on a phone", async () => {
+    renderWithQuery(<ResearchPage />, served);
+    const watch = await screen.findByRole("heading", { level: 2, name: "Your watchlist" });
+    expect(watch.closest("section")?.parentElement).toHaveClass("grid-cols-1", "min-w-0");
+    const sectors = screen.getByRole("heading", { level: 2, name: "Sectors by IV rank" });
+    expect(sectors.closest("section")?.parentElement).toHaveClass("grid-cols-1", "min-w-0");
+  });
+});
diff --git a/web/features/research/ResearchPage.tsx b/web/features/research/ResearchPage.tsx
new file mode 100644
index 0000000..3fda9dd
--- /dev/null
+++ b/web/features/research/ResearchPage.tsx
@@ -0,0 +1,60 @@
+"use client";
+
+import Link from "next/link";
+import { Search } from "lucide-react";
+import { SectorGrid } from "@/components/home/SectorGrid";
+import { WatchlistTable } from "@/components/home/WatchlistTable";
+import { Button } from "@/components/ui/Button";
+import { openSearch } from "@/lib/search";
+import { TopOpportunities } from "./TopOpportunities";
+
+// A link to another page, drawn like the secondary button (OpportunityCard's LINK). Never lime.
+const LINK =
+  "inline-flex min-h-11 items-center justify-center rounded-full bg-sunk px-[18px] text-[1.0625rem] font-bold text-content hover:bg-sunk-deep";
+
+/**
+ * Research (web overhaul Part 6): the title with Search (it opens the console's one palette) and a link to
+ * Universe, then Top opportunities, then two columns from 1024px: Your watchlist on the left and the
+ * Sectors card in a 340px column on the right. The DOM order is the phone order. It reads and links; its
+ * only write is the per-user watchlist's add and remove (research.db, no order consequence).
+ */
+export function ResearchPage() {
+  return (
+    <div className="mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4">
+      <header className="mt-1 flex flex-wrap items-start justify-between gap-3">
+        <div className="min-w-0">
+          <h1 className="text-2xl font-extrabold tracking-[-0.015em]">Research</h1>
+          <p className="mt-1 text-sm text-muted">What the value book would buy, the names you follow, and how each sector is doing.</p>
+        </div>
+        <div className="flex flex-wrap gap-2">
+          <Button variant="secondary" onClick={openSearch} aria-keyshortcuts="Meta+K Control+K">
+            <Search aria-hidden="true" size={18} />
+            Search
+          </Button>
+          <Link href="/research/universe" className={LINK}>
+            Universe
+          </Link>
+        </div>
+      </header>
+
+      <section aria-labelledby="top-title" className="mt-6">
+        <h2 id="top-title" className="text-[1.0625rem] font-bold">
+          Top opportunities
+        </h2>
+        <p className="mt-1 text-[0.8125rem] text-muted">The value book&apos;s names on each list, Ready first. Python&apos;s gates decide; nothing here trades.</p>
+        <div className="mt-3">
+          <TopOpportunities />
+        </div>
+      </section>
+
+      <div className="mt-6 grid items-start gap-x-6 gap-y-4 lg:grid-cols-[minmax(0,1fr)_340px]">
+        <div className="grid min-w-0 grid-cols-1">
+          <WatchlistTable />
+        </div>
+        <div className="grid min-w-0 grid-cols-1">
+          <SectorGrid />
+        </div>
+      </div>
+    </div>
+  );
+}
````

### Task 11: Claude's note

**Files:** Modify `web/features/research/OpportunityCard.tsx` (+ test), `web/DESIGN.md`; this plan.

**What it does (ruling 13):** the note after Python's reasons, labelled, never on a link or button; nothing when null.

- [ ] **Step 1: da-vinci** with the Spec above.
- [ ] **Step 2: Check and apply `T11`.** `git status --short` shows three `M` files.
- [ ] **Step 3: Red check.** `git stash push -- web/features/research/OpportunityCard.tsx`, then
  `cd web && npx vitest run features/research/OpportunityCard.test.tsx` ends `1 failed | 10 passed (11)`, then
  `git stash pop`.
- [ ] **Step 4: Gate.** `npx vitest run features/research`: 36 passed. Full vitest **1605 in 154 files**; tsc, lint
  clean; G1, G2, G3, G5, G7.
- [ ] **Step 5: Commit** `feat(web): Claude's one-line note on Top opportunities, labelled as Claude's`.

<!-- block T11 -->
````diff
diff --git a/web/DESIGN.md b/web/DESIGN.md
index c076be5..90b753d 100644
--- a/web/DESIGN.md
+++ b/web/DESIGN.md
@@ -1019,8 +1019,10 @@ overhaul Part 6) on the Stock page's frame.
   nothing: "See the value file" (READY only) goes to the stock page's value block, which reads the file (the book's decide flow lives on Home's Value card, not here);
   "Sell a put up to $190.00" appears only when the book has a put ceiling and the latest scan has a passed
   cash-secured put at or under it, and opens Trades, Assessed on that name. The strip sends no command and has no
-  button but the two tabs. Claude's one-line note is not shown yet: the API carries it since web overhaul Part 5
-  (`claude_note`, from Claude's own reads only) and the card shows it from Part 6. Unavailable
+  button but the two tabs. Since web overhaul Part 6 Claude's one-line note (`claude_note`, from Claude's own
+  reads only) follows Python's reasons in a pressed-sage block labelled "Claude's note" with "its reading, not a
+  gate" beside it, at most 65 characters wide; a name Claude has not read for the list shows no label at all. It
+  is never on a button. Unavailable
   reads "The value book has not written anything yet."; an empty list names the list. No new token, colour,
   font, radius or elevation.
 
diff --git a/web/features/research/OpportunityCard.test.tsx b/web/features/research/OpportunityCard.test.tsx
index 4e37f28..0795fcf 100644
--- a/web/features/research/OpportunityCard.test.tsx
+++ b/web/features/research/OpportunityCard.test.tsx
@@ -109,4 +109,19 @@ describe("OpportunityCard", () => {
     const age = screen.getByText(/^Scorecard/);
     expect(within(age).getByText("n/a").className).toContain("hatch");
   });
+
+  it("shows Claude's one-line note after Python's reasons, labelled as Claude's and never on a link or button", () => {
+    render(<OpportunityCard item={item({ claude_note: "Search share is holding; the cloud margin carries the bear case." })} canSellPut />);
+    const note = screen.getByText("Search share is holding; the cloud margin carries the bear case.");
+    expect(screen.getByText("Claude's note")).toBeTruthy();
+    expect(screen.getByText("its reading, not a gate")).toBeTruthy();
+    expect(note.closest("a, button")).toBeNull();
+    const reasons = screen.getByText("Python's reasons");
+    expect(reasons.compareDocumentPosition(note) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
+  });
+
+  it("shows no note, and no empty label, when Claude has not read the name for this list", () => {
+    render(<OpportunityCard item={item({ claude_note: null })} canSellPut={false} />);
+    expect(screen.queryByText("Claude's note")).toBeNull();
+  });
 });
diff --git a/web/features/research/OpportunityCard.tsx b/web/features/research/OpportunityCard.tsx
index 5918fdf..cb82a18 100644
--- a/web/features/research/OpportunityCard.tsx
+++ b/web/features/research/OpportunityCard.tsx
@@ -2,7 +2,7 @@ import Link from "next/link";
 import { Card } from "@/components/ui/Card";
 import { StatusWord } from "@/components/ui/StatusWord";
 import { price } from "@/components/value/format";
-import { Hatched } from "@/features/stock-value/parts";
+import { ClaudeLabel, Hatched } from "@/features/stock-value/parts";
 import { PriceBar } from "./PriceBar";
 import { ageWords, assessedHref, fractionPct, layoutBar, listWords, reasonSentence, stockValueHref, verdictWords } from "./format";
 import type { TopItem } from "./types";
@@ -14,7 +14,9 @@ const LINK =
 /**
  * One name on a Top opportunities list. It reads and links; it sends nothing. "See the value file" goes to
  * the stock page's value block, where the book's own decide flow lives; the put link goes to the
- * name's passed cash-secured puts in Trades, and exists only when the parent found one.
+ * name's passed cash-secured puts in Trades, and exists only when the parent found one. Claude's one-line
+ * note (`claude_note`, Claude's own reads only) sits after Python's reasons in a pressed-sage block labelled
+ * as Claude's, never on a button (web overhaul Part 6).
  */
 export function OpportunityCard({ item, canSellPut }: { item: TopItem; canSellPut: boolean }) {
   const titleId = `opp-${item.list_name}-${item.symbol}`;
@@ -64,6 +66,13 @@ export function OpportunityCard({ item, canSellPut }: { item: TopItem; canSellPu
         </div>
       )}
 
+      {item.claude_note && (
+        <div className="mt-3 rounded-xl bg-sunk px-3 py-2">
+          <ClaudeLabel label="Claude's note" note="its reading, not a gate" />
+          <p className="mt-0.5 max-w-[65ch] text-sm">{item.claude_note}</p>
+        </div>
+      )}
+
       {(ready || showPut) && (
         <div className="mt-4 flex flex-wrap gap-2">
           {ready && (
````

---

## Section D: Universe (Tasks 12-13) · model: sonnet (effort medium)

**Reads:** this section; `web/DESIGN.md` (Components: Card, Field, Status word; the new Universe surface is in T12's
patch); `web/app/research/universe/page.tsx`; `web/components/universe/*`; `web/features/stock/StockPage.tsx` (lines
30-45, the back link and frame).

**Spec for da-vinci:** the Universe surface paragraph in T12's DESIGN.md hunk. Classes and copy are fixed by the
patches (the frame and back link as Stock's; a `Card` per list; the tags `rounded-[6px] bg-sunk px-2 py-px text-xs
font-semibold tracking-[0.04em]`; Remove and Revert `min-h-11` on a phone; the `field` with a visible label). Never edit
`components/options/ConfirmAction.tsx` or `CommandReceipt.tsx`, and never change the would-own confirmation's text.

**Entry checks:**

- [ ] **D1. Section C landed.** Four task commits since Section B; vitest 1605 in 154 files.
- [ ] **D2. Both patches apply** (disjoint files): `git apply --check <S>/p6/T12.out` and `T13.out`: each prints nothing.
- [ ] **D3. The universe suite as written.** `grep -c "it(" web/components/universe/UniverseList.test.tsx` prints `18`.

**Section exit:** two task commits; vitest **1611 in 156 files**; tsc, lint clean; G1-G5, G7.

### Task 12: The Universe page

**Files:** Create `web/features/universe/UniversePage.tsx` (+ test); rewrite `web/app/research/universe/page.tsx` to
one mount; modify `web/components/universe/UniverseList.tsx` (+ test, two strings), `web/DESIGN.md`; this plan.

**What it does (ruling 14):** the page and the list cards described in the Spec.

- [ ] **Step 1: da-vinci** with the Spec above.
- [ ] **Step 2: Check and apply `T12`.** `git status --short` shows four `M` files and `?? web/features/universe/`.
- [ ] **Step 3: Red check.** `git stash push -- web/components/universe/UniverseList.tsx`, then
  `cd web && npx vitest run components/universe features/universe` ends `2 failed | 19 passed (21)`, then `git stash pop`.
- [ ] **Step 4: Gate.** `npx vitest run components/universe features/universe`: 21 passed. Full vitest **1608 in 155
  files**; tsc, lint clean; G3 exit 0; G5.
- [ ] **Step 5: Commit** `feat(web): Universe on the payslip: a card per list, each saying what it is for`.

<!-- block T12 -->
````diff
diff --git a/web/DESIGN.md b/web/DESIGN.md
index 90b753d..6af6d4c 100644
--- a/web/DESIGN.md
+++ b/web/DESIGN.md
@@ -1058,6 +1058,25 @@ overhaul Part 6) on the Stock page's frame.
   a higher low, at least 10 sessions after the last, and passes the value gate again first."). No new
   token, colour, font, radius or elevation.
 
+### Universe
+Read and Operate. The names the scan covers, recomposed 2026-11-06 (web overhaul Part 6) on the Stock page's frame.
+- **FIRST VIEWPORT:** a back link to Research, the title "Universe" (24px, 800) and one muted line ("The names
+  the scan covers. Would own and Watchlist take add and remove here; Indexes and Actively wheeling are set in
+  config/universe.yaml."), then the list cards.
+- **FORM:** one white card per list in the API's order (Indexes, Watchlist, Would own, Actively wheeling), two
+  `minmax(0,1fr)` columns from 1024px, one below. A card: the list's name (17px, 700) with "12 names" at the
+  right, one muted line on what the list is for (Would own: "The cash-secured-put allowlist: the system may sell
+  puts on these names, so it may be assigned their shares."), the read-only note on the two file-managed lists
+  ("Managed in config/universe.yaml. No add or remove control here."), the add field on the two others, then
+  hairline rows: the ticker bold (a link to the stock page, 44px on a phone), the sector, "Wheeling" or
+  "Dip-watch" as neutral status words on Would own, "Strike band 0.85", and a quiet Remove. An override keeps its
+  badge (who and when, and Revert) under the row, and a removed base name stays listed, struck through. A
+  failed command is a sentence, never red.
+- **Safety, unchanged:** adding to Would own opens the existing confirmation, which names the cash-secured put
+  and the assignment; Watchlist adds at once; every change is a command with its receipt. `sectors` stays
+  file-only, so nothing here reaches the concentration limits.
+- No new token, colour, font, radius or elevation.
+
 ### Stock
 Read. One name, and everything the system knows about it. VARIANCE 3, DENSITY 6. Recomposed 2026-11-06 (web
 overhaul Part 5) on the Position page's frame.
diff --git a/web/app/research/universe/page.tsx b/web/app/research/universe/page.tsx
index 2d2c9a7..1639d37 100644
--- a/web/app/research/universe/page.tsx
+++ b/web/app/research/universe/page.tsx
@@ -1,67 +1,5 @@
-"use client";
+import { UniversePage } from "@/features/universe/UniversePage";
 
-import { useQuery } from "@tanstack/react-query";
-import { apiFetch } from "@/lib/api";
-import type { ControlsResponse } from "@/components/options/types";
-import { UniverseList } from "@/components/universe/UniverseList";
-import type { UniverseResponse } from "@/components/universe/types";
-
-export default function UniversePage() {
-  const { data, isLoading } = useQuery({
-    queryKey: ["universe"],
-    queryFn: () => apiFetch<UniverseResponse>("/universe"),
-  });
-
-  // Same self-fetch pattern ApprovalDetailCard/AssessedBrowser use for
-  // drainHealthy: defaults to true while loading so an unloaded drain is
-  // never falsely reported as dead.
-  const { data: controls } = useQuery({
-    queryKey: ["options", "controls"],
-    queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
-    placeholderData: (prev) => prev,
-    refetchInterval: 30_000,
-  });
-  const drainHealthy = controls?.drain_healthy ?? true;
-
-  if (isLoading || !data) {
-    return (
-      <div className="px-8 py-6">
-        <h1 className="font-mono text-2xl text-content">Universe</h1>
-        <p className="mt-4 text-sm text-muted">Loading</p>
-      </div>
-    );
-  }
-
-  // The symbols currently being actively wheeled, used to tell the two
-  // would_own tiers apart at a glance: "wheeling" vs "dip-watch" (pre-M7
-  // behaviour, restored in UniverseList). Passed to every list instance;
-  // UniverseList only uses it for the would_own section.
-  const activelyWheeling = new Set(
-    (data.lists.find((list) => list.name === "actively_wheeling")?.entries ?? []).map(
-      (entry) => entry.symbol,
-    ),
-  );
-
-  return (
-    <div className="px-8 py-6">
-      <header className="mb-8">
-        <h1 className="font-mono text-2xl text-content">Universe</h1>
-        <p className="mt-1 text-sm text-muted">
-          The scan universe. Watchlist and would-own accept add and remove; indexes and
-          actively wheeling are managed in config/universe.yaml.
-        </p>
-      </header>
-
-      {data.lists.map((list) => (
-        <UniverseList
-          key={list.name}
-          list={list}
-          sectors={data.sectors}
-          strikeBands={data.strike_bands}
-          drainHealthy={drainHealthy}
-          activelyWheeling={activelyWheeling}
-        />
-      ))}
-    </div>
-  );
+export default function Page() {
+  return <UniversePage />;
 }
diff --git a/web/components/universe/UniverseList.test.tsx b/web/components/universe/UniverseList.test.tsx
index 0ee9ea6..001a732 100644
--- a/web/components/universe/UniverseList.test.tsx
+++ b/web/components/universe/UniverseList.test.tsx
@@ -314,12 +314,12 @@ describe("UniverseList — would_own entries are tagged wheeling vs dip-watch",
     );
 
     const wheelingTag = screen.getByTestId("wheeling-tag-NVDA");
-    expect(wheelingTag.textContent).toBe("wheeling");
+    expect(wheelingTag.textContent).toBe("Wheeling");
     expect(wheelingTag.className).toMatch(/text-content/);
     expect(screen.queryByTestId("dip-watch-tag-NVDA")).toBeNull();
 
     const dipWatchTag = screen.getByTestId("dip-watch-tag-AAPL");
-    expect(dipWatchTag.textContent).toBe("dip-watch");
+    expect(dipWatchTag.textContent).toBe("Dip-watch");
     expect(dipWatchTag.className).toMatch(/text-muted/);
     expect(screen.queryByTestId("wheeling-tag-AAPL")).toBeNull();
   });
diff --git a/web/components/universe/UniverseList.tsx b/web/components/universe/UniverseList.tsx
index 24544f7..63260f9 100644
--- a/web/components/universe/UniverseList.tsx
+++ b/web/components/universe/UniverseList.tsx
@@ -10,6 +10,7 @@ import {
   type CommandStatus,
 } from "@/lib/commands";
 import { CommandReceipt } from "@/components/options/CommandReceipt";
+import { Card } from "@/components/ui/Card";
 import { OverrideBadge } from "./OverrideBadge";
 import { AddSymbol } from "./AddSymbol";
 import type { UniverseEntry, UniverseListOut } from "./types";
@@ -28,6 +29,12 @@ import type { UniverseEntry, UniverseListOut } from "./types";
  * (defence in depth, matching the backend's own discipline), even though the
  * two non-overridable lists never carry `overridden: true` entries in
  * practice.
+ *
+ * Web overhaul Part 6 restyled it in place: each list is a white Card with a
+ * 17px title, the count at the right and one line saying what the list is
+ * for; rows are hairline-separated; the tags are status words; Remove is a
+ * quiet 44px button on a phone. The behaviour, the test ids and the command
+ * flow are unchanged.
  */
 export function UniverseList({
   list,
@@ -49,20 +56,32 @@ export function UniverseList({
    */
   activelyWheeling?: Set<string>;
 }) {
+  const titleId = `universe-${list.name}-title`;
   return (
-    <section className="mb-10" data-testid={`universe-list-${list.name}`}>
-      <h2 className="mb-1 text-sm font-medium tracking-wide text-muted">
-        {listLabel(list.name)} ({list.entries.length})
-      </h2>
+    <Card aria-labelledby={titleId} data-testid={`universe-list-${list.name}`}>
+      <div className="flex items-baseline justify-between gap-3">
+        <h2 id={titleId} className="text-[1.0625rem] font-bold">
+          {listLabel(list.name)}
+        </h2>
+        <span className="tabular shrink-0 text-[0.8125rem] text-muted">
+          {list.entries.length === 1 ? "1 name" : `${list.entries.length} names`}
+        </span>
+      </div>
+      <p className="mt-1 text-[0.8125rem] text-muted">{listPurpose(list.name)}</p>
       {!list.overridable && (
-        <p className="mb-3 text-xs text-muted" data-testid={`readonly-note-${list.name}`}>
+        <p className="mt-1 text-[0.8125rem] text-muted" data-testid={`readonly-note-${list.name}`}>
           Managed in config/universe.yaml. No add or remove control here.
         </p>
       )}
+      {list.overridable && (
+        <div className="mt-3">
+          <AddSymbol listName={list.name as "would_own" | "watchlist"} drainHealthy={drainHealthy} />
+        </div>
+      )}
       {list.entries.length === 0 ? (
-        <p className="text-sm text-muted">None</p>
+        <p className="mt-3 text-sm">None</p>
       ) : (
-        <ul className="divide-y divide-border">
+        <ul className="mt-2">
           {list.entries.map((entry) => (
             <EntryRow
               key={entry.symbol}
@@ -77,12 +96,7 @@ export function UniverseList({
           ))}
         </ul>
       )}
-      {list.overridable && (
-        <div className="mt-3">
-          <AddSymbol listName={list.name as "would_own" | "watchlist"} drainHealthy={drainHealthy} />
-        </div>
-      )}
-    </section>
+    </Card>
   );
 }
 
@@ -93,7 +107,7 @@ function listLabel(name: string): string {
     case "watchlist":
       return "Watchlist";
     case "would_own":
-      return "Would own - CSP allowlist";
+      return "Would own";
     case "actively_wheeling":
       return "Actively wheeling";
     default:
@@ -101,6 +115,22 @@ function listLabel(name: string): string {
   }
 }
 
+/** One line on what a list is for, in the operator's terms. */
+function listPurpose(name: string): string {
+  switch (name) {
+    case "indexes":
+      return "The indexes the regime and the market picture read.";
+    case "watchlist":
+      return "Names the scan reports on. It never sells a put on them.";
+    case "would_own":
+      return "The cash-secured-put allowlist: the system may sell puts on these names, so it may be assigned their shares.";
+    case "actively_wheeling":
+      return "The names the wheel is working now.";
+    default:
+      return "";
+  }
+}
+
 function EntryRow({
   entry,
   listName,
@@ -156,43 +186,43 @@ function EntryRow({
   const showPlainRemove = overridable && !entry.overridden;
 
   return (
-    <li className="py-2">
-      <div className="flex flex-wrap items-center gap-3">
+    <li className="border-t border-border py-2 first:border-t-0">
+      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
         <Link
           href={`/stock/${entry.symbol}`}
           className={
-            "tabular font-mono text-sm hover:text-focus focus-visible:ring-focus " +
+            "tabular inline-flex min-h-11 items-center font-bold underline-offset-2 hover:underline md:min-h-8 " +
             (entry.removed ? "text-muted line-through" : "text-content")
           }
         >
           {entry.symbol}
         </Link>
-        {sector && <span className="text-xs text-muted">{sector}</span>}
+        {sector && <span className="text-[0.8125rem] text-muted">{sector}</span>}
         {listName === "would_own" && !entry.removed && (
           wheeling?.has(entry.symbol) ? (
             <span
-              className="rounded-sm bg-elevated px-1.5 py-0.5 text-xs text-content"
+              className="rounded-[6px] bg-sunk px-2 py-px text-xs font-semibold tracking-[0.04em] text-content"
               data-testid={`wheeling-tag-${entry.symbol}`}
             >
-              wheeling
+              Wheeling
             </span>
           ) : (
             <span
-              className="rounded-sm bg-elevated px-1.5 py-0.5 text-xs text-muted"
+              className="rounded-[6px] bg-sunk px-2 py-px text-xs font-semibold tracking-[0.04em] text-muted"
               data-testid={`dip-watch-tag-${entry.symbol}`}
             >
-              dip-watch
+              Dip-watch
             </span>
           )
         )}
-        {band != null && <span className="text-xs text-unknown">band {band.toFixed(2)}</span>}
+        {band != null && <span className="tabular text-[0.8125rem] text-muted">{`Strike band ${band.toFixed(2)}`}</span>}
 
         {showPlainRemove && (
           <button
             type="button"
             disabled={inFlight}
             onClick={() => fire("remove")}
-            className="ml-auto rounded-sm border border-border bg-background px-2 py-1 text-xs text-content enabled:hover:bg-elevated disabled:cursor-default disabled:opacity-50 focus-visible:ring-focus"
+            className="ml-auto inline-flex min-h-11 items-center rounded-full px-3 text-[0.8125rem] font-semibold text-muted enabled:hover:bg-sunk enabled:hover:text-content disabled:opacity-50 md:min-h-8"
             data-testid={`remove-${entry.symbol}`}
           >
             Remove
@@ -211,11 +241,7 @@ function EntryRow({
       )}
 
       {error && (
-        <p
-          className="mt-1 text-xs text-loss"
-          role="alert"
-          data-testid={`entry-error-${entry.symbol}`}
-        >
+        <p className="mt-1 text-sm" role="alert" data-testid={`entry-error-${entry.symbol}`}>
           {error}
         </p>
       )}
diff --git a/web/features/universe/UniversePage.test.tsx b/web/features/universe/UniversePage.test.tsx
new file mode 100644
index 0000000..9fad6f2
--- /dev/null
+++ b/web/features/universe/UniversePage.test.tsx
@@ -0,0 +1,71 @@
+import { screen } from "@testing-library/react";
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { render } from "@testing-library/react";
+import { describe, expect, it } from "vitest";
+import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
+import { UniversePage } from "./UniversePage";
+
+const entry = (symbol: string) => ({ symbol, overridden: false, removed: false, created_by: null, created_at: null });
+
+const universe = {
+  as_of: "x",
+  lists: [
+    { name: "indexes", overridable: false, entries: [entry("SPY")] },
+    { name: "watchlist", overridable: true, entries: [entry("PLTR")] },
+    { name: "would_own", overridable: true, entries: [entry("NVDA"), entry("KO")] },
+    { name: "actively_wheeling", overridable: false, entries: [entry("NVDA")] },
+  ],
+  sectors: { NVDA: "Semis" },
+  strike_bands: {},
+  editable: true,
+};
+
+const controls = {
+  as_of: "", autonomy: { level: "approve", label: "Approve each trade" }, rungs: [], halted: false,
+  halt_reason: null, halted_at: null, mode: "paper", drain_healthy: true, drain_last_seen: null, pending_commands: 0,
+};
+
+describe("UniversePage", () => {
+  it("leads back to Research, then the title and what can be changed here", async () => {
+    renderWithQuery(<UniversePage />, { "/universe": universe, "/options/controls": controls });
+    expect(screen.getByRole("link", { name: "Research" })).toHaveAttribute("href", "/research");
+    expect(screen.getByRole("heading", { level: 1, name: "Universe" })).toBeInTheDocument();
+    expect(screen.getByText(/Would own and Watchlist take add and remove here/)).toBeInTheDocument();
+  });
+
+  it("draws one card per list, in the API's order, with each list's count", async () => {
+    renderWithQuery(<UniversePage />, { "/universe": universe, "/options/controls": controls });
+    await screen.findByRole("heading", { level: 2, name: "Indexes" });
+    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
+      "Indexes",
+      "Watchlist",
+      "Would own",
+      "Actively wheeling",
+    ]);
+    expect(screen.getAllByText("2 names")).toHaveLength(1);
+    expect(screen.getByTestId("wheeling-tag-NVDA")).toHaveTextContent("Wheeling");
+    expect(screen.getByTestId("dip-watch-tag-KO")).toHaveTextContent("Dip-watch");
+  });
+
+  it("holds its place while loading, and says a failed read in words", async () => {
+    apiFetchMock.mockImplementation(() => new Promise(() => {}));
+    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+    const first = render(
+      <QueryClientProvider client={qc}>
+        <UniversePage />
+      </QueryClientProvider>,
+    );
+    expect(screen.getByRole("status", { name: "Loading the universe" })).toBeInTheDocument();
+    first.unmount();
+    apiFetchMock.mockImplementation(async () => {
+      throw new Error("down");
+    });
+    const qc2 = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+    render(
+      <QueryClientProvider client={qc2}>
+        <UniversePage />
+      </QueryClientProvider>,
+    );
+    expect(await screen.findByText("The universe could not be loaded right now.")).toBeInTheDocument();
+  });
+});
diff --git a/web/features/universe/UniversePage.tsx b/web/features/universe/UniversePage.tsx
new file mode 100644
index 0000000..8ab4eaa
--- /dev/null
+++ b/web/features/universe/UniversePage.tsx
@@ -0,0 +1,82 @@
+"use client";
+
+import Link from "next/link";
+import { useQuery } from "@tanstack/react-query";
+import { ChevronLeft } from "lucide-react";
+import type { ControlsResponse } from "@/components/options/types";
+import { UniverseList } from "@/components/universe/UniverseList";
+import type { UniverseResponse } from "@/components/universe/types";
+import { apiFetch } from "@/lib/api";
+
+/**
+ * Universe (web overhaul Part 6): a back link to Research, the title and one line on what can be changed
+ * here, then one card per list, two columns from 1024px. Would own and Watchlist take add and remove
+ * through `components/universe` (a would-own add confirms first, naming the put and the assignment); the
+ * other two lists are set in config/universe.yaml and say so. `sectors` stays file-only.
+ */
+export function UniversePage() {
+  const { data, isError } = useQuery({
+    queryKey: ["universe"],
+    queryFn: () => apiFetch<UniverseResponse>("/universe"),
+  });
+
+  // Defaults to healthy while loading, so an unloaded drain is never reported as dead.
+  const { data: controls } = useQuery({
+    queryKey: ["options", "controls"],
+    queryFn: () => apiFetch<ControlsResponse>("/options/controls"),
+    placeholderData: (prev) => prev,
+    refetchInterval: 30_000,
+  });
+  const drainHealthy = controls?.drain_healthy ?? true;
+
+  let body;
+  if (!data && isError) {
+    body = <p className="mt-4 text-sm">The universe could not be loaded right now.</p>;
+  } else if (!data) {
+    body = (
+      <div role="status" aria-busy="true" aria-label="Loading the universe" className="mt-4 grid gap-4 lg:grid-cols-2">
+        <div className="h-48 rounded-[18px] bg-surface" />
+        <div className="h-48 rounded-[18px] bg-surface" />
+      </div>
+    );
+  } else {
+    // The names being wheeled now tell the two would-own tiers apart: Wheeling or Dip-watch.
+    const activelyWheeling = new Set(
+      (data.lists.find((list) => list.name === "actively_wheeling")?.entries ?? []).map((entry) => entry.symbol),
+    );
+    body = (
+      <div className="mt-4 grid grid-cols-1 items-start gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
+        {data.lists.map((list) => (
+          <UniverseList
+            key={list.name}
+            list={list}
+            sectors={data.sectors}
+            strikeBands={data.strike_bands}
+            drainHealthy={drainHealthy}
+            activelyWheeling={activelyWheeling}
+          />
+        ))}
+      </div>
+    );
+  }
+
+  return (
+    <div className="mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4">
+      <Link
+        href="/research"
+        className="inline-flex min-h-11 items-center gap-1 text-[0.8125rem] font-semibold text-muted hover:text-content md:min-h-8"
+      >
+        <ChevronLeft size={16} aria-hidden="true" />
+        Research
+      </Link>
+      <header className="mt-1">
+        <h1 className="text-2xl font-extrabold tracking-[-0.015em]">Universe</h1>
+        <p className="mt-1 max-w-[65ch] text-sm text-muted">
+          The names the scan covers. Would own and Watchlist take add and remove here; Indexes and Actively wheeling
+          are set in config/universe.yaml.
+        </p>
+      </header>
+      {body}
+    </div>
+  );
+}
````

### Task 13: The add field and the override badge

**Files:** Modify `web/components/universe/AddSymbol.tsx`, `OverrideBadge.tsx`; create
`web/components/universe/restyle.test.tsx`; this plan.

**What it does (ruling 14):** a visible label on the `field`, 44px hit rows, a plain failure sentence; the badge as a
status word, a 44px Revert on a phone, a hatched unknown author.

- [ ] **Step 1: da-vinci** with the Spec above.
- [ ] **Step 2: Check and apply `T13`.** `git status --short` shows two `M` files and `?? web/components/universe/restyle.test.tsx`.
- [ ] **Step 3: Red check.** `git stash push -- web/components/universe/AddSymbol.tsx web/components/universe/OverrideBadge.tsx`,
  then `cd web && npx vitest run components/universe/restyle.test.tsx` ends `3 failed (3)`, then `git stash pop`.
- [ ] **Step 4: Gate.** `npx vitest run components/universe features/universe`: 24 passed. Full vitest **1611 in 156
  files**; tsc, lint clean; G1, G2, G5, G7; G4 green.
- [ ] **Step 5: Commit** `feat(web): the universe add field and override badge on the payslip`.

<!-- block T13 -->
````diff
diff --git a/web/components/universe/AddSymbol.tsx b/web/components/universe/AddSymbol.tsx
index 387caf3..3102da8 100644
--- a/web/components/universe/AddSymbol.tsx
+++ b/web/components/universe/AddSymbol.tsx
@@ -1,6 +1,6 @@
 "use client";
 
-import { useEffect, useState } from "react";
+import { useEffect, useId, useState } from "react";
 import { useQueryClient } from "@tanstack/react-query";
 import { ApiError, apiFetch } from "@/lib/api";
 import {
@@ -10,6 +10,8 @@ import {
 } from "@/lib/commands";
 import { ConfirmAction } from "@/components/options/ConfirmAction";
 import { CommandReceipt } from "@/components/options/CommandReceipt";
+import { StatusWord } from "@/components/ui/StatusWord";
+import { FIELD, FIELD_LABEL } from "@/components/ui/field";
 
 type Hit = { symbol: string; name: string; exchange: string | null; is_etf: boolean };
 type SearchResponse = { as_of: string; query: string; results: Hit[] };
@@ -34,6 +36,11 @@ type SearchResponse = { as_of: string; query: string; results: Hit[] };
  * Universe write routes never return `needs_confirmation: true`, so there is
  * no live-mode second-confirmation step to build here (unlike `HaltControl`/
  * `AssessedRow`).
+ *
+ * Web overhaul Part 6 restyled it in place: a visible label above the
+ * console's 44px field, the hits as a white panel with 44px rows on a phone,
+ * and a failure in plain words. The confirmation, its consequence text and
+ * the command flow are unchanged.
  */
 export function AddSymbol({
   listName,
@@ -50,6 +57,7 @@ export function AddSymbol({
   const [submitting, setSubmitting] = useState(false);
 
   const qc = useQueryClient();
+  const inputId = useId();
 
   // Poll every 2s while pending; stop once terminal (lib/commands.ts).
   const commandQuery = useCommandStatus(command?.id ?? null);
@@ -116,19 +124,22 @@ export function AddSymbol({
   }
 
   return (
-    <div data-testid={`add-symbol-${listName}`}>
+    <div data-testid={`add-symbol-${listName}`} className="max-w-sm">
+      <label htmlFor={inputId} className={FIELD_LABEL}>
+        {listName === "would_own" ? "Add a name to Would own" : "Add a name to Watchlist"}
+      </label>
       <input
+        id={inputId}
         value={term}
         disabled={inFlight}
         onChange={(e) => setTerm(e.target.value)}
         placeholder="Add a symbol"
-        aria-label={`Add a symbol to ${listName}`}
         autoComplete="off"
-        className="w-full max-w-xs rounded-sm border border-border bg-background px-2 py-1 font-mono text-sm text-content outline-none placeholder:text-muted focus-visible:border-focus disabled:opacity-50"
+        className={`${FIELD} mt-1 w-full disabled:opacity-50`}
       />
       {hits.length > 0 && (
         <ul
-          className="mt-1 max-w-xs rounded-sm border border-border bg-surface"
+          className="mt-1 rounded-xl border border-control bg-surface py-1"
           data-testid={`add-symbol-hits-${listName}`}
         >
           {hits.map((h) => (
@@ -136,23 +147,23 @@ export function AddSymbol({
               <button
                 type="button"
                 onClick={() => pick(h)}
-                className="flex w-full items-baseline gap-3 px-2 py-1 text-left text-sm hover:bg-elevated focus-visible:bg-elevated"
+                className="flex min-h-11 w-full items-center gap-3 px-3 text-left text-sm hover:bg-sunk focus-visible:bg-sunk md:min-h-9"
               >
-                <span className="tabular font-mono text-content">{h.symbol}</span>
-                <span className="truncate text-xs text-muted">{h.name}</span>
-                {h.is_etf && <span className="ml-auto text-[11px] text-muted">ETF</span>}
+                <span className="tabular font-semibold">{h.symbol}</span>
+                <span className="min-w-0 flex-1 truncate text-muted">{h.name}</span>
+                {h.is_etf && <StatusWord>ETF</StatusWord>}
               </button>
             </li>
           ))}
         </ul>
       )}
       {term.trim() && hits.length === 0 && (
-        <p className="mt-1 text-xs text-muted">No match</p>
+        <p className="mt-1 text-[0.8125rem] text-muted">No ticker matches yet.</p>
       )}
 
       {error && (
         <p
-          className="mt-1 text-xs text-loss"
+          className="mt-1 text-sm"
           role="alert"
           data-testid={`add-symbol-error-${listName}`}
         >
diff --git a/web/components/universe/OverrideBadge.tsx b/web/components/universe/OverrideBadge.tsx
index ddf8832..765147a 100644
--- a/web/components/universe/OverrideBadge.tsx
+++ b/web/components/universe/OverrideBadge.tsx
@@ -33,22 +33,22 @@ export function OverrideBadge({
 
   return (
     <div
-      className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted"
+      className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8125rem] text-muted"
       data-testid="override-badge"
       data-removed={removed}
     >
-      <span className="rounded-sm bg-elevated px-1.5 py-0.5 text-content">
+      <span className="rounded-[6px] bg-sunk px-2 py-px text-xs font-semibold tracking-[0.04em] text-content">
         {removed ? "Removed override" : "Override"}
       </span>
       <span>
-        {removed ? "removed" : "added"} by {author ?? "n/a"}
+        {removed ? "removed" : "added"} by {author ?? <span className="hatch px-1 text-unknown">n/a</span>}
         {age ? ` · ${age}` : ""}
       </span>
       <button
         type="button"
         disabled={disabled}
         onClick={onRevert}
-        className="text-content underline enabled:hover:text-focus disabled:cursor-default disabled:opacity-50 focus-visible:ring-focus"
+        className="inline-flex min-h-11 items-center font-semibold text-content underline underline-offset-2 enabled:hover:text-muted disabled:cursor-default disabled:opacity-50 md:min-h-0"
         data-testid="revert-button"
       >
         {removed ? "Revert (add back)" : "Revert"}
diff --git a/web/components/universe/restyle.test.tsx b/web/components/universe/restyle.test.tsx
new file mode 100644
index 0000000..10ef120
--- /dev/null
+++ b/web/components/universe/restyle.test.tsx
@@ -0,0 +1,36 @@
+import { fireEvent, render, screen } from "@testing-library/react";
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { describe, expect, it, vi } from "vitest";
+import { AddSymbol } from "./AddSymbol";
+import { OverrideBadge } from "./OverrideBadge";
+
+// Web overhaul Part 6 restyled the universe controls in place; UniverseList.test.tsx keeps their behaviour.
+function withClient(ui: React.ReactElement) {
+  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
+}
+
+describe("AddSymbol, restyled", () => {
+  it("is named by a visible label, on the console's 44px field", () => {
+    withClient(<AddSymbol listName="would_own" />);
+    const input = screen.getByRole("textbox", { name: "Add a name to Would own" });
+    expect(input).toHaveClass("min-h-11");
+  });
+
+  it("names the Watchlist in its label", () => {
+    withClient(<AddSymbol listName="watchlist" />);
+    expect(screen.getByRole("textbox", { name: "Add a name to Watchlist" })).toBeInTheDocument();
+  });
+});
+
+describe("OverrideBadge, restyled", () => {
+  it("makes Revert a 44px target on a phone and hatches an unknown author", () => {
+    const onRevert = vi.fn();
+    render(<OverrideBadge author={null} timestamp={null} removed={false} onRevert={onRevert} />);
+    const revert = screen.getByRole("button", { name: "Revert" });
+    expect(revert).toHaveClass("min-h-11", "md:min-h-0");
+    expect(screen.getByText("n/a")).toHaveClass("hatch");
+    fireEvent.click(revert);
+    expect(onRevert).toHaveBeenCalledTimes(1);
+  });
+});
````

---

## Section E: Finish (Tasks 14-15) · sonnet; then opus review, sonnet fix pass

**Entry checks:**

- [ ] **E1. Sections A-D landed** (thirteen task commits after A0); every gate green at the D exit; G1-G7.
- [ ] **E2. The docs patch applies**: `git apply --check <S>/p6/T14.out` prints nothing. If it fails because
  `STATUS.md`, `ARCHITECTURE.md` or `web/CLAUDE.md` moved on `main`, apply its hunks by hand (each names its file and
  the lines around it), record a ruling, and continue: docs only.
- [ ] **E3. A browser for Task 15**: `ls ~/.npm/_npx/*/node_modules/playwright-core/package.json` lists at least one
  path (the capture harness uses it headless). None: ask the operator.

### Task 14: Docs (sonnet, effort medium)

**Files:** Modify `STATUS.md` (a "Built (2026-11-06 — web overhaul Part 6: Research, Universe and search)" section above
Part 5's, the Web overhaul row, two Part 5 and value-book deferred lines), `ARCHITECTURE.md` (the Routes paragraph, the
titles paragraph, three new bullets, the palette sentence, the stock page's hold), `web/CLAUDE.md` (the `research/`,
`research/universe/`, titles, `search/`, `home/`, `universe/`, `features/` and `lib/` entries); this plan.

- [ ] **Step 1: Check and apply `T14`.**
- [ ] **Step 2: Fill in what the patch could not know.** In the new STATUS Built section, after "Plan:", add the commit
  range (`git log --oneline main..HEAD | tail -1` to the head) and every ruling from the Progress log that changed
  behaviour; under "Deferred", add any minor a section recorded. Keep the section's existing sentences.
- [ ] **Step 3: Gate.** G3; `grep -n "still mounted only on Research\|has no plan yet.*Part 6\|cmdk. drives" STATUS.md ARCHITECTURE.md`
  prints nothing; `grep -c "features/search\|features/universe" ARCHITECTURE.md web/CLAUDE.md` prints a non-zero count
  for each; `git status --short` shows only the three docs and this plan. Docs only: no test run needed.
- [ ] **Step 4: Commit** `docs: web overhaul Part 6`.

<!-- block T14 -->
````diff
diff --git a/ARCHITECTURE.md b/ARCHITECTURE.md
index 56f8e0f..ab4f4d2 100644
--- a/ARCHITECTURE.md
+++ b/ARCHITECTURE.md
@@ -1586,7 +1586,8 @@ reskinned without an edit. The structure it added:
   nothing waits on you; `/trades/[approvalId]` is an approval's page, with its trade, Claude's review and the
   decision), `/portfolio` (Part 3: the Account card, then Positions by name, Campaigns and the expiry Calendar in `?view=`),
   `/activity` (Part 3: Pay a month at a time, the broker-truth Ledger, Fills and orders and System in `?view=`),
-  `/research` (the old landing page) and `/research/universe`,
+  `/research` (Part 6: Top opportunities, Your watchlist and the Sectors card) and `/research/universe` (Part 6: one
+  card per list),
   `/news`, `/more` (the bot card, the theme toggle, the income-target card, links to Research,
   Universe, News, Ledger, How it works, What Claude knows and statement import, system status and Credits),
   `/more/claude` (What Claude knows: the market picture, the regime and its limits, what each Claude call reads),
@@ -1604,14 +1605,17 @@ reskinned without an edit. The structure it added:
   `components/<domain>` where it is (the "fold into `features/`" idea was cut). **The rule for new code: it goes in
   `features/`; `components/` keeps `ui`, `shell`, the protected `options` controls, `value` and the survivors.**
   **Part 5 (2026-11-06, `docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md`) recomposed the stock
-  page** (`features/stock/`, below). Parts 6-8 (Research, Universe and search; News, More and How it works; the
-  value record) and order control have no plan yet.
+  page** (`features/stock/`, below). **Part 6 (2026-11-06,
+  `docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md`) recomposed Research and Universe
+  and put search in the shell** (`features/research/`, `features/universe/`, `features/search/`, below). Parts 7-8
+  (News, More and How it works; the value record) and order control have no plan yet.
 - **`app/` boundaries and titles** — web overhaul Part 4: the root `layout.tsx` sets `metadata.title` to
   `{ default: "IBKR Income", template: "%s · IBKR Income" }`; each server page exports its own `metadata`, and a
   client page gets a sibling server `layout.tsx` that exports `metadata` (or `generateMetadata` for a dynamic
   segment): `more`, `more/claude`, `research`, `research/universe`, `stock/[symbol]`, `news/[symbol]`,
   `ledger/ticker/[symbol]`, `positions/[underlying]/[slug]` and `trades/[approvalId]`. `app/titles.test.ts` pins
-  every route's title. `app/not-found.tsx` and `app/error.tsx` are the console's two boundaries (one Card each, one
+  every route's title. Since Part 6 the five `generateMetadata` layouts decode their segment through
+  `lib/segment.ts::decodeSegment`, which keeps the raw segment when an escape is malformed. `app/not-found.tsx` and `app/error.tsx` are the console's two boundaries (one Card each, one
   secondary action each: Go to Home on the not-found page, Try again calling `reset` on the error page; the error page shows `error.digest` as a
   reference and never the error's own message); `app/boundaries.test.tsx` pins them. There is no `loading.tsx`
   (every page draws its own `role="status"` skeleton) and no `global-error.tsx`.
@@ -1631,6 +1635,23 @@ reskinned without an edit. The structure it added:
   Activity's At IBKR list (a Value chip in `ExecutionsList`); every value position row links to the stock page's
   value block, and the "Value book unavailable" flag on Home and Activity is hidden only when the book is off and has
   never written.
+- **`features/search/` + `components/search/CommandPalette.tsx` + `lib/search.ts`** — web overhaul Part 6: the
+  console's one search dialog, mounted once in `app/layout.tsx`. `pages.ts` is the fixed list of the console's own
+  pages with `matchPages` (every typed word must match a page's name, hint or words; at most five; operator ruling:
+  no API change); the palette lists them above the tickers from `GET /research/search`, works as a combobox (the arrow
+  keys, Enter, Escape, a tap on the scrim, Close on a phone) and says its state in one status line. ⌘K or Ctrl+K opens
+  it anywhere; the rail's Search row, More's Search row and Research's Search button call `lib/search.ts::openSearch`,
+  which dispatches the one event the palette listens for, so nothing mounts a second palette. It navigates; it sends
+  nothing.
+- **`features/research/ResearchPage.tsx`** — web overhaul Part 6: `/research` (`page.tsx` only mounts it). The title
+  with Search and a Universe link, Top opportunities (`TopOpportunities`, whose `OpportunityCard` shows
+  `claude_note` labelled "Claude's note" since Part 6), then "Your watchlist" (`components/home/WatchlistTable`, the
+  per-user list in research.db, apart from the scan's own) and the Sectors card (`components/home/SectorGrid`), each
+  column one `grid-cols-1` track. A watchlist or sector move is signed, never green or red.
+- **`features/universe/UniversePage.tsx`** — web overhaul Part 6: `/research/universe` (`page.tsx` only mounts it). A
+  back link to Research, then one card per `GET /universe` list (`components/universe/UniverseList`, restyled in
+  place with `AddSymbol` and `OverrideBadge`), two columns from 1024px. The add and remove commands, the would-own
+  confirmation and its consequence text are unchanged; `sectors` stays file-only.
 - **`features/stock/`** — web overhaul Part 5: the stock page (`/stock/[symbol]`; `page.tsx` only mounts
   `StockPage`). A back link to Research, the ticker, name and last price ("Delayed" in words when stale), then one
   grid as the position page's: the chart (`components/stock/PriceChart`, ink candles with the value book's fair
@@ -1640,14 +1661,15 @@ reskinned without an edit. The structure it added:
   (`features/stock-value/ValueBlock`, first when `valueLeads` says the book would buy the name at a price or holds
   it), Checks, Technicals and the statements (behind a disclosure) on the left; the news service's notes, News,
   Sentiment and the model summary on the right, each column one `grid-cols-1` track so a wide statements table
-  scrolls inside its card. Each section is a `StockSection` card. It reads
+  scrolls inside its card. Each section is a `StockSection` card; since Part 6 the value block mounts only after
+  `GET /value/{symbol}` has answered, once, in the slot the answer picks. It reads
   `GET /research/{symbol}` and `GET /value/{symbol}` (the value block's own query key, so one fetch); its only
   command is the value block's `AnalyseButton`.
 
 The paragraphs below describe the pages as they were built; their file paths moved with the routes
 above (`app/page.tsx` → `app/research/page.tsx`, `app/universe/` → `app/research/universe/`,
-`app/options/` → `app/trades/`, `app/pnl/` → `app/activity/`). `cmdk` drives the `⌘K` command palette
-over the SEC symbol directory.
+`app/options/` → `app/trades/`, `app/pnl/` → `app/activity/`). The `⌘K` palette is hand-built (not `cmdk`)
+over the SEC symbol directory and, since Part 6, the console's own pages.
 
 Ticker page at `/stock/[symbol]` renders a price chart (lightweight-charts candlesticks + volume +
 SMA 50/200), technicals panel, sentiment panel, news panel, and normalised SEC statements with
diff --git a/STATUS.md b/STATUS.md
index 3663a2d..752eea0 100644
--- a/STATUS.md
+++ b/STATUS.md
@@ -347,6 +347,43 @@ Operator to-dos: re-copy `config/examples/value.yaml`'s `telegram:` and `prompt_
 
 ---
 
+## Built (2026-11-06 — web overhaul Part 6: Research, Universe and search)
+
+Plan: `docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md` (branch `feat/web-overhaul-6`;
+the plan's Progress log holds each task's commit, gate and rulings). Part 6 puts Research and Universe on the
+payslip, mounts the search palette in the shell, shows Claude's note on Top opportunities and closes four carried
+minors. It adds no API route or field, no command site and no token, colour, font, radius or elevation; the
+protected decide, confirm, receipt, halt, autonomy and roll-mode components, `lib/commands.ts` and `lib/receipt.ts`
+are byte-identical to `main`. The operator ruled on three questions (2026-11-06): search finds tickers and the
+console's own pages from a fixed list in the web (no API change); Research's list is "Your watchlist", apart from the
+scan's own on Universe (copy only); the stock page holds its value block until `GET /value/{symbol}` answers.
+
+**Built, one line per task:**
+
+- **Carried fixes (Tasks 1-4):** the five `generateMetadata` layouts decode their segment through
+  `lib/segment.ts::decodeSegment` (a malformed `%` keeps the raw segment instead of throwing); save-side tests pin
+  that `DecideControls` and the roll flow write a pending command and an open live step to storage; the stock page
+  mounts its value block once, after the value read answers, in the slot the answer picks; the position page's trade
+  column is one `grid-cols-1` track and its headline links are 44px on a phone.
+- **Search (Tasks 5-7):** `features/search/pages.ts` (the console's pages and `matchPages`), `lib/search.ts`
+  (`openSearch`, one event); `components/search/CommandPalette` restyled in place as a combobox (Pages, then Tickers;
+  the arrow keys, Enter, Escape, a tap on the scrim or Close; a status line in words) and mounted once in the root
+  layout; the rail's Search row (Research's icon is now a telescope), More's Search row, Research's Search button.
+- **Research (Tasks 8-11):** "Your watchlist" (`components/home/WatchlistTable`, restyled in place: a card of rows,
+  the move signed but not coloured, unknown hatched, loading and failure in words); the Sectors card
+  (`SectorGrid`/`SectorCard` restyled in place, no green or red); `features/research/ResearchPage` (the frame,
+  Search, a Universe link, Top opportunities, then the two cards); Claude's note on `OpportunityCard`, labelled as
+  Claude's and never on a button.
+- **Universe (Tasks 12-13):** `features/universe/UniversePage` (a back link to Research, the title, one card per list
+  in two columns from 1024px, loading and failure in words); `UniverseList`, `AddSymbol` and `OverrideBadge` restyled
+  in place (each list says what it is for, Wheeling and Dip-watch as status words, 44px targets, failures in plain
+  words). The would-own confirmation, its consequence text and the command flow are unchanged; `sectors` stays
+  file-only.
+
+**Deferred:** the value block still remounts in the rare case that a Claude read flips the lead while the page is
+open (it then loses a terminal receipt; a pending one is restored from storage). Global search does not list held
+positions or waiting proposals (operator ruling: tickers and pages).
+
 ## Built (2026-11-06 — web overhaul Part 5: the stock page)
 
 Plan: `docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md` (branch `feat/web-overhaul-5`; the plan's
@@ -401,8 +438,8 @@ halt, autonomy and roll-mode components, `lib/commands.ts` and `lib/receipt.ts`
   re-evaluations carry it.
 - The chart shows one year with no range chips and no pointer readout (the bars endpoint is fixed at a year; the
   position page's chips slice closes only).
-- Top opportunities shows `claude_note` from web overhaul Part 6, with the Research page.
-- The search palette is still mounted only on Research (Part 6, HANDOFF S1).
+- Top opportunities shows `claude_note` since web overhaul Part 6, and the search palette is in the shell since
+  Part 6.
 
 ## Built (2026-11-05 — drawdown window, hero change per range, spreads card health)
 
@@ -620,7 +657,7 @@ book is still off until `value.book.enabled`.
   with the API through `src/common/value_cost.py`, and a trim offer that went stale is no longer the end of the
   episode.)
 - **Deferred (web, Sections F-I).** Top opportunities' Claude note is in the API since web overhaul Part 5
-  (`ValueTopItem.claude_note`) and shown on the card from Part 6; its stop is always null today. The stock page
+  (`ValueTopItem.claude_note`) and shown on the card since Part 6; its stop is always null today. The stock page
   shows the tranche plan and the size tier since Part 5. The calendar's value split costs one extra request per month opened (`GET /pnl/calendar?
   strategy=value`; the cell's figure is still the whole day, and `MonthPay.net` keeps value out). The
   `value_available=false` flag showed under All on installs that never ran the value process (value.db absent)
@@ -1174,7 +1211,7 @@ the first alias with any facts was wrong), `select_periods` (enforces `kind`, la
 | **P2 — Options console (M1+M2+M3 built 2026-09-06, reviewed; M4 Tasks 4.1+4.2+4.3+4.4 built 2026-09-06; M5 Tasks 5.1+5.2+5.3+5.4 built 2026-09-07; M6 Tasks 6.1+6.2+6.3+6.4 built 2026-09-07; M7 Tasks 7.1-7.7 built 2026-09-07 — P2 complete)** | **M1 — Write foundation:** the intent queue exists, the drain runs with no registered handlers, and no web action can reach an order until M3. `AppCommandRow` (`src/storage/models.py`) + `src/storage/app_commands.py` (enqueue/dedupe/mark/expire helpers); `src/api/models/commands.py` (`CommandKind` enum, typed payloads per kind, `validate_payload`, `dedupe_key_for`, `CommandStatus` — `UniversePayload.list_name` is `Literal["would_own", "watchlist"]` so `sectors`/`leveraged_etfs` fail parsing); `src/api/trading_db.py` gains a write-scoped `get_command_engine` + `command_session` with a `before_flush` listener (`WriteFenceViolation`) that rejects any flush targeting a non-`app_commands` table; `src/api/commands.py` is the only module allowed to import `get_command_engine`/`command_session` (`submit` enqueues, `get_status` reads through the read-only engine, `clear_confirm_token` clears a live-mode token after confirmation); `src/api/routers/commands.py` adds `POST /commands`, `GET /commands/{id}`, `POST /commands/{id}/confirm` (owner-only, dedupe returns 200 not 201, live-mode order-reaching intents get a `confirm_token`); `src/notify/command_drain.py` + `_command_drain_loop` in `approval_service` (fails unknown kinds loudly, isolates throwing handlers, skips commands awaiting confirmation, runs with `ib is None`, writes `command_drain_heartbeat` to `system_settings` after every cycle so `/options/controls` can tell a live drain from a dead one); `tests/test_web_fence.py` gains three P2 fence tests (write-handle leak — greps for both `get_command_engine` and `command_session`, command writer names no other table, trading path still never imports the web layer); the token proxy (`web/app/api/[...path]/route.ts`) moves `API_TOKEN` server-side — `NEXT_PUBLIC_API_TOKEN` is purged from the repo, the built bundle no longer contains the token. **M2 — Read surfaces:** the console exists and is worth opening, still unable to do anything. `GET /options/approvals` + `/approvals/{id}` (`src/api/routers/options.py`, `src/api/models/options.py`) — a four-table join (approval/candidate/risk-verdict/claude-review) through the read-only engine, snapshot-first when the candidate has been pruned, the five review fields rendered separately never as one blob. `GET /options/assessed` implements the promotable table from spec §5.2 exactly (`risk_gate`/`generator` never promotable), ranked like `scan.py::_rank_assessed`, `limit` caps the total across groups not per symbol. `GET /options/orders`, `/fills`, `/shorts` (nulls stay null — `avg_fill_price`/`mark`/`unrealized_pnl` never fabricate `0`; `shorts.as_of` is the snapshot's capture time, not request time). `GET /options/controls` reads `command_drain_heartbeat` against twice the poll interval — never reuses `/health`'s research-worker heartbeat, defaults to unhealthy, never `true` on a drain that has never run. Web: `web/app/options/page.tsx` + `[approvalId]/page.tsx`, `web/components/options/*` (`ApprovalsList`/`ApprovalCard`, `AssessedBrowser` with stage badges that are never colour-alone, `OrdersTable`/`FillsTable`/`ShortsTable`, `ControlsStrip`, `ApprovalDetail`/`ReviewPanel`/`IdealZoneBar`/`AlternativesTable`) — no approve/reject/promote/roll control anywhere, asserted by a frontend test. The rail flip (`src/api/routers/meta.py`) makes `/options` available. A Sonnet verification pass (2026-09-06) live-browser-tested every tab and the detail page against the real dev stack and found the console **completely unreachable** for reasons outside M1/M2's own code: `web/.env.local` still carried the pre-M1 `NEXT_PUBLIC_API_URL`/`NEXT_PUBLIC_API_TOKEN` names instead of the migrated `API_URL`/`API_TOKEN`, so every proxied request 500'd; and `app_commands` (M1 Task 1.1) had never been created in the real `data/income_system.db` because table creation only runs via the trading daemon's own `init_db()` startup path, which nobody had triggered since the model was added. Both are environment/ops gaps, not code defects, and are now fixed locally (`.env.local` corrected, `init_db()` run once). The pass also found and fixed two real code defects: `GET /options/approvals/{id}` raised `MultipleResultsFound` (500) whenever a candidate had been assessed across more than one scan run — completely ordinary, since `risk_verdicts` stores one row per assessed contract *per run* — fixed by ordering both the verdict and review lookups by `created_at` descending and taking the newest; and `web/app/options/[approvalId]/page.tsx` was missing `"use client"`, crashing on every real navigation to it (masked in tests by the component-level test harness). **None of M1 or M2 had ever been `git commit`ed** despite every task's checklist saying so — this is almost certainly why a later M3 session, working from git-tracked state, concluded the console UI "never landed" even though it existed on disk and worked once the environment gaps above were fixed; see `Web plan/milestones/P2/M3-approve-reject.md`'s correction note. All gates green after the fixes: `python -m pytest -q` (1755 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (100 passed) `&& npm run lint && npm run build`, plus a live click-through of every `/options` tab and an approval detail page with zero console errors. **M3 — Approve and reject (built 2026-09-06, opencode/glm-5.3):** the first web action that can cause an order to exist, through the exact Telegram code path. `src/notify/command_drain.py` registers `approve`/`reject` handlers that call `approval_service._process_button` **unchanged** (a monkeypatch test fails if a refactor forks the mutation); an already-decided approval is `applied` neutrally ("Already {status}" in `result.decision`), a replayed drain creates no second order (all four §4.5 idempotency layers hold, asserted in `tests/test_drain_approve_reject.py`), and neither handler needs `ib` — TWS down still queues the order. The drain stores a handler's result dict verbatim and gains `CommandFailed(reason, detail)` for machine-readable failures. The live-mode second confirmation now fails closed exactly per spec §4.6: a wrong/missing token is **403 and does not clear the field** (`tests/test_live_confirmation.py` covers token creation by kind, the drain's skip, the confirm-then-apply round-trip, the 403/409 split, and the TTL sweep), the outstanding `confirm_token` is surfaced through the owner-only `CommandStatus` so the frontend can complete the round-trip, and confirming a not-awaiting command is 409. `tests/test_write_path_invariants.py` asserts the phase invariants in one place: every `/options`+`/commands` route is owner-gated (globbed via route introspection), no route module imports the write handle, Telegram and the console cannot double-decide an approval into two orders, a crashed drain re-applies exactly once, and the API still holds no `ib_async` import. Web: `web/lib/receipt.ts` (`receiptState` — pending never renders as applied, `submitted` only when an order is working, `filled` only when a fill exists, stalled stated in words), `CommandReceipt` (the §9.2 signature component — intent id always visible, humanised failure reasons, no spinner when stalled), `ConfirmAction` (confirm dialog: exact contract/count, case-sensitive typed-word gate for M6's halt, focus trap + Escape + focus return, aria-modal, reduced-motion entry), `web/lib/commands.ts` (`submitCommand`/`confirmCommand`/`useCommandStatus` polling every 2s while pending, stopping at a terminal state), and `DecideControls` — the shared decide flow on both the approval card and the detail page: confirm dialog before any request, one `POST /commands`, controls disabled while in flight, a decided approval renders its decision not controls, 403 renders a permission message, and in live mode a distinct clearly-labelled second LIVE confirmation (cancelling it leaves the intent queued and unconfirmed, stated in the receipt). The M2 no-action-buttons guards evolved with the milestone: the controls now exist and are asserted wired through the confirm gate. **The existing execution-time `[CONFIRM LIVE]` path is untouched and still fires after a web live approve.** All gates green: `python -m pytest -q` (1776 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (130 passed) `&& npm run lint && npm run build`. **M4 — Promote, Tasks 4.1+4.2+4.3+4.4 (built 2026-09-06):** promote is now a real gated action, belt and braces. **Task 4.1 — the API-boundary promotable-stage guard:** `src/api/routers/commands.py`'s `assert_promotable` refuses `POST /commands` for a `promote` before any `app_commands` row exists unless the candidate's most recent `risk_verdicts` row is at `score_floor`/`dedupe`/`top_n` (spec §5.2's promotable table) — `risk_gate`/`generator` are never promotable, `passed` already has an approval, an unknown `candidate_id` is `404`, a non-promotable stage is `409 {"reason": "stage_not_promotable", "stage": ...}`. **Task 4.2 — the drain handler re-prices and re-gates for real:** `src/notify/command_drain.py`'s `promote` handler does not trust the stored row it was asked to promote — it re-runs the single-ticker pricing path (`src.orchestrator.scan._price_and_gate_ticker`, extracted from `run_ticker_scan` as a pure refactor — same chain fetch, analytics, CC/CSP screens, scoring, `validate_candidates` gate, and `record_assessments` audit write, zero behavior change to `run_ticker_scan` itself) for the requested symbol, searches the gate-passed output for the exact `(strategy, strike, expiry)`, and only then calls the new `src/execution/promote_pipeline.py::queue_promoted_for_approval` (mirrors `roll_pipeline.queue_roll_for_approval`'s `has_active_order` guard and `CandidateRow`/`ApprovalRow` upsert, minus the generation half — it takes the fresh `TradeCandidate` directly) to raise a PENDING approval. Nothing from the stored `RiskVerdictRow` reaches the approval except the tuple used to find the fresh match; every number on the approval — including a re-gate that now rejects (`gate_rejected`, reasons surfaced verbatim, by design) — comes from this run. Failure reasons (`broker_unavailable`, `chain_unavailable`, `contract_not_priced`, `gate_rejected`, `score_below_minimum`) are documented verbatim in `docs/web/commands.md`. `drain_once` now awaits a handler's result when it returns one (coroutine handlers, needed for promote's re-scan; every earlier sync handler is unaffected). All gates green: `python -m pytest -q` (1804 passed), `ruff check .`, `mypy src`. **Task 4.3 — the promote control and its receipt in the frontend (built 2026-09-06):** `AssessedBrowser`'s per-contract `<li>` was extracted into its own `web/components/options/AssessedRow.tsx` component (a pure, behavior-preserving extraction — every existing `AssessedBrowser.test.tsx` test kept passing unmodified), which now carries a Promote button rendered only when `promotable` is true and `strike`/`expiry` are both non-null (a promotable row with either unexpectedly null falls through to the non-promotable rendering rather than send `null` to the API). Promoting reuses the M3 decide flow exactly: `ConfirmAction` first (explaining in one sentence that the contract is priced and gated again and an approval appears only if it still passes; a `score_floor` row's dialog additionally shows the blended score and `promote_note`'s configured-minimum text verbatim), then `submitCommand("promote", {candidate_id, symbol, strategy, strike, expiry})` fires once, `useCommandStatus` polls to a terminal state, and `<CommandReceipt/>` renders the outcome unmodified (`order` is always `null` — a promote never has approve/reject's working-order lifecycle) — a live-mode response routes through the same second LIVE confirmation `DecideControls` uses. On `applied`, a "View approval" link to `/options/{approval_id}` renders when `result.approval_id` is non-null. `AssessedBrowser` now also fetches `GET /options/controls` itself (same pattern as `ApprovalsList`) so a promoted row's receipt can state a dead drain in words. All gates green: `python -m pytest -q` (1805 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (150 passed) `&& npm run lint && npm run build`. **Task 4.4 — the promote refusal tests (built 2026-09-06):** `tests/test_write_path_invariants.py` gains the belt-and-braces coverage for the whole milestone: `test_no_promote_path_exists_for_a_gate_rejected_contract` enqueues a promote command directly (bypassing Task 4.1's API-boundary guard entirely, the way a malformed or bypassed request would) for a `risk_gate`-staged contract and asserts the drain handler's own re-gate still refuses it; `test_the_promote_handler_runs_the_real_rules_engine` wraps (not mocks) `validate_candidates` with a spy to prove the real Rules Engine is what's called, not a stand-in; `test_promotable_stages_match_the_spec_exactly` pins `PROMOTABLE_STAGES == {"score_floor", "dedupe", "top_n"}` so a future edit that widens it fails here first. **M5 — Roll on demand, Tasks 5.1+5.2+5.3+5.4 (built 2026-09-07, opencode/glm-5.2):** the operator can ask the system to propose a roll for any open short, without waiting for the intraday monitor to fire an alert. Two steps, never one: the console proposes; the operator approves that proposal through M3's path. **Task 5.1 — the `roll_request` drain handler:** `src/notify/command_drain.py`'s `_roll_request` resolves the position from a live `get_positions(ib)` read, fetches a fresh chain + IV/technical stats through `src.execution.roll_pipeline.fetch_roll_inputs` (the shared chain-fetch path extracted from the monitor's `_try_queue_roll`, which was refactored to call it — behavior unchanged; the same three helpers composed inline are now one function two callers share, so the web and the monitor cannot drift on how a roll is priced), and calls `queue_roll_for_approval` **unchanged**. The handler disambiguates the pipeline's `None` **before** calling it: it runs `generate_roll_candidates(..., defensive=True)` itself to derive the same candidates the pipeline will choose from (same function, same inputs, same deterministic ids), and checks `_existing_roll_in_flight` against **every** one of them, not just the top-ranked one (post-M5 verification fix, 2026-09-07 — see "Bug fixed" note below) — covering both an active order (`active_order_for`, the new row-level companion to `has_active_order` in `src/storage/orders.py`) and an existing PENDING approval. Either → `roll_already_working` with `detail.approval_id` so the receipt links to the in-flight proposal; empty/failed chain → `chain_unavailable` with the provider message; no candidates → `no_qualifying_roll`; non-short or absent position → `not_an_open_short` / `position_not_found`; `ib is None` → `broker_unavailable`. The PENDING-approval check is what closes the monitor-vs-web race `has_active_order` alone would miss (the monitor's roll raises a PENDING `ApprovalRow`, no `OrderRow` until approved) — the milestone's headline acceptance criterion ("a monitor alert and a web request produce exactly one approval") requires it. `tests/test_drain_roll.py` carries the nine specified tests (seven from the plan + `position_not_found` + `chain_unavailable`), mocking only the IBKR/network boundary so the real `generate_roll_candidates` economics run. Failure reasons documented verbatim in `docs/web/commands.md`'s roll_request section. **Task 5.4 — roll degradation tests (built 2026-09-07):** `tests/test_write_path_invariants.py` gains three invariants: a behavioral tripwire + source scan proving the handler never reaches `execute_roll` directly (no `roll_executor` import, no `execute_roll(` call in `command_drain.py` or `roll_pipeline.py`); the verbatim token grep proving no `max_debit`/`min_delta_reduction`/`roc_pct` leaked into `command_drain.py`; and a `wraps`-spy on `generate_roll_candidates` at both call sites proving `defensive=True` flows through the handler's pre-check and the pipeline's internal call (the web roll is the monitor's roll). Reuses the `drain_env`/`fake_chain` fixtures from `tests/test_drain_roll.py` the same sanctioned way the file already imports the promote fixtures. **Task 5.2 — the roll control on the shorts list (built 2026-09-07):** `web/components/options/ShortsRow.tsx` extracted from `ShortsTable` (the same extraction `AssessedRow` got from `AssessedBrowser`), carrying the row's cells plus the confirm-then-submit-then-receipt flow that mirrors `AssessedRow`'s promote control exactly. The control is labelled "Propose a roll" (not "Roll" — the button does not roll the position, and the copy says so); `ConfirmAction` states plainly that the system will price a roll, raise it for approval, and nothing executes until that proposal is approved; `submitCommand("roll_request", {position_symbol})` fires once; `useCommandStatus` polls to terminal. `no_qualifying_roll` renders as a plain sentence in a `data-state="answered"` box (no `text-loss` chrome) — special-cased in `ShortsRow` so `CommandReceipt` stays untouched and every existing receipt test stays green. `roll_already_working` renders the failed receipt plus a "View the roll already in flight" link to `result.detail.approval_id`; success renders a "View approval" link to `result.approval_id`. The control is disabled while in flight and wired through the live-mode second confirmation (roll_request is in `_LIVE_CONFIRM_KINDS`). `ShortsTable` now fetches `GET /options/controls` (same pattern as `ApprovalsList`) so a roll receipt can state a dead drain in words; defaults healthy while loading. The M2 "asserts no roll button exists" guard evolved into the roll-control suite (17 tests in `ShortsTable.test.tsx`). **Task 5.3 — roll alerts on the shorts list (built 2026-09-07):** `_TRIGGER_LABELS` + `humanize_trigger` moved from `src/notify/formatters.py` to `src/monitor/triggers.py` (beside the codes they name); `formatters._humanize_trigger` is now an alias import, so every existing formatter caller works unchanged and the identity `formatters._humanize_trigger is triggers.humanize_trigger` is asserted in `tests/test_api_shorts.py`. `RollAlertSummary` gains `trigger_label` (humanised server-side via the shared mapping) and `claude_recommendation` (passed through from `RollAlertRow`, nullable). The API router imports `humanize_trigger` from `src.monitor.triggers` — not the notify layer — so the "API must not pull in the notify layer" fence holds. The web renders `trigger_label` verbatim, the alert age as text via `relativeAge`, and Claude's view labelled "Model opinion (Claude): ..." — distinct from any deterministic number on the row. A position with no alerts renders nothing extra (not "No alerts"). **A Sonnet verification pass (2026-09-07)** checked the opencode/glm-5.2 build against this plan and the live gate (test count, ruff, mypy, vitest, lint, build all reproduced exactly as claimed) and found one real defect in Task 5.1's own new code: `_roll_request` derived the same candidate `queue_roll_for_approval` would pick and checked only that single, top-ranked candidate for an in-flight roll. Under `defensive=True` every candidate's `roc_pct` is hardcoded `0.0` (rolls are judged on risk reduction, not yield, per D4), so `generate_roll_candidates`'s ROC-desc sort is a no-op tie and "the top-ranked candidate" is really just whichever qualifying quote the chain happened to list first — a property of chain order, not economics. Two fetches taken minutes apart (the monitor's, then the web's) can list the same qualifying strikes in a different order, so the monitor's already-PENDING candidate can silently drop to second-or-later without ceasing to qualify — and the handler would then fail to recognise it as in flight, racing the monitor into a second approval for the same position, exactly the case the milestone's headline acceptance criterion exists to prevent. Fixed by checking every one of `generate_roll_candidates`'s qualifying candidates against `_existing_roll_in_flight`, not just `candidates[0]` — bounded to the handful of strikes/expiries one chain fetch returns, so the cost is negligible. Regression test: `tests/test_drain_roll.py::test_an_in_flight_roll_is_caught_even_when_no_longer_top_ranked` (constructs two qualifying candidates whose chain order flips between the monitor's fetch and the web's, and confirms it reproduces the double-approval against the pre-fix code). Also flagged, not fixed (pre-dates M5, lives in `rolling.py`'s N20-era economics, out of scope for a drain-handler fix): the same `roc_pct = 0.0` fact means the monitor's own roll selection has never actually picked the "best" defensive roll by any economic measure, only the first one the chain lists — worth a human look at whether defensive rolls should rank by delta-reduction, liquidity, or credit instead of an always-tied ROC. All gates green after the fix: `python -m pytest -q` (1827 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (163 passed) `&& npm run lint && npm run build`. **M6 — Controls, Tasks 6.1+6.2+6.3+6.4 (built 2026-09-07, opencode/glm-5.3):** halt, resume and the autonomy rung are reachable from the browser, with the confirmation weights deliberately asymmetric. **Task 6.1 — the drain handlers:** `src/notify/command_drain.py` registers `halt`/`resume`/`set_autonomy`, thin resolvers over the same `system_settings` helpers Telegram's `/halt`, `/resume`, `/autonomy` use (`set_halted`/`set_autonomy_level` — one halt flag, read through `HALT_KEY`; a token-grep test pins that the literal `execution_halted` never appears in the drain). All three apply with `ib is None`: halting matters most exactly when something is wrong, and "TWS is unreachable" is a common shape of wrong. Halt/resume are idempotent (`applied`, never `failed` — halting an already-halted system satisfies the intent; so does resuming an un-halted one, resolving the M1 doc's `not_halted` failure mode as a satisfied intent instead); an empty halt reason is stored as `"halted from the web console"` so `/status` and the console always say something; `resume` records who released the switch in the command's `result` (`released_by`); each handler sends a Telegram notification — the one place a handler notifies, because control-plane changes have no order-poll loop to report them later, and a halt raised from the browser must be visible wherever the operator is. `set_autonomy` enforces the same promotion evidence gate Telegram does (`promotion_blockers` must be empty, else the command fails with `promotion_refused` + `detail.blockers`) so the web is not the rung ladder's back door; demotion always applies. `tests/test_drain_controls.py` carries 13 tests including the six specified verbatim. **Task 6.2 — payload validation:** `HaltPayload.reason` is capped at 200 chars (`422` past it — the reason is rendered by `/status` and the halt banner, an unbounded string there is a rendering bug waiting to happen), and the empty-payload kinds (`halt`/`resume`/`set_autonomy`/`refresh`) are `extra="forbid"` so a client typo is caught rather than ignored — all at parse time, before a command row exists (asserted). Control kinds carry no `dedupe_key` (M1's convention, pinned) and are never in `_LIVE_CONFIRM_KINDS` — the deliberate asymmetry, stated in a comment at the set so it does not look like an oversight: the live token is for intents that can reach an order, and a halt must never be slowed by a second step (asserted for halt with `cfg.is_live` true). **Task 6.3 — the controls panel:** `web/components/options/HaltControl.tsx` (halt is ONE CLICK, no dialog — speed is the feature, and a test name says so; resume requires the typed word RESUME, disabled until it matches exactly case-sensitively) and `AutonomyControl.tsx` (four rungs rendered from the API's `rungs` array, never hardcoded; a rung change click-through confirms showing current and target rungs; a refused promotion renders `promotion refused` with the blockers through the receipt). `ControlsStrip` now hosts both plus an unmissable halted banner at the top of the console (reason and time as text, fill and text never colour alone; honest "unknown time" when no halt command row exists, e.g. a breaker trip) and a `drain_healthy: false` line stating "the trading service is not draining commands" beside the controls — a queued-but-undraining halt is this milestone's worst case. Both controls disable while their own command is in flight, render `CommandReceipt`, invalidate the controls query on terminal so the strip moves on the next poll, and route a live-mode response through the same second LIVE confirmation (unreachable in practice for these kinds, but the shape is shared). `ConfirmAction`'s docstring corrected: the typed word is used by `resume` in M6, not `halt` (the milestone refined design §9.3's first draft). `GET /options/controls` gains `halted_at`, derived from the most recent applied `halt` command's `applied_at` — the "no new setting keys" rule and the banner's "time it was halted" are reconciled without a new key, and a breaker-tripped halt honestly renders no time rather than a fabricated one. 22 new frontend tests across `HaltControl.test.tsx`, `AutonomyControl.test.tsx`, `ControlsStrip.test.tsx`. **Task 6.4 — controls invariants:** `tests/test_write_path_invariants.py` gains the three specified tests (parametrised every-control-kind-applies-without-a-broker over the reused `drain_env` fixture; `test_control_kinds_never_require_live_confirmation` pinning `_LIVE_CONFIRM_KINDS`; `test_the_halt_key_is_the_same_one_telegram_uses` with the verbatim token grep). All gates green: `python -m pytest -q` (1856 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (185 passed) `&& npm run lint && npm run build`. **A Sonnet verification pass (2026-09-07)** checked the opencode/glm-5.3 build against this plan and the live gate (all six commands reproduced exactly as claimed) and found one real defect: `GET /options/controls`' `halted_at` derivation had no lower bound, so a resumed web halt followed by a later, command-row-less halt (a circuit-breaker trip, or a Telegram `/halt` — neither writes an `AppCommandRow`) surfaced the *earlier* halt's timestamp instead of the honest `null` design decision 1 promised for exactly that case; the one existing null-case test only covered a fresh DB with no prior halt rows and never exercised the halt→resume→halt sequence. Fixed by bounding the halt lookup (`routers/options.py::controls`) to applied strictly after the most recent applied `resume` row. Regression test: `tests/test_api_controls.py::test_halted_at_does_not_leak_a_stale_timestamp_from_a_prior_halt_cycle`. All gates green after the fix: `python -m pytest -q` (1857 passed), `ruff check .`, `mypy src` (web gate unaffected, not re-run). **M7 — Universe editing (Tasks 7.1-7.7 built 2026-09-07):** the two soft universe lists — `would_own` and `watchlist` — become editable from the browser, without `sectors` or the risk engine ever becoming reachable from the web. **Task 7.1 — the override store:** `UniverseOverrideRow` (`src/storage/models.py`, unique on `(symbol, list_name)`) holds one row per operator add/remove — upper-cased `symbol`, `action: "add"|"remove"`, `created_by`/`created_at` audit trail; `src/storage/universe_overrides.py`'s `set_override`/`clear_override`/`all_overrides` each take an explicit `session`, and `set_override` is a total-replace upsert — a later call for the same pair overwrites `action`/`created_by`/`created_at` in place, so an add followed by a remove is one row, never two to reconcile at read time. **Task 7.2 — the composer:** `src/common/universe.py::effective_universe()` composes `universe_overrides` onto `config/universe.yaml`, returning a dict shaped exactly like `get_config().universe`. Only `would_own`/`watchlist` are overridable (`OVERRIDABLE_LISTS = frozenset({"would_own", "watchlist"})`); every other key — `sectors`, `strike_bands`, `indexes`, `actively_wheeling`, `leveraged_etfs` — passes through byte-identical, proven even against a stray override row inserted directly under `list_name="sectors"`. A `remove` override on a symbol currently in `actively_wheeling` is ignored when composing `would_own` — you cannot stop being willing to own something you are actively wheeling. An unreadable overrides table falls back to the YAML base untouched and logs a warning; it never raises and never empties the universe. A 60-second TTL cache (a plain `(dict, time.monotonic())` tuple) avoids a DB round-trip on every read; `invalidate_universe_cache()` forces recompute so a web edit is visible immediately in the process that applied it, not up to 60s later. Ordering is deterministic: YAML file order, then added symbols in `created_at` order. **Task 7.3 — six consumers migrated** from `get_config().universe` to `effective_universe()`: `src/strategies/cash_secured_put.py` (the CSP eligibility check — the single most consequential edit in the milestone, proven end-to-end by a test that adds an override and confirms `generate_csp_candidates` actually changes its output), `src/orchestrator/scan.py` (symbol selection), `src/orchestrator/eod_report.py` (two sites — the daily IV-history refresh set and the EOD watchlist report), and `src/api/routers/universe.py` / `routers/research.py` (three read sites across the two files). `src/engine/risk_engine.py`, `src/ibkr/market_data.py`'s `strike_bands`, and every `actively_wheeling`/`sectors` read elsewhere are deliberately untouched — not overridable. An autouse `tests/conftest.py` fixture resets the TTL cache around every test. **Task 7.4 — the write path:** `GET /universe` gains `lists: [{name, overridable, entries: [{symbol, overridden, removed, created_by, created_at}]}]` (four lists, `indexes`/`watchlist`/`would_own`/`actively_wheeling`, only the latter two `overridable`) and flips `editable` to `true`; `would_own`/`watchlist` entries are the union of the YAML base and every override row for that list, not just the filtered effective list, so a removed YAML-base symbol stays visible (greyed out) with a revert path. New routes `POST`/`DELETE /universe/{list_name}/{symbol}` (owner-only, thin wrappers over the same command-queue path `POST /commands` uses) narrow `list_name` to `Literal["would_own", "watchlist"]` so any other value is `422` before a command row can exist; an unknown symbol (checked against the research symbol directory) is `404`; removing an `actively_wheeling` symbol specifically from `would_own` is `409`. The drain handlers `_universe_add`/`_universe_remove` (`src/notify/command_drain.py`) call `set_override` — never `clear_override`, since a remove must always record an explicit suppressing row, even for a YAML-base symbol, because deleting the row would silently do nothing for one — then `invalidate_universe_cache()`. Neither handler can fail (all validation already happened at the API boundary) and neither sends a Telegram notification, deliberately — a universe edit is reversible, non-urgent config, unlike halt/resume/set_autonomy. **One fix-loop round, the only one across the whole milestone:** the initial `GET /universe` entries-union silently dropped a genuinely reachable state — a symbol added via override then removed again, leaving a non-base `action="remove"` row — fixed so every override row for a non-base symbol appears in `entries`, tagged `removed = (action == "remove")`. **Task 7.5 — the frontend:** `web/components/universe/{UniverseList,OverrideBadge,AddSymbol}.tsx` and a rewritten `web/app/universe/page.tsx` consume the new shape (`web/lib/commands.ts` gains `submitUniverseCommand`); add/remove controls render only on `would_own`/`watchlist`, with `indexes`/`actively_wheeling` rendered read-only and noted as YAML-managed. Adding to `would_own` opens a confirmation naming the actual consequence — the system may sell cash-secured puts on the symbol and the operator may be assigned its shares; adding to `watchlist` fires immediately with no dialog (a reporting list, never reaches an order). An overridden entry renders `OverrideBadge` (author, timestamp, a revert control that fires the opposite action of the entry's current state). The symbol picker is a typeahead over `GET /research/search`, so a typo cannot become a `404`. Every mutation renders `CommandReceipt` and stops polling at a terminal command status. The wheeling-vs-dip-watch tag the pre-M7 page showed within `would_own` was preserved. **Task 7.6 — the fence:** `tests/test_web_fence.py` gains three tests: no module under `src/claude/eval/` or `src/research/` can write a universe override; `src/engine/risk_engine.py` never mentions `effective_universe`/`universe_overrides` anywhere in its text; `OVERRIDABLE_LISTS == frozenset({"would_own", "watchlist"})` exactly, pinned so a future widening fails here first. All gates green: `python -m pytest -q` (1920 passed), `ruff check .` (clean), `mypy src` (clean), `cd web && npx vitest run` (203 passed) `&& npm run lint && npm run build` (both clean). **Final whole-branch review fix round (2026-09-07), one commit, seven findings:** `universe_add`/`universe_remove` lost their dedupe key in `dedupe_key_for` — a stable `f"{kind}:{list_name}:{symbol}"` key let a later, semantically different request (e.g. the second `remove` in remove→add→remove) dedupe to an earlier request's already-`applied` command row, so the API returned `200`/`applied` while the override table never actually changed; both kinds now join halt/resume/set_autonomy/refresh under `dedupe_key_for(...) is None`, so a repeat POST/DELETE always creates a fresh command (idempotent in effect via the upsert-only handlers, not via dedupe). The generic `POST /commands` route gained the same unknown-symbol `404` check (`src/api/deps.py::assert_known_symbol`, shared with the thin wrappers) the `POST`/`DELETE /universe/{list_name}/{symbol}` routes already had, closing a path that let an owner smuggle an override for a non-existent symbol straight past those wrappers. `GET /universe`'s `removed` field is now derived directly from the override row's `action` plus the `actively_wheeling` guard (matching `_compose_list`'s own guard condition) instead of from `effective_universe()`'s cached composed list — that cache is invalidated only in the exec process that runs the drain, so the API process's own cache instance could read up to 60s stale right after a removal, showing a just-removed symbol as still present with a revert badge that fired the wrong action. `created_at` is now normalized through `routers/options.py`'s `_as_utc` before serializing, so a naive SQLite timestamp doesn't silently render at the wrong relative age in a non-UTC browser. `effective_universe()` now copies (not aliases) every passthrough container one level deep, so its return value can never share object identity with the `lru_cache`-shared `sectors`/`indexes`/`actively_wheeling` config the risk engine reads. `test_the_overridable_set_matches_the_spec_exactly` now pins all four independent declarations of `{"would_own", "watchlist"}` (`OVERRIDABLE_LISTS`, `routers/universe.py::_OVERRIDABLE`, `UniversePayload.list_name`, and both route functions' `list_name` parameters), not just the first. `ARCHITECTURE.md` now notes `effective_universe()`'s `session_scope()` read (and `checks/warnings.py`'s transitive dependency on it) as a deliberate, documented exception to the API's read-only-trading-DB invariant. All gates green again: `python -m pytest -q`, `ruff check .`, `mypy src`, `cd web && npx vitest run`. **Not built, plainly:** no order ticket (spec §4.3, a standing P2 scope decision from M1, not new to this milestone); no Tailscale (same, standing since earlier milestones); and — the one limitation unique to this milestone, by deliberate design — **no override for `sectors`**: it feeds `risk_engine.py`'s concentration limits and stays file-only, unreachable from the web at every layer (API `422` via the `Literal` path-parameter type, the composer's byte-identical passthrough, and the fence test above). `clear_override` (Task 7.1) is built and independently tested but unused by any handler — revert is achieved through the opposite command (`POST`/`DELETE`), not a dedicated hard-revert route; it remains available for a future feature. No Telegram notification fires for a universe edit, deliberately. ~~`refresh`'s command kind (spec §6.6) still has no registered handler anywhere in the codebase~~ **Registered 2026-09-09** — P3/P4 M1 Task 1.4 (`src/notify/command_drain.py::_refresh`) gave it its handler: it captures positions + account values and writes one `portfolio_snapshots` row (`source="refresh"`), creating no approval and no order; `docs/web/commands.md` documents it. P3 (Portfolio), P4 (Profitability tracker), and P5 (Mobile) remain deferred — see the rows immediately below. |
 | **P3 — Portfolio (M1 — the portfolio spine — built 2026-09-09, opencode/glm-5.3; M2 — the portfolio read API — built 2026-09-10, opencode/glm-5.3; M3 — the portfolio UI — built 2026-09-10)** | **M1:** nothing user-visible — no route, no component, no nav change. The API cannot ask IBKR anything, so the two processes that already hold an IB connection now write down what IBKR said, into a table the API reads. **The new table:** `PortfolioSnapshotRow` (`portfolio_snapshots`, `src/storage/models.py`) + `src/storage/portfolio_snapshots.py` — append-only, **no unique constraint** (two rows may share a `captured_at`: a refresh moments after a monitor write must not fail; newest `id` wins a tie), deliberately separate from `position_snapshots` (whose one-row-per-ET-day contract assignment auto-detection diffs — never written by anything new, pinned by a row-count test), pruned by the EOD run to `storage.portfolio_snapshot_retention_days` (default 30) beside `purge_old_risk_verdicts`; `save/load_latest/latest_capture_time/prune` never raise (the monitor calls save from a live event loop). **The two writers:** (1) the intraday monitor's `_maybe_write_snapshot` (`src/monitor/intraday.py`) — called at the *end* of `_refresh_subscriptions` with the positions that pass already fetched (never a second `get_positions`), rate-limited by `market_data.portfolio_snapshot_interval_minutes` (default 15) through a gate that reads the table's newest `captured_at` from the DB (a restart can't burst snapshots; a refresh's row counts toward the interval), RTH-only, account fetch under `asyncio.wait_for`, and wrapped so no exception can escape into `_refresh_loop` — a dead refresh task would silently stop roll alerts for every position opened after that moment, and that failure mode has its own test (`tests/test_monitor_snapshot.py`); (2) the `refresh` drain handler (`src/notify/command_drain.py::_refresh`, the command kind P2 left unregistered — now registered): captures positions + account now, writes one `source="refresh"` row, ignores the monitor's gate, fails `broker_unavailable` without a broker (never writes stale data as fresh), fails `snapshot_failed` on a bad write, sends no Telegram, and creates no approval and no order — the phase's no-new-order-path assertion lives in `tests/test_drain_refresh.py`. **The fallback chain:** `src/api/portfolio_source.py::read_portfolio` → `PortfolioReading` — three rungs (newest `portfolio_snapshots` row; else newest `position_snapshots` + the account block out of `journal.payload["eod_summary"]["account"]` (optional there, validated whole through `AccountSnapshot.model_validate`); else `source="none"`, `snapshot=None` — never a zeroed-out snapshot, because a portfolio page rendering zeros is indistinguishable from an account that's genuinely empty). A corrupt row on any rung falls through rather than failing; `as_of` is the capture time everywhere (via `as_utc_opt`), never request time. **Config keys:** `market_data.portfolio_snapshot_interval_minutes`, `storage.portfolio_snapshot_retention_days` (both documented in `ARCHITECTURE.md`/`SETUP.md`). **The read-side schema:** `PortfolioSnapshot` (`src/common/schemas.py`; `account` optional only on the API's eod rung). **M2:** four owner-only read routes (`src/api/routers/portfolio.py` + `src/api/models/portfolio.py`, mounted under `/portfolio`), all rendering what `read_portfolio` found — no second data path. `GET /summary`: account values as `Sourced` (`Source.IBKR`, `fresh_for` twice the snapshot interval — one missed capture reads stale) beside the exposure block (open positions/shorts/campaigns, net delta per the EOD formula, cash secured against short puts only at `strike × contracts × 100`, buying-power utilisation `null` not `0.0` when buying power is zero, assignment-risk count through the shared M0 predicate). `GET /positions`: grouped by underlying (a `null` `underlying` groups under its own symbol, never dropped), **both cost bases reported** — `avg_cost` from IBKR, `adjusted_cost_basis` from campaigns for assignment shares (both adjusted fields `null` otherwise), `unrealized_pnl` against the former and `unrealized_pnl_adjusted` against the latter so a profitable assigned position can't look like a loss; `moneyness` from the group's stock price else the latest `price_history` close (read-only, the same table `routers/research.py::_hv30_for` reads), `null` when unknown; `dte` `null` never `0`. `GET /campaigns`: the wheel threads with `status`/`symbol` filters, `opened_date` desc with open before closed at the same date, `as_of` request time (written on fill, not captured — documented in the route so nobody "fixes" it), financials gross of commissions (M0 Task 0.4), a pruned candidate still rendering as a leg with `known: false`; `load_campaigns`'s dicts now carry `leg_candidate_ids` for the join. `GET /calendar`: expiries grouped by date over `horizon_days` (default 45, max 365), the `consequence` table exactly as specified (ITM short put `assigned`; ITM short call `called_away` only with stock held, else `assigned`; short OTM/ATM `expires_worthless`; unknown moneyness `unknown` — a real value, never defaulted). Every route's `none` rung is a **200 with explicit emptiness** (`account: null` / `groups: []` / `days: []` + `source="none"` + a plain-words `note`), never a 404 and never zeros. 47 new tests across `tests/test_api_portfolio_{summary,positions,campaigns,calendar}.py`, plus shared fixtures in `tests/conftest.py` (`seed_portfolio_snapshot`, `seed_position_snapshot`, `seed_journal`, `seed_campaign`, `seed_assigned_campaign`, and the `short_put`/`short_call`/`long_put`/`stock` builders) that M4 reuses. `docs/web/openapi.json` and `web/lib/api-types.ts` regenerated (M0 Task 0.5's freshness test green). Gate: `python -m pytest -q` (2043 passed), `ruff check .`, `mypy src` all green. **A verification pass (2026-09-10, independent audit post-build) reproduced the full gate exactly as claimed and confirmed every artifact, then found and fixed four defects in the built code** (each with its own regression test, 47 → 53 across the four files, suite 2049): (1) `GET /positions`' `_stock_leg` called `storage.campaigns.adjusted_cost_basis_for` — which opens the storage engine's read-write `session_scope` from inside the API process — as its *primary* path, inverting the read-only-engine invariant the route itself documented; the read-only query is now primary (mirroring `adjusted_cost_basis_for`'s newest-open-assigned-campaign rule, also fixing a latent `MultipleResultsFound` on two assigned campaigns for one symbol); (2) `OptionLeg.right`/`strike` fabricated `"C"`/`0.0` for snapshots that carried neither and computed `moneyness` against the fabricated pair — both now `null` and `moneyness` requires all three of spot/right/strike; (3) the calendar's horizon gate used a UTC cutoff while its `dte` measured ET — two clocks in one route; both now ET; (4) `GET /campaigns` read the never-pruned `campaigns` table unbounded — now capped by a `limit` query param (default 50, max 200), the same discipline `load_campaigns` and the other list routes follow. **M3 (Tasks 3.1-3.6):** the `/portfolio` console itself — `Money` (`.hatch` unknown, signed figures, `kind`/`complete` rendered as words, never colour alone) and `FreshnessLabel` (Task 3.1); `PortfolioShell` mounting `SummaryPanel` once above a Positions/Campaigns/Calendar tab bar that never remounts it (Task 3.2); `PositionsPanel`/`PositionGroup` grouping stock and option legs by underlying, both cost bases reported (Task 3.3); `CampaignsPanel`/`CampaignThread` — collapsible wheel threads with a real backend-filtered `status`/`symbol` query, gross-of-commissions financials (Task 3.4); `CalendarPanel` and `RefreshControl` — the expiry grid with consequence text per entry, and the one write this page offers, a one-click `POST /commands{kind:"refresh"}` with no confirmation dialog (Task 3.5); the nav flip (`portfolio.available: true`) plus doc updates (Task 3.6). Every panel self-fetches its own route; what each reads from its response differs (`SummaryPanel` alone reads both `source` and `degraded`, `CampaignsPanel` reads neither — `CampaignsResponse` carries only `{as_of, campaigns}`). A whole-branch cross-cutting fix pass (2026-09-10) then closed six Important findings the six tasks' individual reviews couldn't see: `RefreshControl` now self-fetches `GET /options/controls` for the real `drain_healthy` instead of a hardcoded `true`; all four panels poll every 30s so the freshness label doesn't freeze at mount; `CampaignThread`'s `net_premium`/`adjusted_cost_basis`/`realized_stock_pnl` now pass `Money`'s `complete={false}`, since `/portfolio/campaigns` is documented gross of commissions. |
 | **P4 — Profitability tracker (M4 — the P&L engine — built 2026-09-10, opencode/glm-5.3; M5 — the P&L surfaces — built 2026-09-11, opencode/glm-5.3; M6 — system performance and close-out — built 2026-09-11)** | **M4:** the paired realised-P&L accounting rule now exists once, in `src/reporting/` — a package the web layer may read and the trading path may not import (third, read-only analytics tier, both fence directions asserted in `tests/test_web_fence.py`). **Task 4.1 — the dependency inversion:** `fill_economics` and `classify_outcome` moved **verbatim** out of `src/claude/eval/reconcile.py` into `src/reporting/legs.py` (frozen dataclasses replace the tuples; the one addition is `commissions_complete`, which no existing caller reads). `reconcile.py` imports them from there — the fenced reconciler depends on the neutral read-only module, which the fence allows (`eval/` may import a read-only module; the fence stops it reaching the engine). The four reconcile test files pass **unchanged** at the recorded baseline (150). **Tasks 4.2–4.6 — the builders:** the six P&L schemas (`PnlLeg`/`CampaignPnl`/`PnlBucket`/`PnlSummary`/`EquityPoint`/`EquityCurve`, `src/common/schemas.py` — `PnlLeg.outcome` reuses `VerdictOutcome` so the reporting layer and the outcome ledger share one outcome vocabulary); `build_legs` (one `PnlLeg` per filled candidate, newest first; pruned candidates still produce legs with nulls; paper/live filterable and never silently mixed; assignment read from `CampaignRow.assigned`; `roc_pct` credit-over-collateral, `None` when collateral is unknown; `annualized_pct` `None` at `days_held=0`); `build_campaigns` (wheel threads; stock leg read from `CampaignRow`, never recomputed; `snapshot=None` means every unrealised field `None`, never zero; campaign-less legs land in synthetic per-symbol threads so thread legs always sum to the leg count; marks come from the same `PortfolioSnapshot` the portfolio page renders, and a closed leg's `unrealized_pnl` stays `None` forever); `build_summary` (pure; **raises `ValueError` on a mixed paper/live leg list** — the one raise in `src/reporting/`; `win_rate` `None` with nothing closed; `commissions_complete` is the AND of every leg's flag; best/worst chosen among closed legs only; buckets ordered realised-descending, ties by label); `equity_curve` (one point per `JournalRow`; `gaps` lists missed **trading days** — weekends/holidays are not gaps — never interpolated; `net_liquidation` read through `AccountSnapshot.model_validate` so payload drift surfaces as `None`, never a KeyError; `journal.realized_pnl` surfaces as `premium_cashflow` under its true name; `cumulative_realized` sums legs closed on or before each point). **Task 4.7 — the wheel-scenario suite:** five end-to-end scenarios (CSP expiring worthless, the full wheel with called-away stock, a roll chain, missing commission data, paper-vs-live side by side) with hand-written expected literals, plus the three cross-checks: the ledger and the reporting layer agree on every closed trade (one accounting rule — Task 4.1's whole point), the campaign rollup and the leg sum agree gross-vs-gross, and the gross and net views differ by exactly the commission total. **No routes and no UI** — the `/pnl/*` surfaces are M5. **Its numbers have not been reconciled against a broker statement** — the engine is built and tested against seeded data; a live-verification pass comparing `build_legs` output against IBKR's own fills/P&L report remains outstanding, as it does for the rest of the web platform. Gate at close: `python -m pytest -q` (2141 passed), `ruff check .`, `mypy src` all green. **M5 (Tasks 5.1-5.7, built 2026-09-11, opencode/glm-5.3):** the `/pnl` surfaces — every route a thin renderer over `src/reporting/` (the single accounting rule holds at the API boundary too). **Task 5.1 — `GET /pnl/ledger` + `GET /pnl/summary`** (`src/api/routers/pnl.py` + `src/api/models/pnl.py`): `as_of` is request time (the ledger is computed on read) while `marks_as_of` is the snapshot time behind every unrealised figure, from the same single `read_portfolio` call the portfolio page reads (proven by a test comparing the two responses' stamps); filters echo back verbatim; `build_summary`'s mixed-book `ValueError` becomes a `422 {"reason": "mixed_book"}` answer, never a 500 and never a mixed total, while the ledger may still list both books; `n_legs` is checked at the client boundary against the sum of every campaign thread's leg count (synthetic threads included). **Task 5.2 — `GET /pnl/equity`:** `build_legs` feeds `equity_curve` unchanged; `book=all` allowed here deliberately (a curve is a display choice, not a headline total — the asymmetry with the summary is documented in three places so nobody "fixes" it); `premium_cashflow` never named `realized_pnl` anywhere in the response. **Task 5.3 — `GET /pnl/ledger.csv` + the proxy allowlist:** the CSV is built from the same `build_legs`/`build_campaigns` calls the JSON route uses, with unit-suffixed headers (`credit_usd`, `net_pnl_usd`, `roc_pct`, `days_held`), a `book` column, `None` as an empty cell (never `0`), and a dated `Content-Disposition` filename; the proxy (`web/app/api/[...path]/route.ts`) gains an explicit two-name `FORWARDED_RESPONSE_HEADERS` allowlist (`Content-Type`, `Content-Disposition`) — not a passthrough, with its own pinning test so a copy-all regression fails. **Tasks 5.4-5.6 — the UI** (`web/app/pnl/page.tsx` + `web/components/pnl/{PnlShell,LedgerTable,CampaignRow,LegRow,LedgerFilters,SummaryPanel,BreakdownTable,EquityChart}.tsx`): the ledger grouped by campaign with `<button aria-expanded>` threads; no unknown renders as a zero anywhere (open leg's realised is `n/a`, `win_rate: null` is `n/a`, `marks_as_of: null` renders "no marks available" and every unrealised cell `n/a`, gross qualifier on incomplete commissions); a `422 mixed_book` renders a labelled book-choice group in plain words — a normal situation, not an error state; the equity chart renders gaps as gaps (`connectNulls={false}`), never animates (`isAnimationActive={false}`), reads colours from CSS custom properties at mount, labels `premium_cashflow` under that name, states the start date in words, and mirrors its real props onto `data-series` wrapper elements because Recharts does not expose them as DOM attributes; filters drive the query string so the CSV export link carries the same filters (one composition in `PnlShell`, never two); `Money` reused from `components/portfolio/` in every leg/campaign/summary figure — no second money component; `FreshnessLabel`/`DegradedNotice` are not used on this page (the ledger and summary carry their own `marks_as_of`/`mixed_book` renderings instead). Best/worst legs in the summary link into the ledger tab (filtered to that leg's symbol, the closest cross-reference the ledger's filters expose). **Task 5.7 — nav flip + docs + regen:** `pnl` flipped `available: true` in `_SECTIONS` (every section now available, no note), `tests/test_api_meta.py` updated, `docs/web/api.md` documents all four routes with the `as_of` vs `marks_as_of` distinction and the `mixed_book` refusal, `web/CLAUDE.md` gains the `app/pnl/`+`components/pnl/` layout entries and the proxy-allowlist section, `README.md`/`ARCHITECTURE.md` rows updated, `docs/web/openapi.json` + `web/lib/api-types.ts` regenerated (freshness test green). **Conftest:** the M4 `db` fixture pointed the storage engine at a private `t.db` while the API client read `income_system.db` — invisible while builders were called directly, exposed the moment a route test crossed the boundary — so tests/conftest.py gained a `db` override that rebinds the storage engine to the client's file (via the `client` fixture) plus a shared `seed_wheel` fixture; M4's own suite passes unchanged at its recorded baseline. **The M4 broker-statement caveat still stands:** the engine and now the surfaces are built and tested against seeded data; a live-verification pass comparing the ledger against IBKR's own fills/P&L report remains outstanding. Gate at close: `python -m pytest -q` (2175 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (334 passed, 42 files) `&& npm run lint && npm run build` — all six green. **Also fixed in passing (pre-existing flake, exposed at this timezone):** the portfolio calendar tests and the conftest position builders seeded expiries from the local clock while `routers/portfolio.py` measures dte and its horizon gate on the ET exchange calendar — whenever the two calendars straddle midnight (any evening after 8pm ET, or running the suite from a non-ET machine) every default-dte position lands one day past the 45-day horizon and the calendar tests fail on `days[0]`. The builders (`short_put`/`short_call`/`long_put`) and the calendar tests' `_day()`/boundary assertions now derive from `_et_today()` (tests/conftest.py), the same clock the route itself reads. **M6 (Tasks 6.1-6.4, built 2026-09-11):** the score-vs-outcome evidence `src/claude/eval/score_metrics.py` already produced gets its reader, and the two fences this phase leans on are enforced by tests rather than by intention. **Task 6.1 — `GET /pnl/system`:** the one P&L route that reads behind the `src/claude/eval/` fence, and the reason is written down in its own docstring and in `docs/web/api.md` — `CLAUDE.md` already says everything `eval/` produces "is read by a human, never auto-applied," and this route is that human's reader, not a breach of it. It calls `score_outcome_report(since, until)` and returns exactly what it gets (a test spies on the call and asserts exactly one), adds a new `VerdictAgreement` figure computed here from `ledger.load_records(closed_only=True)` (Claude-vs-baseline agreement rate plus each side's win rate, windowed on `outcome_date` the same way the report is), and answers the empty case with the report's own "nothing to correlate yet" note rather than a `404`. `agreement_rate`/`claude_win_rate`/`baseline_win_rate` are `null` with zero closed rows, never `0.0`. **Task 6.2 — the System tab:** `SystemPanel`/`ScoreBucketTable`/`CorrelationTable` (`web/components/pnl/`), wired into `PnlShell` as a third tab with its own since/until window state, independent of the ledger's filters. `SystemPanel` is presentational (a `data` prop, like `EquityChart`) since the shell owns the fetch. Every note in the report renders in full and in order — the read-only "re-derive the scoring config by hand" sentence is why the surface is allowed to exist, and it is not the UI's to paraphrase; a bucket with `n` under 5 is labelled "small sample" in words; `n_closed: 0` renders the note and no tables at all, never empty tables with `n/a` rows; the only controls anywhere on the tab are the two date inputs, asserted by a test that counts every button/input/select in the panel. **Task 6.3 — five new fence tests** (`tests/test_web_fence.py`): no module under `src/api/` can write the verdict ledger or reference the scoring config by filename; the API still writes exactly one table (re-asserting the P2 guarantee, with the same `trading_db.py` exception the existing P2 test already carries, since that module *defines* the write handle rather than using it); `src/reporting/` never touches a DB session; `save_portfolio_snapshot` still has exactly its two intended callers (the monitor and the drain). One real trip surfaced and was fixed during this task: `pnl_system`'s own docstring named the scoring config by its literal filename in prose, tripping the new check even though it was never a code reference — reworded, not weakened, since the fence's point is that the name should be unreachable from `src/api/` by grep. **Task 6.4 — close-out:** re-derived rather than re-asserted — every command failure reason in `src/notify/command_drain.py` (extracted correctly this time, accounting for the multi-line `CommandFailed(...)` calls the milestone's own literal grep missed, same class of gap the P2 close-out log already flagged) appears in `docs/web/commands.md`; `docs/web/openapi.json` and `web/lib/api-types.ts` both regenerate to an empty diff (generated directly from the checked-in `openapi.json` file rather than via `npm run gen:api` against `:8787`, since a live API instance was already running there for other purposes and was left untouched); `README.md`'s layout table and `ARCHITECTURE.md`'s folder guide were already accurate for every P3/P4 module before this pass (confirmed, not re-written). **P3 and P4 are both complete. Not built:** P5 (mobile/responsive shell), operator notes on legs and campaigns, a materialised P&L table, intraday equity history beyond the snapshot retention window, and any Tailscale or remote hosting. **The ledger's numbers have not been reconciled against a broker statement** — every P&L figure across P3 and P4 is built and tested against seeded data; a live-verification pass comparing `build_legs`/`build_campaigns` output against IBKR's own fills/P&L report remains outstanding. Gate at close: see the implementation log in `Web plan/P3-P4-IMPLEMENTATION-PLAN.md` for the exact numbers. |
-| **Web overhaul (Parts 1-5 built; Parts 6-8 and order control not started, 2026-10-13 onward)** | **Part 1 built 2026-10-14** (`docs/superpowers/plans/2026-10-13-web-overhaul-1-foundation-home.md`): the payslip design system (`web/DESIGN.md`), the new shell and Home, and three read-only routes (`GET /portfolio/value`, `GET /pnl/month`, `GET /spreads/positions`). **Part 2 (Trades) built 2026-10-19** (`docs/superpowers/plans/2026-10-19-web-overhaul-2-trades.md`, see "Built (2026-10-19 — web overhaul Part 2)" below). **Part 3 (Portfolio and Activity) built 2026-10-28** (`docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md`, see "Built (2026-10-28 — web overhaul Part 3)" below). **Part 4 (cleanup, honesty and the value gaps) built 2026-11-05** (`docs/superpowers/plans/2026-11-05-web-overhaul-4-cleanup-honesty-value-gaps.md`, see "Built (2026-11-05 — web overhaul Part 4)" above): it deleted the legacy files Parts 2 and 3 left unmounted, removed `GET /nav`, made unknown say "could not read" instead of none, gave the value book its places (the drain note, Needs you, Portfolio, At IBKR) and added route titles and the not-found and error pages. **Part 5 (the stock page) built 2026-11-06** (`docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md`, see "Built (2026-11-06 — web overhaul Part 5)" above). **Not started, no plan yet (HANDOFF section 5):** Part 6, Research, Universe and search; Part 7, News, More and How it works; Part 8, the value record (gated on a month of paper record); and order control (cancelling a working order from the web), on its own track with a spec first. |
+| **Web overhaul (Parts 1-6 built; Parts 7-8 and order control not started, 2026-10-13 onward)** | **Part 1 built 2026-10-14** (`docs/superpowers/plans/2026-10-13-web-overhaul-1-foundation-home.md`): the payslip design system (`web/DESIGN.md`), the new shell and Home, and three read-only routes (`GET /portfolio/value`, `GET /pnl/month`, `GET /spreads/positions`). **Part 2 (Trades) built 2026-10-19** (`docs/superpowers/plans/2026-10-19-web-overhaul-2-trades.md`, see "Built (2026-10-19 — web overhaul Part 2)" below). **Part 3 (Portfolio and Activity) built 2026-10-28** (`docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md`, see "Built (2026-10-28 — web overhaul Part 3)" below). **Part 4 (cleanup, honesty and the value gaps) built 2026-11-05** (`docs/superpowers/plans/2026-11-05-web-overhaul-4-cleanup-honesty-value-gaps.md`, see "Built (2026-11-05 — web overhaul Part 4)" above): it deleted the legacy files Parts 2 and 3 left unmounted, removed `GET /nav`, made unknown say "could not read" instead of none, gave the value book its places (the drain note, Needs you, Portfolio, At IBKR) and added route titles and the not-found and error pages. **Part 5 (the stock page) built 2026-11-06** (`docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md`, see "Built (2026-11-06 — web overhaul Part 5)" above). **Part 6 (Research, Universe and search) built 2026-11-06** (`docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md`, see "Built (2026-11-06 — web overhaul Part 6)" above). **Not started, no plan yet (HANDOFF section 5):** Part 7, News, More and How it works; Part 8, the value record (gated on a month of paper record); and order control (cancelling a working order from the web), on its own track with a spec first. |
 | **P5 — Mobile** | A native app is deliberately not built. The web console is responsive since web overhaul Part 1 (phone tab bar, bottom sheets, 44px phone targets on the new surfaces). |
 
 Invariants (see `CLAUDE.md` and `Web plan/P0-P1-design.md` §4.3/§4.7 and `Web plan/P2-design.md` §4.2): the API process holds no
diff --git a/web/CLAUDE.md b/web/CLAUDE.md
index 062ca96..a0488ce 100644
--- a/web/CLAUDE.md
+++ b/web/CLAUDE.md
@@ -104,7 +104,9 @@ app/                App Router pages and the root layout
                     that calls `reset`. No `loading.tsx` (every page draws its own `role="status"`
                     skeleton) and no `global-error.tsx` (the root layout renders no data). Both are
                     pinned by `boundaries.test.tsx`.
-  titles            Every route has its own title (`titles.test.ts` pins them): a server page exports
+  titles            Every route has its own title (`titles.test.ts` pins them; since web overhaul Part 6 a
+                    dynamic segment is decoded through lib/segment.ts, so a malformed `%` keeps the raw
+                    segment instead of throwing): a server page exports
                     `metadata`; a client page gets a sibling server `layout.tsx` that renders
                     `children` and exports `metadata`, or `generateMetadata` for a dynamic segment
                     (`more`, `more/claude`, `research`, `research/universe`, `stock/[symbol]`,
@@ -155,15 +157,14 @@ app/                App Router pages and the root layout
                     Read-only: one request, `GET /claude/context`, and five cards (Regime and
                     limits, Market picture, What each Claude call reads, Dropped as noise, Names).
                     No news service says so in a sentence and the regime still shows.
-  research/         Research, the old landing page (moved from app/page.tsx): a header
-                    row with the page title and a visible
-                    search-bar button (opens the same <CommandPalette/> ⌘K does — the
-                    page owns `searchOpen` state and passes it as controlled
-                    `open`/`onOpenChange` props), then <TopOpportunities/> (features/research/),
-                    then WatchlistTable, then SectorGrid
-                    (ordered by IV rank). A client component because the watchlist and
-                    sector grid use react-query.
-  research/universe/  (moved from universe/; `/universe` redirects here) Universe page: react-query on GET /universe (M7: `lists[]`, one
+  research/         Research (web overhaul Part 6): page.tsx only mounts
+                    features/research/ResearchPage (the title with Search, which calls
+                    lib/search.ts `openSearch` to open the shell's one palette, and a Universe
+                    link; Top opportunities; then Your watchlist and the Sectors card).
+  research/universe/  (moved from universe/; `/universe` redirects here) Universe page; since web overhaul
+                    Part 6 page.tsx only mounts features/universe/UniversePage (a back link to Research,
+                    one card per list, two columns from 1024px, loading and failure in words). What
+                    follows is unchanged: react-query on GET /universe (M7: `lists[]`, one
                     UniverseListOut per section, replacing the old flat per-list
                     arrays), renders each list through <UniverseList/>. Writable since
                     M7 Task 7.5 (`editable: true`): would_own and watchlist accept add
@@ -261,8 +262,8 @@ components/          Where new code goes (web overhaul Part 4, HANDOFF D4): `fea
                     days out, Today and Clear in the foot; dates.ts is its UTC day arithmetic).
                     Activity's Book, Outcome, Since and Until and the ledger Trades page's filters use
                     them; a test drives them with `lib/test-pick.ts` (`chooseOption`, `chooseDay`).
-  shell/            Web overhaul Part 1: Rail (desktop, from 768px: the lib/nav.ts
-                    destinations, the lime pending-count badge on Trades, BotCard at its
+  shell/            Web overhaul Part 1: Rail (desktop, from 768px: since Part 6 a Search row under the
+                    wordmark that calls `openSearch()`, then the lib/nav.ts destinations, the lime pending-count badge on Trades, BotCard at its
                     foot), TabBar (phones: five tabs; Research and News mark More
                     current), BotCard (running or halted in words, mode, rung, the
                     not-draining line; aria-haspopup; a loading block) and BotSheet (the
@@ -299,7 +300,13 @@ components/          Where new code goes (web overhaul Part 4, HANDOFF D4): `fea
                     matching lines at this level" when it exists but nothing matched -
                     so a healthy daemon's clean log is never reported as if it had never
                     run)
-  search/           CommandPalette (⌘K/Escape as before; controlled if `open`/
+  search/           CommandPalette. Since web overhaul Part 6 it is mounted ONCE, in app/layout.tsx, and
+                    nothing else mounts it: the rail's Search row, More's Search row and Research's
+                    Search button call lib/search.ts `openSearch()`, whose event it listens for. It
+                    lists the console's pages (features/search/pages.ts, no request) above the tickers
+                    (GET /research/search), is a combobox (aria-activedescendant; the arrow keys move,
+                    Enter opens, Escape or a tap on the scrim closes, Close on a phone), and says its
+                    state in one always-mounted `role="status"` line. The older notes follow: (⌘K/Escape as before; controlled if `open`/
                     `onOpenChange` props are passed — the home page's visible search-bar
                     button drives it that way — otherwise falls back to its own internal
                     open state so ⌘K still works standalone anywhere it's mounted with
@@ -316,7 +323,12 @@ components/          Where new code goes (web overhaul Part 4, HANDOFF D4): `fea
                     during React's commit, before any effect can run, so it would steal
                     focus out from under the open-edge effect's own capture of the prior
                     trigger before that capture ever happened)
-  home/             SectorGrid (react-query on GET /research/sectors, renders SectorCard
+  home/             Restyled in place in web overhaul Part 6: WatchlistTable is the "Your watchlist" card
+                    (rows, not a table; the move signed and never green or red; a hatched n/a for
+                    every unknown; loading, a failed read, add or remove in words; a line pointing to
+                    the scan's own watchlist on Universe) and SectorGrid is one "Sectors by IV rank"
+                    card whose rows are SectorCard (an `li`, no green or red). The older notes follow:
+                    SectorGrid (react-query on GET /research/sectors, renders SectorCard
                     ordered by avg_iv_rank desc; a sector with no IV history sorts last),
                     SectorCard (sector name + count, daily change with sign + colour never
                     colour alone, best/worst movers, avg IV rank with contributing count so a
@@ -555,7 +567,11 @@ components/          Where new code goes (web overhaul Part 4, HANDOFF D4): `fea
                     CampaignsView, CalendarView), and the rules they carried (n/a never "$0.00",
                     the degraded note verbatim, filters in the request, an unknown consequence
                     named) are those views' tests.
-  universe/         M7 Task 7.5. UniverseList (one GET /universe section: heading with
+  universe/         Restyled in place in web overhaul Part 6: each UniverseList is a Card (17px title, the
+                    count, one line on what the list is for), Wheeling and Dip-watch are status words,
+                    Remove and Revert are 44px on a phone, AddSymbol has a visible label on the `field`,
+                    and a failure is plain words, never red; the behaviour below is unchanged.
+                    M7 Task 7.5. UniverseList (one GET /universe section: heading with
                     entry count, a row per entry with sector tag, strike-band
                     override, and, for would_own only, a wheeling/dip-watch tag; a
                     non-overridable list renders a config/universe.yaml note instead
@@ -788,7 +804,13 @@ features/
                     (a Card per section: the title, then the content, or the API's reason / "Building this
                     section." in words), and stock.ts (`valueLeads`, `valueLines`, `nameLine`, the
                     `Analysis` alias over the generated AnalysisResponse). The page reads; its only command
-                    is AnalyseButton inside the value block.
+                    is AnalyseButton inside the value block. Since web overhaul Part 6 the value block
+                    mounts only once GET /value/{symbol} has answered (or failed), in the slot the
+                    answer picks, so it never mounts at the foot and moves.
+  search/           Web overhaul Part 6: pages.ts (PAGES, the console's own pages, and `matchPages`: every
+                    typed word must match a page's name, hint or words; at most five). The palette is
+                    components/search/CommandPalette; the open event is lib/search.ts.
+  universe/         Web overhaul Part 6: UniversePage (see app/research/universe above).
   stock-value/      The value book's view of one name on the stock page (value book Part 6, Section G).
                     ValueBlock (react-query on GET /value/{symbol}, key ["value","ticker",SYMBOL]:
                     the verdict per list first, then BusinessBlock, WorthBlock and SizeBlock for the spec's
@@ -806,7 +828,9 @@ features/
                     held name), else at the foot of the left column. Since web overhaul Part 5 SizeBlock
                     says the size tier per priced list (`sizeSegment`) and a held name's tranche plan
                     (`trancheWords`).
-  research/         Top opportunities (value book Part 6, Section H), the strip above the watchlist.
+  research/         ResearchPage (web overhaul Part 6, the `/research` page) and Top opportunities (value
+                    book Part 6, Section H), the strip above the watchlist; since Part 6 OpportunityCard
+                    shows `claude_note` after Python's reasons, labelled "Claude's note", never on a button.
                     TopOpportunities (two tabs on a SegmentedControl, Deep value and Quality growth; react-query
                     on GET /value/top?list=, key ["value","top",list], only the list on view is fetched; a second
                     query, key ["value","top","assessed-passed"], reads `GET /options/assessed?run=latest&stage=
@@ -1025,7 +1049,12 @@ lib/
   useHydrated.ts    `useHydrated()` (moved out of HomePage; Home and Trades both use it): false for
                     the server render and the hydration pass, so a page whose query shares a key
                     with the rail renders its bare shell until hydration is over
-  nav.ts            NAV (the seven destinations, which five sit on the phone tab bar),
+  search.ts         Web overhaul Part 6: OPEN_SEARCH_EVENT and `openSearch()`, the one way to open the
+                    shell's search palette.
+  segment.ts        Web overhaul Part 6: `decodeSegment`, a dynamic segment decoded for a title, the raw
+                    segment when the escape is malformed.
+  nav.ts            NAV (the seven destinations, which five sit on the phone tab bar; Research's
+                    icon is a telescope since Part 6, so the magnifier means search),
                     activeKey and phoneActiveKey
   strategy.ts       StrategyKind / StrategyFilter, labels and eyebrows, kindOf (a roll
                     files under the side it rolls; unknown strategies only under All),
````

### Task 15: The da-vinci finish by a fresh reviewer (sonnet, effort high)

**Spawned by the orchestrator as a new subagent with no prior context.** Its prompt: this plan's Global Constraints,
rulings 2-14, `web/DESIGN.md` (the Search palette component, the Research and Universe surfaces), "Invoke the `da-vinci`
skill first and run `critique`, then `audit`, then `polish` over Research, Universe, the palette and the rail", "never
the live API, never inside `web/`, never on port 3000".

- [ ] **Step 1: The synthetic API.** `mock6` was extracted in A0 to `<S>/p6/mock6.out`. Copy it to `<S>/p6/mock6.py`
  and run it in the background: `python3 <S>/p6/mock6.py` (port 8799). It serves Top opportunities (GOOGL Ready with
  Claude's note, KO Watch without), a watchlist (one delayed row, one all-unknown row, one long price), four sectors
  (one with no IV history), the four universe lists (an override, a removed base name, Wheeling and Dip-watch), the
  ticker search, and the routes the shell and More read.
- [ ] **Step 2: A scratch build served on 3101.** G4's copy and build in `<S>/p6/build` (keep it), then in the
  background: `cd <S>/p6/build/web && API_URL=http://127.0.0.1:8799 API_TOKEN=mock npx next start -p 3101`. Wait until
  `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3101/research` prints 200.
- [ ] **Step 3: Captures.** Copy `capture6` to `<S>/p6/capture6.cjs`, `mkdir -p <S>/p6/shots`, then
  `node <S>/p6/capture6.cjs <a playwright-core directory from E3, without /package.json> <S>/p6/shots` (the prototype
  ran with `~/.npm/_npx/e41f203b7505f1fb/node_modules/playwright-core`). It captures Research, Universe and More at
  320, 390 and 1440 px, light and dark, **in chunks by scrolling `main`** (the shell scrolls `main`, not the document;
  Part 5's lesson), plus the palette open on Research with "a" typed and the second result active, and prints per page
  `hscroll` measured on `main`, the `h2` order and, on a phone, every control in `main` under 44 px. Expected (checked in
  the prototype): `hscroll` 0 everywhere and no `pageErrors`; Research's `h2` order Top opportunities, Your watchlist,
  Sectors by IV rank; Universe's Indexes, Watchlist, Would own, Actively wheeling; the palette shows a Pages group
  (Activity, Pay ... ) and a Tickers group (AAPL, AMZN), 7 options. Under 44 px on a phone, expected and accepted: the
  two list tabs on Research (34 px pills with a 44 px hit area, DESIGN.md's rule), the inline "Universe" link inside the
  watchlist's sentence (an inline link in prose, WCAG 2.5.8's inline exception), and More's legacy theme, target-mode
  and credits controls (outside this part). Open and look at every capture.
- [ ] **Step 4: critique, audit, polish.** Fix what they find, each behaviour fix with a test written red first; no new
  token (a proposal waits for the operator); nothing in the protected files. Record every finding not fixed, with a
  reason, in the Progress log row.
- [ ] **Step 5: Gate and commit.** Every web gate; G1-G5, G7; stop the two background servers
  (`pkill -f "next start -p 3101"`, `pkill -f mock6.py`); remove `<S>/p6/build` by literal path (symlink first). Commit
  `fix(web): da-vinci finish of Research, Universe and search` (if nothing changed, record "no change" and commit only
  the log row).

<!-- block mock6 -->
````python
"""A synthetic API for web overhaul Part 6's visual check (Task 15). Never the live one.
Research: Top opportunities (one READY name with Claude's note, one WATCH without), a watchlist with a known
and an all-unknown row, four sectors (one with no IV history). Universe: all four lists, an override, a
removed base name, a wheeling and a dip-watch name. Search: tickers for any term containing A or S."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

AT = "2026-11-06T15:00:00Z"


def top(list_name):
    items = []
    if list_name == "deep_value":
        items = [
            {"symbol": "GOOGL", "list_name": "deep_value", "verdict": "READY", "decided_by": "claude", "price": 182.4,
             "fair_value": 215.0, "entry_ceiling": 190.0, "stop": None, "half_sell": 215.0, "mos": 0.151,
             "reasons": ["healthy, cheap enough, timing passes"], "put_ceiling": 190.0, "age_days": 1,
             "claude_note": "Search share is holding and cloud margins carry the bear case; the buyback keeps the share count falling."},
            {"symbol": "KO", "list_name": "deep_value", "verdict": "WATCH", "decided_by": "python", "price": 61.2,
             "fair_value": 64.0, "entry_ceiling": 55.0, "stop": None, "half_sell": 64.0, "mos": 0.044,
             "reasons": ["price 61.20 above the entry ceiling 55.00"], "put_ceiling": None, "age_days": 3,
             "claude_note": None},
        ]
    return {"as_of": AT, "available": True, "list_name": list_name, "items": items}


def entry(symbol, **over):
    e = {"symbol": symbol, "overridden": False, "removed": False, "created_by": None, "created_at": None}
    e.update(over)
    return e


ROUTES = {
    "/options/controls": {"as_of": AT, "autonomy": {"level": "full", "label": "Full"}, "rungs": [], "halted": False,
                          "halt_reason": None, "halted_at": None, "mode": "paper", "drain_healthy": True,
                          "drain_last_seen": AT, "pending_commands": 0},
    "/options/approvals": {"as_of": AT, "approvals": []},
    "/options/assessed": {"as_of": AT, "run": None, "groups": []},
    "/system/status": {"as_of": AT, "rows": []},
    "/pnl/target": {"as_of": AT, "source": "none", "target": {"mode": "off", "amount": None, "pct": None, "base": None}},
    "/pnl/month": {"as_of": AT, "book": "paper", "spreads_available": True, "pay": {"month": "2026-11-01", "month_start_value": None}},
    "/watchlist": {"as_of": AT, "items": [
        {"symbol": "NVDA", "name": "NVIDIA Corporation", "price": {"value": 120.0, "source": "ibkr", "as_of": AT, "stale": True},
         "change_pct": -1.25, "iv_rank": 80.0, "checks": {"passed": 3, "evaluable": 5, "unknown": 1}, "next_earnings": "2026-11-19"},
        {"symbol": "BRK.B", "name": "Berkshire Hathaway Inc. Class B", "price": None, "change_pct": None, "iv_rank": None,
         "checks": {"passed": 0, "evaluable": 0, "unknown": 4}, "next_earnings": None},
        {"symbol": "PLTR", "name": "Palantir Technologies Inc.", "price": {"value": 1234.56, "source": "ibkr", "as_of": AT, "stale": False},
         "change_pct": 12.5, "iv_rank": 99.9, "checks": {"passed": 5, "evaluable": 5, "unknown": 0}, "next_earnings": "2026-12-01"},
    ]},
    "/research/sectors": {"as_of": AT, "sectors": [
        {"sector": "Semiconductors", "count": 7, "change_pct": 1.5, "best": {"symbol": "NVDA", "change_pct": 3.1},
         "worst": {"symbol": "INTC", "change_pct": -2.4}, "avg_iv_rank": 71.2, "iv_rank_count": 7},
        {"sector": "Banks", "count": 4, "change_pct": -0.3, "best": {"symbol": "JPM", "change_pct": 0.4},
         "worst": {"symbol": "C", "change_pct": -1.1}, "avg_iv_rank": 40.0, "iv_rank_count": 1},
        {"sector": "Consumer staples", "count": 3, "change_pct": 0.0, "best": {"symbol": "KO", "change_pct": 0.2},
         "worst": {"symbol": "PG", "change_pct": -0.2}, "avg_iv_rank": 22.5, "iv_rank_count": 3},
        {"sector": "Bonds", "count": 1, "change_pct": None, "best": {"symbol": "TLT", "change_pct": None},
         "worst": {"symbol": "TLT", "change_pct": None}, "avg_iv_rank": None, "iv_rank_count": 0},
    ]},
    "/universe": {"as_of": AT, "editable": True,
                  "sectors": {"NVDA": "Semiconductors", "AAPL": "Technology", "KO": "Consumer staples", "COIN": "Financials"},
                  "strike_bands": {"NVDA": 0.85},
                  "lists": [
                      {"name": "indexes", "overridable": False, "entries": [entry("SPY"), entry("QQQ")]},
                      {"name": "watchlist", "overridable": True, "entries": [entry("PLTR"), entry("TSLA", overridden=True, created_by="owner", created_at=AT)]},
                      {"name": "would_own", "overridable": True, "entries": [entry("NVDA"), entry("AAPL"), entry("KO"),
                                                                              entry("COIN", overridden=True, removed=True, created_by="owner", created_at=AT)]},
                      {"name": "actively_wheeling", "overridable": False, "entries": [entry("NVDA")]},
                  ]},
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        path, q = url.path, parse_qs(url.query)
        if path == "/value/top":
            body, code = top(q.get("list", ["deep_value"])[0]), 200
        elif path == "/research/search":
            term = q.get("q", [""])[0].upper()
            hits = [h for h in [
                {"symbol": "AAPL", "name": "Apple Inc.", "exchange": "NASDAQ", "is_etf": False},
                {"symbol": "AMZN", "name": "Amazon.com, Inc.", "exchange": "NASDAQ", "is_etf": False},
                {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust", "exchange": "NYSE Arca", "is_etf": True},
            ] if term and (term in h["symbol"] or term in h["name"].upper())]
            body, code = {"as_of": AT, "query": term, "results": hits}, 200
        elif path in ROUTES:
            body, code = ROUTES[path], 200
        else:
            body, code = {"detail": f"mock: no route for {self.path}"}, 404
        payload = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # quiet
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8799), Handler).serve_forever()
````

<!-- block capture6 -->
````javascript
// Captures for web overhaul Part 6, Task 15. Usage:
//   node capture6.cjs <path to playwright-core> <output dir> [base url]
// Research, Universe and More at 320, 390 and 1440 px, light and dark, plus the search palette open on
// Research with "a" typed. The shell scrolls <main>, not the document, so each page is captured in
// viewport-high chunks by scrolling <main>, and the sideways overflow is measured on <main>.
// Never point it at the live API or the operator's next dev on 3000.
const { chromium } = require(process.argv[2]);
const outDir = process.argv[3];
const base = process.argv[4] ?? "http://127.0.0.1:3101";
const PAGES = [["research", "/research"], ["universe", "/research/universe"], ["more", "/more"]];
(async () => {
  const browser = await chromium.launch({ headless: true });
  const report = [];
  for (const theme of ["light", "dark"]) {
    for (const width of [320, 390, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      await page.addInitScript((t) => localStorage.setItem("ibkr-theme", t), theme);
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      for (const [name, path] of PAGES) {
        await page.goto(`${base}${path}`, { waitUntil: "networkidle" });
        await page.waitForTimeout(800);
        const m = await page.evaluate(() => {
          const main = document.querySelector("main");
          return { sw: main.scrollWidth, cw: main.clientWidth, sh: main.scrollHeight, ch: main.clientHeight };
        });
        const chunks = Math.min(6, Math.ceil(m.sh / m.ch));
        for (let i = 0; i < chunks; i++) {
          await page.evaluate((y) => document.querySelector("main").scrollTo(0, y), i * m.ch);
          await page.waitForTimeout(150);
          await page.screenshot({ path: `${outDir}/${name}-${width}-${theme}-${String.fromCharCode(97 + i)}.png` });
        }
        const small = await page.evaluate(() =>
          [...document.querySelectorAll("main a, main button, main input")]
            .map((el) => ({ el, r: el.getBoundingClientRect() }))
            .filter(({ r }) => r.width > 0 && r.height > 0 && r.height < 44)
            .map(({ el, r }) => `${el.tagName.toLowerCase()} "${(el.textContent || el.getAttribute("placeholder") || "").trim().slice(0, 30)}" ${Math.round(r.height)}px`),
        );
        report.push({
          name, width, theme, hscroll: m.sw - m.cw,
          h2: await page.evaluate(() => [...document.querySelectorAll("main h2")].map((h) => h.textContent)),
          under44: width < 768 ? small : undefined,
        });
      }
      await page.goto(`${base}/research`, { waitUntil: "networkidle" });
      await page.keyboard.press(process.platform === "darwin" ? "Meta+k" : "Control+k");
      await page.waitForTimeout(200);
      if (!(await page.getByRole("dialog").count())) await page.keyboard.press("Control+k");
      await page.keyboard.type("a");
      await page.waitForTimeout(700);
      await page.keyboard.press("ArrowDown");
      await page.screenshot({ path: `${outDir}/palette-${width}-${theme}.png` });
      report.push({
        name: "palette", width, theme,
        groups: await page.evaluate(() => [...document.querySelectorAll("[role=dialog] [role=group]")].map((g) => g.textContent.slice(0, 60))),
        options: await page.evaluate(() => document.querySelectorAll("[role=option]").length),
      });
      report.push({ width, theme, pageErrors: errors });
      await page.close();
    }
  }
  console.log(JSON.stringify(report, null, 1));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
````

**Then:** one **opus** whole-branch review (superpowers:requesting-code-review, effort high) over `main..HEAD` with the
Review Focus; the orchestrator confirms each finding in the code; one **sonnet** fix pass (high), each fix test first;
fill both rows; superpowers:finishing-a-development-branch. **No merge or push without the operator.** On the
operator's yes, from the main checkout on a clean `main`: `git merge --ff-only feat/web-overhaul-6` (if `main` moved,
stop and ask) and fill the Merge row; push when told and fill the Push row; then `./ibkr restart` (the web needs only
`next dev`'s rebuild, but restart keeps the stack on one commit) and fill the Restart row with the `ps` start time.

---

## Operator to-dos

1. Before Section B, overturn any of rulings 5-9 you dislike (one palette in the shell, the combobox, pages first, the
   rail's Search row and Research's telescope icon). Before Section C, rulings 10-13 (the Research layout, Your
   watchlist's rows, the sectors as one card, Claude's note). After that they cost a rework.
2. After the merge: `./ibkr restart` (no API change, but the stack then runs one commit).
3. Look once at Research and the palette on a phone in dark mode.
4. Housekeeping from the HANDOFF (7.3 item 3).

## Self-review (run by the plan's author, 2026-11-06)

- **Spec coverage.** HANDOFF Part 6 row: L1 (Tasks 8-11), L3 (12-13), S1 (5-7), V7 card (11), S5 Research and
  Universe (10, 12), the save-side tests (2), the `generateMetadata` guard (1), the position page fixes (4); the
  operator's three answers (rulings 2-4: Tasks 5-7, 8, 3).
- **Prototype.** As the Plan written row: every patch was cut from a per-task git history of a prototype that passed
  the full web gates at every task, the Python gates on the final tree and a scratch build, and was rendered against
  `mock6` at three widths in both themes.
- **Placeholders.** None: every change is a patch; the two scripts are given in full; commands carry expected output.
- **Consistency.** `openSearch`/`OPEN_SEARCH_EVENT` (lib, palette, rail, More, Research, tests), `matchPages`/`PAGES`,
  `decodeSegment` (five layouts), `valuePending` (StockPage), "Your watchlist" (card, tests, DESIGN.md, docs), the five
  list labels (UniverseList, UniversePage test, DESIGN.md).
