# Web Overhaul, Part 4: Cleanup, Honesty and the Value Gaps (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task (natively, or one subagent per section on the labelled model and effort, with a stop between sections: the operator's token-light method). The plan has seven sections; each opens with **entry checks** that must all pass before its first task starts. **Every task that touches UI starts by invoking the `da-vinci` skill**, and so does any subagent given one of those tasks (say so in its prompt). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the debts the overhaul and the value book left on the pages that are already built, before
any new page is recomposed:

- **Stop two false or silent things the value book causes today** (the book is on in paper): a wheel put
  bought back to fund a value buy reads "Bought back; the reason was not recorded" on Done today, History
  and the position page, and a web tap on a value proposal shows "Queued" forever when the value process is
  not running. These ship first, on their own (Section A), so they can reach `main` before the rest.
- **Delete what Parts 2 and 3 left unmounted**, after porting the tests that are the only coverage of live
  code (the decide flow, the roll flow, the drain warning), and remove the unused `GET /nav`.
- **Make the value book visible where it is missing**: "Needs you" and the phone banner, the Portfolio
  register, the IBKR executions list; stop flagging "Value book unavailable" on an install whose book is
  off and never ran.
- **Fix the honesty minors** Parts 2 and 3 deferred (unknown that reads as none, a capped list that reads as
  whole, a raw code on screen, a back link that forgets where you were) and link History and Fills to each
  other.
- **Give every route a title, a not-found page and an error page.**
- **Run the da-vinci finish the value book's web sections skipped** (a fresh reviewer agent, dark captures).

**Architecture:** Two backend sections, both read-side except one heartbeat write. Section A adds one
`CloseReason` entry to `src/reporting/day.py` and a value-process drain heartbeat: `scripts/run_value.py`
writes `value_drain_heartbeat` to the trading DB's `system_settings` after every drain (as `command_drain`
does for `command_drain_heartbeat`), and `GET /value/book` reads it through `src/api/settings_read.py`
(`drain_healthy`, `drain_last_seen`). Section B removes `GET /nav` and adds `truncated` to
`GET /spreads/orders`. The web sections delete sixteen legacy files, add `components/shell/DrainWarning.tsx`,
`components/value/ValueDrainNote.tsx`, `features/home/ValueWaiting.tsx`, `app/not-found.tsx`,
`app/error.tsx` and small route `layout.tsx` files for titles, and change existing components in place under
their tests. Nothing on the trading path, the Rules Engine, any gate, any sizing or the value book's own
logic changes. The API still writes exactly one table.

**Tech Stack:** Next.js 15 App Router, React 19, Tailwind CSS v4, @tanstack/react-query, lucide-react, Vitest
+ Testing Library; FastAPI, SQLAlchemy, Pydantic, pytest.

**Spec:** `docs/superpowers/plans/2026-11-05-web-overhaul-HANDOFF.md` (the ledger: section 3 is the item list,
section 4 the recommendations, section 5 the part list and rulings, section 6 the binding rules; this plan
corrects it where the code disagrees, rulings 1 to 9), `web/DESIGN.md` (ratified; the authority for every
visual value), `docs/superpowers/specs/2026-10-28-value-swing-book-design.md` revision 4 (capital release),
`docs/superpowers/plans/2026-10-29-value-book-6-web-telegram.md` Sections F to I and its rulings F5, G3, G6,
G11, H2 to H4, H9, I2, I4, I10.

## Execution model

| Section | Tasks | Model | Effort | Why this model |
|---|---|---|---|---|
| **A, Ship first: capital-release words and the value drain heartbeat** | 1-2 | **opus** | high | Touches `scripts/run_value.py` (the value process) and the value fence's import allowances; the read is money-shaped wording on a live surface. Every line is given and was prototyped against `main` at ca14c40. |
| **B, API tidy** | 3-4 | **sonnet** | high | A route removal and one response flag; given in full, prototyped. |
| **C, Delete the unmounted, after porting their tests** | 5-7 | **sonnet** | high | Test ports with mutation checks, then deletions; the protected files never change. |
| **D, The value book where it is missing** | 8-10 | **sonnet** | high | UI in `components/value`, `features/home`, `features/portfolio`, `features/activity`, `components/ledger`; da-vinci first. |
| **E, Honesty minors and the cross-links** | 11-13 | **sonnet** | high | Small UI fixes, each with a red test first; da-vinci first. |
| **F, Titles, not-found and error pages** | 14-15 | **sonnet** | high | Route metadata and two boundary files; da-vinci first. |
| **G, Finish** | 16-17 | **sonnet** (docs), **sonnet** fresh reviewer (da-vinci finish) | high | A doc sweep and a fresh-eyes visual review; then one **opus** whole-branch review (high) and one **sonnet** fix pass (high). |

**How a section runs (the orchestrator).** The main session is a Sonnet orchestrator at high effort. For each
section:

1. Run the section's **entry checks** yourself, in order. **Any check fails: stop**, report the output, do
   not start the section. A failure that belongs to the previous section is fixed there (reopen its last task,
   record the ruling) before re-running the checks.
2. All pass: add a "Section X entry" row to the Progress log (gate result, date) in the worktree.
3. Spawn **one** subagent for the section with `model` and `effort` from the table above (pass `effort` on
   every spawn). Its prompt names this plan, the section, `web/DESIGN.md` for UI sections, the files the
   section lists under "Reads", and says: "Invoke the `da-vinci` skill before any UI code" for Sections D, E,
   F and G's Task 17. Tell it to commit each task, fill its Progress log row in the same commit (status,
   commit, gate, date, every ruling with its cost-if-wrong), and to stop on any red gate it cannot attribute
   to its own change.
4. Verify the report yourself: `git log --oneline main..HEAD`, `git status --short`, the gate counts against
   the expected counts in the section exit, the protected-file diff (G1 below) and the command-site grep
   (G2 below).
5. **Stop and ask the operator before the next section.** After Section A, the question is the early merge
   (below).

After Section F: the Section G tasks, then one **opus** whole-branch review (superpowers:requesting-code-review,
effort high) as a subagent, the orchestrator confirms each finding in the code, then one **sonnet** fix pass
(high). Ask before merge or push.

**The early merge of Section A.** The value book is on in the operator's paper config
(`config/value.yaml` line 263, `enabled: true`) and the daemons run `main`, so the false capital-release
sentence is live now. When Section A exits green, ask the operator: "Merge Section A to main now and restart?"
On yes, from the **main checkout** (`/Users/ianlim/Desktop/IBKR Investments`, on `main`, clean):

```bash
git merge --ff-only feat/web-overhaul-4      # main must not have moved since A0; if it did, stop and ask
./ibkr restart                               # restarts the supervised stack (trading service first, then the API)
```

The branch keeps going on top; the final merge is another fast-forward. Record the merge commit and the
restart time in the "Early merge" row. Without a yes, Section A merges with the rest.

**How to apply a step (for the implementer).** Every code block is the exact text to write. A "replace the
lines" step names old text that occurs exactly once in the file today (line numbers are from `main` at
ca14c40): if it does not, stop and report rather than guess. Copy blocks byte for byte; extract them from a
pristine copy of this plan by line range rather than retyping. The formatter steps format.

**Commit counts.** Each task is one commit and fills its own Progress log row. A0 adds one commit on `main`
before the worktree exists. A review fix pass adds one commit; record it and add one to every later entry
check's count.

## Progress log

| Section / task | Status | Commits | Gate | Date | Rulings |
|---|---|---|---|---|---|
| **Plan written** | done | (plan file only) | Sections A and B prototyped on a code-only copy of `main` at ca14c40 (see Self-review): full pytest 5666 passed + 1 skipped, with 3 failures that need a git checkout (`test_private_config_files_are_gitignored`, `test_a_relative_ai_workdir_stays_gitignored`, `test_spreads_runtime_files_are_gitignored`: the copy is not a repo), so 5669 expected in the worktree (5665 + 5 - 1); ruff check clean; mypy src clean; `test_openapi_current` green after regeneration. Web sections not prototyped (ruling 31) | 2026-11-05 | Written from the HANDOFF section 7.1 brief, re-checked against the code; corrections are rulings 1-9; the HANDOFF's six operator questions take its defaults (ruling 10). |
| **A0 setup** | pending | | | | |
| **Section A entry** | pending | | | | |
| **Task 1: a capital-release close says why** | pending | | | | |
| **Task 2: the value drain heartbeat** | pending | | | | |
| **Section A exit / early merge** | pending | | | | |
| **Section B entry** | pending | | | | |
| **Task 3: `GET /nav` removed** | pending | | | | |
| **Task 4: `GET /spreads/orders` says when it is capped** | pending | | | | |
| **Section C entry** | pending | | | | |
| **Task 5: `DecideControls.test.tsx`, ported from `ApprovalCard.test.tsx`** | pending | | | | |
| **Task 6: the roll flow's tests on `RollCard`; `DrainWarning` moves to the shell** | pending | | | | |
| **Task 7: delete the sixteen unmounted files** | pending | | | | |
| **Section D entry** | pending | | | | |
| **Task 8: a value tap says when the value process is not checking** | pending | | | | |
| **Task 9: value taps in "Needs you" and the phone banner** | pending | | | | |
| **Task 10: the value book on Portfolio and At IBKR; the unavailable flag** | pending | | | | |
| **Section E entry** | pending | | | | |
| **Task 11: History never shows unknown as none** | pending | | | | |
| **Task 12: back to the Trades you left; the Spreads day in the URL** | pending | | | | |
| **Task 13: Pay's words, the month floor, the ledger's stock gain, capped spread fills, cross-links** | pending | | | | |
| **Section F entry** | pending | | | | |
| **Task 14: a title on every route** | pending | | | | |
| **Task 15: not-found and error pages** | pending | | | | |
| **Section G entry** | pending | | | | |
| **Task 16: docs** | pending | | | | |
| **Task 17: the da-vinci finish by a fresh reviewer, with the missing dark captures** | pending | | | | |
| **Whole-branch review (opus)** | pending | | | | |
| **Review fix pass (sonnet)** | pending | | | | |

*(Rows are filled as each task lands; a ruling is any deviation from the task text, and why, with its cost if wrong.)*

## Roadmap (this plan is Part 4 of 8, HANDOFF section 5)

- **Parts 1-3** and the value book's web sections F-I: done and merged.
- **Part 4, Cleanup, honesty and the value gaps.** This plan.
- **Part 5, The stock page** (L2, V6, V7 backend). **Part 6, Research, Universe and search** (L1, L3, S1, V7
  card). **Part 7, News, More and How it works** (L4, L5, L6, S4, S5). **Part 8, The value record** (F5, V9),
  gated on a month of paper record. **Order control** on its own track (spec first).

## Rulings made up front (the operator may overturn any of them)

**Corrections to the HANDOFF (read 2026-11-05 against `main` at ca14c40):**

1. **The value book is already on.** The HANDOFF (section 7.2, item 2) says not to enable it until Part 4
   merges; `config/value.yaml:263` already reads `enabled: true` and the daemons were restarted onto Part 6 at
   14:08. So V1 and the backend half of V2 are Section A, built first and offered for an early merge.
   *Cost if wrong: none; the order only moves earlier.*
2. **V1 needs no agreement work elsewhere.** The HANDOFF says `src/api/routers/options.py` and
   `src/notify/formatters.py` "already name" capital release. Neither renders `close_reason` at all
   (`grep -rn close_reason src/api src/notify/formatters.py` finds nothing); `src/reporting/day.py` is the one
   place a close reason becomes words. Task 1 adds the entry and a guard test that every `CloseReason` except
   `ROLL` has words. *Cost if wrong: none.*
3. **V1's words do not name the funding request.** The request id lives only in the closing order's `detail`
   (`position_manager.py:135`, "buy-to-close (capital_release) capital release request N for SYM"), which
   `PnlLeg` does not carry; reading it would add an `OrderRow` lookup to `day.py` for one sentence. The rule
   line says what happened and the price limit instead. *Cost if wrong: one lookup in `_lookups` and a name
   in the sentence.*
4. **The value heartbeat lives in the trading DB, not value.db.** The HANDOFF suggests `src/api/value_db.py`
   reads it. value.db has one writer package (`src/value/`; the fence scans `scripts/` too), the value process
   already writes the trading DB's `app_commands` from `scripts/run_value.py`, and the API already reads
   `system_settings` through `src/api/settings_read.py` for the trading drain. So the heartbeat mirrors
   `command_drain_heartbeat` exactly: key `value_drain_heartbeat` (`src/common/value_commands.py`, stdlib
   only), written by `run_value.py::_drain_commands` after its work on both paths, read by `GET /value/book`.
   `src/api/value_db.py` does not change. *Cost if wrong: none for behaviour; a later move is two files.*
5. **The value receipt never says "the trading service is not draining commands".** `CommandReceipt`
   (protected) prints that sentence for a stalled drain, which names the wrong process for a value tap. So
   `ValueDecide` and `AnalyseButton` keep passing a healthy drain to the receipt and add their own line,
   `ValueDrainNote`, which says when the value process last checked. The receipt's protected "accepted,
   waiting for the trading service" copy on a queued value tap stays (protected; recorded for the Part 7
   decide-controls decision, S4). *Cost if wrong: copy.*
6. **V4 is smaller than listed.** The ledger's trades and its `by_book` buckets are option trades only
   (`src/reporting/trade_ledger.py:836` builds `by_book` from trades; the value book trades shares), so a
   Value choice on the ledger's Trades filter would always be empty and the overview's "By book" heading never
   meets a value bucket. V4 is: `book: "value"` in the hand-written `LedgerTrade` type (type honesty), a Value
   chip on Activity's At IBKR list (value executions are tagged `book="value"` by ingest), and
   `bookWord("value")` reads "Value book". *Cost if wrong: one option in a select.*
7. **V8 keeps Part 6's backend rule.** `tests/test_reporting_value.py::test_a_missing_value_db_is_not_available_and_never_zero`
   pins `value_available: false` for an absent value.db on purpose. The web hides the flag only when
   `GET /value/book` positively says the book is off **and** has never written anything (`enabled: false`,
   `available: false`); a failed or loading book read keeps the flag. On this install (enabled) nothing
   changes. *Cost if wrong: a book switched off after it sold, whose value.db then became unreadable, hides
   the flag over sales it cannot count.*
8. **D1 is sixteen files, not fifteen.** `components/options/{ApprovalsList,ApprovalCard,ShortsTable,ShortsRow,
   ControlsStrip}`, `components/portfolio/{PortfolioShell,SummaryPanel,PositionsPanel,PositionGroup,StockLegRow,
   OptionLegRow,CampaignsPanel,CampaignThread,CalendarPanel}`, `components/pnl/PnlShell`,
   `components/ledger/LedgerNav` (import grep, 2026-11-05: no live page imports any of them; `ControlsStrip`'s
   `DrainWarning` export is live and moves first). Nine test files go with them: 100 tests
   (`ApprovalCard` 17, `ApprovalsList` 10, `ShortsTable` 22, `ControlsStrip` 3, `PortfolioShell` 4,
   portfolio `SummaryPanel` 8, `PositionGroup` 16, `CampaignThread` 12, `CalendarPanel` 8). *Cost: none.*
9. **The output file name** is the one the orchestrator gave (`...-cleanup-honesty-value-gaps.md`), not the
   HANDOFF brief's. *Cost: none.*

**The HANDOFF's open questions and rulings, adopted:**

10. **Q1-Q6 take their defaults** (HANDOFF 5.3): How it works is rebuilt small in Part 7; order control is
    specced in parallel and built after Part 6; no new Value destination; the value record waits for a month
    of paper; `/recommendations` is cut (the API route and the Telegram card stay); the `DESIGN.md` Open
    Decisions keep their defaults until the operator ratifies them before Part 7. None blocks this part.
11. **HANDOFF 5.1 rulings 1-11 hold** (numbering, no fold of `components/` into `features/`, `components/value/`
    stays, delete after porting, `GET /nav` removed and the other unused routes kept, no Value nav item or
    Trades tab, the calendar's second request, no new token).

**Section C (deletions):**

12. **Port what is the only coverage of live code; drop what dies with its file.** `ApprovalCard.test.tsx`'s
    14 decide-flow cases become `components/options/DecideControls.test.tsx` rendering `DecideControls`
    directly; its 3 card-display cases (the raised timestamp, the IV-rank flag, the review-summary preview)
    test `ApprovalCard`'s own markup and go with it. `ShortsTable.test.tsx`'s 15 roll-control, live-step and
    reload cases are ported onto `RollCard` (the live mount of `useRollProposal`), minus the 3 `RollCard`
    already has (confirm before request, one `roll_request` then the receipt, `no_qualifying_roll` in words),
    so 12 are appended; its 7 table-display cases go with the table. `ControlsStrip.test.tsx`'s drain case
    becomes `components/shell/DrainWarning.test.tsx` (2 tests). *Cost if wrong: a display test lost for code
    that no longer exists; none.*
13. **Every ported test is mutation-checked** in a scratch copy (never in the worktree, never on a protected
    file in place): break the behaviour it pins, see it fail, restore. The protected `DecideControls.tsx`
    docstring still says "each tested in ApprovalCard.test.tsx"; it stays (protected), and `web/CLAUDE.md`
    names the new file. *Cost: a stale comment.*
14. **`DrainWarning` moves to `components/shell/DrainWarning.tsx` unchanged** (text, test id, classes), and its
    two importers (`BotSheet.tsx:4`, `TradesPage.tsx:4`) change their import line only. *Cost: none.*

**Section D (value gaps):**

15. **Value taps in "Needs you": a row that jumps, not a second Review.** The same proposal on one screen with
    two lime Reviews breaks "The Lime Means Act Rule", and two mounted `ValueDecide`s would poll one command
    twice. So under All and Value, "Needs you" lists each tap-waiting value proposal as a compact row (eyebrow
    "Value book", the proposal title, cost, time left) with a secondary pill, **Review in the Value book**, that
    jumps to the Value card (`#value-title`); the Value card keeps the one decide flow and its one lime Review.
    The heading counts both ("Needs you · 1 proposal · 1 value"). On a phone the banner names value proposals
    too; its lime **Open** goes to Trades only when a wheel proposal waits, and a value-only banner carries a
    secondary **Show** that jumps to the Value card. da-vinci may refine the row's layout, not the rule.
    *Cost if wrong: one extra tap (jump, then Review) per value decision.*
16. **The value drain note's words.** Healthy or unknown (book not read yet): nothing. Stale with a time:
    StatusWord "Not checking" (flag tone) and "The value process last checked for taps <Day, Mon D · h:mm PM ET>.
    This tap waits until it checks again." Never run: "The value process has not checked for taps yet. This tap
    waits until it runs." Shown only while the command is pending. Healthy is within
    `max(2 x value.telegram.commands_poll_seconds, 300 s)`: the night (48 s on 2026-11-04, `logs/value.log`)
    and the RTH cycle hold the drain; a Claude read drains between items. *Cost if wrong: a busy process reads
    "Not checking" for a minute; the time is shown so the operator can judge.*
17. **Value rows link to the stock page's value block** (`stockValueHref`, `/stock/SYM#value-block-SYM`), on Home
    and Portfolio both; Home's test that pins `href: null` changes. Portfolio gains a **Value** chip (between
    Credit spreads and Shares, Home's order) and a "Value book" card under All and Value; no Value tab on
    Campaigns or Calendar. The broker rows are already the wheel's view (`wheel_view`, `src/ibkr/portfolio.py`),
    so value shares are never counted twice. *Cost: none.*

**Section E (honesty minors):** every item below is a deferred minor from Part 2 or Part 3, fixed with a red
test first:

18. **History, In flight**: a failed orders or approvals read shows the section with "In-flight orders could
    not be loaded right now.", never nothing. **Not traded**: a failed read shows "Proposals that did not trade
    could not be loaded right now."; a read that hit the 200 limit adds "Only the newest 200 proposals over
    these days could be read, so an older one may be missing." *Cost: none.*
19. **Back to Trades keeps where you were.** Links from Trades views into `/trades/<id>` carry the Trades
    `view`, `day` and `strategy` parameters; `BackToTrades` returns to `/trades` with those three (and only
    those three, each validated). A detail page opened from Home or a bare URL goes to `/trades` as today.
    *Cost if wrong: a longer detail URL.*
20. **The Spreads view keeps its day in `?day=`** through `useTradesDay`, the hook History uses; the same
    parameter, so switching between History and Spreads keeps the day. `positionHref` keeps `paper` (only a
    paper spread has a position page; not a defect). *Cost: none.*
21. **Pay's by-strategy table says words** ("Cash-secured puts", "Covered calls"; any other label passes
    through), through an optional `labelOf` on `BreakdownTable`; the by-symbol table is unchanged. The one
    existing test that pins the raw label is updated (an existing test changes; recorded). **`?month=` before
    the system began** opens the first month. **A ledger trade's stock gain** reads a hatched `n/a` only for a
    "Called away" trade whose gain is unknown; for every other trade the cell stays blank because nothing is
    there to know (not "unknown"). **Capped spread fills** say "Only the newest 200 are listed." when
    `truncated`. *Cost: copy.*
22. **Cross-links (F3)**: History ends with "IBKR's own record of each fill is under Activity, Fills and orders."
    linking `/activity?view=fills`; Fills and orders ends with "Each day's trades, with their reasons, are under
    Trades, History." linking `/trades?view=history`. One sentence each, secondary text links. *Cost: none.*

**Section F (titles and boundaries):**

23. **Titles**: the root layout's metadata becomes `{ default: "IBKR Income", template: "%s · IBKR Income" }`;
    each server page exports `metadata.title`; a client page gets a sibling `layout.tsx` (a server component that
    renders `children` and exports `metadata`, or `generateMetadata` for a dynamic segment), because a client
    component cannot export metadata. Titles: Home keeps the default; Trades; "Proposal 42"; Portfolio;
    Activity; "AAPL position"; Research; Universe; "AAPL" (stock); News; "AAPL news"; How it works; More;
    What Claude knows; Ledger trades; "AAPL ledger"; Import a statement; Not found. *Cost: none.*
24. **Boundaries**: one root `app/not-found.tsx` and one root `app/error.tsx` (client, `reset()` behind a
    secondary "Try again"). **No `loading.tsx`**: every page already renders its own `role="status"` skeleton,
    and a root loading boundary would flash a second skeleton on each navigation. No `global-error.tsx` (the
    root layout renders no data). *Cost if wrong: one file each.*

**Section G (finish):**

25. **The finish review is a fresh agent** (the step F-I skipped, HANDOFF V10): the orchestrator spawns it
    with no prior context; it reviews Part 4's surfaces and the F-I surfaces and takes the missing captures
    (F 1440 dark, G 390 dark, H and I every state in dark), at 320, 390 and 1440 px in light and dark, against a
    synthetic API in the scratchpad. Never the live API.

**Standing rules:**

26. **Protected files are byte-identical to `main`**: `web/components/options/{DecideControls,ConfirmAction,
    CommandReceipt,HaltControl,AutonomyControl,RollModeControl}.tsx`, `web/lib/commands.ts`,
    `web/lib/receipt.ts`. Deleting an unmounted sibling is allowed; editing these is not.
27. **The command-site grep** `grep -rln "submitCommand\|confirmCommand" web/features` prints exactly
    `features/more/TargetCard.tsx`, `features/more/TargetCard.test.tsx`, `features/stock-value/AnalyseButton.tsx`,
    `features/stock-value/AnalyseButton.test.tsx`. This part adds no command site (V3's row is a link).
28. **Deferred minors left deferred** (cosmetic, or cost more than they return; HANDOFF 4 row M): Part 2's smart
    default on an empty Proposals, `activity_days` loading every snapshot, Spreads "Next onto today" (Task 12
    checks it and records whether it still happens); Part 3's `/ledger/executions` days+1 window, a name card's
    visible-leg P&L, `source: none` with spreads, class-name pins, `SpreadFills`' raw `mode`. The ledger
    overview's `by_book` labels stay the API's lowercase keys (option trades only; ruling 6).
29. **Docs move with their change**: Sections A and B update `docs/web/api.md`, `ARCHITECTURE.md`,
    `docs/web/architecture.md` and `STATUS.md` for what they change (A may merge early, so `main` must stay
    true); Task 16 does the rest (D6) and the web docs.
30. **Never build inside `web/`**: the operator's `next dev` shares `web/.next`. Builds run in a scratch copy
    (G4 below).
31. **The web code here is a reference, not a transcript.** Sections A and B were prototyped and are exact.
    The web sections give the tests (the contract), the anchors and reference code; the implementer writes the
    test red first, then the code, and records any deviation. *Cost: the implementer's judgement inside the
    tests' bounds.*

## Global Constraints

- Core invariant, the fences and the two written exceptions in root `CLAUDE.md` are untouched. Nothing here
  places, sizes, prices or gates anything; Claude's words stay labelled and never sit on a button.
- The API writes exactly one table (`app_commands`); `src/api/` imports from `src.value` only `scorecard` and
  `schemas`; only `src/api/value_db.py` opens value.db; `src/reporting/` imports nothing from `src.claude` or
  `src.value`. `tests/test_web_fence.py`, `test_eval_skills.py`, `test_regime_fence.py`, `test_news_fence.py`,
  `test_spreads_fence.py`, `test_value_fence.py`, `test_wheel_spreads_isolation.py` stay green and unweakened.
- `scripts/run_value.py` imports `src.storage.system_settings` and `src.common.value_commands` only inside
  function bodies (both already on `test_value_fence.py`'s allowed list); it is never imported, only
  `py_compile`d.
- UI: tokens only (no raw palette class, no hex); Hanken Grotesk, Red Hat Mono for figures, `.tabular` on
  numbers; lime only on the primary act, the count badge, the pay meter and "Expires today"; unknown is a
  hatched `n/a`, never `$0` or blank; no state by colour alone; no shadow except the sheet and the confirm
  dialog; charts never animate in; 44 px phone targets; zero em dashes and none of "seamless", "robust",
  "unlock", "elevate" in UI copy. No new token, colour, font, radius or elevation (a proposal waits for the
  operator).
- Gates (from the worktree root, never the main checkout: four ledger, openapi and web-fence tests fail
  spuriously from elsewhere): web tasks `cd web && npx vitest run && npx tsc --noEmit && npm run lint`;
  Python tasks `python -m pytest -q && ruff check . && mypy src` after `ruff format` on the files the task
  touched. `tests/test_scan_timeout.py` is a known flake: if it is the only failure, re-run it alone; green
  means "scan timeout flake" in the log.
- After any API contract change regenerate offline:
  `IBKR_CONFIG_USE_EXAMPLES=1 python -c "import json; from src.api.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json`
  then `cd web && npx openapi-typescript ../docs/web/openapi.json -o lib/api-types.ts`; `tests/test_openapi_current.py` stays green.

**Shared checks (referenced by every section exit):**

- **G1, protected files:** `git diff --stat main -- web/components/options/DecideControls.tsx web/components/options/ConfirmAction.tsx web/components/options/CommandReceipt.tsx web/components/options/HaltControl.tsx web/components/options/AutonomyControl.tsx web/components/options/RollModeControl.tsx web/lib/commands.ts web/lib/receipt.ts` prints nothing.
- **G2, command sites:** `grep -rln "submitCommand\|confirmCommand" web/features | sort` prints the four files of ruling 27.
- **G3, design spec:** `python3 ~/.claude/skills/da-vinci/scripts/design_md_check.py web/DESIGN.md` exits 0.
- **G4, scratch build:** `S="$(mktemp -d)/web" && rsync -a --exclude node_modules --exclude .next web/ "$S/" && ln -s "$PWD/web/node_modules" "$S/node_modules" && (cd "$S" && npm run build); rm "$S/node_modules"; rm -rf "$(dirname "$S")"` (remove the symlink before the directory).

## Review Focus

1. **A capital-release close never reads "the reason was not recorded"**, and no future `CloseReason` can
   silently fall into that sentence → Task 1's parametrised case and guard test.
2. **A dead value process is said in words, and a live one is not accused**: never-run is not healthy; within
   the window is healthy; older shows the last time; the receipt never names the trading service for a value
   tap → Task 2 API tests, Task 2 structural test, Task 8 `ValueDrainNote` tests.
3. **The ports keep every live behaviour pinned**: each ported case fails against a scratch mutation of the
   behaviour it names → Tasks 5 and 6 Progress log rows list the mutations.
4. **Unknown is never none**: History, Not traded, the value flag, capped spread fills → Tasks 10, 11, 13.
5. **One decide flow per value proposal**: "Needs you" links to the Value card; it never mounts a second
   `ValueDecide` → Task 9 test "never renders an Approve or a Review button for a value proposal".
6. **Nothing reaches the trading path**: G1, G2 and the fence suites at every exit.

---

## File structure

```
docs/superpowers/plans/2026-11-05-web-overhaul-HANDOFF.md, this plan   COMMIT (A0, on main)
src/
  reporting/day.py                        MODIFY  _CLOSE_RULE: CAPITAL_RELEASE                  (Task 1)
  common/value_commands.py                MODIFY  VALUE_DRAIN_HEARTBEAT_KEY                      (Task 2)
  api/models/value.py, routers/value.py   MODIFY  drain_healthy, drain_last_seen on /value/book  (Task 2)
  api/routers/meta.py                     MODIFY  GET /nav removed                               (Task 3)
  api/models/spreads.py, routers/spreads.py  MODIFY  truncated on /spreads/orders                (Task 4)
scripts/run_value.py                      MODIFY  _beat() after every drain                      (Task 2)
tests/test_reporting_day.py               MODIFY  +2 (1 case, 1 guard)                           (Task 1)
tests/test_api_value.py                   MODIFY  +2                                             (Task 2)
tests/test_value_commands.py              MODIFY  +1 structural                                  (Task 2)
tests/test_api_meta.py                    MODIFY  -1 nav, +1 nav gone                            (Task 3)
tests/test_api_ledger.py                  MODIFY  -1 nav                                         (Task 3)
tests/test_api_spread_orders.py           MODIFY  extended assertions                            (Task 4)
docs/web/openapi.json, web/lib/api-types.ts  MODIFY  regenerated                                 (Tasks 2-4)
docs/web/api.md, docs/web/architecture.md, ARCHITECTURE.md, STATUS.md   MODIFY  (Tasks 2-4, 16)
web/
  components/options/DecideControls.test.tsx   CREATE (Task 5)
  features/position/RollCard.test.tsx          MODIFY +12 (Task 6)
  components/shell/DrainWarning.tsx (+ test)   CREATE (Task 6); BotSheet.tsx, features/trades/TradesPage.tsx import line
  components/options/{ApprovalsList,ApprovalCard,ShortsTable,ShortsRow,ControlsStrip}.tsx (+ 4 tests)   DELETE (Task 7)
  components/portfolio/{PortfolioShell,SummaryPanel,PositionsPanel,PositionGroup,StockLegRow,OptionLegRow,
    CampaignsPanel,CampaignThread,CalendarPanel}.tsx (+ 5 tests)   DELETE (Task 7)
  components/pnl/PnlShell.tsx, components/ledger/LedgerNav.tsx    DELETE (Task 7)
  components/value/ValueDrainNote.tsx (+ test) CREATE; ValueDecide.tsx, features/stock-value/AnalyseButton.tsx MODIFY (Task 8)
  components/value/useValueBook.ts             MODIFY waitingProposals, useValueOut (Tasks 9, 10)
  features/home/ValueWaiting.tsx (+ test)      CREATE; NeedsYou.tsx, ProposalsBanner.tsx MODIFY (Task 9)
  features/home/positions.ts (+ test)          MODIFY value row href (Task 10)
  features/portfolio/positions.ts, PositionsView.tsx (+ tests)   MODIFY Value chip and card (Task 10)
  features/activity/ExecutionsList.tsx, fills.ts; components/ledger/types.ts   MODIFY (Task 10)
  features/home/PayCard.tsx, TodayTrades.tsx, RealisedCalendar.tsx, features/activity/PayMonth.tsx   MODIFY flag (Task 10)
  features/trades/HistoryView.tsx (+ test)     MODIFY (Tasks 11, 13)
  features/trades/useTradesView.ts, SpreadsView.tsx, components/options/ApprovalDetail.tsx,
    features/home/ProposalCard.tsx, features/trades/ProposalsView.tsx   MODIFY (Task 12)
  components/pnl/BreakdownTable.tsx, SummaryPanel.tsx; features/activity/PayView.tsx or useMonthParam.ts;
    components/ledger/TradesTable.tsx; features/activity/SpreadFills.tsx, FillsView.tsx   MODIFY (Task 13)
  app/layout.tsx; server pages; app/**/layout.tsx for client pages; app/titles.test.ts   (Task 14)
  app/not-found.tsx, app/error.tsx (+ tests)   CREATE (Task 15)
  DESIGN.md, CLAUDE.md                         MODIFY (Tasks 9, 10, 15, 16)
```

---

## Section A: Ship first (Tasks 1-2) · model: opus (effort high)

**Reads:** this section; `src/reporting/day.py` (lines 260-300, 380-410); `src/common/schemas.py` (lines
1014-1028); `scripts/run_value.py`; `src/api/routers/value.py` (lines 1-50, 115-206); `src/api/models/value.py`
(lines 100-115); `src/api/settings_read.py`; `tests/test_reporting_day.py` (lines 1-175);
`tests/test_api_value.py` (lines 1-50, 160-280, 410-430); `tests/test_value_commands.py` (lines 320-360);
`tests/test_value_fence.py` (lines 276-345).

**A0. Setup (orchestrator, before the entry checks).**

- [ ] On `main` in the main checkout, `git status --short` shows only the two untracked docs. Commit them:
  `git add docs/superpowers/plans/2026-11-05-web-overhaul-HANDOFF.md docs/superpowers/plans/2026-11-05-web-overhaul-4-cleanup-honesty-value-gaps.md && git commit -m "docs(plan): web overhaul Part 4 plan and the handoff ledger"` (with the session's attribution lines). The main checkout is then clean, which the early merge needs.
- [ ] `df -h .` shows at least 10 GiB free (20 GiB at 96% on 2026-11-05). Below that, stop and ask.
- [ ] Create the worktree: `git worktree add .claude/worktrees/web-overhaul-4 -b feat/web-overhaul-4 main`; in it,
  `ln -s "$PWD/../../../.venv" .venv` (or the absolute path of the main checkout's `.venv`),
  `ln -s "<main checkout>/web/node_modules" web/node_modules`, then
  `IBKR_CONFIG_USE_EXAMPLES=1 .venv/bin/python -c "from src.storage.db import init_db; init_db()"`.
  Every later command runs from the worktree root. Worktree sessions cannot edit private `config/*.yaml`
  (none is needed here). Never `cd` into `web/` to run `next build` or `next dev`.
- [ ] Record A0 in the Progress log (commit hash, worktree path) in the first task's commit.

**Entry checks:**

- [ ] **A1. Starting point.** In the worktree, `git log --oneline -2` shows the A0 commit over ca14c40;
  `git status --short` is empty apart from the `.venv` and `web/node_modules` symlinks (git-ignored). Each
  prints a line:

  ```bash
  grep -n 'CAPITAL_RELEASE = "capital_release"' src/common/schemas.py
  grep -n '"the account next reconciled.",' src/reporting/day.py
  grep -n "def _drain_commands" scripts/run_value.py
  grep -n "def value_book(user: OwnerUser) -> ValueBookResponse:" src/api/routers/value.py
  grep -n '"src.storage.system_settings",' tests/test_value_fence.py
  ```

- [ ] **A2. Nothing already named what Section A adds.** This prints nothing:
  `grep -rn "VALUE_DRAIN_HEARTBEAT_KEY\|value_drain_heartbeat\|_value_drain\b" src scripts tests web/lib`
- [ ] **A3. Baseline green.** `python -m pytest -q && ruff check . && mypy src`;
  `cd web && npx vitest run && npx tsc --noEmit && npm run lint && cd ..`. Expected on 2026-11-05: pytest 5665
  passed + 1 skipped, mypy 360 files, vitest 1485 in 152 files. Record the counts; later gates compare with them.

**Section exit:** two commits after A0; pytest = baseline + 5; `test_openapi_current` green; G1, G2 hold
(no web code changed beyond the regenerated `api-types.ts`); `python -m py_compile scripts/run_value.py` silent.
Then the early-merge question (Execution model).

---

### Task 1: A capital-release close says why

**Files:** Modify `src/reporting/day.py`, `tests/test_reporting_day.py`, `ARCHITECTURE.md`, this plan.

- [ ] **Step 1: Write the failing tests.** In `tests/test_reporting_day.py`, replace line 158

```python
        ("manual", "Closed outside the system", "reconciled"),
```

with

```python
        ("manual", "Closed outside the system", "reconciled"),
        ("capital_release", "Closed to fund a value-book buy", "breakeven or better"),
```

and insert directly above line 176 (`def test_a_closed_card_shows_the_whole_trade_so_its_stub_can_sum(db) -> None:`):

```python
def test_every_close_reason_but_a_roll_has_words_of_its_own() -> None:
    """A roll is its own card; every other stamped reason must say why in words. A reason added to
    CloseReason without words here would read "the reason was not recorded", which is false."""
    from src.reporting.day import _CLOSE_RULE

    assert set(CloseReason) - set(_CLOSE_RULE) == {CloseReason.ROLL}


```

- [ ] **Step 2: Run them red.** `python -m pytest -q tests/test_reporting_day.py` → 2 failed (the
  `capital_release` case reads "the reason was not recorded"; the guard finds `CAPITAL_RELEASE` missing).
- [ ] **Step 3: Add the words.** In `src/reporting/day.py`, replace lines 285-287

```python
        "the account next reconciled.",
    ),
}
```

with

```python
        "the account next reconciled.",
    ),
    CloseReason.CAPITAL_RELEASE: (
        "Closed to fund a value-book buy.",
        "An approved value-book buy needed more cash than the account had free, so the system "
        "bought this put back to release the cash it secured. A release closes only at breakeven "
        "or better: the buy-back may not cost more than the premium taken in, less the required "
        "profit.",
    ),
}
```

  (The sentence matches `src/execution/capital_release.py`: the fewest wheel CSPs at breakeven or better,
  `max_price = entry_credit x (1 - release.min_profit_pct / 100)`; "approved" covers a tap and an
  autonomy-approved buy, ruling 7 of value Part 5.)
- [ ] **Step 4: Green.** `python -m pytest -q tests/test_reporting_day.py` → 36 passed.
- [ ] **Step 5: Docs.** In `ARCHITECTURE.md` line 1137 (the `day.py` row), after "closed (the `CloseReason`
  stamped on the buy-back fill," insert "including a capital release (web overhaul Part 4: "Closed to fund a
  value-book buy."; every reason except a roll has words, test-pinned),".
- [ ] **Step 6: Gate and commit.** `ruff format src/reporting/day.py tests/test_reporting_day.py`;
  `python -m pytest -q && ruff check . && mypy src` (pytest baseline + 2). Fill this task's and A0's rows; commit
  `fix(reporting): a capital-release close says why, not "the reason was not recorded"`.

### Task 2: The value drain heartbeat

**Files:** Modify `src/common/value_commands.py`, `scripts/run_value.py`, `src/api/models/value.py`,
`src/api/routers/value.py`, `tests/test_api_value.py`, `tests/test_value_commands.py`,
`docs/web/openapi.json`, `web/lib/api-types.ts`, `docs/web/api.md`, `docs/web/architecture.md`,
`ARCHITECTURE.md`, `STATUS.md`, this plan.

- [ ] **Step 1: Write the failing tests.** In `tests/test_api_value.py`, insert directly above
  `def test_every_value_route_needs_the_owner_token(client, vdb_file) -> None:` (line 427):

```python
def test_book_says_whether_the_value_drain_is_checking(client, vdb_file, monkeypatch) -> None:
    """Web overhaul Part 4 (V2): the value process's drain heartbeat. Never run is false with a null
    time; within five minutes (the floor over twice the 15 s poll) is healthy; older is stale, and
    its time is still shown so the receipt can say when the process last checked."""
    import src.api.routers.value as router
    from src.common.value_commands import VALUE_DRAIN_HEARTBEAT_KEY
    from src.storage.system_settings import set_setting

    now = NOW.replace(tzinfo=UTC)
    monkeypatch.setattr(router, "_now", lambda: now)
    body = client.get("/value/book", headers=OWNER).json()
    assert body["drain_healthy"] is False and body["drain_last_seen"] is None
    set_setting(VALUE_DRAIN_HEARTBEAT_KEY, (now - timedelta(seconds=290)).isoformat())
    body = client.get("/value/book", headers=OWNER).json()
    assert body["drain_healthy"] is True
    set_setting(VALUE_DRAIN_HEARTBEAT_KEY, (now - timedelta(seconds=310)).isoformat())
    body = client.get("/value/book", headers=OWNER).json()
    assert body["drain_healthy"] is False
    assert body["drain_last_seen"].startswith("2026-11-02T14:54:50")


def test_a_missing_value_db_still_says_whether_the_drain_runs(
    client, no_vdb_file, monkeypatch
) -> None:
    """The heartbeat lives in the trading DB: a book with no value.db yet still reports it."""
    import src.api.routers.value as router
    from src.common.value_commands import VALUE_DRAIN_HEARTBEAT_KEY
    from src.storage.system_settings import set_setting

    now = NOW.replace(tzinfo=UTC)
    monkeypatch.setattr(router, "_now", lambda: now)
    set_setting(VALUE_DRAIN_HEARTBEAT_KEY, now.isoformat())
    body = client.get("/value/book", headers=OWNER).json()
    assert body["available"] is False and body["drain_healthy"] is True


```

  (`client` from `tests/conftest.py` binds the storage engine to the trading DB the API reads, so
  `set_setting` seeds the row the route sees. The examples' `value.telegram.commands_poll_seconds` is 15, so
  the window is `max(30, 300)` = 300 s: 290 s is healthy, 310 s is not; 15:00 less 310 s is 14:54:50.)

  Append to the end of `tests/test_value_commands.py`:

```python


def test_the_value_drain_beats_after_its_work_on_both_paths() -> None:
    """Web overhaul Part 4 (V2): `_drain_commands` writes the heartbeat on the empty path and after
    `vcmd.drain` on the busy one, never before the work, and `_beat` writes the key GET /value/book
    reads. Structural: the entrypoint is never imported by a test, so its source is read."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("scripts/run_value.py").read_text())
    fns = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}

    def calls(node: ast.AST, name: str) -> list[int]:
        return [
            n.lineno
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and (getattr(n.func, "id", None) == name or getattr(n.func, "attr", None) == name)
        ]

    drain = fns["_drain_commands"]
    beats, [work] = calls(drain, "_beat"), calls(drain, "drain")
    assert len(beats) == 2 and max(beats) > work  # the busy path beats after vcmd.drain
    [empty] = [
        n for n in ast.walk(drain) if isinstance(n, ast.If) and ast.unparse(n.test) == "not rows"
    ]
    assert calls(empty, "_beat") and any(isinstance(b, ast.Return) for b in empty.body)
    assert "set_setting(VALUE_DRAIN_HEARTBEAT_KEY" in ast.unparse(fns["_beat"])
    assert vc.VALUE_DRAIN_HEARTBEAT_KEY == "value_drain_heartbeat"
```

- [ ] **Step 2: Run them red.** `python -m pytest -q tests/test_api_value.py tests/test_value_commands.py`
  → 3 failed (`KeyError: 'drain_healthy'` twice; `KeyError: '_beat'`).
- [ ] **Step 3: The shared key.** In `src/common/value_commands.py`, replace line 25

```python
VALUE_ORDER_KINDS: frozenset[str] = frozenset({"value_approve", "value_reject", "value_trim"})
```

with

```python
VALUE_ORDER_KINDS: frozenset[str] = frozenset({"value_approve", "value_reject", "value_trim"})
# The value process's drain heartbeat (web overhaul Part 4): a system_settings key in the trading
# DB, written by scripts/run_value.py after every drain of the kinds above (after the work, never
# before, as command_drain does) and read by GET /value/book, so a web tap's receipt can say the
# value process is not checking for taps rather than wait in silence.
VALUE_DRAIN_HEARTBEAT_KEY = "value_drain_heartbeat"
```

- [ ] **Step 4: The writer.** In `scripts/run_value.py`, insert directly above line 230
  (`def _drain_commands() -> int:`):

```python
def _beat() -> None:
    """The value drain's heartbeat (web overhaul Part 4): ``value_drain_heartbeat`` in the trading
    DB's system_settings, which GET /value/book reads so a web tap's receipt can say the value
    process is not checking for taps. Called after the drain's work, never before (command_drain's
    rule): a drain that raises leaves the old time, so a failing drain reads as stale."""
    from src.common.value_commands import VALUE_DRAIN_HEARTBEAT_KEY
    from src.storage.system_settings import set_setting

    set_setting(VALUE_DRAIN_HEARTBEAT_KEY, datetime.now(UTC).isoformat())


```

  Replace lines 251-252

```python
    if not rows:
        return 0
```

  with

```python
    if not rows:
        _beat()
        return 0
```

  and replace line 277 (`    outcomes = vcmd.drain(rows, _apply, _mark)`) with

```python
    outcomes = vcmd.drain(rows, _apply, _mark)
    _beat()
```

  (`set_setting` logs and swallows its own failure, so a heartbeat write never stops a drain. One small
  `system_settings` write every `commands_poll_seconds`, as the trading drain already does every poll.)
- [ ] **Step 5: The response fields.** In `src/api/models/value.py`, replace line 113

```python
    release_max_closes: int  # release.max_closes_per_request: the K in the approval sentence
```

with

```python
    release_max_closes: int  # release.max_closes_per_request: the K in the approval sentence
    # The value process's command drain (web overhaul Part 4): when it last checked for value_*
    # commands (system_settings ``value_drain_heartbeat``), and whether that is recent enough for a
    # pending tap to read as queued. Never-run is false with a null time, never true.
    drain_healthy: bool = False
    drain_last_seen: datetime | None = None
```

- [ ] **Step 6: The reader.** In `src/api/routers/value.py`:
  - replace line 10 (`from datetime import UTC, datetime`) with

```python
import logging
from datetime import UTC, datetime, timedelta
```

  - replace line 16 (`from src.api.deps import OwnerUser`) with `from src.api.deps import OwnerUser, TradingDb`;
  - replace lines 41-42

```python
from src.common.config import get_config
from src.common.value_commands import trim_offer_stale
```

    with

```python
from src.api.settings_read import parse_setting_dt, read_setting
from src.common.config import get_config
from src.common.value_commands import VALUE_DRAIN_HEARTBEAT_KEY, trim_offer_stale
```

  - replace line 45 (`router = APIRouter(prefix="/value", tags=["value"])`) with

```python
log = logging.getLogger(__name__)
router = APIRouter(prefix="/value", tags=["value"])
```

  - replace lines 140-149

```python
@router.get("/book", response_model=ValueBookResponse)
def value_book(user: OwnerUser) -> ValueBookResponse:  # noqa: ARG001
    now = _now()
    cfg = get_config().value
    enabled, release_max = cfg.book.enabled, cfg.book.release.max_closes_per_request
    with vdb.value_read_session() as s:
        if s is None:
            return ValueBookResponse(
                as_of=now, available=False, enabled=enabled, release_max_closes=release_max
            )
```

    with

```python
# The value drain's slow steps (the night, the RTH cycle) hold the drain for a minute or two; a
# Claude read drains between items. Five minutes covers them without hiding a dead process long.
VALUE_DRAIN_FLOOR_SECONDS = 300


def _value_drain(db: TradingDb, now: datetime) -> tuple[bool, datetime | None]:
    """Whether the value process checked for value_* commands recently, and when it last did.
    Healthy is within twice ``value.telegram.commands_poll_seconds`` or five minutes, whichever is
    longer. A drain that never ran, or a heartbeat that cannot be read, is not healthy."""
    try:
        seen = parse_setting_dt(read_setting(db, VALUE_DRAIN_HEARTBEAT_KEY))
    except Exception as exc:  # noqa: BLE001 - the book's figures do not depend on the heartbeat
        log.debug("value book: the drain heartbeat could not be read: %s", exc)
        return False, None
    if seen is None:
        return False, None
    poll = get_config().value.telegram.commands_poll_seconds
    window = timedelta(seconds=max(2 * poll, VALUE_DRAIN_FLOOR_SECONDS))
    return now - seen <= window, seen


@router.get("/book", response_model=ValueBookResponse)
def value_book(user: OwnerUser, db: TradingDb) -> ValueBookResponse:  # noqa: ARG001
    now = _now()
    cfg = get_config().value
    enabled, release_max = cfg.book.enabled, cfg.book.release.max_closes_per_request
    drain_healthy, drain_last_seen = _value_drain(db, now)
    with vdb.value_read_session() as s:
        if s is None:
            return ValueBookResponse(
                as_of=now,
                available=False,
                enabled=enabled,
                release_max_closes=release_max,
                drain_healthy=drain_healthy,
                drain_last_seen=drain_last_seen,
            )
```

  - in the final `return ValueBookResponse(` of `value_book`, replace

```python
        release_max_closes=release_max,
        ceiling_usd=ceiling,
```

    with

```python
        release_max_closes=release_max,
        drain_healthy=drain_healthy,
        drain_last_seen=drain_last_seen,
        ceiling_usd=ceiling,
```

- [ ] **Step 7: Green.** `python -m pytest -q tests/test_api_value.py tests/test_value_commands.py tests/test_value_fence.py tests/test_value_final_review.py tests/test_web_fence.py`
  → all pass; `python -m py_compile scripts/run_value.py` silent.
- [ ] **Step 8: Regenerate the contract** (Global Constraints). The `api-types.ts` diff is exactly the two
  fields on `ValueBookResponse` (`drain_healthy: boolean` with `@default false`, `drain_last_seen?: string | null`).
  `python -m pytest -q tests/test_openapi_current.py` passes.
- [ ] **Step 9: Docs.**
  - `docs/web/api.md`, `### GET /value/book`: after "`release_max_closes` is ... cash-secured puts")." append:
    "`drain_healthy` / `drain_last_seen` (web overhaul Part 4): the value process's command drain, from
    `system_settings.value_drain_heartbeat` (written by `scripts/run_value.py` after every drain). Healthy is a
    heartbeat within `max(2 x value.telegram.commands_poll_seconds, 300 s)`; never-run is `false` with `null`.
    Present on the `available: false` answer too (the heartbeat is in the trading DB)."
  - `docs/web/architecture.md`, under the drain block (after line 53): a paragraph: "The value process
    (`scripts/run_value.py`) drains the six `value_*` kinds itself (`command_drain` skips them,
    `src/common/value_commands.VALUE_KINDS`) every `value.telegram.commands_poll_seconds` and between its slow
    steps, and writes `value_drain_heartbeat` to `system_settings` after each drain, after the work. `GET
    /value/book` reads it (`drain_healthy`, `drain_last_seen`), so a value tap's receipt can say the value
    process is not checking (web overhaul Part 4)."
  - `ARCHITECTURE.md` line 968 (`routers/value.py` row): append "Web overhaul Part 4: `GET /value/book` carries
    `drain_healthy` and `drain_last_seen`, read from `system_settings.value_drain_heartbeat` through
    `src/api/settings_read.py` (no value.db read; healthy within `max(2 x commands_poll_seconds, 300 s)`)." Line
    1733 (`run_value.py` row): append "It writes `value_drain_heartbeat` to the trading DB's `system_settings`
    after every drain of its command kinds (web overhaul Part 4)."
  - `STATUS.md` line 407: replace "The Home card's `drainHealthy` is always true: no API field says whether the
    value process is running." with "The value process's drain heartbeat is served since web overhaul Part 4
    Section A (`GET /value/book` `drain_healthy`); the web says it from Part 4 Section D." Add one bullet at the
    end of the same "Deferred (web, Sections F-I)" list: "A capital-release close read "the reason was not
    recorded" on Done today, History and the position page until web overhaul Part 4 Section A (fixed)."
- [ ] **Step 10: Gate and commit.** `ruff format` the six Python files; `python -m pytest -q && ruff check . && mypy src`
  (pytest = Task 1's + 3); `cd web && npx vitest run && npx tsc --noEmit && npm run lint` (unchanged counts).
  Fill the row; commit `feat(value): the value drain's heartbeat, served on GET /value/book`.

---

## Section B: API tidy (Tasks 3-4) · model: sonnet (effort high)

**Reads:** this section; `src/api/routers/meta.py`; `tests/test_api_meta.py`; `tests/test_api_ledger.py` (lines
85-100); `src/api/routers/spreads.py` (lines 165-210); `src/api/models/spreads.py` (lines 95-125);
`tests/test_api_spread_orders.py` (lines 130-160); `docs/web/api.md` (the `/nav` and `/spreads/orders` sections).

**Entry checks:**

- [ ] **B1. Section A landed.** `git log --oneline main..HEAD` shows A0's successor commits (two task commits,
  plus the A0 commit if `main` was not fast-forwarded); Tasks 1-2 are ticked.
- [ ] **B2. Green.** Python gate, web gate; pytest = A3 baseline + 5.
- [ ] **B3. Anchors.** Each prints a line: `grep -n '@router.get("/nav"' src/api/routers/meta.py`;
  `grep -n "def test_nav_has_a_ledger_section" tests/test_api_ledger.py`;
  `grep -n "limit=limit$" src/api/routers/spreads.py`.
- [ ] **B4. Nobody reads `/nav`.** `grep -rn '"/nav"' web/app web/components web/features web/lib --include=*.ts --include=*.tsx | grep -v api-types`
  prints nothing.

**Section exit:** two more commits; pytest = A's + 0 (Task 3: -2 +1; Task 4: +0; see the counts in each task);
`test_openapi_current` green; G1, G2.

### Task 3: `GET /nav` removed

**Files:** Modify `src/api/routers/meta.py`, `tests/test_api_meta.py`, `tests/test_api_ledger.py`,
`docs/web/openapi.json`, `web/lib/api-types.ts`, `docs/web/api.md`, `ARCHITECTURE.md`, `SETUP.md`, this plan.

- [ ] **Step 1: The test that it is gone.** Append to `tests/test_api_meta.py`:

```python


def test_the_old_nav_manifest_is_gone(client) -> None:
    """Web overhaul Part 4 (D3): the rail comes from web/lib/nav.ts; GET /nav is removed."""
    assert client.get("/nav", headers=AUTH).status_code == 404
```

  Run it: fails (200).
- [ ] **Step 2: Remove the tests of the route.** Delete `test_nav_lists_every_section_with_availability`
  (`tests/test_api_meta.py` line 46 to the end of that function, `assert all(s["available"] and s["note"] is None for s in sections.values())`)
  and, in `tests/test_api_ledger.py`, lines 94-96 (`def test_nav_has_a_ledger_section` and its two lines) with
  the two blank lines after them.
- [ ] **Step 3: Remove the route.** In `src/api/routers/meta.py`: line 1 becomes
  `"""Liveness and identity. (`GET /nav`, the old rail manifest, was removed in web overhaul Part 4.)"""`;
  delete `class NavSection` (line 32) through the end of `_SECTIONS` (the `]` after
  `("explain", "System Explanation", True, None),`) and the blank lines after it, so `@router.get("/health"`
  follows `class MeResponse`; delete the whole `nav` route (line 99 to the end of the file) so the file ends
  with `me`'s `return`.
- [ ] **Step 4: Green.** `python -m pytest -q tests/test_api_meta.py tests/test_api_ledger.py` passes;
  `ruff check src/api/routers/meta.py tests/test_api_meta.py tests/test_api_ledger.py` clean.
- [ ] **Step 5: Regenerate the contract.** The `api-types.ts` diff removes only the `/nav` path, `NavResponse`,
  `NavSection` and the `nav_nav_get` operation. `grep -rn "NavResponse\|NavSection" web --include=*.ts --include=*.tsx | grep -v node_modules` prints nothing.
- [ ] **Step 6: Docs.** `docs/web/api.md`: delete the `## GET /nav` section (from its heading to the `---`
  before the next section) and say in the meta routes' introduction "`GET /nav` was removed in web overhaul
  Part 4 (the rail comes from `web/lib/nav.ts`)." `ARCHITECTURE.md` line 947: replace the `GET /nav (...)` clause
  and the two sentences after it with "`GET /nav` was removed in web overhaul Part 4 (the rail and tab bar come
  from `web/lib/nav.ts`)". `SETUP.md` line 789: drop `` `GET /nav`, `` from the endpoint list.
- [ ] **Step 7: Gate and commit.** Python gate (pytest = A's - 1: two removed, one added), web gate. Commit
  `chore(api): remove GET /nav, unread since web overhaul Part 1`.

### Task 4: `GET /spreads/orders` says when it is capped

**Files:** Modify `src/api/models/spreads.py`, `src/api/routers/spreads.py`, `tests/test_api_spread_orders.py`,
the contract, `docs/web/api.md`, `STATUS.md`, this plan.

- [ ] **Step 1: Failing assertions.** In `tests/test_api_spread_orders.py`, replace line 148

```python
    assert len(client.get("/spreads/orders?days=60&limit=1", headers=OWNER).json()["orders"]) == 1
```

with

```python
    assert len(client.get("/spreads/orders?days=60&limit=1", headers=OWNER).json()["orders"]) == 1
    assert client.get("/spreads/orders?days=60&limit=1", headers=OWNER).json()["truncated"] is True
    assert client.get("/spreads/orders?days=60&limit=3", headers=OWNER).json()["truncated"] is False
    assert client.get("/spreads/orders?days=60", headers=OWNER).json()["truncated"] is False
```

  Run: fails (`KeyError: 'truncated'`).
- [ ] **Step 2: The field.** In `src/api/models/spreads.py`, after line 121
  (`    orders: list[SpreadOrderOut] = Field(default_factory=list)`) insert

```python
    truncated: bool = False  # more filled orders exist in the window than were returned (Part 4)
```

- [ ] **Step 3: The route.** In `src/api/routers/spreads.py` `spread_orders`:
  - the docstring's last line `an empty list: "unavailable" is not "none"."""` becomes

```python
    an empty list: "unavailable" is not "none". ``truncated`` says the window held more than
    ``limit`` orders (web overhaul Part 4), so a capped list never reads as the whole record."""
```

  - line 184 `            s, start=(now - timedelta(days=days)).replace(tzinfo=None), limit=limit` becomes
    `            s, start=(now - timedelta(days=days)).replace(tzinfo=None), limit=limit + 1`;
  - line 205 `        for r in rows` becomes `        for r in rows[:limit]`;
  - line 207 becomes

```python
    return SpreadOrdersResponse(
        as_of=now,
        available=True,
        underlying=underlying,
        orders=orders,
        truncated=len(rows) > limit,
    )
```

- [ ] **Step 4: Green, regenerate, docs.** `python -m pytest -q tests/test_api_spread_orders.py tests/test_web_fence.py tests/test_spreads_fence.py`;
  regenerate the contract (the diff adds `truncated` and the two docstring lines); `docs/web/api.md`
  `/spreads/orders` section: add `truncated` ("true when the window held more than `limit` orders");
  `STATUS.md`: the Part 3 caps line that says the spread-fills list "has no `truncated` flag" now says it has
  one since Part 4 (find it with `grep -n "truncated" STATUS.md`).
- [ ] **Step 5: Gate and commit.** Python gate (pytest unchanged by this task), web gate. Commit
  `feat(api): GET /spreads/orders says when the window held more than it returned`.

---

## Section C: Delete the unmounted, after porting their tests (Tasks 5-7) · model: sonnet (effort high)

**Reads:** this section; `web/components/options/{ApprovalCard.test.tsx,DecideControls.tsx,ShortsTable.test.tsx,
RollProposal.tsx,ControlsStrip.tsx,ControlsStrip.test.tsx}`; `web/features/position/{RollCard.tsx,RollCard.test.tsx}`;
`web/lib/test-query.tsx` (lines 1-80); `web/components/shell/BotSheet.tsx` (lines 1-10);
`web/features/trades/TradesPage.tsx` (lines 1-10). No UI is designed here; da-vinci is not needed.

**Entry checks:**

- [ ] **C1. Section B landed;** four task commits since A0 (or since the early merge); green gates.
- [ ] **C2. The sixteen are still unmounted.** For each name in ruling 8, this prints only the files ruling 8
  deletes and their tests (run from the worktree root):

  ```bash
  cd web && for n in ApprovalsList ApprovalCard ShortsTable ShortsRow PortfolioShell PositionsPanel PositionGroup StockLegRow OptionLegRow CampaignsPanel CampaignThread CalendarPanel PnlShell LedgerNav; do grep -rln "/$n\"\|\./$n\"" app components features lib; done | sort -u; grep -rln "portfolio/SummaryPanel\|from \"./SummaryPanel\"" components/portfolio app features; grep -rn "ControlsStrip" app components features lib | grep -v "^components/options/ControlsStrip"; cd ..
  ```

  Expected: only `components/options/{ApprovalCard,ApprovalsList,ShortsRow,ShortsTable}.tsx`,
  `components/portfolio/{CampaignsPanel,PortfolioShell,PositionGroup,PositionsPanel}.tsx` and their
  `*.test.tsx`; the `SummaryPanel` line names `PortfolioShell.tsx` and `SummaryPanel.test.tsx`; the
  `ControlsStrip` line names `BotSheet.tsx:4` and `TradesPage.tsx:4` (the `DrainWarning` imports). Anything
  else: stop.
- [ ] **C3. Green**; vitest = 1485 in 152 files (unchanged by A and B).

**Section exit:** three more commits; vitest = 1485 - 100 + 14 + 12 + 2 = **1413**, files = 152 - 9 + 2 = **145**
(recompute if C3 differed); G1 (the protected files untouched; `DecideControls.tsx` still exists), G2; G4 build
green.

### Task 5: `DecideControls.test.tsx`, ported from `ApprovalCard.test.tsx`

**Files:** Create `web/components/options/DecideControls.test.tsx`; this plan.

- [ ] **Step 1: Write the file.** Copy `ApprovalCard.test.tsx`'s harness (lines 1-61: the imports, `withClient`,
  `approval()`, the `@/lib/commands` mock, `dialogConfirm`), importing `DecideControls` from `./DecideControls`
  instead of `ApprovalCard`. Port these 14 cases, rendering
  `<DecideControls approval={approval(...)} />` (plus `drainHealthy`, `initialCommand` where the original passes
  them to the card; the card forwarded both unchanged):
  - "ApprovalCard — initialCommand": both cases (lines 73, 98);
  - "localStorage persistence": all three (131, 151, 169);
  - "decide controls (M3)": the seven at 192, 203, 229, 246, 252, 262, 279;
  - "live-mode second confirmation": the two at 320 and 344.
  Keep each case's title and body; change only the render call and any query scoped to the card's markup
  (none of the 14 reads the card's title or tags; if one does, scope it to the controls and record it). Title
  the describes `DecideControls — ...`. The three card-display cases (64, 361, 366) are not ported (ruling 12).
- [ ] **Step 2: Green.** `cd web && npx vitest run components/options/DecideControls.test.tsx` → 14 passed.
- [ ] **Step 3: Mutation check, in a scratch copy only.** Copy `web/` to the scratchpad (as G4, symlinked
  `node_modules`), and in the copy apply each mutation to `components/options/DecideControls.tsx`, run the new
  file, confirm the named cases fail, then discard the copy:
  1. call `submitCommand` directly from Approve's `onClick` (skip `ConfirmAction`) → "opens ConfirmAction before
     any request" fails;
  2. drop the `disabled` on both buttons → "disables both controls while a command is in flight" fails;
  3. ignore `initialCommand` → both initialCommand cases fail;
  4. never call `savePersistedCommand` → the three persistence cases fail;
  5. treat a 403 like any error → the permission case fails;
  6. render the plain receipt instead of the live dialog for `needs_confirmation` → the live-step cases fail.
  Record each mutation and its failing case names in the Progress log row. A case no mutation turns red is a
  finding: say so, do not delete it.
- [ ] **Step 4: Gate and commit.** Web gate (vitest + 14, files + 1). G1 prints nothing. Commit
  `test(web): DecideControls' own suite, ported from ApprovalCard before it goes`.

### Task 6: The roll flow's tests on `RollCard`; `DrainWarning` moves to the shell

**Files:** Modify `web/features/position/RollCard.test.tsx`; create `web/components/shell/DrainWarning.tsx`,
`web/components/shell/DrainWarning.test.tsx`; modify `web/components/shell/BotSheet.tsx`,
`web/features/trades/TradesPage.tsx`; this plan.

- [ ] **Step 1: Port the roll cases.** Append to `RollCard.test.tsx`'s describe the 12 cases of
  `ShortsTable.test.tsx` lines 187-470 that `RollCard` does not already cover (ruling 12): the control is labelled
  "Propose a roll" (198); the dialog says price, raise for approval, nothing executes until approved (214);
  `roll_already_working` links to the existing approval (278); on success the receipt links to the new approval
  (301); disabled while a roll command is in flight (322); a 403 renders a permission message (345); the three
  live-step cases (357, 386, 412); the two reload cases (438, 459); and "renders a Propose a roll control" as
  "renders one Propose a roll control" (187). Use `RollCard.test.tsx`'s harness (`renderWithQuery`,
  `apiFetchMock`, `command()`, `confirmDialog`, `writes()`), answering `/commands` POSTs through `apiFetchMock`
  as its existing "sends one roll_request" case does, and the persistence key the hook uses
  (`useRollProposal`'s `subject`). Keep each original title.
- [ ] **Step 2: Green, then the mutation check** in a scratch copy of `web/` on `components/options/RollProposal.tsx`
  (not protected, still: scratch only): skip the confirm dialog; drop the in-flight disable; skip persistence;
  render the success link without the approval id. Record each in the row.
- [ ] **Step 3: Move `DrainWarning`.** Create `web/components/shell/DrainWarning.tsx` with `"use client";`, the
  `relativeAge` import from `@/lib/format`, and the `DrainWarning` function and its comment copied byte for byte
  from `components/options/ControlsStrip.tsx` (the comment's "here and in the shell's bot sheet" becomes "in the
  shell's bot sheet and on Trades"). Change `BotSheet.tsx:4` and `TradesPage.tsx:4` to
  `import { DrainWarning } from "@/components/shell/DrainWarning";`. `ControlsStrip.tsx` is left as it is (Task 7
  deletes it).
- [ ] **Step 4: Its test.** `components/shell/DrainWarning.test.tsx`, 2 cases: never run → text contains
  "the trading service is not draining commands" and "(it has never run)"; a last-seen time → contains
  "(last seen " and not "never". `components/shell/shell.test.tsx` and `features/trades/TradesPage.test.tsx`
  pass unmodified.
- [ ] **Step 5: Gate and commit.** Web gate (vitest + 14, files + 1). Commit
  `test(web): the roll flow's suite on RollCard; DrainWarning moves to the shell`.

### Task 7: Delete the sixteen unmounted files

**Files:** Delete the sixteen of ruling 8 and their nine test files; this plan.

- [ ] **Step 1: Delete.** `git rm` `web/components/options/{ApprovalsList,ApprovalCard,ShortsTable,ShortsRow,ControlsStrip}.tsx`,
  `web/components/options/{ApprovalsList,ApprovalCard,ShortsTable,ControlsStrip}.test.tsx`,
  `web/components/portfolio/{PortfolioShell,SummaryPanel,PositionsPanel,PositionGroup,StockLegRow,OptionLegRow,CampaignsPanel,CampaignThread,CalendarPanel}.tsx`,
  `web/components/portfolio/{PortfolioShell,SummaryPanel,PositionGroup,CampaignThread,CalendarPanel}.test.tsx`,
  `web/components/pnl/PnlShell.tsx`, `web/components/ledger/LedgerNav.tsx`.
- [ ] **Step 2: Nothing dangles.** `cd web && npx tsc --noEmit` clean; the C2 loop prints nothing; the
  survivors still resolve: `ls components/portfolio/{types.ts,Money.tsx,FreshnessLabel.tsx,DegradedNotice.tsx,RefreshControl.tsx,useBrokerRefresh.ts} components/options/{EmptyState,StageBadge,RationaleTags,RollModeControl,RollProposal,DecideControls}.tsx`.
  `EmptyState` keeps importers (`FillsTable`, `OrdersTable`, `components/pnl/SummaryPanel`); `RationaleTags`
  keeps `ApprovalDetail`.
- [ ] **Step 3: Comments that name the deleted.** `grep -rn "ShortsTable\|ApprovalsList\|ApprovalCard\|PortfolioShell\|PnlShell\|LedgerNav\|ControlsStrip" web/app web/components web/features web/lib | grep -v "\.test\."`
  lists comments only; reword each to name the live file (for example `RollCard.tsx`'s "Same key as the legacy
  ShortsTable" becomes "Same key as Home's Roll alert word"), except inside the protected files, which stay.
- [ ] **Step 4: Gate and commit.** Web gate: vitest = **1413**, files = **145** (if C3 differed, C3 - 100 + 28 and
  C3 files - 7). G1, G2, G4 (the build lists the same routes as before). Commit
  `chore(web): delete the sixteen files Parts 2 and 3 left unmounted, their live coverage ported`.

---

## Section D: The value book where it is missing (Tasks 8-10) · model: sonnet (effort high)

**Reads:** this section and rulings 5-7, 15-17; `web/DESIGN.md` (Surfaces → Home, Portfolio, Activity;
Components; The Lime Means Act Rule); `web/components/value/{ValueDecide,ValueProposalRow,ValueCard,useValueBook,format,types}.ts(x)`;
`web/features/stock-value/AnalyseButton.tsx`; `web/features/home/{NeedsYou,ProposalsBanner,HomePage,PositionsCard,positions,PayCard,TodayTrades,RealisedCalendar}.tsx/ts`;
`web/features/portfolio/{positions.ts,PositionsView.tsx}`; `web/features/activity/{ExecutionsList.tsx,fills.ts,PayMonth.tsx}`;
`web/components/ledger/types.ts`; `web/features/research/format.ts` (`stockValueHref`); `web/lib/test-query.tsx`.
**Invoke `da-vinci` first** (it reads `web/DESIGN.md`; no interview).

**Entry checks:**

- [ ] **D1. Section C landed**; vitest 1413 in 145 files (or C's recorded counts).
- [ ] **D2. The contract carries the heartbeat.** `grep -n "drain_last_seen?: string | null" web/lib/api-types.ts`
  prints at least two lines (Controls and ValueBook).
- [ ] **D3. Anchors.** `grep -n "Value proposals wait in the Value book card." web/features/home/NeedsYou.tsx`;
  `grep -n 'href: null,' web/features/home/positions.ts`; `grep -n 'const BOOK: Record<string, string>' web/features/activity/fills.ts`
  each print a line.

**Section exit:** three more commits; G1, G2 (no new command site), G3 (DESIGN.md updated by Tasks 9-10), G4;
da-vinci `lint.py` over the touched folders: no finding in a non-test file.

### Task 8: A value tap says when the value process is not checking

**Files:** Create `web/components/value/ValueDrainNote.tsx`, `ValueDrainNote.test.tsx`; modify
`web/components/value/ValueDecide.tsx`, `ValueDecide.test.tsx`, `web/features/stock-value/AnalyseButton.tsx`,
`AnalyseButton.test.tsx`; this plan.

- [ ] **Step 1: Tests first.** `ValueDrainNote.test.tsx` with `renderWithQuery` answering `/value/book`:
  1. `pending` and `drain_healthy: true` → renders nothing (`queryByTestId("value-drain-note")` null);
  2. `pending`, `drain_healthy: false`, `drain_last_seen: "2026-11-05T19:31:00Z"` → the note contains
     "Not checking" and "last checked for taps" and "2:31 PM ET" (19:31 UTC is 2:31 PM in New York in November);
  3. `pending`, `drain_healthy: false`, `drain_last_seen: null` → "has not checked for taps yet";
  4. not pending, unhealthy → nothing;
  5. the book request fails → nothing (unknown is not stalled).
  Append to `ValueDecide.test.tsx`: a pending tap with an unhealthy drain shows the note **and** no element with
  `data-testid="stalled-words"` (the protected receipt's trading-service sentence never appears for a value tap).
  Append to `AnalyseButton.test.tsx`: the same note appears under a pending analysis with an unhealthy drain.
  Run red (the module does not exist).
- [ ] **Step 2: The component** (reference; da-vinci may adjust spacing, not the words or the rules of ruling 16):

```tsx
"use client";

import { StatusWord } from "@/components/ui/StatusWord";
import { whenET } from "@/features/trades/time";
import { useValueBook } from "./useValueBook";

/**
 * The value process's drain, in words, under a value tap's receipt (web overhaul Part 4, ruling 5). The
 * protected CommandReceipt names "the trading service" when stalled, the wrong process for a value tap, so
 * the receipt is always given a healthy drain and this line says the true thing. Nothing while the command
 * is not pending, the drain is healthy, or the book has not been read (unknown is not stalled).
 */
export function ValueDrainNote({ pending }: { pending: boolean }) {
  const { data } = useValueBook();
  if (!pending || !data || data.drain_healthy) return null;
  const seen = data.drain_last_seen ?? null;
  return (
    <p className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-[0.8125rem]" data-testid="value-drain-note">
      <StatusWord tone="flag">Not checking</StatusWord>
      <span>
        {seen
          ? `The value process last checked for taps ${whenET(seen)}. This tap waits until it checks again.`
          : "The value process has not checked for taps yet. This tap waits until it runs."}
      </span>
    </p>
  );
}
```

- [ ] **Step 3: Mount it.** In `ValueDecide.tsx`, directly after
  `{current && <CommandReceipt command={current} order={null} drainHealthy={drainHealthy} />}` add
  `<ValueDrainNote pending={current?.status === "pending"} />` and its import; the `drainHealthy` prop stays
  (its default `true` is now the rule, ruling 5; say so in the prop's comment). In `AnalyseButton.tsx`, after its
  `CommandReceipt` line (88) add the same line and import.
- [ ] **Step 4: Gate and commit.** Web gate (vitest + 7); da-vinci `lint.py web/components/value web/features/stock-value`.
  Commit `feat(web): a value tap says when the value process is not checking for taps`.

### Task 9: Value taps in "Needs you" and the phone banner

**Files:** Create `web/features/home/ValueWaiting.tsx`, `ValueWaiting.test.tsx`; modify
`web/components/value/useValueBook.ts` (+ test), `web/features/home/NeedsYou.tsx`, `ProposalsBanner.tsx`,
`HomePage.test.tsx`, `web/components/value/ValueCard.tsx` (only if `#value-title` needs `scroll-mt`),
`web/DESIGN.md`; this plan.

- [ ] **Step 1: Tests first.**
  - `useValueBook.test.ts`: `waitingProposals(book)` returns the `needs_tap && status === "pending"` proposals in
    the book's order; `null` when the book is unread or unavailable (as `waitingOnTap`).
  - `ValueWaiting.test.tsx` (`renderWithQuery` with `/value/book`): one waiting buy → a row with "Value book", the
    title from `proposalTitle`, the cost, the time-left words, and a link named "Review in the Value book" whose
    `href` ends `#value-title`; **no button named Approve, Reject or Review** (ruling 15; Review Focus 5); a
    proposal that does not need a tap is not listed; an unreadable book → "The value book could not be read, so
    a value proposal may be waiting." (unknown is not none); none waiting → renders nothing.
  - `HomePage.test.tsx` (append): under All with one wheel and one value proposal waiting, the heading reads
    "Needs you · 1 proposal · 1 value"; under Value, "Needs you" lists the value row and no longer says "Value
    proposals wait in the Value book card."; with only a value proposal, the phone banner reads "1 value proposal
    needs you", names it, and its link is not lime (no `bg-primary` class) and jumps to `#value-title`; with a
    wheel proposal too, the lime Open still goes to `/trades`.
  Run red.
- [ ] **Step 2: Build.** `waitingProposals` beside `waitingOnTap` in `useValueBook.ts`. `ValueWaiting.tsx`: a
  `Card` per the row anatomy of `ProposalCard`'s eyebrow and title (eyebrow "Value book", `proposalTitle`,
  the cost with `price()` or a hatched `n/a`, `expiresWords`), the link a secondary pill (`bg-sunk`, 44 px,
  the `ProposalCard` Details pill's classes), `href="#value-title"`. `NeedsYou.tsx`: under `all` render the wheel
  body then `<ValueWaiting />`; under `value` render only `<ValueWaiting />` (or "No value proposal waits on
  you." when it renders nothing and the book read); the heading appends ` · N value` when N > 0. `ProposalsBanner`:
  read `waitingProposals(useValueBook().data)`; under `all` and `value` add them to the count and the names
  ("GOOGL buy"); the link per ruling 15. If the jump hides the heading under the halted banner, add `scroll-mt-4`
  to the Value card's `h2`.
- [ ] **Step 3: DESIGN.md.** Surfaces → Home: one paragraph for the value rows in Needs you and the banner
  (ruling 15's rule and words); a Decision Log entry dated the day; bump the marker's `updated=`. G3 exits 0.
- [ ] **Step 4: Gate and commit.** Web gate; da-vinci lint over `web/features/home web/components/value`.
  Commit `feat(web): value proposals waiting on a tap show in Needs you and the phone banner`.

### Task 10: The value book on Portfolio and At IBKR; the unavailable flag

**Files:** Modify `web/features/home/positions.ts` (+ test), `web/features/portfolio/positions.ts`,
`PositionsView.tsx` (+ tests), `web/features/activity/ExecutionsList.tsx`, `fills.ts` (+ tests),
`web/components/ledger/types.ts`, `web/components/value/useValueBook.ts` (+ test), `web/features/home/PayCard.tsx`,
`TodayTrades.tsx`, `RealisedCalendar.tsx`, `web/features/activity/PayMonth.tsx` (+ tests), `web/DESIGN.md`; this plan.

- [ ] **Step 1: Tests first.**
  - `features/home/positions.test.ts` line 165: the value row's expected `href` becomes `"/stock/AAPL#value-block-AAPL"`
    (an existing test changes, ruling 17).
  - `features/portfolio` tests: the Value chip exists between Credit spreads and Shares with the count of open
    value positions; under All and Value a "Value book" card lists them (title, open P&L or a hatched `n/a`, the
    stock link); an unreadable `/value/positions` says "The value book could not be read, so its shares are not
    listed." and never "holds no shares"; Value with none says "The value book holds no shares."
  - `features/activity` tests: `bookWord("value")` is "Value book"; the At IBKR chips include "Value", and choosing it
    requests `&book=value`.
  - `useValueBook.test.ts`: `useValueOut(false)` with a book `{enabled: false, available: false}` is false; with
    `{enabled: true, available: false}` true; with the book request failing true; `useValueOut(true)` and
    `useValueOut(undefined)` false.
  - One `PayCard` case: `value_available: false` under All with the book off and never written shows no "Value
    book unavailable" word; the existing flag cases pass unmodified.
  Run red.
- [ ] **Step 2: Build.** `buildValueRows`' `href` becomes `stockValueHref(p.symbol)` (import from
  `@/features/research/format`) and its doc comment says so. Portfolio: `PositionsFilter` gains `"value"`
  (`FILTERS` `["all","csp","cc","spread","value","shares"]`, `EMPTY.value`), `PositionsView` reads
  `/value/positions?status=open` with Home's key `["value","positions","open"]` and renders the card with
  `PositionRowItem`. `fills.ts` `BOOK` gains `value: "Value book"`; `ExecutionsList` `BookFilter` and `BOOKS` gain
  `value`/"Value". `components/ledger/types.ts:24` `book: "system" | "manual" | "spreads" | "value"`. `useValueOut`
  in `useValueBook.ts` (ruling 7; reference below) and the four flag sites call it at the top of the component
  (hooks before any early return), keeping their scope conditions:

```ts
/**
 * Whether to flag the value book as unavailable beside a P&L figure (web overhaul Part 4, ruling 7). The pay
 * routes answer `value_available: false` both when value.db cannot be read and when it was never written; a
 * book that is off and has never written anything has no sales to miss, so it is not flagged. A book read
 * that failed or is still loading keeps the flag: unknown is not none.
 */
export function useValueOut(valueAvailable: boolean | undefined): boolean {
  const { data } = useValueBook();
  if (valueAvailable !== false) return false;
  return !(data !== undefined && data.enabled === false && data.available === false);
}
```

- [ ] **Step 3: DESIGN.md.** Surfaces → Portfolio: the Value chip and card in one sentence; Activity: the Value
  chip on At IBKR. G3.
- [ ] **Step 4: Gate and commit.** Web gate; da-vinci lint. G1, G2, G4. Commit
  `feat(web): the value book on Portfolio and At IBKR; no unavailable flag for a book that never ran`.

---

## Section E: Honesty minors and the cross-links (Tasks 11-13) · model: sonnet (effort high)

**Reads:** this section and rulings 18-22, 28; `web/DESIGN.md` (Surfaces → Trades, Activity);
`web/features/trades/{HistoryView,SpreadsView,ProposalsView,useTradesView,TradesPage}.tsx/ts` and their tests;
`web/components/options/ApprovalDetail.tsx` (lines 1-90); `web/features/home/ProposalCard.tsx`;
`web/components/pnl/{BreakdownTable,SummaryPanel}.tsx` (+ `SummaryPanel.test.tsx`);
`web/features/activity/{PayView,useMonthParam,month,SpreadFills,FillsView}.ts(x)`;
`web/components/ledger/TradesTable.tsx`; `web/lib/strategy.ts`. **Invoke `da-vinci` first.**

**Entry checks:**

- [ ] **E1. Section D landed**; green gates.
- [ ] **E2. Anchors.** Each prints a line:
  `grep -n "if (!loaded || !orders.data || (sent.length === 0 && working.length === 0)) return null;" web/features/trades/HistoryView.tsx`;
  `grep -n "if (!q.data) return null;" web/features/trades/HistoryView.tsx`;
  `grep -n "const \[day, setDay\] = useState<string | null>(null);" web/features/trades/SpreadsView.tsx`;
  `grep -n 'href="/trades"' web/components/options/ApprovalDetail.tsx`;
  `grep -n 'stock_gain === null ? ""' web/components/ledger/TradesTable.tsx`.

**Section exit:** three more commits; G1, G2, G4; da-vinci lint clean on non-test files.

### Task 11: History never shows unknown as none

**Files:** Modify `web/features/trades/HistoryView.tsx` (+ `HistoryView.test.tsx`); this plan.

- [ ] **Step 1: Tests first** (append): today, `/options/orders?state=working` fails and nothing was sent →
  the "In flight" heading shows with "In-flight orders could not be loaded right now."; the approvals read for
  sent cards fails → the same section says so; `/options/approvals?status=all...` fails → "Not traded" shows with
  "Proposals that did not trade could not be loaded right now."; it returns 200 rows → the 200-limit sentence of
  ruling 18; a successful empty read still renders neither section (existing behaviour, existing tests unchanged).
  Run red.
- [ ] **Step 2: Build.** `InFlight`: replace the bare `return null` with: loading (no data, no error) → `null`;
  either read failed with no data → the section with the sentence; both loaded and empty → `null`. `useSent`'s
  `loaded` flag needs its error state; expose `failed` beside `loaded` in the same hook. `NotTraded`: `q.isError
  && !q.data` → the section with the sentence; `q.data.approvals.length >= 200` → the limit sentence under the
  list (and the list).
- [ ] **Step 3: Gate and commit.** Web gate. Commit `fix(web): History says when it could not read, never nothing`.

### Task 12: Back to the Trades you left; the Spreads day in the URL

**Files:** Modify `web/features/trades/useTradesView.ts` (+ test), `HistoryView.tsx`, `ProposalsView.tsx`,
`SpreadsView.tsx` (+ tests), `web/features/home/ProposalCard.tsx`, `web/components/options/ApprovalDetail.tsx`
(+ `ApprovalDetail.test.tsx`); this plan.

- [ ] **Step 1: Tests first.** `useTradesView.test`: `tradesReturnQuery(params)` keeps only `view`, `day` (a real
  calendar day) and `strategy` (a known filter), in that order, and drops the rest; empty gives `""`.
  `ApprovalDetail.test` (append): rendered at `?view=history&day=2026-11-03&strategy=csp&x=1`, the back link's
  `href` is `/trades?view=history&day=2026-11-03&strategy=csp`; with `?day=junk` it is `/trades`; with nothing it is
  `/trades`. `HistoryView.test` (append): a Not traded row's link carries the current view, day and strategy.
  `SpreadsView.test` (append): Previous writes `?day=<previous_day>` to the URL (router `replace` called with it);
  a `?day=` in the URL is the day requested (`/spreads/picks?day=...`). Run red.
- [ ] **Step 2: Build.** `tradesReturnQuery` and `detailHref(id, query)` in `useTradesView.ts`; HistoryView's three
  links and `ProposalCard`'s Details link (through an optional `detailQuery?: string` prop, passed by
  `ProposalsView`; Home passes nothing) use `detailHref`. `BackToTrades` reads `useSearchParams()` and builds the
  href with `tradesReturnQuery`; wrap its use in `<Suspense fallback={<plain link to /trades>}>` if the build asks
  for it (`app/trades/[approvalId]` is dynamic; G4 says). `SpreadsView`: `const [day, setDay] = useTradesDay();`
  replaces the `useState` (null still means today). Check "Next onto today": with `next_day` equal to today the
  arrow must clear `?day` (today), not pin the date; record whether it already did.
- [ ] **Step 3: Gate and commit.** Web gate; G4 (the detail route still builds). Commit
  `fix(web): back to the Trades view you left; the Spreads day lives in the URL`.

### Task 13: Pay's words, the month floor, the ledger's stock gain, capped spread fills, cross-links

**Files:** Modify `web/components/pnl/BreakdownTable.tsx`, `SummaryPanel.tsx` (+ test),
`web/features/activity/PayView.tsx` (+ test), `SpreadFills.tsx` (+ test), `FillsView.tsx` (+ test),
`web/components/ledger/TradesTable.tsx` (+ `TradesView.test.tsx`), `web/features/trades/HistoryView.tsx`
(+ test), `web/features/activity/types.ts` if `SpreadOrdersResponse` is hand-typed there; this plan.

- [ ] **Step 1: Tests first.**
  - `SummaryPanel.test.tsx`: the by-strategy row for `cash_secured_put` reads "Cash-secured puts" and
    `covered_call` "Covered calls"; an unknown label passes through (the existing assertion on the raw label at
    line 23's fixture is updated, ruling 21).
  - `PayView.test`: `?month=` a month before `starts_at` opens `starts_at`'s month (Previous disabled), never a
    month of zeros before the record.
  - `TradesView.test`: a "Called away" trade with `stock_gain: null` shows a hatched `n/a`; an "Expired" trade with
    `stock_gain: null` shows an empty cell.
  - `SpreadFills.test`: `truncated: true` → "Only the newest 200 are listed."; false → no such sentence.
  - `HistoryView.test` and `FillsView.test`: the two cross-link sentences of ruling 22 with their `href`s.
  Run red.
- [ ] **Step 2: Build** per ruling 21-22: `BreakdownTable` gains `labelOf?: (label: string) => string` (identity by
  default); `SummaryPanel` passes a `strategyWord` for by-strategy only. `PayView` clamps the month to the record's
  first month once `starts_at` is known (through `parseMonth`'s floor or a clamp beside it; the URL is rewritten
  with `router.replace`). `TradesTable`'s stock-gain cell per ruling 21. `SpreadFills` reads `truncated` (add it to
  the hand type if `features/activity/types.ts` declares one; otherwise it comes from `api-types.ts`). The two
  sentences: secondary text links (`underline underline-offset-2`), one at the foot of History, one at the foot of
  Fills and orders.
- [ ] **Step 3: Gate and commit.** Web gate; da-vinci lint. Commit
  `fix(web): Pay says strategy names, months start at the record, a capped list says so, History and Fills link`.

---

## Section F: Titles, not-found and error pages (Tasks 14-15) · model: sonnet (effort high)

**Reads:** this section and rulings 23-24; `web/app/layout.tsx`; every `web/app/**/page.tsx` (first lines);
`web/DESIGN.md` (Typography, Components → Button, Card). **Invoke `da-vinci` first.**

**Entry checks:**

- [ ] **F1. Section E landed**; green gates.
- [ ] **F2. No boundary exists yet.** `find web/app -name "not-found.tsx" -o -name "error.tsx" -o -name "layout.tsx" | sort`
  prints only `web/app/layout.tsx`.
- [ ] **F3. Client pages** (these need a sibling layout): `grep -l '^"use client"' $(find web/app -name page.tsx)` lists
  `research`, `more`, `stock/[symbol]`, `more/claude`, `news/[symbol]`, `research/universe`, `trades/[approvalId]`,
  `positions/[underlying]/[slug]`, `ledger/ticker/[symbol]` (nine). A difference: update ruling 23's list first.

**Section exit:** two more commits; G1, G2, G3, G4 (the build lists every route and `/_not-found`).

### Task 14: A title on every route

**Files:** Modify `web/app/layout.tsx`, the eight server pages; create nine `layout.tsx` files beside the
client pages and `web/app/titles.test.ts`; this plan.

- [ ] **Step 1: Test first.** `app/titles.test.ts` imports each server page's `metadata`, each new layout's
  `metadata` or calls its `generateMetadata({ params: Promise.resolve({...}) })`, and asserts ruling 23's titles
  (`"AAPL"` from `symbol: "aapl"`; `"AAPL position"` from `underlying: "AAPL", slug: "x"`; `"Proposal 42"` from
  `approvalId: "42"`; `"AAPL news"`; `"AAPL ledger"`), plus the root's `{ default: "IBKR Income", template:
  "%s · IBKR Income" }`. Run red.
- [ ] **Step 2: Build.** Root: `title: { default: "IBKR Income", template: "%s · IBKR Income" }`. Server pages:
  `export const metadata: Metadata = { title: "Trades" };` etc. (Home sets none.) Client pages: a sibling
  `layout.tsx`:

```tsx
import type { Metadata } from "next";

// The page is a client component, which cannot export metadata (web overhaul Part 4, ruling 23).
export async function generateMetadata({ params }: { params: Promise<{ symbol: string }> }): Promise<Metadata> {
  const { symbol } = await params;
  return { title: decodeURIComponent(symbol).toUpperCase() };
}

export default function Layout({ children }: { children: React.ReactNode }) {
  return children;
}
```

  (a static one exports `metadata` instead).
- [ ] **Step 3: Gate and commit.** Web gate; G4 (titles appear in the built HTML: grep one page's `<title>` in
  `.next/server/app/portfolio.html` of the scratch copy). Commit `feat(web): every route has its own title`.

### Task 15: Not-found and error pages

**Files:** Create `web/app/not-found.tsx`, `web/app/error.tsx`, `web/app/boundaries.test.tsx`; modify
`web/DESIGN.md`; this plan.

- [ ] **Step 1: Tests first.** `boundaries.test.tsx`: `NotFound` renders one `h1` "This page does not exist", the
  sentence "The address may be old or mistyped. Nothing was changed.", and a link to `/`; `metadata.title` is
  "Not found". `ErrorPage` (`app/error.tsx`) renders one `h1` "This page could not be shown", "Nothing was changed.
  The rest of the console still works.", a "Try again" button that calls `reset` once, and (when `error.digest`
  exists) "Reference <digest>"; no element carries `bg-primary` (ruling 24: not lime). Run red.
- [ ] **Step 2: Build.** Both on the page frame (`mx-auto max-w-[720px] px-4 py-5 md:px-7 md:py-6`), a `Card`, the
  `Button` primitive (`variant="secondary"`) for Try again, a secondary pill link for Home; `error.tsx` starts with
  `"use client"` and `console.error(error)` in an effect.
- [ ] **Step 3: DESIGN.md.** Components or Surfaces: one paragraph for the not-found and error pages (words above;
  no lime; one action each); Decision Log entry; marker. G3.
- [ ] **Step 4: Gate and commit.** Web gate; G4 (`/_not-found` built). Commit
  `feat(web): a not-found page and an error page that say what happened`.

---

## Section G: Finish (Tasks 16-17) · sonnet (high); then opus review, sonnet fix pass

**Entry checks:**

- [ ] **G-1. Sections A-F landed** (15 task commits beyond A0, plus any recorded fix); every gate green; G1-G4.
- [ ] **G-2. A browser** (Playwright MCP or Claude in Chrome) loads, or the operator agrees to take the captures.

### Task 16: Docs

**Reads:** this section; the files named below; `CLAUDE.md` doc-update table. **Files:** `STATUS.md`,
`ARCHITECTURE.md`, `web/CLAUDE.md`, `web/DESIGN.md`, `SETUP.md`, `docs/web/architecture.md` (if Task 2 missed
anything), this plan.

- [ ] **Step 1: The D6 rewrites.** `STATUS.md:949` row: Parts 1-3 built with dates, **Part 4 built <date>**, Parts
  5-8 and order control as the HANDOFF's roadmap (one sentence each, no plan yet); `STATUS.md` lines 651, 688,
  1127, 1395-1396, 1413 ("until Part 4"): say the files were deleted in Part 4. `ARCHITECTURE.md:1596-1597`: Part 4
  "deleted the legacy files Parts 2-3 left unmounted, removed `GET /nav`, ..."; drop "folds the ... into
  `features/`" (cut, HANDOFF D4). `web/CLAUDE.md` lines 534, 540, 578, 689, 706: the files are gone; name
  `DecideControls.test.tsx`, the roll cases on `RollCard.test.tsx`, `components/shell/DrainWarning.tsx`,
  `components/value/ValueDrainNote.tsx`, `features/home/ValueWaiting.tsx`, the route layouts and boundaries; add
  the rule "new code goes in `features/`; `components/` keeps `ui`, `shell`, the protected `options` controls,
  `value` and the survivors" (HANDOFF D4).
- [ ] **Step 2: Built section.** `STATUS.md`: "Built (<date> - web overhaul Part 4)" listing each task's change in
  one line, the rulings that changed behaviour (5, 7, 15, 18-24), and "Deferred" (ruling 28).
- [ ] **Step 3: Folder guide.** `ARCHITECTURE.md` web folder guide: the new files and the deleted ones.
- [ ] **Step 4: SETUP.md troubleshooting.** One row: "A value tap stays Queued with 'Not checking'" → the value
  process is not draining: `./ibkr status`, `logs/value.log`, `./ibkr restart`.
- [ ] **Step 5: Gate and commit.** G3; `grep -rn "until Part 4" STATUS.md ARCHITECTURE.md web/CLAUDE.md docs/web`
  prints nothing. Commit `docs: web overhaul Part 4`.

### Task 17: The da-vinci finish by a fresh reviewer, with the missing dark captures

**Spawned by the orchestrator as a new subagent with no prior context** (ruling 25), sonnet, effort high. Its
prompt: this plan's Global Constraints, ruling 25, `web/DESIGN.md`, the list of surfaces below, "Invoke the
`da-vinci` skill first and run `critique`, then `audit`, then `polish`", "never the live API, never inside `web/`".

- [ ] **Step 1: The synthetic API.** In the scratchpad, extend Part 3's mock
  (`docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md` Task 15 Step 1; extract by line range)
  with: `/value/book` (one tap-waiting buy, one approved, `drain_healthy: false`, a `drain_last_seen`), `/value/positions`
  (two open), `/value/top?list=` (three cards, one READY), `/value/GOOGL` (built from `api-types.ts`'
  `ValueTickerResponse`: one list READY, a Claude block), `/pnl/day` (a `capital_release` close card), `/pnl/month`
  and `/pnl/calendar` with `value_available`, `/spreads/orders` with `truncated: true`, `/ledger/executions` with a
  value execution. A scratch `next dev` from a copy of `web/` (as Part 3: never inside `web/`, never on 3000).
- [ ] **Step 2: Captures.** At 320, 390 and 1440 px, light and dark: Home (All and Value, Needs you, the banner),
  the Value card with its sheet open, a pending tap with "Not checking", Done today with the capital-release card,
  Portfolio (Value chip), Activity Fills (At IBKR, Value chip; spread fills capped), Trades History (In flight
  unavailable), a detail page and its back link, the stock page's value block (G), Research Top opportunities (H),
  a not-found and an error page. The F-I set must include F at 1440 dark, G at 390 dark, H and I in every state in
  dark. PNGs stay in the scratchpad.
- [ ] **Step 3: critique, audit, polish.** Fix what they find, each fix with a test written red first when behaviour
  changes; record findings not fixed with a reason. No new token (a proposal waits for the operator).
- [ ] **Step 4: Gate and commit.** Every gate; G1-G4; da-vinci `lint.py` over `web/app web/components web/features`
  finds nothing in a non-test file (the one legacy em dash at `components/explain/SourceRefs.tsx:21` is Part 7's
  page; fix it here only if the reviewer touches the file, else record it). Commit
  `fix(web): da-vinci finish of web overhaul Part 4 and the value book's web sections`.

**Then:** one **opus** whole-branch review (superpowers:requesting-code-review, effort high) over `main..HEAD`
with Review Focus above; the orchestrator confirms each finding in the code; one **sonnet** fix pass (high), each
fix test-first; fill both rows; superpowers:finishing-a-development-branch. **No merge or push without the
operator.**

---

## Operator to-dos

1. **Answer the early-merge question after Section A** (yes merges Section A to `main` and runs
   `./ibkr restart`). Until then a capital-release close reads "the reason was not recorded" on the web; nothing
   else about the release is wrong, and its Telegram message is unaffected. Turning the book off meanwhile is your
   call; this plan does not need it (recommendation: leave it on).
2. After the final merge: `./ibkr restart` (the API serves the new fields; the web picks up the new code through
   your running `next dev`).
3. Look once at Home on a phone in dark mode with a value proposal waiting (ruling 15's row and banner); overturn
   ruling 15 if you would rather decide from "Needs you" directly.
4. Ratify or amend the `web/DESIGN.md` Open Decisions before Part 7 (Q6), including the receipt's "waiting for the
   trading service" copy on value taps (ruling 5).
5. Housekeeping still owed from the HANDOFF (7.2 item 3): remove `.claude/worktrees/value-book-6` and the merged
   branches.

## Self-review (run by the plan's author, 2026-11-05)

- **Spec coverage.** HANDOFF section 5's Part 4 row: V1 (Task 1), V2 (Tasks 2, 8), D3 (Task 3), D1-D2 (Tasks 5-7),
  V3 (Task 9), V4, V5, V8 (Task 10), the Part 2/3 honesty minors (Tasks 4, 11-13), F3 (Task 13), S2 (Task 14), S3
  (Task 15), V10 (Task 17), D6 (Task 16). V6, V7, V9 are Parts 5, 6, 8 by the HANDOFF's own plan.
- **Prototype.** Sections A and B were applied to a code-only copy of `main` at ca14c40 (`git archive`, `.venv` and
  `web/node_modules` symlinked, in the session scratchpad, deleted afterwards): `tests/test_reporting_day.py` 36
  passed; `tests/test_api_value.py`, `test_value_commands.py`, `test_value_fence.py`, `test_value_final_review.py`
  101 passed; `test_api_spread_orders.py`, `test_api_meta.py`, `test_api_ledger.py` 27 passed;
  `test_openapi_current.py` passed after the offline regeneration; `py_compile scripts/run_value.py` silent; ruff
  check clean and the touched files formatted (the structural test is given as `ruff format` writes it); mypy src
  clean; full pytest as in the Plan written row (5669 expected in a git worktree). The web sections were not prototyped (ruling 31).
- **Placeholders.** None in Sections A and B. Web tasks give tests and reference code; the implementer records
  deviations.
- **Type consistency.** `drain_healthy`/`drain_last_seen` (API, `api-types.ts`, `ValueDrainNote`);
  `VALUE_DRAIN_HEARTBEAT_KEY` (common, script, router, two tests); `truncated` (model, route, `SpreadFills`).
