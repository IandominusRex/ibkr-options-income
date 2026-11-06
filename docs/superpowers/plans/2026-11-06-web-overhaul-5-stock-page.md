# Web Overhaul, Part 5: The Stock Page (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task
> (one Sonnet subagent per section, at the effort the Execution model gives, with a stop between sections: the
> operator's token-light method). Each section opens with **entry checks** that must all pass before its first task
> starts. **Every task that touches UI starts by invoking the `da-vinci` skill**, and so does any subagent given one of
> those tasks (say so in its prompt). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recompose `/stock/[symbol]` on the payslip system and give the value book's figures their place on it:

- **The page frame:** a back link to Research, the ticker as the title, its name and exchange, the last price with
  "Delayed" in words when it is stale, then one grid like the position page's: the chart and the sections on the
  left, the news service's notes, the headlines, the crowd's tone and the written summary in a 340 px column on
  the right.
- **The value book's levels on the chart** (HANDOFF V6): fair value, entry ceiling, half sale and stop as dashed
  price lines, and the value block first, under the chart, for a name the book would buy at a price or holds.
- **The size tier and the tranche plan** in the API and in the value block's "How much, and when?" (value book
  Part 6 ruling G3), and **Claude's one-line note** on `GET /value/top` for Part 6's card (HANDOFF V7, backend only).
- **Every section a card**, restyled in place, saying its state in words: no green or red on anything that is not
  money (candles, the check ribbon, headline tone, the sentiment change).

**Architecture:** One read-side API change and one page. Section A adds `size_pct` and `tranches` to each
`ValueListOut`, the tranche fields to `ValuePlanOut` and `claude_note` to `ValueTopItem` (`src/api/models/value.py`,
`src/api/routers/value.py`, `src/api/value_db.py`); the size tier rule is mirrored from `src.value.sizing.tier_pct`
because the API may import only `scorecard` and `schemas` from `src.value`, and a parametrised test holds the two
equal. Section B adds `web/features/stock/` (`StockPage`, `StockSection`, `stock.ts`), rewrites
`components/stock/PriceChart.tsx` in place, thins `app/stock/[symbol]/page.tsx` to one mount, deletes
`components/stock/SectionShell.tsx`, and adds the size and tranche sentences to `features/stock-value/SizeBlock.tsx`.
Section C restyles `components/checks/*` and the other `components/stock/*` panels in place under their tests.
Nothing on the trading path, the Rules Engine, any gate, sizing or the value book's own logic changes; the API still
writes exactly one table; no command site is added (the page's only one stays the value block's `AnalyseButton`).

**Tech Stack:** Next.js 15 App Router, React 19, Tailwind CSS v4, @tanstack/react-query, lightweight-charts 4,
lucide-react, Vitest + Testing Library; FastAPI, Pydantic, SQLAlchemy (plain SQL over value.db), pytest.

**Spec:** `docs/superpowers/plans/2026-11-05-web-overhaul-HANDOFF.md` (updated 2026-11-06: section 3 lists L2, V6, V7,
S5; section 4 the calls; section 6 the binding rules), `web/DESIGN.md` (the visual authority), value book spec
`docs/superpowers/specs/2026-10-28-value-swing-book-design.md` sections 9.5 (size tiers and tranches) and 10 (the
stock page), `docs/superpowers/plans/2026-10-29-value-book-6-web-telegram.md` rulings G3, G5, G8, H2, H3.

## How the code is given (read this first)

**Every change in this plan is a `git diff` patch embedded below, one per task**, generated from a per-task git
history of a prototype (see the Plan written row) and applied with `git apply`. A patch is the complete, exact code:
new files appear in full, edits with their surrounding lines. So:

- **Never retype a patch.** Extract it with the helper written in A0 (`<S>/p5/plan_block.py`, `<S>` = the session's
  scratchpad directory, written out in full each time), check its SHA-256 against the table below, then
  `git apply --check` it. **`git apply --check` is the entry check that re-verifies every line a task edits**: if
  `main` moved under a patch, it fails and the section stops.
- The helper restores a blank context line an editor may have stripped (a diff's blank context line is one space);
  everything else is byte for byte. Edit this plan only with the Edit tool (Progress log rows, checkboxes), which
  leaves the patch blocks alone.
- Two blocks are not patches: `mock5` (the synthetic API for Task 11) and `capture5` (the capture harness).

| Block | SHA-256 of the extracted file | Applies on top of |
|---|---|---|
| `T1` | `c7b47420c84c44c9025446a43a3b1a2f1bf12939073daf6d877379b9a68078be` | `main` at A0 (`6347dd9` + the plan commit) |
| `T2` | `a7852848506560609127ac74878f1537622588ca03d47ea4c3e46b3246bacea3` | T1 and the Task 2 regeneration |
| `T3` | `80b1879cf925177b430ddc688c01d8083f30d5414b80913e60daf9e7efdc5eaa` | T2 |
| `T4` | `f9642237a89711c2c4fb8a33c742fc16c3d97952a7d498092a3909843ecbaa19` | T3 |
| `T5` | `9305fe956d1e4f6e3bac8da3aa74076d0dc080c4e0591f7d3ca6f531f1f7af56` | T4 |
| `T6` | `d11f27ded22e4ec38aa7c5434ac8d56c1d71a462e2e718cf29c905ed3f0484cf` | T5 (and T2's fixtures) |
| `T7` | `5e04a7f7b5714e3e3f97b637bbed487c0a7b304fe13ee2374d17a8c448e26904` | T6 |
| `T8` | `27fbf9a28273ecd111b4c33b6061856f5ad424a3aec947dbcbf0e3b69a284bfc` | T7 |
| `T9` | `455f0cb31695cf95070c8c9b28c23d843295f93aeba9673859684cde6d2fb484` | T8 |
| `T10` | `d37710f4c9639e0c2904238bcbd2d55db4554e88b06e75231b3b59fed70f9774` | T9 |
| `mock5` | `981d5174a62454dcc93c486c21055d2c3f707cbeba4521ba9a113a290b4693f9` | (a script, not a patch) |
| `capture5` | `d07f776428b6056a76041fc72285bf4df47022d8d36a5fc5576c48d1684fd67a` | (a script, not a patch) |

## Execution model

| Section | Tasks | Model | Effort | Why this model and effort |
|---|---|---|---|---|
| **A, The API: size tier, tranche plan, Claude's note** | 1-2 | **sonnet** | high | Read-side Python next to the value fence and a contract change the web types are generated from (shared state). Every line is a prototyped patch. |
| **B, The stock page: frame, chart, value levels** | 3-6 | **sonnet** | high | The page's structure and a chart; da-vinci first; four patches that build on each other. |
| **C, The sections, restyled in place** | 7-9 | **sonnet** | medium | Mechanical: three patches over small components, each with its red check. da-vinci first. |
| **D, Finish** | 10-11 | **sonnet** medium (Task 10, docs), **sonnet** high, a fresh agent (Task 11, the da-vinci finish) | as listed | Then one **opus** whole-branch review (high) and one **sonnet** fix pass (high). |

**How a section runs (the orchestrator).** The main session is a Sonnet orchestrator (effort high). For each section:

1. Run the section's **entry checks** yourself, in order. **Any check fails: stop**, report the output, do not start
   the section. A failure that belongs to the previous section is fixed there (record the ruling) first.
2. All pass: add a "Section X entry" row to the Progress log (gate result, date) in the worktree.
3. Spawn **one** subagent for the section with `model` and `effort` from the table (pass `effort` on every spawn). Its
   prompt: "You are executing Section X of `docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md` in the
   worktree `<W>` (the absolute path). The session scratchpad is `<S>` (the absolute path); the patch helper is
   `<S>/p5/plan_block.py`. Read the plan's 'How the code is given', 'Global Constraints' and your section only, plus
   the files the section lists under Reads. Apply each task's patch exactly as its steps say; never retype a patch;
   never edit a protected file; never build or run `next dev` inside `web/`. [For B, C and Task 11:] Invoke the
   `da-vinci` skill before any UI step and give it the task's Spec for da-vinci paragraph. Commit each task with its
   message, ticking its boxes and filling its Progress log row in the same commit (status, commit, gate, date, every
   ruling with its cost-if-wrong). Stop on any red gate you cannot attribute to your own change."
4. Verify the report yourself: `git log --oneline main..HEAD`, `git status --short`, the gate counts against the
   section exit, G1 and G2.
5. **Stop and ask the operator before the next section.**

After Section D's Task 11: one **opus** whole-branch review (superpowers:requesting-code-review, effort high) over
`main..HEAD` with the Review Focus below, as a subagent; the orchestrator confirms each finding in the code; one
**sonnet** fix pass (high), each fix test first. Ask before merge or push; fill the Merge row after.

**Commit counts.** A0 adds one commit on `main` (this plan and the HANDOFF). Each task is one commit and fills its own
Progress log row; a "Section X entry" row rides in the next task's commit. A review fix pass adds one commit.

## Progress log

| Section / task | Status | Commits | Gate | Date | Rulings |
|---|---|---|---|---|---|
| **Plan written** | done | (plan file only) | Prototyped on a code-only copy of `main` at `6347dd9` (`git archive`, `.venv` and `web/node_modules` symlinked, session scratchpad), then replayed as a per-task git history from which every patch was generated; each task's commit re-checked: `tsc --noEmit` clean at T2-T9; the targeted suites 79 -> 79 -> 86 -> 89 -> 94 -> 97 -> 100 -> 103 -> 105 across T1-T10. **Full gates on the final tree:** pytest **5703 passed, 1 skipped** (5675 + 28); `ruff check .` clean; the four touched Python files `ruff format`-clean; `mypy src` 361 files clean; `test_openapi_current`, `test_web_fence`, `test_value_fence` green; vitest **1557 in 152 files** (1531 + 26); `tsc --noEmit` and `npm run lint` clean; da-vinci `lint.py` over the touched folders: no finding; `design_md_check.py web/DESIGN.md` exit 0; scratch `npm run build` green (19 routes plus `/_not-found`; the first try hit the known Google-font fetch error, the retry passed). **Red checks run** (each new test against the old code): Task 1 28 failed / 16 passed; Task 4 3 failed; Task 6 3 failed / 35 passed; Task 7 3 / 18; Task 8 3 / 12; Task 9 2 / 6; Tasks 3 and 5 are new modules (red = module missing). **Rendered** with `next start` from the prototype's build against the `mock5` API and a headless Chromium (`capture5`): `/stock/GOOGL`, `/KO`, `/SPY`, `/ZZZZ` at 320, 390 and 1440 px, light and dark: no page error, no horizontal scroll, the value block second for GOOGL and after the statements for KO and SPY, the 404 sentence for ZZZZ, the chart's levels "Fair value, Half sale $215.00" and "Entry ceiling $190.00". One fix came from looking: the volume bars drew a "1M" axis label and a heavy band, so they are now the perforation tone with no label (in the T4 patch). **Not run:** a fresh-eyes da-vinci critique and audit (Task 11 does it), the live API. | 2026-11-06 | Written from the HANDOFF (updated 2026-11-06) section 5's Part 5 row; rulings 1-21 below. |
| **A0 setup** | done | `7981584` (docs: plan + handoff, on `main` over `6347dd9`) | Worktree `/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/web-overhaul-5` on `feat/web-overhaul-5`; `.venv` and `web/node_modules` symlinked; `init_db()` ok; patch helper written; all 12 block hashes match the table; 22 GiB free | 2026-11-06 | none |
| **Section A entry** | done | (rides in Task 1's commit) | A1 clean at `7981584`; A2 `T1` applies; A3 baseline: pytest 5675 passed, 1 skipped; ruff clean; mypy 361 files clean; vitest 1531 in 149 files; tsc and lint clean | 2026-11-06 | none |
| **Task 1: size tier, tranche plan and Claude's note in the API** | done | `0a9ed58` | `T1` applied clean (hash c7b47420...). Red check: `tests/test_api_value.py` 28 failed, 16 passed with the three source files stashed, as the plan says. Targeted: 100 passed (test_api_value, test_api_value_lookup, test_value_fence, test_web_fence); `ruff format --check` 4 files already formatted; `ruff check .` clean; `mypy src` 361 files clean. Full pytest: 1 failed, 5702 passed, 1 skipped, the one failure `tests/test_openapi_current.py` as expected (Task 2 regenerates the contract) | 2026-11-06 | none. (The Section A entry row and the A0 row ride in this commit.) |
| **Task 2: the contract, regenerated** | done | `3323cb1` (Task 1 is `0a9ed58`) | Regenerated offline: `docs/web/openapi.json` +60, `web/lib/api-types.ts` +23 (83 insertions, no deletions), the added keys exactly as the step lists. Red: `tsc --noEmit` failed with the three expected errors (format.test.ts 17, ValueBlock.test.tsx 19 and 73). `T2` (hash a7852848...) applied clean; tsc clean; `vitest run features/stock-value` 35 passed; full vitest 1531 in 149 files; `npm run lint` clean; `ruff check .` clean; `mypy src` 361 files clean; full pytest 5703 passed, 1 skipped (`test_openapi_current` green); G1 prints nothing; G2 lists exactly the four expected files; G6 (web_fence, value_fence, eval_skills, openapi_current) 55 passed | 2026-11-06 | none |
| **Section A exit** | done | `3323cb1` | Verified by the orchestrator: two task commits over A0; vitest 1531 in 149 files; tsc clean; G1 empty; G2 the four files; fences/contract tests green; the subagent's full pytest 5703 passed + 1 skipped, ruff and mypy 361 clean; status clean | 2026-11-06 | none |
| **Section B entry** | done | (rides in Task 3's commit) | B1 two task commits; B2 T3-T6 apply; B3 no `web/features/stock`, no `valueLines`/`sizeSegment`/`trancheWords` | 2026-11-06 | none |
| **Task 3: `features/stock/stock.ts`** | done | `7bcb301` | da-vinci loaded (ratified DESIGN.md, sync OK; nothing visual in the task). All four B patches hash-match the table and `git apply --check` clean. `T3` (80b1879c...) applied clean: two new files. `stock.test.ts` 7 passed; full vitest 1538 in 150 files; `tsc --noEmit` clean; `npm run lint` clean. (The Section A exit and Section B entry rows ride in this commit.) | 2026-11-06 | none |
| **Task 4: the chart draws the value book's levels** | done | `f90f66a` | `T4` (f9642237...) applied clean: `M PriceChart.tsx`, `?? PriceChart.test.tsx`. Red check: with `PriceChart.tsx` stashed, `PriceChart.test.tsx` 3 failed; popped. Gate: 3 passed; full vitest 1541 in 151 files; tsc clean; lint clean. da-vinci contrast of the muted price-line labels (`--text-muted` on `--bg-background`, the paper the chart sits on): light `#575d55` on `#f2f4ef` 6.11 (AA), dark `#a3aa9f` on `#0f110f` 7.95 (AAA) | 2026-11-06 | none |
| **Task 5: the page frame** | done | `390ef33` | `T5` (9305fe95...) applied clean: `M DESIGN.md`, `M app/stock/[symbol]/page.tsx`, `D SectionShell.tsx`, `M ValueBlock.tsx`, three new `features/stock/` files. `vitest run features/stock features/stock-value` 47 passed; full vitest 1546 in 152 files; tsc clean; lint clean; G3 exit 0 (marker `updated=2026-11-06`); G5 no finding; no `SectionShell` left outside `node_modules`; G4 scratch build green on the first try (`ƒ /stock/[symbol]` 16.2 kB; the table lists 18 routes plus `/_not-found`, and `find web/app -name page.tsx -o -name route.ts` finds 18, so the plan's "19 routes plus `/_not-found`" counts `/_not-found` in the 19), scratch copy removed. da-vinci reviewed the frame against the spec and the Position page (same shell and grid classes): the spec's `gap-y-4` (Position uses `gap-y-5`) kept as specified | 2026-11-06 | none (da-vinci changed no spacing; the build could not be viewed in a browser here, the plan's rendered check was done on the prototype) |
| **Task 6: size tier and tranche plan in the value block** | done | (this commit; its hash is filled in by the orchestrator's follow-up, since a commit cannot contain its own hash) | `T6` (d11f27de...) applied clean: `SizeBlock.tsx`, `format.ts`, `format.test.ts`, `ValueBlock.test.tsx` all `M`. Red check: with `format.ts` and `SizeBlock.tsx` stashed, `vitest run features/stock-value` 3 failed, 35 passed; popped. Gate: 38 passed; full vitest 1549 in 152 files; tsc clean; lint clean; G1 prints nothing; G2 lists exactly the four expected files; G3 exit 0; G5 no finding. da-vinci: the two new lines (tranche line under the holding, size line under each entry ceiling) use the same `mt-1 text-sm` as their neighbours, so they sit in the block's rhythm; no change | 2026-11-06 | none |
| **Section B exit** | pending | | | | |
| **Section C entry** | pending | | | | |
| **Task 7: Checks** | pending | | | | |
| **Task 8: Technicals, Sentiment, News, statements** | pending | | | | |
| **Task 9: the model summary** | pending | | | | |
| **Section C exit** | pending | | | | |
| **Section D entry** | pending | | | | |
| **Task 10: docs** | pending | | | | |
| **Task 11: the da-vinci finish by a fresh reviewer** | pending | | | | |
| **Whole-branch review (opus)** | pending | | | | |
| **Review fix pass (sonnet)** | pending | | | | |
| **Merge, push, restart** | pending | | | | |

*(Rows are filled as each task lands; a ruling is any deviation from the task text, and why, with its cost if wrong.)*

## Roadmap (this plan is Part 5 of 8, HANDOFF section 5)

- **Parts 1-4** and the value book's web sections F-I: done and merged.
- **Part 5, The stock page.** This plan.
- **Part 6, Research, Universe and search** (L1, L3, S1, V7 card: `claude_note` shown, labelled as Claude's).
  **Part 7, News, More and How it works** (L4, L5, L6, S4, S5). **Part 8, The value record** (F5, V9), gated.
  **Order control** on its own track (spec first).

## Rulings made up front (the operator may overturn any of them)

**Scope:**

1. **Scope is the HANDOFF's Part 5 row**: L2, V6, V7 (backend only), S5 (the Stock paragraph). The Top
   opportunities card shows `claude_note` in Part 6, where its page is recomposed. "What changed since last time"
   stays without a field of its own (value book ruling G5: a held name's re-evaluations carry it). *Cost if wrong:
   one labelled line on `OpportunityCard` moves earlier.*

**The API (Section A):**

2. **The size tier is computed in the API, mirroring `src.value.sizing.tier_pct`**, because the value fence lets the
   API import only `scorecard` and `schemas` from `src.value`. `_size_pct` is six lines in
   `src/api/routers/value.py`; `test_the_size_tier_is_the_value_books_own_rule` compares it with the real function
   over 24 cases (two lists x twelve margins, including unknown, negative, each tier edge and above the cap), so a
   change to either side turns the suite red. *Cost if wrong: none; a drift is caught.*
3. **`size_pct` is for every list; the web shows it only for a priced verdict** (Ready, Watch, Wait). `null` when the
   effective margin of safety is unknown (never 0); `0.0` below the first tier ("the book would not buy"); capped at
   `name_cap_pct`. It is a share of the book's ceiling, not dollars: the ticker route does not read the account
   snapshot, and the ceiling halves under the trend brake. *Cost if wrong: a dollar figure needs the snapshot read
   that `GET /value/book` already does.*
4. **`claude_note` is Claude's own `why`**: the latest non-superseded `value_claude_verdicts` row for the name and
   list from the **CLI backend only** (a local model's verdict never decides and is not Claude's), whitespace
   collapsed to one line, at most 200 characters (cut at a word, ended with "…"; the longest stored `why` on
   2026-11-06 is 170). *Cost if wrong: a label that says Claude over a local model's words, prevented here.*
5. **The tranche plan is words over stored facts**: the API adds `tranches_done`, `last_tranche_on` (from
   `value_positions`) and the config's `tranches` and `tranche_min_sessions`; the web says what the next tranche
   waits for from the rule (`src/value/sizing.py::tranche_due`: the second on a higher low, any later one on a close
   above the 50-day average, at least `tranche_min_sessions` apart, each gated again). It does not say whether that
   condition is met today: that needs bars and the SMA the API does not read. *Cost if wrong: one boolean the value
   process would have to store.*

**The page (Section B):**

6. **Ink candles.** The HANDOFF (L2) keeps `PriceChart` and its candles, volume and averages; DESIGN.md keeps green
   and red for signed money. So a candle is ink, hollow on an up day and filled on a down day (direction by shape),
   volume is the perforation tone with no axis label, the 50-day average is a thin ink line and the 200-day a thin
   muted one, and a line of words under the chart names every series. The value levels are dashed muted price lines
   labelled on the axis, as the position page's strike line. *Cost if wrong: two colour options in `PriceChart`.*
7. **"Model summary", labelled by its model.** The research summary's backend can be Claude, Ollama or OpenAI
   (`src/research/summary/factory.py`), so the card is titled "Model summary" and its foot says "Written by
   <model>, a language model that decides nothing"; Claude's own words on the page stay in the value block, each
   labelled as Claude's. *Cost if wrong: a title.*
8. **The back link goes to Research**, the stock page's parent in the nav (`lib/nav.ts`: Research matches
   `/stock`). The browser's Back still returns wherever the operator came from. *Cost if wrong: one link.*
9. **The value block leads when the book has a view worth leading with** (`valueLeads`): a list with a priced verdict
   or shares held. Otherwise (every list No, a name it does not score, no file, an error) it sits at the foot of the
   left column. It is placed by the page reading `GET /value/{symbol}` under the block's own query key, so there is
   one fetch. *Cost if wrong: one condition.*
10. **The layout is the position page's grid**: content left, a 340 px column right from 1024 px, the DOM order the
    phone order. Left: chart, (value block), Checks, Technicals, Financial statements, (value block). Right: the news
    service's notes, News, Sentiment, Model summary. The chart sits on the paper, not in a card, as Position's.
    *Cost if wrong: a reorder.*
11. **Restyle in place** (HANDOFF ruling 2): `components/stock` and `components/checks` stay where they are; new code
    goes in `features/stock/`. `SectionShell` is deleted (its only caller is gone) and `StockSection` replaces it.
    *Cost: none.*
12. **The generated types meet the panels' hand types through a typed cast** (`ComponentProps<typeof X>["data"]`):
    the generated types mark a nullable field optional, the panels read it as a value or null, and the API always
    sends the key. No `any` is added; the panels' own types and tests do not change. *Cost if wrong: a later pass
    moves the panels onto the generated types.*
13. **The chart shows one year, no range chips and no pointer readout.** The bars endpoint is fixed at a year and the
    averages are aligned to it; the position page's chips slice closes only. *Cost if wrong: a later task.*
14. **The statements sit behind a closed disclosure** ("Revenue, profit, balance sheet and cash flow, as filed"):
    DESIGN.md's "everything secondary collapsed". *Cost: one tap.*
15. **Errors in words**: a 404 from `GET /research/{symbol}` reads "The research service does not know ZZZZ. Check the
    ticker, or add it to the watchlist on Research." and is not retried; any other failure reads "This page could
    not be loaded. It tries again when you reopen it."; a missing price is a hatched "Last price n/a". *Cost: copy.*

**The sections (Section C):**

16. **Words, not colours, on everything that is not money**: a check's state is a `StatusWord` (Fail in the flag
    tone), the ribbon fills a pass and outlines a fail in ink, a warning carries "Caution" (flag) or "Note"; headline
    tone is a neutral word; the sentiment change is signed but muted; bull and bear points are plain ink. A check row
    is two lines (the question with its word, then "Reads 24.10 · bar 22"), so a 320 px phone never squeezes the
    question into a column. `sentimentTint` stays exported for `features/position/Headlines.tsx` (untouched).
    *Cost if wrong: classes.*
17. **"Generate summary" becomes the secondary `Button`** (44 px; the Part 4 finish found it at 36 px). *Cost: none.*

**Standing rules:**

18. **Protected files are byte-identical to `main`** (G1), and **the command-site grep is unchanged** (G2).
19. **No new token, colour, font, radius or elevation.** The volume bars use the existing `--color-perforation`.
20. **Docs**: `web/DESIGN.md` (the Stock surface, the Value block and Top opportunities lines, a Decision Log entry,
    the marker date) lands with the page in Task 5; `STATUS.md`, `ARCHITECTURE.md`, `web/CLAUDE.md` and
    `docs/web/api.md` in Task 10. No config key, script, command kind or Telegram command is added, so `SETUP.md`,
    `README.md` and `docs/web/commands.md` do not change.
21. **Effort per section** follows the operator's 2026-11-06 instruction (medium for mechanical edits, high for UI and
    shared state). **Never build inside `web/`** (G4).

## Global Constraints

- Core invariant, the fences and the two written exceptions in root `CLAUDE.md` are untouched. Nothing here places,
  sizes, prices or gates anything; Claude's words stay labelled and never sit on a button.
- The API writes exactly one table (`app_commands`); `src/api/` imports from `src.value` only `scorecard` and
  `schemas`; only `src/api/value_db.py` opens value.db. `tests/test_web_fence.py`, `test_eval_skills.py`,
  `test_regime_fence.py`, `test_news_fence.py`, `test_spreads_fence.py`, `test_value_fence.py` and
  `test_wheel_spreads_isolation.py` stay green and unweakened.
- UI: tokens only (no raw palette class, no hex); `.tabular` on numbers; lime only on the primary act (this page has
  none); unknown is a hatched `n/a`, never `$0` or blank; no state by colour alone; no shadow; charts never animate
  in; 44 px phone targets; zero em dashes and none of "seamless", "robust", "unlock", "elevate" in UI copy.
- Gates run from the worktree root. Web: `cd web && npx vitest run && npx tsc --noEmit && npm run lint`. Python:
  `python -m pytest -q && ruff check . && mypy src`. `tests/test_scan_timeout.py` is a known flake: if it is the only
  failure, re-run it alone; green means "scan timeout flake" in the log. The repo is not prettier-formatted: never
  run `prettier --write` on a file.
- In a Bash call, `cd` does not persist and environment variables do not either: write `<S>` and `<W>` out as
  absolute paths in every command.

**Shared checks (referenced by every section exit):**

- **G1, protected files:** `git diff --stat main -- web/components/options/DecideControls.tsx web/components/options/ConfirmAction.tsx web/components/options/CommandReceipt.tsx web/components/options/HaltControl.tsx web/components/options/AutonomyControl.tsx web/components/options/RollModeControl.tsx web/lib/commands.ts web/lib/receipt.ts` prints nothing.
- **G2, command sites:** `grep -rln "submitCommand\|confirmCommand" web/features | sort` prints exactly
  `web/features/more/TargetCard.test.tsx`, `web/features/more/TargetCard.tsx`,
  `web/features/stock-value/AnalyseButton.test.tsx`, `web/features/stock-value/AnalyseButton.tsx`.
- **G3, design spec:** `python3 ~/.claude/skills/da-vinci/scripts/design_md_check.py web/DESIGN.md` exits 0.
- **G4, scratch build** (never inside `web/`; the `mktemp` + `rm -rf "$(dirname ...)"` form is refused by the
  sandbox, so use the scratchpad by literal path):
  `rm -rf <S>/p5/build && mkdir -p <S>/p5/build && rsync -a --exclude node_modules --exclude .next web/ <S>/p5/build/web/ && ln -s <W>/web/node_modules <S>/p5/build/web/node_modules`
  then `cd <S>/p5/build/web && npm run build`. Expect the route table with `ƒ /stock/[symbol]` among 19 routes plus
  `/_not-found`. If it fails with `Cannot read properties of null (reading '1')` in `next/font/google`, that is the
  known transient font fetch: run the build again, up to three tries. Then `rm <S>/p5/build/web/node_modules` and
  `rm -rf <S>/p5/build`.
- **G5, da-vinci lint:** `python3 ~/.claude/skills/da-vinci/scripts/lint.py web/features/stock web/features/stock-value web/components/stock web/components/checks web/app/stock`
  prints no line for a non-test file.
- **G6, fences:** `python -m pytest -q tests/test_web_fence.py tests/test_value_fence.py tests/test_eval_skills.py tests/test_openapi_current.py` passes.

**Extracting and applying a patch.** A0 extracts every block to `<S>/p5/<name>.out` and checks the hashes. A task
step "Check and apply `Tn`" means, from `<W>`:

```bash
git apply --check <S>/p5/Tn.out      # prints nothing; any error: stop and report it
git apply <S>/p5/Tn.out
```

If `<S>/p5/Tn.out` is missing (a new session), re-extract it first and check its hash:
`python3 <S>/p5/plan_block.py docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md Tn > <S>/p5/Tn.out && shasum -a 256 <S>/p5/Tn.out`
(the helper itself is written in A0; write it again from A0 if the scratchpad is new).

## Review Focus

1. **The size tier is the value book's rule, never a second opinion**: `_size_pct` equals `tier_pct` capped at the
   name cap in every parametrised case; unknown is `null`, never 0 → Task 1.
2. **Claude's note is Claude's**: only the CLI backend fills `claude_note`, never a superseded row, never a local
   model's → Task 1 `test_top_carries_claudes_one_line_note_from_the_cli_only`.
3. **The chart says what it draws**: every level in the `role="img"` sentence, no level without a number, two levels
   at one price share a line → Tasks 3, 4.
4. **One fetch, one decide-free page**: the page reads `["value","ticker",SYM]` like the block; it adds no command
   site (G2) and no write.
5. **Unknown is never none, and no colour carries a state**: hatched n/a in the quote, the checks, the technicals,
   the size line; no `text-gain`/`text-loss` outside money → Tasks 5-9.
6. **Nothing reaches the trading path**: G1, G2, G6 at every exit.

---

## File structure

```
docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md, the HANDOFF          COMMIT (A0, on main)
src/api/models/value.py            MODIFY  ValueTopItem.claude_note; ValueListOut.size_pct, tranches;
                                           ValuePlanOut.tranches_done, tranches, tranche_min_sessions, last_tranche_on   (T1)
src/api/routers/value.py           MODIFY  _one_line, _size_pct; wired into value_top, _list_out, _plan                  (T1)
src/api/value_db.py                MODIFY  read_top reads claude_why; read_positions reads the tranche columns             (T1)
tests/test_api_value.py            MODIFY  +28 (5 tests, one parametrised over 24 cases)                                  (T1)
docs/web/openapi.json, web/lib/api-types.ts   REGENERATE                                                                   (T2)
web/features/stock-value/format.test.ts, ValueBlock.test.tsx   MODIFY  typed fixtures gain the new keys (T2); new cases (T6)
web/features/stock/stock.ts (+ stock.test.ts)                   CREATE                                                    (T3)
web/components/stock/PriceChart.tsx                              REWRITE in place; PriceChart.test.tsx CREATE             (T4)
web/features/stock/StockSection.tsx, StockPage.tsx (+ StockPage.test.tsx)   CREATE                                        (T5)
web/app/stock/[symbol]/page.tsx                                  MODIFY  one mount                                        (T5)
web/components/stock/SectionShell.tsx                            DELETE                                                   (T5)
web/features/stock-value/ValueBlock.tsx                          MODIFY  no outer margin wrapper (it sits in a grid)       (T5)
web/DESIGN.md                                                    MODIFY  Stock surface, value lines, Decision Log, marker (T5)
web/features/stock-value/format.ts, SizeBlock.tsx                MODIFY  sizeSegment, trancheWords                         (T6)
web/components/checks/{ChecksSection,CheckRibbon,CheckRow}.tsx (+ 2 tests)   MODIFY                                       (T7)
web/components/stock/{TechnicalsPanel,SentimentPanel,NewsPanel,StatementsTable}.tsx (+ 3 tests)   MODIFY                   (T8)
web/components/stock/SummaryPanel.tsx (+ test)                   MODIFY                                                   (T9)
STATUS.md, ARCHITECTURE.md, web/CLAUDE.md, docs/web/api.md       MODIFY                                                   (T10)
```

---

## Section A: The API (Tasks 1-2) · model: sonnet (effort high)

**Reads:** this section; `src/api/routers/value.py` (lines 1-120, 270-330, 450-475); `src/api/models/value.py`;
`src/api/value_db.py` (lines 170-315); `src/value/sizing.py` (lines 1-60); `tests/test_api_value.py` (lines 1-140,
270-330).

**A0. Setup (orchestrator, before the entry checks).**

- [ ] In the main checkout (`/Users/ianlim/Desktop/IBKR Investments`, on `main`): `git status --short` shows only
  ` M docs/superpowers/plans/2026-11-05-web-overhaul-HANDOFF.md`, `?? docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md`
  and `?? data/value_filing_reads.json` (a runtime file: leave it alone). Commit the two docs:
  `git add docs/superpowers/plans/2026-11-05-web-overhaul-HANDOFF.md docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md`
  then `git commit -m "docs(plan): web overhaul Part 5 plan and the updated handoff"` (with the session's attribution
  lines). `git log --oneline -2` shows it over `6347dd9` (if `main` moved past `6347dd9`, stop and ask: the patches
  were cut against it).
- [ ] `df -h .` shows at least 10 GiB free (22 GiB at 95% on 2026-11-06). Below that, stop and ask.
- [ ] Create the worktree, one command per call:
  `git worktree add .claude/worktrees/web-overhaul-5 -b feat/web-overhaul-5 main`;
  `ln -s "/Users/ianlim/Desktop/IBKR Investments/.venv" "/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/web-overhaul-5/.venv"`;
  `ln -s "/Users/ianlim/Desktop/IBKR Investments/web/node_modules" "/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/web-overhaul-5/web/node_modules"`;
  then from the worktree root
  `IBKR_CONFIG_USE_EXAMPLES=1 .venv/bin/python -c "from src.storage.db import init_db; init_db()"`.
  `<W>` = `/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/web-overhaul-5`.
- [ ] Write the patch helper (`<S>` = this session's scratchpad, absolute):

```bash
mkdir -p <S>/p5 && cat > <S>/p5/plan_block.py <<'PY'
"""Print one fenced block of the web overhaul Part 5 plan, found by its marker comment.

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

- [ ] From `<W>`, extract all ten patches and the two other blocks, and check every hash against the table:
  `for b in T1 T2 T3 T4 T5 T6 T7 T8 T9 T10 mock5 capture5; do python3 <S>/p5/plan_block.py docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md $b > <S>/p5/$b.out; done; shasum -a 256 <S>/p5/*.out`
  Every line matches the table. Any mismatch: stop.
- [ ] Record A0 in the Progress log (commit hash, worktree path, hashes OK) in Task 1's commit.

**Entry checks:**

- [ ] **A1. Starting point.** In `<W>`: `git log --oneline -2` shows the A0 commit over `6347dd9`; `git status --short`
  is empty.
- [ ] **A2. Both patches apply.** `git apply --check <S>/p5/T1.out` prints nothing. (T2's patch is checked after the
  regeneration in Task 2, which it sits on.)
- [ ] **A3. Baseline green.** `python -m pytest -q && ruff check . && mypy src`;
  `cd web && npx vitest run && npx tsc --noEmit && npm run lint`. Expected on 2026-11-06: pytest **5675 passed, 1
  skipped**; mypy **361 files**; vitest **1531 in 149 files**. Record the counts.

**Section exit:** two task commits after A0; pytest 5703 passed + 1 skipped; vitest 1531 in 149 files; tsc, lint,
ruff, mypy clean; G1, G2, G6; `git status --short` clean.

### Task 1: Size tier, tranche plan and Claude's note in the API

**Files:** Modify `src/api/models/value.py`, `src/api/routers/value.py`, `src/api/value_db.py`,
`tests/test_api_value.py`, this plan (Progress log).

**What it does:** `ValueListOut` gains `size_pct` (rulings 2-3) and `tranches`; `ValuePlanOut` gains
`tranches_done`, `tranches`, `tranche_min_sessions`, `last_tranche_on` (ruling 5); `ValueTopItem` gains
`claude_note` (ruling 4). Five tests: the note (CLI only, one line, superseded and local rows ignored, a long `why`
cut at a word under 200 characters), the size tier on a list, an unknown margin is `null`, the parity with
`tier_pct` (24 cases), a held name's tranche fields.

- [x] **Step 1: Check and apply `T1`.** `git status --short` shows exactly the four files above as `M`.
- [x] **Step 2: Red check.** `git stash push -- src/api/models/value.py src/api/routers/value.py src/api/value_db.py`,
  then `IBKR_CONFIG_USE_EXAMPLES=1 python -m pytest -q tests/test_api_value.py` ends `28 failed, 16 passed`, then
  `git stash pop` (the three files come back; `git status --short` shows the four `M` files again).
- [x] **Step 3: Targeted gate.** `IBKR_CONFIG_USE_EXAMPLES=1 python -m pytest -q tests/test_api_value.py tests/test_api_value_lookup.py tests/test_value_fence.py tests/test_web_fence.py`
  passes; `ruff format --check src/api/models/value.py src/api/routers/value.py src/api/value_db.py tests/test_api_value.py`
  prints `4 files already formatted`; `ruff check .` clean; `mypy src` 361 files clean.
- [x] **Step 4: Full gate.** `python -m pytest -q`: **1 failed, 5702 passed, 1 skipped**, the one failure being
  `tests/test_openapi_current.py` (the committed contract does not name the new fields until Task 2 regenerates it;
  checked in the prototype). Any other failure: stop.
- [x] **Step 5: Commit** `feat(api): the value book's size tier, tranche plan and Claude's note, read-only` with the
  Progress log row (and the A0 row).

<!-- block T1 -->
````diff
diff --git a/src/api/models/value.py b/src/api/models/value.py
index 9cf2b49..f846f67 100644
--- a/src/api/models/value.py
+++ b/src/api/models/value.py
@@ -38,6 +38,10 @@ class ValueTopItem(BaseModel):
     reasons: list[str] = Field(default_factory=list)
     put_ceiling: float | None = None  # the wheel's value-suggested put ceiling
     age_days: int | None = None
+    # Claude's own why for this list, as one line (value_claude_verdicts, the CLI backend only: a
+    # local model's verdict never decides and is not Claude's). Labelled as Claude's on the web,
+    # never on a button. None when Claude has not read the name for this list.
+    claude_note: str | None = None
 
 
 class ValueTopResponse(Envelope):
@@ -155,6 +159,11 @@ class ValueListOut(BaseModel):
     mos_review: bool = False
     methods: list[ValueMethodOut] = Field(default_factory=list)
     gates: list[ValueGateOut] = Field(default_factory=list)  # this list's entry and timing checks
+    # The size tier the effective margin of safety reaches (value.book.tiers, spec section 9.5), in
+    # percent of the book's ceiling and capped at the name cap: 0.0 below the first tier, None when
+    # the margin is unknown (never 0). A buy aims at it in ``tranches`` steps.
+    size_pct: float | None = None
+    tranches: int = 3  # value.book.tranches
 
 
 class ValueFileOut(BaseModel):
@@ -249,6 +258,10 @@ class ValuePlanOut(BaseModel):
     half_sold: bool = False
     fair_value: float | None = None
     effective_fair_value: float | None = None
+    tranches_done: int | None = None  # how many of the tranches have been bought
+    tranches: int = 3  # value.book.tranches
+    tranche_min_sessions: int = 5  # value.book.tranche_min_sessions: sessions between two
+    last_tranche_on: date | None = None
 
 
 class ValueTickerResponse(Envelope):
diff --git a/src/api/routers/value.py b/src/api/routers/value.py
index 38ef918..d7b5109 100644
--- a/src/api/routers/value.py
+++ b/src/api/routers/value.py
@@ -50,6 +50,7 @@ router = APIRouter(prefix="/value", tags=["value"])
 _DEEP_FINANCIAL = ("bank", "insurer")
 _NOTE_KINDS = ("profile", "why_cheap", "thesis", "bear_case")
 _PRICED = ("READY", "WATCH", "WAIT")
+_NOTE_MAX = 200  # characters of Claude's why a Top opportunities card carries
 
 
 def _now() -> datetime:
@@ -61,6 +62,35 @@ def _next_exit_out(raw: dict[str, Any] | None) -> ValueNextExit | None:
     return None if raw is None else ValueNextExit(kind=raw["kind"], level=raw["level"])
 
 
+def _one_line(text: Any) -> str | None:
+    """Claude's why as one line for a card: whitespace collapsed, at most ``_NOTE_MAX``
+    characters (cut at a word, ended with an ellipsis); None when there is none."""
+    if not isinstance(text, str):
+        return None
+    line = " ".join(text.split())
+    if not line:
+        return None
+    if len(line) <= _NOTE_MAX:
+        return line
+    return line[: _NOTE_MAX - 1].rsplit(" ", 1)[0] + "\u2026"
+
+
+def _size_pct(list_name: str, mos: float | None) -> float | None:
+    """The size tier the margin of safety (a fraction) reaches, in percent of the book's ceiling:
+    the highest ``value.book.tiers`` row it reaches, capped at ``name_cap_pct``; 0.0 below the
+    first row; None when the margin is unknown, never 0. The rule of
+    ``src.value.sizing.tier_pct``, which the API may not import (the value fence);
+    ``tests/test_api_value.py`` holds the two equal."""
+    if mos is None:
+        return None
+    book = get_config().value.book
+    size = 0.0
+    for start, pct in getattr(book.tiers, list_name):
+        if mos * 100.0 >= start:
+            size = pct
+    return min(size, book.name_cap_pct)
+
+
 def _position_out(p: dict[str, Any]) -> ValuePositionOut:
     return ValuePositionOut(
         id=p["id"],
@@ -109,6 +139,7 @@ def value_top(
             reasons=r["reasons"],
             put_ceiling=r["put_ceiling"],
             age_days=vdb.age_days(vdb.day(r["as_of"]), now),
+            claude_note=_one_line(r["claude_why"]),
         )
         for r in rows
     ]
@@ -305,6 +336,7 @@ def _list_out(
     if ev is None:
         return None
     baseline = card.verdict_for(name)
+    mos = eff["margin_of_safety"] if eff else ev.margin_of_safety
     return ValueListOut(
         list_name=name,
         baseline_verdict=baseline,
@@ -312,7 +344,7 @@ def _list_out(
         decided_by="claude" if eff and eff["decided_by"] == "claude" else "python",
         fair_value=ev.fair_value,
         effective_fair_value=eff["fair_value"] if eff else ev.fair_value,
-        mos=eff["margin_of_safety"] if eff else ev.margin_of_safety,
+        mos=mos,
         required_mos_pct=ev.required_mos_pct,
         entry_ceiling=eff["entry_ceiling"] if eff else ev.entry_ceiling,
         entry=ev.entry,
@@ -324,6 +356,8 @@ def _list_out(
             *(_gate(c, "entry") for c in ev.entry_checks),
             *(_gate(c, "timing") for c in ev.timing_checks),
         ],
+        size_pct=_size_pct(name, mos),
+        tranches=get_config().value.book.tranches,
     )
 
 
@@ -487,6 +521,7 @@ def _plan(session: Any, symbol: str) -> ValuePlanOut | None:
     p = held[0]
     plan = vdb.jsonish(p["plan_json"], {})
     plan = plan if isinstance(plan, dict) else {}
+    book = get_config().value.book
     return ValuePlanOut(
         position_id=p["id"],
         list_name=p["list_name"],
@@ -498,6 +533,10 @@ def _plan(session: Any, symbol: str) -> ValuePlanOut | None:
         half_sold=bool(plan.get("half_sold")),
         fair_value=plan.get("fair_value"),
         effective_fair_value=plan.get("effective_fair_value"),
+        tranches_done=p["tranches_done"],
+        tranches=book.tranches,
+        tranche_min_sessions=book.tranche_min_sessions,
+        last_tranche_on=p["last_tranche_on"],
     )
 
 
diff --git a/src/api/value_db.py b/src/api/value_db.py
index 673ecbd..22a420c 100644
--- a/src/api/value_db.py
+++ b/src/api/value_db.py
@@ -184,7 +184,10 @@ def read_top(session: Session, list_name: str, limit: int = 10) -> list[dict] |
         "e.verdict, e.decided_by, e.fair_value, e.entry_ceiling, e.margin_of_safety, "
         "(SELECT MAX(x.entry_ceiling) FROM value_effective x WHERE x.symbol = t.symbol "
         " AND x.verdict IN ('READY', 'WATCH', 'WAIT') AND x.entry_ceiling IS NOT NULL) "
-        "AS put_ceiling "
+        "AS put_ceiling, "
+        "(SELECT v.why FROM value_claude_verdicts v WHERE v.symbol = t.symbol "
+        " AND v.list_name = :list AND v.superseded = 0 AND v.backend = 'cli' "
+        " ORDER BY v.id DESC LIMIT 1) AS claude_why "
         "FROM value_ticker_files t JOIN value_effective e "
         "ON e.symbol = t.symbol AND e.list_name = :list "
         "WHERE t.universe = 'trading' AND e.verdict IN ('READY', 'WATCH', 'WAIT') "
@@ -248,7 +251,8 @@ def read_positions(session: Session, status: str) -> list[dict] | None:
     realised dollars (None until a sale has filled), newest first."""
     positions = _rows(
         session,
-        "SELECT id, symbol, list_name, status, opened_on, closed_on, plan_json, decided_by "
+        "SELECT id, symbol, list_name, status, opened_on, closed_on, plan_json, decided_by, "
+        "tranches_done, last_tranche_on "
         "FROM value_positions WHERE status = :s ORDER BY id DESC",
         {"s": status},
     )
@@ -306,6 +310,8 @@ def read_positions(session: Session, status: str) -> list[dict] | None:
                 "realised_usd": realised if sold > 0 else None,
                 "decided_by": str(p["decided_by"] or "python"),
                 "plan_json": p["plan_json"],
+                "tranches_done": None if p["tranches_done"] is None else int(p["tranches_done"]),
+                "last_tranche_on": day(p["last_tranche_on"]),
             }
         )
     return out
diff --git a/tests/test_api_value.py b/tests/test_api_value.py
index 8e8fd2b..8301084 100644
--- a/tests/test_api_value.py
+++ b/tests/test_api_value.py
@@ -495,3 +495,94 @@ def test_a_re_entry_starts_the_average_cost_again(value_book_db) -> None:
         fills = vdb.read_fills(s)
     assert fills is not None
     assert [f["realised_usd"] for f in fills] == [None, 1000.0, None, 1000.0]
+
+
+# --- web overhaul Part 5: the size tier, the tranche plan, Claude's one-line note ----------------
+
+
+def _seed_why(symbol: str, why: str, *, backend: str = "cli", superseded: bool = False) -> None:
+    with value_session() as s:
+        s.add(
+            ValueClaudeVerdictRow(
+                read_id=1,
+                symbol=symbol,
+                list_name="deep_value",
+                verdict="READY",
+                why=why,
+                drivers_json="{}",
+                clamps_json="[]",
+                fair_value=150.0,
+                python_fair_value=140.0,
+                clamp_bound=False,
+                fingerprint_key="k" * 16,
+                backend=backend,
+                created_at=NOW,
+                superseded=superseded,
+            )
+        )
+
+
+def test_top_carries_claudes_one_line_note_from_the_cli_only(client, vdb_file) -> None:
+    for sym in ("CLI", "LOCAL", "NONE", "LONG", "OLD"):
+        _seed_file(sym)
+    _seed_why("CLI", "Cheap on free cash flow,\n  below the ceiling.")
+    _seed_why("LOCAL", "A local model wrote this.", backend="ollama")
+    _seed_why("LONG", "word " * 60)
+    _seed_why("OLD", "An older read.", superseded=True)
+    items = {
+        i["symbol"]: i
+        for i in client.get("/value/top?list=deep_value", headers=OWNER).json()["items"]
+    }
+    assert items["CLI"]["claude_note"] == "Cheap on free cash flow, below the ceiling."
+    assert items["LOCAL"]["claude_note"] is None  # not Claude's: never labelled as Claude's
+    assert items["NONE"]["claude_note"] is None
+    assert items["OLD"]["claude_note"] is None
+    long = items["LONG"]["claude_note"]
+    assert len(long) <= 200 and long.endswith("…") and not long.endswith(" …")
+
+
+def test_ticker_lists_carry_the_size_tier_and_the_tranche_count(client, vdb_file) -> None:
+    _seed_file(
+        "GOOGL"
+    )  # effective margin of safety 0.3; deep_value tiers 25 -> 3, 35 -> 5, 45 -> 8
+    deep = client.get("/value/GOOGL", headers=OWNER).json()["file"]["lists"][0]
+    assert deep["size_pct"] == 3.0 and deep["tranches"] == 3
+
+
+def test_an_unknown_margin_has_no_size_never_zero(client, vdb_file) -> None:
+    _seed_file("GOOGL")
+    with value_session() as s:
+        row = s.query(ValueEffectiveRow).filter_by(symbol="GOOGL").one()
+        row.margin_of_safety = None
+    deep = client.get("/value/GOOGL", headers=OWNER).json()["file"]["lists"][0]
+    assert deep["size_pct"] is None
+
+
+@pytest.mark.parametrize("list_name", ["deep_value", "quality_growth"])
+@pytest.mark.parametrize(
+    "mos", [None, -0.2, 0.0, 0.09, 0.1, 0.249, 0.25, 0.3, 0.35, 0.44, 0.45, 0.9]
+)
+def test_the_size_tier_is_the_value_books_own_rule(list_name, mos) -> None:
+    from src.api.routers.value import _size_pct
+    from src.common.config import get_config
+    from src.value.sizing import tier_pct
+
+    book = get_config().value.book
+    expected = (
+        None
+        if mos is None
+        else min(tier_pct(mos * 100.0, getattr(book.tiers, list_name)), book.name_cap_pct)
+    )
+    assert _size_pct(list_name, mos) == expected
+
+
+def test_a_held_names_plan_carries_its_tranches(client, vdb_file) -> None:
+    _seed_file("GOOGL")
+    _seed_position("GOOGL", status="open", sells=False)
+    with value_session() as s:
+        pos = s.query(ValuePositionRow).filter_by(symbol="GOOGL").one()
+        pos.tranches_done = 1
+        pos.last_tranche_on = date(2026, 10, 20)
+    plan = client.get("/value/GOOGL", headers=OWNER).json()["plan"]
+    assert plan["tranches_done"] == 1 and plan["tranches"] == 3
+    assert plan["tranche_min_sessions"] == 5 and plan["last_tranche_on"] == "2026-10-20"
````

### Task 2: The contract, regenerated

**Files:** Regenerate `docs/web/openapi.json`, `web/lib/api-types.ts`; modify `web/features/stock-value/format.test.ts`,
`web/features/stock-value/ValueBlock.test.tsx` (typed fixtures only); this plan.

- [x] **Step 1: Regenerate offline** (from `<W>`):
  `IBKR_CONFIG_USE_EXAMPLES=1 python -c "import json; from src.api.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json`
  then `cd web && npx openapi-typescript ../docs/web/openapi.json -o lib/api-types.ts`.
  `git diff --stat` shows `docs/web/openapi.json | 60 +` and `web/lib/api-types.ts | 23 +` (83 insertions, no
  deletions). `git diff web/lib/api-types.ts | grep '^+ ' ` lists exactly these keys: `size_pct?: number | null`,
  `tranches: number` (twice), `tranches_done?: number | null`, `tranche_min_sessions: number`,
  `last_tranche_on?: string | null`, `claude_note?: string | null`.
- [x] **Step 2: Red.** `cd web && npx tsc --noEmit` fails with three errors: `features/stock-value/format.test.ts(17,...)`
  and `features/stock-value/ValueBlock.test.tsx(19,...)` and `(73,...)` (the new keys are required in the generated
  types because the API declares them with a default).
- [x] **Step 3: Check and apply `T2`.** It adds the keys to the two typed fixtures.
- [x] **Step 4: Gate.** `npx tsc --noEmit` clean; `npx vitest run features/stock-value` 35 passed; full vitest
  **1531 in 149 files**; `npm run lint` clean; from `<W>`, `python -m pytest -q`: **5703 passed, 1 skipped**
  (`test_openapi_current` green now); G1, G2, G6.
- [x] **Step 5: Commit** `chore(api): regenerate the contract for the value book's size, tranches and note`.

<!-- block T2 -->
````diff
diff --git a/web/features/stock-value/ValueBlock.test.tsx b/web/features/stock-value/ValueBlock.test.tsx
index 113b885..262cbd8 100644
--- a/web/features/stock-value/ValueBlock.test.tsx
+++ b/web/features/stock-value/ValueBlock.test.tsx
@@ -29,7 +29,7 @@ function ticker(over: Partial<ValueTicker> = {}): ValueTicker {
         {
           list_name: "deep_value", baseline_verdict: "WAIT", verdict: "READY", decided_by: "claude",
           fair_value: 200, effective_fair_value: 215, mos: 0.151, required_mos_pct: 30, entry_ceiling: 190,
-          entry: "pass", timing: "fail", reasons: ["timing_not_ready"], mos_review: false,
+          entry: "pass", timing: "fail", reasons: ["timing_not_ready"], mos_review: false, size_pct: 3, tranches: 3,
           methods: [
             { method: "B", value: 210, state: "ok", detail: "", used: true, median: true },
             { method: "A", value: 190, state: "ok", detail: "", used: true, median: false },
@@ -40,7 +40,8 @@ function ticker(over: Partial<ValueTicker> = {}): ValueTicker {
         {
           list_name: "quality_growth", baseline_verdict: "NO", verdict: "NO", decided_by: "python",
           fair_value: null, effective_fair_value: null, mos: null, required_mos_pct: 25, entry_ceiling: null,
-          entry: "fail", timing: "unknown", reasons: [], mos_review: false, methods: [], gates: [],
+          entry: "fail", timing: "unknown", reasons: [], mos_review: false, methods: [], gates: [], size_pct: null,
+          tranches: 3,
         },
       ],
       metrics: {}, adjustments: [],
@@ -72,7 +73,8 @@ function ticker(over: Partial<ValueTicker> = {}): ValueTicker {
     ],
     plan: {
       position_id: 1, list_name: "deep_value", shares: 20, avg_cost: 150, next_exit: { kind: "sell_half", level: 215 },
-      stop: 140, half_sold: false, fair_value: 200, effective_fair_value: 215,
+      stop: 140, half_sold: false, fair_value: 200, effective_fair_value: 215, tranches_done: 1, tranches: 3,
+      tranche_min_sessions: 5, last_tranche_on: "2026-10-20",
     },
     ...over,
   };
diff --git a/web/features/stock-value/format.test.ts b/web/features/stock-value/format.test.ts
index b6d568f..01af8df 100644
--- a/web/features/stock-value/format.test.ts
+++ b/web/features/stock-value/format.test.ts
@@ -16,7 +16,8 @@ import type { ValuePlan, ValueTicker } from "./types";
 
 const plan = (over: Partial<ValuePlan> = {}): ValuePlan => ({
   position_id: 1, list_name: "deep_value", shares: 20, avg_cost: 150, next_exit: null, stop: 140,
-  half_sold: false, fair_value: 200, effective_fair_value: 210, ...over,
+  half_sold: false, fair_value: 200, effective_fair_value: 210, tranches_done: 1, tranches: 3, tranche_min_sessions: 5,
+  last_tranche_on: "2026-10-20", ...over,
 });
 
 const ticker = (over: Partial<ValueTicker> = {}): ValueTicker => ({
````

---

## Section B: The stock page (Tasks 3-6) · model: sonnet (effort high)

**Reads:** this section; `web/DESIGN.md` (Overview, Colors, Layout, Components: Card, Disclosure, StatusWord,
Buttons; Surfaces: Position, Research; the new Stock paragraph is in T5's patch); `web/app/stock/[symbol]/page.tsx`;
`web/components/stock/PriceChart.tsx`; `web/features/position/PositionPage.tsx` (lines 1-40, 150-200, the frame this
page copies); `web/features/position/UnderlyingChart.tsx` (the chart pattern); `web/features/stock-value/ValueBlock.tsx`,
`SizeBlock.tsx`, `format.ts`.

**Spec for da-vinci (give it this, so it has little to decide):** the Stock surface paragraph in T5's DESIGN.md hunk
is the spec. Layout and classes are fixed by the patches: the frame `mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4`;
the back link `min-h-11 text-[0.8125rem] font-semibold text-muted` with `ChevronLeft` 16; the title
`text-2xl font-extrabold tracking-[-0.015em]`; the price `tabular text-[1.5rem] font-extrabold`; the grid
`mt-4 grid items-start gap-x-6 gap-y-4 lg:grid-cols-[minmax(0,1fr)_340px]`; each section a `Card` with an `h2`
`text-[1.0625rem] font-bold`; the chart 280 px tall on the paper. da-vinci may tune spacing inside those (a gap, a
margin) and must record each change as a ruling; it may not add a token, colour, font, radius, shadow or lime, change
copy, or move a section (rulings 9-10).

**Entry checks:**

- [ ] **B1. Section A landed.** `git log --oneline main..HEAD` shows the two task commits (plus no stray); vitest 1531
  in 149 files at the last gate.
- [ ] **B2. Every patch of the section applies on the tree as it is** (they touch disjoint files):
  `git apply --check <S>/p5/T3.out`, `T4.out`, `T5.out`, `T6.out`: each prints nothing.
- [ ] **B3. Nothing already named what B adds.** `ls web/features/stock` fails (no such directory);
  `grep -rn "valueLines\|sizeSegment\|trancheWords" web/` prints nothing.

**Section exit:** four task commits; vitest **1549 in 152 files**; tsc, lint clean; G1, G2, G3, G4, G5; the Stock
paragraph is in `web/DESIGN.md` and its marker reads `updated=2026-11-06`.

### Task 3: `features/stock/stock.ts`

**Files:** Create `web/features/stock/stock.ts`, `web/features/stock/stock.test.ts`; this plan.

**What it does:** three pure helpers. `valueLeads(t)` (ruling 9); `valueLines(t)`: per priced list its effective
fair value and entry ceiling, for a held name the half sale (the plan's fair value until it is made) and the stop,
merged when two levels share a price ("Fair value, Half sale $215.00"), each list named when two are priced;
`nameLine(a)` ("Alphabet Inc. · NASDAQ · ETF"); and the `Analysis` alias over the generated `AnalysisResponse`.

- [x] **Step 1: da-vinci** (it reads the spec above; nothing visual in this task beyond the label words, which are
  fixed).
- [x] **Step 2: Check and apply `T3`.** `git status --short` shows the two new files.
- [x] **Step 3: Gate.** `cd web && npx vitest run features/stock/stock.test.ts`: 7 passed. Full vitest **1538 in 150
  files**; tsc, lint clean.
- [x] **Step 4: Commit** `feat(web): the stock page's helpers: where the value block goes and the levels it draws`.

<!-- block T3 -->
````diff
diff --git a/web/features/stock/stock.test.ts b/web/features/stock/stock.test.ts
new file mode 100644
index 0000000..a9791f1
--- /dev/null
+++ b/web/features/stock/stock.test.ts
@@ -0,0 +1,85 @@
+import { describe, expect, it } from "vitest";
+import type { ValueList, ValuePlan, ValueTicker } from "@/features/stock-value/types";
+import { nameLine, valueLeads, valueLines } from "./stock";
+
+const list = (over: Partial<ValueList> = {}): ValueList => ({
+  list_name: "deep_value", baseline_verdict: "READY", verdict: "READY", decided_by: "python",
+  fair_value: 200, effective_fair_value: 215, mos: 0.15, required_mos_pct: 30, entry_ceiling: 190,
+  entry: "pass", timing: "pass", reasons: [], mos_review: false, methods: [], gates: [],
+  size_pct: 3, tranches: 3, ...over,
+});
+
+const plan = (over: Partial<ValuePlan> = {}): ValuePlan => ({
+  position_id: 1, list_name: "deep_value", shares: 20, avg_cost: 150, next_exit: null, stop: null,
+  half_sold: false, fair_value: 200, effective_fair_value: 215, tranches_done: 1, tranches: 3,
+  tranche_min_sessions: 5, last_tranche_on: "2026-11-02", ...over,
+});
+
+const ticker = (lists: ValueList[], over: Partial<ValueTicker> = {}): ValueTicker => ({
+  as_of: "2026-11-05T15:00:00Z", available: true, symbol: "GOOGL", computed: "stored", age_days: 1,
+  file: {
+    symbol: "GOOGL", as_of: "2026-11-04", company_class: "operating", data_quality: "pass", health: "pass",
+    ruleset_version: "v4", ruleset_hash: "be30d1eaa915", lists,
+  },
+  plan: null,
+  ...over,
+});
+
+describe("valueLeads", () => {
+  it("leads with the value block for a priced list or a held name", () => {
+    expect(valueLeads(ticker([list({ verdict: "WAIT" })]))).toBe(true);
+    expect(valueLeads(ticker([list({ verdict: "NO" })], { plan: plan() }))).toBe(true);
+  });
+  it("does not lead for every list No, a name it does not score, no file, or no answer", () => {
+    expect(valueLeads(ticker([list({ verdict: "NO" })]))).toBe(false);
+    const na = ticker([list()]);
+    na.file!.not_applicable_reason = "a fund";
+    expect(valueLeads(na)).toBe(false);
+    expect(valueLeads(ticker([], { available: false, file: null }))).toBe(false);
+    expect(valueLeads(undefined)).toBe(false);
+  });
+});
+
+describe("valueLines", () => {
+  it("draws fair value and the entry ceiling of a priced list", () => {
+    expect(valueLines(ticker([list()]))).toEqual([
+      { price: 215, title: "Fair value $215.00" },
+      { price: 190, title: "Entry ceiling $190.00" },
+    ]);
+  });
+  it("shares one line when the half sale sits at fair value, and draws a stop once there is one", () => {
+    expect(valueLines(ticker([list()], { plan: plan({ stop: 140 }) }))).toEqual([
+      { price: 215, title: "Fair value, Half sale $215.00" },
+      { price: 190, title: "Entry ceiling $190.00" },
+      { price: 140, title: "Stop $140.00" },
+    ]);
+  });
+  it("draws no half sale once it is made, and no level it has no number for", () => {
+    expect(
+      valueLines(ticker([list({ effective_fair_value: null, entry_ceiling: null })], { plan: plan({ half_sold: true }) })),
+    ).toEqual([]);
+  });
+  it("names the list when two lists are priced, and draws nothing for a No list", () => {
+    const lines = valueLines(
+      ticker([
+        list(),
+        list({ list_name: "quality_growth", effective_fair_value: 230, entry_ceiling: 200 }),
+      ]),
+    );
+    expect(lines.map((l) => l.title)).toEqual([
+      "Fair value (Deep value) $215.00",
+      "Entry ceiling (Deep value) $190.00",
+      "Fair value (Quality growth) $230.00",
+      "Entry ceiling (Quality growth) $200.00",
+    ]);
+    expect(valueLines(ticker([list({ verdict: "NO" })]))).toEqual([]);
+  });
+});
+
+describe("nameLine", () => {
+  it("joins the name, the exchange and ETF with middle dots", () => {
+    expect(nameLine({ name: "SPDR Gold", exchange: "NYSE", is_etf: true })).toBe("SPDR Gold · NYSE · ETF");
+    expect(nameLine({ name: "Alphabet Inc.", exchange: null, is_etf: false })).toBe("Alphabet Inc.");
+    expect(nameLine(undefined)).toBe("");
+  });
+});
diff --git a/web/features/stock/stock.ts b/web/features/stock/stock.ts
new file mode 100644
index 0000000..914ab26
--- /dev/null
+++ b/web/features/stock/stock.ts
@@ -0,0 +1,62 @@
+import { listWords, price } from "@/components/value/format";
+import type { components } from "@/lib/api-types";
+import type { ValueTicker } from "@/features/stock-value/types";
+
+/** The stock page's read of `GET /research/{symbol}` (src/api/models/research.py). */
+export type Analysis = components["schemas"]["AnalysisResponse"];
+
+/** A level drawn across the price chart as a dashed rule, with its label on the price axis. */
+export type ChartLine = { price: number; title: string };
+
+const PRICED = new Set(["READY", "WATCH", "WAIT"]);
+
+/**
+ * Whether the value book has a view of this name worth leading with: a list the book would buy at a
+ * price (Ready, Watch or Wait), or shares it holds. Anything else (no file, a name it does not score,
+ * every list No) puts the value block at the foot of the page instead.
+ */
+export function valueLeads(t: ValueTicker | undefined): boolean {
+  if (!t?.available || !t.file || t.file.not_applicable_reason) return false;
+  if (t.plan) return true;
+  return (t.file.lists ?? []).some((l) => PRICED.has(l.verdict));
+}
+
+/**
+ * The value book's levels for the chart (web overhaul Part 5, HANDOFF V6): per priced list its fair
+ * value (the effective one) and entry ceiling; for a held name the half sale (at the plan's fair value,
+ * until it is made) and the stop. A level with no number is not drawn; two levels at the same price
+ * share one line and one label. With two priced lists each label names its list.
+ */
+export function valueLines(t: ValueTicker | undefined): ChartLine[] {
+  if (!t?.available || !t.file || t.file.not_applicable_reason) return [];
+  const priced = (t.file.lists ?? []).filter((l) => PRICED.has(l.verdict));
+  const both = priced.length > 1;
+  const raw: ChartLine[] = [];
+  for (const l of priced) {
+    const suffix = both ? ` (${listWords(l.list_name)})` : "";
+    if (l.effective_fair_value != null) raw.push({ price: l.effective_fair_value, title: `Fair value${suffix}` });
+    if (l.entry_ceiling != null) raw.push({ price: l.entry_ceiling, title: `Entry ceiling${suffix}` });
+  }
+  const plan = t.plan;
+  if (plan) {
+    const target = plan.effective_fair_value ?? plan.fair_value;
+    if (!plan.half_sold && target != null) raw.push({ price: target, title: "Half sale" });
+    if (plan.stop != null) raw.push({ price: plan.stop, title: "Stop" });
+  }
+  const merged: ChartLine[] = [];
+  for (const line of raw) {
+    const same = merged.find((m) => Math.abs(m.price - line.price) < 0.005);
+    if (same) {
+      if (!same.title.split(", ").includes(line.title)) same.title = `${same.title}, ${line.title}`;
+    } else {
+      merged.push({ ...line });
+    }
+  }
+  return merged.map((m) => ({ price: m.price, title: `${m.title} ${price(m.price)}` }));
+}
+
+/** "Alphabet Inc. · NASDAQ · ETF": the name line under the ticker. Empty while loading. */
+export function nameLine(a: Pick<Analysis, "name" | "exchange" | "is_etf"> | undefined): string {
+  if (!a) return "";
+  return [a.name, a.exchange ?? null, a.is_etf ? "ETF" : null].filter((x): x is string => !!x).join(" · ");
+}
````

### Task 4: The chart draws the value book's levels

**Files:** Rewrite `web/components/stock/PriceChart.tsx`; create `web/components/stock/PriceChart.test.tsx`; this plan.

**What it does (ruling 6, 13):** `PriceChart({ symbol, lines })`: transparent background, no grid, no borders, no
logo, `autoSize` at 280 px; ink candles (up hollow, down filled), volume in the perforation tone with no axis label,
SMA 50 ink and SMA 200 muted, each `lines` entry a dashed muted price line with its title on the axis; colours from the
tokens at mount and again on a theme change (a `MutationObserver` on `data-theme`, as `UnderlyingChart`); a
`role="img"` sentence ("GOOGL daily prices over the last year, from $150.13 to $189.10; Fair value $215.00; ...") and
a line of words naming every series; loading (`role="status"` skeleton, `bg-sunk`), empty ("No price history for X
yet.") and failed ("The price chart could not be loaded. It tries again when you reopen this page.") in words.

- [x] **Step 1: da-vinci** (the chart's look is fixed by ruling 6; da-vinci checks contrast of the muted price line
  labels in both themes with `contrast.py` and records the numbers).
- [x] **Step 2: Check and apply `T4`.** `git status --short`: `M web/components/stock/PriceChart.tsx`,
  `?? web/components/stock/PriceChart.test.tsx`.
- [x] **Step 3: Red check.** `git stash push -- web/components/stock/PriceChart.tsx`, then
  `cd web && npx vitest run components/stock/PriceChart` shows `3 failed`; `git stash pop`.
- [x] **Step 4: Gate.** `npx vitest run components/stock/PriceChart`: 3 passed. Full vitest **1541 in 151 files**;
  tsc, lint clean.
- [x] **Step 5: Commit** `feat(web): the stock chart in ink, with the value book's levels drawn across it`.

<!-- block T4 -->
````diff
diff --git a/web/components/stock/PriceChart.test.tsx b/web/components/stock/PriceChart.test.tsx
new file mode 100644
index 0000000..bc2d3b7
--- /dev/null
+++ b/web/components/stock/PriceChart.test.tsx
@@ -0,0 +1,92 @@
+import { cleanup, screen } from "@testing-library/react";
+import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
+import { renderWithQuery } from "@/lib/test-query";
+
+const chart = vi.hoisted(() => ({
+  options: [] as Array<Record<string, unknown>>,
+  lines: [] as Array<{ price: number; title: string; lineStyle: number }>,
+  candles: [] as Array<Record<string, unknown>>,
+}));
+
+vi.mock("lightweight-charts", () => ({
+  ColorType: { Solid: "solid" },
+  CrosshairMode: { Normal: 0 },
+  LineStyle: { Dashed: 2 },
+  createChart: (_el: unknown, opts: Record<string, unknown>) => {
+    chart.options.push(opts);
+    const series = () => ({
+      setData: vi.fn(),
+      applyOptions: vi.fn(),
+      createPriceLine: (l: { price: number; title: string; lineStyle: number }) => {
+        chart.lines.push(l);
+        return { applyOptions: vi.fn() };
+      },
+    });
+    return {
+      addCandlestickSeries: (o: Record<string, unknown>) => {
+        chart.candles.push(o);
+        return series();
+      },
+      addHistogramSeries: series,
+      addLineSeries: series,
+      priceScale: () => ({ applyOptions: vi.fn() }),
+      timeScale: () => ({ fitContent: vi.fn() }),
+      applyOptions: vi.fn(),
+      remove: vi.fn(),
+    };
+  },
+}));
+
+import { PriceChart } from "./PriceChart";
+
+const BARS = {
+  as_of: "2026-11-05T21:00:00Z",
+  bars: [
+    { time: "2026-11-03", open: 180, high: 184, low: 179, close: 182.4, volume: 1000 },
+    { time: "2026-11-04", open: 182.4, high: 186, low: 181, close: 185.1, volume: 1200 },
+  ],
+  sma50: [null, 178.2],
+  sma200: [null, null],
+};
+
+beforeEach(() => {
+  chart.options.length = 0;
+  chart.lines.length = 0;
+  chart.candles.length = 0;
+});
+afterEach(cleanup);
+
+describe("PriceChart", () => {
+  it("draws the caller's levels as dashed lines and names them in the chart's sentence", async () => {
+    renderWithQuery(
+      <PriceChart symbol="GOOGL" lines={[{ price: 215, title: "Fair value $215.00" }, { price: 190, title: "Entry ceiling $190.00" }]} />,
+      { "/research/GOOGL/bars": BARS },
+    );
+    const img = await screen.findByRole("img");
+    expect(img).toHaveAccessibleName(
+      "GOOGL daily prices over the last year, from $182.40 to $185.10; Fair value $215.00; Entry ceiling $190.00",
+    );
+    expect(chart.lines.map((l) => [l.price, l.title, l.lineStyle])).toEqual([
+      [215, "Fair value $215.00", 2],
+      [190, "Entry ceiling $190.00", 2],
+    ]);
+    expect(screen.getByText(/Dashed lines are the value book's levels\./)).toBeInTheDocument();
+  });
+
+  it("draws candles by shape, not colour, with no logo on the canvas", async () => {
+    renderWithQuery(<PriceChart symbol="GOOGL" />, { "/research/GOOGL/bars": BARS });
+    await screen.findByRole("img");
+    expect(chart.candles[0]?.upColor).toBe("transparent");
+    expect((chart.options[0]?.layout as { attributionLogo?: boolean }).attributionLogo).toBe(false);
+    expect(screen.getByText(/hollow on an up day, filled on a down day/)).toBeInTheDocument();
+    expect(screen.queryByText(/Dashed lines/)).toBeNull();
+  });
+
+  it("says so in words when there is no history or the request fails", async () => {
+    renderWithQuery(<PriceChart symbol="NEWCO" />, { "/research/NEWCO/bars": { ...BARS, bars: [], sma50: [], sma200: [] } });
+    expect(await screen.findByText("No price history for NEWCO yet.")).toBeInTheDocument();
+    cleanup();
+    renderWithQuery(<PriceChart symbol="GONE" />, {});
+    expect(await screen.findByText(/The price chart could not be loaded/)).toBeInTheDocument();
+  });
+});
diff --git a/web/components/stock/PriceChart.tsx b/web/components/stock/PriceChart.tsx
index 3b3d9ac..74746d6 100644
--- a/web/components/stock/PriceChart.tsx
+++ b/web/components/stock/PriceChart.tsx
@@ -2,158 +2,144 @@
 
 import { useQuery } from "@tanstack/react-query";
 import { useEffect, useRef } from "react";
-import {
-  ColorType,
-  createChart,
-  type IChartApi,
-  type ISeriesApi,
-} from "lightweight-charts";
-
+import { ColorType, CrosshairMode, LineStyle, createChart, type IChartApi } from "lightweight-charts";
 import { apiFetch } from "@/lib/api";
+import { formatMoneyCell } from "@/lib/money";
 
-type Bar = {
-  time: string;
-  open: number;
-  high: number;
-  low: number;
-  close: number;
-  volume: number;
-};
-
-type BarsResponse = {
-  as_of: string;
-  bars: Bar[];
-  sma50: (number | null)[];
-  sma200: (number | null)[];
-};
+type Bar = { time: string; open: number; high: number; low: number; close: number; volume: number };
+type BarsResponse = { as_of: string; bars: Bar[]; sma50: (number | null)[]; sma200: (number | null)[] };
+export type PriceLine = { price: number; title: string };
 
-/**
- * Reads the semantic colour tokens from CSS custom properties at mount, never hard-coded
- * hex. The chart draws to a canvas, so it needs resolved colour strings, not `var(...)"
- * references — but the tokens are defined globally in `globals.css` and this component only
- * mounts client-side, so the computed values are always present. An empty string means the
- * token was misconfigured; the chart renders with an empty series colour rather than a
- * hex the rest of the page does not use.
- */
+/** A resolved token colour for the canvas (it cannot read `var(...)`); empty when unset. */
 function cssVar(name: string): string {
   if (typeof window === "undefined") return "";
   return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
 }
 
-export function PriceChart({ symbol }: { symbol: string }) {
-  const containerRef = useRef<HTMLDivElement>(null);
-  const chartRef = useRef<IChartApi | null>(null);
+function overlay(values: (number | null)[], bars: Bar[]) {
+  return values
+    .map((v, i) => (v === null || !bars[i] ? null : { time: bars[i].time, value: v }))
+    .filter((p): p is { time: string; value: number } => p !== null);
+}
 
-  const { data } = useQuery<BarsResponse>({
+/**
+ * A year of daily candles in ink (an up day hollow, a down day filled: direction by shape, never by
+ * colour), volume as light bars along the foot (the perforation tone), the 50-day average as a thin ink line and the 200-day
+ * as a thin muted one, and the caller's levels as dashed rules with their labels on the price axis
+ * (web overhaul Part 5: the value book's fair value, entry ceiling, half sale and stop). Colours come
+ * from the tokens at mount and again when the theme changes; nothing animates in. The canvas is
+ * hidden from a screen reader and a sentence stands in for it; a line of words under it names
+ * every series.
+ */
+export function PriceChart({ symbol, lines = [] }: { symbol: string; lines?: PriceLine[] }) {
+  const ref = useRef<HTMLDivElement>(null);
+  const { data, isError } = useQuery<BarsResponse>({
     queryKey: ["bars", symbol],
     queryFn: () => apiFetch<BarsResponse>(`/research/${symbol}/bars?range=1y`),
   });
+  const bars = data?.bars ?? [];
+  const lineKey = lines.map((l) => `${l.price}:${l.title}`).join("|");
 
   useEffect(() => {
-    const el = containerRef.current;
-    if (!el) return;
-
-    const gain = cssVar("--color-gain");
-    const loss = cssVar("--color-loss");
-    const muted = cssVar("--text-muted");
-    const background = cssVar("--bg-background");
-    const surface = cssVar("--bg-surface");
-    const focus = cssVar("--color-focus");
-
-    const chart = createChart(el, {
+    const el = ref.current;
+    if (!el || !data || data.bars.length === 0) return;
+    const ink = () => cssVar("--chart-line");
+    const muted = () => cssVar("--text-muted");
+    const light = () => cssVar("--color-perforation");
+    const chart: IChartApi = createChart(el, {
+      autoSize: true,
+      height: 280,
       layout: {
-        background: { type: ColorType.Solid, color: background },
-        textColor: muted,
-        fontFamily: "var(--font-mono), ui-monospace, monospace",
+        background: { type: ColorType.Solid, color: "transparent" },
+        textColor: muted(),
+        fontFamily: "var(--font-sans), system-ui, sans-serif",
+        // The licence link is the Credits card on More; the logo would sit on the candles.
+        attributionLogo: false,
       },
-      grid: {
-        vertLines: { color: surface },
-        horzLines: { color: surface },
-      },
-      rightPriceScale: { borderColor: surface },
-      timeScale: { borderColor: surface },
-      crosshair: { mode: 0 },
+      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
+      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.24 } },
+      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
+      crosshair: { mode: CrosshairMode.Normal },
       handleScale: false,
       handleScroll: false,
     });
-    chartRef.current = chart;
-
-    const candle = chart.addCandlestickSeries({
-      upColor: gain,
-      downColor: loss,
-      wickUpColor: gain,
-      wickDownColor: loss,
-      borderVisible: false,
+    const candles = chart.addCandlestickSeries({
+      upColor: "transparent",
+      downColor: ink(),
+      borderUpColor: ink(),
+      borderDownColor: ink(),
+      wickUpColor: ink(),
+      wickDownColor: ink(),
+      priceLineVisible: false,
+      lastValueVisible: true,
     });
+    candles.setData(data.bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));
     const volume = chart.addHistogramSeries({
       priceFormat: { type: "volume" },
       priceScaleId: "vol",
-    });
-    chart.priceScale("vol").applyOptions({
-      scaleMargins: { top: 0.8, bottom: 0 },
-    });
-    const sma50Line = chart.addLineSeries({
-      color: focus,
-      lineWidth: 1,
-      priceLineVisible: false,
-      lastValueVisible: false,
-    });
-    const sma200Line = chart.addLineSeries({
-      color: muted,
-      lineWidth: 1,
+      color: light(),
       priceLineVisible: false,
       lastValueVisible: false,
     });
+    chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.86, bottom: 0 } });
+    volume.setData(data.bars.map((b) => ({ time: b.time, value: b.volume })));
+    const sma50 = chart.addLineSeries({ color: ink(), lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
+    sma50.setData(overlay(data.sma50, data.bars));
+    const sma200 = chart.addLineSeries({ color: muted(), lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
+    sma200.setData(overlay(data.sma200, data.bars));
+    const priceLines = lines.map((l) =>
+      candles.createPriceLine({
+        price: l.price,
+        color: muted(),
+        lineWidth: 1,
+        lineStyle: LineStyle.Dashed,
+        axisLabelVisible: true,
+        title: l.title,
+      }),
+    );
+    chart.timeScale().fitContent();
 
-    if (data && data.bars.length > 0) {
-      candle.setData(
-        data.bars.map((b) => ({
-          time: b.time,
-          open: b.open,
-          high: b.high,
-          low: b.low,
-          close: b.close,
-        })),
-      );
-      volume.setData(
-        data.bars.map((b) => ({
-          time: b.time,
-          value: b.volume,
-          color: b.close >= b.open ? gain : loss,
-        })),
-      );
-      sma50Line.setData(
-        data.sma50
-          .map((v, i) => (v === null ? null : { time: data.bars[i].time, value: v }))
-          .filter((p): p is { time: string; value: number } => p !== null),
-      );
-      sma200Line.setData(
-        data.sma200
-          .map((v, i) => (v === null ? null : { time: data.bars[i].time, value: v }))
-          .filter((p): p is { time: string; value: number } => p !== null),
-      );
-      chart.timeScale().fitContent();
-    }
-
-    const resize = () => {
-      if (containerRef.current && chartRef.current) {
-        chartRef.current.applyOptions({
-          width: containerRef.current.clientWidth,
-        });
-      }
-    };
-    window.addEventListener("resize", resize);
-
+    const observer = new MutationObserver(() => {
+      candles.applyOptions({ downColor: ink(), borderUpColor: ink(), borderDownColor: ink(), wickUpColor: ink(), wickDownColor: ink() });
+      volume.applyOptions({ color: light() });
+      sma50.applyOptions({ color: ink() });
+      sma200.applyOptions({ color: muted() });
+      chart.applyOptions({ layout: { textColor: muted() } });
+      priceLines.forEach((pl) => pl.applyOptions({ color: muted() }));
+    });
+    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
     return () => {
-      window.removeEventListener("resize", resize);
+      observer.disconnect();
       chart.remove();
-      chartRef.current = null;
     };
-  }, [data]);
+    // `lines` is compared by value through lineKey: a new array with the same levels must not rebuild the chart.
+    // eslint-disable-next-line react-hooks/exhaustive-deps
+  }, [data, lineKey]);
 
+  if (isError && !data) {
+    return <p className="text-sm text-muted">The price chart could not be loaded. It tries again when you reopen this page.</p>;
+  }
+  if (!data) {
+    return <div role="status" aria-busy="true" aria-label="Loading the price chart" className="h-[280px] rounded-xl bg-sunk" />;
+  }
+  if (bars.length === 0) {
+    return <p className="text-sm text-muted">{`No price history for ${symbol} yet.`}</p>;
+  }
+  const first = bars[0];
+  const last = bars[bars.length - 1];
   return (
-    <div className="overflow-x-auto rounded-md bg-surface">
-      <div ref={containerRef} className="h-80 w-full" />
+    <div>
+      <div
+        role="img"
+        aria-label={`${symbol} daily prices over the last year, from ${formatMoneyCell(first.close)} to ${formatMoneyCell(last.close)}${lines.map((l) => `; ${l.title}`).join("")}`}
+      >
+        <div ref={ref} className="h-[280px] w-full" aria-hidden="true" />
+      </div>
+      <p className="mt-2 text-[0.8125rem] text-muted">
+        One year of daily candles: hollow on an up day, filled on a down day. The ink line is the 50-day average, the grey
+        line the 200-day, and the light bars are each day&apos;s volume.
+        {lines.length > 0 ? " Dashed lines are the value book's levels." : ""}
+      </p>
     </div>
   );
-}
\ No newline at end of file
+}
````

### Task 5: The page frame

**Files:** Create `web/features/stock/StockSection.tsx`, `web/features/stock/StockPage.tsx`,
`web/features/stock/StockPage.test.tsx`; modify `web/app/stock/[symbol]/page.tsx`,
`web/features/stock-value/ValueBlock.tsx`, `web/DESIGN.md`; delete `web/components/stock/SectionShell.tsx`; this plan.

**What it does (rulings 7-12, 14, 15):** the page described in the Spec for da-vinci. `StockPage` reads
`GET /research/{symbol}` (key `["analysis", SYM]`, polling every 5 s while a section is pending, no retry on a 404)
and `GET /value/{symbol}` (key `["value","ticker",SYM]`, the block's own); `StockSection` is a `Card` per section; the
value block loses its outer `mt-4` wrapper because it now sits in a grid; `page.tsx` only mounts `StockPage`.
`web/DESIGN.md` gains the Stock surface paragraph, the size-and-tranche sentence in the Value block paragraph, the
`claude_note` sentence in Top opportunities, a Decision Log entry and `updated=2026-11-06`.

- [x] **Step 1: da-vinci** with the Spec above; it reads the new Stock paragraph from the T5 patch (or after Step 2).
- [x] **Step 2: Check and apply `T5`.** `git status --short` shows `M web/DESIGN.md`,
  `M web/app/stock/[symbol]/page.tsx`, `D web/components/stock/SectionShell.tsx`,
  `M web/features/stock-value/ValueBlock.tsx` and the three new `web/features/stock/` files.
- [x] **Step 3: Gate.** `cd web && npx vitest run features/stock features/stock-value`: 47 passed (StockPage 5,
  stock 7, format 12, ValueBlock 15, AnalyseButton 8). Full vitest **1546 in 152 files**; tsc, lint clean; G3 exit 0;
  G4 green; G5 no finding; `grep -rn "SectionShell" web --include=*.tsx --include=*.ts` prints nothing outside
  `node_modules`.
- [x] **Step 4: Commit** `feat(web): the stock page on the payslip: one grid, every section a card, the value block where it matters`.

<!-- block T5 -->
````diff
diff --git a/web/DESIGN.md b/web/DESIGN.md
index 8dd2b52..fedbf8b 100644
--- a/web/DESIGN.md
+++ b/web/DESIGN.md
@@ -221,7 +221,7 @@ components:
     backgroundColor: "{colors.ink}"
     textColor: "{colors.ground}"
 ---
-<!-- da-vinci schema=1 status=ratified updated=2026-11-05 -->
+<!-- da-vinci schema=1 status=ratified updated=2026-11-06 -->
 # Design System: IBKR Income
 
 ## Overview
@@ -981,7 +981,8 @@ Read. Search, watchlist, sectors, the stock page, and Universe. VARIANCE 3, DENS
   nothing: "See the value file" (READY only) goes to the stock page's value block, which reads the file (the book's decide flow lives on Home's Value card, not here);
   "Sell a put up to $190.00" appears only when the book has a put ceiling and the latest scan has a passed
   cash-secured put at or under it, and opens Trades, Assessed on that name. The strip sends no command and has no
-  button but the two tabs. Claude's one-line note is not shown, because the API does not carry one. Unavailable
+  button but the two tabs. Claude's one-line note is not shown yet: the API carries it since web overhaul Part 5
+  (`claude_note`, from Claude's own reads only) and the card shows it from Part 6. Unavailable
   reads "The value book has not written anything yet."; an empty list names the list. No new token, colour,
   font, radius or elevation.
 
@@ -1011,9 +1012,50 @@ Read. Search, watchlist, sectors, the stock page, and Universe. VARIANCE 3, DENS
   in config." answers a `claude_off` reply, and an applied one says the read is queued and that the card looks
   again for ten minutes. A name the book cannot score says why in one sentence ("The value book does not score
   GOOGL: ..."); unavailable reads "The value book has not written anything yet."; unknown figures are hatched
-  n/a. The tranche plan and the size tier are not in the API yet, so the card does not show them. No new
+  n/a. Since web overhaul Part 5, "How much, and when?" also says the size tier per priced list ("At this margin of
+  safety a buy aims at 5% of the book's ceiling, in 3 tranches."; a hatched "Size if bought n/a" when the margin is
+  unknown) and a held name's tranche plan ("1 of 3 tranches bought (the last on Oct 20, 2026). Tranche 2 waits for
+  a higher low, at least 5 sessions after the last, and passes the value gate again first."). No new
   token, colour, font, radius or elevation.
 
+### Stock
+Read. One name, and everything the system knows about it. VARIANCE 3, DENSITY 6. Recomposed 2026-11-06 (web
+overhaul Part 5) on the Position page's frame.
+- **THESIS:** a name is a price and the verdicts on it. The chart leads, with the value book's levels drawn
+  across it; the value book's verdict comes straight after when the book would buy the name at a price (Ready,
+  Watch or Wait on a list) or holds it.
+- **OWN-WORLD:** the payslip. Sage paper; ink candles (an up day hollow, a down day filled: direction by shape,
+  never by colour), the 50-day average as a thin ink line and the 200-day as a thin muted one, volume as light
+  bars along the foot (the perforation tone), and the value book's fair value, entry ceiling, half sale and stop as dashed muted rules
+  labelled on the price axis (two levels at one price share a label: "Fair value, Half sale $215.00"). White
+  cards for every section. No lime: the page's one command, "Run Claude's analysis" in the value block, is
+  secondary.
+- **STORY:** the price and how fresh it is; where it sits against the value book's levels; the value book's
+  verdict; the checks; the technicals; the statements as filed; then the news service's notes, the headlines,
+  the crowd's tone and a model's written summary.
+- **FIRST VIEWPORT:** desktop: a back link to Research, the ticker as the title (24px, 800), the name, exchange
+  and "ETF" on a muted line, then the last price at 24px with "Delayed" as a flag word when it is stale and its
+  age beside it (a hatched "Last price n/a" when there is none); then two columns: the chart (280px tall, on the
+  paper) with one line of words under it naming every series, and the news service's notes in the 340px column on
+  the right. Phone: title, price, chart, then the cards in DOM order.
+- **FORM:** one grid as Position's (content left, a 340px column right from 1024px; the DOM order is the phone
+  order). Left: chart, the value block when it leads, Checks, Technicals, Financial statements (the tables
+  behind a closed disclosure, "Revenue, profit, balance sheet and cash flow, as filed"), the value block when it
+  does not lead. Right: the notes, News, Sentiment, Model summary. Each section is a white card titled at
+  17px/700; one still being built says "Building this section. It will appear shortly." and one that cannot be
+  shown says the API's reason as written.
+- **Words, not colours:** a check's state is a word (Fail is a flag word); the ribbon fills a passed check and
+  outlines a failed one, both in ink; a warning carries "Caution" (flag) or "Note". Headline tone and the
+  sentiment change are words and signs, never green or red, because they are not money. An unknown figure is a
+  hatched n/a.
+- **Model summary:** labelled by the model that wrote it ("Written by <model>, a language model that decides
+  nothing"), because the summary backend can be Claude or another model; Claude's own words on this page are in
+  the value block, each labelled as Claude's. "Generate summary" is a secondary button.
+- **Errors:** a name the research service does not know reads "The research service does not know ZZZZ. Check
+  the ticker, or add it to the watchlist on Research."; any other failure reads "This page could not be loaded.
+  It tries again when you reopen it."
+- No new token, colour, font, radius or elevation.
+
 ### News
 Read. Feed and calendar; ticker briefs. The feed opens with the Market card: regimes, up to six stories
 with each description labelled as Claude's, and one line on the last 7 days of triage (judged as noise,
@@ -1101,6 +1143,12 @@ sibling keys; re-run the check after edits.
 
 ## Decision Log
 
+- 2026-11-06: **The stock page on the payslip** (web overhaul Part 5). Added the Stock surface. The chart keeps its
+  candles (the HANDOFF's call: keep `PriceChart`, add the value book's levels) but draws them in ink with direction
+  by shape, and the levels as dashed rules; every section is a card; the value block leads for a priced or held
+  name; checks, headline tone and sentiment say their state in words, never in green or red, which stay for signed
+  money. The written summary is labelled by its model, not as Claude's. No new token, colour, font, radius or
+  elevation.
 - 2026-11-05: **Not-found and error pages** (web overhaul Part 4, Task 15). Added the paragraph under
   Components and the two root boundaries (`app/not-found.tsx`, `app/error.tsx`). The rule that shaped them: a
   page that failed to draw is not a place to act, so each has one secondary action and no lime. No new token,
diff --git a/web/app/stock/[symbol]/page.tsx b/web/app/stock/[symbol]/page.tsx
index 29cf25c..37ebe24 100644
--- a/web/app/stock/[symbol]/page.tsx
+++ b/web/app/stock/[symbol]/page.tsx
@@ -1,116 +1,9 @@
 "use client";
 
-import { useQuery } from "@tanstack/react-query";
 import { use } from "react";
-import { apiFetch } from "@/lib/api";
-import { RefreshButton } from "@/components/shell/RefreshButton";
-import { ChecksSection } from "@/components/checks/ChecksSection";
-import { NewsPanel } from "@/components/stock/NewsPanel";
-import { PriceChart } from "@/components/stock/PriceChart";
-import { SectionShell } from "@/components/stock/SectionShell";
-import { SentimentPanel } from "@/components/stock/SentimentPanel";
-import { StatementsTable } from "@/components/stock/StatementsTable";
-import { SummaryPanel } from "@/components/stock/SummaryPanel";
-import { TechnicalsPanel } from "@/components/stock/TechnicalsPanel";
-import { NameNotes } from "@/features/market/NameNotes";
-import { ValueBlock } from "@/features/stock-value/ValueBlock";
-import { relativeAge } from "@/lib/format";
+import { StockPage } from "@/features/stock/StockPage";
 
-const PENDING_SECTIONS = ["fundamentals", "technicals", "sentiment", "news", "checks"] as const;
-
-export default function StockPage({ params }: { params: Promise<{ symbol: string }> }) {
+export default function Page({ params }: { params: Promise<{ symbol: string }> }) {
   const { symbol } = use(params);
-  const upper = symbol.toUpperCase();
-
-  const { data, isLoading } = useQuery({
-    queryKey: ["analysis", upper],
-    queryFn: () => apiFetch<any>(`/research/${upper}`),
-    // Poll while any section is still building \u2014 not just fundamentals, which was the
-    // only section that existed before M4 added technicals/sentiment/news.
-    refetchInterval: (q) =>
-      PENDING_SECTIONS.some((s) => q.state.data?.[s]?.state === "pending") ? 5000 : false,
-  });
-
-  const quote = data?.quote;
-
-  return (
-    <div className="px-8 py-6">
-      <header className="mb-8 flex items-start justify-between gap-3">
-        <div className="min-w-0">
-          <h1 className="font-mono text-2xl text-content">{upper}</h1>
-          <p className="mt-1 text-sm text-muted">
-            {data?.name ?? (isLoading ? "Loading" : "")}
-            {data?.exchange ? ` \u00b7 ${data.exchange}` : ""}
-            {data?.is_etf ? " \u00b7 ETF" : ""}
-          </p>
-          {quote?.value != null && (
-            <p className="mt-2 flex items-baseline gap-2">
-              <span className="tabular text-lg text-content">${quote.value.toFixed(2)}</span>
-              <span className={`text-xs ${quote.stale ? "text-unknown" : "text-muted"}`}>
-                {relativeAge(quote.as_of)}
-                {quote.stale ? " \u00b7 delayed" : ""}
-              </span>
-            </p>
-          )}
-        </div>
-        <RefreshButton label={`Refresh ${upper}`} className="-mr-2" />
-      </header>
-
-      <section className="mb-10">
-        <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">Price chart</h2>
-        <PriceChart symbol={upper} />
-      </section>
-
-      <section className="mb-10">
-        <NameNotes symbol={upper} />
-        <ValueBlock symbol={upper} />
-      </section>
-
-      <SectionShell
-        title="Checks"
-        state={data?.checks?.state ?? "pending"}
-        reason={data?.checks?.reason}
-      >
-        {data?.checks?.data && <ChecksSection data={data.checks.data} />}
-      </SectionShell>
-
-      <SectionShell
-        title="Technicals"
-        state={data?.technicals?.state ?? "pending"}
-        reason={data?.technicals?.reason}
-      >
-        {data?.technicals?.data && <TechnicalsPanel data={data.technicals.data} />}
-      </SectionShell>
-
-      <SectionShell
-        title="Financial statements"
-        state={data?.fundamentals?.state ?? "pending"}
-        reason={data?.fundamentals?.reason}
-      >
-        {data?.fundamentals?.data && (
-          <StatementsTable financials={data.fundamentals.data} />
-        )}
-      </SectionShell>
-
-      <SectionShell
-        title="Sentiment"
-        state={data?.sentiment?.state ?? "pending"}
-        reason={data?.sentiment?.reason}
-      >
-        {data?.sentiment?.data && <SentimentPanel data={data.sentiment.data} />}
-      </SectionShell>
-
-      <SectionShell
-        title="News"
-        state={data?.news?.state ?? "pending"}
-        reason={data?.news?.reason}
-      >
-        {data?.news?.data && <NewsPanel items={data.news.data} />}
-      </SectionShell>
-
-      <SectionShell title="AI summary" state="ready">
-        <SummaryPanel symbol={upper} />
-      </SectionShell>
-    </div>
-  );
-}
\ No newline at end of file
+  return <StockPage symbol={symbol} />;
+}
diff --git a/web/components/stock/SectionShell.tsx b/web/components/stock/SectionShell.tsx
deleted file mode 100644
index e4c15ba..0000000
--- a/web/components/stock/SectionShell.tsx
+++ /dev/null
@@ -1,28 +0,0 @@
-export function SectionShell({
-  title,
-  state,
-  reason,
-  children,
-}: {
-  title: string;
-  state: "ready" | "pending" | "unavailable";
-  reason?: string | null;
-  children: React.ReactNode;
-}) {
-  return (
-    <section className="mb-10">
-      <h2 className="mb-3 text-sm font-medium tracking-wide text-muted">{title}</h2>
-      {state === "ready" && children}
-      {state === "pending" && (
-        <p className="rounded-md bg-surface px-4 py-3 text-sm text-muted">
-          {reason ?? "Building this section. It will appear shortly."}
-        </p>
-      )}
-      {state === "unavailable" && (
-        <p className="rounded-md bg-surface px-4 py-3 text-sm text-muted">
-          {reason ?? "Not available for this symbol."}
-        </p>
-      )}
-    </section>
-  );
-}
\ No newline at end of file
diff --git a/web/features/stock-value/ValueBlock.tsx b/web/features/stock-value/ValueBlock.tsx
index aa3e6f5..aabb7ed 100644
--- a/web/features/stock-value/ValueBlock.tsx
+++ b/web/features/stock-value/ValueBlock.tsx
@@ -139,41 +139,32 @@ export function ValueBlock({ symbol }: { symbol: string }) {
   const titleId = `value-block-${sym}`;
   if (!data) {
     return isError ? (
-      <div className="mt-4">
-        <Card as="div">
-          <p className="text-sm text-muted">The value book&apos;s view of {sym} could not be loaded.</p>
-        </Card>
-      </div>
+      <Card as="div">
+        <p className="text-sm text-muted">The value book&apos;s view of {sym} could not be loaded.</p>
+      </Card>
     ) : (
-      <div
-        role="status"
-        aria-busy="true"
-        aria-label="Loading the value book's view"
-        className="mt-4 h-28 rounded-[18px] bg-surface"
-      />
+      <div role="status" aria-busy="true" aria-label="Loading the value book's view" className="h-28 rounded-[18px] bg-surface" />
     );
   }
   return (
-    <div className="mt-4">
-      <Card aria-labelledby={titleId}>
-        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
-          <h2 id={titleId} className="text-[1.0625rem] font-bold">
-            Value book on {sym}
-          </h2>
-          {data.available && (
-            <span className="tabular text-[0.8125rem] text-muted">{fileAgeWords(data, data.file?.as_of)}</span>
-          )}
-        </div>
-        {data.available ? (
-          <Body
-            sym={sym}
-            t={data}
-            onQueued={() => setWatch({ since: Date.now(), readAt: data.claude?.read_at ?? null })}
-          />
-        ) : (
-          <p className="mt-2 text-sm">The value book has not written anything yet.</p>
+    <Card aria-labelledby={titleId}>
+      <div className="flex flex-wrap items-baseline justify-between gap-x-3">
+        <h2 id={titleId} className="text-[1.0625rem] font-bold">
+          Value book on {sym}
+        </h2>
+        {data.available && (
+          <span className="tabular text-[0.8125rem] text-muted">{fileAgeWords(data, data.file?.as_of)}</span>
         )}
-      </Card>
-    </div>
+      </div>
+      {data.available ? (
+        <Body
+          sym={sym}
+          t={data}
+          onQueued={() => setWatch({ since: Date.now(), readAt: data.claude?.read_at ?? null })}
+        />
+      ) : (
+        <p className="mt-2 text-sm">The value book has not written anything yet.</p>
+      )}
+    </Card>
   );
 }
diff --git a/web/features/stock/StockPage.test.tsx b/web/features/stock/StockPage.test.tsx
new file mode 100644
index 0000000..7d7fe3a
--- /dev/null
+++ b/web/features/stock/StockPage.test.tsx
@@ -0,0 +1,119 @@
+import { cleanup, render, screen } from "@testing-library/react";
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { afterEach, describe, expect, it, vi } from "vitest";
+import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
+import { ApiError } from "@/lib/api";
+
+// The children have their own suites; here they are stand-ins that say where they were placed.
+vi.mock("@/components/stock/PriceChart", () => ({
+  PriceChart: ({ symbol, lines }: { symbol: string; lines: { title: string }[] }) => (
+    <div data-testid="chart">{`${symbol} chart: ${lines.map((l) => l.title).join("; ")}`}</div>
+  ),
+}));
+vi.mock("@/features/stock-value/ValueBlock", () => ({
+  ValueBlock: ({ symbol }: { symbol: string }) => <section aria-label={`Value book on ${symbol}`} data-testid="value" />,
+}));
+vi.mock("@/features/market/NameNotes", () => ({ NameNotes: () => <section data-testid="notes" /> }));
+vi.mock("@/components/stock/SummaryPanel", () => ({ SummaryPanel: () => <p>summary stand-in</p> }));
+
+import { StockPage } from "./StockPage";
+
+afterEach(cleanup);
+
+const ready = <T,>(data: T) => ({ state: "ready", data, reason: null });
+
+const ANALYSIS = {
+  as_of: "2026-11-05T15:00:00Z",
+  symbol: "GOOGL",
+  name: "Alphabet Inc.",
+  exchange: "NASDAQ",
+  is_etf: false,
+  quote: { value: 182.4, source: "ibkr", as_of: "2026-11-05T14:58:00Z", stale: true },
+  fundamentals: { state: "unavailable", data: null, reason: "No filings for this symbol." },
+  technicals: ready({ symbol: "GOOGL", price: 182.4, rsi_14: 55.2, atr_14: 3.1, macd: 0.5, macd_signal: 0.3, sma_20: 180, sma_50: 178, sma_200: 160, phase: "Stage 2", regime: "bull" }),
+  sentiment: { state: "pending", data: null, reason: null },
+  news: ready([]),
+  checks: ready({ categories: [], warnings: [] }),
+};
+
+const VALUE_READY = {
+  as_of: "2026-11-05T15:00:00Z", available: true, symbol: "GOOGL", computed: "stored", age_days: 1, plan: null,
+  file: {
+    symbol: "GOOGL", as_of: "2026-11-04", company_class: "operating", data_quality: "pass", health: "pass",
+    ruleset_version: "v4", ruleset_hash: "be30d1eaa915",
+    lists: [{
+      list_name: "deep_value", baseline_verdict: "READY", verdict: "READY", decided_by: "python", fair_value: 215,
+      effective_fair_value: 215, mos: 0.15, required_mos_pct: 30, entry_ceiling: 190, reasons: [], mos_review: false,
+      methods: [], gates: [], size_pct: 3, tranches: 3,
+    }],
+  },
+};
+
+const VALUE_NO = {
+  ...VALUE_READY,
+  file: { ...VALUE_READY.file, lists: [{ ...VALUE_READY.file.lists[0], verdict: "NO", baseline_verdict: "NO" }] },
+};
+
+function headings() {
+  return screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
+}
+
+function order(): string[] {
+  // The value block's stand-in and the cards' titles, in DOM order.
+  return Array.from(document.querySelectorAll("[data-testid=value], h2")).map((el) =>
+    el.getAttribute("data-testid") === "value" ? "VALUE" : (el.textContent ?? ""),
+  );
+}
+
+describe("StockPage", () => {
+  it("leads with the ticker, its name, the last price with Delayed in words, and a back link to Research", async () => {
+    renderWithQuery(<StockPage symbol="googl" />, { "/research/GOOGL": ANALYSIS, "/value/GOOGL": VALUE_READY });
+    expect(await screen.findByText("Alphabet Inc. · NASDAQ")).toBeInTheDocument();
+    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("GOOGL");
+    expect(screen.getByText("$182.40")).toBeInTheDocument();
+    expect(screen.getByText("Delayed")).toBeInTheDocument();
+    expect(screen.getByRole("link", { name: "Research" })).toHaveAttribute("href", "/research");
+    expect(screen.getByRole("button", { name: "Refresh GOOGL" })).toBeInTheDocument();
+  });
+
+  it("puts the value block first, under the chart, when the book would buy the name at a price, and draws its levels", async () => {
+    renderWithQuery(<StockPage symbol="GOOGL" />, { "/research/GOOGL": ANALYSIS, "/value/GOOGL": VALUE_READY });
+    expect(await screen.findByText("GOOGL chart: Fair value $215.00; Entry ceiling $190.00")).toBeInTheDocument();
+    expect(order().slice(0, 3)).toEqual(["GOOGL price chart", "VALUE", "Checks"]);
+  });
+
+  it("puts the value block at the foot of the left column when every list is No", async () => {
+    renderWithQuery(<StockPage symbol="GOOGL" />, { "/research/GOOGL": ANALYSIS, "/value/GOOGL": VALUE_NO });
+    await screen.findByText("Alphabet Inc. · NASDAQ");
+    expect(await screen.findByText("GOOGL chart:")).toBeInTheDocument();
+    const o = order();
+    expect(o.indexOf("VALUE")).toBe(o.indexOf("Financial statements") + 1);
+  });
+
+  it("shows each section in its own card, with the API's reason when it is not ready", async () => {
+    renderWithQuery(<StockPage symbol="GOOGL" />, { "/research/GOOGL": ANALYSIS, "/value/GOOGL": VALUE_READY });
+    await screen.findByText("Alphabet Inc. · NASDAQ");
+    expect(headings()).toEqual(
+      expect.arrayContaining(["Checks", "Technicals", "Financial statements", "News", "Sentiment", "Model summary"]),
+    );
+    expect(screen.getByText("No filings for this symbol.")).toBeInTheDocument();
+    expect(screen.getByText("Building this section. It will appear shortly.")).toBeInTheDocument();
+    expect(screen.getByText("RSI 14")).toBeInTheDocument();
+  });
+
+  it("says a name the research service does not know in words, not an empty page", async () => {
+    apiFetchMock.mockImplementation(async (path: string) => {
+      throw new ApiError(404, `Unknown ${path}`);
+    });
+    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+    render(
+      <QueryClientProvider client={qc}>
+        <StockPage symbol="zzzz" />
+      </QueryClientProvider>,
+    );
+    expect(
+      await screen.findByText("The research service does not know ZZZZ. Check the ticker, or add it to the watchlist on Research."),
+    ).toBeInTheDocument();
+    expect(screen.queryByText("Checks")).toBeNull();
+  });
+});
diff --git a/web/features/stock/StockPage.tsx b/web/features/stock/StockPage.tsx
new file mode 100644
index 0000000..9b0cc94
--- /dev/null
+++ b/web/features/stock/StockPage.tsx
@@ -0,0 +1,167 @@
+"use client";
+
+import Link from "next/link";
+import { useQuery } from "@tanstack/react-query";
+import { ChevronLeft } from "lucide-react";
+import type { ComponentProps, JSXElementConstructor, ReactNode } from "react";
+import { ChecksSection } from "@/components/checks/ChecksSection";
+import { RefreshButton } from "@/components/shell/RefreshButton";
+import { NewsPanel } from "@/components/stock/NewsPanel";
+import { PriceChart } from "@/components/stock/PriceChart";
+import { SentimentPanel } from "@/components/stock/SentimentPanel";
+import { StatementsTable } from "@/components/stock/StatementsTable";
+import { SummaryPanel } from "@/components/stock/SummaryPanel";
+import { TechnicalsPanel } from "@/components/stock/TechnicalsPanel";
+import { Disclosure } from "@/components/ui/Disclosure";
+import { StatusWord } from "@/components/ui/StatusWord";
+import { NameNotes } from "@/features/market/NameNotes";
+import { ValueBlock } from "@/features/stock-value/ValueBlock";
+import type { ValueTicker } from "@/features/stock-value/types";
+import { ApiError, apiFetch } from "@/lib/api";
+import { relativeAge } from "@/lib/format";
+import { formatMoneyCell } from "@/lib/money";
+import { StockSection } from "./StockSection";
+import { nameLine, valueLeads, valueLines, type Analysis } from "./stock";
+
+// The generated types mark a nullable field optional; the panels' own types read it as a value or
+// null. The API always sends the key (pydantic writes None as null), so the shapes agree at runtime.
+type Props<C extends JSXElementConstructor<any>> = ComponentProps<C>;
+
+const PENDING_SECTIONS = ["fundamentals", "technicals", "sentiment", "news", "checks"] as const;
+
+function Shell({ children }: { children: ReactNode }) {
+  return <div className="mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4">{children}</div>;
+}
+
+function BackLink() {
+  return (
+    <Link
+      href="/research"
+      className="inline-flex min-h-11 items-center gap-1 text-[0.8125rem] font-semibold text-muted hover:text-content md:min-h-8"
+    >
+      <ChevronLeft size={16} aria-hidden="true" />
+      Research
+    </Link>
+  );
+}
+
+/** The last quote under the name: the price, "Delayed" in words when it is stale, and its age. */
+function QuoteLine({ quote }: { quote: Analysis["quote"] }) {
+  if (quote?.value == null) {
+    return (
+      <p className="mt-2 text-sm">
+        Last price <span className="hatch px-1 text-unknown">n/a</span>
+      </p>
+    );
+  }
+  return (
+    <p className="mt-2 flex flex-wrap items-center gap-x-2.5 gap-y-1">
+      <span className="tabular text-[1.5rem] font-extrabold tracking-[-0.015em]">{formatMoneyCell(quote.value)}</span>
+      {quote.stale && <StatusWord tone="flag">Delayed</StatusWord>}
+      <span className="text-[0.8125rem] text-muted">{relativeAge(quote.as_of)}</span>
+    </p>
+  );
+}
+
+/**
+ * The stock page (web overhaul Part 5): a back link to Research, the ticker as the title with its name
+ * and last price, then two columns from 1024px. Left: the price chart with the value book's levels
+ * drawn across it, the value block (first when the book would buy the name at a price or holds it,
+ * else at the foot of the column), Checks, Technicals and the financial statements (behind a
+ * disclosure). Right: the news service's notes, News, Sentiment and a model's written summary. The
+ * DOM order is the phone order. The page reads; its only command is the value block's "Run Claude's
+ * analysis".
+ */
+export function StockPage({ symbol }: { symbol: string }) {
+  const upper = symbol.toUpperCase();
+  const { data, isError, error } = useQuery({
+    queryKey: ["analysis", upper],
+    queryFn: () => apiFetch<Analysis>(`/research/${upper}`),
+    // Look again while any section is still being built.
+    refetchInterval: (q) => (PENDING_SECTIONS.some((s) => q.state.data?.[s]?.state === "pending") ? 5000 : false),
+    // A name the research service does not know will not appear in a minute; the rest are worth a retry.
+    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 2,
+  });
+  // The value block reads the same request under the same key, so this costs no second fetch.
+  const { data: value } = useQuery({
+    queryKey: ["value", "ticker", upper],
+    queryFn: () => apiFetch<ValueTicker>(`/value/${upper}`),
+  });
+  const leads = valueLeads(value);
+
+  const header = (
+    <header className="mt-1 flex items-start justify-between gap-3">
+      <div className="min-w-0">
+        <h1 className="text-2xl font-extrabold tracking-[-0.015em]">{upper}</h1>
+        <p className="mt-1 text-sm text-muted">{data ? nameLine(data) : isError ? "" : "Loading"}</p>
+        {data && <QuoteLine quote={data.quote} />}
+      </div>
+      <RefreshButton label={`Refresh ${upper}`} className="-mr-2 -mt-1" />
+    </header>
+  );
+
+  if (isError && !data) {
+    const missing = error instanceof ApiError && error.status === 404;
+    return (
+      <Shell>
+        <BackLink />
+        {header}
+        <p className="mt-3 text-sm">
+          {missing
+            ? `The research service does not know ${upper}. Check the ticker, or add it to the watchlist on Research.`
+            : "This page could not be loaded. It tries again when you reopen it."}
+        </p>
+      </Shell>
+    );
+  }
+
+  const section = (key: (typeof PENDING_SECTIONS)[number]) => ({
+    state: data?.[key]?.state ?? "pending",
+    reason: data?.[key]?.reason ?? null,
+  });
+  const valueBlock = <ValueBlock symbol={upper} />;
+
+  return (
+    <Shell>
+      <BackLink />
+      {header}
+      <div className="mt-4 grid items-start gap-x-6 gap-y-4 lg:grid-cols-[minmax(0,1fr)_340px]">
+        <div className="grid min-w-0 gap-4">
+          <section aria-labelledby="stock-chart-title">
+            <h2 id="stock-chart-title" className="sr-only">
+              {`${upper} price chart`}
+            </h2>
+            <PriceChart symbol={upper} lines={valueLines(value)} />
+          </section>
+          {leads && valueBlock}
+          <StockSection id="checks" title="Checks" {...section("checks")}>
+            {data?.checks?.data && <ChecksSection data={data.checks.data as Props<typeof ChecksSection>["data"]} />}
+          </StockSection>
+          <StockSection id="technicals" title="Technicals" {...section("technicals")}>
+            {data?.technicals?.data && <TechnicalsPanel data={data.technicals.data as Props<typeof TechnicalsPanel>["data"]} />}
+          </StockSection>
+          <StockSection id="statements" title="Financial statements" {...section("fundamentals")}>
+            {data?.fundamentals?.data && (
+              <Disclosure summary={<span className="text-sm font-semibold">Revenue, profit, balance sheet and cash flow, as filed</span>}>
+                <StatementsTable financials={data.fundamentals.data as Props<typeof StatementsTable>["financials"]} />
+              </Disclosure>
+            )}
+          </StockSection>
+          {!leads && valueBlock}
+        </div>
+        <div className="grid min-w-0 gap-4">
+          <NameNotes symbol={upper} />
+          <StockSection id="news" title="News" {...section("news")}>
+            {data?.news?.data && <NewsPanel items={data.news.data as Props<typeof NewsPanel>["items"]} />}
+          </StockSection>
+          <StockSection id="sentiment" title="Sentiment" {...section("sentiment")}>
+            {data?.sentiment?.data && <SentimentPanel data={data.sentiment.data as Props<typeof SentimentPanel>["data"]} />}
+          </StockSection>
+          <StockSection id="summary" title="Model summary" state="ready">
+            <SummaryPanel symbol={upper} />
+          </StockSection>
+        </div>
+      </div>
+    </Shell>
+  );
+}
diff --git a/web/features/stock/StockSection.tsx b/web/features/stock/StockSection.tsx
new file mode 100644
index 0000000..a5a9a6a
--- /dev/null
+++ b/web/features/stock/StockSection.tsx
@@ -0,0 +1,43 @@
+import type { ReactNode } from "react";
+import { Card } from "@/components/ui/Card";
+
+export type SectionState = "ready" | "pending" | "unavailable";
+
+/**
+ * One section of the stock page as a white card (web overhaul Part 5): its title, then the content
+ * once it is ready, or one sentence saying it is still being built or why it is not available. The
+ * reason comes from the API and is shown as written (`Section.reason`, src/api/models/research.py).
+ */
+export function StockSection({
+  id,
+  title,
+  state,
+  reason,
+  children,
+}: {
+  id: string;
+  title: string;
+  state: SectionState;
+  reason?: string | null;
+  children?: ReactNode;
+}) {
+  const titleId = `stock-${id}-title`;
+  return (
+    <Card aria-labelledby={titleId}>
+      <h2 id={titleId} className="text-[1.0625rem] font-bold">
+        {title}
+      </h2>
+      <div className="mt-2">
+        {state === "ready" ? (
+          children
+        ) : state === "pending" ? (
+          <p role="status" className="text-sm text-muted">
+            {reason ?? "Building this section. It will appear shortly."}
+          </p>
+        ) : (
+          <p className="text-sm text-muted">{reason ?? "Not available for this symbol."}</p>
+        )}
+      </div>
+    </Card>
+  );
+}
````

### Task 6: Size tier and tranche plan in the value block

**Files:** Modify `web/features/stock-value/format.ts`, `SizeBlock.tsx`, `format.test.ts`, `ValueBlock.test.tsx`;
this plan.

**What it does (rulings 3, 5):** `sizeSegment(l)`: for a priced list, "At this margin of safety a buy aims at 3% of the
book's ceiling, in 3 tranches.", "This margin of safety is below the first size tier, so the book would not buy." at
0, a hatched "Size if bought n/a" when unknown, nothing for a No list. `trancheWords(plan)`: "1 of 3 tranches bought
(the last on Oct 20, 2026). Tranche 2 waits for a higher low, at least 5 sessions after the last, and passes the
value gate again first."; "All 3 tranches are bought." when done; null (a hatched "Tranches bought n/a") when the
count is unknown. `SizeBlock` shows the tranche line under the holding and the size line under each list's entry
ceiling.

- [x] **Step 1: da-vinci** (copy is fixed; it checks the two new lines sit in the block's rhythm).
- [x] **Step 2: Check and apply `T6`.** `git status --short` shows the four files as `M`.
- [x] **Step 3: Red check.** `git stash push -- web/features/stock-value/format.ts web/features/stock-value/SizeBlock.tsx`,
  then `cd web && npx vitest run features/stock-value` shows `3 failed | 35 passed`; `git stash pop`.
- [x] **Step 4: Gate.** `npx vitest run features/stock-value`: 38 passed. Full vitest **1549 in 152 files**; tsc,
  lint clean; G1, G2, G3, G5.
- [x] **Step 5: Commit** `feat(web): the value block says the size tier and the tranche plan`.

<!-- block T6 -->
````diff
diff --git a/web/features/stock-value/SizeBlock.tsx b/web/features/stock-value/SizeBlock.tsx
index 00c4a90..14b5408 100644
--- a/web/features/stock-value/SizeBlock.tsx
+++ b/web/features/stock-value/SizeBlock.tsx
@@ -7,17 +7,21 @@ import {
   pointsPct,
   price,
   reasonCodeWords,
+  sizeSegment,
+  trancheWords,
 } from "./format";
-import { Hatched, Subhead } from "./parts";
+import { Hatched, Segments, Subhead } from "./parts";
 import type { ValueFile, ValuePlan } from "./types";
 
 /**
  * "How much, and when?": per list the timing state, the margin of safety the regime asks against
  * what this name has, the entry ceiling and why the baseline said what it said; for a held name,
- * what the book holds. The size tier and tranche plan are not in the API yet, so they are not shown.
+ * what the book holds and its tranche plan; per priced list the size tier its margin of safety
+ * reaches (web overhaul Part 5).
  */
 export function SizeBlock({ file, plan }: { file: ValueFile; plan: ValuePlan | null | undefined }) {
   const lists = file.lists ?? [];
+  const tranches = trancheWords(plan);
   return (
     <section aria-labelledby="vb-size" className="mt-4 border-t border-border pt-3">
       <h3 id="vb-size" className="text-sm font-bold">
@@ -30,8 +34,17 @@ export function SizeBlock({ file, plan }: { file: ValueFile; plan: ValuePlan | n
           list.
         </p>
       )}
+      {plan &&
+        (tranches ? (
+          <p className="mt-1 text-sm">{tranches}</p>
+        ) : (
+          <p className="mt-1 text-sm">
+            Tranches bought <Hatched />
+          </p>
+        ))}
       {lists.map((l) => {
         const timing = gateStateWord(l.timing ?? "unknown");
+        const size = sizeSegment(l);
         return (
           <div key={l.list_name} className="mt-4 first:mt-2">
             <Subhead>{listWords(l.list_name)}</Subhead>
@@ -46,6 +59,11 @@ export function SizeBlock({ file, plan }: { file: ValueFile; plan: ValuePlan | n
             <p className="tabular mt-1 text-sm">
               Entry ceiling {l.entry_ceiling == null ? <Hatched /> : price(l.entry_ceiling)}
             </p>
+            {size && (
+              <p className="tabular mt-1 text-sm">
+                <Segments parts={[size]} />
+              </p>
+            )}
             {(l.reasons ?? []).length > 0 && (
               <p className="mt-1 text-[0.8125rem] text-muted">
                 Why the baseline says {l.baseline_verdict.toLowerCase()}: {(l.reasons ?? []).map(reasonCodeWords).join("; ")}.
diff --git a/web/features/stock-value/ValueBlock.test.tsx b/web/features/stock-value/ValueBlock.test.tsx
index 262cbd8..e2df007 100644
--- a/web/features/stock-value/ValueBlock.test.tsx
+++ b/web/features/stock-value/ValueBlock.test.tsx
@@ -162,6 +162,14 @@ describe("ValueBlock", () => {
     expect(within(size).getByText(/20 shares at an average cost of \$150\.00/)).toBeInTheDocument();
   });
 
+  it("says the size tier per priced list and a held name's tranche plan", async () => {
+    show();
+    const size = await screen.findByRole("region", { name: "How much, and when?" });
+    expect(within(size).getByText("At this margin of safety a buy aims at 3% of the book's ceiling, in 3 tranches.")).toBeInTheDocument();
+    expect(within(size).getByText(/^1 of 3 tranches bought \(the last on Oct 20, 2026\)\. Tranche 2 waits for a higher low/)).toBeInTheDocument();
+    expect(within(size).queryByText(/Size if bought/)).toBeNull(); // the No list carries no size line
+  });
+
   it("lists a held name's re-evaluations as a short dated list", async () => {
     show();
     const list = await screen.findByRole("list", { name: "Re-evaluations" });
diff --git a/web/features/stock-value/format.test.ts b/web/features/stock-value/format.test.ts
index 01af8df..1b225d6 100644
--- a/web/features/stock-value/format.test.ts
+++ b/web/features/stock-value/format.test.ts
@@ -11,6 +11,8 @@ import {
   readWords,
   refetchMs,
   shortDate,
+  sizeSegment,
+  trancheWords,
 } from "./format";
 import type { ValuePlan, ValueTicker } from "./types";
 
@@ -91,4 +93,25 @@ describe("stock-value format", () => {
     expect(shortDate("2026-11-03")).toBe("Nov 3, 2026");
     expect(shortDate(null)).toBe("n/a");
   });
+  it("words the size tier for a priced list only, hatched when the margin is unknown", () => {
+    expect(sizeSegment({ verdict: "READY", size_pct: 5, tranches: 3 })).toEqual({
+      text: "At this margin of safety a buy aims at 5% of the book's ceiling, in 3 tranches.",
+    });
+    expect(sizeSegment({ verdict: "WAIT", size_pct: 0, tranches: 3 })?.text).toBe(
+      "This margin of safety is below the first size tier, so the book would not buy.",
+    );
+    expect(sizeSegment({ verdict: "WATCH", size_pct: null, tranches: 3 })).toEqual({ text: "Size if bought n/a", unknown: true });
+    expect(sizeSegment({ verdict: "NO", size_pct: 8, tranches: 3 })).toBeNull();
+  });
+  it("words the tranche plan: what is bought and what the next one waits for", () => {
+    expect(trancheWords(plan())).toBe(
+      "1 of 3 tranches bought (the last on Oct 20, 2026). Tranche 2 waits for a higher low, at least 5 sessions after the last, and passes the value gate again first.",
+    );
+    expect(trancheWords(plan({ tranches_done: 2 }))).toBe(
+      "2 of 3 tranches bought (the last on Oct 20, 2026). Tranche 3 waits for a close above the 50-day average, at least 5 sessions after the last, and passes the value gate again first.",
+    );
+    expect(trancheWords(plan({ tranches_done: 3 }))).toBe("All 3 tranches are bought.");
+    expect(trancheWords(plan({ tranches_done: null }))).toBeNull();
+    expect(trancheWords(null)).toBeNull();
+  });
 });
diff --git a/web/features/stock-value/format.ts b/web/features/stock-value/format.ts
index 101b46d..104d2cb 100644
--- a/web/features/stock-value/format.ts
+++ b/web/features/stock-value/format.ts
@@ -280,3 +280,38 @@ export function triggerWords(triggers: ValueReevaluation["triggers"]): string {
 export function claudeFor(lists: ValueClaudeList[] | undefined, name: string): ValueClaudeList | undefined {
   return (lists ?? []).find((c) => c.list_name === name);
 }
+
+const SIZED = new Set(["READY", "WATCH", "WAIT"]);
+
+/**
+ * The size tier a list's margin of safety reaches, as one line (web overhaul Part 5): only for a list
+ * the book would buy at a price; a hatched n/a when the margin is unknown, never 0.
+ */
+export function sizeSegment(l: Pick<ValueList, "verdict" | "size_pct" | "tranches">): Segment | null {
+  if (!SIZED.has(l.verdict)) return null;
+  if (l.size_pct == null) return { text: "Size if bought n/a", unknown: true };
+  if (l.size_pct <= 0) return { text: "This margin of safety is below the first size tier, so the book would not buy." };
+  return {
+    text: `At this margin of safety a buy aims at ${pointsPct(l.size_pct)} of the book's ceiling, in ${l.tranches} tranches.`,
+  };
+}
+
+/**
+ * A held name's tranche plan in words (spec section 9.5): what is bought, and what the next tranche
+ * waits for. The second waits for a higher low, any later one for a close above the 50-day average,
+ * each at least `tranche_min_sessions` after the last and gated again. Null when the count is unknown.
+ */
+export function trancheWords(
+  plan: Pick<ValuePlan, "tranches_done" | "tranches" | "tranche_min_sessions" | "last_tranche_on"> | null | undefined,
+): string | null {
+  if (!plan || plan.tranches_done == null) return null;
+  const done = plan.tranches_done;
+  const total = plan.tranches;
+  if (done >= total) return `All ${total} tranches are bought.`;
+  const last = plan.last_tranche_on ? ` (the last on ${shortDate(plan.last_tranche_on)})` : "";
+  const bought = done === 0 ? `None of the ${total} tranches is bought yet` : `${done} of ${total} tranches bought${last}`;
+  const next = done + 1;
+  const waits = done <= 1 ? "a higher low" : "a close above the 50-day average";
+  const gap = done === 0 ? "" : `, at least ${plan.tranche_min_sessions} sessions after the last`;
+  return `${bought}. Tranche ${next} waits for ${done === 0 ? "a Ready verdict" : waits}${gap}, and passes the value gate again first.`;
+}
````

---

## Section C: The sections, restyled in place (Tasks 7-9) · model: sonnet (effort medium)

**Reads:** this section; `web/DESIGN.md` (Colors: the Words First Rule; Components: StatusWord, Buttons; Surfaces:
Stock); the files each task names.

**Spec for da-vinci:** the Stock paragraph's "Words, not colours" and "Model summary" bullets. Classes and copy are
fixed by the patches; da-vinci may tune spacing only, and records each change.

**Entry checks:**

- [ ] **C1. Section B landed.** Four task commits since Section A; vitest 1549 in 152 files at the last gate.
- [ ] **C2. Every patch applies**: `git apply --check <S>/p5/T7.out`, `T8.out`, `T9.out` each print nothing.
- [ ] **C3. The tests the patches extend are as written:** `grep -c "it(" web/components/checks/CheckRow.test.tsx`
  prints 5; `web/components/checks/ChecksSection.test.tsx` 6; `web/components/stock/TechnicalsPanel.test.tsx` 2;
  `SentimentPanel.test.tsx` 5; `NewsPanel.test.tsx` 5; `SummaryPanel.test.tsx` 6.

**Section exit:** three task commits; vitest **1557 in 152 files**; tsc, lint clean; G1-G5.

### Task 7: Checks

**Files:** Modify `web/components/checks/{ChecksSection,CheckRibbon,CheckRow}.tsx`, `CheckRow.test.tsx`,
`ChecksSection.test.tsx`; this plan.

**What it does (ruling 16):** warnings on a `bg-sunk` block with "Caution" (flag) or "Note"; categories as hairline
rows (`min-h-11`, a 22 px chevron chip like `Disclosure`'s on expandable ones); the ribbon in ink (filled pass,
outlined fail, hatched unknown, sunk not applicable); a check row on two lines with its state as a `StatusWord`.

- [ ] **Step 1: da-vinci.**
- [ ] **Step 2: Check and apply `T7`.**
- [ ] **Step 3: Red check.** `git stash push -- web/components/checks/ChecksSection.tsx web/components/checks/CheckRibbon.tsx web/components/checks/CheckRow.tsx`,
  then `cd web && npx vitest run components/checks` shows `3 failed | 18 passed`; `git stash pop`.
- [ ] **Step 4: Gate.** `npx vitest run components/checks`: 21 passed. Full vitest **1552 in 152 files**; tsc, lint.
- [ ] **Step 5: Commit** `fix(web): checks say their state in words, in ink`.

<!-- block T7 -->
````diff
diff --git a/web/components/checks/CheckRibbon.tsx b/web/components/checks/CheckRibbon.tsx
index ee489e8..4fe3db2 100644
--- a/web/components/checks/CheckRibbon.tsx
+++ b/web/components/checks/CheckRibbon.tsx
@@ -68,14 +68,16 @@ function buildSegments(
 
 function segmentClass(state: SegmentState): string {
   switch (state) {
+    // Pass filled and fail hollow, both in ink: the state is the shape (and the data attribute and the
+    // label), never a colour (web overhaul Part 5; DESIGN.md keeps green and red for signed money).
     case "pass":
-      return "bg-gain";
+      return "bg-content";
     case "fail":
-      return "border border-loss";
+      return "border border-content";
     case "unknown":
       return "hatch";
     case "na":
-      return "bg-surface opacity-50";
+      return "bg-sunk";
   }
 }
 
diff --git a/web/components/checks/CheckRow.test.tsx b/web/components/checks/CheckRow.test.tsx
index f53fe01..fcb1d74 100644
--- a/web/components/checks/CheckRow.test.tsx
+++ b/web/components/checks/CheckRow.test.tsx
@@ -59,4 +59,18 @@ describe("CheckRow", () => {
     );
     expect(screen.getByTestId("check-row").dataset.state).toBe("fail");
   });
+
+  it("says Fail as a flag word and the bar beside the reading, never by colour alone", () => {
+    render(<CheckRow statement="Is the P/E ratio below 22?" state="FAIL" actual={30} threshold={22} />);
+    const word = screen.getByText("Fail");
+    expect(word.dataset.tone).toBe("flag");
+    expect(screen.getByText("Is the P/E ratio below 22?").closest("[data-testid=check-row]")?.textContent).toContain(
+      "Reads 30 · bar 22",
+    );
+  });
+
+  it("hatches an unknown bar too", () => {
+    render(<CheckRow statement="Is the yield above its average?" state="UNKNOWN" actual={2} threshold={null} />);
+    expect(screen.getByText("n/a").className).toContain("hatch");
+  });
 });
diff --git a/web/components/checks/CheckRow.tsx b/web/components/checks/CheckRow.tsx
index 35c81db..cbebd87 100644
--- a/web/components/checks/CheckRow.tsx
+++ b/web/components/checks/CheckRow.tsx
@@ -1,3 +1,4 @@
+import { StatusWord } from "@/components/ui/StatusWord";
 import { UNKNOWN } from "@/lib/format";
 
 export type CheckRowState = "PASS" | "FAIL" | "UNKNOWN" | "NOT_APPLICABLE";
@@ -29,43 +30,31 @@ function formatThreshold(threshold: number | number[] | null): string {
   return formatNumber(threshold);
 }
 
+/**
+ * One check (web overhaul Part 5): the question, its state as a word (a flag word for Fail), then
+ * what it read against the bar on a line of its own, so a phone never squeezes the question into a
+ * column. An unknown reading is a hatched n/a, never 0.
+ */
 export function CheckRow({ statement, state, actual, threshold, note }: CheckRowProps) {
-  const isUnknown = state === "UNKNOWN";
-
   return (
     <div
       data-testid="check-row"
       data-state={state.toLowerCase()}
-      className="flex items-center gap-4 border-t border-border py-2 text-sm first:border-t-0"
+      className="border-t border-border py-2.5 text-sm first:border-t-0"
     >
-      <div className="flex-1">
-        <p className="text-content">{statement}</p>
-        {note && <p className="mt-0.5 text-xs text-unknown">{note}</p>}
+      <div className="flex items-start justify-between gap-3">
+        <p className="min-w-0">{statement}</p>
+        <StatusWord tone={state === "FAIL" ? "flag" : "neutral"}>{STATE_LABEL[state]}</StatusWord>
       </div>
-      <span
-        className={`tabular w-16 shrink-0 text-right ${isUnknown ? "text-unknown" : "text-content"}`}
-      >
-        {actual === null ? UNKNOWN : formatNumber(actual)}
-      </span>
-      <span className="tabular w-24 shrink-0 text-right text-xs text-muted">
-        {formatThreshold(threshold)}
-      </span>
-      <span className={`w-24 shrink-0 text-right text-xs ${stateClass(state)}`}>
-        {STATE_LABEL[state]}
-      </span>
+      <p className="tabular mt-0.5 text-[0.8125rem] text-muted">
+        Reads{" "}
+        <span className={actual === null ? "hatch px-1 text-unknown" : "font-semibold text-content"}>
+          {actual === null ? UNKNOWN : formatNumber(actual)}
+        </span>
+        {" · bar "}
+        <span className={threshold === null ? "hatch px-1 text-unknown" : "text-content"}>{formatThreshold(threshold)}</span>
+      </p>
+      {note && <p className="mt-0.5 text-[0.8125rem] text-muted">{note}</p>}
     </div>
   );
 }
-
-function stateClass(state: CheckRowState): string {
-  switch (state) {
-    case "PASS":
-      return "text-gain";
-    case "FAIL":
-      return "text-loss";
-    case "UNKNOWN":
-      return "text-unknown";
-    case "NOT_APPLICABLE":
-      return "text-muted";
-  }
-}
diff --git a/web/components/checks/ChecksSection.test.tsx b/web/components/checks/ChecksSection.test.tsx
index 6d17b80..36c8057 100644
--- a/web/components/checks/ChecksSection.test.tsx
+++ b/web/components/checks/ChecksSection.test.tsx
@@ -101,4 +101,16 @@ describe("ChecksSection", () => {
     render(<ChecksSection data={payload()} />);
     expect(screen.queryByTestId("warning")).toBeNull();
   });
+
+  it("names a caution warning in words, not by a red border", () => {
+    render(
+      <ChecksSection
+        data={payload({
+          warnings: [{ level: "caution", title: "Daily-reset decay risk", detail: "Leveraged ETFs compound daily." }],
+        })}
+      />,
+    );
+    expect(screen.getByText("Caution").dataset.tone).toBe("flag");
+    expect(screen.getByTestId("warning").className).not.toContain("border-loss");
+  });
 });
diff --git a/web/components/checks/ChecksSection.tsx b/web/components/checks/ChecksSection.tsx
index c03f459..3d428f7 100644
--- a/web/components/checks/ChecksSection.tsx
+++ b/web/components/checks/ChecksSection.tsx
@@ -1,6 +1,9 @@
 "use client";
 
+import clsx from "clsx";
+import { ChevronDown } from "lucide-react";
 import { useState } from "react";
+import { StatusWord } from "@/components/ui/StatusWord";
 import { CheckRibbon } from "./CheckRibbon";
 import { CheckRow, type CheckRowState } from "./CheckRow";
 
@@ -55,19 +58,20 @@ export function ChecksSection({ data }: { data: ChecksPayloadData }) {
       {data.warnings.length > 0 && (
         <div className="space-y-2">
           {data.warnings.map((w, i) => (
-            <div
-              key={i}
-              data-testid="warning"
-              className="rounded-md border border-loss/40 bg-surface px-4 py-3 text-sm"
-            >
-              <p className="font-medium text-content">{w.title}</p>
-              <p className="mt-1 text-muted">{w.detail}</p>
+            <div key={i} data-testid="warning" className="rounded-xl bg-sunk px-3 py-2.5 text-sm">
+              <p className="flex flex-wrap items-center gap-x-2 gap-y-1">
+                <StatusWord tone={w.level === "caution" ? "flag" : "neutral"}>
+                  {w.level === "caution" ? "Caution" : "Note"}
+                </StatusWord>
+                <span className="font-semibold">{w.title}</span>
+              </p>
+              <p className="mt-1 text-[0.8125rem] text-muted">{w.detail}</p>
             </div>
           ))}
         </div>
       )}
 
-      <div className="divide-y divide-border rounded-md border border-border">
+      <div className="divide-y divide-border">
         {data.categories.map((cat) => {
           const isOpen = expanded === cat.category && !cat.not_applicable;
           return (
@@ -79,25 +83,35 @@ export function ChecksSection({ data }: { data: ChecksPayloadData }) {
                 onClick={() =>
                   setExpanded((current) => (current === cat.category ? null : cat.category))
                 }
-                className="flex w-full items-center justify-between gap-4 px-4 py-3 text-left disabled:cursor-default"
+                className="flex min-h-11 w-full flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5 text-left disabled:cursor-default"
               >
-                <span className="text-sm text-content">
-                  {CATEGORY_LABEL[cat.category] ?? cat.category}
+                <span className="text-sm font-semibold">{CATEGORY_LABEL[cat.category] ?? cat.category}</span>
+                <span className="flex items-center gap-2.5">
+                  <CheckRibbon
+                    category={cat.category}
+                    passed={cat.passed}
+                    failed={cat.failed}
+                    unknown={cat.unknown}
+                    total={cat.total}
+                    notApplicable={cat.not_applicable}
+                  />
+                  {!cat.not_applicable && (
+                    <span
+                      aria-hidden="true"
+                      className={clsx(
+                        "grid h-[22px] w-[22px] flex-none place-items-center rounded-full bg-sunk",
+                        "transition-transform duration-[180ms] ease-out motion-reduce:transition-none",
+                        isOpen && "rotate-180",
+                      )}
+                    >
+                      <ChevronDown size={14} strokeWidth={2.25} />
+                    </span>
+                  )}
                 </span>
-                <CheckRibbon
-                  category={cat.category}
-                  passed={cat.passed}
-                  failed={cat.failed}
-                  unknown={cat.unknown}
-                  total={cat.total}
-                  notApplicable={cat.not_applicable}
-                />
               </button>
-              {cat.not_applicable && cat.note && (
-                <p className="px-4 pb-3 text-xs text-muted">{cat.note}</p>
-              )}
+              {cat.not_applicable && cat.note && <p className="pb-2.5 text-[0.8125rem] text-muted">{cat.note}</p>}
               {isOpen && (
-                <div className="border-t border-border px-4 pb-3">
+                <div className="pb-2.5">
                   {cat.checks.map((chk) => (
                     <CheckRow
                       key={chk.id}
````

### Task 8: Technicals, Sentiment, News and the statements

**Files:** Modify `web/components/stock/{TechnicalsPanel,SentimentPanel,NewsPanel,StatementsTable}.tsx` and the first
three's tests; this plan.

**What it does (ruling 16):** Technicals as figure lines in two columns from 640 px with the phase and regime as words
(hatched when unknown); Sentiment's figure at 24 px with its word, the day's change signed and muted, each source a
figure line; News rows on hairlines with the tone as a neutral `StatusWord`; the statements' tables without their own
card fill (they sit in the section's card behind the disclosure), headers in the label style.

- [ ] **Step 1: da-vinci.**
- [ ] **Step 2: Check and apply `T8`.**
- [ ] **Step 3: Red check.** `git stash push -- web/components/stock/TechnicalsPanel.tsx web/components/stock/SentimentPanel.tsx web/components/stock/NewsPanel.tsx web/components/stock/StatementsTable.tsx`,
  then `cd web && npx vitest run components/stock/TechnicalsPanel components/stock/SentimentPanel components/stock/NewsPanel`
  shows `3 failed | 12 passed`; `git stash pop`.
- [ ] **Step 4: Gate.** The same three files: 15 passed; `npx vitest run components/stock/StatementsTable` passes
  unchanged. Full vitest **1555 in 152 files**; tsc, lint. `features/position/Headlines.tsx` is untouched
  (`git diff --stat main -- web/features/position` prints nothing).
- [ ] **Step 5: Commit** `fix(web): technicals, tone and headlines in words; the statements inside their card`.

<!-- block T8 -->
````diff
diff --git a/web/components/stock/NewsPanel.test.tsx b/web/components/stock/NewsPanel.test.tsx
index c324d00..f5eff8b 100644
--- a/web/components/stock/NewsPanel.test.tsx
+++ b/web/components/stock/NewsPanel.test.tsx
@@ -59,4 +59,10 @@ describe("NewsPanel", () => {
     render(<NewsPanel items={[]} />);
     expect(screen.getByText("No recent headlines.")).toBeInTheDocument();
   });
-});
\ No newline at end of file
+
+  it("says the tone as a neutral word, never green or red (web overhaul Part 5)", () => {
+    render(<NewsPanel items={items} />);
+    expect(screen.getByText("bullish").className).not.toMatch(/text-(gain|loss)/);
+    expect(screen.getByText("bearish").className).not.toMatch(/text-(gain|loss)/);
+  });
+});
diff --git a/web/components/stock/NewsPanel.tsx b/web/components/stock/NewsPanel.tsx
index 3d26a0a..5a6f0ab 100644
--- a/web/components/stock/NewsPanel.tsx
+++ b/web/components/stock/NewsPanel.tsx
@@ -1,3 +1,4 @@
+import { StatusWord } from "@/components/ui/StatusWord";
 import { relativeAge } from "@/lib/format";
 
 type NewsItem = {
@@ -26,42 +27,36 @@ export function sentimentTint(v: number | null): string {
 
 export function NewsPanel({ items }: { items: NewsItem[] }) {
   if (items.length === 0) {
-    return (
-      <p className="rounded-md bg-surface px-4 py-3 text-sm text-muted">
-        No recent headlines.
-      </p>
-    );
+    return <p className="text-sm text-muted">No recent headlines.</p>;
   }
 
+  // The tone is a word in a neutral status chip: it is not money, so it is never green or red on
+  // this page (web overhaul Part 5). `sentimentTint` stays for the position page's headlines.
   return (
-    <ul className="space-y-3">
+    <ul>
       {items.map((item, i) => {
-        const label = sentimentLabel(item.sentiment);
-        const tint = sentimentTint(item.sentiment);
         const age = relativeAge(item.published_at);
         return (
-          <li key={i} className="flex items-start gap-3 text-sm">
-            <div className="flex-1">
+          <li key={i} className="flex items-start gap-3 border-t border-border py-2.5 text-sm first:border-t-0">
+            <div className="min-w-0 flex-1">
               {item.url ? (
                 <a
                   href={item.url}
                   target="_blank"
                   rel="noopener noreferrer"
-                  className="text-content underline-offset-2 hover:underline"
+                  className="font-semibold underline-offset-2 hover:underline"
                 >
                   {item.title}
                 </a>
               ) : (
-                <span className="text-content">{item.title}</span>
+                <span className="font-semibold">{item.title}</span>
               )}
-              <div className="mt-0.5 flex gap-2 text-xs text-muted">
+              <div className="mt-0.5 flex flex-wrap gap-x-2 text-[0.8125rem] text-muted">
                 {item.source && <span>{item.source}</span>}
                 {age && <span>{age}</span>}
               </div>
             </div>
-            <span className={`tabular shrink-0 rounded bg-elevated px-2 py-0.5 text-xs ${tint}`}>
-              {label}
-            </span>
+            <StatusWord>{sentimentLabel(item.sentiment)}</StatusWord>
           </li>
         );
       })}
diff --git a/web/components/stock/SentimentPanel.test.tsx b/web/components/stock/SentimentPanel.test.tsx
index fdb5149..18dba85 100644
--- a/web/components/stock/SentimentPanel.test.tsx
+++ b/web/components/stock/SentimentPanel.test.tsx
@@ -54,4 +54,10 @@ describe("SentimentPanel", () => {
     expect(screen.getByText("n/a samples")).toBeInTheDocument();
     expect(screen.queryByText("0 samples")).not.toBeInTheDocument();
   });
-});
\ No newline at end of file
+
+  it("signs the day's change but never colours it: tone is not money (web overhaul Part 5)", () => {
+    render(<SentimentPanel data={{ ...full, delta_1d: -2.0 }} />);
+    const delta = screen.getByText("-2.0 1d");
+    expect(delta.className).not.toMatch(/text-(gain|loss)/);
+  });
+});
diff --git a/web/components/stock/SentimentPanel.tsx b/web/components/stock/SentimentPanel.tsx
index 390fdf2..b7bde39 100644
--- a/web/components/stock/SentimentPanel.tsx
+++ b/web/components/stock/SentimentPanel.tsx
@@ -20,43 +20,54 @@ function Score({
   label: string;
   score: number | null;
   // null when this source has no tracked sample count at all (not the same as a
-  // genuine zero) — rendering "0 samples" next to a real score would be a fabricated
+  // genuine zero): rendering "0 samples" next to a real score would be a fabricated
   // number, exactly what this panel exists to avoid.
   count: number | null;
 }) {
   return (
-    <div className="flex flex-col gap-0.5">
-      <span className="text-xs text-muted">{label}</span>
-      <span className={`tabular text-sm ${score === null ? "text-unknown" : "text-content"}`}>
-        {score === null ? UNKNOWN : score.toFixed(1)}
-      </span>
-      <span className={`text-xs ${count === null ? "text-unknown" : "text-muted"}`}>
-        {count === null ? `${UNKNOWN} samples` : `${count} samples`}
-      </span>
+    <div className="flex items-baseline justify-between gap-3 border-t border-border py-2 text-sm">
+      <dt className="text-muted">{label}</dt>
+      <dd className="text-right">
+        <span className={score === null ? "tabular hatch px-1 text-unknown" : "tabular font-semibold"}>
+          {score === null ? UNKNOWN : score.toFixed(1)}
+        </span>
+        <span className={`ml-2 text-[0.8125rem] ${count === null ? "text-unknown" : "text-muted"}`}>
+          {count === null ? `${UNKNOWN} samples` : `${count} samples`}
+        </span>
+      </dd>
     </div>
   );
 }
 
+/** Crowd and news tone for the name (web overhaul Part 5): one figure and its word, the day's change
+ * with its sign (tone is not money, so it is never green or red), then each source with its sample
+ * count. Enrichment only: nothing here reaches a gate or a size. */
 export function SentimentPanel({ data }: { data: Sentiment }) {
   return (
-    <div className="space-y-4">
-      <div className="flex items-baseline gap-4">
-        <span className={`tabular text-2xl ${data.overall === null ? "text-unknown" : "text-content"}`}>
+    <div>
+      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
+        <span
+          className={
+            data.overall === null
+              ? "tabular hatch px-1 text-[1.5rem] font-extrabold text-unknown"
+              : "tabular text-[1.5rem] font-extrabold tracking-[-0.015em]"
+          }
+        >
           {data.overall === null ? UNKNOWN : data.overall.toFixed(1)}
         </span>
-        <span className="text-sm text-muted">{data.label}</span>
+        <span className="text-sm font-semibold">{data.label}</span>
         {data.delta_1d !== null && (
-          <span className={`tabular text-xs ${data.delta_1d >= 0 ? "text-gain" : "text-loss"}`}>
+          <span className="tabular text-[0.8125rem] text-muted">
             {data.delta_1d >= 0 ? "+" : ""}
             {data.delta_1d.toFixed(1)} 1d
           </span>
         )}
-      </div>
-      <div className="flex flex-wrap gap-4">
+      </p>
+      <dl className="mt-2">
         <Score label="StockTwits" score={data.stocktwits} count={data.stocktwits_msgs} />
         <Score label="News" score={data.news} count={data.news_count} />
         <Score label="Reddit" score={data.reddit} count={null} />
-      </div>
+      </dl>
     </div>
   );
-}
\ No newline at end of file
+}
diff --git a/web/components/stock/StatementsTable.tsx b/web/components/stock/StatementsTable.tsx
index d0d721f..48ed563 100644
--- a/web/components/stock/StatementsTable.tsx
+++ b/web/components/stock/StatementsTable.tsx
@@ -28,23 +28,19 @@ const ROWS: [string, string][] = [
 
 function StatementBody({ periods }: { periods: Period[] }) {
   if (periods.length === 0) {
-    return (
-      <p className="rounded-md bg-surface px-4 py-3 text-sm text-muted">
-        No periods filed.
-      </p>
-    );
+    return <p className="text-sm text-muted">No periods filed.</p>;
   }
 
   return (
-    <div className="overflow-x-auto rounded-md bg-surface">
+    <div className="overflow-x-auto">
       <table className="w-full border-collapse text-sm">
         <thead>
           <tr className="border-b border-border">
-            <th className="px-4 py-3 text-left font-medium text-muted">Line item</th>
+            <th className="py-2 pr-3 text-left text-xs font-semibold tracking-[0.04em] text-muted">Line item</th>
             {periods.map((p) => (
               <th
                 key={p.period_end}
-                className="tabular px-4 py-3 text-right font-mono font-medium text-muted"
+                className="tabular px-3 py-2 text-right font-mono text-xs font-semibold text-muted"
               >
                 {formatPeriod(p.period_end)}
               </th>
@@ -54,7 +50,7 @@ function StatementBody({ periods }: { periods: Period[] }) {
         <tbody>
           {ROWS.map(([key, label]) => (
             <tr key={key} className="border-b border-border last:border-0">
-              <td className="px-4 py-2 text-content">{label}</td>
+              <td className="whitespace-nowrap py-2 pr-3">{label}</td>
               {periods.map((p) => {
                 const item = p.items[key];
                 // Hyphen, not an em dash, per web/CLAUDE.md "Zero em dashes in UI copy".
@@ -66,7 +62,7 @@ function StatementBody({ periods }: { periods: Period[] }) {
                   <td
                     key={p.period_end}
                     title={title}
-                    className={`tabular px-4 py-2 text-right font-mono ${
+                    className={`tabular whitespace-nowrap px-3 py-2 text-right font-mono ${
                       isUnknown ? "hatch text-unknown" : "text-content"
                     }`}
                   >
@@ -84,27 +80,21 @@ function StatementBody({ periods }: { periods: Period[] }) {
 
 export function StatementsTable({ financials }: { financials: Financials }) {
   return (
-    <div className="space-y-8">
+    <div className="space-y-5">
       {financials.annual.length > 0 && (
         <section>
-          <h3 className="mb-3 text-xs font-medium tracking-wide text-muted">
-            Annual
-          </h3>
+          <h3 className="mb-1 text-xs font-semibold tracking-[0.04em] text-muted">Annual</h3>
           <StatementBody periods={financials.annual} />
         </section>
       )}
       {financials.quarterly.length > 0 && (
         <section>
-          <h3 className="mb-3 text-xs font-medium tracking-wide text-muted">
-            Quarterly
-          </h3>
+          <h3 className="mb-1 text-xs font-semibold tracking-[0.04em] text-muted">Quarterly</h3>
           <StatementBody periods={financials.quarterly} />
         </section>
       )}
       {financials.annual.length === 0 && financials.quarterly.length === 0 && (
-        <p className="rounded-md bg-surface px-4 py-3 text-sm text-muted">
-          No statements filed.
-        </p>
+        <p className="text-sm text-muted">No statements filed.</p>
       )}
     </div>
   );
diff --git a/web/components/stock/TechnicalsPanel.test.tsx b/web/components/stock/TechnicalsPanel.test.tsx
index 7d422a5..2bb038d 100644
--- a/web/components/stock/TechnicalsPanel.test.tsx
+++ b/web/components/stock/TechnicalsPanel.test.tsx
@@ -41,4 +41,9 @@ describe("TechnicalsPanel", () => {
     expect(screen.getByText(/Phase: n\/a/)).toBeInTheDocument();
     expect(screen.getByText(/Regime: n\/a/)).toBeInTheDocument();
   });
-});
\ No newline at end of file
+
+  it("hatches an unknown figure (web overhaul Part 5)", () => {
+    render(<TechnicalsPanel data={{ ...full, rsi_14: null }} />);
+    expect(screen.getByText("n/a").className).toContain("hatch");
+  });
+});
diff --git a/web/components/stock/TechnicalsPanel.tsx b/web/components/stock/TechnicalsPanel.tsx
index 5c4d093..9db6fe2 100644
--- a/web/components/stock/TechnicalsPanel.tsx
+++ b/web/components/stock/TechnicalsPanel.tsx
@@ -15,43 +15,47 @@ type Technicals = {
 
 function Metric({ label, value }: { label: string; value: number | null }) {
   return (
-    <div className="flex flex-col gap-0.5">
-      <span className="text-xs text-muted">{label}</span>
-      <span className={`tabular text-sm ${value === null ? "text-unknown" : "text-content"}`}>
+    <div className="flex items-baseline justify-between gap-3 border-t border-border py-2 text-sm">
+      <dt className="text-muted">{label}</dt>
+      <dd className={value === null ? "tabular hatch px-1 text-unknown" : "tabular font-semibold"}>
         {value === null ? UNKNOWN : value.toFixed(2)}
-      </span>
+      </dd>
     </div>
   );
 }
 
-function Badge({ label, value }: { label: string; value: string | null }) {
+function Word({ label, value }: { label: string; value: string | null }) {
   if (!value) {
     return (
-      <span className="rounded px-2 py-0.5 text-xs text-unknown">{label}: {UNKNOWN}</span>
+      <span className="hatch inline-block rounded-[6px] px-2 py-px text-xs font-semibold tracking-[0.04em] text-unknown">
+        {label}: {UNKNOWN}
+      </span>
     );
   }
   return (
-    <span className="rounded bg-elevated px-2 py-0.5 text-xs text-content">
+    <span className="inline-block rounded-[6px] bg-sunk px-2 py-px text-xs font-semibold tracking-[0.04em] text-muted">
       {label}: {value}
     </span>
   );
 }
 
+/** The technicals as figure lines (web overhaul Part 5), two columns from 640px; the phase and the
+ * regime as words under them. An unknown figure is a hatched n/a, never 0. */
 export function TechnicalsPanel({ data }: { data: Technicals }) {
   return (
-    <div className="space-y-4">
-      <div className="flex flex-wrap gap-3">
+    <div>
+      <dl className="grid gap-x-6 sm:grid-cols-2">
         <Metric label="RSI 14" value={data.rsi_14} />
         <Metric label="MACD" value={data.macd} />
         <Metric label="Signal" value={data.macd_signal} />
         <Metric label="SMA 50" value={data.sma_50} />
         <Metric label="SMA 200" value={data.sma_200} />
         <Metric label="ATR 14" value={data.atr_14} />
-      </div>
-      <div className="flex gap-2">
-        <Badge label="Phase" value={data.phase} />
-        <Badge label="Regime" value={data.regime} />
-      </div>
+      </dl>
+      <p className="mt-3 flex flex-wrap gap-2">
+        <Word label="Phase" value={data.phase} />
+        <Word label="Regime" value={data.regime} />
+      </p>
     </div>
   );
-}
\ No newline at end of file
+}
````

### Task 9: The model summary

**Files:** Modify `web/components/stock/SummaryPanel.tsx`, `SummaryPanel.test.tsx`; this plan.

**What it does (rulings 7, 16, 17):** "Generate summary" is the secondary `Button` (44 px); a failed generation is a
`role="alert"` sentence in ink, not red; bull and bear points are plain ink bullets at a 65-character measure; caveats
sit on `bg-sunk`; the foot line reads "Written by <model>, a language model that decides nothing · data as of ...".

- [ ] **Step 1: da-vinci.**
- [ ] **Step 2: Check and apply `T9`.**
- [ ] **Step 3: Red check.** `git stash push -- web/components/stock/SummaryPanel.tsx`, then
  `cd web && npx vitest run components/stock/SummaryPanel` shows `2 failed | 6 passed`; `git stash pop`.
- [ ] **Step 4: Gate.** `npx vitest run components/stock/SummaryPanel`: 8 passed. Full vitest **1557 in 152 files**;
  tsc, lint; G1-G5.
- [ ] **Step 5: Commit** `fix(web): the stock page's summary names the model that wrote it`.

<!-- block T9 -->
````diff
diff --git a/web/components/stock/SummaryPanel.test.tsx b/web/components/stock/SummaryPanel.test.tsx
index 5519a87..92b5d2b 100644
--- a/web/components/stock/SummaryPanel.test.tsx
+++ b/web/components/stock/SummaryPanel.test.tsx
@@ -177,4 +177,17 @@ describe("SummaryPanel", () => {
     // The action to retry is still there — a failed generation doesn't wipe the panel.
     expect(screen.getByRole("button", { name: /Generate summary/i })).toBeInTheDocument();
   });
-});
\ No newline at end of file
+
+  it("says a language model wrote it and decides nothing, in plain ink (web overhaul Part 5)", async () => {
+    mockFetch({ as_of: "2026-09-05T12:00:00Z", symbol: "AAPL", state: "ready", summary: SUMMARY });
+    render(withProviders(<SummaryPanel symbol="AAPL" />));
+    expect(await screen.findByText(/Written by claude-sonnet-4-6, a language model that decides nothing/)).toBeInTheDocument();
+    expect(screen.getByText("ROE above 15%").className).not.toMatch(/text-(gain|loss)/);
+  });
+
+  it("asks for a summary with a secondary button, never lime", async () => {
+    mockFetch({ as_of: "2026-09-05T12:00:00Z", symbol: "AAPL", state: "unavailable", summary: null, reason: null });
+    render(withProviders(<SummaryPanel symbol="AAPL" />));
+    expect(await screen.findByRole("button", { name: "Generate summary" })).toHaveAttribute("data-variant", "secondary");
+  });
+});
diff --git a/web/components/stock/SummaryPanel.tsx b/web/components/stock/SummaryPanel.tsx
index 1165be5..fd35c04 100644
--- a/web/components/stock/SummaryPanel.tsx
+++ b/web/components/stock/SummaryPanel.tsx
@@ -1,6 +1,7 @@
 "use client";
 
 import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
+import { Button } from "@/components/ui/Button";
 import { apiFetch } from "@/lib/api";
 import { relativeAge } from "@/lib/format";
 
@@ -22,14 +23,14 @@ type SummaryResponse = {
   reason: string | null;
 };
 
-function List({ label, items, accent }: { label: string; items: string[]; accent?: string }) {
+function List({ label, items }: { label: string; items: string[] }) {
   if (!items.length) return null;
   return (
     <div className="space-y-1">
-      <span className="text-xs font-medium tracking-wide text-muted">{label}</span>
-      <ul className="space-y-1">
+      <span className="text-xs font-semibold tracking-[0.04em] text-muted">{label}</span>
+      <ul className="max-w-[65ch] list-disc space-y-1 pl-5">
         {items.map((item, i) => (
-          <li key={i} className={`text-sm ${accent ?? "text-content"}`}>
+          <li key={i} className="text-sm">
             {item}
           </li>
         ))}
@@ -64,16 +65,11 @@ export function SummaryPanel({ symbol }: { symbol: string }) {
         <p className="text-sm text-muted">
           {data?.reason ?? "No summary yet. Generate one on demand."}
         </p>
-        <button
-          type="button"
-          disabled={generating}
-          onClick={() => generate.mutate()}
-          className="rounded-md bg-elevated px-4 py-2 text-sm text-content transition-opacity hover:opacity-80 disabled:opacity-50"
-        >
+        <Button variant="secondary" disabled={generating} onClick={() => generate.mutate()}>
           {generating ? "Generating..." : "Generate summary"}
-        </button>
+        </Button>
         {generate.isError && (
-          <p className="text-sm text-loss">
+          <p role="alert" className="text-sm">
             Generation failed. The rest of the page is unaffected; try again later.
           </p>
         )}
@@ -82,12 +78,12 @@ export function SummaryPanel({ symbol }: { symbol: string }) {
   }
 
   return (
-    <div className="space-y-5">
-      <p className="text-sm text-content">{summary.thesis}</p>
+    <div className="space-y-4">
+      <p className="max-w-[65ch] text-sm">{summary.thesis}</p>
 
-      <div className="grid gap-5 sm:grid-cols-2">
-        <List label="Bull points" items={summary.bull_points} accent="text-gain" />
-        <List label="Bear points" items={summary.bear_points} accent="text-loss" />
+      <div className="grid gap-4">
+        <List label="Bull points" items={summary.bull_points} />
+        <List label="Bear points" items={summary.bear_points} />
       </div>
 
       {summary.watch_items.length > 0 && (
@@ -95,8 +91,8 @@ export function SummaryPanel({ symbol }: { symbol: string }) {
       )}
 
       {summary.caveats.length > 0 && (
-        <div className="space-y-1 rounded-md bg-surface px-4 py-3">
-          <span className="text-xs font-medium tracking-wide text-muted">Caveats</span>
+        <div className="space-y-1 rounded-xl bg-sunk px-3 py-2.5">
+          <span className="text-xs font-semibold tracking-[0.04em] text-muted">Caveats</span>
           <ul className="space-y-1">
             {summary.caveats.map((c, i) => (
               <li key={i} className="text-sm text-muted">
@@ -108,7 +104,7 @@ export function SummaryPanel({ symbol }: { symbol: string }) {
       )}
 
       <p className="text-xs text-muted">
-        {summary.model} · data as of {relativeAge(summary.data_as_of)}
+        Written by {summary.model}, a language model that decides nothing · data as of {relativeAge(summary.data_as_of)}
         {state === "stale" ? " · stale" : ""}
       </p>
     </div>
````

---

## Section D: Finish (Tasks 10-11) · sonnet; then opus review, sonnet fix pass

**Entry checks:**

- [ ] **D1. Sections A-C landed** (nine task commits after A0); every gate green at the C exit; G1-G6.
- [ ] **D2. The docs patch applies**: `git apply --check <S>/p5/T10.out` prints nothing. If it fails because
  `STATUS.md`, `ARCHITECTURE.md`, `web/CLAUDE.md` or `docs/web/api.md` moved on `main`, apply its hunks by hand (each
  names its file and the lines around it), record a ruling, and continue: docs only.
- [ ] **D3. A browser for Task 11**: `ls ~/.npm/_npx/*/node_modules/playwright-core/package.json` lists at least one
  path (the capture harness uses it headless), or the Playwright MCP loads. Neither: ask the operator.

### Task 10: Docs (sonnet, effort medium)

**Files:** Modify `STATUS.md` (a "Built (2026-11-06 — web overhaul Part 5: the stock page)" section above the
2026-11-05 drawdown section, the Web overhaul row in "Web platform", the value book Part 6 "Deferred (web, Sections
F-I)" bullet), `ARCHITECTURE.md` (the Routes paragraph, a `features/stock/` bullet, the `routers/value.py` and
`value_db.py` rows), `web/CLAUDE.md` (the `stock/[symbol]/`, `checks/`, `stock/` and `stock-value/` entries, a new
`features/stock/` entry), `docs/web/api.md` (`claude_note`, `size_pct`, `tranches`, the plan's tranche fields); this plan.

- [ ] **Step 1: Check and apply `T10`.**
- [ ] **Step 2: Fill in what the patch could not know.** In the new STATUS Built section, after "Plan:", add the
  commit range (`git log --oneline main..HEAD | tail -1` to the head) and every ruling from the Progress log that
  changed behaviour; under "Deferred", add any minor a section recorded. Keep the section's existing sentences.
- [ ] **Step 3: Gate.** G3; `grep -n "no tranche plan or size tier\|has no Claude note field" STATUS.md` prints
  nothing; `grep -c "features/stock/" ARCHITECTURE.md web/CLAUDE.md` prints a non-zero count for each; `git status --short` shows only the four docs and this plan. Docs only: no test run needed.
- [ ] **Step 4: Commit** `docs: web overhaul Part 5`.

<!-- block T10 -->
````diff
diff --git a/ARCHITECTURE.md b/ARCHITECTURE.md
index a609856..bb61599 100644
--- a/ARCHITECTURE.md
+++ b/ARCHITECTURE.md
@@ -963,9 +963,9 @@ enforces it by grepping those three packages' source text.
 | `spreads_db.py` | **Web overhaul Part 1 (Task 8).** `spreads_read_session()` — a read-only (`mode=ro`, URI) engine on `data/spreads.db`, the only way `src/api/` reaches it: the spreads fence forbids `src/api/` importing `src.spreads`, so it reads with plain SQL (`try_read_spread_rows` / `read_spread_rows`, typed `text()` selects so stored timestamps come back as datetimes). Yields `None` when the file is absent or is not an openable SQLite database (probed with `SELECT count(*) FROM sqlite_master`), so routes answer `available: false` instead of a 500. Asserted by `tests/test_web_fence.py::test_only_spreads_db_opens_the_spreads_file_in_the_api`. **Web overhaul Part 2 (Task 1)** adds `try_read_pick_rows(session, day=)` (the day's `spread_picks` rows, newest first, `menu` and `send_reasons` parsed; `None` when the table is missing, meaning the picker never ran), `try_read_spread_rows_opened(session, start=, end=)` (every mode's `spread_positions` opened in a New York day, oldest first, tolerating a table without `pick_id`) and `read_activity_days(session)` (the New York days that have a pick or an opened spread), with the `_json_list`, `_columns_of` and `_stamp` helpers. Still plain SQL over the `mode=ro` engine. **Web overhaul Part 3** adds `try_read_spread_order_rows(session, start=, limit=)` (the book's filled `spread_orders`, newest first, joined to their `spread_positions` row for the spread's side, expiry and strikes; `None` when the read fails, as it does on an older file with no `spread_orders` table, which the route turns into `available: true` with no orders). Still plain SQL over the `mode=ro` engine. |
 | `spread_inputs.py` | **Web Home follow-ups (2026-10-15).** The book's `spread_positions` rows as the plain inputs the reporting builders take: `spread_pay_inputs(book)` (`SpreadPayInput`, for the pay stub) and `spread_day_inputs(book)` (`SpreadDayInput`, for the day's cards, the calendar and the position page), and `spread_position_out(row, now)`, the one row-to-model map `GET /spreads/positions` and the position route share. All return `None` when `data/spreads.db` could not be read, which the routes turn into `spreads_available: false`. Reads only through `spreads_db.py`, never `src.spreads`. |
 | `routers/spreads.py` + `models/spreads.py` | **Web overhaul Part 1 (Task 8).** `GET /spreads/positions?status=open|closed|all&mode=paper|shadow|baseline&limit=` (owner-only, read-only): `SpreadPositionsResponse` (`available`, `underlying`, `mode`, `positions: SpreadPositionOut[]`); `realized_pnl_usd` is `null` while open, timestamps served as UTC. The API still writes exactly one table and imports nothing from `src.spreads`. **Web overhaul Part 2 (Task 1)** adds `GET /spreads/picks?day=YYYY-MM-DD` (owner-only, read-only; default today in New York, a bad date is 422): `SpreadPicksResponse` (`available`, `underlying`, `mode`, `ai_enabled`, `day`, `previous_day`, `next_day`, `picks`, `positions`) with `SpreadPickOut` (Claude's choice and reason, the fallback reason, the letter sent, whether it was refused or did not fill, the menu) and `SpreadMenuItemOut`. Each stored menu is parsed with the shared `SpreadMenuItem` schema; one that no longer parses is `menu_readable: false` with an empty `menu`, never a 500. `available: false` only for a missing file or an unreadable `spread_positions`; a file without `spread_picks` is `available: true` with no picks. Helpers: `_now`, `_new_york_day_bounds`, `_menu_item_out`, `_pick_out`. **Web overhaul Part 3** adds `GET /spreads/orders?days=&limit=` (owner-only, read-only): `SpreadOrdersResponse` (`available`, `underlying`, `orders: SpreadOrderOut[]`, and since Part 4 `truncated`: the window held more than `limit` orders; the route asks for `limit + 1` rows and returns `limit`), the spreads book's filled orders for the Fills page's credit-spread section. `available: false` for a missing or unreadable file and for a `spread_orders` table that exists but cannot be read (`try_read_spread_order_rows` returns `None` for a failed read); an older file without the table is `available: true` with no orders, and a row's spread fields are `null` when its position row is missing. |
-| `value_db.py` | **Value book Part 6 (Task 13).** `value_read_session()` — a read-only (`mode=ro`, URI) engine on `data/value.db`, yielding `None` when the file is missing or not a database; the only module in `src/api/` that names `value_db_url_abs`. Plain-SQL readers returning dicts (`read_top`, `read_positions`, `read_proposals` with each fingerprint, `read_funding`, `book_state`, `used_usd`, `read_ticker_row`, `read_effective`, `read_claude`, `read_reevaluations`) and, for Home's money, `read_value_pay_inputs()` / `read_value_day_inputs()` (a sale's realised dollars are proceeds less the shares' running average cost; a fill with no price is left out). A failed read is None, never an empty book. |
+| `value_db.py` | **Value book Part 6 (Task 13).** `value_read_session()` — a read-only (`mode=ro`, URI) engine on `data/value.db`, yielding `None` when the file is missing or not a database; the only module in `src/api/` that names `value_db_url_abs`. Plain-SQL readers returning dicts (`read_top`, `read_positions`, `read_proposals` with each fingerprint, `read_funding`, `book_state`, `used_usd`, `read_ticker_row`, `read_effective`, `read_claude`, `read_reevaluations`; since web overhaul Part 5 `read_top` also reads each row's latest CLI `why` and `read_positions` each position's `tranches_done` and `last_tranche_on`) and, for Home's money, `read_value_pay_inputs()` / `read_value_day_inputs()` (a sale's realised dollars are proceeds less the shares' running average cost; a fill with no price is left out). A failed read is None, never an empty book. |
 | `value_lookup.py` | **A ticker file fresh on open (Task 14, ruling 24).** `lookup(symbol, user)`: a stored file whose freshness key equals the key of the cheap parts now is `stored`; a stale or absent one is computed `now` with the pure `src.value.scorecard.build_scorecard` over `src.common.value_inputs` (research.db `mode=ro`, yfinance market facts, `news.db` earnings through `news_db.py`) on a daemon thread inside `research.tiers.materialization_budget_seconds`, with exactly one `value_snapshot` command (`src.api.commands.submit`, deduped on the symbol and fingerprint) carrying the input set; a stored file that is still fresh sends one `value_snapshot` with an empty fingerprint instead (the view mark, at most once a day per name, keyed `value_snapshot:<SYMBOL>:viewed:<date>` and checked in any status with `api.commands.dedupe_key_seen`, a read-only existence check on the key; it scans the table, which is fine at today's volumes); filings or bars missing from research.db are `pending` and queue the research ingest; past the budget the stored file. It never opens value.db for writing. |
-| `routers/value.py` + `models/value.py` | **Value book Part 6 (Task 13), read-only, owner-only.** `GET /value/top?list=`, `GET /value/book`, `GET /value/positions?status=` and `GET /value/{symbol}` (`docs/web/api.md`, "Value book"). The API imports from `src.value` only `scorecard` and `schemas` (`tests/test_value_fence.py::test_the_api_imports_only_scorecard_and_schemas_from_value`); Claude's text and numbers are one block labelled `source: "claude"`. A web click on a proposal is a `POST /commands` of a `value_*` kind that the value process drains, so the API still writes exactly one table. Web overhaul Part 4: `GET /value/book` carries `drain_healthy` and `drain_last_seen`, read from `system_settings.value_drain_heartbeat` through `src/api/settings_read.py` (no value.db read; healthy within `max(2 x commands_poll_seconds, 300 s)`). |
+| `routers/value.py` + `models/value.py` | **Value book Part 6 (Task 13), read-only, owner-only.** `GET /value/top?list=`, `GET /value/book`, `GET /value/positions?status=` and `GET /value/{symbol}` (`docs/web/api.md`, "Value book"). The API imports from `src.value` only `scorecard` and `schemas` (`tests/test_value_fence.py::test_the_api_imports_only_scorecard_and_schemas_from_value`); Claude's text and numbers are one block labelled `source: "claude"`. A web click on a proposal is a `POST /commands` of a `value_*` kind that the value process drains, so the API still writes exactly one table. Web overhaul Part 4: `GET /value/book` carries `drain_healthy` and `drain_last_seen`, read from `system_settings.value_drain_heartbeat` through `src/api/settings_read.py` (no value.db read; healthy within `max(2 x commands_poll_seconds, 300 s)`). Web overhaul Part 5: each `ValueListOut` carries `size_pct` (the tier its effective margin of safety reaches on `value.book.tiers`, capped at `name_cap_pct`; None when the margin is unknown) and `tranches`; `_size_pct` mirrors `src.value.sizing.tier_pct`, which the API may not import, and `tests/test_api_value.py` holds the two equal. `ValuePlanOut` carries `tranches_done`, `tranches`, `tranche_min_sessions` and `last_tranche_on`; `ValueTopItem.claude_note` is the latest non-superseded CLI verdict's `why` on one line (at most 200 characters; never a local model's). |
 | `models/portfolio.py` | **P3-P4 M2** — the response shapes for the four portfolio routes: `AccountBlock`/`ExposureBlock`/`PortfolioSummaryResponse` (2.1), `OptionLeg`/`StockLeg`/`PositionGroup`/`PositionsResponse` (2.2), `CampaignLeg`/`CampaignSummary`/`CampaignsResponse` (2.3), `CalendarEntry`/`CalendarDay`/`CalendarResponse` (2.4). All built on `Envelope`/`Sourced` from `models/common.py`. **Web overhaul Part 1:** `AccountValueResponse` (`series: AccountValueSeries`). |
 | `settings_read.py` | `read_setting(db, key) -> str \| None` / `parse_setting_dt(raw) -> datetime \| None` — the system_settings-row reader shared by `routers/options.py`'s `drain_healthy` and `routers/system.py`'s heartbeat rows, extracted so the two routers can't drift on how a setting is read or parsed. |
 | `routers/system.py` | **The left-rail status card's backend.** `GET /system/status` (owner-only) returns 7 rows — Trading DB / Research DB (a live `SELECT 1` each), Data providers (`src.data.breaker.breaker_states()`, rolled up to the worst state), Command drain / Intraday monitor / Research worker (each a heartbeat-age check — `ok` within 2x that process's own poll interval, `down` if stale, `unknown` if the heartbeat has never been written this run — never a false "down" on a cold start; the Research worker is the one exception, with its own fixed `_RESEARCH_WORKER_MAX_AGE` of 2 minutes rather than 2x a poll interval, since research jobs only heartbeat on success), and IBKR connection (an aggregate of the two `_ibkr_connected` flags `intraday.py` and `command_drain.py` now write alongside their heartbeats, `down` if either daemon disagrees or its heartbeat is stale). No row for `web_api` itself (a failed fetch of this very endpoint *is* that signal) or `eod_report` (a daily batch job, not a thing that's "up" at a point in time). **A broken `trading_db`/`research_db` connection degrades gracefully rather than 500ing the whole endpoint** (final review fix #1): the initial `SELECT 1` reachability check for each DB sets a `trading_ok`/`research_ok` flag, and every later read of that same DB — `read_setting` for the drain/monitor/ibkr-connected keys, `read_heartbeat()` for the research-worker row — is skipped when its flag is `False`, in favour of an honest `"unknown"` row with a `"... DB unreachable — cannot read heartbeat"` detail, since a `Session` that already raised once re-raises (`PendingRollbackError`) on any further use. `GET /system/{name}/log` tails that daemon's log file (`name` through a fixed allowlist — `approval`/`monitor`/`research`, mapped to the real paths in `scripts/start.py`'s `SERVICES` dict, never built from the request), filtered server-side to WARNING+ by default (`level=info` widens to INFO+), capped at 150 lines, and carries a `file_exists` bool distinguishing a genuinely missing log file from one that exists but has no lines at the requested level (final review fix #3) — the frontend renders "No log file yet" only for the former. |
@@ -1591,7 +1591,7 @@ reskinned without an edit. The structure it added:
   Universe, News, Ledger, How it works, What Claude knows and statement import, system status and Credits),
   `/more/claude` (What Claude knows: the market picture, the regime and its limits, what each Claude call reads),
   `/positions/[underlying]/[slug]` (a position's page; on a held short option it carries the Roll card, so
-  Propose a roll lives there, not on Trades), plus `/stock/[symbol]` and `/explain` unchanged and the
+  Propose a roll lives there, not on Trades), plus `/stock/[symbol]` (recomposed in Part 5, below) and `/explain` unchanged and the
   ledger's own pages `/ledger/trades`, `/ledger/ticker/[symbol]` and `/ledger/import` (restyled in Part 3; they lead back to
   Activity, Ledger, and `/ledger` itself redirects there). `next.config.ts` redirects the old URLs with a 307: `/options` →
   `/trades`, `/options/:id` → `/trades/:id`, `/pnl` → `/activity`, `/ledger` → `/activity?view=ledger`, `/universe` →
@@ -1603,8 +1603,9 @@ reskinned without an edit. The structure it added:
   campaigns, campaign and calendar panels; the P&L shell; the ledger tab strip), removed `GET /nav`, and kept
   `components/<domain>` where it is (the "fold into `features/`" idea was cut). **The rule for new code: it goes in
   `features/`; `components/` keeps `ui`, `shell`, the protected `options` controls, `value` and the survivors.**
-  Parts 5-8 (the stock page; Research, Universe and search; News, More and How it works; the value record) and
-  order control have no plan yet.
+  **Part 5 (2026-11-06, `docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md`) recomposed the stock
+  page** (`features/stock/`, below). Parts 6-8 (Research, Universe and search; News, More and How it works; the
+  value record) and order control have no plan yet.
 - **`app/` boundaries and titles** — web overhaul Part 4: the root `layout.tsx` sets `metadata.title` to
   `{ default: "IBKR Income", template: "%s · IBKR Income" }`; each server page exports its own `metadata`, and a
   client page gets a sibling server `layout.tsx` that exports `metadata` (or `generateMetadata` for a dynamic
@@ -1630,6 +1631,15 @@ reskinned without an edit. The structure it added:
   Activity's At IBKR list (a Value chip in `ExecutionsList`); every value position row links to the stock page's
   value block, and the "Value book unavailable" flag on Home and Activity is hidden only when the book is off and has
   never written.
+- **`features/stock/`** — web overhaul Part 5: the stock page (`/stock/[symbol]`; `page.tsx` only mounts
+  `StockPage`). A back link to Research, the ticker, name and last price ("Delayed" in words when stale), then one
+  grid as the position page's: the chart (`components/stock/PriceChart`, ink candles with the value book's fair
+  value, entry ceiling, half sale and stop as dashed lines from `stock.ts::valueLines`), the value block
+  (`features/stock-value/ValueBlock`, first when `valueLeads` says the book would buy the name at a price or holds
+  it), Checks, Technicals and the statements (behind a disclosure) on the left; the news service's notes, News,
+  Sentiment and the model summary on the right. Each section is a `StockSection` card. It reads
+  `GET /research/{symbol}` and `GET /value/{symbol}` (the value block's own query key, so one fetch); its only
+  command is the value block's `AnalyseButton`.
 
 The paragraphs below describe the pages as they were built; their file paths moved with the routes
 above (`app/page.tsx` → `app/research/page.tsx`, `app/universe/` → `app/research/universe/`,
diff --git a/STATUS.md b/STATUS.md
index d5f77d9..0da040e 100644
--- a/STATUS.md
+++ b/STATUS.md
@@ -347,6 +347,45 @@ Operator to-dos: re-copy `config/examples/value.yaml`'s `telegram:` and `prompt_
 
 ---
 
+## Built (2026-11-06 — web overhaul Part 5: the stock page)
+
+Plan: `docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md` (branch `feat/web-overhaul-5`; the plan's
+Progress log holds each task's commit, gate and rulings). Part 5 recomposes `/stock/[symbol]` on the payslip and
+gives the value book's figures their place on it. It adds no command site (the page's only one is still the value
+block's `AnalyseButton`) and no token, colour, font, radius or elevation; the protected decide, confirm, receipt,
+halt, autonomy and roll-mode components, `lib/commands.ts` and `lib/receipt.ts` are byte-identical to `main`.
+
+**Built, one line per task:**
+
+- **API (Task 1):** `GET /value/{symbol}` lists carry `size_pct` (the size tier the effective margin of safety
+  reaches, capped at the name cap; `null` when the margin is unknown, never 0) and `tranches`; a held name's `plan`
+  carries `tranches_done`, `tranches`, `tranche_min_sessions` and `last_tranche_on`; `GET /value/top` items carry
+  `claude_note` (Claude's own `why` on one line, CLI reads only). The API still imports only `scorecard` and
+  `schemas` from `src.value`; `_size_pct` mirrors `src.value.sizing.tier_pct` and a test holds them equal.
+- **Contract (Task 2):** `docs/web/openapi.json` and `web/lib/api-types.ts` regenerated; the typed value fixtures
+  gained the new keys.
+- **The stock page (Tasks 3-5):** `features/stock/` (`StockPage`, `StockSection`, `stock.ts`); a back link to
+  Research, the ticker, name and last price with "Delayed" in words; the chart and the cards in one grid as the
+  position page's; the value block first for a name the book would buy at a price or holds, else at the foot;
+  `SectionShell` deleted.
+- **The chart (Task 4):** `PriceChart` draws ink candles (up hollow, down filled), light volume bars, the two averages
+  and the value book's fair value, entry ceiling, half sale and stop as dashed lines, with a sentence for a screen
+  reader and a line of words naming every series; loading, empty and failed states in words.
+- **Size and tranches (Task 6):** the value block's "How much, and when?" says the size tier per priced list and a
+  held name's tranche plan.
+- **The sections (Tasks 7-9):** Checks, Technicals, Sentiment, News, the statements and the model summary restyled
+  in place: state words (Fail as a flag word, "Caution" on a warning), hatched n/a, no green or red on anything that
+  is not money, "Generate summary" a secondary button, the summary labelled by its model.
+
+**Deferred:**
+
+- "What changed since last time" still has no field of its own (value book Part 6 ruling G5): a held name's
+  re-evaluations carry it.
+- The chart shows one year with no range chips and no pointer readout (the bars endpoint is fixed at a year; the
+  position page's chips slice closes only).
+- Top opportunities shows `claude_note` from web overhaul Part 6, with the Research page.
+- The search palette is still mounted only on Research (Part 6, HANDOFF S1).
+
 ## Built (2026-11-05 — drawdown window, hero change per range, spreads card health)
 
 - **The drawdown breaker no longer halts every morning.** The log showed `Drawdown $108-123K from
@@ -562,9 +601,9 @@ book is still off until `value.book.enabled`.
   cards. (Fixed in the final fix pass, no longer deferred: `book.totals` now carries a running average cost shared
   with the API through `src/common/value_cost.py`, and a trim offer that went stale is no longer the end of the
   episode.)
-- **Deferred (web, Sections F-I).** Top opportunities has no Claude note field (`ValueTopItem` has none) and its
-  stop is always null today. The stock page shows no tranche plan or size tier (`GET /value/{symbol}` does not
-  expose them). The calendar's value split costs one extra request per month opened (`GET /pnl/calendar?
+- **Deferred (web, Sections F-I).** Top opportunities' Claude note is in the API since web overhaul Part 5
+  (`ValueTopItem.claude_note`) and shown on the card from Part 6; its stop is always null today. The stock page
+  shows the tranche plan and the size tier since Part 5. The calendar's value split costs one extra request per month opened (`GET /pnl/calendar?
   strategy=value`; the cell's figure is still the whole day, and `MonthPay.net` keeps value out). The
   `value_available=false` flag showed under All on installs that never ran the value process (value.db absent)
   until web overhaul Part 4 Task 10 (the web now hides it only when `/value/book` says the book is off and has
@@ -1117,7 +1156,7 @@ the first alias with any facts was wrong), `select_periods` (enforces `kind`, la
 | **P2 — Options console (M1+M2+M3 built 2026-09-06, reviewed; M4 Tasks 4.1+4.2+4.3+4.4 built 2026-09-06; M5 Tasks 5.1+5.2+5.3+5.4 built 2026-09-07; M6 Tasks 6.1+6.2+6.3+6.4 built 2026-09-07; M7 Tasks 7.1-7.7 built 2026-09-07 — P2 complete)** | **M1 — Write foundation:** the intent queue exists, the drain runs with no registered handlers, and no web action can reach an order until M3. `AppCommandRow` (`src/storage/models.py`) + `src/storage/app_commands.py` (enqueue/dedupe/mark/expire helpers); `src/api/models/commands.py` (`CommandKind` enum, typed payloads per kind, `validate_payload`, `dedupe_key_for`, `CommandStatus` — `UniversePayload.list_name` is `Literal["would_own", "watchlist"]` so `sectors`/`leveraged_etfs` fail parsing); `src/api/trading_db.py` gains a write-scoped `get_command_engine` + `command_session` with a `before_flush` listener (`WriteFenceViolation`) that rejects any flush targeting a non-`app_commands` table; `src/api/commands.py` is the only module allowed to import `get_command_engine`/`command_session` (`submit` enqueues, `get_status` reads through the read-only engine, `clear_confirm_token` clears a live-mode token after confirmation); `src/api/routers/commands.py` adds `POST /commands`, `GET /commands/{id}`, `POST /commands/{id}/confirm` (owner-only, dedupe returns 200 not 201, live-mode order-reaching intents get a `confirm_token`); `src/notify/command_drain.py` + `_command_drain_loop` in `approval_service` (fails unknown kinds loudly, isolates throwing handlers, skips commands awaiting confirmation, runs with `ib is None`, writes `command_drain_heartbeat` to `system_settings` after every cycle so `/options/controls` can tell a live drain from a dead one); `tests/test_web_fence.py` gains three P2 fence tests (write-handle leak — greps for both `get_command_engine` and `command_session`, command writer names no other table, trading path still never imports the web layer); the token proxy (`web/app/api/[...path]/route.ts`) moves `API_TOKEN` server-side — `NEXT_PUBLIC_API_TOKEN` is purged from the repo, the built bundle no longer contains the token. **M2 — Read surfaces:** the console exists and is worth opening, still unable to do anything. `GET /options/approvals` + `/approvals/{id}` (`src/api/routers/options.py`, `src/api/models/options.py`) — a four-table join (approval/candidate/risk-verdict/claude-review) through the read-only engine, snapshot-first when the candidate has been pruned, the five review fields rendered separately never as one blob. `GET /options/assessed` implements the promotable table from spec §5.2 exactly (`risk_gate`/`generator` never promotable), ranked like `scan.py::_rank_assessed`, `limit` caps the total across groups not per symbol. `GET /options/orders`, `/fills`, `/shorts` (nulls stay null — `avg_fill_price`/`mark`/`unrealized_pnl` never fabricate `0`; `shorts.as_of` is the snapshot's capture time, not request time). `GET /options/controls` reads `command_drain_heartbeat` against twice the poll interval — never reuses `/health`'s research-worker heartbeat, defaults to unhealthy, never `true` on a drain that has never run. Web: `web/app/options/page.tsx` + `[approvalId]/page.tsx`, `web/components/options/*` (`ApprovalsList`/`ApprovalCard`, `AssessedBrowser` with stage badges that are never colour-alone, `OrdersTable`/`FillsTable`/`ShortsTable`, `ControlsStrip`, `ApprovalDetail`/`ReviewPanel`/`IdealZoneBar`/`AlternativesTable`) — no approve/reject/promote/roll control anywhere, asserted by a frontend test. The rail flip (`src/api/routers/meta.py`) makes `/options` available. A Sonnet verification pass (2026-09-06) live-browser-tested every tab and the detail page against the real dev stack and found the console **completely unreachable** for reasons outside M1/M2's own code: `web/.env.local` still carried the pre-M1 `NEXT_PUBLIC_API_URL`/`NEXT_PUBLIC_API_TOKEN` names instead of the migrated `API_URL`/`API_TOKEN`, so every proxied request 500'd; and `app_commands` (M1 Task 1.1) had never been created in the real `data/income_system.db` because table creation only runs via the trading daemon's own `init_db()` startup path, which nobody had triggered since the model was added. Both are environment/ops gaps, not code defects, and are now fixed locally (`.env.local` corrected, `init_db()` run once). The pass also found and fixed two real code defects: `GET /options/approvals/{id}` raised `MultipleResultsFound` (500) whenever a candidate had been assessed across more than one scan run — completely ordinary, since `risk_verdicts` stores one row per assessed contract *per run* — fixed by ordering both the verdict and review lookups by `created_at` descending and taking the newest; and `web/app/options/[approvalId]/page.tsx` was missing `"use client"`, crashing on every real navigation to it (masked in tests by the component-level test harness). **None of M1 or M2 had ever been `git commit`ed** despite every task's checklist saying so — this is almost certainly why a later M3 session, working from git-tracked state, concluded the console UI "never landed" even though it existed on disk and worked once the environment gaps above were fixed; see `Web plan/milestones/P2/M3-approve-reject.md`'s correction note. All gates green after the fixes: `python -m pytest -q` (1755 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (100 passed) `&& npm run lint && npm run build`, plus a live click-through of every `/options` tab and an approval detail page with zero console errors. **M3 — Approve and reject (built 2026-09-06, opencode/glm-5.3):** the first web action that can cause an order to exist, through the exact Telegram code path. `src/notify/command_drain.py` registers `approve`/`reject` handlers that call `approval_service._process_button` **unchanged** (a monkeypatch test fails if a refactor forks the mutation); an already-decided approval is `applied` neutrally ("Already {status}" in `result.decision`), a replayed drain creates no second order (all four §4.5 idempotency layers hold, asserted in `tests/test_drain_approve_reject.py`), and neither handler needs `ib` — TWS down still queues the order. The drain stores a handler's result dict verbatim and gains `CommandFailed(reason, detail)` for machine-readable failures. The live-mode second confirmation now fails closed exactly per spec §4.6: a wrong/missing token is **403 and does not clear the field** (`tests/test_live_confirmation.py` covers token creation by kind, the drain's skip, the confirm-then-apply round-trip, the 403/409 split, and the TTL sweep), the outstanding `confirm_token` is surfaced through the owner-only `CommandStatus` so the frontend can complete the round-trip, and confirming a not-awaiting command is 409. `tests/test_write_path_invariants.py` asserts the phase invariants in one place: every `/options`+`/commands` route is owner-gated (globbed via route introspection), no route module imports the write handle, Telegram and the console cannot double-decide an approval into two orders, a crashed drain re-applies exactly once, and the API still holds no `ib_async` import. Web: `web/lib/receipt.ts` (`receiptState` — pending never renders as applied, `submitted` only when an order is working, `filled` only when a fill exists, stalled stated in words), `CommandReceipt` (the §9.2 signature component — intent id always visible, humanised failure reasons, no spinner when stalled), `ConfirmAction` (confirm dialog: exact contract/count, case-sensitive typed-word gate for M6's halt, focus trap + Escape + focus return, aria-modal, reduced-motion entry), `web/lib/commands.ts` (`submitCommand`/`confirmCommand`/`useCommandStatus` polling every 2s while pending, stopping at a terminal state), and `DecideControls` — the shared decide flow on both the approval card and the detail page: confirm dialog before any request, one `POST /commands`, controls disabled while in flight, a decided approval renders its decision not controls, 403 renders a permission message, and in live mode a distinct clearly-labelled second LIVE confirmation (cancelling it leaves the intent queued and unconfirmed, stated in the receipt). The M2 no-action-buttons guards evolved with the milestone: the controls now exist and are asserted wired through the confirm gate. **The existing execution-time `[CONFIRM LIVE]` path is untouched and still fires after a web live approve.** All gates green: `python -m pytest -q` (1776 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (130 passed) `&& npm run lint && npm run build`. **M4 — Promote, Tasks 4.1+4.2+4.3+4.4 (built 2026-09-06):** promote is now a real gated action, belt and braces. **Task 4.1 — the API-boundary promotable-stage guard:** `src/api/routers/commands.py`'s `assert_promotable` refuses `POST /commands` for a `promote` before any `app_commands` row exists unless the candidate's most recent `risk_verdicts` row is at `score_floor`/`dedupe`/`top_n` (spec §5.2's promotable table) — `risk_gate`/`generator` are never promotable, `passed` already has an approval, an unknown `candidate_id` is `404`, a non-promotable stage is `409 {"reason": "stage_not_promotable", "stage": ...}`. **Task 4.2 — the drain handler re-prices and re-gates for real:** `src/notify/command_drain.py`'s `promote` handler does not trust the stored row it was asked to promote — it re-runs the single-ticker pricing path (`src.orchestrator.scan._price_and_gate_ticker`, extracted from `run_ticker_scan` as a pure refactor — same chain fetch, analytics, CC/CSP screens, scoring, `validate_candidates` gate, and `record_assessments` audit write, zero behavior change to `run_ticker_scan` itself) for the requested symbol, searches the gate-passed output for the exact `(strategy, strike, expiry)`, and only then calls the new `src/execution/promote_pipeline.py::queue_promoted_for_approval` (mirrors `roll_pipeline.queue_roll_for_approval`'s `has_active_order` guard and `CandidateRow`/`ApprovalRow` upsert, minus the generation half — it takes the fresh `TradeCandidate` directly) to raise a PENDING approval. Nothing from the stored `RiskVerdictRow` reaches the approval except the tuple used to find the fresh match; every number on the approval — including a re-gate that now rejects (`gate_rejected`, reasons surfaced verbatim, by design) — comes from this run. Failure reasons (`broker_unavailable`, `chain_unavailable`, `contract_not_priced`, `gate_rejected`, `score_below_minimum`) are documented verbatim in `docs/web/commands.md`. `drain_once` now awaits a handler's result when it returns one (coroutine handlers, needed for promote's re-scan; every earlier sync handler is unaffected). All gates green: `python -m pytest -q` (1804 passed), `ruff check .`, `mypy src`. **Task 4.3 — the promote control and its receipt in the frontend (built 2026-09-06):** `AssessedBrowser`'s per-contract `<li>` was extracted into its own `web/components/options/AssessedRow.tsx` component (a pure, behavior-preserving extraction — every existing `AssessedBrowser.test.tsx` test kept passing unmodified), which now carries a Promote button rendered only when `promotable` is true and `strike`/`expiry` are both non-null (a promotable row with either unexpectedly null falls through to the non-promotable rendering rather than send `null` to the API). Promoting reuses the M3 decide flow exactly: `ConfirmAction` first (explaining in one sentence that the contract is priced and gated again and an approval appears only if it still passes; a `score_floor` row's dialog additionally shows the blended score and `promote_note`'s configured-minimum text verbatim), then `submitCommand("promote", {candidate_id, symbol, strategy, strike, expiry})` fires once, `useCommandStatus` polls to a terminal state, and `<CommandReceipt/>` renders the outcome unmodified (`order` is always `null` — a promote never has approve/reject's working-order lifecycle) — a live-mode response routes through the same second LIVE confirmation `DecideControls` uses. On `applied`, a "View approval" link to `/options/{approval_id}` renders when `result.approval_id` is non-null. `AssessedBrowser` now also fetches `GET /options/controls` itself (same pattern as `ApprovalsList`) so a promoted row's receipt can state a dead drain in words. All gates green: `python -m pytest -q` (1805 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (150 passed) `&& npm run lint && npm run build`. **Task 4.4 — the promote refusal tests (built 2026-09-06):** `tests/test_write_path_invariants.py` gains the belt-and-braces coverage for the whole milestone: `test_no_promote_path_exists_for_a_gate_rejected_contract` enqueues a promote command directly (bypassing Task 4.1's API-boundary guard entirely, the way a malformed or bypassed request would) for a `risk_gate`-staged contract and asserts the drain handler's own re-gate still refuses it; `test_the_promote_handler_runs_the_real_rules_engine` wraps (not mocks) `validate_candidates` with a spy to prove the real Rules Engine is what's called, not a stand-in; `test_promotable_stages_match_the_spec_exactly` pins `PROMOTABLE_STAGES == {"score_floor", "dedupe", "top_n"}` so a future edit that widens it fails here first. **M5 — Roll on demand, Tasks 5.1+5.2+5.3+5.4 (built 2026-09-07, opencode/glm-5.2):** the operator can ask the system to propose a roll for any open short, without waiting for the intraday monitor to fire an alert. Two steps, never one: the console proposes; the operator approves that proposal through M3's path. **Task 5.1 — the `roll_request` drain handler:** `src/notify/command_drain.py`'s `_roll_request` resolves the position from a live `get_positions(ib)` read, fetches a fresh chain + IV/technical stats through `src.execution.roll_pipeline.fetch_roll_inputs` (the shared chain-fetch path extracted from the monitor's `_try_queue_roll`, which was refactored to call it — behavior unchanged; the same three helpers composed inline are now one function two callers share, so the web and the monitor cannot drift on how a roll is priced), and calls `queue_roll_for_approval` **unchanged**. The handler disambiguates the pipeline's `None` **before** calling it: it runs `generate_roll_candidates(..., defensive=True)` itself to derive the same candidates the pipeline will choose from (same function, same inputs, same deterministic ids), and checks `_existing_roll_in_flight` against **every** one of them, not just the top-ranked one (post-M5 verification fix, 2026-09-07 — see "Bug fixed" note below) — covering both an active order (`active_order_for`, the new row-level companion to `has_active_order` in `src/storage/orders.py`) and an existing PENDING approval. Either → `roll_already_working` with `detail.approval_id` so the receipt links to the in-flight proposal; empty/failed chain → `chain_unavailable` with the provider message; no candidates → `no_qualifying_roll`; non-short or absent position → `not_an_open_short` / `position_not_found`; `ib is None` → `broker_unavailable`. The PENDING-approval check is what closes the monitor-vs-web race `has_active_order` alone would miss (the monitor's roll raises a PENDING `ApprovalRow`, no `OrderRow` until approved) — the milestone's headline acceptance criterion ("a monitor alert and a web request produce exactly one approval") requires it. `tests/test_drain_roll.py` carries the nine specified tests (seven from the plan + `position_not_found` + `chain_unavailable`), mocking only the IBKR/network boundary so the real `generate_roll_candidates` economics run. Failure reasons documented verbatim in `docs/web/commands.md`'s roll_request section. **Task 5.4 — roll degradation tests (built 2026-09-07):** `tests/test_write_path_invariants.py` gains three invariants: a behavioral tripwire + source scan proving the handler never reaches `execute_roll` directly (no `roll_executor` import, no `execute_roll(` call in `command_drain.py` or `roll_pipeline.py`); the verbatim token grep proving no `max_debit`/`min_delta_reduction`/`roc_pct` leaked into `command_drain.py`; and a `wraps`-spy on `generate_roll_candidates` at both call sites proving `defensive=True` flows through the handler's pre-check and the pipeline's internal call (the web roll is the monitor's roll). Reuses the `drain_env`/`fake_chain` fixtures from `tests/test_drain_roll.py` the same sanctioned way the file already imports the promote fixtures. **Task 5.2 — the roll control on the shorts list (built 2026-09-07):** `web/components/options/ShortsRow.tsx` extracted from `ShortsTable` (the same extraction `AssessedRow` got from `AssessedBrowser`), carrying the row's cells plus the confirm-then-submit-then-receipt flow that mirrors `AssessedRow`'s promote control exactly. The control is labelled "Propose a roll" (not "Roll" — the button does not roll the position, and the copy says so); `ConfirmAction` states plainly that the system will price a roll, raise it for approval, and nothing executes until that proposal is approved; `submitCommand("roll_request", {position_symbol})` fires once; `useCommandStatus` polls to terminal. `no_qualifying_roll` renders as a plain sentence in a `data-state="answered"` box (no `text-loss` chrome) — special-cased in `ShortsRow` so `CommandReceipt` stays untouched and every existing receipt test stays green. `roll_already_working` renders the failed receipt plus a "View the roll already in flight" link to `result.detail.approval_id`; success renders a "View approval" link to `result.approval_id`. The control is disabled while in flight and wired through the live-mode second confirmation (roll_request is in `_LIVE_CONFIRM_KINDS`). `ShortsTable` now fetches `GET /options/controls` (same pattern as `ApprovalsList`) so a roll receipt can state a dead drain in words; defaults healthy while loading. The M2 "asserts no roll button exists" guard evolved into the roll-control suite (17 tests in `ShortsTable.test.tsx`). **Task 5.3 — roll alerts on the shorts list (built 2026-09-07):** `_TRIGGER_LABELS` + `humanize_trigger` moved from `src/notify/formatters.py` to `src/monitor/triggers.py` (beside the codes they name); `formatters._humanize_trigger` is now an alias import, so every existing formatter caller works unchanged and the identity `formatters._humanize_trigger is triggers.humanize_trigger` is asserted in `tests/test_api_shorts.py`. `RollAlertSummary` gains `trigger_label` (humanised server-side via the shared mapping) and `claude_recommendation` (passed through from `RollAlertRow`, nullable). The API router imports `humanize_trigger` from `src.monitor.triggers` — not the notify layer — so the "API must not pull in the notify layer" fence holds. The web renders `trigger_label` verbatim, the alert age as text via `relativeAge`, and Claude's view labelled "Model opinion (Claude): ..." — distinct from any deterministic number on the row. A position with no alerts renders nothing extra (not "No alerts"). **A Sonnet verification pass (2026-09-07)** checked the opencode/glm-5.2 build against this plan and the live gate (test count, ruff, mypy, vitest, lint, build all reproduced exactly as claimed) and found one real defect in Task 5.1's own new code: `_roll_request` derived the same candidate `queue_roll_for_approval` would pick and checked only that single, top-ranked candidate for an in-flight roll. Under `defensive=True` every candidate's `roc_pct` is hardcoded `0.0` (rolls are judged on risk reduction, not yield, per D4), so `generate_roll_candidates`'s ROC-desc sort is a no-op tie and "the top-ranked candidate" is really just whichever qualifying quote the chain happened to list first — a property of chain order, not economics. Two fetches taken minutes apart (the monitor's, then the web's) can list the same qualifying strikes in a different order, so the monitor's already-PENDING candidate can silently drop to second-or-later without ceasing to qualify — and the handler would then fail to recognise it as in flight, racing the monitor into a second approval for the same position, exactly the case the milestone's headline acceptance criterion exists to prevent. Fixed by checking every one of `generate_roll_candidates`'s qualifying candidates against `_existing_roll_in_flight`, not just `candidates[0]` — bounded to the handful of strikes/expiries one chain fetch returns, so the cost is negligible. Regression test: `tests/test_drain_roll.py::test_an_in_flight_roll_is_caught_even_when_no_longer_top_ranked` (constructs two qualifying candidates whose chain order flips between the monitor's fetch and the web's, and confirms it reproduces the double-approval against the pre-fix code). Also flagged, not fixed (pre-dates M5, lives in `rolling.py`'s N20-era economics, out of scope for a drain-handler fix): the same `roc_pct = 0.0` fact means the monitor's own roll selection has never actually picked the "best" defensive roll by any economic measure, only the first one the chain lists — worth a human look at whether defensive rolls should rank by delta-reduction, liquidity, or credit instead of an always-tied ROC. All gates green after the fix: `python -m pytest -q` (1827 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (163 passed) `&& npm run lint && npm run build`. **M6 — Controls, Tasks 6.1+6.2+6.3+6.4 (built 2026-09-07, opencode/glm-5.3):** halt, resume and the autonomy rung are reachable from the browser, with the confirmation weights deliberately asymmetric. **Task 6.1 — the drain handlers:** `src/notify/command_drain.py` registers `halt`/`resume`/`set_autonomy`, thin resolvers over the same `system_settings` helpers Telegram's `/halt`, `/resume`, `/autonomy` use (`set_halted`/`set_autonomy_level` — one halt flag, read through `HALT_KEY`; a token-grep test pins that the literal `execution_halted` never appears in the drain). All three apply with `ib is None`: halting matters most exactly when something is wrong, and "TWS is unreachable" is a common shape of wrong. Halt/resume are idempotent (`applied`, never `failed` — halting an already-halted system satisfies the intent; so does resuming an un-halted one, resolving the M1 doc's `not_halted` failure mode as a satisfied intent instead); an empty halt reason is stored as `"halted from the web console"` so `/status` and the console always say something; `resume` records who released the switch in the command's `result` (`released_by`); each handler sends a Telegram notification — the one place a handler notifies, because control-plane changes have no order-poll loop to report them later, and a halt raised from the browser must be visible wherever the operator is. `set_autonomy` enforces the same promotion evidence gate Telegram does (`promotion_blockers` must be empty, else the command fails with `promotion_refused` + `detail.blockers`) so the web is not the rung ladder's back door; demotion always applies. `tests/test_drain_controls.py` carries 13 tests including the six specified verbatim. **Task 6.2 — payload validation:** `HaltPayload.reason` is capped at 200 chars (`422` past it — the reason is rendered by `/status` and the halt banner, an unbounded string there is a rendering bug waiting to happen), and the empty-payload kinds (`halt`/`resume`/`set_autonomy`/`refresh`) are `extra="forbid"` so a client typo is caught rather than ignored — all at parse time, before a command row exists (asserted). Control kinds carry no `dedupe_key` (M1's convention, pinned) and are never in `_LIVE_CONFIRM_KINDS` — the deliberate asymmetry, stated in a comment at the set so it does not look like an oversight: the live token is for intents that can reach an order, and a halt must never be slowed by a second step (asserted for halt with `cfg.is_live` true). **Task 6.3 — the controls panel:** `web/components/options/HaltControl.tsx` (halt is ONE CLICK, no dialog — speed is the feature, and a test name says so; resume requires the typed word RESUME, disabled until it matches exactly case-sensitively) and `AutonomyControl.tsx` (four rungs rendered from the API's `rungs` array, never hardcoded; a rung change click-through confirms showing current and target rungs; a refused promotion renders `promotion refused` with the blockers through the receipt). `ControlsStrip` now hosts both plus an unmissable halted banner at the top of the console (reason and time as text, fill and text never colour alone; honest "unknown time" when no halt command row exists, e.g. a breaker trip) and a `drain_healthy: false` line stating "the trading service is not draining commands" beside the controls — a queued-but-undraining halt is this milestone's worst case. Both controls disable while their own command is in flight, render `CommandReceipt`, invalidate the controls query on terminal so the strip moves on the next poll, and route a live-mode response through the same second LIVE confirmation (unreachable in practice for these kinds, but the shape is shared). `ConfirmAction`'s docstring corrected: the typed word is used by `resume` in M6, not `halt` (the milestone refined design §9.3's first draft). `GET /options/controls` gains `halted_at`, derived from the most recent applied `halt` command's `applied_at` — the "no new setting keys" rule and the banner's "time it was halted" are reconciled without a new key, and a breaker-tripped halt honestly renders no time rather than a fabricated one. 22 new frontend tests across `HaltControl.test.tsx`, `AutonomyControl.test.tsx`, `ControlsStrip.test.tsx`. **Task 6.4 — controls invariants:** `tests/test_write_path_invariants.py` gains the three specified tests (parametrised every-control-kind-applies-without-a-broker over the reused `drain_env` fixture; `test_control_kinds_never_require_live_confirmation` pinning `_LIVE_CONFIRM_KINDS`; `test_the_halt_key_is_the_same_one_telegram_uses` with the verbatim token grep). All gates green: `python -m pytest -q` (1856 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (185 passed) `&& npm run lint && npm run build`. **A Sonnet verification pass (2026-09-07)** checked the opencode/glm-5.3 build against this plan and the live gate (all six commands reproduced exactly as claimed) and found one real defect: `GET /options/controls`' `halted_at` derivation had no lower bound, so a resumed web halt followed by a later, command-row-less halt (a circuit-breaker trip, or a Telegram `/halt` — neither writes an `AppCommandRow`) surfaced the *earlier* halt's timestamp instead of the honest `null` design decision 1 promised for exactly that case; the one existing null-case test only covered a fresh DB with no prior halt rows and never exercised the halt→resume→halt sequence. Fixed by bounding the halt lookup (`routers/options.py::controls`) to applied strictly after the most recent applied `resume` row. Regression test: `tests/test_api_controls.py::test_halted_at_does_not_leak_a_stale_timestamp_from_a_prior_halt_cycle`. All gates green after the fix: `python -m pytest -q` (1857 passed), `ruff check .`, `mypy src` (web gate unaffected, not re-run). **M7 — Universe editing (Tasks 7.1-7.7 built 2026-09-07):** the two soft universe lists — `would_own` and `watchlist` — become editable from the browser, without `sectors` or the risk engine ever becoming reachable from the web. **Task 7.1 — the override store:** `UniverseOverrideRow` (`src/storage/models.py`, unique on `(symbol, list_name)`) holds one row per operator add/remove — upper-cased `symbol`, `action: "add"|"remove"`, `created_by`/`created_at` audit trail; `src/storage/universe_overrides.py`'s `set_override`/`clear_override`/`all_overrides` each take an explicit `session`, and `set_override` is a total-replace upsert — a later call for the same pair overwrites `action`/`created_by`/`created_at` in place, so an add followed by a remove is one row, never two to reconcile at read time. **Task 7.2 — the composer:** `src/common/universe.py::effective_universe()` composes `universe_overrides` onto `config/universe.yaml`, returning a dict shaped exactly like `get_config().universe`. Only `would_own`/`watchlist` are overridable (`OVERRIDABLE_LISTS = frozenset({"would_own", "watchlist"})`); every other key — `sectors`, `strike_bands`, `indexes`, `actively_wheeling`, `leveraged_etfs` — passes through byte-identical, proven even against a stray override row inserted directly under `list_name="sectors"`. A `remove` override on a symbol currently in `actively_wheeling` is ignored when composing `would_own` — you cannot stop being willing to own something you are actively wheeling. An unreadable overrides table falls back to the YAML base untouched and logs a warning; it never raises and never empties the universe. A 60-second TTL cache (a plain `(dict, time.monotonic())` tuple) avoids a DB round-trip on every read; `invalidate_universe_cache()` forces recompute so a web edit is visible immediately in the process that applied it, not up to 60s later. Ordering is deterministic: YAML file order, then added symbols in `created_at` order. **Task 7.3 — six consumers migrated** from `get_config().universe` to `effective_universe()`: `src/strategies/cash_secured_put.py` (the CSP eligibility check — the single most consequential edit in the milestone, proven end-to-end by a test that adds an override and confirms `generate_csp_candidates` actually changes its output), `src/orchestrator/scan.py` (symbol selection), `src/orchestrator/eod_report.py` (two sites — the daily IV-history refresh set and the EOD watchlist report), and `src/api/routers/universe.py` / `routers/research.py` (three read sites across the two files). `src/engine/risk_engine.py`, `src/ibkr/market_data.py`'s `strike_bands`, and every `actively_wheeling`/`sectors` read elsewhere are deliberately untouched — not overridable. An autouse `tests/conftest.py` fixture resets the TTL cache around every test. **Task 7.4 — the write path:** `GET /universe` gains `lists: [{name, overridable, entries: [{symbol, overridden, removed, created_by, created_at}]}]` (four lists, `indexes`/`watchlist`/`would_own`/`actively_wheeling`, only the latter two `overridable`) and flips `editable` to `true`; `would_own`/`watchlist` entries are the union of the YAML base and every override row for that list, not just the filtered effective list, so a removed YAML-base symbol stays visible (greyed out) with a revert path. New routes `POST`/`DELETE /universe/{list_name}/{symbol}` (owner-only, thin wrappers over the same command-queue path `POST /commands` uses) narrow `list_name` to `Literal["would_own", "watchlist"]` so any other value is `422` before a command row can exist; an unknown symbol (checked against the research symbol directory) is `404`; removing an `actively_wheeling` symbol specifically from `would_own` is `409`. The drain handlers `_universe_add`/`_universe_remove` (`src/notify/command_drain.py`) call `set_override` — never `clear_override`, since a remove must always record an explicit suppressing row, even for a YAML-base symbol, because deleting the row would silently do nothing for one — then `invalidate_universe_cache()`. Neither handler can fail (all validation already happened at the API boundary) and neither sends a Telegram notification, deliberately — a universe edit is reversible, non-urgent config, unlike halt/resume/set_autonomy. **One fix-loop round, the only one across the whole milestone:** the initial `GET /universe` entries-union silently dropped a genuinely reachable state — a symbol added via override then removed again, leaving a non-base `action="remove"` row — fixed so every override row for a non-base symbol appears in `entries`, tagged `removed = (action == "remove")`. **Task 7.5 — the frontend:** `web/components/universe/{UniverseList,OverrideBadge,AddSymbol}.tsx` and a rewritten `web/app/universe/page.tsx` consume the new shape (`web/lib/commands.ts` gains `submitUniverseCommand`); add/remove controls render only on `would_own`/`watchlist`, with `indexes`/`actively_wheeling` rendered read-only and noted as YAML-managed. Adding to `would_own` opens a confirmation naming the actual consequence — the system may sell cash-secured puts on the symbol and the operator may be assigned its shares; adding to `watchlist` fires immediately with no dialog (a reporting list, never reaches an order). An overridden entry renders `OverrideBadge` (author, timestamp, a revert control that fires the opposite action of the entry's current state). The symbol picker is a typeahead over `GET /research/search`, so a typo cannot become a `404`. Every mutation renders `CommandReceipt` and stops polling at a terminal command status. The wheeling-vs-dip-watch tag the pre-M7 page showed within `would_own` was preserved. **Task 7.6 — the fence:** `tests/test_web_fence.py` gains three tests: no module under `src/claude/eval/` or `src/research/` can write a universe override; `src/engine/risk_engine.py` never mentions `effective_universe`/`universe_overrides` anywhere in its text; `OVERRIDABLE_LISTS == frozenset({"would_own", "watchlist"})` exactly, pinned so a future widening fails here first. All gates green: `python -m pytest -q` (1920 passed), `ruff check .` (clean), `mypy src` (clean), `cd web && npx vitest run` (203 passed) `&& npm run lint && npm run build` (both clean). **Final whole-branch review fix round (2026-09-07), one commit, seven findings:** `universe_add`/`universe_remove` lost their dedupe key in `dedupe_key_for` — a stable `f"{kind}:{list_name}:{symbol}"` key let a later, semantically different request (e.g. the second `remove` in remove→add→remove) dedupe to an earlier request's already-`applied` command row, so the API returned `200`/`applied` while the override table never actually changed; both kinds now join halt/resume/set_autonomy/refresh under `dedupe_key_for(...) is None`, so a repeat POST/DELETE always creates a fresh command (idempotent in effect via the upsert-only handlers, not via dedupe). The generic `POST /commands` route gained the same unknown-symbol `404` check (`src/api/deps.py::assert_known_symbol`, shared with the thin wrappers) the `POST`/`DELETE /universe/{list_name}/{symbol}` routes already had, closing a path that let an owner smuggle an override for a non-existent symbol straight past those wrappers. `GET /universe`'s `removed` field is now derived directly from the override row's `action` plus the `actively_wheeling` guard (matching `_compose_list`'s own guard condition) instead of from `effective_universe()`'s cached composed list — that cache is invalidated only in the exec process that runs the drain, so the API process's own cache instance could read up to 60s stale right after a removal, showing a just-removed symbol as still present with a revert badge that fired the wrong action. `created_at` is now normalized through `routers/options.py`'s `_as_utc` before serializing, so a naive SQLite timestamp doesn't silently render at the wrong relative age in a non-UTC browser. `effective_universe()` now copies (not aliases) every passthrough container one level deep, so its return value can never share object identity with the `lru_cache`-shared `sectors`/`indexes`/`actively_wheeling` config the risk engine reads. `test_the_overridable_set_matches_the_spec_exactly` now pins all four independent declarations of `{"would_own", "watchlist"}` (`OVERRIDABLE_LISTS`, `routers/universe.py::_OVERRIDABLE`, `UniversePayload.list_name`, and both route functions' `list_name` parameters), not just the first. `ARCHITECTURE.md` now notes `effective_universe()`'s `session_scope()` read (and `checks/warnings.py`'s transitive dependency on it) as a deliberate, documented exception to the API's read-only-trading-DB invariant. All gates green again: `python -m pytest -q`, `ruff check .`, `mypy src`, `cd web && npx vitest run`. **Not built, plainly:** no order ticket (spec §4.3, a standing P2 scope decision from M1, not new to this milestone); no Tailscale (same, standing since earlier milestones); and — the one limitation unique to this milestone, by deliberate design — **no override for `sectors`**: it feeds `risk_engine.py`'s concentration limits and stays file-only, unreachable from the web at every layer (API `422` via the `Literal` path-parameter type, the composer's byte-identical passthrough, and the fence test above). `clear_override` (Task 7.1) is built and independently tested but unused by any handler — revert is achieved through the opposite command (`POST`/`DELETE`), not a dedicated hard-revert route; it remains available for a future feature. No Telegram notification fires for a universe edit, deliberately. ~~`refresh`'s command kind (spec §6.6) still has no registered handler anywhere in the codebase~~ **Registered 2026-09-09** — P3/P4 M1 Task 1.4 (`src/notify/command_drain.py::_refresh`) gave it its handler: it captures positions + account values and writes one `portfolio_snapshots` row (`source="refresh"`), creating no approval and no order; `docs/web/commands.md` documents it. P3 (Portfolio), P4 (Profitability tracker), and P5 (Mobile) remain deferred — see the rows immediately below. |
 | **P3 — Portfolio (M1 — the portfolio spine — built 2026-09-09, opencode/glm-5.3; M2 — the portfolio read API — built 2026-09-10, opencode/glm-5.3; M3 — the portfolio UI — built 2026-09-10)** | **M1:** nothing user-visible — no route, no component, no nav change. The API cannot ask IBKR anything, so the two processes that already hold an IB connection now write down what IBKR said, into a table the API reads. **The new table:** `PortfolioSnapshotRow` (`portfolio_snapshots`, `src/storage/models.py`) + `src/storage/portfolio_snapshots.py` — append-only, **no unique constraint** (two rows may share a `captured_at`: a refresh moments after a monitor write must not fail; newest `id` wins a tie), deliberately separate from `position_snapshots` (whose one-row-per-ET-day contract assignment auto-detection diffs — never written by anything new, pinned by a row-count test), pruned by the EOD run to `storage.portfolio_snapshot_retention_days` (default 30) beside `purge_old_risk_verdicts`; `save/load_latest/latest_capture_time/prune` never raise (the monitor calls save from a live event loop). **The two writers:** (1) the intraday monitor's `_maybe_write_snapshot` (`src/monitor/intraday.py`) — called at the *end* of `_refresh_subscriptions` with the positions that pass already fetched (never a second `get_positions`), rate-limited by `market_data.portfolio_snapshot_interval_minutes` (default 15) through a gate that reads the table's newest `captured_at` from the DB (a restart can't burst snapshots; a refresh's row counts toward the interval), RTH-only, account fetch under `asyncio.wait_for`, and wrapped so no exception can escape into `_refresh_loop` — a dead refresh task would silently stop roll alerts for every position opened after that moment, and that failure mode has its own test (`tests/test_monitor_snapshot.py`); (2) the `refresh` drain handler (`src/notify/command_drain.py::_refresh`, the command kind P2 left unregistered — now registered): captures positions + account now, writes one `source="refresh"` row, ignores the monitor's gate, fails `broker_unavailable` without a broker (never writes stale data as fresh), fails `snapshot_failed` on a bad write, sends no Telegram, and creates no approval and no order — the phase's no-new-order-path assertion lives in `tests/test_drain_refresh.py`. **The fallback chain:** `src/api/portfolio_source.py::read_portfolio` → `PortfolioReading` — three rungs (newest `portfolio_snapshots` row; else newest `position_snapshots` + the account block out of `journal.payload["eod_summary"]["account"]` (optional there, validated whole through `AccountSnapshot.model_validate`); else `source="none"`, `snapshot=None` — never a zeroed-out snapshot, because a portfolio page rendering zeros is indistinguishable from an account that's genuinely empty). A corrupt row on any rung falls through rather than failing; `as_of` is the capture time everywhere (via `as_utc_opt`), never request time. **Config keys:** `market_data.portfolio_snapshot_interval_minutes`, `storage.portfolio_snapshot_retention_days` (both documented in `ARCHITECTURE.md`/`SETUP.md`). **The read-side schema:** `PortfolioSnapshot` (`src/common/schemas.py`; `account` optional only on the API's eod rung). **M2:** four owner-only read routes (`src/api/routers/portfolio.py` + `src/api/models/portfolio.py`, mounted under `/portfolio`), all rendering what `read_portfolio` found — no second data path. `GET /summary`: account values as `Sourced` (`Source.IBKR`, `fresh_for` twice the snapshot interval — one missed capture reads stale) beside the exposure block (open positions/shorts/campaigns, net delta per the EOD formula, cash secured against short puts only at `strike × contracts × 100`, buying-power utilisation `null` not `0.0` when buying power is zero, assignment-risk count through the shared M0 predicate). `GET /positions`: grouped by underlying (a `null` `underlying` groups under its own symbol, never dropped), **both cost bases reported** — `avg_cost` from IBKR, `adjusted_cost_basis` from campaigns for assignment shares (both adjusted fields `null` otherwise), `unrealized_pnl` against the former and `unrealized_pnl_adjusted` against the latter so a profitable assigned position can't look like a loss; `moneyness` from the group's stock price else the latest `price_history` close (read-only, the same table `routers/research.py::_hv30_for` reads), `null` when unknown; `dte` `null` never `0`. `GET /campaigns`: the wheel threads with `status`/`symbol` filters, `opened_date` desc with open before closed at the same date, `as_of` request time (written on fill, not captured — documented in the route so nobody "fixes" it), financials gross of commissions (M0 Task 0.4), a pruned candidate still rendering as a leg with `known: false`; `load_campaigns`'s dicts now carry `leg_candidate_ids` for the join. `GET /calendar`: expiries grouped by date over `horizon_days` (default 45, max 365), the `consequence` table exactly as specified (ITM short put `assigned`; ITM short call `called_away` only with stock held, else `assigned`; short OTM/ATM `expires_worthless`; unknown moneyness `unknown` — a real value, never defaulted). Every route's `none` rung is a **200 with explicit emptiness** (`account: null` / `groups: []` / `days: []` + `source="none"` + a plain-words `note`), never a 404 and never zeros. 47 new tests across `tests/test_api_portfolio_{summary,positions,campaigns,calendar}.py`, plus shared fixtures in `tests/conftest.py` (`seed_portfolio_snapshot`, `seed_position_snapshot`, `seed_journal`, `seed_campaign`, `seed_assigned_campaign`, and the `short_put`/`short_call`/`long_put`/`stock` builders) that M4 reuses. `docs/web/openapi.json` and `web/lib/api-types.ts` regenerated (M0 Task 0.5's freshness test green). Gate: `python -m pytest -q` (2043 passed), `ruff check .`, `mypy src` all green. **A verification pass (2026-09-10, independent audit post-build) reproduced the full gate exactly as claimed and confirmed every artifact, then found and fixed four defects in the built code** (each with its own regression test, 47 → 53 across the four files, suite 2049): (1) `GET /positions`' `_stock_leg` called `storage.campaigns.adjusted_cost_basis_for` — which opens the storage engine's read-write `session_scope` from inside the API process — as its *primary* path, inverting the read-only-engine invariant the route itself documented; the read-only query is now primary (mirroring `adjusted_cost_basis_for`'s newest-open-assigned-campaign rule, also fixing a latent `MultipleResultsFound` on two assigned campaigns for one symbol); (2) `OptionLeg.right`/`strike` fabricated `"C"`/`0.0` for snapshots that carried neither and computed `moneyness` against the fabricated pair — both now `null` and `moneyness` requires all three of spot/right/strike; (3) the calendar's horizon gate used a UTC cutoff while its `dte` measured ET — two clocks in one route; both now ET; (4) `GET /campaigns` read the never-pruned `campaigns` table unbounded — now capped by a `limit` query param (default 50, max 200), the same discipline `load_campaigns` and the other list routes follow. **M3 (Tasks 3.1-3.6):** the `/portfolio` console itself — `Money` (`.hatch` unknown, signed figures, `kind`/`complete` rendered as words, never colour alone) and `FreshnessLabel` (Task 3.1); `PortfolioShell` mounting `SummaryPanel` once above a Positions/Campaigns/Calendar tab bar that never remounts it (Task 3.2); `PositionsPanel`/`PositionGroup` grouping stock and option legs by underlying, both cost bases reported (Task 3.3); `CampaignsPanel`/`CampaignThread` — collapsible wheel threads with a real backend-filtered `status`/`symbol` query, gross-of-commissions financials (Task 3.4); `CalendarPanel` and `RefreshControl` — the expiry grid with consequence text per entry, and the one write this page offers, a one-click `POST /commands{kind:"refresh"}` with no confirmation dialog (Task 3.5); the nav flip (`portfolio.available: true`) plus doc updates (Task 3.6). Every panel self-fetches its own route; what each reads from its response differs (`SummaryPanel` alone reads both `source` and `degraded`, `CampaignsPanel` reads neither — `CampaignsResponse` carries only `{as_of, campaigns}`). A whole-branch cross-cutting fix pass (2026-09-10) then closed six Important findings the six tasks' individual reviews couldn't see: `RefreshControl` now self-fetches `GET /options/controls` for the real `drain_healthy` instead of a hardcoded `true`; all four panels poll every 30s so the freshness label doesn't freeze at mount; `CampaignThread`'s `net_premium`/`adjusted_cost_basis`/`realized_stock_pnl` now pass `Money`'s `complete={false}`, since `/portfolio/campaigns` is documented gross of commissions. |
 | **P4 — Profitability tracker (M4 — the P&L engine — built 2026-09-10, opencode/glm-5.3; M5 — the P&L surfaces — built 2026-09-11, opencode/glm-5.3; M6 — system performance and close-out — built 2026-09-11)** | **M4:** the paired realised-P&L accounting rule now exists once, in `src/reporting/` — a package the web layer may read and the trading path may not import (third, read-only analytics tier, both fence directions asserted in `tests/test_web_fence.py`). **Task 4.1 — the dependency inversion:** `fill_economics` and `classify_outcome` moved **verbatim** out of `src/claude/eval/reconcile.py` into `src/reporting/legs.py` (frozen dataclasses replace the tuples; the one addition is `commissions_complete`, which no existing caller reads). `reconcile.py` imports them from there — the fenced reconciler depends on the neutral read-only module, which the fence allows (`eval/` may import a read-only module; the fence stops it reaching the engine). The four reconcile test files pass **unchanged** at the recorded baseline (150). **Tasks 4.2–4.6 — the builders:** the six P&L schemas (`PnlLeg`/`CampaignPnl`/`PnlBucket`/`PnlSummary`/`EquityPoint`/`EquityCurve`, `src/common/schemas.py` — `PnlLeg.outcome` reuses `VerdictOutcome` so the reporting layer and the outcome ledger share one outcome vocabulary); `build_legs` (one `PnlLeg` per filled candidate, newest first; pruned candidates still produce legs with nulls; paper/live filterable and never silently mixed; assignment read from `CampaignRow.assigned`; `roc_pct` credit-over-collateral, `None` when collateral is unknown; `annualized_pct` `None` at `days_held=0`); `build_campaigns` (wheel threads; stock leg read from `CampaignRow`, never recomputed; `snapshot=None` means every unrealised field `None`, never zero; campaign-less legs land in synthetic per-symbol threads so thread legs always sum to the leg count; marks come from the same `PortfolioSnapshot` the portfolio page renders, and a closed leg's `unrealized_pnl` stays `None` forever); `build_summary` (pure; **raises `ValueError` on a mixed paper/live leg list** — the one raise in `src/reporting/`; `win_rate` `None` with nothing closed; `commissions_complete` is the AND of every leg's flag; best/worst chosen among closed legs only; buckets ordered realised-descending, ties by label); `equity_curve` (one point per `JournalRow`; `gaps` lists missed **trading days** — weekends/holidays are not gaps — never interpolated; `net_liquidation` read through `AccountSnapshot.model_validate` so payload drift surfaces as `None`, never a KeyError; `journal.realized_pnl` surfaces as `premium_cashflow` under its true name; `cumulative_realized` sums legs closed on or before each point). **Task 4.7 — the wheel-scenario suite:** five end-to-end scenarios (CSP expiring worthless, the full wheel with called-away stock, a roll chain, missing commission data, paper-vs-live side by side) with hand-written expected literals, plus the three cross-checks: the ledger and the reporting layer agree on every closed trade (one accounting rule — Task 4.1's whole point), the campaign rollup and the leg sum agree gross-vs-gross, and the gross and net views differ by exactly the commission total. **No routes and no UI** — the `/pnl/*` surfaces are M5. **Its numbers have not been reconciled against a broker statement** — the engine is built and tested against seeded data; a live-verification pass comparing `build_legs` output against IBKR's own fills/P&L report remains outstanding, as it does for the rest of the web platform. Gate at close: `python -m pytest -q` (2141 passed), `ruff check .`, `mypy src` all green. **M5 (Tasks 5.1-5.7, built 2026-09-11, opencode/glm-5.3):** the `/pnl` surfaces — every route a thin renderer over `src/reporting/` (the single accounting rule holds at the API boundary too). **Task 5.1 — `GET /pnl/ledger` + `GET /pnl/summary`** (`src/api/routers/pnl.py` + `src/api/models/pnl.py`): `as_of` is request time (the ledger is computed on read) while `marks_as_of` is the snapshot time behind every unrealised figure, from the same single `read_portfolio` call the portfolio page reads (proven by a test comparing the two responses' stamps); filters echo back verbatim; `build_summary`'s mixed-book `ValueError` becomes a `422 {"reason": "mixed_book"}` answer, never a 500 and never a mixed total, while the ledger may still list both books; `n_legs` is checked at the client boundary against the sum of every campaign thread's leg count (synthetic threads included). **Task 5.2 — `GET /pnl/equity`:** `build_legs` feeds `equity_curve` unchanged; `book=all` allowed here deliberately (a curve is a display choice, not a headline total — the asymmetry with the summary is documented in three places so nobody "fixes" it); `premium_cashflow` never named `realized_pnl` anywhere in the response. **Task 5.3 — `GET /pnl/ledger.csv` + the proxy allowlist:** the CSV is built from the same `build_legs`/`build_campaigns` calls the JSON route uses, with unit-suffixed headers (`credit_usd`, `net_pnl_usd`, `roc_pct`, `days_held`), a `book` column, `None` as an empty cell (never `0`), and a dated `Content-Disposition` filename; the proxy (`web/app/api/[...path]/route.ts`) gains an explicit two-name `FORWARDED_RESPONSE_HEADERS` allowlist (`Content-Type`, `Content-Disposition`) — not a passthrough, with its own pinning test so a copy-all regression fails. **Tasks 5.4-5.6 — the UI** (`web/app/pnl/page.tsx` + `web/components/pnl/{PnlShell,LedgerTable,CampaignRow,LegRow,LedgerFilters,SummaryPanel,BreakdownTable,EquityChart}.tsx`): the ledger grouped by campaign with `<button aria-expanded>` threads; no unknown renders as a zero anywhere (open leg's realised is `n/a`, `win_rate: null` is `n/a`, `marks_as_of: null` renders "no marks available" and every unrealised cell `n/a`, gross qualifier on incomplete commissions); a `422 mixed_book` renders a labelled book-choice group in plain words — a normal situation, not an error state; the equity chart renders gaps as gaps (`connectNulls={false}`), never animates (`isAnimationActive={false}`), reads colours from CSS custom properties at mount, labels `premium_cashflow` under that name, states the start date in words, and mirrors its real props onto `data-series` wrapper elements because Recharts does not expose them as DOM attributes; filters drive the query string so the CSV export link carries the same filters (one composition in `PnlShell`, never two); `Money` reused from `components/portfolio/` in every leg/campaign/summary figure — no second money component; `FreshnessLabel`/`DegradedNotice` are not used on this page (the ledger and summary carry their own `marks_as_of`/`mixed_book` renderings instead). Best/worst legs in the summary link into the ledger tab (filtered to that leg's symbol, the closest cross-reference the ledger's filters expose). **Task 5.7 — nav flip + docs + regen:** `pnl` flipped `available: true` in `_SECTIONS` (every section now available, no note), `tests/test_api_meta.py` updated, `docs/web/api.md` documents all four routes with the `as_of` vs `marks_as_of` distinction and the `mixed_book` refusal, `web/CLAUDE.md` gains the `app/pnl/`+`components/pnl/` layout entries and the proxy-allowlist section, `README.md`/`ARCHITECTURE.md` rows updated, `docs/web/openapi.json` + `web/lib/api-types.ts` regenerated (freshness test green). **Conftest:** the M4 `db` fixture pointed the storage engine at a private `t.db` while the API client read `income_system.db` — invisible while builders were called directly, exposed the moment a route test crossed the boundary — so tests/conftest.py gained a `db` override that rebinds the storage engine to the client's file (via the `client` fixture) plus a shared `seed_wheel` fixture; M4's own suite passes unchanged at its recorded baseline. **The M4 broker-statement caveat still stands:** the engine and now the surfaces are built and tested against seeded data; a live-verification pass comparing the ledger against IBKR's own fills/P&L report remains outstanding. Gate at close: `python -m pytest -q` (2175 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (334 passed, 42 files) `&& npm run lint && npm run build` — all six green. **Also fixed in passing (pre-existing flake, exposed at this timezone):** the portfolio calendar tests and the conftest position builders seeded expiries from the local clock while `routers/portfolio.py` measures dte and its horizon gate on the ET exchange calendar — whenever the two calendars straddle midnight (any evening after 8pm ET, or running the suite from a non-ET machine) every default-dte position lands one day past the 45-day horizon and the calendar tests fail on `days[0]`. The builders (`short_put`/`short_call`/`long_put`) and the calendar tests' `_day()`/boundary assertions now derive from `_et_today()` (tests/conftest.py), the same clock the route itself reads. **M6 (Tasks 6.1-6.4, built 2026-09-11):** the score-vs-outcome evidence `src/claude/eval/score_metrics.py` already produced gets its reader, and the two fences this phase leans on are enforced by tests rather than by intention. **Task 6.1 — `GET /pnl/system`:** the one P&L route that reads behind the `src/claude/eval/` fence, and the reason is written down in its own docstring and in `docs/web/api.md` — `CLAUDE.md` already says everything `eval/` produces "is read by a human, never auto-applied," and this route is that human's reader, not a breach of it. It calls `score_outcome_report(since, until)` and returns exactly what it gets (a test spies on the call and asserts exactly one), adds a new `VerdictAgreement` figure computed here from `ledger.load_records(closed_only=True)` (Claude-vs-baseline agreement rate plus each side's win rate, windowed on `outcome_date` the same way the report is), and answers the empty case with the report's own "nothing to correlate yet" note rather than a `404`. `agreement_rate`/`claude_win_rate`/`baseline_win_rate` are `null` with zero closed rows, never `0.0`. **Task 6.2 — the System tab:** `SystemPanel`/`ScoreBucketTable`/`CorrelationTable` (`web/components/pnl/`), wired into `PnlShell` as a third tab with its own since/until window state, independent of the ledger's filters. `SystemPanel` is presentational (a `data` prop, like `EquityChart`) since the shell owns the fetch. Every note in the report renders in full and in order — the read-only "re-derive the scoring config by hand" sentence is why the surface is allowed to exist, and it is not the UI's to paraphrase; a bucket with `n` under 5 is labelled "small sample" in words; `n_closed: 0` renders the note and no tables at all, never empty tables with `n/a` rows; the only controls anywhere on the tab are the two date inputs, asserted by a test that counts every button/input/select in the panel. **Task 6.3 — five new fence tests** (`tests/test_web_fence.py`): no module under `src/api/` can write the verdict ledger or reference the scoring config by filename; the API still writes exactly one table (re-asserting the P2 guarantee, with the same `trading_db.py` exception the existing P2 test already carries, since that module *defines* the write handle rather than using it); `src/reporting/` never touches a DB session; `save_portfolio_snapshot` still has exactly its two intended callers (the monitor and the drain). One real trip surfaced and was fixed during this task: `pnl_system`'s own docstring named the scoring config by its literal filename in prose, tripping the new check even though it was never a code reference — reworded, not weakened, since the fence's point is that the name should be unreachable from `src/api/` by grep. **Task 6.4 — close-out:** re-derived rather than re-asserted — every command failure reason in `src/notify/command_drain.py` (extracted correctly this time, accounting for the multi-line `CommandFailed(...)` calls the milestone's own literal grep missed, same class of gap the P2 close-out log already flagged) appears in `docs/web/commands.md`; `docs/web/openapi.json` and `web/lib/api-types.ts` both regenerate to an empty diff (generated directly from the checked-in `openapi.json` file rather than via `npm run gen:api` against `:8787`, since a live API instance was already running there for other purposes and was left untouched); `README.md`'s layout table and `ARCHITECTURE.md`'s folder guide were already accurate for every P3/P4 module before this pass (confirmed, not re-written). **P3 and P4 are both complete. Not built:** P5 (mobile/responsive shell), operator notes on legs and campaigns, a materialised P&L table, intraday equity history beyond the snapshot retention window, and any Tailscale or remote hosting. **The ledger's numbers have not been reconciled against a broker statement** — every P&L figure across P3 and P4 is built and tested against seeded data; a live-verification pass comparing `build_legs`/`build_campaigns` output against IBKR's own fills/P&L report remains outstanding. Gate at close: see the implementation log in `Web plan/P3-P4-IMPLEMENTATION-PLAN.md` for the exact numbers. |
-| **Web overhaul (Parts 1-4 built; Parts 5-8 and order control not started, 2026-10-13 onward)** | **Part 1 built 2026-10-14** (`docs/superpowers/plans/2026-10-13-web-overhaul-1-foundation-home.md`): the payslip design system (`web/DESIGN.md`), the new shell and Home, and three read-only routes (`GET /portfolio/value`, `GET /pnl/month`, `GET /spreads/positions`). **Part 2 (Trades) built 2026-10-19** (`docs/superpowers/plans/2026-10-19-web-overhaul-2-trades.md`, see "Built (2026-10-19 — web overhaul Part 2)" below). **Part 3 (Portfolio and Activity) built 2026-10-28** (`docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md`, see "Built (2026-10-28 — web overhaul Part 3)" below). **Part 4 (cleanup, honesty and the value gaps) built 2026-11-05** (`docs/superpowers/plans/2026-11-05-web-overhaul-4-cleanup-honesty-value-gaps.md`, see "Built (2026-11-05 — web overhaul Part 4)" above): it deleted the legacy files Parts 2 and 3 left unmounted, removed `GET /nav`, made unknown say "could not read" instead of none, gave the value book its places (the drain note, Needs you, Portfolio, At IBKR) and added route titles and the not-found and error pages. **Not started, no plan yet (HANDOFF section 5):** Part 5, the stock page; Part 6, Research, Universe and search; Part 7, News, More and How it works; Part 8, the value record (gated on a month of paper record); and order control (cancelling a working order from the web), on its own track with a spec first. |
+| **Web overhaul (Parts 1-5 built; Parts 6-8 and order control not started, 2026-10-13 onward)** | **Part 1 built 2026-10-14** (`docs/superpowers/plans/2026-10-13-web-overhaul-1-foundation-home.md`): the payslip design system (`web/DESIGN.md`), the new shell and Home, and three read-only routes (`GET /portfolio/value`, `GET /pnl/month`, `GET /spreads/positions`). **Part 2 (Trades) built 2026-10-19** (`docs/superpowers/plans/2026-10-19-web-overhaul-2-trades.md`, see "Built (2026-10-19 — web overhaul Part 2)" below). **Part 3 (Portfolio and Activity) built 2026-10-28** (`docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md`, see "Built (2026-10-28 — web overhaul Part 3)" below). **Part 4 (cleanup, honesty and the value gaps) built 2026-11-05** (`docs/superpowers/plans/2026-11-05-web-overhaul-4-cleanup-honesty-value-gaps.md`, see "Built (2026-11-05 — web overhaul Part 4)" above): it deleted the legacy files Parts 2 and 3 left unmounted, removed `GET /nav`, made unknown say "could not read" instead of none, gave the value book its places (the drain note, Needs you, Portfolio, At IBKR) and added route titles and the not-found and error pages. **Part 5 (the stock page) built 2026-11-06** (`docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md`, see "Built (2026-11-06 — web overhaul Part 5)" above). **Not started, no plan yet (HANDOFF section 5):** Part 6, Research, Universe and search; Part 7, News, More and How it works; Part 8, the value record (gated on a month of paper record); and order control (cancelling a working order from the web), on its own track with a spec first. |
 | **P5 — Mobile** | A native app is deliberately not built. The web console is responsive since web overhaul Part 1 (phone tab bar, bottom sheets, 44px phone targets on the new surfaces). |
 
 Invariants (see `CLAUDE.md` and `Web plan/P0-P1-design.md` §4.3/§4.7 and `Web plan/P2-design.md` §4.2): the API process holds no
diff --git a/docs/web/api.md b/docs/web/api.md
index baffec5..0c27f4c 100644
--- a/docs/web/api.md
+++ b/docs/web/api.md
@@ -1595,7 +1595,10 @@ Up to ten names of the trading universe on one list by the **effective** verdict
 WAIT; each by rank, higher first). **Response — `ValueTopResponse`:** `{ as_of, available, list_name, items }`;
 `ValueTopItem`: `{ symbol, list_name, verdict, decided_by: "claude" | "python", price, fair_value (the
 effective one), entry_ceiling, stop, half_sell, mos (a fraction), reasons (up to 3, Python's), put_ceiling,
-age_days }`. `stop` is always `null`: the live `value` policy sets no stop before the half sale, so there is no
+age_days, claude_note }`. `claude_note` (web overhaul Part 5) is Claude's own `why` for the list on one line (the
+latest non-superseded verdict from the CLI backend; whitespace collapsed, at most 200 characters, cut at a word
+with an ellipsis), `null` when Claude has not read the name; a local model's verdict never fills it. It is
+Claude's text: label it as Claude's and never put it on a button. `stop` is always `null`: the live `value` policy sets no stop before the half sale, so there is no
 number to show for a name not yet held. `half_sell` is the effective fair value, the level the half sale fires
 at. `put_ceiling` is the highest effective entry ceiling among the name's priced lists, the ceiling of a
 value-suggested put.
@@ -1630,12 +1633,18 @@ The ticker file. **Response — `ValueTickerResponse`:** `{ as_of, available, sy
 laid over each list's baseline: `gates` (data quality and health, each `{ id, group, state, value, threshold,
 detail }`), `lists[]` (`baseline_verdict`, the effective `verdict` and `decided_by`, Python's `fair_value` and
 the `effective_fair_value`, `mos`, `entry_ceiling`, `methods[]` with `used` and `median` marked, the entry and
-timing `gates[]`), `metrics`, `put_ceiling`. **`claude` is `null` when Claude has read nothing for the name**,
+timing `gates[]`, and since web overhaul Part 5 `size_pct` and `tranches`), `metrics`, `put_ceiling`. `size_pct` is
+the size tier the effective margin of safety reaches (`value.book.tiers`, in percent of the book's ceiling, capped
+at `name_cap_pct`): `0.0` below the first tier, `null` when the margin is unknown; `tranches` is
+`value.book.tranches`. **`claude` is `null` when Claude has read nothing for the name**,
 else `{ source: "claude", read_at, lists[] (a verdict per list with `why`, `fair_value`, `python_fair_value`,
 `cap_applied`, `drivers[]` `{ name, chosen, used, clamped, bound }`, `clamps[]`, `backend`), notes[], kill_triggers[]
 (`{ name, threshold, actual, state, distance_pct }`), facts[] (grounded only, `{ text, quote, filing }`) }`: it is
 Claude's text and numbers as Python bounded them and is always labelled; no Python field carries it. `reevaluations`
-are a held name's; `plan` is its open position's exit plan (`null` for a name not held).
+are a held name's; `plan` is its open position's exit plan (`null` for a name not held), with, since web overhaul
+Part 5, `tranches_done`, `tranches`, `tranche_min_sessions` and `last_tranche_on` (the tranche plan: the second
+tranche waits for a higher low, any later one for a close above the 50-day average, each at least
+`tranche_min_sessions` after the last and gated again).
 
 `computed` (ruling 24, `src/api/value_lookup.py`): **`stored`** when the file's freshness key (the newest accession
 and bar in `research.db`, the regime, the ruleset: `src/common/value_freshness.py`) equals the key of the cheap
diff --git a/web/CLAUDE.md b/web/CLAUDE.md
index ce355c9..062ca96 100644
--- a/web/CLAUDE.md
+++ b/web/CLAUDE.md
@@ -172,13 +172,10 @@ app/                App Router pages and the root layout
                     that they are managed in config/universe.yaml. Still shows sector
                     tag, strike-band override, and marks which would_own names are
                     actively_wheeling vs dip-watch.
-  stock/[symbol]/   Ticker page: react-query on GET /research/{symbol}, polls while
-                    fundamentals/technicals/sentiment/news/checks is pending, mounts
-                    <SectionShell/> per region, shows the delayed quote (with its age
-                    and a "delayed" tag once stale) beside the header. <PriceChart/>
-                    is NOT gated behind a Section's state — it fetches its own data
-                    from GET /research/{symbol}/bars independently, so a technicals
-                    outage must not hide it too
+  stock/[symbol]/   Ticker page: page.tsx mounts features/stock/StockPage (web overhaul Part 5);
+                    the sibling layout.tsx sets the title. <PriceChart/> is NOT gated
+                    behind a Section's state: it fetches GET /research/{symbol}/bars
+                    itself, so a technicals outage must not hide it too
   options/          (RETIRED) The old tabbed options console. `/options` and `/options/:id`
                     redirect (307) to `/trades` and `/trades/:id` in next.config.ts; what it
                     did lives under trades/ above and features/trades/ below, and its
@@ -344,20 +341,30 @@ components/          Where new code goes (web overhaul Part 4, HANDOFF D4): `fea
                     `<button aria-expanded>` that expands to CheckRow list on click,
                     collapses on a second click; a not-applicable category is disabled and
                     shows its `note` instead; renders leveraged-ETF decay Warnings above the
-                    ribbons), CheckRow (statement + actual + threshold + state; unknown
-                    renders `n/a` in `text-unknown`, never `0`)
-  stock/            SectionShell (renders pending/unavailable states inline),
-                    StatementsTable (normalised statements with filing traceability
+                    ribbons, each with a "Caution" (flag) or "Note" word), CheckRow (the
+                    statement and its state as a StatusWord, Fail in the flag tone, then
+                    "Reads <actual> · bar <threshold>" on its own line; unknown renders a
+                    hatched `n/a`, never `0`). Since web overhaul Part 5 the ribbon fills a
+                    passed check and outlines a failed one in ink: no green or red
+  stock/            StatementsTable (normalised statements with filing traceability
                     in a `title` attribute using a hyphen not an em dash; fixed row
                     order; annual and quarterly sections; missing items render "n/a"
                     with `.hatch` texture, never "$0", never colour alone),
-                    PriceChart (lightweight-charts candlestick + volume + SMA 50/200,
-                    colours read from CSS custom properties at mount, no entry
-                    animation), TechnicalsPanel (RSI/MACD/SMA/ATR + phase/regime,
-                    null renders "n/a" never "0"), NewsPanel (newest-first, relative
-                    age, sentiment chip is label+tint not colour-only), SentimentPanel
-                    (composite score + per-source sample count; a source with no
-                    tracked count renders "n/a samples", never a fabricated "0")
+                    PriceChart (lightweight-charts: a year of ink candles, up hollow and
+                    down filled, light volume, SMA 50 ink and SMA 200 muted, the caller's
+                    `lines` as dashed price lines; colours from the tokens at mount and on
+                    a theme change, no entry animation, attribution logo off; a role="img"
+                    sentence and a line of words name every series), TechnicalsPanel
+                    (figure lines; null renders a hatched "n/a" never "0"), NewsPanel
+                    (newest-first, relative age, the tone as a neutral StatusWord word,
+                    never green or red; `sentimentTint` stays exported for
+                    features/position/Headlines), SentimentPanel (composite score, the
+                    day's change signed but not coloured, per-source sample count; a
+                    source with no tracked count renders "n/a samples", never a
+                    fabricated "0"), SummaryPanel ("Generate summary" is a secondary
+                    Button; the foot line says "Written by <model>, a language model that
+                    decides nothing"). Web overhaul Part 5 deleted SectionShell (replaced
+                    by features/stock/StockSection)
   options/          Web overhaul Part 4 deleted the unmounted ApprovalsList, ApprovalCard, ShortsTable,
                     ShortsRow and ControlsStrip (their live coverage moved first: the decide flow's cases
                     to DecideControls.test.tsx, the roll flow's to RollCard.test.tsx, the drain line's to
@@ -774,6 +781,14 @@ components/          Where new code goes (web overhaul Part 4, HANDOFF D4): `fea
                     tests. A trim has no web button (plan ruling 10): the card
                     says it is offered in Telegram. Claude's words never sit on a button.
 features/
+  stock/            The stock page (web overhaul Part 5). StockPage (react-query on GET /research/{symbol},
+                    key ["analysis",SYMBOL], polling every 5 s while a section is pending, no retry on a
+                    404; it also reads GET /value/{symbol} under ValueBlock's own key ["value","ticker",
+                    SYMBOL], so no second fetch, to place the value block and draw its levels), StockSection
+                    (a Card per section: the title, then the content, or the API's reason / "Building this
+                    section." in words), and stock.ts (`valueLeads`, `valueLines`, `nameLine`, the
+                    `Analysis` alias over the generated AnalysisResponse). The page reads; its only command
+                    is AnalyseButton inside the value block.
   stock-value/      The value book's view of one name on the stock page (value book Part 6, Section G).
                     ValueBlock (react-query on GET /value/{symbol}, key ["value","ticker",SYMBOL]:
                     the verdict per list first, then BusinessBlock, WorthBlock and SizeBlock for the spec's
@@ -786,8 +801,11 @@ features/
                     parts.tsx (Hatched, Segments, ClaudeLabel), `types.ts` (aliases over the generated
                     api-types) and `format.ts` (sentences and the poll rule `refetchMs`). Every piece of
                     Claude's text carries a "Claude's ..." label with the date it was read against; a
-                    hatched n/a is an unknown; Claude's words never sit on a button. Mounted by one line in
-                    app/stock/[symbol]/page.tsx after NameNotes.
+                    hatched n/a is an unknown; Claude's words never sit on a button. Mounted by
+                    features/stock/StockPage: first under the chart when `valueLeads` (a priced list or a
+                    held name), else at the foot of the left column. Since web overhaul Part 5 SizeBlock
+                    says the size tier per priced list (`sizeSegment`) and a held name's tranche plan
+                    (`trancheWords`).
   research/         Top opportunities (value book Part 6, Section H), the strip above the watchlist.
                     TopOpportunities (two tabs on a SegmentedControl, Deep value and Quality growth; react-query
                     on GET /value/top?list=, key ["value","top",list], only the list on view is fetched; a second
````

### Task 11: The da-vinci finish by a fresh reviewer (sonnet, effort high)

**Spawned by the orchestrator as a new subagent with no prior context.** Its prompt: this plan's Global Constraints,
rulings 6-17, `web/DESIGN.md` (the Stock surface), "Invoke the `da-vinci` skill first and run `critique`, then
`audit`, then `polish` over the stock page", "never the live API, never inside `web/`, never on port 3000".

- [ ] **Step 1: The synthetic API.** `mock5` was extracted in A0 to `<S>/p5/mock5.out`. Copy it to `<S>/p5/mock5.py`
  and run it in the background: `python3 <S>/p5/mock5.py` (port 8799). It serves GOOGL (Ready deep value, held: the
  value block first, levels on the chart, a Caution warning, a failed and an unknown check, a model summary), KO
  (every list No: the value block after the statements), SPY (an ETF the book does not score, no bars, checks
  pending, statements unavailable) and a 404 for ZZZZ, plus the two routes the shell reads.
- [ ] **Step 2: A scratch build served on 3101.** G4's copy and build in `<S>/p5/build` (keep it), then in the
  background: `cd <S>/p5/build/web && API_URL=http://127.0.0.1:8799 API_TOKEN=mock npx next start -p 3101`. Wait until
  `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3101/stock/GOOGL` prints 200.
- [ ] **Step 3: Captures.** Copy `capture5` to `<S>/p5/capture5.cjs`, `mkdir -p <S>/p5/shots`, then
  `node <S>/p5/capture5.cjs <a playwright-core directory from D3, without /package.json> <S>/p5/shots` (if Chromium
  fails to launch for a missing browser build, use the other directory D3 listed; the prototype ran with
  `~/.npm/_npx/e41f203b7505f1fb/node_modules/playwright-core`). It writes 24 PNGs (four pages x 320, 390,
  1440 px x light, dark, with GOOGL's statements disclosure and first check category open) and prints each page's `h2`
  order and horizontal scroll. Expected (checked in the prototype): `hscroll` 0 everywhere, no `pageErrors`; GOOGL's
  `h2` order is price chart, Value book on GOOGL, Checks, Technicals, Financial statements, What the news service keeps
  on GOOGL, News, Sentiment, Model summary; KO's and SPY's put the value book after Financial statements. The shell
  scrolls its `main`, so a full-page capture of a long page may show one viewport: scroll `main` and capture in
  chunks (`-a`, `-b`, ...) as Part 4 did. Open and look at every capture.
- [ ] **Step 4: critique, audit, polish.** Fix what they find, each behaviour fix with a test written red first;
  no new token (a proposal waits for the operator); nothing in the protected files. Record every finding not fixed,
  with a reason, in the Progress log row.
- [ ] **Step 5: Gate and commit.** Every web gate; G1-G5; stop the two background servers (`pkill -f "next start -p 3101"`,
  `pkill -f mock5.py`); remove `<S>/p5/build` by literal path (symlink first). Commit
  `fix(web): da-vinci finish of the stock page` (if nothing changed, record "no change" and commit only the log row).

<!-- block mock5 -->
````python
"""A synthetic API for the stock page's visual check (web overhaul Part 5, Task 11). Never the live one.
GOOGL: a Ready deep-value name the book holds (value block first, four levels on the chart).
KO: every list No (value block at the foot). SPY: an ETF the book does not score. ZZZZ: unknown (404)."""

import json
import math
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

now = datetime.now(UTC)
AT = now.isoformat()


def bars(base: float, drift: float) -> dict:
    out, sma50, sma200, closes = [], [], [], []
    day = date.today() - timedelta(days=365)
    price = base
    while day <= date.today():
        if day.weekday() < 5:
            o = price
            price = max(5.0, price * (1 + drift + 0.012 * math.sin(len(out) / 6.0)))
            c = price
            out.append({"time": day.isoformat(), "open": round(o, 2), "high": round(max(o, c) * 1.01, 2),
                        "low": round(min(o, c) * 0.99, 2), "close": round(c, 2), "volume": 1_000_000 + 40_000 * (len(out) % 9)})
            closes.append(c)
            sma50.append(round(sum(closes[-50:]) / 50, 2) if len(closes) >= 50 else None)
            sma200.append(round(sum(closes[-200:]) / 200, 2) if len(closes) >= 200 else None)
        day += timedelta(days=1)
    return {"as_of": AT, "bars": out, "sma50": sma50, "sma200": sma200}


def ready(data):
    return {"state": "ready", "data": data, "reason": None}


def analysis(symbol: str, name: str, *, etf: bool = False, stale: bool = False) -> dict:
    return {
        "as_of": AT, "symbol": symbol, "name": name, "exchange": "NASDAQ" if not etf else "NYSE ARCA", "is_etf": etf,
        "quote": {"value": 182.4, "source": "ibkr", "as_of": (now - timedelta(minutes=3)).isoformat(), "stale": stale},
        "fundamentals": {"state": "unavailable", "data": None, "reason": "Funds file no XBRL financial statements."} if etf else ready({
            "symbol": symbol, "cik": "0001652044", "entity_name": name,
            "annual": [{"period_end": f"{y}-12-31", "period_type": "FY", "items": {
                "revenue": {"line_item": "revenue", "value": 300e9 + (y - 2023) * 30e9, "concept": "Revenues", "accn": "0001652044-25-000010", "filed": f"{y + 1}-02-01", "form": "10-K"},
                "net_income": {"line_item": "net_income", "value": 70e9 + (y - 2023) * 9e9, "concept": "NetIncomeLoss", "accn": "0001652044-25-000010", "filed": f"{y + 1}-02-01", "form": "10-K"},
            }} for y in (2023, 2024, 2025)],
            "quarterly": [],
        }),
        "technicals": ready({"symbol": symbol, "price": 182.4, "rsi_14": 55.2, "atr_14": 3.1, "macd": 0.5, "macd_signal": None,
                             "sma_20": 180.0, "sma_50": 178.2, "sma_200": 160.4, "phase": "Stage 2", "regime": None}),
        "sentiment": ready({"overall": 61.5, "label": "Lean bullish", "delta_1d": -2.0, "stocktwits": 65.0, "stocktwits_msgs": 42,
                            "news": 58.0, "news_count": 15, "reddit": None, "top_headline": None}),
        "news": ready([
            {"title": f"{name} beats on cloud revenue", "url": "https://example.com/1", "published_at": (now - timedelta(minutes=40)).isoformat(), "source": "Reuters", "sentiment": 0.6},
            {"title": f"Regulators widen a probe into {name}", "url": None, "published_at": (now - timedelta(hours=5)).isoformat(), "source": "Bloomberg", "sentiment": -0.4},
        ]),
        "checks": {"state": "pending", "data": None, "reason": None} if etf else ready({
            "warnings": [{"level": "caution", "title": "Earnings in 6 days", "detail": "Premium is high into the report."}],
            "categories": [
                {"category": "value", "passed": 2, "failed": 1, "unknown": 1, "evaluable": 3, "total": 4, "not_applicable": False, "note": None, "checks": [
                    {"id": "v1", "category": "value", "statement": "Is the P/E ratio below 22?", "state": "FAIL", "actual": 24.1, "threshold": 22, "note": None},
                    {"id": "v2", "category": "value", "statement": "Is the price below fair value?", "state": "PASS", "actual": 182.4, "threshold": 215, "note": None},
                    {"id": "v3", "category": "value", "statement": "Is free cash flow yield above 4%?", "state": "PASS", "actual": 4.6, "threshold": 4, "note": None},
                    {"id": "v4", "category": "value", "statement": "Is the dividend yield above 1%?", "state": "UNKNOWN", "actual": None, "threshold": 1, "note": "Input data unavailable"}]},
                {"category": "health", "passed": 3, "failed": 0, "unknown": 0, "evaluable": 3, "total": 3, "not_applicable": False, "note": None, "checks": []},
                {"category": "dividend", "passed": 0, "failed": 0, "unknown": 0, "evaluable": 0, "total": 2, "not_applicable": True, "note": "Pays no dividend.", "checks": []},
            ],
        }),
    }


def lst(name: str, verdict: str, fair, ceiling, mos, size):
    return {"list_name": name, "baseline_verdict": verdict, "verdict": verdict, "decided_by": "python", "fair_value": fair,
            "effective_fair_value": fair, "mos": mos, "required_mos_pct": 30, "entry_ceiling": ceiling, "entry": "pass",
            "timing": "pass", "reasons": ["healthy, cheap enough, timing passes"], "mos_review": False, "methods": [], "gates": [],
            "size_pct": size, "tranches": 3}


def ticker(symbol: str, lists: list, plan) -> dict:
    return {"as_of": AT, "available": True, "symbol": symbol, "computed": "stored", "age_days": 1, "claude": None,
            "reevaluations": [], "plan": plan,
            "file": {"symbol": symbol, "as_of": date.today().isoformat(), "company_class": "operating", "data_quality": "pass",
                     "health": "pass", "price": 182.4, "ruleset_version": "v4", "ruleset_hash": "be30d1eaa915", "gates": [],
                     "lists": lists, "metrics": {}, "adjustments": []}}


GOOGL_PLAN = {"position_id": 1, "list_name": "deep_value", "shares": 20, "avg_cost": 168.0, "next_exit": {"kind": "sell_half", "level": 215.0},
              "stop": None, "half_sold": False, "fair_value": 215.0, "effective_fair_value": 215.0, "tranches_done": 1, "tranches": 3,
              "tranche_min_sessions": 5, "last_tranche_on": (date.today() - timedelta(days=8)).isoformat()}

SUMMARY = {"as_of": AT, "symbol": "GOOGL", "state": "ready", "reason": None, "summary": {
    "thesis": "A cash-rich compounder priced below its own history.", "bull_points": ["ROE above 25%", "Net cash"],
    "bear_points": ["Antitrust remedies"], "watch_items": ["Earnings in 6 days"], "caveats": ["Quantitative only."],
    "model": "claude-sonnet-4-6", "data_as_of": AT}}

ROUTES = {
    "/research/GOOGL": analysis("GOOGL", "Alphabet Inc.", stale=True),
    "/research/GOOGL/bars": bars(150.0, 0.0009),
    "/research/GOOGL/summary": SUMMARY,
    "/value/GOOGL": ticker("GOOGL", [lst("deep_value", "READY", 215.0, 190.0, 0.151, 3.0), lst("quality_growth", "NO", None, None, None, None)], GOOGL_PLAN),
    "/research/KO": analysis("KO", "Coca-Cola Co"),
    "/research/KO/bars": bars(60.0, 0.0002),
    "/research/KO/summary": {"as_of": AT, "symbol": "KO", "state": "unavailable", "summary": None, "reason": None},
    "/value/KO": ticker("KO", [lst("deep_value", "NO", 50.0, None, -0.2, None)], None),
    "/research/SPY": analysis("SPY", "SPDR S&P 500 ETF", etf=True),
    "/research/SPY/bars": {"as_of": AT, "bars": [], "sma50": [], "sma200": []},
    "/research/SPY/summary": {"as_of": AT, "symbol": "SPY", "state": "unavailable", "summary": None, "reason": None},
    "/value/SPY": {**ticker("SPY", [], None), "file": {**ticker("SPY", [], None)["file"], "not_applicable_reason": "a fund has no filings to score"}},
    "/claude/context": {"as_of": AT, "available": True, "claude_cut_mode": "record_only", "account_mode": "paper",
                        "claude_cut_breaker_tripped_today": False, "dossiers": []},
    "/options/controls": {"as_of": AT, "autonomy": {"level": "full", "label": "Full"}, "rungs": [], "halted": False, "mode": "paper",
                          "drain_healthy": True, "drain_last_seen": AT, "pending_commands": 0},
    "/options/approvals": {"as_of": AT, "approvals": []},
}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        body = ROUTES.get(path)
        code = 200 if body is not None else 404
        payload = json.dumps(body if body is not None else {"detail": f"mock: no route for {self.path}"}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # quiet
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8799), Handler).serve_forever()
````

<!-- block capture5 -->
````javascript
// Captures for web overhaul Part 5, Task 11. Usage:
//   node capture5.cjs <path to playwright-core> <output dir> [base url]
// Every page at 320, 390 and 1440 px, light and dark; prints the h2 order, page errors and any
// horizontal scroll per capture. Never point it at the live API or the operator's next dev on 3000.
const { chromium } = require(process.argv[2]);
const outDir = process.argv[3];
const base = process.argv[4] ?? "http://127.0.0.1:3101";
(async () => {
  const browser = await chromium.launch({ headless: true });
  const report = [];
  for (const theme of ["light", "dark"]) {
    for (const width of [320, 390, 1440]) {
      const page = await browser.newPage({ viewport: { width, height: 900 } });
      await page.addInitScript((t) => localStorage.setItem("ibkr-theme", t), theme);
      const errors = [];
      page.on("pageerror", (e) => errors.push(e.message));
      for (const sym of ["GOOGL", "KO", "SPY", "ZZZZ"]) {
        await page.goto(`${base}/stock/${sym}`, { waitUntil: "networkidle" });
        await page.waitForTimeout(1200);
        if (sym === "GOOGL") {
          const statements = page.getByRole("button", { name: /Revenue, profit, balance sheet/ });
          if (await statements.count()) await statements.click();
          const value = page.getByRole("button", { name: /^Value/ });
          if (await value.count()) await value.first().click();
        }
        await page.screenshot({ path: `${outDir}/stock-${sym}-${width}-${theme}.png`, fullPage: true });
        report.push({
          sym, width, theme,
          h2: await page.evaluate(() => [...document.querySelectorAll("h2")].map((h) => h.textContent)),
          hscroll: await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth),
        });
      }
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
operator's yes, from the main checkout on a clean `main`: `git merge --ff-only feat/web-overhaul-5` (if `main` moved,
stop and ask), push when told, then `./ibkr restart` (the API serves the new fields; `next dev` picks up the web), and
fill the "Merge, push, restart" row (commit, time).

---

## Operator to-dos

1. Before Section B, overturn any of rulings 6-10 you dislike (ink candles instead of green and red, "Model summary",
   the back link to Research, where the value block goes, the layout). After that they cost a rework.
2. After the merge: `./ibkr restart` (the API process serves `size_pct`, `tranches`, the plan's tranche fields and
   `claude_note`; until then the value block's new lines read as unknown).
3. Look once at `/stock/<a Ready name>` on a phone in dark mode.
4. Housekeeping from the HANDOFF (7.3 item 4).

## Self-review (run by the plan's author, 2026-11-06)

- **Spec coverage.** HANDOFF Part 5 row: L2 (Tasks 3-9), V6 (Tasks 1, 3, 4, 6), V7 backend (Task 1), S5 Stock (Task 5's
  DESIGN.md hunk). V7 card is Part 6; G5 ("what changed") stays deferred (ruling 1).
- **Prototype.** As the Plan written row: every patch was cut from a per-task git history of a prototype that passed
  the full Python and web gates and a scratch build, and rendered against `mock5` at three widths in both themes.
- **Placeholders.** None: every change is a patch; the two scripts are given in full; commands carry expected output.
- **Type consistency.** `size_pct`, `tranches`, `tranches_done`, `tranche_min_sessions`, `last_tranche_on`,
  `claude_note` (models, router, value_db, tests, `api-types.ts`, `stock.ts`, `format.ts`, `SizeBlock`, fixtures).
