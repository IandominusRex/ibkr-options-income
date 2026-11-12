# Web Overhaul, Part 7: News, More and How It Works (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task
> (one Sonnet subagent per section, at the effort the Execution model gives, with a stop between sections: the
> operator's token-light method). Each section opens with **entry checks** that must all pass before its first task
> starts. **Every task that touches UI starts by invoking the `da-vinci` skill**, and so does any subagent given one of
> those tasks (say so in its prompt). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the last legacy pages on the payslip, close `web/DESIGN.md`'s Open Decisions, and land the small carried
items the operator took on 2026-11-07 (HANDOFF 5.4, every answer as recommended):

- **Carried** (Part 6 Task 15's two proposals; three Part 5 stock-page minors): the rail's Search row becomes an
  outlined field; a sector's IV-rank count reads "(7 with history)"; the Sentiment rows say n/a once; the tranche
  sentence and the sample counts set in tabular figures; the statements' scroll hint stays up to 1024px.
- **News** (L4): the feed and the ticker page in the Stock/Research frame, the Market card first, 44px controls, the
  calendar as a card of rows, the news verdict in ink (a forecast is not money), the ticker page cross-linked to the
  stock page. `NewsCard`'s content and `BriefRequest`'s `news_brief` command stay.
- **How it works** (L5, the operator's answer (a)): one small page of static plain-English sections in
  `features/explain/`, each linking to the page that shows it; `components/explain/` (1,532 lines with tests) deleted.
- **More** (L6): a "Value book" row, and the theme, target-mode and credits controls restyled in place.
- **Open Decisions** (S4, the six defaults): recorded in `DESIGN.md`; the code they need is a favicon and the
  disabled quiet button's rule.

**Architecture:** Web only. Section A edits `components/shell/Rail.tsx`, `components/home/SectorCard.tsx`,
`components/stock/{SentimentPanel,StatementsTable}.tsx` and `features/stock-value/SizeBlock.tsx` in place. Section B
adds `features/news/` (the feed and ticker pages; the routes only mount them) and restyles `components/news/*` in
place. Section C adds `features/explain/ExplainPage.tsx` and deletes `components/explain/`. Section D edits
`app/more/page.tsx`, `components/ui/Button.tsx` and adds `app/icon.svg`. No API route or field, no Python file, no
command site, no protected file, no token, colour, font, radius or elevation. Nothing reaches the Rules Engine, a
gate, sizing or the value book's logic.

**Tech Stack:** Next.js 15 App Router, React 19, Tailwind CSS v4, @tanstack/react-query, lucide-react, Vitest + Testing
Library. (Python is untouched; its gate runs to prove it.)

**Spec:** `docs/superpowers/plans/2026-11-05-web-overhaul-HANDOFF.md` (updated 2026-11-07 after Part 6: sections 3-6
bind this plan; 5.4 holds the outline and the operator's five answers), `web/DESIGN.md` (the visual authority),
`web/CLAUDE.md`, root `CLAUDE.md` (the web fence, the doc-update table, the Progress-log rule).

## How the code is given (read this first)

**Every change in this plan is a `git diff` patch embedded below, one per task**, generated from a per-task git
history of a prototype (see the Plan written row) and applied with `git apply`. A patch is the complete, exact code:
new files appear in full, deleted files in full, edits with their surrounding lines. So:

- **Never retype a patch.** Extract it with the helper written in A0 (`<S>/p7/plan_block.py`, `<S>` = the session's
  scratchpad directory, written out in full each time), check its SHA-256 against the table below, then
  `git apply --check` it. **`git apply --check` is the entry check that re-verifies every line a task edits**: if
  `main` moved under a patch, it fails and the section stops.
- The helper restores a blank context line an editor may have stripped (a diff's blank context line is one space);
  everything else is byte for byte. Edit this plan only with the Edit tool (Progress log rows, checkboxes), which
  leaves the patch blocks alone.
- Two blocks are not patches: `mock7` (the synthetic API for the finish) and `capture7` (the capture harness).

| Block | SHA-256 of the extracted file | Applies on top of |
|---|---|---|
| `T1` | `ab3bec3bbb09c86ffcbd0b7ef800343998d5a81f9cb14094185dae11459e2ef4` | `main` at A0 (`02236ec` + the plan commit) |
| `T2` | `8c21582d9228c8fe35d5b5d435e5532d8eaaac2c3a4bd3b2f31166293213e5b8` | T1 |
| `T3` | `8b286fe0065c9ebe4be093cc7e96e9dd860ef7541bd9dbae8fe5bcf23ad5eb6e` | T2 |
| `T4` | `4f5f4bcb714fcba23b4e6261e021bca966d1f5c6384781202e86fb460aa45d87` | T3 |
| `T5` | `9580231e9eb70d3e60ca73fc6cc08c6689090de0570d0e0a76b2392c722995c2` | T4 |
| `T6` | `78270c176e4ae6c5bd8541136337b58008b57f5d01420151b0b6eb1fd360d5a9` | T5 |
| `T7` | `d6363fb0a1115f5cafc23465aaf78d89eae23d9ecbc4aaf491868384efc49047` | T6 |
| `T8` | `3c629e8e567e16488125bb65e79cc113dce169662066de2dccffabf765f6e468` | T7 |
| `T9` | `7da611db4a2e18c030e2d247023fd22747ee660efdaf220a9d29c2e23be7eb16` | T8 |
| `T10` | `da83ae7192c0cbd409f09b103cfe5afd8adcb450d981b3267fa521523c08145c` | T9 |
| `mock7` | `cdac96883e24ec18965719fdd5292a776f1aa5f19ac9a8df15304b4c94084cee` | (a script, not a patch) |
| `capture7` | `e701a8ee3cc2ab494169a86f076648819b3c78c1a0de4c9ae12077ba53e4a4d8` | (a script, not a patch) |

## Execution model

| Section | Tasks | Model | Effort | Why this model and effort |
|---|---|---|---|---|
| **A, Carried** | 1-2 | **sonnet** | medium | Two small patches over five components, each with its red check; nothing to decide. |
| **B, News** | 3-5 | **sonnet** | high | A new page frame over two routes, a restyle in place under existing suites, and a page that hosts a command site (`BriefRequest`) whose behaviour must not move; da-vinci first. |
| **C, How it works** | 6-7 | **sonnet** | high | A page of static copy whose every sentence must stay true to `CLAUDE.md` and the code, then a 1,532-line deletion with the search list and More kept consistent. |
| **D, More and Open Decisions** | 8-9 | **sonnet** | high | A shared component's rule (`components/ui/Button.tsx`, used across the console) and `DESIGN.md`'s decisions; Task 8 alone would be medium. |
| **E, Finish** | 10-11 | **sonnet** medium (Task 10, docs), **sonnet** high, a fresh agent (Task 11, the da-vinci finish) | as listed | Then one **opus** whole-branch review (high) and one **sonnet** fix pass (high). |

**How a section runs (the orchestrator).** The main session is a Sonnet orchestrator (effort high). For each section:

1. Run the section's **entry checks** yourself, in order. **Any check fails: stop**, report the output, do not start
   the section. A failure that belongs to the previous section is fixed there (record the ruling) first.
2. All pass: add a "Section X entry" row to the Progress log (gate result, date) in the worktree.
3. Spawn **one** subagent for the section with `model` and `effort` from the table (pass `effort` on every spawn). Its
   prompt: "You are executing Section X of `docs/superpowers/plans/2026-11-07-web-overhaul-7-news-more-how-it-works.md`
   in the worktree `<W>` (the absolute path). The session scratchpad is `<S>` (the absolute path); the patch helper is
   `<S>/p7/plan_block.py`. Read the plan's 'How the code is given', 'Global Constraints' and your section only, plus
   the files the section lists under Reads. Apply each task's patch exactly as its steps say; never retype a patch;
   never edit a protected file; never build or run `next dev` inside `web/`. Invoke the `da-vinci` skill before any
   UI step and give it the section's Spec for da-vinci paragraph. Commit each task with its message, ticking its boxes
   and filling its Progress log row in the same commit (status, commit, gate, date, every ruling with its
   cost-if-wrong). Stop on any red gate you cannot attribute to your own change."
4. Verify the report yourself: `git log --oneline main..HEAD`, `git status --short`, the gate counts against the
   section exit, G1, G2 and G7.
5. **Stop and ask the operator before the next section.**

After Section E's Task 11: one **opus** whole-branch review (superpowers:requesting-code-review, effort high) over
`main..HEAD` with the Review Focus below, as a subagent; the orchestrator confirms each finding in the code; one
**sonnet** fix pass (high), each fix test first. Ask before merge or push; fill the Merge, Push and Restart rows after
each happens.

**Commit counts.** A0 adds one commit on `main` (this plan, the HANDOFF and Part 6's Restart row). Each task is one
commit and fills its own Progress log row; a "Section X entry" row rides in the next task's commit. A review fix pass
adds one commit.

## Progress log

| Section / task | Status | Commits | Gate | Date | Rulings |
|---|---|---|---|---|---|
| **Plan written** | done | (plan file only) | Written in four increments 2026-11-07 to 2026-11-11 (`main` was `02236ec` throughout). Prototyped on a code-only copy of `main` (`git archive`, `.venv` and `web/node_modules` symlinked, session scratchpad) as a per-task git history from which every patch was generated (one fix found by looking was folded back into T3 with `--fixup`). **Per-task web gates** (each re-run when the patches were applied in order to a fresh copy of `main`): vitest 1623 in 157 files at T1, 1624/157 at T2, 1631/158 at T3, 1639/159 at T4, 1644/160 at T5, 1649/161 at T6, 1620/153 at T7 (eight test files deleted), 1621/153 at T8, 1622/153 at T9 and T10; `tsc --noEmit` and `npm run lint` clean at every task. **Red checks run** (each task's source files at their pre-task version, its tests kept): T1 3 failed / 8 passed; T2 3 / 29; T3 4 / 3; T4 9 / 2; T5 6 / 2; T7 2 / 12 (by the `git stash` form in its Step 2, on the fresh copy); T8 1 / 8; T9 1 / 11; T6 is a new module (red = module missing); T10 is docs. **Full gate on the final tree** (all ten patches applied in order to a fresh copy of `main`, identical to the prototype): vitest **1622 in 153 files**; `tsc --noEmit` and `npm run lint` clean; pytest **5767 passed, 1 skipped** (G6 included), `ruff check .` clean, `mypy src` 361 files clean; G1 empty; G2 the four `features` files and `components/news/BriefRequest.tsx`; G3 exit 0 (`grep -c RESOLVED web/DESIGN.md` 8); G5 no line for a non-test file over every Part 7 folder; G7 the one layout line; no file under `src/`, `scripts/`, `tests/` or `config/` changed; D2 confirmed (T9 applies before T8); **scratch `npm run build` green** (20 rows: 18 routes, `/_not-found`, `○ /icon.svg`; Section B's exit build was green at 19 rows, after one transient font-fetch retry on a later build). **Rendered** with `next start -p 3102` from the prototype's build against `mock7` (port 8798) and `capture7` in headless Chromium: News, `/news/NVDA`, How it works, More and Research at 320, 390 and 1440 px, light and dark (30 page captures): `hscroll` on `main` 0 everywhere, no page error, the `h2` orders as Task 11 expects, the under-44px set exactly ruling 25's; captures opened and read: News at 1440 light, `/news/NVDA` at 390 dark, How it works at 390 light. **Not run:** a fresh-eyes da-vinci critique and audit (Task 11), the live API, the stock page rendered (Task 2's three changes are pinned by tests only), the Opus review. |
| **A0 setup** | done | 7eb2ae8 (docs on main) | Worktree `.claude/worktrees/web-overhaul-7` (branch `feat/web-overhaul-7`), `.venv` and `web/node_modules` symlinked, init_db run; all 12 block hashes match; 14 GiB free | 2026-11-12 | Part 6's Restart row filled as the plan gave it (dated 2026-11-07). Orchestrator is a Sonnet session; plan gate counts held. Operator said "execute everything to completion": sections run without stopping between them; merge and push still wait for a yes. |
| **Section A entry** | pass | (rides in Task 1) | A1 clean over 02236ec + A0; A2 T1 and T2 apply; A3 pytest 5767 passed, 1 skipped, ruff clean, mypy 361 files, vitest 1623 in 157 files, tsc and lint clean | 2026-11-12 | none |
| **Task 1: the rail's Search field and the sectors' count** | done | this commit (see git log) | T1 applied (hash ab3bec3b matched, git apply --check clean); red check 3 failed / 8 passed; components/shell+home+features/research 13 files 106 passed; full vitest 1623 in 157 files; tsc and lint clean; G3 exit 0 | 2026-11-12 | da-vinci: no change (the patch matches Section A's spec). No rulings; none deviated. |
| **Task 2: the stock page's three minors** | done | this commit (see git log) | T2 applied (hash 8c21582d matched, check clean); red check 3 failed / 29 passed; components/stock+features/stock-value 9 files 77 passed; full vitest 1624 in 157 files; tsc and lint clean; G1 empty; G2 as listed; G5 no line | 2026-11-12 | da-vinci: no change. No rulings; none deviated. |
| **Section A exit** | pass | rides in Task 2's commit | two task commits after A0; vitest 1624 in 157 files; tsc, lint clean; G1 empty, G2 exact, G3 exit 0, G5 (shell, home, stock, stock-value) no line, G7 the one layout line; git status clean after commit | 2026-11-12 | none |
| **Section B entry** | pass | (rides in Task 3) | B1 two Section A commits (c9eb71e, 971b9d7), vitest 1624 in 157 files, tsc and lint clean, G1 empty, G2 exact, G7 one line; B2 T3, T4, T5 apply; B3 no features/news, BriefRequest the only submitCommand, 3/3/3 `it(` | 2026-11-12 | none |
| **Task 3: the News page** | done | this commit (see git log) | T3 applied (hash 8b286fe0 matched, check clean); red check 4 failed / 3 passed; components/news+features/news+app/titles 5 files 41 passed; full vitest 1631 in 158 files; tsc and lint clean; G5 over components/news, features/news, app/news no line for a non-test file | 2026-11-12 | da-vinci read T3 against Section B's spec: no change (no lime, green, red or em dash in the added lines). No rulings; none deviated. |
| **Task 4: the calendar and the news card** | done | this commit (see git log) | T4 applied (hash 4f5f4bcb matched, check clean); red check 9 failed / 2 passed; components/news+features/news 5 files 24 passed; full vitest 1639 in 159 files; tsc and lint clean; G5 no line for a non-test file | 2026-11-12 | da-vinci read T4: no change (verdict pill in ink, no green or red, no lime, no em dash in added lines). No rulings; none deviated. |
| **Task 5: the ticker news page** | done | this commit (see git log) | T5 applied (hash 9580231e matched, check clean); red check 6 failed / 2 passed; components/news+features/news+app/titles 7 files 54 passed; full vitest 1644 in 160 files; tsc and lint clean; G1 empty; G2 both greps exact; G3 exit 0; G4 scratch build green first try (19 rows, `○ /news` and `ƒ /news/[symbol]`, `○ /explain`, `○ /more`; removed); G5 no line; G6 55 passed; G7 the one layout line | 2026-11-12 | da-vinci read T5: no change (the only `lime`/`text-loss` hits in added lines are a comment and a test asserting their absence). No rulings; none deviated. |
| **Section B exit** | pass | rides in Task 5's commit | three task commits after Section A; vitest 1644 in 160 files; tsc, lint clean; G1 empty, G2 both greps exact, G3 exit 0, G4 green (19 rows), G5 (Section A folders + components/news, features/news, app/news, app/explain, app/more, components/ui) no line for a non-test file, G6 55 passed, G7 one line; git status clean after commit | 2026-11-12 | none |
| **Section C entry** | pass | (rides in Task 6) | C1 five task commits, vitest 1644 in 160 files, tsc and lint clean, G1 empty, G2 exact, G7 one line; C2 T6 applies; C3 26 files in components/explain, only app/explain/page.tsx imports it, no features/explain | 2026-11-12 | none |
| **Task 6: How it works** | done | this commit (see git log) | T6 applied (hash 78270c17 matched, check clean); red check: features/explain stashed, vitest reports "No test files found" (module missing); features/explain + app/titles 2 files 30 passed (ExplainPage 5 passed); full vitest 1649 in 161 files; tsc and lint clean; G3 exit 0; G5 over web/features/explain web/app/explain: no line for a non-test file (one em dash line in ExplainPage.test.tsx:41, which is the test's own assertion string, a test file) | 2026-11-12 | da-vinci read T6 against Section C's spec: no change (seven Cards in one column at max 820px, 1.0625rem bold titles, 65ch 14px body, 0.8125rem muted "See it on" then underlined semibold links at min-h-11 md:min-h-0; no lime, icon, chip or tab). Copy checked against root CLAUDE.md (core invariant, both written exceptions, books, capital release, paper-only) and the code (regime reads SPY and QQQ per `src/analytics/regime.py`; MarketCard on Home and News): every sentence true, none reworded. No rulings; none deviated. |
| **Task 7: the old explainer deleted** | done | this commit (see git log) | T7 applied (hash d6363fb0 matched, check clean; 26 D lines and the four M files as listed); red check 2 failed / 12 passed (by the `git stash push --` form, then pop, `ls web/components/explain` fails); features/explain+features/search+app/more+app/titles 4 files 47 passed; full vitest 1620 in 153 files; tsc and lint clean; G1 empty; G2 both greps exact; G3 exit 0; G5 over the full Section C list no line for a non-test file; G6 55 passed; G7 the one layout line; `grep -rl components/explain` over web/app, features, components, lib and DESIGN.md finds only the test that asserts the folder is gone | 2026-11-12 | No rulings; none deviated. |
| **Section C exit** | pass | rides in Task 7's commit | two task commits after Section B; vitest 1620 in 153 files; tsc, lint clean; G1 empty, G2 exact, G3 exit 0, G5 (shell, home, stock, stock-value, components/news, features/news, app/news, features/explain, app/explain, app/more, features/search) no line for a non-test file, G6 55 passed, G7 one line; git status clean after commit | 2026-11-12 | none |
| **Section D entry** | pass | (rides in Task 8) | D1 seven task commits, vitest 1620 in 153 files, tsc and lint clean, G1 empty, G2 exact, G7 one line; D2 T8 and T9 apply; D3 no icon.svg, `disabled:bg-sunk` count 1, RESOLVED count 2 | 2026-11-12 | none |
| **Task 8: More** | done | this commit (see git log) | T8 applied (hash 3c629e8e matched, check clean; three ` M` files as listed); red check 1 failed / 8 passed (`web/app/more/page.tsx` stashed, then popped); `vitest run app/more` 9 passed; full vitest 1621 in 153 files; tsc and lint clean; G3 exit 0 | 2026-11-12 | da-vinci read T8 against Section D's spec: no change (one row after Universe, bold label, muted sub line, the same chevron; nothing else on More moves; no new token). No rulings; none deviated. |
| **Task 9: the Open Decisions** | done | this commit (see git log) | T9 applied (hash 7da611db matched, check clean; three ` M` files and `?? web/app/icon.svg` as listed); red check 1 failed / 11 passed (`web/components/ui/Button.tsx` stashed, then popped); `vitest run components/ui features/trades features/activity` 28 files, 310 passed; full vitest 1622 in 153 files; tsc and lint clean; `grep -c RESOLVED web/DESIGN.md` 8; G3 exit 0 | 2026-11-12 | da-vinci read T9 against Section D's spec: no change (quiet stays transparent and dims, primary and secondary keep disabled:bg-sunk and muted ink, the favicon is the ink I on the paper-value rounded square; no new token, colour, font, radius or elevation). No rulings; none deviated. Order 8 then 9 as the plan gave (D2 hunks disjoint). |
| **Section D exit** | pass | rides in Task 9's commit | two task commits after Section C; vitest 1622 in 153 files; tsc, lint clean; G1 empty, G2 both greps exact, G3 exit 0, G4 scratch build green first try (20 rows: `○ /icon.svg`, `○ /news`, `ƒ /news/[symbol]`, `○ /explain`, `○ /more`; removed), G5 (Section C list plus components/ui) no line for a non-test file, G6 55 passed, G7 one line; git status clean after commit | 2026-11-12 | none |
| **Section E entry** | | | | | |
| **Task 10: docs** | | | | | |
| **Task 11: the da-vinci finish by a fresh reviewer** | | | | | |
| **Whole-branch review (opus)** | | | | | |
| **Review fix pass (sonnet)** | | | | | |
| **Merge** (fast-forward onto `main`, on the operator's yes) | | | | | |
| **Push** (on the operator's yes) | | | | | |
| **Restart** (web only: write "not needed" unless a Python file changed; otherwise `./ibkr restart` and the `ps` start time) | | | | | |

*(Rows are filled as each task lands; a ruling is any deviation from the task text, and why, with its cost if wrong.)*

## Roadmap (this plan is Part 7 of 8, HANDOFF section 5)

- **Parts 1-6** and the value book's web sections F-I: done, merged and pushed.
- **Part 7, News, More and How it works.** This plan.
- **Part 8, The value record** (F5, V9), gated on a month of paper record. **Order control** on its own track (spec
  first).

## Rulings made up front (the operator may overturn any of them)

**Scope:**

1. **Scope is the HANDOFF's Part 7 row and outline (5.4) with the operator's five answers**: L4, L5, L6, S4, S5 (News,
   How it works and More paragraphs), Part 6 Task 15's proposals (a) and (b), and three Part 5 stock-page minors. No
   API route or field, no Python file. `_one_line`'s trailing comma (Python) stays deferred. *Cost if wrong: none.*

**The operator's answers (2026-11-07, HANDOFF 5.4), as rulings:**

2. **How it works is rebuilt small** (answer (a)): one page, static copy in the web, no API read, about seven short
   sections, each linking to the console page that shows it. The eight-panel shell goes. *Cost if wrong: a bigger
   page later.*
3. **The six Open Decisions take their defaults**: "IBKR Income" as a text wordmark and a text-mark favicon; lucide
   icons; the immediate sheet close; the legacy bordered decide controls inside sheets as the recorded exception (the
   protected files are untouched); a disabled quiet button stays transparent and only dims. *Cost: a ruling each.*
4. **`/news/[symbol]` stays**, restyled, with a link to `/stock/SYM` (and nothing folded into the stock page, which
   would then carry a command site). *Cost if wrong: a redirect later.*
5. **Both Part 6 proposals are taken**: the rail's Search row is an outlined field; a sector's IV-rank count reads
   "(N with history)". *Cost: classes and copy.*
6. **The three web-only Part 5 stock minors are in** (Section A, Task 2). *Cost: none.*

**The carried items (Section A):**

7. **The rail's Search field** is the shared field's edge on white (`border border-control bg-surface`, the
   `components/ui/field.ts` look at the rail's row size), muted text, ink on hover; no hover fill, so the current
   destination is the rail's only pressed-sage row. Its height, icon, "⌘K", `aria-keyshortcuts` and behaviour are
   unchanged. *Cost if wrong: classes.*
8. **"(N with history)" for every count**, "(1 with history)" included (the old "(1 name)" special case goes: the
   words now say what the count is). *Cost: copy.*
9. **The Sentiment row says n/a once**: a source with neither a score nor a count shows the hatched n/a score and no
   samples text; a source with a score and no tracked count still says "n/a samples" (the existing test that pins
   this stays). Sample counts and the tranche sentence carry `.tabular`. **The statements' scroll hint shows below
   1024px** (`lg:hidden`), since the stock page's column is too narrow for a long quarterly table until its two
   columns open. *Cost: classes.*

**Standing rules:**

10. **Protected files are byte-identical to `main`** (G1), **the command-site grep is unchanged** (G2) and **one
    palette is mounted** (G7). `components/news/BriefRequest.tsx` (a `submitCommand("news_brief")` site outside the G2
    grep) stays in `components/news/` with its command, its `CommandReceipt` and its poll unchanged.
11. **No new token, colour, font, radius or elevation.** Green and red only on signed money (HANDOFF ruling 7).
    **Docs**: `web/DESIGN.md` lands with the UI it describes; `STATUS.md`, `ARCHITECTURE.md` and `web/CLAUDE.md` in
    Task 10. No route, field, config key, script, command kind or Telegram command is added, so `docs/web/api.md`,
    `docs/web/commands.md`, `SETUP.md` and `README.md` do not change.
12. **Effort per section** follows the operator's 2026-11-06 instruction (medium for mechanical edits, high for UI and
    shared state). **Never build inside `web/`** (G4).

**News (Section B):**

13. **News takes Research's frame** (`features/news/NewsPage.tsx`; `app/news/page.tsx` keeps its `metadata` and only
    mounts it): the title "News", the line "What moved, what is scheduled this week, and what the news service made of
    it. Nothing here trades.", Refresh at the right; the Market card full width; then `lg:grid-cols-[minmax(0,1fr)_340px]`,
    each column one `grid min-w-0 grid-cols-1` track: the feed left, the calendar right. *Cost: classes and copy.*
14. **The feed is "Latest", restyled in place** (`components/news/NewsFeed.tsx`): the group chips are
    `SegmentedControl` (`appearance="chips"`, label "Show"; the "All" chip is the value `all`, which sends no `group`
    parameter, as `null` did); the symbol field is `FIELD` with a visible "Filter by symbol" label and no
    `aria-label`; the 300ms debounce, the 30-post limit, the 60s poll and the three existing test strings are
    unchanged. Loading is a labelled block; a failed read, "not written yet" and no match are sentences in ink (a
    failure is never red). *Cost: copy.*
15. **The calendar is one card, "This week"**, that never vanishes: it used to render nothing while loading, on a
    failed read and before the news service wrote; each is now a sentence, and an empty list says "None in the next 7
    days." An earnings ticker links to `/news/SYM` (it used a bare `<a>`; now `next/link`), "held" becomes a neutral
    "Held" status word, times use `.tabular` in the body font (no mono). *Cost: copy.*
16. **A post's content is the news service's and stays**, emoji included (the reaction grid's coloured circles are
    the service's text, not this page's styling; the actual move beside each is signed). Restyled only: a `Card`, a
    17px/700 title, "Critical" as a flag word, the time on its own muted line, source links that say they open a new
    tab. **The explanation is labelled "The news model's reading"** with "Claude, or the local model when Claude cannot
    be reached; it trades nothing", because `config/examples/news.yaml` runs `llm.backend: cli_then_ollama`: the text
    may not be Claude's (HANDOFF section 6: label text by its model). A digest's per-item readings get one line saying
    they are the news model's. *Cost if wrong: copy.*
17. **The verdict pill is an outlined ink pill** (`border border-border`, `text-content`; "Unclear" muted): the icon
    and the words carry the direction; a forecast is not money, so never green or red (HANDOFF ruling 7). The
    confidence reads "medium confidence". *Cost: classes.*
18. **The ticker page** (`features/news/NewsTickerPage.tsx`; `app/news/[symbol]/page.tsx` mounts it with
    `decodeSegment`, as Part 6's review fix did for the position page) has a back link to News, the ticker as the
    title, a "Stock page" pill link to `/stock/SYM` and Refresh; the brief request under the header. The body stays in
    `components/news/NewsTicker.tsx` (restyled in place, its header moved to the page), at most 820px wide.
    **`BriefRequest` stays in `components/news/`** (outside G2's `features` grep, so that grep is unchanged) and only
    its look changes: the secondary `Button`, a refused request in ink (it was `text-loss`). *Cost: classes.*
19. **The News Surfaces paragraph is rewritten in Task 5** (JOB, FORM, Latest, A post, This week, A ticker page) with
    a Decision Log entry. *Cost: none.*

**How it works (Section C):**

20. **How it works is `features/explain/ExplainPage.tsx`**, a server component with no request (`app/explain/page.tsx`
    keeps its `metadata` and only mounts it): the title, one muted line, then seven `Card`s in one column at most
    820px wide, each a 17px/700 title, two to four short paragraphs (65ch) and a "See it on" line of underlined links
    (44px rows on a phone). The copy is in the T6 patch, word for word; each sentence traces to root `CLAUDE.md`
    (the core invariant and its two written exceptions, the spreads and value fences' paper-only rules, capital
    release, the news fence) or the code. `PARTS` is exported so a test holds every link to a page in
    `features/search/pages.ts`. *Cost if wrong: copy.*
21. **`components/explain/` is deleted** (26 files, eight of them test files holding 30 tests; nothing else imports
    it), with its `SourceRefs.tsx:21` em dash. The search palette's hint and More's row now read "The system in plain
    English" ("..., and where to see it" on More). A test pins the folder's absence. *Cost: none.*

**More and the Open Decisions (Section D):**

22. **More gets a "Value book" row** in its links card, to `/research` ("Its candidates lead Research; each name's
    file is on its stock page"): the book has no page of its own (HANDOFF ruling 4). The rows are keyed by label
    (two now share `/research`), and the existing test's `/Research/` query is anchored to `/^Research/`. **Nothing
    else on More changes:** TargetCard's red field edge and error stay (DESIGN.md's Field rule draws a field error in
    loss, ratified), and the theme and target-mode `SegmentedControl`s already have the 44px phone hit area
    (Part 6's finding (f), re-read in the prototype's captures). *Cost: copy.*
23. **The Open Decisions close on their defaults** (ruling 3): `components/ui/Button.tsx` moves `disabled:bg-sunk`
    from the base classes to the primary and secondary variants, so a disabled quiet button stays transparent and
    dims through `disabled:text-muted` (History's, Spreads' and Activity's end-of-range arrows); `web/app/icon.svg` is
    a 32px rounded square in the paper value `#f2f4ef` with an ink `#111410` "I" in Hanken Grotesk 800 (an asset
    cannot read CSS variables; the values are the existing tokens', so no new colour; the tab icon is not themed);
    the "IBKR Income" wordmark in `Rail.tsx` is unchanged. Each Open Decision is marked RESOLVED in `DESIGN.md` with
    one Decision Log entry. *Cost: a ruling each.*

**Finish (Section E):**

24. **Task 10 is docs only**: `STATUS.md` (a Built section and the overview row), `ARCHITECTURE.md` (the Part 7 line,
    the News and How it works paragraphs), `web/CLAUDE.md` (`app/news`, `app/explain`, `components/news`,
    `features/news`, `features/explain`; the two `explain/` blocks go). `README.md`, `SETUP.md`, `docs/web/api.md`
    and `docs/web/commands.md` do not change (no route, field, kind, command or setup step). The orchestrator updates
    the HANDOFF after the merge, as for Part 6. *Cost: none.*
25. **What the prototype's render found** (`mock7` + `capture7`, 30 captures): `hscroll` on `main` 0 everywhere, no
    page error, the `h2` orders as Task 11 expects. **One fix was folded into T3**: the symbol field's placeholder
    "NVDA" read like a filter already applied, so it is "Ticker". **One finding is left for Task 11's reviewer**: on a
    phone a post's emoji sits alone on the line above a long title (the header wraps). Under 44px on a phone, expected
    and accepted: the group chips and More's target-mode chips (24px pills with a 44px hit area), More's theme track
    (34px, the same rule), the source links inside a post's headline line and the TradingView credit (inline links in
    prose, WCAG 2.5.8's inline exception), and Research's two list tabs and its inline Universe link (Part 6's).
    *Cost: none.*


## Global Constraints

- Core invariant, the fences and the two written exceptions in root `CLAUDE.md` are untouched. Nothing here places,
  sizes, prices or gates anything; Claude's words stay labelled and never sit on a button.
- The API is not touched: it still writes exactly one trading-DB table (`app_commands`); `src/api/` imports from
  `src.value` only `scorecard` and `schemas`. `tests/test_web_fence.py`, `test_eval_skills.py`, `test_regime_fence.py`,
  `test_news_fence.py`, `test_spreads_fence.py`, `test_value_fence.py` and `test_wheel_spreads_isolation.py` stay green
  and unweakened.
- UI: tokens only (no raw palette class, no hex); `.tabular` on numbers; lime only on the primary act; unknown is a
  hatched `n/a`, never `$0` or blank; no state by colour alone; green and red only on signed money; no shadow except the
  sheet and the confirm dialog; 44px phone targets; zero em dashes and none of "seamless", "robust", "unlock",
  "elevate" in UI copy.
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
  `web/features/stock-value/AnalyseButton.test.tsx`, `web/features/stock-value/AnalyseButton.tsx`; and
  `grep -rln "submitCommand" web/components/news | sort` prints exactly `web/components/news/BriefRequest.tsx`.
- **G3, design spec:** `python3 ~/.claude/skills/da-vinci/scripts/design_md_check.py web/DESIGN.md` exits 0.
- **G4, scratch build** (never inside `web/`; the `mktemp` + `rm -rf "$(dirname ...)"` form is refused by the sandbox,
  so use the scratchpad by literal path):
  `rm -rf <S>/p7/build && mkdir -p <S>/p7/build && rsync -a --exclude node_modules --exclude .next web/ <S>/p7/build/web/ && ln -s <W>/web/node_modules <S>/p7/build/web/node_modules`
  then `cd <S>/p7/build/web && npm run build`. Expect the route table with `/news`, `/news/[symbol]`, `/explain` and
  `/more` among **18 routes plus `/_not-found`** (19 rows; **20 from Task 9 on**, which adds `○ /icon.svg`). If it fails with `Cannot read properties of null (reading
  '1')` in `next/font/google`, that is the known transient font fetch: run the build again, up to three tries. Then
  `rm <S>/p7/build/web/node_modules` and `rm -rf <S>/p7/build` (Task 11 keeps it until its own last step).
- **G5, da-vinci lint:** `python3 ~/.claude/skills/da-vinci/scripts/lint.py <folders>` prints no line for a non-test
  file, where `<folders>` is every folder this part touches **that exists at that point** (`lint.py` refuses a missing
  path): `web/components/shell web/components/home web/components/stock web/features/stock-value web/components/news
  web/app/news web/app/explain web/app/more web/components/ui`, plus `web/features/news` from Task 3 and
  `web/features/explain` from Task 6, and minus `web/components/explain` (it fails until Task 7 deletes it: its
  `SourceRefs.tsx:21` em dash is the one known finding).
- **G6, fences:** `python -m pytest -q tests/test_web_fence.py tests/test_value_fence.py tests/test_eval_skills.py tests/test_openapi_current.py` passes.
- **G7, one palette:** `grep -rn "<CommandPalette" web/app web/components web/features | grep -v "\.test\."` prints
  exactly one line, `web/app/layout.tsx:55:          <CommandPalette />`.

**Extracting and applying a patch.** A0 extracts every block to `<S>/p7/<name>.out` and checks the hashes. A task
step "Check and apply `Tn`" means, from `<W>`:

```bash
git apply --check <S>/p7/Tn.out      # prints nothing; any error: stop and report it
git apply <S>/p7/Tn.out
```

If `<S>/p7/Tn.out` is missing (a new session), re-extract it first and check its hash:
`python3 <S>/p7/plan_block.py docs/superpowers/plans/2026-11-07-web-overhaul-7-news-more-how-it-works.md Tn > <S>/p7/Tn.out && shasum -a 256 <S>/p7/Tn.out`
(the helper itself is written in A0; write it again from A0 if the scratchpad is new).

## Review Focus

1. **Nothing reaches the trading path**: G1, G2, G6 at every exit; no file under `src/` changes; `BriefRequest`'s
   command, receipt and poll are byte-identical in behaviour (its tests unchanged) → Tasks 4-5.
2. **No green or red off money**: the news verdict pill, any move or tone on the News pages → Tasks 3-5.
3. **Unknown is never none**: the feed's loading, empty and failed states in words; the ticker page with no brief or
   no news service; the Sentiment row's one n/a → Tasks 2-5.
4. **How it works says only what is true**: every sentence traceable to root `CLAUDE.md` or the code; Claude's two
   written exceptions stated as exceptions, not as Claude trading; no em dash → Task 6.
5. **The deletion leaves no dangling import or link**: `components/explain/` gone, the search page list, More and the
   nav still reach `/explain` → Task 7.
6. **The disabled quiet button** dims and stays transparent everywhere it is used (History's, Spreads' and Activity's
   end-of-range arrows), and no other variant changes → Task 9.
7. **Copy is honest**: the "(N with history)" count, the Search field, the Value book row's words → Tasks 1, 8.

---

## File structure

```
docs/superpowers/plans/2026-11-07-web-overhaul-7-news-more-how-it-works.md, the HANDOFF,
docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md (Restart row)       COMMIT (A0, on main)
web/components/shell/Rail.tsx (+ test), web/components/home/SectorCard.tsx (+ test), web/DESIGN.md       MODIFY  (T1)
web/components/stock/SentimentPanel.tsx, StatementsTable.tsx (+ tests),
web/features/stock-value/SizeBlock.tsx (+ ValueBlock.test.tsx)                                         MODIFY  (T2)
web/features/news/ (the feed and ticker pages), web/app/news/**, web/components/news/* (in place),
web/DESIGN.md                                                                                   CREATE/MODIFY (T3-T5)
web/features/explain/ExplainPage.tsx (+ test), web/app/explain/page.tsx                         CREATE/MODIFY (T6)
web/components/explain/** (26 files)                                                                     DELETE  (T7)
web/app/more/page.tsx (+ test), web/components/shell/ThemeToggle.tsx (in place)                          MODIFY  (T8)
web/components/ui/Button.tsx (+ test), web/app/icon.svg, web/DESIGN.md                            MODIFY/CREATE (T9)
STATUS.md, ARCHITECTURE.md, web/CLAUDE.md                                                                MODIFY  (T10)
```

(The writer pins the exact file list of Tasks 3-11 with their sections; Sections B-E below are the authority.)

---

## Section A: Carried (Tasks 1-2) · model: sonnet (effort medium)

**Reads:** this section; `web/components/shell/Rail.tsx` (lines 30-45); `web/components/home/SectorCard.tsx` (lines
14-40); `web/components/stock/SentimentPanel.tsx` (lines 15-40); `web/components/stock/StatementsTable.tsx` (lines
80-88); `web/features/stock-value/SizeBlock.tsx` (lines 35-45).

**Spec for da-vinci (Tasks 1 and 2; give it this, so it has little to decide):** Task 1: the rail's Search row is an
outlined field, a 1px control-edge border (`border-control`) on white (`bg-surface`), radius 10px, muted text and
icon, ink on hover, no fill on hover; the current destination stays the only pressed-sage row. A sector's IV rank
reads "IV rank 71.2 (7 with history)", the count muted and tabular. Task 2: one hatched n/a for a sentiment source
with no score and no count; tabular figures on sample counts and the tranche sentence; the statements' scroll hint
below 1024px. No other visual change; da-vinci changes nothing; record "no change" in the row.

**A0. Setup (orchestrator, before the entry checks).**

- [ ] In the main checkout (`/Users/ianlim/Desktop/IBKR Investments`, on `main`): `git status --short` shows only
  ` M docs/superpowers/plans/2026-11-05-web-overhaul-HANDOFF.md`,
  `?? docs/superpowers/plans/2026-11-07-web-overhaul-7-news-more-how-it-works.md` and `?? data/value_filing_reads.json`
  (a runtime file: leave it alone).
- [ ] Fill Part 6's Restart row (HANDOFF operator to-do 2) with the Edit tool in
  `docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md`: replace
  `| **Restart** (\`./ibkr restart\`; fill this row when it happens, with the \`ps\` start time) | | | | | |` with
  `| **Restart** (\`./ibkr restart\`; fill this row when it happens, with the \`ps\` start time) | not needed | - | Part 6 changed no file under src/, scripts/, tests/ or config/; the daemons (started 2026-11-06 19:59:14) run the same Python, and \`next dev\` recompiles web changes | 2026-11-07 | none |`.
- [ ] Commit the three docs:
  `git add docs/superpowers/plans/2026-11-05-web-overhaul-HANDOFF.md docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md docs/superpowers/plans/2026-11-07-web-overhaul-7-news-more-how-it-works.md`
  then `git commit -m "docs(plan): web overhaul Part 7 plan, the updated handoff and Part 6's restart row"` (with the
  session's attribution lines). `git log --oneline -2` shows it over `02236ec` (if `main` moved past `02236ec`, stop
  and ask: the patches were cut against it).
- [ ] `df -h .` shows at least 10 GiB free (22 GiB at 95% on 2026-11-07). Below that, stop and ask.
- [ ] Create the worktree, one command per call:
  `git worktree add .claude/worktrees/web-overhaul-7 -b feat/web-overhaul-7 main`;
  `ln -s "/Users/ianlim/Desktop/IBKR Investments/.venv" "/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/web-overhaul-7/.venv"`;
  `ln -s "/Users/ianlim/Desktop/IBKR Investments/web/node_modules" "/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/web-overhaul-7/web/node_modules"`;
  then from the worktree root
  `IBKR_CONFIG_USE_EXAMPLES=1 .venv/bin/python -c "from src.storage.db import init_db; init_db()"`.
  `<W>` = `/Users/ianlim/Desktop/IBKR Investments/.claude/worktrees/web-overhaul-7`.
- [ ] Write the patch helper (`<S>` = this session's scratchpad, absolute):

```bash
mkdir -p <S>/p7 && cat > <S>/p7/plan_block.py <<'PY'
"""Print one fenced block of the web overhaul Part 7 plan, found by its marker comment.

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

- [ ] From `<W>`, extract every block in the hash table and check every hash against it:
  `for b in T1 T2 T3 T4 T5 T6 T7 T8 T9 T10 mock7 capture7; do python3 <S>/p7/plan_block.py docs/superpowers/plans/2026-11-07-web-overhaul-7-news-more-how-it-works.md $b > <S>/p7/$b.out; done; shasum -a 256 <S>/p7/*.out`
  Every line matches the table. Any mismatch: stop.
- [x] Record A0 in the Progress log (commit hash, worktree path, hashes OK) in Task 1's commit.

**Entry checks:**

- [ ] **A1. Starting point.** In `<W>`: `git log --oneline -2` shows the A0 commit over `02236ec`; `git status --short`
  is empty.
- [ ] **A2. Both patches apply, in order** (they touch disjoint files): `git apply --check <S>/p7/T1.out` and
  `git apply --check <S>/p7/T2.out` each print nothing.
- [ ] **A3. Baseline green.** `python -m pytest -q && ruff check . && mypy src`;
  `cd web && npx vitest run && npx tsc --noEmit && npm run lint`. Expected on 2026-11-07: pytest **5767 passed, 1
  skipped**; mypy **361 files**; vitest **1623 in 157 files**. Record the counts.

**Section exit:** two task commits after A0; vitest **1624 in 157 files**; tsc, lint clean; G1, G2, G3, G5 (the
Section A folders: `web/components/shell web/components/home web/components/stock web/features/stock-value`), G7;
`git status --short` clean.

### Task 1: The rail's Search field and the sectors' count

**Files:** Modify `web/components/shell/Rail.tsx` (+ `Rail.test.tsx`), `web/components/home/SectorCard.tsx` (+
`SectorCard.test.tsx`), `web/DESIGN.md` (the Rail paragraph, the Sectors line, a Decision Log entry); this plan
(Progress log).

**What it does (rulings 5, 7, 8):** the Search row no longer shares the current row's pressed-sage fill; the sectors'
count says what it counts. Two existing assertions change ("(1 name)" and "(3)"), and the Rail test gains three
class assertions (jsdom has no layout, so a class is the only thing to pin).

- [x] **Step 1: Check and apply `T1`.** `git status --short` shows five `M` files: `web/DESIGN.md`,
  `web/components/home/SectorCard.test.tsx`, `web/components/home/SectorCard.tsx`, `web/components/shell/Rail.test.tsx`,
  `web/components/shell/Rail.tsx`.
- [x] **Step 2: Red check.** `git stash push -- web/components/shell/Rail.tsx web/components/home/SectorCard.tsx`,
  then `cd web && npx vitest run components/shell/Rail.test.tsx components/home/SectorCard.test.tsx` ends
  `3 failed | 8 passed (11)`, then `git stash pop` (the two sources come back).
- [x] **Step 3: Gate.** `npx vitest run components/shell components/home features/research`: 13 files, 106 passed.
  Full vitest **1623 in 157 files**; tsc, lint clean; G3 exit 0.
- [x] **Step 4: Commit** `feat(web): the rail's Search is an outlined field; a sector's count says "with history"`
  with the Progress log row (and the A0 and Section A entry rows).

<!-- block T1 -->
````diff
diff --git a/web/DESIGN.md b/web/DESIGN.md
index 0c2c509..247531a 100644
--- a/web/DESIGN.md
+++ b/web/DESIGN.md
@@ -453,7 +453,7 @@ the not-draining warning sits above the controls. The same exception as the revi
 state also shows a full-width flag banner on every page, worded for the wheel ("Wheel trading is
 halted"), since credit spreads have their own halt.
 
-**Rail and tab bar**: the 200px white rail opens with the wordmark, then a pressed-sage **Search** row
+**Rail and tab bar**: the 200px white rail opens with the wordmark, then an outlined **Search** field
 (the magnifier, "Search" and a muted "⌘K") that opens the search palette, then the seven destinations
 with an ink-on-sage current row and the lime pending count on Trades (Research's icon is a telescope, so
 the magnifier means search alone); the phone tab bar (64px, white, hairline above)
@@ -1002,7 +1002,7 @@ overhaul Part 6) on the Stock page's frame.
   sits at the right of the name, the facts take the full width under both (each fact whole, so a line breaks
   only between two) and Remove has its own 44px row; from 768px the row is one line, as above.
 - **Sectors by IV rank:** one white card, a row per sector in the API's order: the name bold with "IV rank 42.0
-  (3)" at the right, then "3 names · +1.50% today", then "Best MSFT +2.00% · worst AAPL -1.00%", all in muted ink
+  (3 with history)" at the right, then "3 names · +1.50% today", then "Best MSFT +2.00% · worst AAPL -1.00%", all in muted ink
   apart from the names; no green or red. Loading holds its place; empty and failed are sentences.
 
 - **Top opportunities (2026-11-05):** a strip above the watchlist, headed "Top opportunities", with two tabs on
@@ -1204,6 +1204,10 @@ sibling keys; re-run the check after edits.
 
 ## Decision Log
 
+- 2026-11-07: **Two Part 6 proposals taken** (web overhaul Part 7, Task 1; the operator's answer). The rail's
+  Search row is an outlined field (a control-edge border on white) instead of a pressed-sage row, so the current
+  destination is the only pressed-sage row in the rail; a sector's IV-rank count reads "(7 with history)" instead
+  of a bare "(7)". No new token, colour, font, radius or elevation.
 - 2026-11-07: **da-vinci finish of Research, Universe and search** (web overhaul Part 6, Task 15). Reviewed
   rendered at 320, 390 and 1440 px in both themes. Your watchlist's row was recomposed on a phone (the quote beside
   the name, the facts on the full width, Remove on its own 44px row; at 320px the facts had been squeezed to a
diff --git a/web/components/home/SectorCard.test.tsx b/web/components/home/SectorCard.test.tsx
index d25fc79..0976cef 100644
--- a/web/components/home/SectorCard.test.tsx
+++ b/web/components/home/SectorCard.test.tsx
@@ -48,7 +48,7 @@ describe("SectorCard", () => {
         ivRankCount={1}
       />,
     );
-    expect(screen.getByText("(1 name)")).toBeDefined();
+    expect(screen.getByText("(1 with history)")).toBeDefined();
   });
 
   it("shows the count when more than one name contributed", () => {
@@ -63,7 +63,7 @@ describe("SectorCard", () => {
         ivRankCount={3}
       />,
     );
-    expect(screen.getByText("(3)")).toBeDefined();
+    expect(screen.getByText("(3 with history)")).toBeDefined();
   });
 });
 describe("SectorCard, restyled (web overhaul Part 6)", () => {
diff --git a/web/components/home/SectorCard.tsx b/web/components/home/SectorCard.tsx
index d309f0b..408bbfd 100644
--- a/web/components/home/SectorCard.tsx
+++ b/web/components/home/SectorCard.tsx
@@ -14,7 +14,7 @@ type Props = {
 
 /**
  * One sector as a row of the Sectors card (web overhaul Part 6, restyled in place): the name and its
- * average IV rank with how many names it averages, then the day's move and the count, then the best and
+ * average IV rank with how many names have the history it averages ("(7 with history)"), then the day's move and the count, then the best and
  * worst movers. A move is signed but never green or red, because a sector's move is a price, not money
  * (web/DESIGN.md Colors). Unknown is a hatched n/a, never 0.
  */
@@ -30,7 +30,7 @@ export function SectorCard({ sector, count, changePct, best, worst, avgIvRank, i
           ) : (
             <>
               <span className="tabular font-semibold">{avgIvRank.toFixed(1)}</span>{" "}
-              <span className="tabular text-[0.8125rem] text-muted">{ivRankCount === 1 ? "(1 name)" : `(${ivRankCount})`}</span>
+              <span className="tabular text-[0.8125rem] text-muted">{`(${ivRankCount} with history)`}</span>
             </>
           )}
         </span>
diff --git a/web/components/shell/Rail.test.tsx b/web/components/shell/Rail.test.tsx
index 4134e3b..c4c5da4 100644
--- a/web/components/shell/Rail.test.tsx
+++ b/web/components/shell/Rail.test.tsx
@@ -51,6 +51,9 @@ describe("Rail", () => {
     window.addEventListener(OPEN_SEARCH_EVENT, seen);
     const button = screen.getByRole("button", { name: "Search" });
     expect(button).toHaveAttribute("aria-keyshortcuts", "Meta+K Control+K");
+    // Outlined like a field, never the pressed-sage fill of the current row (web overhaul Part 7).
+    expect(button).toHaveClass("border", "border-control", "bg-surface");
+    expect(button).not.toHaveClass("bg-sunk");
     fireEvent.click(button);
     window.removeEventListener(OPEN_SEARCH_EVENT, seen);
     expect(seen).toHaveBeenCalledTimes(1);
diff --git a/web/components/shell/Rail.tsx b/web/components/shell/Rail.tsx
index 9cb9379..14a3f3b 100644
--- a/web/components/shell/Rail.tsx
+++ b/web/components/shell/Rail.tsx
@@ -29,12 +29,13 @@ export function Rail() {
   return (
     <nav aria-label="Sections" className="hidden w-[200px] shrink-0 flex-col bg-surface px-3 py-[18px] md:flex">
       <div className="px-2.5 pb-4 text-[0.9375rem] font-extrabold">IBKR Income</div>
-      {/* Opens the one palette the root layout mounts; ⌘K does the same from anywhere. */}
+      {/* Opens the one palette the root layout mounts; ⌘K does the same from anywhere. Outlined like a field, so it
+          never looks like the current row, which is the only pressed-sage row in the rail (web overhaul Part 7). */}
       <button
         type="button"
         onClick={openSearch}
         aria-keyshortcuts="Meta+K Control+K"
-        className="mb-3 flex items-center gap-2.5 rounded-[10px] bg-sunk px-2.5 py-2 text-sm text-muted hover:bg-sunk-deep hover:text-content"
+        className="mb-3 flex items-center gap-2.5 rounded-[10px] border border-control bg-surface px-2.5 py-2 text-sm text-muted hover:text-content"
       >
         <Search aria-hidden="true" size={17} strokeWidth={2} />
         <span className="flex-1 text-left">Search</span>
````

### Task 2: The stock page's three minors

**Files:** Modify `web/components/stock/SentimentPanel.tsx` (+ test), `web/components/stock/StatementsTable.tsx` (+
test), `web/features/stock-value/SizeBlock.tsx`, `web/features/stock-value/ValueBlock.test.tsx`; this plan (Progress
log).

**What it does (ruling 9):** a sentiment source with neither a score nor a count says n/a once; sample counts and the
tranche sentence set in tabular figures; the statements' scroll hint stays up to 1024px. One new test case
(`SentimentPanel`), and two existing assertions tightened (`StatementsTable`'s hint class, `ValueBlock`'s tranche
sentence).

- [x] **Step 1: Check and apply `T2`.** `git status --short` shows six `M` files:
  `web/components/stock/SentimentPanel.test.tsx`, `web/components/stock/SentimentPanel.tsx`,
  `web/components/stock/StatementsTable.test.tsx`, `web/components/stock/StatementsTable.tsx`,
  `web/features/stock-value/SizeBlock.tsx`, `web/features/stock-value/ValueBlock.test.tsx`.
- [x] **Step 2: Red check.** `git stash push -- web/components/stock/SentimentPanel.tsx web/components/stock/StatementsTable.tsx web/features/stock-value/SizeBlock.tsx`,
  then `cd web && npx vitest run components/stock/SentimentPanel.test.tsx components/stock/StatementsTable.test.tsx features/stock-value/ValueBlock.test.tsx`
  ends `3 failed | 29 passed (32)`, then `git stash pop`.
- [x] **Step 3: Gate.** `npx vitest run components/stock features/stock-value`: 9 files, 77 passed. Full vitest **1624
  in 157 files**; tsc, lint clean; G1 empty; G2 as listed; G5 over the Section A folders: no line for a non-test file.
- [x] **Step 4: Commit** `fix(web): the stock page says n/a once, sets its counts in tabular figures and keeps the
  scroll hint up to 1024px` with the Progress log row and the Section A exit row.

<!-- block T2 -->
````diff
diff --git a/web/components/stock/SentimentPanel.test.tsx b/web/components/stock/SentimentPanel.test.tsx
index 18dba85..4e8ba4e 100644
--- a/web/components/stock/SentimentPanel.test.tsx
+++ b/web/components/stock/SentimentPanel.test.tsx
@@ -55,6 +55,12 @@ describe("SentimentPanel", () => {
     expect(screen.queryByText("0 samples")).not.toBeInTheDocument();
   });
 
+  it("says n/a once for a source with neither a score nor a count, and sets counts in tabular figures", () => {
+    render(<SentimentPanel data={{ ...full, reddit: null }} />);
+    expect(screen.queryByText("n/a samples")).toBeNull();
+    expect(screen.getByText("42 samples")).toHaveClass("tabular");
+  });
+
   it("signs the day's change but never colours it: tone is not money (web overhaul Part 5)", () => {
     render(<SentimentPanel data={{ ...full, delta_1d: -2.0 }} />);
     const delta = screen.getByText("-2.0 1d");
diff --git a/web/components/stock/SentimentPanel.tsx b/web/components/stock/SentimentPanel.tsx
index b7bde39..2f22c1f 100644
--- a/web/components/stock/SentimentPanel.tsx
+++ b/web/components/stock/SentimentPanel.tsx
@@ -31,9 +31,12 @@ function Score({
         <span className={score === null ? "tabular hatch px-1 text-unknown" : "tabular font-semibold"}>
           {score === null ? UNKNOWN : score.toFixed(1)}
         </span>
-        <span className={`ml-2 text-[0.8125rem] ${count === null ? "text-unknown" : "text-muted"}`}>
-          {count === null ? `${UNKNOWN} samples` : `${count} samples`}
-        </span>
+        {/* A source with neither a score nor a count says n/a once, not "n/a" then "n/a samples". */}
+        {(score !== null || count !== null) && (
+          <span className={`tabular ml-2 text-[0.8125rem] ${count === null ? "text-unknown" : "text-muted"}`}>
+            {count === null ? `${UNKNOWN} samples` : `${count} samples`}
+          </span>
+        )}
       </dd>
     </div>
   );
diff --git a/web/components/stock/StatementsTable.test.tsx b/web/components/stock/StatementsTable.test.tsx
index 2f6f827..758e627 100644
--- a/web/components/stock/StatementsTable.test.tsx
+++ b/web/components/stock/StatementsTable.test.tsx
@@ -45,7 +45,9 @@ describe("StatementsTable", () => {
     // Found by looking (Task 11): at 390 px the third year sat off the card's edge with no hint.
     const { unmount } = render(<StatementsTable financials={financials} />);
     const hint = screen.getByText("Scroll sideways to see every column.");
-    expect(hint).toHaveClass("md:hidden");
+    // Below 1024px the column is too narrow for a long quarterly table, so the hint stays up to lg (web overhaul Part 7).
+    expect(hint).toHaveClass("lg:hidden");
+    expect(hint).not.toHaveClass("md:hidden");
     unmount();
     render(<StatementsTable financials={{ annual: [], quarterly: [] }} />);
     expect(screen.queryByText("Scroll sideways to see every column.")).toBeNull();
diff --git a/web/components/stock/StatementsTable.tsx b/web/components/stock/StatementsTable.tsx
index d6a4965..3faa69f 100644
--- a/web/components/stock/StatementsTable.tsx
+++ b/web/components/stock/StatementsTable.tsx
@@ -82,7 +82,7 @@ export function StatementsTable({ financials }: { financials: Financials }) {
   return (
     <div className="space-y-5">
       {(financials.annual.length > 0 || financials.quarterly.length > 0) && (
-        <p className="text-xs text-muted md:hidden">Scroll sideways to see every column.</p>
+        <p className="text-xs text-muted lg:hidden">Scroll sideways to see every column.</p>
       )}
       {financials.annual.length > 0 && (
         <section>
diff --git a/web/features/stock-value/SizeBlock.tsx b/web/features/stock-value/SizeBlock.tsx
index 14b5408..c2b5d51 100644
--- a/web/features/stock-value/SizeBlock.tsx
+++ b/web/features/stock-value/SizeBlock.tsx
@@ -36,7 +36,7 @@ export function SizeBlock({ file, plan }: { file: ValueFile; plan: ValuePlan | n
       )}
       {plan &&
         (tranches ? (
-          <p className="mt-1 text-sm">{tranches}</p>
+          <p className="tabular mt-1 text-sm">{tranches}</p>
         ) : (
           <p className="mt-1 text-sm">
             Tranches bought <Hatched />
diff --git a/web/features/stock-value/ValueBlock.test.tsx b/web/features/stock-value/ValueBlock.test.tsx
index e2df007..59de6f1 100644
--- a/web/features/stock-value/ValueBlock.test.tsx
+++ b/web/features/stock-value/ValueBlock.test.tsx
@@ -166,7 +166,8 @@ describe("ValueBlock", () => {
     show();
     const size = await screen.findByRole("region", { name: "How much, and when?" });
     expect(within(size).getByText("At this margin of safety a buy aims at 3% of the book's ceiling, in 3 tranches.")).toBeInTheDocument();
-    expect(within(size).getByText(/^1 of 3 tranches bought \(the last on Oct 20, 2026\)\. Tranche 2 waits for a higher low/)).toBeInTheDocument();
+    const tranche = within(size).getByText(/^1 of 3 tranches bought \(the last on Oct 20, 2026\)\. Tranche 2 waits for a higher low/);
+    expect(tranche).toHaveClass("tabular");
     expect(within(size).queryByText(/Size if bought/)).toBeNull(); // the No list carries no size line
   });
 
````

## Section B: News (Tasks 3-5) · model: sonnet (effort high)

**Reads:** this section; `web/components/news/NewsFeed.tsx`, `NewsTicker.tsx`, `BriefRequest.tsx` (each in full, all
under 60 lines); `web/components/news/NewsCard.tsx` (lines 1-20 and 45-60); `web/features/research/ResearchPage.tsx`
(lines 20-40, the frame this section copies); `web/components/ui/SegmentedControl.tsx` (lines 1-50).

**Spec for da-vinci (Tasks 3-5; give it this, so it has little to decide):** the News Surfaces paragraph in the T5
patch is the spec (rulings 13-19). The frame is Research's: `mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4`, the
24px/800 title, a muted 14px line, actions at the right. Section titles 17px/700 with a muted 13px line under them.
Cards are `components/ui/Card` (white, 18px radius, no border, no shadow); rows inside a card are
`border-t border-border py-2 first:border-t-0`. The chips are `SegmentedControl` with `appearance="chips"`; the field
is `components/ui/field.ts`'s `FIELD` with a visible `FIELD_LABEL` label. Links to other pages are the secondary
pill (`bg-sunk`, never lime); an external link is underlined with an `sr-only` "(opens in a new tab)" and is a 44px
row on a phone (`flex min-h-11 items-center md:inline md:min-h-0`). No lime anywhere on these pages: the brief
request is secondary. No green or red: the verdict is ink. da-vinci reads the patches and changes nothing; record
"no change" in each row, or record any change as a ruling with its cost.

**Entry checks:**

- [x] **B1. Section A landed.** In `<W>`: `git log --oneline main..HEAD` shows the two Section A commits; vitest
  **1624 in 157 files**; tsc and lint clean; G1 empty; G2 as listed; G7 the one layout line.
- [x] **B2. Every patch of the section applies on the tree as it is** (they touch disjoint files): `git apply --check
  <S>/p7/T3.out`, `T4.out`, `T5.out`: each prints nothing.
- [x] **B3. Starting shape.** `ls web/features/news` fails (no such directory);
  `grep -rln "submitCommand" web/components/news` prints exactly `web/components/news/BriefRequest.tsx`;
  `grep -c "it(" web/components/news/NewsFeed.test.tsx web/components/news/NewsTicker.test.tsx web/components/news/NewsCard.test.tsx`
  prints `3`, `3` and `3`.

**Section exit:** three task commits; vitest **1644 in 160 files**; tsc, lint clean; G1, G2 (both greps), G3, G4
(the route table shows `○ /news` and `ƒ /news/[symbol]`, 19 rows), G5 over the Section A folders plus
`web/components/news web/features/news web/app/news`, G6, G7; `git status --short` clean.

### Task 3: The News page

**Files:** Create `web/features/news/NewsPage.tsx` (+ `NewsPage.test.tsx`); modify `web/app/news/page.tsx` (it mounts
the page), `web/components/news/NewsFeed.tsx` (+ test); this plan (Progress log).

**What it does (rulings 13, 14):** News gets the frame, a title and a line; the Market card leads full width; the
feed ("Latest") and the calendar sit in two single-track columns from 1024px. The feed's chips are the shared
`SegmentedControl`; its symbol field has a visible label (the `aria-label` goes, WCAG 2.5.3); loading, a failed
read and no match are sentences. `NewsFeed` no longer mounts the Market card, the calendar or Refresh (the page
does). Its three existing tests pass unchanged; four are added.

- [x] **Step 1: Check and apply `T3`.** `git status --short` shows ` M web/app/news/page.tsx`,
  ` M web/components/news/NewsFeed.test.tsx`, ` M web/components/news/NewsFeed.tsx` and `?? web/features/`.
- [x] **Step 2: Red check.** `git stash push -- web/components/news/NewsFeed.tsx`, then
  `cd web && npx vitest run components/news/NewsFeed.test.tsx` ends `4 failed | 3 passed (7)`, then `git stash pop`.
  (`NewsPage` is a new module: its red is the module missing.)
- [x] **Step 3: Gate.** `npx vitest run components/news features/news app/titles.test.ts`: all pass. Full vitest **1631
  in 158 files**; tsc, lint clean; G5 over `web/components/news web/features/news web/app/news`: no line for a
  non-test file.
- [x] **Step 4: Commit** `feat(web): News on the payslip: the frame, the Market card first, the feed with labelled
  controls` with the Progress log row (and the Section B entry row).

<!-- block T3 -->
````diff
diff --git a/web/app/news/page.tsx b/web/app/news/page.tsx
index a5b6a6e..1d5dcc9 100644
--- a/web/app/news/page.tsx
+++ b/web/app/news/page.tsx
@@ -1,8 +1,8 @@
 import type { Metadata } from "next";
-import { NewsFeed } from "@/components/news/NewsFeed";
+import { NewsPage } from "@/features/news/NewsPage";
 
 export const metadata: Metadata = { title: "News" };
 
-export default function NewsPage() {
-  return <NewsFeed />;
+export default function Page() {
+  return <NewsPage />;
 }
diff --git a/web/components/news/NewsFeed.test.tsx b/web/components/news/NewsFeed.test.tsx
index 607e138..62eb92d 100644
--- a/web/components/news/NewsFeed.test.tsx
+++ b/web/components/news/NewsFeed.test.tsx
@@ -1,4 +1,5 @@
-import { screen, fireEvent, waitFor } from "@testing-library/react";
+import { render, screen, fireEvent, waitFor } from "@testing-library/react";
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
 import { describe, expect, it } from "vitest";
 import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
 import { NewsFeed } from "./NewsFeed";
@@ -43,4 +44,38 @@ describe("NewsFeed", () => {
     });
     expect(await screen.findByText(/news service has not written anything yet/i)).toBeInTheDocument();
   });
+
+  it("is a titled section whose chips are 'Show' and whose symbol field has a visible label", async () => {
+    renderWithQuery(<NewsFeed />, { "/news/feed?limit=30": { as_of: ISO, available: true, posts: [] } });
+    expect(screen.getByRole("heading", { level: 2, name: "Latest" })).toBeInTheDocument();
+    expect(screen.getByRole("group", { name: "Show" })).toBeInTheDocument();
+    expect(screen.getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
+    const box = screen.getByLabelText("Filter by symbol");
+    expect(box).not.toHaveAttribute("aria-label");
+    expect(box).toHaveClass("min-h-11", "text-base");
+  });
+
+  it("says it is loading instead of showing an empty feed", () => {
+    apiFetchMock.mockImplementation(() => new Promise(() => {}));
+    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+    render(<QueryClientProvider client={qc}><NewsFeed /></QueryClientProvider>);
+    expect(screen.getByRole("status", { name: "Loading the news" })).toBeInTheDocument();
+    expect(screen.queryByText(/No posts/)).toBeNull();
+  });
+
+  it("says a failed read in words, not as an empty feed", async () => {
+    renderWithQuery(<NewsFeed />, {});
+    expect(await screen.findByText("The news feed could not be loaded. It is asked for again every minute.")).toBeInTheDocument();
+    expect(screen.queryByText(/No posts/)).toBeNull();
+  });
+
+  it("names the symbol when a filter matches nothing", async () => {
+    renderWithQuery(<NewsFeed />, {
+      "/news/feed?limit=30": { as_of: ISO, available: true, posts: [post(1, "macro_print", "CPI")] },
+      "/news/feed?symbol=ZZZ&limit=30": { as_of: ISO, available: true, posts: [] },
+    });
+    expect(await screen.findByText("CPI")).toBeInTheDocument();
+    fireEvent.change(screen.getByLabelText("Filter by symbol"), { target: { value: "zzz" } });
+    expect(await screen.findByText("No posts match ZZZ in this group.")).toBeInTheDocument();
+  });
 });
diff --git a/web/components/news/NewsFeed.tsx b/web/components/news/NewsFeed.tsx
index cca7b77..0f91583 100644
--- a/web/components/news/NewsFeed.tsx
+++ b/web/components/news/NewsFeed.tsx
@@ -1,22 +1,29 @@
 "use client";
 
-import { RefreshButton } from "@/components/shell/RefreshButton";
-import { useEffect, useState } from "react";
+import { useEffect, useId, useState } from "react";
 import { useQuery } from "@tanstack/react-query";
 import { apiFetch } from "@/lib/api";
-import { MarketCard } from "@/features/market/MarketCard";
-import { CalendarColumn } from "./CalendarColumn";
+import { SegmentedControl } from "@/components/ui/SegmentedControl";
+import { FIELD, FIELD_LABEL } from "@/components/ui/field";
 import { NewsCard } from "./NewsCard";
 import type { NewsFeedResponse } from "./types";
 
-const GROUPS: { key: string | null; label: string }[] = [
-  { key: null, label: "All" }, { key: "macro", label: "Macro" }, { key: "market", label: "Market" },
-  { key: "tickers", label: "Tickers" }, { key: "earnings", label: "Earnings" }, { key: "briefs", label: "Briefs" },
+type Group = "all" | "macro" | "market" | "tickers" | "earnings" | "briefs";
+
+const GROUPS: { value: Group; label: string }[] = [
+  { value: "all", label: "All" }, { value: "macro", label: "Macro" }, { value: "market", label: "Market" },
+  { value: "tickers", label: "Tickers" }, { value: "earnings", label: "Earnings" }, { value: "briefs", label: "Briefs" },
 ];
 
+/**
+ * The news feed (restyled in place, web overhaul Part 7): a titled section with the group chips and a
+ * labelled symbol field, then the posts newest first. Loading, failed, not yet written and no match
+ * are each a sentence, so an empty list never reads as "no news".
+ */
 export function NewsFeed() {
-  const [group, setGroup] = useState<string | null>(null);
+  const [group, setGroup] = useState<Group>("all");
   const [symbol, setSymbol] = useState("");
+  const fieldId = useId();
   // The query follows the box 300ms after the last keystroke, not on every one.
   const [filter, setFilter] = useState("");
   useEffect(() => {
@@ -24,7 +31,7 @@ export function NewsFeed() {
     return () => clearTimeout(id);
   }, [symbol]);
   const params = new URLSearchParams();
-  if (group) params.set("group", group);
+  if (group !== "all") params.set("group", group);
   if (filter) params.set("symbol", filter);
   params.set("limit", "30");
   const path = `/news/feed?${params.toString()}`;
@@ -32,26 +39,40 @@ export function NewsFeed() {
                        placeholderData: (prev) => prev, refetchInterval: 60_000 });
 
   return (
-    <div className="grid gap-6 lg:grid-cols-[1fr_320px]" data-testid="news-feed">
-      <div className="space-y-4">
-        <MarketCard variant="news" />
-        <div className="flex flex-wrap items-center gap-2">
-          {GROUPS.map((g) => (
-            <button key={g.label} type="button" onClick={() => setGroup(g.key)} aria-pressed={group === g.key}
-              className={`rounded-sm px-3 py-1 text-sm ${group === g.key ? "bg-elevated text-content" : "text-muted hover:text-content"} focus-visible:ring-focus`}>
-              {g.label}
-            </button>
-          ))}
-          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="Symbol"
-            className="ml-auto w-28 rounded-sm bg-background px-2 py-1 font-mono text-sm text-content" aria-label="Filter by symbol" />
-          <RefreshButton label="Refresh the news" className="-my-2" />
+    <section aria-labelledby="feed-title" data-testid="news-feed">
+      <h2 id="feed-title" className="text-[1.0625rem] font-bold">
+        Latest
+      </h2>
+      <p className="mt-1 text-[0.8125rem] text-muted">The news service&apos;s posts, newest first, 30 at most.</p>
+      <div className="mt-3 flex flex-wrap items-end justify-between gap-x-4 gap-y-3">
+        <SegmentedControl label="Show" appearance="chips" options={GROUPS} value={group} onChange={setGroup} />
+        <div className="flex flex-col gap-1">
+          <label htmlFor={fieldId} className={FIELD_LABEL}>
+            Filter by symbol
+          </label>
+          <input
+            id={fieldId}
+            value={symbol}
+            onChange={(e) => setSymbol(e.target.value)}
+            placeholder="Ticker"
+            autoCapitalize="characters"
+            autoComplete="off"
+            spellCheck={false}
+            className={`${FIELD} w-36 uppercase`}
+          />
         </div>
-        {q.isError && <p className="text-sm text-muted">Could not load the news feed.</p>}
-        {q.data && !q.data.available && <p className="text-sm text-muted">The news service has not written anything yet.</p>}
-        {q.data?.available && q.data.posts.length === 0 && <p className="text-sm text-muted">No posts match.</p>}
+      </div>
+      <div className="mt-4 grid grid-cols-1 gap-3">
+        {q.isPending && (
+          <div role="status" aria-busy="true" aria-label="Loading the news" className="h-28 rounded-[18px] bg-surface" />
+        )}
+        {q.isError && !q.data && <p className="text-sm">The news feed could not be loaded. It is asked for again every minute.</p>}
+        {q.data && !q.data.available && <p className="text-sm">The news service has not written anything yet.</p>}
+        {q.data?.available && q.data.posts.length === 0 && (
+          <p className="text-sm">{filter ? `No posts match ${filter} in this group.` : "No posts in this group yet."}</p>
+        )}
         {q.data?.posts.map((p) => <NewsCard key={p.id} post={p} />)}
       </div>
-      <CalendarColumn />
-    </div>
+    </section>
   );
 }
diff --git a/web/features/news/NewsPage.test.tsx b/web/features/news/NewsPage.test.tsx
new file mode 100644
index 0000000..a54dc77
--- /dev/null
+++ b/web/features/news/NewsPage.test.tsx
@@ -0,0 +1,37 @@
+import { screen } from "@testing-library/react";
+import { describe, expect, it } from "vitest";
+import { renderWithQuery } from "@/lib/test-query";
+import { NewsPage } from "./NewsPage";
+
+const ISO = "2026-11-07T01:00:00Z";
+// /claude/context is left unmocked on purpose: the Market card then shows its failure sentence, which is
+// enough to place it in the page's order without a full market picture fixture.
+const served = {
+  "/news/feed": { as_of: ISO, available: true, posts: [] },
+  "/news/calendar": { as_of: ISO, available: true, econ: [], earnings: [] },
+};
+
+describe("NewsPage", () => {
+  it("is titled News, with a line saying what the page holds and that nothing here trades", () => {
+    renderWithQuery(<NewsPage />, served);
+    expect(screen.getByRole("heading", { level: 1, name: "News" })).toBeInTheDocument();
+    expect(
+      screen.getByText("What moved, what is scheduled this week, and what the news service made of it. Nothing here trades."),
+    ).toBeInTheDocument();
+    expect(screen.getByRole("button", { name: "Refresh the news" })).toBeInTheDocument();
+  });
+
+  it("puts the Market card first, then the feed, which is the phone's order", async () => {
+    renderWithQuery(<NewsPage />, served);
+    const market = await screen.findByText(/The market picture could not be loaded/);
+    const feed = screen.getByRole("heading", { level: 2, name: "Latest" });
+    expect(market.compareDocumentPosition(feed) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
+  });
+
+  it("uses the frame's single-track columns, so a wide card never widens the page", () => {
+    const { container } = renderWithQuery(<NewsPage />, served);
+    const grid = container.querySelector(".lg\\:grid-cols-\\[minmax\\(0\\,1fr\\)_340px\\]");
+    expect(grid).not.toBeNull();
+    for (const col of Array.from(grid!.children)) expect(col).toHaveClass("grid", "min-w-0", "grid-cols-1");
+  });
+});
diff --git a/web/features/news/NewsPage.tsx b/web/features/news/NewsPage.tsx
new file mode 100644
index 0000000..233f88c
--- /dev/null
+++ b/web/features/news/NewsPage.tsx
@@ -0,0 +1,39 @@
+"use client";
+
+import { RefreshButton } from "@/components/shell/RefreshButton";
+import { CalendarColumn } from "@/components/news/CalendarColumn";
+import { NewsFeed } from "@/components/news/NewsFeed";
+import { MarketCard } from "@/features/market/MarketCard";
+
+/**
+ * News (web overhaul Part 7): the Stock and Research frame. The title with Refresh at the right, the
+ * Market card full width, then two columns from 1024px: the feed on the left and the week's calendar
+ * in a 340px column on the right. The DOM order is the phone order. It reads only: the news service
+ * writes every post, and nothing here trades.
+ */
+export function NewsPage() {
+  return (
+    <div className="mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4" data-testid="news-page">
+      <header className="mt-1 flex flex-wrap items-start justify-between gap-3">
+        <div className="min-w-0">
+          <h1 className="text-2xl font-extrabold tracking-[-0.015em]">News</h1>
+          <p className="mt-1 text-sm text-muted">What moved, what is scheduled this week, and what the news service made of it. Nothing here trades.</p>
+        </div>
+        <RefreshButton label="Refresh the news" />
+      </header>
+
+      <div className="mt-6">
+        <MarketCard variant="news" />
+      </div>
+
+      <div className="mt-6 grid items-start gap-x-6 gap-y-6 lg:grid-cols-[minmax(0,1fr)_340px]">
+        <div className="grid min-w-0 grid-cols-1">
+          <NewsFeed />
+        </div>
+        <div className="grid min-w-0 grid-cols-1">
+          <CalendarColumn />
+        </div>
+      </div>
+    </div>
+  );
+}
````

### Task 4: The calendar and the news card

**Files:** Modify `web/components/news/CalendarColumn.tsx` (+ `CalendarColumn.test.tsx`, CREATE),
`web/components/news/NewsCard.tsx` (+ test), `web/components/news/VerdictPill.tsx`; this plan (Progress log).

**What it does (rulings 15-17):** the calendar is one card, "This week", that says when it is loading, failed, not
yet written or empty instead of vanishing; a missing forecast is hatched; an earnings ticker links to its news page
(44px on a phone) with a neutral "Held" word. A post is a `Card`; "Critical" is a flag word; its source links say
they open a new tab; the explanation sits in a pressed-sage block labelled "The news model's reading"; a digest says
once that its readings are the news model's; the verdict pill is ink with its icon (never green or red) and says
"medium confidence". One existing assertion changes (the BLS link's name gains "(opens in a new tab)").

- [x] **Step 1: Check and apply `T4`.** `git status --short` shows four `M` files (`CalendarColumn.tsx`,
  `NewsCard.test.tsx`, `NewsCard.tsx`, `VerdictPill.tsx` under `web/components/news/`) and
  `?? web/components/news/CalendarColumn.test.tsx`.
- [x] **Step 2: Red check.** `git stash push -- web/components/news/CalendarColumn.tsx web/components/news/NewsCard.tsx web/components/news/VerdictPill.tsx`,
  then `cd web && npx vitest run components/news/CalendarColumn.test.tsx components/news/NewsCard.test.tsx` ends
  `9 failed | 2 passed (11)`, then `git stash pop`.
- [x] **Step 3: Gate.** `npx vitest run components/news features/news`: all pass. Full vitest **1639 in 159 files**;
  tsc, lint clean; G5 as in Task 3.
- [x] **Step 4: Commit** `feat(web): the week's calendar as one card that says when it is empty, and the news
  verdict in ink` with the Progress log row.

<!-- block T4 -->
````diff
diff --git a/web/components/news/CalendarColumn.test.tsx b/web/components/news/CalendarColumn.test.tsx
new file mode 100644
index 0000000..f4b15c5
--- /dev/null
+++ b/web/components/news/CalendarColumn.test.tsx
@@ -0,0 +1,51 @@
+import { screen } from "@testing-library/react";
+import { describe, expect, it } from "vitest";
+import { renderWithQuery } from "@/lib/test-query";
+import { CalendarColumn } from "./CalendarColumn";
+
+const ISO = "2026-11-07T01:00:00Z";
+const econ = (title: string, actual: string | null, forecast: string | null) => ({
+  title, scheduled_at: "2026-11-10T13:30:00Z", impact: "high", forecast, previous: null, actual, surprise_dir: null,
+});
+const earn = (symbol: string, held: boolean) => ({
+  symbol, report_date: "2026-11-12", timing: "amc", eps_est: null, eps_actual: null, status: "scheduled", held,
+});
+
+describe("CalendarColumn", () => {
+  it("is one card titled This week, with the releases and the earnings as rows", async () => {
+    renderWithQuery(<CalendarColumn />, {
+      "/news/calendar?days=7": { as_of: ISO, available: true, econ: [econ("CPI m/m", "0.4%", "0.3%")], earnings: [earn("NVDA", true)] },
+    });
+    expect(await screen.findByText("CPI m/m")).toBeInTheDocument();
+    expect(screen.getByRole("heading", { level: 2, name: "This week" })).toBeInTheDocument();
+    expect(screen.getByRole("heading", { level: 3, name: "Economic releases" })).toBeInTheDocument();
+    expect(screen.getByRole("heading", { level: 3, name: "Earnings" })).toBeInTheDocument();
+    expect(screen.getByText("0.4%").closest("li")).toHaveTextContent("0.4% vs 0.3% forecast");
+    expect(screen.getByRole("link", { name: "NVDA" })).toHaveAttribute("href", "/news/NVDA");
+    expect(screen.getByText("Held")).toHaveAttribute("data-tone", "neutral");
+    expect(screen.getByRole("link", { name: "NVDA" }).closest("li")).toHaveTextContent("AMC");
+  });
+
+  it("hatches a missing forecast instead of printing nothing", async () => {
+    renderWithQuery(<CalendarColumn />, {
+      "/news/calendar?days=7": { as_of: ISO, available: true, econ: [econ("Retail sales", "1.1%", null)], earnings: [] },
+    });
+    const row = (await screen.findByText("Retail sales")).closest("li")!;
+    expect(row.querySelector(".hatch")).toHaveTextContent("n/a");
+  });
+
+  it("says an empty week in words instead of vanishing", async () => {
+    renderWithQuery(<CalendarColumn />, { "/news/calendar?days=7": { as_of: ISO, available: true, econ: [], earnings: [] } });
+    expect(await screen.findAllByText("None in the next 7 days.")).toHaveLength(2);
+  });
+
+  it("says when the calendar has not been written, or could not be read", async () => {
+    const { unmount } = renderWithQuery(<CalendarColumn />, {
+      "/news/calendar?days=7": { as_of: ISO, available: false, econ: [], earnings: [] },
+    });
+    expect(await screen.findByText("The news service has not written the calendar yet.")).toBeInTheDocument();
+    unmount();
+    renderWithQuery(<CalendarColumn />, {});
+    expect(await screen.findByText("The calendar could not be loaded.")).toBeInTheDocument();
+  });
+});
diff --git a/web/components/news/CalendarColumn.tsx b/web/components/news/CalendarColumn.tsx
index c595343..9f00190 100644
--- a/web/components/news/CalendarColumn.tsx
+++ b/web/components/news/CalendarColumn.tsx
@@ -1,40 +1,84 @@
 "use client";
 
+import Link from "next/link";
 import { useQuery } from "@tanstack/react-query";
 import { apiFetch } from "@/lib/api";
+import { Card } from "@/components/ui/Card";
+import { StatusWord } from "@/components/ui/StatusWord";
+import { Hatched } from "@/features/stock-value/parts";
 import { dayLabel, whenLabel } from "./format";
 import type { NewsCalendarResponse } from "./types";
 
+const SUBHEAD = "mt-4 text-xs font-semibold tracking-[0.04em] text-muted";
+const ROW = "flex items-baseline justify-between gap-3 border-t border-border py-2 text-sm first:border-t-0";
+
+/**
+ * The week's calendar (restyled in place, web overhaul Part 7): one white card, "This week", with the
+ * economic releases and the earnings as quiet rows. Loading, failed and not yet written are each a
+ * sentence, and an empty list says so, so the card never vanishes and never reads as "nothing due".
+ */
 export function CalendarColumn() {
   const q = useQuery({ queryKey: ["news", "calendar"], queryFn: () => apiFetch<NewsCalendarResponse>("/news/calendar?days=7"),
                        placeholderData: (prev) => prev, refetchInterval: 5 * 60_000 });
-  if (!q.data?.available) return null;
   return (
-    <aside className="space-y-4" data-testid="news-calendar">
-      <section>
-        <h2 className="pb-2 text-sm font-medium text-content">Economic calendar</h2>
-        <ul className="space-y-1 text-xs">
-          {q.data.econ.map((e) => (
-            <li key={`${e.scheduled_at}-${e.title}`} className="flex justify-between gap-2">
-              <span>{e.title}</span>
-              <span className="font-mono text-muted tabular">
-                {e.actual ? `${e.actual} vs ${e.forecast ?? "n/a"}` : whenLabel(e.scheduled_at)}
-              </span>
-            </li>
-          ))}
-        </ul>
-      </section>
-      <section>
-        <h2 className="pb-2 text-sm font-medium text-content">Earnings</h2>
-        <ul className="space-y-1 text-xs">
-          {q.data.earnings.map((e) => (
-            <li key={`${e.symbol}-${e.report_date}`} className="flex justify-between gap-2">
-              <a href={`/news/${e.symbol}`} className="font-mono">{e.symbol}{e.held ? " · held" : ""}</a>
-              <span className="text-muted">{dayLabel(e.report_date)} {e.timing.toUpperCase()}</span>
-            </li>
-          ))}
-        </ul>
-      </section>
-    </aside>
+    <Card aria-labelledby="calendar-title" data-testid="news-calendar">
+      <h2 id="calendar-title" className="text-[1.0625rem] font-bold">
+        This week
+      </h2>
+      <p className="mt-1 text-[0.8125rem] text-muted">The next 7 days, in Singapore time with New York time beside it.</p>
+      {q.isPending && <div role="status" aria-busy="true" aria-label="Loading the calendar" className="mt-3 h-20 rounded-xl bg-sunk" />}
+      {q.isError && !q.data && <p className="mt-3 text-sm">The calendar could not be loaded.</p>}
+      {q.data && !q.data.available && <p className="mt-3 text-sm">The news service has not written the calendar yet.</p>}
+      {q.data?.available && (
+        <>
+          <h3 className={SUBHEAD}>Economic releases</h3>
+          {q.data.econ.length === 0 ? (
+            <p className="mt-1 text-sm text-muted">None in the next 7 days.</p>
+          ) : (
+            <ul className="mt-1">
+              {q.data.econ.map((e) => (
+                <li key={`${e.scheduled_at}-${e.title}`} className={ROW}>
+                  <span className="min-w-0">{e.title}</span>
+                  {e.actual ? (
+                    <span className="shrink-0 text-right text-[0.8125rem]">
+                      <span className="tabular font-semibold">{e.actual}</span>
+                      <span className="text-muted"> vs </span>
+                      {e.forecast ? <span className="tabular">{e.forecast}</span> : <Hatched />}
+                      <span className="text-muted"> forecast</span>
+                    </span>
+                  ) : (
+                    <span className="tabular shrink-0 text-right text-[0.8125rem] text-muted">{whenLabel(e.scheduled_at)}</span>
+                  )}
+                </li>
+              ))}
+            </ul>
+          )}
+          <h3 className={SUBHEAD}>Earnings</h3>
+          {q.data.earnings.length === 0 ? (
+            <p className="mt-1 text-sm text-muted">None in the next 7 days.</p>
+          ) : (
+            <ul className="mt-1">
+              {q.data.earnings.map((e) => (
+                <li key={`${e.symbol}-${e.report_date}`} className={ROW}>
+                  <span className="flex min-w-0 items-center gap-2">
+                    <Link
+                      href={`/news/${encodeURIComponent(e.symbol)}`}
+                      className="flex min-h-11 items-center font-semibold underline-offset-2 hover:underline md:min-h-0"
+                    >
+                      {e.symbol}
+                    </Link>
+                    {e.held && <StatusWord>Held</StatusWord>}
+                  </span>
+                  <span className="tabular shrink-0 text-right text-[0.8125rem] text-muted">
+                    {dayLabel(e.report_date)}
+                    {e.timing ? ` · ${e.timing.toUpperCase()}` : ""}
+                  </span>
+                </li>
+              ))}
+            </ul>
+          )}
+        </>
+      )}
+    </Card>
   );
 }
diff --git a/web/components/news/NewsCard.test.tsx b/web/components/news/NewsCard.test.tsx
index 5792891..a6ad67c 100644
--- a/web/components/news/NewsCard.test.tsx
+++ b/web/components/news/NewsCard.test.tsx
@@ -23,7 +23,7 @@ describe("NewsCard", () => {
     expect(screen.getByTestId("grid-stocks")).toHaveTextContent("ES=F -1.20%");
     expect(screen.getByTestId("verdict")).toHaveTextContent("Further downside likely");
     expect(screen.getByText(/NVDA 165P 3.1% OTM/)).toBeInTheDocument();
-    expect(screen.getByRole("link", { name: "BLS" })).toHaveAttribute("href", "https://www.bls.gov/x");
+    expect(screen.getByRole("link", { name: "BLS (opens in a new tab)" })).toHaveAttribute("href", "https://www.bls.gov/x");
   });
 
   it("renders two identical update lines without a duplicate-key warning", () => {
@@ -35,6 +35,40 @@ describe("NewsCard", () => {
     err.mockRestore();
   });
 
+  it("labels the explanation as the news model's reading, never as Claude's alone", () => {
+    render(<NewsCard post={POST} />);
+    const reading = screen.getByTestId("news-reading");
+    expect(reading).toHaveTextContent("The news model's reading");
+    expect(reading).toHaveTextContent("Claude, or the local model when Claude cannot be reached; it trades nothing");
+    expect(reading).toHaveTextContent("Inflation re-accelerating.");
+  });
+
+  it("draws the verdict in ink with its icon and words: a forecast is not money, so never green or red", () => {
+    for (const verdict of ["further_downside_likely", "further_upside_likely"] as const) {
+      const { unmount } = render(
+        <NewsCard post={{ ...POST, payload: { ...POST.payload, explanation: { ...POST.payload.explanation!, verdict } } }} />,
+      );
+      const pill = screen.getByTestId("verdict");
+      expect(pill).toHaveClass("text-content");
+      expect(pill.className).not.toMatch(/text-(gain|loss)/);
+      expect(pill).toHaveTextContent(verdict === "further_upside_likely" ? "▲" : "▼");
+      expect(pill).toHaveTextContent("medium confidence");
+      unmount();
+    }
+  });
+
+  it("says Critical as a flag word, and names a source link as opening a new tab", () => {
+    render(<NewsCard post={POST} />);
+    expect(screen.getByText("Critical")).toHaveAttribute("data-tone", "flag");
+    expect(screen.getByRole("link", { name: "BLS (opens in a new tab)" })).toHaveAttribute("target", "_blank");
+  });
+
+  it("says once that a digest's readings are the news model's", () => {
+    const sections = [{ title: "Movers", items: [{ text: "NVDA -4%", read: "Profit taking.", verdict: "priced_in" as const, links: [] }] }];
+    render(<NewsCard post={{ ...POST, payload: { ...POST.payload, explanation: null, sections } }} />);
+    expect(screen.getByText("The readings and verdicts below are the news model's.")).toBeInTheDocument();
+  });
+
   it("never renders an em dash in UI copy", () => {
     const { container } = render(<NewsCard post={POST} />);
     expect(container.textContent).not.toContain("—");
diff --git a/web/components/news/NewsCard.tsx b/web/components/news/NewsCard.tsx
index 0d41c34..4a2b641 100644
--- a/web/components/news/NewsCard.tsx
+++ b/web/components/news/NewsCard.tsx
@@ -1,66 +1,84 @@
+import { Card } from "@/components/ui/Card";
+import { StatusWord } from "@/components/ui/StatusWord";
 import type { NewsPost } from "./types";
 import { whenLabel } from "./format";
 import { VerdictPill } from "./VerdictPill";
 
+/**
+ * One news post (restyled in place, web overhaul Part 7). The content is the news service's own: the
+ * title, the headline line and its sources, the facts, the reaction grid, the sections and the updates.
+ * The explanation is written by the news model (Claude, or the local model when Claude cannot be
+ * reached), so it sits in a labelled block and is named by that model, not as Claude's.
+ */
 export function NewsCard({ post, chartUri }: { post: NewsPost; chartUri?: string | null }) {
   const p = post.payload;
   const e = p.explanation;
   return (
-    <article className="space-y-3 rounded-md bg-surface p-4" data-testid={`news-card-${post.id}`}>
-      <header className="flex flex-wrap items-baseline gap-2">
+    <Card as="article" className="space-y-3" data-testid={`news-card-${post.id}`}>
+      <header className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
         <span aria-hidden="true">{p.emoji}</span>
-        <h3 className="text-sm font-medium text-content">{p.title}</h3>
-        <span className="font-mono text-xs text-muted tabular">{whenLabel(p.when)}</span>
-        {post.critical && <span className="text-xs text-unknown">critical</span>}
+        <h3 className="min-w-0 text-[1.0625rem] font-bold">{p.title}</h3>
+        {post.critical && <StatusWord tone="flag">Critical</StatusWord>}
+        <span className="tabular basis-full text-[0.8125rem] text-muted">{whenLabel(p.when)}</span>
       </header>
       {p.image_url && (
         // A plain <img>: next/image would need every news site's host in remotePatterns.
         // no-referrer so a third-party thumbnail never learns which page showed it.
         // eslint-disable-next-line @next/next/no-img-element
-        <img src={p.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" className="max-h-48 w-full rounded-sm object-cover" />
+        <img src={p.image_url} alt="" loading="lazy" referrerPolicy="no-referrer" className="max-h-48 w-full rounded-xl object-cover" />
       )}
       {p.headline_line && (
-        <p className="text-sm text-content">
+        <p className="max-w-[65ch] text-sm">
           {p.headline_line}
           {p.links.length > 0 && <span className="text-muted"> · </span>}
           {p.links.slice(0, 3).map((l, i) => (
             <span key={l.url}>
               {i > 0 && <span className="text-muted"> · </span>}
-              <a href={l.url} target="_blank" rel="noreferrer" className="underline decoration-border hover:text-content">{l.name}</a>
+              <a href={l.url} target="_blank" rel="noreferrer" className="font-semibold underline underline-offset-2">
+                {l.name}
+                <span className="sr-only"> (opens in a new tab)</span>
+              </a>
             </span>
           ))}
         </p>
       )}
-      {p.facts_line && <p className="font-mono text-xs text-muted tabular">{p.facts_line}</p>}
+      {p.facts_line && <p className="tabular text-[0.8125rem] text-muted">{p.facts_line}</p>}
       {p.grid.length > 0 && (
-        <table className="w-full text-xs">
-          <thead className="text-left text-muted"><tr><th className="pr-4">Asset</th><th className="pr-4">Textbook</th><th>Actual (15m)</th></tr></thead>
+        <table className="w-full text-[0.8125rem]">
+          <thead className="text-left text-xs font-semibold tracking-[0.04em] text-muted"><tr><th className="pb-1 pr-4 font-semibold">Asset</th><th className="pb-1 pr-4 font-semibold">Textbook</th><th className="pb-1 font-semibold">Actual (15m)</th></tr></thead>
           <tbody>
             {p.grid.map((g) => (
               <tr key={g.asset} data-testid={`grid-${g.asset}`} className="border-t border-border">
                 <td className="py-1 pr-4 capitalize">{g.asset}</td>
                 <td className="py-1 pr-4">{g.textbook ?? "·"}</td>
-                <td className="py-1 font-mono tabular">{g.actual ?? "pending"}</td>
+                <td className="tabular py-1">{g.actual ?? "pending"}</td>
               </tr>
             ))}
           </tbody>
         </table>
       )}
-      {p.grid_note && <p className="text-xs text-muted">{p.grid_note}</p>}
+      {p.grid_note && <p className="text-[0.8125rem] text-muted">{p.grid_note}</p>}
       {e && (
-        <div className="space-y-1 text-sm">
-          <p className="text-content">{e.read}</p>
-          <p className="text-muted">Bull: {e.bull} · Bear: {e.bear}</p>
+        <div className="space-y-1.5 rounded-xl bg-sunk px-3 py-2 text-sm" data-testid="news-reading">
+          <p className="flex flex-wrap items-baseline gap-x-2 text-xs">
+            <span className="font-semibold">The news model&apos;s reading</span>
+            <span className="text-muted">Claude, or the local model when Claude cannot be reached; it trades nothing</span>
+          </p>
+          <p className="max-w-[65ch]">{e.read}</p>
+          <p className="max-w-[65ch] text-muted">Bull: {e.bull} · Bear: {e.bear}</p>
           <VerdictPill verdict={e.verdict} confidence={e.confidence} />
-          {e.book_impact && <p className="text-content">Your book: {e.book_impact}</p>}
-          {e.setup_impact && <p className="text-content">Setups: {e.setup_impact}</p>}
-          {p.trimmed && <p className="text-xs text-unknown">Some unsupported numbers were removed.</p>}
+          {e.book_impact && <p className="max-w-[65ch]">Your book: {e.book_impact}</p>}
+          {e.setup_impact && <p className="max-w-[65ch]">Setups: {e.setup_impact}</p>}
+          {p.trimmed && <p className="text-xs text-muted">Some unsupported numbers were removed.</p>}
         </div>
       )}
-      {p.llm_note && <p className="text-xs text-muted">{p.llm_note}</p>}
+      {p.llm_note && <p className="text-[0.8125rem] text-muted">{p.llm_note}</p>}
       {p.sections.map((s) => (
         <section key={s.title} className="space-y-1">
-          <h4 className="text-xs font-medium text-muted">{s.title}</h4>
+          <h4 className="text-xs font-semibold tracking-[0.04em] text-muted">{s.title}</h4>
+          {s.items.some((it) => it.read || it.verdict) && (
+            <p className="text-xs text-muted">The readings and verdicts below are the news model&apos;s.</p>
+          )}
           <ul className="space-y-1 text-sm">
             {s.items.map((it, i) => (
               <li key={i}>
@@ -72,12 +90,12 @@ export function NewsCard({ post, chartUri }: { post: NewsPost; chartUri?: string
           </ul>
         </section>
       ))}
-      {p.updates.map((u, i) => <p key={i} className="text-xs text-muted">{u}</p>)}
+      {p.updates.map((u, i) => <p key={i} className="text-[0.8125rem] text-muted">{u}</p>)}
       {chartUri && (
         // A data: URI from GET /news/posts/{id}; next/image adds nothing for an inline PNG.
         // eslint-disable-next-line @next/next/no-img-element
-        <img src={chartUri} alt={`${post.subject ?? "News"} chart`} className="w-full rounded-sm" />
+        <img src={chartUri} alt={`${post.subject ?? "News"} chart`} className="w-full rounded-xl" />
       )}
-    </article>
+    </Card>
   );
 }
diff --git a/web/components/news/VerdictPill.tsx b/web/components/news/VerdictPill.tsx
index b0721a4..81d298b 100644
--- a/web/components/news/VerdictPill.tsx
+++ b/web/components/news/VerdictPill.tsx
@@ -4,17 +4,23 @@ import { VERDICT_LABEL } from "./format";
 const ICON: Record<Verdict, string> = {
   further_downside_likely: "▼", further_upside_likely: "▲", overreaction_likely: "↺", priced_in: "=", unclear: "?",
 };
-const TONE: Record<Verdict, string> = {
-  further_downside_likely: "text-loss", further_upside_likely: "text-gain", overreaction_likely: "text-content",
-  priced_in: "text-muted", unclear: "text-unknown",
-};
 
+/**
+ * The news model's verdict as an outlined pill (restyled in place, web overhaul Part 7): the icon and the
+ * words carry the direction, in ink. A verdict is a forecast, not money, so it is never green or red
+ * (web/DESIGN.md Colors); "Unclear" alone is muted.
+ */
 export function VerdictPill({ verdict, confidence }: { verdict: Verdict; confidence?: string }) {
   return (
-    <span data-testid="verdict" className={`inline-flex items-center gap-1 rounded-sm bg-elevated px-2 py-0.5 text-xs ${TONE[verdict]}`}>
+    <span
+      data-testid="verdict"
+      className={`inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-0.5 text-xs font-semibold ${
+        verdict === "unclear" ? "text-muted" : "text-content"
+      }`}
+    >
       <span aria-hidden="true">{ICON[verdict]}</span>
       {VERDICT_LABEL[verdict]}
-      {confidence ? <span className="text-muted"> · {confidence}</span> : null}
+      {confidence ? <span className="font-normal text-muted"> · {confidence} confidence</span> : null}
     </span>
   );
 }
````

### Task 5: The ticker news page

**Files:** Create `web/features/news/NewsTickerPage.tsx` (+ `NewsTickerPage.test.tsx`); modify
`web/app/news/[symbol]/page.tsx` (it mounts the page with `decodeSegment`), `web/components/news/NewsTicker.tsx` (+
test), `web/components/news/BriefRequest.tsx`, `web/DESIGN.md` (the News surface, a Decision Log entry); this plan
(Progress log).

**What it does (rulings 18, 19):** `/news/SYM` gets the frame with a back link to News, the ticker as its title, a
"Stock page" link (the operator's answer: keep the page, cross-linked) and Refresh; "Request fresh brief" becomes
the secondary `Button` (its `news_brief` command, receipt, poll and disabled-while-pending unchanged; a refused
request is a plain sentence, never red). The body keeps its reads and adds a loading block and a failure sentence;
"Recent stories" is one card of rows whose source links are 44px on a phone and say they open a new tab. The two
tests that drove the request button move from `NewsTicker.test.tsx` to `NewsTickerPage.test.tsx` (the button now
lives in the page header); the "Request fresh brief" and `news_brief` payload assertions are kept word for word.

- [x] **Step 1: Check and apply `T5`.** `git status --short` shows five `M` files (`web/DESIGN.md`,
  `web/app/news/[symbol]/page.tsx`, `web/components/news/BriefRequest.tsx`, `web/components/news/NewsTicker.test.tsx`,
  `web/components/news/NewsTicker.tsx`) and `?? web/features/news/NewsTickerPage.test.tsx`,
  `?? web/features/news/NewsTickerPage.tsx`.
- [x] **Step 2: Red check.** `git stash push -- web/components/news/NewsTicker.tsx web/components/news/BriefRequest.tsx`,
  then `cd web && npx vitest run components/news/NewsTicker.test.tsx features/news/NewsTickerPage.test.tsx` ends
  `6 failed | 2 passed (8)`, then `git stash pop`.
- [x] **Step 3: Gate.** `npx vitest run components/news features/news app/titles.test.ts`: 7 files, 54 passed. Full
  vitest **1644 in 160 files**; tsc, lint clean; G1 empty; G2 both greps as listed; G3 exit 0; G4 green (19 rows, `○
  /news` and `ƒ /news/[symbol]` among them; scratch build removed); G5 as in Task 3; G6 passes; G7 the one layout line.
- [x] **Step 4: Commit** `feat(web): a name's news page in the frame, linked to its stock page, with the brief
  request as the secondary button` with the Progress log row and the Section B exit row.

<!-- block T5 -->
````diff
diff --git a/web/DESIGN.md b/web/DESIGN.md
index 247531a..e2bda0d 100644
--- a/web/DESIGN.md
+++ b/web/DESIGN.md
@@ -1118,9 +1118,33 @@ overhaul Part 5) on the Position page's frame.
 - No new token, colour, font, radius or elevation.
 
 ### News
-Read. Feed and calendar; ticker briefs. The feed opens with the Market card: regimes, up to six stories
-with each description labelled as Claude's, and one line on the last 7 days of triage (judged as noise,
-promoted, not reviewed). A ticker page carries that name's notes.
+- **JOB:** Read. What moved, what is scheduled this week, and what the news service made of it. The one
+  write is a ticker page's brief request (a `news_brief` command the news process drains). Nothing here trades.
+- **FORM:** the Stock and Research frame (1200px, `px-4` on a phone, `px-7` from 768px; the 24px/800 title and a
+  muted line, Refresh at the right). The Market card full width (regimes, up to six stories with each description
+  labelled as Claude's, one line on the last 7 days of triage), then two single-track columns from 1024px
+  (`minmax(0,1fr)` and 340px): **Latest** on the left, **This week** on the right. The DOM order is the phone order.
+- **Latest:** the title, "The news service's posts, newest first, 30 at most.", the group chips (All, Macro,
+  Market, Tickers, Earnings, Briefs: the chips appearance, ink when chosen, a 44px hit area on a phone) and a
+  labelled "Filter by symbol" field (the shared field: 16px, 44px tall). Then the posts as white cards. Loading
+  holds a block; a failed read, a service that has not written yet, and no match ("No posts match ZZZ in this
+  group.") are sentences.
+- **A post:** the emoji, the title (17px/700), a flag-amber "Critical" word, the time (Singapore, then New York) in
+  muted tabular figures; the service's headline line with its sources as underlined inline links that say they
+  open a new tab; the facts; the reaction grid; then the explanation in a pressed-sage block labelled "The news
+  model's reading" ("Claude, or the local model when Claude cannot be reached; it trades nothing"), never as
+  Claude's alone, because the news model falls back to a local one. The verdict is an outlined ink pill whose icon
+  and words carry the direction: a forecast is not money, so it is never green or red ("Unclear" is muted). A
+  digest says once that its readings and verdicts are the news model's.
+- **This week:** one white card, "The next 7 days, in Singapore time with New York time beside it.", the economic
+  releases ("0.4% vs 0.3% forecast", a missing forecast hatched) and the earnings (the ticker a link to its news
+  page, 44px on a phone, a neutral "Held" word, the day and BMO/AMC) as quiet rows. Empty, not yet written,
+  loading and failed are each said; the card never vanishes.
+- **A ticker page** (`/news/SYM`): a back link to News, the ticker as the title, the "Stock page" link (the
+  secondary pill) and Refresh, then "Request fresh brief" (the secondary button; its receipt beside it; a refused
+  request is a plain sentence, never red). Then the next earnings, the latest brief (a post card with its chart),
+  the market picture's notes on the name, and "Recent stories": one card of rows, the headline bold, the source
+  count, and up to two sources as links (44px on a phone, "(opens in a new tab)"). One column at most 820px wide.
 
 ### More
 Read and Operate. How it works (the System Explanation pages), What Claude knows (a link to its own surface), Bot controls, Theme, the monthly income target, Ledger import, Credits.
@@ -1204,6 +1228,11 @@ sibling keys; re-run the check after edits.
 
 ## Decision Log
 
+- 2026-11-07: **News on the payslip** (web overhaul Part 7, Tasks 3-5). The feed and the ticker page take the Stock
+  and Research frame; the calendar is one card of rows that says when it is empty or failed instead of vanishing;
+  the news verdict is an outlined ink pill (a forecast is not money); the explanation is labelled as the news
+  model's reading, since the news model falls back to a local model; the ticker page links to the stock page
+  (the operator's answer: keep the page). No new token, colour, font, radius or elevation.
 - 2026-11-07: **Two Part 6 proposals taken** (web overhaul Part 7, Task 1; the operator's answer). The rail's
   Search row is an outlined field (a control-edge border on white) instead of a pressed-sage row, so the current
   destination is the only pressed-sage row in the rail; a sector's IV-rank count reads "(7 with history)" instead
diff --git a/web/app/news/[symbol]/page.tsx b/web/app/news/[symbol]/page.tsx
index ae2ad4f..2326fb5 100644
--- a/web/app/news/[symbol]/page.tsx
+++ b/web/app/news/[symbol]/page.tsx
@@ -1,9 +1,10 @@
 "use client";
 
 import { use } from "react";
-import { NewsTicker } from "@/components/news/NewsTicker";
+import { NewsTickerPage } from "@/features/news/NewsTickerPage";
+import { decodeSegment } from "@/lib/segment";
 
-export default function NewsTickerPage({ params }: { params: Promise<{ symbol: string }> }) {
+export default function Page({ params }: { params: Promise<{ symbol: string }> }) {
   const { symbol } = use(params);
-  return <NewsTicker symbol={symbol} />;
+  return <NewsTickerPage symbol={decodeSegment(symbol)} />;
 }
diff --git a/web/components/news/BriefRequest.tsx b/web/components/news/BriefRequest.tsx
index 5f32276..147baeb 100644
--- a/web/components/news/BriefRequest.tsx
+++ b/web/components/news/BriefRequest.tsx
@@ -5,8 +5,14 @@ import { useQuery, useQueryClient } from "@tanstack/react-query";
 import { apiFetch, ApiError } from "@/lib/api";
 import { submitCommand, useCommandStatus, type CommandStatus } from "@/lib/commands";
 import { CommandReceipt } from "@/components/options/CommandReceipt";
+import { Button } from "@/components/ui/Button";
 import type { ControlsResponse } from "@/components/options/types";
 
+/**
+ * Asks the news process for a fresh brief on one name: a `news_brief` command, its receipt and its poll
+ * (unchanged; restyled in place in web overhaul Part 7 as the secondary button, with a failure said in
+ * words, never red). It trades nothing.
+ */
 export function BriefRequest({ symbol }: { symbol: string }) {
   const [command, setCommand] = useState<CommandStatus | null>(null);
   const [error, setError] = useState<string | null>(null);
@@ -34,12 +40,11 @@ export function BriefRequest({ symbol }: { symbol: string }) {
   }
 
   return (
-    <div className="flex items-center gap-2">
-      <button type="button" onClick={onClick} disabled={submitting || current?.status === "pending"}
-        className="rounded-sm border border-border bg-background px-3 py-1.5 text-sm text-content enabled:hover:bg-elevated disabled:opacity-50 focus-visible:ring-focus">
+    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
+      <Button variant="secondary" onClick={onClick} disabled={submitting || current?.status === "pending"}>
         Request fresh brief
-      </button>
-      {error && <p className="text-xs text-loss" role="alert">{error}</p>}
+      </Button>
+      {error && <p className="text-sm" role="alert">{error}</p>}
       {current && <CommandReceipt command={current} order={null} drainHealthy={controls.data?.drain_healthy ?? true} plainReasons={["invalid_symbol"]} />}
     </div>
   );
diff --git a/web/components/news/NewsTicker.test.tsx b/web/components/news/NewsTicker.test.tsx
index f28e24f..2674ad4 100644
--- a/web/components/news/NewsTicker.test.tsx
+++ b/web/components/news/NewsTicker.test.tsx
@@ -1,12 +1,13 @@
-import { fireEvent, screen } from "@testing-library/react";
-import { describe, expect, it, vi } from "vitest";
+import { render, screen } from "@testing-library/react";
+import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
+import { describe, expect, it } from "vitest";
 import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
 import { NewsTicker } from "./NewsTicker";
 
 const ISO = new Date().toISOString();
 
 describe("NewsTicker", () => {
-  it("shows the latest brief and the request button", async () => {
+  it("shows the latest brief with its chart and the grouped stories", async () => {
     renderWithQuery(<NewsTicker symbol="tsm" />, {
       "/news/ticker/TSM": {
         as_of: ISO, available: true, symbol: "TSM",
@@ -16,44 +17,55 @@ describe("NewsTicker", () => {
         next_earnings: null, request: null,
       },
       "/news/posts/4": { as_of: ISO, available: true, post: { id: 4 }, chart_data_uri: "data:image/png;base64,AAAA" },
-      "/options/controls": { drain_healthy: true },
     });
     expect(await screen.findByText("TSM brief")).toBeInTheDocument();
-    expect(screen.getByRole("button", { name: /request fresh brief/i })).toBeInTheDocument();
     expect(await screen.findByRole("img", { name: /TSM chart/i })).toHaveAttribute("src", "data:image/png;base64,AAAA");
     expect(screen.getByText("TSMC beats on AI demand")).toBeInTheDocument();
   });
 
-  it("submits a news_brief command for the symbol and shows the receipt", async () => {
-    renderWithQuery(<NewsTicker symbol="tsm" />, {
+  it("lists the stories in a titled card, each source a 44px link on a phone that says it opens a new tab", async () => {
+    renderWithQuery(<NewsTicker symbol="TSM" />, {
       "/news/ticker/TSM": {
-        as_of: ISO, available: true, symbol: "TSM", latest_brief: null, clusters: [], next_earnings: null, request: null,
+        as_of: ISO, available: true, symbol: "TSM", latest_brief: null, next_earnings: null, request: null,
+        clusters: [
+          { id: 1, headline: "TSMC beats on AI demand", source_count: 3, last_seen: ISO, links: [{ name: "Reuters", url: "https://r.example/1" }] },
+          { id: 2, headline: "Fab delay in Arizona", source_count: 1, last_seen: ISO, links: [] },
+        ],
       },
-      "/commands": {
-        id: 7, kind: "news_brief", status: "pending", result: null, needs_confirmation: false, confirm_token: null,
-        created_at: ISO, applied_at: null, as_of: ISO, created: true,
+    });
+    expect(await screen.findByRole("heading", { level: 2, name: "Recent stories" })).toBeInTheDocument();
+    const link = screen.getByRole("link", { name: "Reuters (opens in a new tab)" });
+    expect(link).toHaveAttribute("target", "_blank");
+    expect(link).toHaveClass("min-h-11", "md:min-h-0");
+    expect(screen.getByText("3 sources")).toBeInTheDocument();
+    expect(screen.getByText("1 source")).toBeInTheDocument();
+  });
+
+  it("says the next earnings with its timing", async () => {
+    renderWithQuery(<NewsTicker symbol="NVDA" />, {
+      "/news/ticker/NVDA": {
+        as_of: ISO, available: true, symbol: "NVDA", latest_brief: null, clusters: [], request: null,
+        next_earnings: { symbol: "NVDA", report_date: "2026-11-19", timing: "amc", eps_est: null, eps_actual: null, status: "scheduled", held: false },
       },
-      "/options/controls": { drain_healthy: true },
     });
-    expect(await screen.findByText(/no brief yet/i)).toBeInTheDocument();
-    fireEvent.click(screen.getByRole("button", { name: /request fresh brief/i }));
-    await vi.waitFor(() =>
-      expect(
-        apiFetchMock.mock.calls.some(
-          (c) => c[0] === "/commands" && JSON.parse(String((c[1] as RequestInit).body)).kind === "news_brief"
-            && JSON.parse(String((c[1] as RequestInit).body)).payload.symbol === "TSM",
-        ),
-      ).toBe(true),
-    );
-    await vi.waitFor(() => expect(screen.getByRole("button", { name: /request fresh brief/i })).toBeDisabled());
+    expect(await screen.findByText(/^Next earnings .* · AMC$/)).toBeInTheDocument();
   });
 
   it("says the news service has not run yet when unavailable", async () => {
     renderWithQuery(<NewsTicker symbol="NVDA" />, {
       "/news/ticker/NVDA": { as_of: ISO, available: false, symbol: "NVDA", latest_brief: null, clusters: [], next_earnings: null, request: null },
-      "/options/controls": { drain_healthy: true },
     });
     expect(await screen.findByText(/news service has not written anything yet/i)).toBeInTheDocument();
     expect(screen.queryByText(/no brief yet/i)).not.toBeInTheDocument();
   });
+
+  it("says it is loading, and says a failed read in words", async () => {
+    apiFetchMock.mockImplementation(() => new Promise(() => {}));
+    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
+    const { unmount } = render(<QueryClientProvider client={qc}><NewsTicker symbol="NVDA" /></QueryClientProvider>);
+    expect(screen.getByRole("status", { name: "Loading NVDA news" })).toBeInTheDocument();
+    unmount();
+    renderWithQuery(<NewsTicker symbol="NVDA" />, {});
+    expect(await screen.findByText("The news for NVDA could not be loaded. It is asked for again every minute.")).toBeInTheDocument();
+  });
 });
diff --git a/web/components/news/NewsTicker.tsx b/web/components/news/NewsTicker.tsx
index 0c84957..623daaf 100644
--- a/web/components/news/NewsTicker.tsx
+++ b/web/components/news/NewsTicker.tsx
@@ -1,14 +1,19 @@
 "use client";
 
-import { RefreshButton } from "@/components/shell/RefreshButton";
 import { useQuery } from "@tanstack/react-query";
 import { apiFetch } from "@/lib/api";
-import { BriefRequest } from "./BriefRequest";
+import { Card } from "@/components/ui/Card";
 import { NewsCard } from "./NewsCard";
 import { NameNotes } from "@/features/market/NameNotes";
 import { dayLabel } from "./format";
 import type { NewsPostDetail, NewsTickerResponse } from "./types";
 
+/**
+ * The body of one name's news page (restyled in place, web overhaul Part 7; the frame, the title and the
+ * brief request are `features/news/NewsTickerPage`): the next earnings, the latest brief, the market
+ * picture's notes on the name and the grouped stories. Loading, failed, not yet written and no brief are
+ * each a sentence.
+ */
 export function NewsTicker({ symbol }: { symbol: string }) {
   const sym = symbol.toUpperCase();
   const t = useQuery({
@@ -21,36 +26,49 @@ export function NewsTicker({ symbol }: { symbol: string }) {
                             queryFn: () => apiFetch<NewsPostDetail>(`/news/posts/${briefId}`) });
 
   return (
-    <div className="space-y-4" data-testid="news-ticker">
-      <header className="flex items-center justify-between gap-4">
-        <h1 className="font-mono text-lg text-content">{sym}</h1>
-        <div className="flex items-center gap-2">
-          <BriefRequest symbol={sym} />
-          <RefreshButton label={`Refresh ${sym} news`} />
-        </div>
-      </header>
+    <>
+      {t.isPending && <div role="status" aria-busy="true" aria-label={`Loading ${sym} news`} className="h-28 rounded-[18px] bg-surface" />}
+      {t.isError && !t.data && <p className="text-sm">The news for {sym} could not be loaded. It is asked for again every minute.</p>}
       {t.data?.next_earnings && (
-        <p className="text-sm text-muted">Next earnings {dayLabel(t.data.next_earnings.report_date)} {t.data.next_earnings.timing.toUpperCase()}</p>
+        <p className="tabular text-sm">
+          Next earnings {dayLabel(t.data.next_earnings.report_date)}
+          {t.data.next_earnings.timing ? ` · ${t.data.next_earnings.timing.toUpperCase()}` : ""}
+        </p>
       )}
-      {t.data && !t.data.available && <p className="text-sm text-muted">The news service has not written anything yet.</p>}
-      {t.data?.available && !t.data.latest_brief && <p className="text-sm text-muted">No brief yet. Request one above.</p>}
+      {t.data && !t.data.available && <p className="text-sm">The news service has not written anything yet.</p>}
+      {t.data?.available && !t.data.latest_brief && <p className="text-sm">No brief yet. Request one above.</p>}
       {t.data?.latest_brief && <NewsCard post={t.data.latest_brief} chartUri={detail.data?.chart_data_uri ?? null} />}
       <NameNotes symbol={sym} />
       {t.data && t.data.clusters.length > 0 && (
-        <section className="space-y-2">
-          <h2 className="text-sm font-medium text-content">Recent stories</h2>
-          <ul className="space-y-1 text-sm">
+        <Card aria-labelledby="stories-title">
+          <h2 id="stories-title" className="text-[1.0625rem] font-bold">
+            Recent stories
+          </h2>
+          <p className="mt-1 text-[0.8125rem] text-muted">Headlines the news service grouped as one story, with how many sources carried it.</p>
+          <ul className="mt-2">
             {t.data.clusters.map((c) => (
-              <li key={c.id}>
-                {c.headline} <span className="text-muted">· {c.source_count} sources</span>
-                {c.links.slice(0, 2).map((l) => (
-                  <a key={l.url} href={l.url} target="_blank" rel="noreferrer" className="ml-2 text-xs underline decoration-border">{l.name}</a>
-                ))}
+              <li key={c.id} className="border-t border-border py-2 text-sm first:border-t-0 md:py-2.5">
+                <p className="font-semibold">{c.headline}</p>
+                <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-[0.8125rem] text-muted">
+                  <span className="tabular">{c.source_count === 1 ? "1 source" : `${c.source_count} sources`}</span>
+                  {c.links.slice(0, 2).map((l) => (
+                    <a
+                      key={l.url}
+                      href={l.url}
+                      target="_blank"
+                      rel="noreferrer"
+                      className="flex min-h-11 items-center font-semibold text-content underline-offset-2 hover:underline md:inline md:min-h-0"
+                    >
+                      {l.name}
+                      <span className="sr-only"> (opens in a new tab)</span>
+                    </a>
+                  ))}
+                </div>
               </li>
             ))}
           </ul>
-        </section>
+        </Card>
       )}
-    </div>
+    </>
   );
 }
diff --git a/web/features/news/NewsTickerPage.test.tsx b/web/features/news/NewsTickerPage.test.tsx
new file mode 100644
index 0000000..c9b405d
--- /dev/null
+++ b/web/features/news/NewsTickerPage.test.tsx
@@ -0,0 +1,54 @@
+import { fireEvent, screen } from "@testing-library/react";
+import { describe, expect, it, vi } from "vitest";
+import { apiFetchMock, renderWithQuery } from "@/lib/test-query";
+import { NewsTickerPage } from "./NewsTickerPage";
+
+const ISO = new Date().toISOString();
+const empty = { as_of: ISO, available: true, symbol: "TSM", latest_brief: null, clusters: [], next_earnings: null, request: null };
+
+describe("NewsTickerPage", () => {
+  it("is titled by the ticker, with a back link to News and a link to the stock page", () => {
+    renderWithQuery(<NewsTickerPage symbol="tsm" />, { "/news/ticker/TSM": empty, "/options/controls": { drain_healthy: true } });
+    expect(screen.getByRole("heading", { level: 1, name: "TSM" })).toBeInTheDocument();
+    expect(screen.getByRole("link", { name: "News" })).toHaveAttribute("href", "/news");
+    expect(screen.getByRole("link", { name: "Stock page" })).toHaveAttribute("href", "/stock/TSM");
+    expect(screen.getByRole("button", { name: "Refresh TSM news" })).toBeInTheDocument();
+  });
+
+  it("asks for a fresh brief with the secondary button, which submits a news_brief command for the symbol", async () => {
+    renderWithQuery(<NewsTickerPage symbol="tsm" />, {
+      "/news/ticker/TSM": empty,
+      "/commands": {
+        id: 7, kind: "news_brief", status: "pending", result: null, needs_confirmation: false, confirm_token: null,
+        created_at: ISO, applied_at: null, as_of: ISO, created: true,
+      },
+      "/options/controls": { drain_healthy: true },
+    });
+    expect(await screen.findByText(/no brief yet/i)).toBeInTheDocument();
+    const button = screen.getByRole("button", { name: /request fresh brief/i });
+    expect(button).toHaveAttribute("data-variant", "secondary");
+    fireEvent.click(button);
+    await vi.waitFor(() =>
+      expect(
+        apiFetchMock.mock.calls.some(
+          (c) => c[0] === "/commands" && JSON.parse(String((c[1] as RequestInit).body)).kind === "news_brief"
+            && JSON.parse(String((c[1] as RequestInit).body)).payload.symbol === "TSM",
+        ),
+      ).toBe(true),
+    );
+    await vi.waitFor(() => expect(screen.getByRole("button", { name: /request fresh brief/i })).toBeDisabled());
+  });
+
+  it("says a refused request in words, never in red", async () => {
+    renderWithQuery(<NewsTickerPage symbol="TSM" />, { "/news/ticker/TSM": empty, "/options/controls": { drain_healthy: true } });
+    apiFetchMock.mockImplementation(async (path: string) => {
+      if (path === "/commands") throw new Error("boom");
+      if (path.startsWith("/news/ticker")) return empty;
+      return { drain_healthy: true };
+    });
+    fireEvent.click(screen.getByRole("button", { name: /request fresh brief/i }));
+    const alert = await screen.findByRole("alert");
+    expect(alert).toHaveTextContent("The request could not be created.");
+    expect(alert.className).not.toMatch(/text-loss/);
+  });
+});
diff --git a/web/features/news/NewsTickerPage.tsx b/web/features/news/NewsTickerPage.tsx
new file mode 100644
index 0000000..3dcf7d0
--- /dev/null
+++ b/web/features/news/NewsTickerPage.tsx
@@ -0,0 +1,50 @@
+"use client";
+
+import Link from "next/link";
+import { ChevronLeft } from "lucide-react";
+import { RefreshButton } from "@/components/shell/RefreshButton";
+import { BriefRequest } from "@/components/news/BriefRequest";
+import { NewsTicker } from "@/components/news/NewsTicker";
+
+// A link to another page, drawn like the secondary button (Research's LINK). Never lime.
+const LINK =
+  "inline-flex min-h-11 items-center justify-center rounded-full bg-sunk px-[18px] text-[1.0625rem] font-bold text-content hover:bg-sunk-deep";
+
+/**
+ * One name's news (web overhaul Part 7): the Stock and Research frame with a back link to News, the
+ * ticker as the title, then the brief request, a link to the name's stock page and Refresh. The body
+ * (`components/news/NewsTicker`) reads; the brief request is the page's one write, a `news_brief`
+ * command the news process drains (unchanged).
+ */
+export function NewsTickerPage({ symbol }: { symbol: string }) {
+  const sym = symbol.toUpperCase();
+  return (
+    <div className="mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4">
+      <Link
+        href="/news"
+        className="inline-flex min-h-11 items-center gap-1 text-[0.8125rem] font-semibold text-muted hover:text-content md:min-h-8"
+      >
+        <ChevronLeft size={16} aria-hidden="true" />
+        News
+      </Link>
+      <header className="mt-1 flex flex-wrap items-start justify-between gap-3">
+        <div className="min-w-0">
+          <h1 className="text-2xl font-extrabold tracking-[-0.015em]">{sym}</h1>
+          <p className="mt-1 text-sm text-muted">The latest brief on this name, its notes and the stories the news service grouped.</p>
+        </div>
+        <div className="flex flex-wrap items-center gap-2">
+          <Link href={`/stock/${encodeURIComponent(sym)}`} className={LINK}>
+            Stock page
+          </Link>
+          <RefreshButton label={`Refresh ${sym} news`} />
+        </div>
+      </header>
+      <div className="mt-4">
+        <BriefRequest symbol={sym} />
+      </div>
+      <div className="mt-6 grid min-w-0 max-w-[820px] grid-cols-1 gap-4">
+        <NewsTicker symbol={sym} />
+      </div>
+    </div>
+  );
+}
````

## Section C: How it works (Tasks 6-7) · model: sonnet (effort high)

**Reads:** this section; root `CLAUDE.md` ("Core invariant", "The spreads fence", "The value fence"; to check the
copy, not to change it); `web/app/explain/page.tsx`; `web/features/search/pages.ts`; `web/app/more/page.tsx` (lines
12-20).

**Spec for da-vinci (Task 6; give it this):** the How it works Surfaces paragraph in the T6 patch is the spec (ruling
20). The Stock/Research frame without actions; seven white cards in one column at most 820px wide; each card a
17px/700 title, paragraphs at most 65 characters wide in 14px body, then a 13px line "See it on" (muted) followed by
underlined semibold links, each a 44px row on a phone and inline from 768px. No lime, no icon, no chip, no tab. The
words are fixed by the patch: if da-vinci finds a sentence untrue against root `CLAUDE.md`, stop and report it rather
than rewording (a copy change needs the operator). Record "no change" in the row.

**Entry checks:**

- [x] **C1. Section B landed.** In `<W>`: `git log --oneline main..HEAD` shows the five task commits of Sections A and
  B; vitest **1644 in 160 files**; tsc and lint clean; G1 empty; G2 both greps as listed; G7 the one layout line.
- [x] **C2. Task 6's patch applies:** `git apply --check <S>/p7/T6.out` prints nothing. (T7 edits a file T6 creates,
  so it is checked in Task 7's Step 1.)
- [x] **C3. Starting shape.** `ls web/components/explain | wc -l` prints `26`;
  `grep -rln "components/explain" web/app web/features web/components web/lib | grep -v "^web/components/explain/"`
  prints exactly `web/app/explain/page.tsx`; `ls web/features/explain` fails.

**Section exit:** two task commits; vitest **1620 in 153 files**; tsc, lint clean; G1, G2, G3, G5 (now over every
Part 7 folder, `web/components/explain` gone: `web/components/shell web/components/home web/components/stock
web/features/stock-value web/components/news web/features/news web/app/news web/features/explain web/app/explain
web/app/more web/features/search`), G6, G7; `git status --short` clean.

### Task 6: How it works

**Files:** Create `web/features/explain/ExplainPage.tsx` (+ `ExplainPage.test.tsx`); modify
`web/app/explain/page.tsx` (it mounts the page), `web/DESIGN.md` (a How it works surface, a Decision Log entry);
this plan (Progress log).

**What it does (rulings 2, 20):** `/explain` becomes seven short cards of plain English, each ending in links to the
pages that show it. The old eight-tab shell stays on disk until Task 7 but is no longer mounted.

- [x] **Step 1: Check and apply `T6`.** `git status --short` shows ` M web/DESIGN.md`, ` M web/app/explain/page.tsx`
  and `?? web/features/explain/`.
- [x] **Step 2: Red check.** `ExplainPage` is a new module: its red is the module missing (`git stash push -u --
  web/features/explain`, then `cd web && npx vitest run features/explain` reports no test files or an import
  failure, then `git stash pop`). `app/titles.test.ts` passes before and after (the title is still "How it works").
- [x] **Step 3: Gate.** `npx vitest run features/explain app/titles.test.ts`: all pass (features/explain 5 passed).
  Full vitest **1649 in 161 files**; tsc, lint clean; G3 exit 0; G5 over `web/features/explain web/app/explain`: no
  line for a non-test file.
- [x] **Step 4: Commit** `feat(web): How it works rebuilt small: seven cards of plain English, each linked to its
  page` with the Progress log row (and the Section C entry row).

<!-- block T6 -->
````diff
diff --git a/web/DESIGN.md b/web/DESIGN.md
index e2bda0d..45c2c62 100644
--- a/web/DESIGN.md
+++ b/web/DESIGN.md
@@ -1146,6 +1146,16 @@ overhaul Part 5) on the Position page's frame.
   the market picture's notes on the name, and "Recent stories": one card of rows, the headline bold, the source
   count, and up to two sources as links (44px on a phone, "(opens in a new tab)"). One column at most 820px wide.
 
+### How it works
+- **JOB:** Read. The system in plain English for the operator: what runs, who decides, and where to see it.
+- **FORM:** the Stock and Research frame; the title and one muted line; then seven white cards in one column at
+  most 820px wide, in this order: A day, from scan to order; Who decides what; Four books in one account; Sizing
+  and the market; Rolls, assignment and freeing cash; What keeps it safe; Where to look. Each card is a 17px/700
+  title, two to four short paragraphs at most 65 characters wide, and a "See it on" line of underlined links (44px
+  rows on a phone) to the pages that show it. Static copy (`features/explain/ExplainPage.tsx`), no request; every
+  sentence traceable to root `CLAUDE.md` or the code. Claude's limits and its two written exceptions are stated as
+  limits. It replaced the eight-tab System Explanation pages (2026-11-07).
+
 ### More
 Read and Operate. How it works (the System Explanation pages), What Claude knows (a link to its own surface), Bot controls, Theme, the monthly income target, Ledger import, Credits.
 
@@ -1228,6 +1238,10 @@ sibling keys; re-run the check after edits.
 
 ## Decision Log
 
+- 2026-11-07: **How it works rebuilt small** (web overhaul Part 7, Task 6; the operator's answer (a)). Seven short
+  cards of plain English replace the eight-tab System Explanation, which said nothing of spreads, the value book,
+  regime sizing, capital release, the news thread or the roll redesign. No new token, colour, font, radius or
+  elevation.
 - 2026-11-07: **News on the payslip** (web overhaul Part 7, Tasks 3-5). The feed and the ticker page take the Stock
   and Research frame; the calendar is one card of rows that says when it is empty or failed instead of vanishing;
   the news verdict is an outlined ink pill (a forecast is not money); the explanation is labelled as the news
diff --git a/web/app/explain/page.tsx b/web/app/explain/page.tsx
index 9c9caf0..61ad84e 100644
--- a/web/app/explain/page.tsx
+++ b/web/app/explain/page.tsx
@@ -1,8 +1,8 @@
 import type { Metadata } from "next";
-import { ExplainShell } from "@/components/explain/ExplainShell";
+import { ExplainPage } from "@/features/explain/ExplainPage";
 
 export const metadata: Metadata = { title: "How it works" };
 
-export default function ExplainPage() {
-  return <ExplainShell />;
+export default function Page() {
+  return <ExplainPage />;
 }
diff --git a/web/features/explain/ExplainPage.test.tsx b/web/features/explain/ExplainPage.test.tsx
new file mode 100644
index 0000000..c926785
--- /dev/null
+++ b/web/features/explain/ExplainPage.test.tsx
@@ -0,0 +1,49 @@
+import { render, screen } from "@testing-library/react";
+import { describe, expect, it } from "vitest";
+import { PAGES } from "@/features/search/pages";
+import { ExplainPage, PARTS } from "./ExplainPage";
+
+describe("ExplainPage", () => {
+  it("is titled How it works, with seven sections in a fixed order", () => {
+    render(<ExplainPage />);
+    expect(screen.getByRole("heading", { level: 1, name: "How it works" })).toBeInTheDocument();
+    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
+      "A day, from scan to order",
+      "Who decides what",
+      "Four books in one account",
+      "Sizing and the market",
+      "Rolls, assignment and freeing cash",
+      "What keeps it safe",
+      "Where to look",
+    ]);
+  });
+
+  it("links only to pages the console has (every link is in the search palette's page list)", () => {
+    const known = new Set(PAGES.map((p) => p.href));
+    for (const part of PARTS) for (const w of part.where) expect(known.has(w.href), w.href).toBe(true);
+    render(<ExplainPage />);
+    expect(screen.getAllByRole("link", { name: "Trades" })[0]).toHaveAttribute("href", "/trades");
+  });
+
+  it("states the core rule and both written exceptions as Claude's limits, not as Claude trading", () => {
+    const { container } = render(<ExplainPage />);
+    const text = container.textContent ?? "";
+    expect(text).toContain("it is the only path to an order");
+    expect(text).toContain("It never places, prices or gates an order");
+    expect(text).toContain("Claude may lower, never raise, the contract count");
+    expect(text).toContain("only recorded in live");
+    expect(text).toContain("the console never sends an order itself");
+  });
+
+  it("uses no em dash and none of the banned words", () => {
+    const { container } = render(<ExplainPage />);
+    const text = container.textContent ?? "";
+    expect(text).not.toContain("—");
+    expect(text).not.toMatch(/seamless|robust|unlock|elevate/i);
+  });
+
+  it("makes each link a 44px row on a phone", () => {
+    render(<ExplainPage />);
+    for (const link of screen.getAllByRole("link")) expect(link).toHaveClass("min-h-11", "md:min-h-0");
+  });
+});
diff --git a/web/features/explain/ExplainPage.tsx b/web/features/explain/ExplainPage.tsx
new file mode 100644
index 0000000..f75d3cb
--- /dev/null
+++ b/web/features/explain/ExplainPage.tsx
@@ -0,0 +1,127 @@
+import Link from "next/link";
+import { Card } from "@/components/ui/Card";
+
+type Where = { href: string; label: string };
+type Part = { id: string; title: string; body: string[]; where: Where[] };
+
+/**
+ * How it works (web overhaul Part 7, the operator's answer: rebuild small). Seven short sections of static
+ * plain English, each ending with the console pages that show it. Every sentence is traceable to root
+ * CLAUDE.md or the code; change the copy here when the system changes (STATUS.md is the record).
+ */
+export const PARTS: Part[] = [
+  {
+    id: "day",
+    title: "A day, from scan to order",
+    body: [
+      "During US market hours Python scans the names in your universe, reads their option chains and scores covered calls and cash-secured puts.",
+      "The Rules Engine checks every candidate against your limits. Only what passes becomes a proposal.",
+      "Claude reviews the proposals and writes a note on each. You approve or reject on Trades or in Telegram, unless the autonomy setting lets the system approve for you.",
+      "Before an order is sent, the Rules Engine checks it again against a fresh quote. Then a limit order at mid goes to Interactive Brokers.",
+    ],
+    where: [{ href: "/trades", label: "Trades" }, { href: "/", label: "Home" }],
+  },
+  {
+    id: "decides",
+    title: "Who decides what",
+    body: [
+      "The Rules Engine is plain Python with no model in it, and it is the only path to an order.",
+      "Claude reviews and ranks. It never places, prices or gates an order, and a malformed reply falls back to Python's list.",
+      "Two written exceptions: Claude may lower, never raise, the contract count of a cash-secured put the system opens on its own; and in the value book, on a name that already passed every Python gate, Claude's verdict decides Ready, Watch, Wait or No, with its fair value bounded by Python's. Both apply in paper and are only recorded in live until you have reviewed them.",
+      "You decide approvals, the autonomy setting, a halt, and which names are on the would-own list and the watchlist.",
+    ],
+    where: [{ href: "/more/claude", label: "What Claude knows" }, { href: "/research/universe", label: "Universe" }],
+  },
+  {
+    id: "books",
+    title: "Four books in one account",
+    body: [
+      "The wheel sells covered calls and cash-secured puts on the names in your universe.",
+      "Credit spreads trade daily SPY spreads in their own process with their own gate. Claude may pick from a menu Python built and checked, never beyond it. Paper only for now.",
+      "The value book buys and sells shares of companies scored from their filings, apart from the wheel's shares. Paper only for now.",
+      "The news service explains market and company news on its own thread. It never trades.",
+    ],
+    where: [{ href: "/portfolio", label: "Portfolio" }, { href: "/research", label: "Research" }, { href: "/news", label: "News" }],
+  },
+  {
+    id: "sizing",
+    title: "Sizing and the market",
+    body: [
+      "Python reads the market's regime from SPY and QQQ and uses it to size new cash-secured puts, and to hold some back when the market is weak.",
+      "The Market card on Home and News says what the regime does to new puts today. Every size is Python's.",
+    ],
+    where: [{ href: "/more/claude", label: "What Claude knows" }, { href: "/activity?view=system", label: "Activity, System" }],
+  },
+  {
+    id: "rolls",
+    title: "Rolls, assignment and freeing cash",
+    body: [
+      "When a short option comes under pressure, Python's roll policy decides whether to roll, take assignment, let the shares be called away, close or hold. The Rules Engine checks every roll against the roll limits in your settings.",
+      "When the value book wants to buy and the account is short of cash, the trading service may close the fewest wheel cash-secured puts at breakeven or better to free it. Paper only.",
+    ],
+    where: [{ href: "/trades", label: "Trades" }, { href: "/portfolio", label: "Portfolio" }],
+  },
+  {
+    id: "safety",
+    title: "What keeps it safe",
+    body: [
+      "Paper first: live trading needs a setting in the private environment file and the live port, and the console says which mode it is in.",
+      "A halt stops new orders until you lift it. Circuit breakers pause trading after losses. Every act on this console is a request that one of the system's services carries out after its own checks; the console never sends an order itself.",
+    ],
+    where: [{ href: "/more", label: "More" }, { href: "/activity?view=fills", label: "Activity, Fills and orders" }],
+  },
+  {
+    id: "pages",
+    title: "Where to look",
+    body: [
+      "Home is today: the account, what needs you and the market. Trades holds the proposals and the day's history. Portfolio is what you hold. Activity is your pay, the fills and the ledger. Research is what the value book would buy, your watchlist and the sectors. News is the feed and the calendar.",
+    ],
+    where: [
+      { href: "/", label: "Home" },
+      { href: "/trades", label: "Trades" },
+      { href: "/portfolio", label: "Portfolio" },
+      { href: "/activity", label: "Activity" },
+      { href: "/research", label: "Research" },
+      { href: "/news", label: "News" },
+    ],
+  },
+];
+
+export function ExplainPage() {
+  return (
+    <div className="mx-auto max-w-[1200px] px-4 py-3 md:px-7 md:py-4">
+      <header className="mt-1">
+        <h1 className="text-2xl font-extrabold tracking-[-0.015em]">How it works</h1>
+        <p className="mt-1 max-w-[65ch] text-sm text-muted">
+          The system in plain English: what runs, who decides, and where to see it on this console.
+        </p>
+      </header>
+      <div className="mt-6 grid max-w-[820px] grid-cols-1 gap-4">
+        {PARTS.map((p) => (
+          <Card key={p.id} aria-labelledby={`explain-${p.id}`}>
+            <h2 id={`explain-${p.id}`} className="text-[1.0625rem] font-bold">
+              {p.title}
+            </h2>
+            <div className="mt-2 max-w-[65ch] space-y-2 text-sm">
+              {p.body.map((b) => (
+                <p key={b}>{b}</p>
+              ))}
+            </div>
+            <p className="mt-3 flex flex-wrap items-center gap-x-4 text-[0.8125rem]">
+              <span className="text-muted">See it on</span>
+              {p.where.map((w) => (
+                <Link
+                  key={w.href}
+                  href={w.href}
+                  className="flex min-h-11 items-center font-semibold underline underline-offset-2 md:inline md:min-h-0"
+                >
+                  {w.label}
+                </Link>
+              ))}
+            </p>
+          </Card>
+        ))}
+      </div>
+    </div>
+  );
+}
````

### Task 7: The old explainer deleted

**Files:** Delete `web/components/explain/` (26 files); modify `web/app/more/page.tsx` (+ `page.test.tsx`),
`web/features/search/pages.ts`, `web/features/explain/ExplainPage.test.tsx`; this plan (Progress log).

**What it does (ruling 21):** removes the unmounted 1,532-line explainer and its 30 tests, and rewords the two places
that described it ("The pipeline in plain English").

- [x] **Step 1: Check and apply `T7`.** `git apply --check <S>/p7/T7.out` prints nothing, then `git apply
  <S>/p7/T7.out`. `git status --short` shows 26 ` D web/components/explain/...` lines and four ` M` lines
  (`web/app/more/page.test.tsx`, `web/app/more/page.tsx`, `web/features/explain/ExplainPage.test.tsx`,
  `web/features/search/pages.ts`).
- [x] **Step 2: Red check.** `git stash push -- web/components/explain web/app/more/page.tsx web/features/search/pages.ts`
  (the stash restores the folder and the old words), then `cd web && npx vitest run features/explain/ExplainPage.test.tsx app/more/page.test.tsx`
  ends `2 failed | 12 passed (14)`, then `git stash pop` (the folder is deleted again; `ls web/components/explain`
  fails).
- [x] **Step 3: Gate.** `npx vitest run features/explain features/search app/more app/titles.test.ts`: 4 files, all
  pass. Full vitest **1620 in 153 files**; tsc, lint clean; G1, G2, G3, G5 (the full Section C list), G6, G7.
- [x] **Step 4: Commit** `refactor(web): delete the eight-tab explainer that How it works replaced` with the Progress
  log row and the Section C exit row.

<!-- block T7 -->
````diff
diff --git a/web/app/more/page.test.tsx b/web/app/more/page.test.tsx
index 188fa78..645830a 100644
--- a/web/app/more/page.test.tsx
+++ b/web/app/more/page.test.tsx
@@ -38,6 +38,7 @@ describe("More page", () => {
     expect(screen.getByRole("link", { name: /Research/ })).toHaveAttribute("href", "/research");
     expect(screen.getByRole("link", { name: /News/ })).toHaveAttribute("href", "/news");
     expect(screen.getByRole("link", { name: /Import a statement/ })).toHaveAttribute("href", "/ledger/import");
+    expect(screen.getByRole("link", { name: /How it works/ })).toHaveTextContent("The system in plain English, and where to see it");
   });
   it("offers Search first, for a phone, which has no rail and no shortcut", () => {
     renderWithQuery(<MorePage />, served);
diff --git a/web/app/more/page.tsx b/web/app/more/page.tsx
index 8f127da..a8bf230 100644
--- a/web/app/more/page.tsx
+++ b/web/app/more/page.tsx
@@ -14,7 +14,7 @@ const LINKS = [
   { href: "/research/universe", label: "Universe", sub: "The names the scan covers; edit would-own and watchlist" },
   { href: "/news", label: "News", sub: "Feed, calendar and ticker briefs" },
   { href: "/activity?view=ledger", label: "Ledger", sub: "Broker trades and per-ticker roll-ups" },
-  { href: "/explain", label: "How it works", sub: "The pipeline in plain English" },
+  { href: "/explain", label: "How it works", sub: "The system in plain English, and where to see it" },
   { href: "/more/claude", label: "What Claude knows", sub: "The market picture and what each Claude call reads" },
   { href: "/ledger/import", label: "Import a statement", sub: "Upload an IBKR activity CSV" },
 ];
diff --git a/web/components/explain/Callout.test.tsx b/web/components/explain/Callout.test.tsx
deleted file mode 100644
index ef108a8..0000000
--- a/web/components/explain/Callout.test.tsx
+++ /dev/null
@@ -1,32 +0,0 @@
-import { render, screen } from "@testing-library/react";
-import { describe, expect, it } from "vitest";
-import { Callout } from "./Callout";
-
-describe("Callout", () => {
-  it("renders the label and children", () => {
-    render(<Callout label="No AI involved">Deterministic Python only.</Callout>);
-    expect(screen.getByText("No AI involved")).toBeDefined();
-    expect(screen.getByText("Deterministic Python only.")).toBeDefined();
-  });
-
-  it("defaults to the info tone", () => {
-    render(<Callout label="Note">text</Callout>);
-    expect(screen.getByText("Note").className).toContain("text-focus");
-  });
-
-  it("colours the label per tone, distinctly from every other tone", () => {
-    const { rerender } = render(
-      <Callout label="Guarantee" tone="positive">
-        text
-      </Callout>,
-    );
-    expect(screen.getByText("Guarantee").className).toContain("text-gain");
-
-    rerender(
-      <Callout label="Careful" tone="caution">
-        text
-      </Callout>,
-    );
-    expect(screen.getByText("Careful").className).toContain("text-unknown");
-  });
-});
diff --git a/web/components/explain/Callout.tsx b/web/components/explain/Callout.tsx
deleted file mode 100644
index 0539da3..0000000
--- a/web/components/explain/Callout.tsx
+++ /dev/null
@@ -1,51 +0,0 @@
-import type { ReactNode } from "react";
-import clsx from "clsx";
-
-type Tone = "info" | "positive" | "caution";
-
-// Mirrors the rest of the app's rule that state is never colour alone (see StageBadge,
-// CheckRibbon): each tone pairs its colour with a distinct border treatment - a caution
-// callout is dashed, not just a different hue - and the label text itself says what kind
-// of fact this is, so the tone reads correctly even for a viewer who can't see colour.
-const TONE_CLASS: Record<Tone, string> = {
-  info: "border-l-4 border-focus",
-  positive: "border-l-4 border-gain",
-  caution: "border-l-4 border-dashed border-unknown",
-};
-
-const TONE_LABEL_CLASS: Record<Tone, string> = {
-  info: "text-focus",
-  positive: "text-gain",
-  caution: "text-unknown",
-};
-
-/**
- * A raised-by-lightness callout for facts that are not design choices but hard
- * invariants or notable guarantees - "no LLM can place an order," "paper by default."
- * Elevation (bg-elevated) marks it as load-bearing, per this app's own rule that a
- * surface change is a background change; the tone accent is a second, deliberate layer
- * on top of that, not a replacement for it.
- */
-export function Callout({
-  label,
-  tone = "info",
-  children,
-}: {
-  label: string;
-  tone?: Tone;
-  children: ReactNode;
-}) {
-  return (
-    <div className={clsx("rounded-md bg-elevated px-4 py-3", TONE_CLASS[tone])}>
-      <div
-        className={clsx(
-          "mb-1 font-mono text-[11px] font-medium uppercase tracking-wide",
-          TONE_LABEL_CLASS[tone],
-        )}
-      >
-        {label}
-      </div>
-      <div className="text-sm text-content">{children}</div>
-    </div>
-  );
-}
diff --git a/web/components/explain/ClaudePanel.tsx b/web/components/explain/ClaudePanel.tsx
deleted file mode 100644
index f776682..0000000
--- a/web/components/explain/ClaudePanel.tsx
+++ /dev/null
@@ -1,96 +0,0 @@
-"use client";
-
-import { Callout } from "./Callout";
-import { FactCard } from "./FactCard";
-import { PanelShell } from "./PanelShell";
-import type { TabKey } from "./types";
-
-export function ClaudePanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
-  return (
-    <PanelShell
-      tab="claude"
-      title="Claude's role"
-      dek="A second pair of eyes - a small language model running locally on this Mac - that writes a short, plain-English verdict on each gate survivor. Advisory only - it cannot open, resize, or block a trade."
-      onNavigate={onNavigate}
-      ties={[
-        {
-          tab: "gate",
-          reason: "only reviews candidates the gate already approved, and can never override its verdict.",
-        },
-        {
-          tab: "execution",
-          reason: "its note rides along to Telegram next to the Approve/Reject buttons - context for the human, not a vote.",
-        },
-        {
-          tab: "watching",
-          reason: "the outcome of every trade it reviewed is logged read-only, for a human to study later.",
-        },
-      ]}
-      files={[
-        { path: "src/claude/ollama_runner.py", note: "calls the local Ollama model with a fixed JSON output schema and one overall deadline" },
-        { path: "src/claude/prompts/strategist.py", note: "what the model is actually shown - the numbered FACTS, the NEWS block, the rubric, the portfolio" },
-        { path: "src/claude/news_context.py", note: "builds the NEWS block from keyless Google News and Yahoo headlines" },
-        { path: "src/claude/ollama_tools.py", note: "the bounded research turn: up to two news searches before judging" },
-        { path: "src/claude/eval/", note: "the read-only outcome ledger and reconciler (see below)" },
-      ]}
-    >
-      <p className="text-muted">
-        The handful of top candidates that survive the rulebook get sent to a local language model
-        (Ollama, <code className="font-mono">qwen3.5:4b</code> by default). It never works the
-        numbers out itself: Python hands it a numbered list of FACTS for each candidate (how far
-        the strike is from the price, whether earnings land inside the trade, the credit against
-        its fair-value floor, the IV rank) plus a NEWS block of recent headlines, and it may run up
-        to two extra news searches before it judges. A short rubric tells it to default to
-        &quot;sell&quot; for a gate-passing trade unless a specific fact or headline argues
-        otherwise, and to name the ones it relied on. If the model is unavailable, times out, or
-        returns something unparseable, the system just proceeds without its commentary; nothing
-        waits on it, and the whole review is capped by one deadline so it cannot stall a scan.
-      </p>
-
-      <section>
-        <h3 className="font-mono text-sm text-content">What comes back, every time</h3>
-        <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
-          <FactCard tag="Verdict" tone="neutral" title="Sell, wait, or skip">
-            One of three calls, with a 2-3 sentence plain-English summary.
-          </FactCard>
-          <FactCard tag="Verdict" tone="neutral" title="Evidence">
-            The fact (F#) and headline (N#) ids the call relied on.
-          </FactCard>
-          <FactCard tag="Context" tone="caution" title="Key risks">
-            What could go wrong, in words.
-          </FactCard>
-          <FactCard tag="Context" tone="caution" title="Assignment notes">
-            How likely, and what it would mean.
-          </FactCard>
-        </div>
-      </section>
-
-      <Callout label="Invariant, enforced by a test" tone="positive">
-        The model&apos;s only tool is a read-only news search. It cannot call back into the system,
-        place an order, or change a config value, and none of the news or search code can be
-        imported by the rulebook, the execution path, or the strategy screens. If the model goes
-        down entirely, the pipeline ships the deterministic, gate-approved list on its own.
-      </Callout>
-
-      <section>
-        <h3 className="font-mono text-sm text-content">The fence around learning from outcomes</h3>
-        <p className="mt-1 text-muted">
-          Every candidate Claude reviews gets logged - its full signal set, Claude&apos;s verdict,
-          and what the deterministic rulebook would have done on its own - in a read-only outcome
-          ledger. When a trade closes, a reconciler fills in what actually happened. Periodically, a
-          read-only report buckets scores against real outcomes, purely so a human can ask
-          &quot;is this scoring approach actually predictive&quot; and, by hand, decide whether to
-          adjust <code className="font-mono">scoring_weights.yaml</code>.
-        </p>
-      </section>
-
-      <Callout label="What this loop can never do" tone="caution">
-        None of it can touch the rulebook, the sizing, or the scoring config on its own - a
-        dedicated test fails the build if any of that code ever becomes importable from the trading
-        path. There used to be a feature that auto-drafted strategy changes from this history; it
-        was removed, because the signal it measured never affects a live decision, so scoring its
-        &quot;accuracy&quot; didn&apos;t mean much.
-      </Callout>
-    </PanelShell>
-  );
-}
diff --git a/web/components/explain/DataPanel.tsx b/web/components/explain/DataPanel.tsx
deleted file mode 100644
index b0f0508..0000000
--- a/web/components/explain/DataPanel.tsx
+++ /dev/null
@@ -1,83 +0,0 @@
-"use client";
-
-import { Callout } from "./Callout";
-import { FactCard } from "./FactCard";
-import { PanelShell } from "./PanelShell";
-import type { TabKey } from "./types";
-
-export function DataPanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
-  return (
-    <PanelShell
-      tab="data"
-      title="Data in"
-      dek="The shopping list, how often it gets checked, and the research done on every name before anyone proposes a trade."
-      onNavigate={onNavigate}
-      ties={[
-        {
-          tab: "ideas",
-          reason: "every number gathered here - IV, technicals, fundamentals, sentiment - is what the generators price a trade against.",
-        },
-        {
-          tab: "claude",
-          reason: "the same research rides along, read-only, into the reasoning prompt as background context.",
-        },
-      ]}
-      files={[
-        { path: "config/universe.yaml", note: "the watchlist / would_own / actively_wheeling tiers" },
-        { path: "src/orchestrator/scan.py", note: "the 15-minute loop and its materiality gate" },
-        { path: "src/analytics/", note: "IV, technicals, fundamentals, liquidity, sentiment, macro" },
-      ]}
-    >
-      <section>
-        <h3 className="font-mono text-sm text-content">The shopping list - three tiers of eagerness</h3>
-        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
-          <FactCard tag="Tier 1" tone="caution" title="watchlist">
-            Covered-call candidates only, and only for names already owned.
-          </FactCard>
-          <FactCard tag="Tier 2" tone="info" title="would_own">
-            Names it&apos;s genuinely fine to get assigned via a cash-secured put.
-          </FactCard>
-          <FactCard tag="Tier 3" tone="positive" title="actively_wheeling">
-            The core subset of would_own, checked on every single 15-minute cycle.
-          </FactCard>
-        </div>
-        <p className="mt-3 text-muted">
-          Everything else in would_own is &quot;dip-watch&quot;: only pulled in after a real price
-          drop, so the system isn&apos;t re-checking option chains on names that haven&apos;t
-          moved.
-        </p>
-      </section>
-
-      <section>
-        <h3 className="font-mono text-sm text-content">Refreshing, every 15 minutes</h3>
-        <div className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-md border border-border bg-border sm:grid-cols-4">
-          {[
-            { n: "0.5%", l: "move re-fetches actively_wheeling" },
-            { n: "2%", l: "rally re-fetches a held stock" },
-            { n: "3%", l: "drop re-fetches dip-watch" },
-            { n: "120m", l: "staleness safety-net refresh" },
-          ].map((s) => (
-            <div key={s.l} className="bg-surface p-3">
-              <div className="font-mono text-lg text-focus">{s.n}</div>
-              <div className="mt-1 text-[11px] leading-snug text-muted">{s.l}</div>
-            </div>
-          ))}
-        </div>
-        <p className="mt-3 text-muted">
-          IBKR caps concurrent market-data lines at roughly 100, so fetching every chain every
-          cycle simply isn&apos;t an option - each symbol is re-fetched only when something about
-          it actually changed enough to matter.
-        </p>
-      </section>
-
-      <Callout label="The research bench, in one pass" tone="info">
-        For every name under consideration: is implied volatility rich right now relative to its
-        own history (IV rank, and the IV-vs-realized-vol gap)? Is the stock trending or choppy
-        (technicals)? Are the company&apos;s finances sound (fundamentals)? Can you actually get a
-        fair fill (liquidity)? What&apos;s the crowd&apos;s mood, and what&apos;s the broad market
-        doing (sentiment, macro)? None of this decides anything by itself - it&apos;s all read by
-        the next stage.
-      </Callout>
-    </PanelShell>
-  );
-}
diff --git a/web/components/explain/ExecutionPanel.tsx b/web/components/explain/ExecutionPanel.tsx
deleted file mode 100644
index ba0eebc..0000000
--- a/web/components/explain/ExecutionPanel.tsx
+++ /dev/null
@@ -1,108 +0,0 @@
-"use client";
-
-import { Callout } from "./Callout";
-import { PanelShell } from "./PanelShell";
-import type { TabKey } from "./types";
-
-const RUNGS: { name: string; pct: number; note: string }[] = [
-  { name: "OBSERVE", pct: 25, note: "proposals only, no buttons - the default" },
-  { name: "MANUAL", pct: 50, note: "every trade needs a tap" },
-  { name: "WHITELIST", pct: 75, note: "trusted symbols auto-execute, the rest still need a tap" },
-  { name: "FULL", pct: 100, note: "anything that clears the rulebook auto-executes" },
-];
-
-export function ExecutionPanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
-  return (
-    <PanelShell
-      tab="execution"
-      title="Approval & execution"
-      dek="How much happens automatically is a dial that only turns up once the account has earned it. Whatever the setting, the order that finally goes out is a limit order, re-checked one last time."
-      onNavigate={onNavigate}
-      ties={[
-        {
-          tab: "claude",
-          reason: "its note is what you read alongside the Approve/Reject buttons.",
-        },
-        {
-          tab: "gate",
-          reason: "re-runs the exact same rulebook against a live quote right before transmitting.",
-        },
-        {
-          tab: "watching",
-          reason: "the moment an order fills, the intraday monitor picks the position up.",
-        },
-        {
-          tab: "web",
-          reason: "this dashboard's Approve/Reject controls drain through this identical code path, not a shortcut.",
-        },
-      ]}
-      files={[
-        { path: "src/notify/approval_service.py", note: "the Telegram daemon - buttons, commands, and the exec connection" },
-        { path: "src/execution/executor.py", note: "limit-at-mid order building, qualification, and the live re-gate" },
-        { path: "config/settings.yaml", note: "autonomy.rung, autonomy promotion thresholds, LIVE_TRADING" },
-      ]}
-    >
-      <section>
-        <h3 className="font-mono text-sm text-content">The autonomy ladder</h3>
-        <p className="mt-1 text-muted">
-          Approved candidates route to Telegram, split into topic threads so CSPs, covered calls,
-          buy-to-own ideas, and account snapshots each stay readable. Four rungs decide how much is
-          automatic - moving <em>up</em> requires the account to have actually demonstrated it
-          works (a minimum number of real fills, a fill-rate floor, at least one automatic
-          loss-reducing close having genuinely fired); moving down is instant, always.
-        </p>
-        <div className="mt-3 flex flex-col gap-2.5 rounded-md border border-border bg-surface p-4">
-          {RUNGS.map((r) => (
-            <div key={r.name} className="flex items-center gap-3">
-              <div className="w-24 shrink-0 font-mono text-xs text-content">{r.name}</div>
-              <div className="h-2.5 flex-1 rounded-full bg-elevated">
-                <div
-                  className="h-full rounded-full bg-focus"
-                  style={{ width: `${r.pct}%` }}
-                  aria-hidden="true"
-                />
-              </div>
-              <div className="hidden w-72 shrink-0 text-xs text-muted sm:block">{r.note}</div>
-            </div>
-          ))}
-          <p className="mt-1 text-xs text-muted sm:hidden">
-            {RUNGS.map((r) => `${r.name}: ${r.note}`).join(". ")}
-          </p>
-        </div>
-      </section>
-
-      <Callout label="Paper-only shortcut, and the live backstop" tone="caution">
-        On the paper account an operator can skip the evidence requirement
-        (<code className="font-mono">automation.paper_skip_promotion_gate</code>) to watch the top
-        rung work end to end. The switch is ignored whenever live trading is on, and only live
-        fills count as evidence for a live account. When the trading service starts in live mode
-        with a rung it has not earned with live fills, it drops itself back to manual and says so
-        on Telegram.
-      </Callout>
-
-      <Callout label="A separate switch, not gated by the ladder" tone="positive">
-        Automatically closing a losing or winning position is independent of the autonomy rung - it
-        runs regardless of setting, because reducing risk should never have to wait for a human to
-        be free to check their phone.
-      </Callout>
-
-      <section>
-        <h3 className="font-mono text-sm text-content">Placing the order</h3>
-        <p className="mt-1 text-muted">
-          The executor builds a <strong className="text-focus">limit order at the mid-price</strong>{" "}
-          - never a market order - rounds it to the correct tick, qualifies the contract with IBKR,
-          and re-checks it against the rulebook one final time with a live quote before sending. In
-          live mode a second, explicit confirmation tap is required per order. Rolls transmit as a
-          single atomic two-leg combo (close the old option, open the new one, together), so there
-          is never a moment of holding neither leg or both.
-        </p>
-      </section>
-
-      <Callout label="Paper by default" tone="positive">
-        Live orders are blocked unless <code className="font-mono">LIVE_TRADING=true</code> is
-        explicitly set and the account is pointed at the live port, with a loud on-screen banner
-        either way.
-      </Callout>
-    </PanelShell>
-  );
-}
diff --git a/web/components/explain/ExplainShell.test.tsx b/web/components/explain/ExplainShell.test.tsx
deleted file mode 100644
index dca8abb..0000000
--- a/web/components/explain/ExplainShell.test.tsx
+++ /dev/null
@@ -1,46 +0,0 @@
-import { fireEvent, render, screen } from "@testing-library/react";
-import { describe, expect, it } from "vitest";
-import { ExplainShell } from "./ExplainShell";
-
-describe("ExplainShell", () => {
-  it("opens on the Overview panel", () => {
-    render(<ExplainShell />);
-    expect(screen.getByRole("heading", { name: "The system, in one pass" })).toBeDefined();
-  });
-
-  it("switches panels via the tab bar", () => {
-    render(<ExplainShell />);
-    fireEvent.click(screen.getByRole("button", { name: "Gate" }));
-    expect(screen.getByRole("heading", { name: "The risk gate" })).toBeDefined();
-    expect(screen.queryByRole("heading", { name: "The system, in one pass" })).toBeNull();
-  });
-
-  it("marks the active tab bar entry with aria-current", () => {
-    render(<ExplainShell />);
-    fireEvent.click(screen.getByRole("button", { name: "Claude" }));
-    expect(screen.getByRole("button", { name: "Claude" }).getAttribute("aria-current")).toBe(
-      "page",
-    );
-  });
-
-  it("navigates from an overview card straight into that panel", () => {
-    render(<ExplainShell />);
-    // The overview grid renders a card per subtab using the full label; "The Risk Gate"
-    // card is distinct from the "Gate" tab-bar button and the pipeline-map box, so this
-    // exercises the onNavigate prop threading through OverviewPanel rather than the tab bar.
-    fireEvent.click(screen.getAllByRole("button", { name: "The Risk Gate" })[0]);
-    expect(screen.getByRole("heading", { name: "The risk gate" })).toBeDefined();
-  });
-
-  it("navigates via a ties-into chip on a subtab", () => {
-    render(<ExplainShell />);
-    fireEvent.click(screen.getByRole("button", { name: "Gate" }));
-    // GatePanel ties into "execution" — click that chip and land on the execution panel.
-    const executionTie = screen
-      .getAllByRole("button")
-      .find((el) => el.textContent?.includes("Approval & Execution") && el.textContent?.includes("live quote"));
-    expect(executionTie).toBeDefined();
-    fireEvent.click(executionTie!);
-    expect(screen.getByRole("heading", { name: "Approval & execution" })).toBeDefined();
-  });
-});
diff --git a/web/components/explain/ExplainShell.tsx b/web/components/explain/ExplainShell.tsx
deleted file mode 100644
index 2315a56..0000000
--- a/web/components/explain/ExplainShell.tsx
+++ /dev/null
@@ -1,69 +0,0 @@
-"use client";
-
-import { useState } from "react";
-import { ClaudePanel } from "./ClaudePanel";
-import { DataPanel } from "./DataPanel";
-import { ExecutionPanel } from "./ExecutionPanel";
-import { GatePanel } from "./GatePanel";
-import { IdeasPanel } from "./IdeasPanel";
-import { OverviewPanel } from "./OverviewPanel";
-import { TAB_META, TAB_ORDER } from "./types";
-import type { TabKey } from "./types";
-import { WatchingPanel } from "./WatchingPanel";
-import { WebLayerPanel } from "./WebLayerPanel";
-
-/**
- * The System Explanation page frame. Plain useState tab switching - no react-query anywhere on this page, because every panel is
- * static content describing how the system works rather than a live view of it. Matches
- * the rest of the app's tab-bar convention (border-b-2 on the active tab) so this console
- * feels like one product rather than a bolted-on docs page.
- */
-export function ExplainShell() {
-  const [tab, setTab] = useState<TabKey>("overview");
-
-  const panelProps = { onNavigate: setTab };
-
-  return (
-    <div className="px-8 py-6">
-      <header className="mb-6">
-        <h1 className="font-mono text-2xl text-content">System Explanation</h1>
-        <p className="mt-1 text-sm text-muted">
-          How the whole options-income system actually works, in plain English - one subtab per
-          stage, each showing where it sits in the larger pipeline and how it depends on the
-          others. Nothing on this page is live data; for that, see Options, Portfolio, and P&amp;L.
-        </p>
-      </header>
-
-      <nav
-        className="mb-6 flex flex-wrap gap-1 border-b border-border"
-        aria-label="System Explanation sections"
-      >
-        {TAB_ORDER.map((key) => (
-          <button
-            key={key}
-            type="button"
-            onClick={() => setTab(key)}
-            className={
-              "border-b-2 px-3 py-2 text-sm transition-colors " +
-              (tab === key
-                ? "border-focus text-content"
-                : "border-transparent text-muted hover:text-content")
-            }
-            aria-current={tab === key ? "page" : undefined}
-          >
-            {TAB_META[key].short}
-          </button>
-        ))}
-      </nav>
-
-      {tab === "overview" && <OverviewPanel {...panelProps} />}
-      {tab === "data" && <DataPanel {...panelProps} />}
-      {tab === "ideas" && <IdeasPanel {...panelProps} />}
-      {tab === "gate" && <GatePanel {...panelProps} />}
-      {tab === "claude" && <ClaudePanel {...panelProps} />}
-      {tab === "execution" && <ExecutionPanel {...panelProps} />}
-      {tab === "watching" && <WatchingPanel {...panelProps} />}
-      {tab === "web" && <WebLayerPanel {...panelProps} />}
-    </div>
-  );
-}
diff --git a/web/components/explain/FactCard.test.tsx b/web/components/explain/FactCard.test.tsx
deleted file mode 100644
index c25f8f9..0000000
--- a/web/components/explain/FactCard.test.tsx
+++ /dev/null
@@ -1,16 +0,0 @@
-import { render, screen } from "@testing-library/react";
-import { describe, expect, it } from "vitest";
-import { FactCard } from "./FactCard";
-
-describe("FactCard", () => {
-  it("renders the tag, title, and body", () => {
-    render(
-      <FactCard tag="Feasibility" tone="info" title="Cash reserve comes off first">
-        20% of available cash.
-      </FactCard>,
-    );
-    expect(screen.getByText("Feasibility")).toBeDefined();
-    expect(screen.getByText("Cash reserve comes off first")).toBeDefined();
-    expect(screen.getByText("20% of available cash.")).toBeDefined();
-  });
-});
diff --git a/web/components/explain/FactCard.tsx b/web/components/explain/FactCard.tsx
deleted file mode 100644
index 6c535f8..0000000
--- a/web/components/explain/FactCard.tsx
+++ /dev/null
@@ -1,39 +0,0 @@
-import type { ReactNode } from "react";
-import { Tag } from "./Tag";
-
-type Tone = "info" | "positive" | "caution" | "neutral";
-
-/**
- * One bordered, elevated-on-hover box for a single fact inside a grid - the "cards and
- * boxes" unit every explain panel now builds its structural content from, instead of a
- * run of plain paragraphs. A card is for one scannable idea; a paragraph is still the
- * right tool for connective narrative, so panels mix both rather than forcing everything
- * into a box.
- *
- * `bodyClass` overrides the body's default caption-weight styling (`text-xs text-muted`)
- * for callers whose content is substantive rather than incidental - e.g. options/
- * ReviewPanel reuses this shell for Claude's actual review text, which needs to read at
- * the same weight the original plain-paragraph version did (`text-sm text-content`), not
- * as a footnote.
- */
-export function FactCard({
-  tag,
-  tone = "neutral",
-  title,
-  bodyClass,
-  children,
-}: {
-  tag: string;
-  tone?: Tone;
-  title: string;
-  bodyClass?: string;
-  children: ReactNode;
-}) {
-  return (
-    <div className="rounded-md border border-border bg-surface p-4">
-      <Tag tone={tone}>{tag}</Tag>
-      <div className="mt-1.5 font-mono text-sm text-content">{title}</div>
-      <p className={`mt-1.5 leading-relaxed ${bodyClass ?? "text-xs text-muted"}`}>{children}</p>
-    </div>
-  );
-}
diff --git a/web/components/explain/GatePanel.tsx b/web/components/explain/GatePanel.tsx
deleted file mode 100644
index aef719e..0000000
--- a/web/components/explain/GatePanel.tsx
+++ /dev/null
@@ -1,120 +0,0 @@
-"use client";
-
-import { Callout } from "./Callout";
-import { FactCard } from "./FactCard";
-import { PanelShell } from "./PanelShell";
-import { RangeBar } from "./RangeBar";
-import type { TabKey } from "./types";
-
-export function GatePanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
-  return (
-    <PanelShell
-      tab="gate"
-      title="The risk gate"
-      dek="The compliance officer that can't be talked out of anything - not even by Claude. Pure, deterministic Python, and the only path to an order."
-      onNavigate={onNavigate}
-      ties={[
-        {
-          tab: "ideas",
-          reason: "every ranked candidate arrives here before anything else sees it.",
-        },
-        {
-          tab: "claude",
-          reason: "only what survives this gate is ever shown to the model - it never reviews a rejected candidate.",
-        },
-        {
-          tab: "execution",
-          reason: "the exact same checks run a second time, against a fresh live quote, right before the order is sent.",
-        },
-      ]}
-      files={[
-        { path: "src/engine/risk_engine.py", note: "the gate itself - two passes, zero LLM calls" },
-        { path: "config/risk_limits.yaml", note: "every threshold below, tunable without a code change" },
-        { path: "src/storage/risk_verdicts.py", note: "the audit trail of every contract assessed and why" },
-      ]}
-    >
-      <Callout label="No AI involved, anywhere in this box" tone="positive">
-        <code className="font-mono">src/engine/risk_engine.py</code> is plain deterministic Python.
-        It has no code path that calls a language model, and nothing upstream of it - not Claude,
-        not a hallucinated number - can reach an order without passing through it.
-      </Callout>
-
-      <section>
-        <h3 className="font-mono text-sm text-content">Strike targeting, drawn to scale</h3>
-        <div className="mt-3 flex flex-col gap-3 rounded-md border border-border bg-surface p-4">
-          <RangeBar
-            label="CSP delta target"
-            lowPct={20}
-            highPct={35}
-            lowText="0.20"
-            highText="0.35"
-            scaleLeft="0.0 (deep OTM)"
-            scaleRight="1.0 (deep ITM)"
-          />
-          <RangeBar
-            label="CC delta target"
-            lowPct={20}
-            highPct={35}
-            lowText="0.20"
-            highText="0.35"
-            scaleLeft="0.0 (deep OTM)"
-            scaleRight="1.0 (deep ITM)"
-          />
-          <RangeBar
-            label="DTE window"
-            lowPct={12}
-            highPct={47}
-            lowText="7d"
-            highText="28d"
-            scaleLeft="0d"
-            scaleRight="60d"
-          />
-        </div>
-      </section>
-
-      <section>
-        <h3 className="font-mono text-sm text-content">What it checks, cumulatively across the whole account</h3>
-        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
-          <FactCard tag="Feasibility" tone="info" title="Cash reserve comes off first">
-            20% of available cash, or a fixed floor, whichever is larger - puts may only use what
-            remains.
-          </FactCard>
-          <FactCard tag="Concentration" tone="info" title="Measured in risk units, not dollars">
-            collateral x IV x sqrt(days-to-expiry / 365) - a calm $65k position and a wild $15k one
-            are compared fairly. Per-ticker and per-sector caps apply.
-          </FactCard>
-          <FactCard tag="Deliberateness" tone="info" title="Two large-position slots">
-            At most two names at a time may exceed the standard per-ticker cap, so a deliberate
-            big bet is possible without the whole book drifting oversized.
-          </FactCard>
-          <FactCard tag="The real floor" tone="positive" title="The income gate">
-            The credit must beat the option&apos;s Black-Scholes fair value (at realized vol) by a
-            required edge. Return-on-capital and annualized-yield minimums exist only as a noise
-            filter underneath it.
-          </FactCard>
-          <FactCard tag="Timing" tone="caution" title="Earnings blackout">
-            No new short premium within a configured number of days of the next earnings date.
-          </FactCard>
-          <FactCard tag="Richness" tone="info" title="IV-rank & IV/realized-vol floors">
-            Sell only when implied volatility is high relative to its own history and rich versus
-            what the stock has actually been doing.
-          </FactCard>
-        </div>
-      </section>
-
-      <Callout label="Checked twice" tone="info">
-        Once when the candidate is ranked, and again immediately before the order transmits,
-        against a fresh live quote - so a price that drifted between the scan and the send
-        can&apos;t slip a trade through on a stale number.
-      </Callout>
-
-      <FactCard tag="Audit trail" tone="neutral" title="Nothing vanishes silently">
-        Every contract this gate looks at - pass or reject, and why - is written to an audit table.
-        A rejection is never just &quot;no&quot;; it&apos;s a specific reason (IV rank too low, delta
-        outside the band, concentration cap hit, a better strike on the same name already took the
-        shared budget, and so on), which is what makes it possible to answer &quot;why didn&apos;t
-        this trade get proposed&quot; after the fact.
-      </FactCard>
-    </PanelShell>
-  );
-}
diff --git a/web/components/explain/IdeasPanel.tsx b/web/components/explain/IdeasPanel.tsx
deleted file mode 100644
index f54b88b..0000000
--- a/web/components/explain/IdeasPanel.tsx
+++ /dev/null
@@ -1,78 +0,0 @@
-"use client";
-
-import { Callout } from "./Callout";
-import { FactCard } from "./FactCard";
-import { PanelShell } from "./PanelShell";
-import type { TabKey } from "./types";
-
-export function IdeasPanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
-  return (
-    <PanelShell
-      tab="ideas"
-      title="Finding trades"
-      dek="Writing a fair price for itself first, then turning research into concrete, priced candidates, then ranking them."
-      onNavigate={onNavigate}
-      ties={[
-        {
-          tab: "data",
-          reason: "every candidate here is built from the IV, technicals, and liquidity numbers gathered upstream.",
-        },
-        {
-          tab: "gate",
-          reason: "nothing decided here is binding - every ranked candidate still has to clear the rulebook next.",
-        },
-      ]}
-      files={[
-        { path: "src/analytics/fair_value.py", note: "the ideal strike band and the minimum-credit fair-value floor" },
-        { path: "src/strategies/", note: "the covered-call, CSP, roll, and buy-to-own generators" },
-        { path: "src/engine/scoring.py", note: "the blended 0-100 score and rank" },
-      ]}
-    >
-      <Callout label="The price tag it writes for itself" tone="info">
-        Before shopping: an expected move (spot price x implied volatility x the square root of
-        time), an ideal strike band inside it, and a minimum credit - the option&apos;s fair value
-        at realized volatility, plus a required edge on top. &quot;A put around here, for at least
-        this much, is a fair deal - anything cheaper isn&apos;t worth the risk.&quot; Every contract
-        actually offered gets compared against that tag.
-      </Callout>
-
-      <section>
-        <h3 className="font-mono text-sm text-content">Four generators</h3>
-        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
-          <FactCard tag="On stock you own" tone="positive" title="Covered calls">
-            Find the best strike/expiry to sell against shares already held.
-          </FactCard>
-          <FactCard tag="On stock you'd own" tone="info" title="Cash-secured puts">
-            Strikes that pay well without excessive assignment risk, sized to the room the account
-            actually has left - never the theoretical max lot.
-          </FactCard>
-          <FactCard tag="On a challenged short" tone="caution" title="Rolls">
-            For existing short options nearing expiry or drifting in-the-money, propose the best
-            replacement trade.
-          </FactCard>
-          <FactCard tag="Before you own it" tone="neutral" title="Buy-to-own">
-            Stocks worth buying specifically so calls can be written against them later, filtered
-            to only the strongest handful.
-          </FactCard>
-        </div>
-        <p className="mt-3 text-muted">
-          Every generator keeps a record of contracts it considered and rejected, tagged with every
-          reason it failed - a quiet scan still shows its work.
-        </p>
-      </section>
-
-      <FactCard tag="Ranking" tone="neutral" title="Scoring, 0-100">
-        Each candidate gets normalized scores across IV rank, technicals, fundamentals, liquidity,
-        and sentiment, blended by configurable weights into one number. Anything below a minimum
-        score floor, or that loses to a better strike on the same name, is dropped - and why is
-        recorded rather than silently disappearing.
-      </FactCard>
-
-      <p className="text-xs text-muted">
-        A separate, standalone backtester replays these same strategies over historical prices,
-        isolated from everything live - it answers &quot;how would this have done historically,&quot;
-        not &quot;should I trade now.&quot;
-      </p>
-    </PanelShell>
-  );
-}
diff --git a/web/components/explain/OverviewPanel.tsx b/web/components/explain/OverviewPanel.tsx
deleted file mode 100644
index 3bdefb5..0000000
--- a/web/components/explain/OverviewPanel.tsx
+++ /dev/null
@@ -1,107 +0,0 @@
-"use client";
-
-import { PanelShell } from "./PanelShell";
-import { Callout } from "./Callout";
-import { Tag } from "./Tag";
-import type { TabKey } from "./types";
-import { TAB_META } from "./types";
-
-const CARDS: { tab: TabKey; tag: string; tone: "info" | "positive" | "caution" | "neutral"; blurb: string }[] = [
-  {
-    tab: "data",
-    tag: "Stage 1",
-    tone: "info",
-    blurb:
-      "What the system watches, how often it refreshes, and the research (IV, technicals, fundamentals, sentiment) run on every name.",
-  },
-  {
-    tab: "ideas",
-    tag: "Stage 2",
-    tone: "info",
-    blurb:
-      "Turning that research into priced, concrete trades - a fair price is computed first, then candidates are generated and ranked.",
-  },
-  {
-    tab: "gate",
-    tag: "Stage 3",
-    tone: "positive",
-    blurb:
-      "The one part with zero AI. Deterministic Python checks every candidate against hard limits, twice, before a cent moves.",
-  },
-  {
-    tab: "claude",
-    tag: "Stage 4",
-    tone: "info",
-    blurb:
-      "A language model writes a plain-English second opinion on gate survivors. Advisory only - it cannot open or block a trade.",
-  },
-  {
-    tab: "execution",
-    tag: "Stage 5",
-    tone: "info",
-    blurb:
-      "Telegram (or this dashboard) collects your approval, an autonomy ladder decides how much is automatic, and orders go to IBKR.",
-  },
-  {
-    tab: "watching",
-    tag: "The loop",
-    tone: "caution",
-    blurb:
-      "Once filled, an always-on monitor watches every position and can propose rolls or trigger automatic loss/profit exits.",
-  },
-  {
-    tab: "web",
-    tag: "Sits alongside",
-    tone: "neutral",
-    blurb:
-      "This console. Read-only over the trading database, plus one narrow write path that queues the same actions Telegram sends.",
-  },
-];
-
-export function OverviewPanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
-  return (
-    <PanelShell
-      tab="overview"
-      title="The system, in one pass"
-      dek="An options-income pipeline for one Interactive Brokers account: it watches a list of stocks, proposes covered calls and cash-secured puts, checks every one against a hard rulebook, gets a second opinion from a language model, and only ever trades once a human (or a rule-following autopilot) has said yes."
-      onNavigate={onNavigate}
-      ties={[]}
-      files={[
-        { path: "README.md", note: "the full plain-English walkthrough this tab is adapted from" },
-        { path: "ARCHITECTURE.md", note: "the technical reference, folder by folder" },
-        { path: "STATUS.md", note: "what's built, what's deliberately not, and known limitations" },
-      ]}
-    >
-      <p>
-        Read it as a straight line with one loop in it. Data comes in, ideas get generated and
-        priced, a deterministic rulebook decides what&apos;s even allowed, a language model adds
-        commentary, a human (or an earned autopilot) approves, and the order goes out. Once a
-        position is open, a separate always-on watcher takes over and can feed new candidates -
-        rolls, closes - back into that same rulebook. This dashboard sits beside the whole thing,
-        reading its trail and offering the same approve/reject buttons Telegram does.
-      </p>
-
-      <Callout label="The one rule that matters most" tone="positive">
-        The Rules Engine (deterministic Python, no AI) is the <em>only</em> path to an order. A
-        language model can write a recommendation; it can never place, resize, or wave through a
-        trade. If the model is down entirely, the system keeps trading the rule-approved list
-        without it.
-      </Callout>
-
-      <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
-        {CARDS.map((c) => (
-          <button
-            key={c.tab}
-            type="button"
-            onClick={() => onNavigate(c.tab)}
-            className="rounded-md border border-border bg-surface p-4 text-left transition-colors hover:border-focus/60"
-          >
-            <Tag tone={c.tone}>{c.tag}</Tag>
-            <div className="mt-1 font-mono text-sm text-content">{TAB_META[c.tab].label}</div>
-            <p className="mt-1 text-xs leading-relaxed text-muted">{c.blurb}</p>
-          </button>
-        ))}
-      </div>
-    </PanelShell>
-  );
-}
diff --git a/web/components/explain/PanelShell.tsx b/web/components/explain/PanelShell.tsx
deleted file mode 100644
index a30d98c..0000000
--- a/web/components/explain/PanelShell.tsx
+++ /dev/null
@@ -1,48 +0,0 @@
-import type { ReactNode } from "react";
-import { PipelineMap } from "./PipelineMap";
-import { SourceRefs } from "./SourceRefs";
-import { TiesInto } from "./TiesInto";
-import type { SourceRef, TabKey, TieIn } from "./types";
-
-/**
- * The one layout every subtab (bar Overview, which composes the map differently) shares:
- * the pipeline map with this tab lit up, a title and one-line dek, freeform content, then
- * the ties-into chips and the source-file bridge. Keeping this in one place is what makes
- * "every subtab shows how it connects to the others" true by construction rather than by
- * each panel remembering to add it.
- */
-export function PanelShell({
-  tab,
-  title,
-  dek,
-  onNavigate,
-  children,
-  ties,
-  files,
-}: {
-  tab: TabKey;
-  title: string;
-  dek: string;
-  onNavigate: (tab: TabKey) => void;
-  children: ReactNode;
-  ties: TieIn[];
-  files: SourceRef[];
-}) {
-  return (
-    <div>
-      <PipelineMap active={tab} onNavigate={onNavigate} />
-
-      <header className="mt-6">
-        <h2 className="font-mono text-xl text-content">{title}</h2>
-        <p className="mt-1 text-sm text-muted">{dek}</p>
-      </header>
-
-      <div className="mt-5 flex flex-col gap-4 text-sm leading-relaxed text-content">
-        {children}
-      </div>
-
-      <TiesInto items={ties} onNavigate={onNavigate} />
-      <SourceRefs files={files} />
-    </div>
-  );
-}
diff --git a/web/components/explain/PipelineMap.test.tsx b/web/components/explain/PipelineMap.test.tsx
deleted file mode 100644
index 3bb174b..0000000
--- a/web/components/explain/PipelineMap.test.tsx
+++ /dev/null
@@ -1,42 +0,0 @@
-import { fireEvent, render, screen } from "@testing-library/react";
-import { describe, expect, it, vi } from "vitest";
-import { PipelineMap } from "./PipelineMap";
-
-describe("PipelineMap", () => {
-  it("renders every main-pipeline stage plus the watching and web side nodes", () => {
-    render(<PipelineMap active={null} onNavigate={() => {}} />);
-    for (const label of [
-      "Data In",
-      "Finding Trades",
-      "The Risk Gate",
-      "Claude's Role",
-      "Approval & Execution",
-      "Watching & Adjusting",
-      "This Dashboard",
-    ]) {
-      expect(screen.getByRole("button", { name: label })).toBeDefined();
-    }
-  });
-
-  it("marks the active stage with aria-current", () => {
-    render(<PipelineMap active="gate" onNavigate={() => {}} />);
-    const gateBtn = screen.getByRole("button", { name: "The Risk Gate" });
-    expect(gateBtn.getAttribute("aria-current")).toBe("step");
-    const dataBtn = screen.getByRole("button", { name: "Data In" });
-    expect(dataBtn.getAttribute("aria-current")).toBeNull();
-  });
-
-  it("calls onNavigate with the clicked stage's key", () => {
-    const onNavigate = vi.fn();
-    render(<PipelineMap active={null} onNavigate={onNavigate} />);
-    fireEvent.click(screen.getByRole("button", { name: "Claude's Role" }));
-    expect(onNavigate).toHaveBeenCalledWith("claude");
-  });
-
-  it("navigating to the web side node passes its key too", () => {
-    const onNavigate = vi.fn();
-    render(<PipelineMap active={null} onNavigate={onNavigate} />);
-    fireEvent.click(screen.getByRole("button", { name: "This Dashboard" }));
-    expect(onNavigate).toHaveBeenCalledWith("web");
-  });
-});
diff --git a/web/components/explain/PipelineMap.tsx b/web/components/explain/PipelineMap.tsx
deleted file mode 100644
index 766ac25..0000000
--- a/web/components/explain/PipelineMap.tsx
+++ /dev/null
@@ -1,87 +0,0 @@
-"use client";
-
-import clsx from "clsx";
-import type { TabKey } from "./types";
-import { TAB_META } from "./types";
-
-const MAIN_STAGES: TabKey[] = ["data", "ideas", "gate", "claude", "execution"];
-
-function StageBox({
-  tab,
-  active,
-  onNavigate,
-  variant = "main",
-}: {
-  tab: TabKey;
-  active: boolean;
-  onNavigate: (tab: TabKey) => void;
-  variant?: "main" | "side";
-}) {
-  return (
-    <button
-      type="button"
-      onClick={() => onNavigate(tab)}
-      aria-current={active ? "step" : undefined}
-      className={clsx(
-        "rounded-md border px-3 py-2 text-left text-sm transition-colors",
-        variant === "main" ? "min-w-[108px]" : "min-w-[140px]",
-        active
-          ? "border-focus bg-elevated text-content"
-          : "border-border bg-surface text-muted hover:border-focus/60 hover:text-content",
-      )}
-    >
-      {TAB_META[tab].label}
-    </button>
-  );
-}
-
-function Arrow() {
-  return (
-    <span aria-hidden="true" className="px-1 text-muted">
-      &rarr;
-    </span>
-  );
-}
-
-/**
- * The "you are here" map every System Explanation subtab mounts at the top of its panel.
- * It is the one piece of UI that makes the tie-between-tabs concrete: the same five-box
- * chain renders on every subtab with that subtab's own box highlighted, plus the two
- * pieces that sit outside the straight-line pipeline - the monitor loop that feeds rolls
- * back into the gate, and this dashboard, which only ever reads the trail the pipeline
- * leaves behind and queues commands into the same approval flow Telegram uses.
- *
- * Every box is a real nav control (onNavigate), not decoration - clicking anywhere on the
- * map jumps the shell to that subtab, so the map doubles as navigation.
- */
-export function PipelineMap({
-  active,
-  onNavigate,
-}: {
-  active: TabKey | null;
-  onNavigate: (tab: TabKey) => void;
-}) {
-  return (
-    <div className="rounded-lg border border-border bg-surface p-4">
-      <div className="flex flex-wrap items-center gap-1">
-        {MAIN_STAGES.map((tab, i) => (
-          <span key={tab} className="flex items-center">
-            <StageBox tab={tab} active={active === tab} onNavigate={onNavigate} />
-            {i < MAIN_STAGES.length - 1 && <Arrow />}
-          </span>
-        ))}
-      </div>
-
-      <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-3 text-xs text-muted">
-        <span>once filled &darr;</span>
-        <StageBox tab="watching" active={active === "watching"} onNavigate={onNavigate} variant="side" />
-        <span>rolls &amp; closes re-enter the gate &#8635;</span>
-      </div>
-
-      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-muted">
-        <StageBox tab="web" active={active === "web"} onNavigate={onNavigate} variant="side" />
-        <span>reads the gate &amp; approval trail, writes commands into the same approval flow</span>
-      </div>
-    </div>
-  );
-}
diff --git a/web/components/explain/RangeBar.test.tsx b/web/components/explain/RangeBar.test.tsx
deleted file mode 100644
index c910722..0000000
--- a/web/components/explain/RangeBar.test.tsx
+++ /dev/null
@@ -1,41 +0,0 @@
-import { render, screen } from "@testing-library/react";
-import { describe, expect, it } from "vitest";
-import { RangeBar } from "./RangeBar";
-
-describe("RangeBar", () => {
-  it("renders its label, bounds, and scale endpoints", () => {
-    render(
-      <RangeBar
-        label="CSP delta target"
-        lowPct={15}
-        highPct={30}
-        lowText="0.15"
-        highText="0.30"
-        scaleLeft="0.0 (deep OTM)"
-        scaleRight="1.0 (deep ITM)"
-      />,
-    );
-    expect(screen.getByText("CSP delta target")).toBeDefined();
-    expect(screen.getByText("0.15")).toBeDefined();
-    expect(screen.getByText("0.30")).toBeDefined();
-    expect(screen.getByText("0.0 (deep OTM)")).toBeDefined();
-    expect(screen.getByText("1.0 (deep ITM)")).toBeDefined();
-  });
-
-  it("renders the filled range at the given bounds, not animated in", () => {
-    const { container } = render(
-      <RangeBar
-        label="DTE window"
-        lowPct={12}
-        highPct={47}
-        lowText="7d"
-        highText="28d"
-        scaleLeft="0d"
-        scaleRight="60d"
-      />,
-    );
-    const fill = container.querySelector(".border-focus") as HTMLElement;
-    expect(fill.style.left).toBe("12%");
-    expect(fill.style.right).toBe("53%");
-  });
-});
diff --git a/web/components/explain/RangeBar.tsx b/web/components/explain/RangeBar.tsx
deleted file mode 100644
index 5ec635b..0000000
--- a/web/components/explain/RangeBar.tsx
+++ /dev/null
@@ -1,61 +0,0 @@
-/**
- * A labelled range on a 0-100 scale, e.g. "CSP delta target: 0.15-0.30" drawn against
- * "0.0 (deep OTM) .. 1.0 (deep ITM)". Mirrors the artifact-report band bars this tab was
- * asked to match, rebuilt on this app's own tokens: the track is a raised surface
- * (elevation, not a colour choice), the filled range is bounded by the app's one accent
- * colour, and - since a bar's value is never allowed to animate in here - it renders at
- * its final width immediately. The bound labels sit above the track rather than inside
- * the fill, so a narrow band (a tight delta window) never has its own two numbers
- * colliding into each other.
- */
-export function RangeBar({
-  label,
-  lowPct,
-  highPct,
-  lowText,
-  highText,
-  scaleLeft,
-  scaleRight,
-}: {
-  label: string;
-  lowPct: number;
-  highPct: number;
-  lowText: string;
-  highText: string;
-  scaleLeft: string;
-  scaleRight: string;
-}) {
-  return (
-    <div>
-      <div className="flex items-center gap-3">
-        <div className="w-32 shrink-0 text-xs text-muted">{label}</div>
-        <div className="relative flex-1">
-          <div className="relative mb-4 h-4 font-mono text-[11px] text-focus">
-            <span
-              className="absolute -translate-x-1/2 whitespace-nowrap"
-              style={{ left: `${lowPct}%` }}
-            >
-              {lowText}
-            </span>
-            <span
-              className="absolute -translate-x-1/2 whitespace-nowrap"
-              style={{ left: `${highPct}%` }}
-            >
-              {highText}
-            </span>
-          </div>
-          <div className="relative h-2.5 rounded-full border border-border bg-elevated">
-            <div
-              className="absolute inset-y-0 rounded-full border-x-2 border-focus bg-focus/25"
-              style={{ left: `${lowPct}%`, right: `${100 - highPct}%` }}
-            />
-          </div>
-        </div>
-      </div>
-      <div className="ml-[8.75rem] mt-1 flex justify-between font-mono text-[10px] text-muted">
-        <span>{scaleLeft}</span>
-        <span>{scaleRight}</span>
-      </div>
-    </div>
-  );
-}
diff --git a/web/components/explain/SourceRefs.tsx b/web/components/explain/SourceRefs.tsx
deleted file mode 100644
index 6211714..0000000
--- a/web/components/explain/SourceRefs.tsx
+++ /dev/null
@@ -1,27 +0,0 @@
-import type { SourceRef } from "./types";
-
-/**
- * "Under the hood" - the bridge from the simplified explanation back to the real modules
- * and the exhaustive reference docs, for anyone who wants to go past the plain-English
- * version. Deliberately plain (a labelled list, not a diagram) - this is the one place on
- * each panel that is allowed to look like documentation rather than an explainer.
- */
-export function SourceRefs({ files }: { files: SourceRef[] }) {
-  if (files.length === 0) return null;
-
-  return (
-    <div className="mt-6 rounded-md border border-border bg-surface px-4 py-3">
-      <h3 className="mb-2 font-mono text-xs uppercase tracking-wide text-muted">
-        Under the hood
-      </h3>
-      <ul className="flex flex-col gap-1">
-        {files.map((f) => (
-          <li key={f.path} className="text-xs">
-            <code className="font-mono text-content">{f.path}</code>
-            <span className="text-muted"> &mdash; {f.note}</span>
-          </li>
-        ))}
-      </ul>
-    </div>
-  );
-}
diff --git a/web/components/explain/Tag.test.tsx b/web/components/explain/Tag.test.tsx
deleted file mode 100644
index 0430c05..0000000
--- a/web/components/explain/Tag.test.tsx
+++ /dev/null
@@ -1,20 +0,0 @@
-import { render, screen } from "@testing-library/react";
-import { describe, expect, it } from "vitest";
-import { Tag } from "./Tag";
-
-describe("Tag", () => {
-  it("renders its text", () => {
-    render(<Tag>Stage 1</Tag>);
-    expect(screen.getByText("Stage 1")).toBeDefined();
-  });
-
-  it("defaults to the neutral tone", () => {
-    render(<Tag>Neutral</Tag>);
-    expect(screen.getByText("Neutral").className).toContain("text-muted");
-  });
-
-  it("applies the tone's colour class", () => {
-    render(<Tag tone="positive">Safe</Tag>);
-    expect(screen.getByText("Safe").className).toContain("text-gain");
-  });
-});
diff --git a/web/components/explain/Tag.tsx b/web/components/explain/Tag.tsx
deleted file mode 100644
index bcb0193..0000000
--- a/web/components/explain/Tag.tsx
+++ /dev/null
@@ -1,19 +0,0 @@
-import clsx from "clsx";
-
-type Tone = "info" | "positive" | "caution" | "neutral";
-
-const TONE_CLASS: Record<Tone, string> = {
-  info: "text-focus",
-  positive: "text-gain",
-  caution: "text-unknown",
-  neutral: "text-muted",
-};
-
-/** The small uppercase mono eyebrow on a <FactCard/> - a card's category at a glance. */
-export function Tag({ tone = "neutral", children }: { tone?: Tone; children: string }) {
-  return (
-    <div className={clsx("font-mono text-[11px] font-medium uppercase tracking-wide", TONE_CLASS[tone])}>
-      {children}
-    </div>
-  );
-}
diff --git a/web/components/explain/TiesInto.test.tsx b/web/components/explain/TiesInto.test.tsx
deleted file mode 100644
index ae63828..0000000
--- a/web/components/explain/TiesInto.test.tsx
+++ /dev/null
@@ -1,33 +0,0 @@
-import { fireEvent, render, screen } from "@testing-library/react";
-import { describe, expect, it, vi } from "vitest";
-import { TiesInto } from "./TiesInto";
-
-describe("TiesInto", () => {
-  it("renders nothing when there are no ties", () => {
-    const { container } = render(<TiesInto items={[]} onNavigate={() => {}} />);
-    expect(container.firstChild).toBeNull();
-  });
-
-  it("renders a chip per tie with its label and reason", () => {
-    render(
-      <TiesInto
-        items={[{ tab: "gate", reason: "every candidate has to clear this next." }]}
-        onNavigate={() => {}}
-      />,
-    );
-    expect(screen.getByText("The Risk Gate")).toBeDefined();
-    expect(screen.getByText("every candidate has to clear this next.")).toBeDefined();
-  });
-
-  it("navigates to the tied tab on click", () => {
-    const onNavigate = vi.fn();
-    render(
-      <TiesInto
-        items={[{ tab: "claude", reason: "gets the read-only research too." }]}
-        onNavigate={onNavigate}
-      />,
-    );
-    fireEvent.click(screen.getByRole("button"));
-    expect(onNavigate).toHaveBeenCalledWith("claude");
-  });
-});
diff --git a/web/components/explain/TiesInto.tsx b/web/components/explain/TiesInto.tsx
deleted file mode 100644
index fda8931..0000000
--- a/web/components/explain/TiesInto.tsx
+++ /dev/null
@@ -1,41 +0,0 @@
-"use client";
-
-import type { TieIn } from "./types";
-import { TAB_META } from "./types";
-
-/**
- * "How this ties into the rest of the system" - a short, reasoned link to each related
- * subtab, not just a label. Every panel ends with one of these so the tab never reads as
- * an island; clicking a chip jumps the shell straight there.
- */
-export function TiesInto({
-  items,
-  onNavigate,
-}: {
-  items: TieIn[];
-  onNavigate: (tab: TieIn["tab"]) => void;
-}) {
-  if (items.length === 0) return null;
-
-  return (
-    <div className="mt-8 border-t border-border pt-5">
-      <h3 className="mb-3 font-mono text-xs uppercase tracking-wide text-muted">
-        Ties into
-      </h3>
-      <ul className="flex flex-col gap-2">
-        {items.map((item) => (
-          <li key={item.tab}>
-            <button
-              type="button"
-              onClick={() => onNavigate(item.tab)}
-              className="flex w-full flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-md border border-border bg-surface px-3 py-2 text-left text-sm text-muted transition-colors hover:border-focus/60 hover:text-content"
-            >
-              <span className="font-medium text-content">{TAB_META[item.tab].label}</span>
-              <span>{item.reason}</span>
-            </button>
-          </li>
-        ))}
-      </ul>
-    </div>
-  );
-}
diff --git a/web/components/explain/WatchingPanel.tsx b/web/components/explain/WatchingPanel.tsx
deleted file mode 100644
index b7f3ed7..0000000
--- a/web/components/explain/WatchingPanel.tsx
+++ /dev/null
@@ -1,100 +0,0 @@
-"use client";
-
-import { Callout } from "./Callout";
-import { FactCard } from "./FactCard";
-import { PanelShell } from "./PanelShell";
-import type { TabKey } from "./types";
-
-const TRIGGERS = [
-  "Delta drift",
-  "7-day DTE threshold",
-  "21-DTE management point",
-  "IV spike",
-  "Ex-dividend assignment risk",
-  "General assignment risk",
-];
-
-export function WatchingPanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
-  return (
-    <PanelShell
-      tab="watching"
-      title="Watching & adjusting"
-      dek="Separate from the 15-minute scan, an always-on lookout watches every open position live and can propose a rescue, or close one automatically, well before it becomes urgent."
-      onNavigate={onNavigate}
-      ties={[
-        {
-          tab: "execution",
-          reason: "picks up every position the moment its order fills.",
-        },
-        {
-          tab: "gate",
-          reason: "a proposed roll is itself a new candidate - it must clear the rulebook again, under its own defensive-roll economics.",
-        },
-        {
-          tab: "ideas",
-          reason: "the wheel's adjusted cost basis feeds back into the covered-call strike gate.",
-        },
-      ]}
-      files={[
-        { path: "src/monitor/", note: "the event-driven intraday watcher (delta drift, DTE, IV spike, assignment risk)" },
-        { path: "src/strategies/rolling.py", note: "income-roll vs defensive-roll economics" },
-        { path: "src/execution/circuit_breakers.py", note: "daily-loss halt and drawdown halt" },
-      ]}
-    >
-      <section>
-        <h3 className="font-mono text-sm text-content">Six conditions, watched continuously</h3>
-        <div className="mt-3 flex flex-wrap gap-2">
-          {TRIGGERS.map((t) => (
-            <span
-              key={t}
-              className="rounded-full border border-focus/40 px-3 py-1 font-mono text-xs text-focus"
-            >
-              {t}
-            </span>
-          ))}
-        </div>
-        <p className="mt-3 text-muted">
-          Any trigger sends an alert explaining, in prose, what happened and why it matters - well
-          before the next 15-minute scan would have noticed.
-        </p>
-      </section>
-
-      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
-        <FactCard tag="Unchallenged" tone="positive" title="Income roll">
-          Just harvesting more premium - still has to clear the normal return-on-capital and yield
-          floors.
-        </FactCard>
-        <FactCard tag="Challenged" tone="caution" title="Defensive roll">
-          Rescuing a position that moved against you - allowed a small, bounded cost, as long as it
-          meaningfully reduces delta and improves the breakeven.
-        </FactCard>
-      </div>
-      <p className="text-xs text-muted">
-        Roll execution ships off by default; today rolls are alert-only until the mechanics are
-        verified on a live paper account, though approving one manually still works end to end.
-      </p>
-
-      <Callout label="The seatbelt" tone="positive">
-        A profit-take closes a short once 50% of its credit is captured; a loss-exit closes it once
-        the cost to buy back reaches 2x the original credit, by default. A daily-loss halt and a
-        drawdown halt can trip a persisted kill switch that stops all new order transmission -
-        closing existing risk is still always allowed.
-      </Callout>
-
-      <FactCard tag="Wheel" tone="info" title="One thread per symbol">
-        When a put gets assigned, the resulting stock position, any covered calls later sold against
-        it, subsequent rolls, and the eventual close are all linked into one campaign - tracking
-        cumulative premium collected and an adjusted cost basis (the assignment price minus premium
-        already banked per share), so a wheel that has already collected real premium can write
-        strikes below the raw assignment price without the system mistaking that for locking in a
-        loss.
-      </FactCard>
-
-      <p className="text-xs text-muted">
-        At 4:15pm ET, a scheduled job summarizes the day&apos;s premium cashflow, records
-        today&apos;s volatility for tomorrow&apos;s IV rank, reconciles the outcome ledger, and
-        snapshots positions so an overnight assignment is auto-detected the next morning.
-      </p>
-    </PanelShell>
-  );
-}
diff --git a/web/components/explain/WebLayerPanel.tsx b/web/components/explain/WebLayerPanel.tsx
deleted file mode 100644
index d4095d8..0000000
--- a/web/components/explain/WebLayerPanel.tsx
+++ /dev/null
@@ -1,86 +0,0 @@
-"use client";
-
-import { Callout } from "./Callout";
-import { PanelShell } from "./PanelShell";
-import type { TabKey } from "./types";
-
-const PROPOSABLE = [
-  "Approve / reject a pending trade",
-  "Promote an assessed candidate",
-  "Request a roll",
-  "Halt / resume the system",
-  "Change the autonomy rung",
-  "Edit the watchlist / would-own universe",
-];
-
-export function WebLayerPanel({ onNavigate }: { onNavigate: (tab: TabKey) => void }) {
-  return (
-    <PanelShell
-      tab="web"
-      title="This dashboard"
-      dek="A second window onto the same system Telegram already runs - not a second system. It reads everything, and writes through exactly one narrow door."
-      onNavigate={onNavigate}
-      ties={[
-        {
-          tab: "execution",
-          reason: "every Approve, Reject, Promote, or Roll button here queues a command that drains through the identical handler Telegram's buttons call.",
-        },
-        {
-          tab: "gate",
-          reason: "the Options console's Assessed tab shows the same pass/reject audit trail this tab describes in words.",
-        },
-      ]}
-      files={[
-        { path: "src/api/", note: "the FastAPI backend - its own process, no IBKR connection, no clientId" },
-        { path: "src/api/commands.py", note: "the one table (app_commands) this whole app is allowed to write" },
-        { path: "src/notify/command_drain.py", note: "reads pending commands and applies them via the same handlers Telegram uses" },
-      ]}
-    >
-      <p className="text-muted">
-        The web console you&apos;re looking at right now talks to a FastAPI backend (
-        <code className="font-mono">src/api/</code>) that runs as its own process, with no IBKR
-        connection and no clientId - it cannot reach the broker even if something in it were
-        compromised. It exists to give you a second, richer surface onto the exact same system
-        Telegram already runs, reachable over a private network rather than a phone.
-      </p>
-
-      <Callout label="Two database handles, on purpose" tone="positive">
-        Every read in this app - portfolio, P&amp;L, the risk-gate audit trail, approvals, orders,
-        fills - goes through a connection SQLite itself opens read-only; an accidental write raises
-        an error at the database layer, not by convention. A second, separate handle can write, and
-        only to one table: <code className="font-mono">app_commands</code>. Nothing else in this
-        codebase is allowed to import that write handle - a test enforces it.
-      </Callout>
-
-      <section>
-        <h3 className="font-mono text-sm text-content">Every click is a proposal, never a shortcut</h3>
-        <p className="mt-1 text-muted">
-          Clicking Approve here doesn&apos;t approve anything directly. It inserts a row into{" "}
-          <code className="font-mono">app_commands</code> with status <em>pending</em>. A background
-          loop inside the same process that holds the live IBKR connection - the Telegram bot&apos;s
-          process - picks that row up, usually within a couple of seconds, and applies it by calling
-          the exact same function Telegram&apos;s own Approve button calls.
-        </p>
-      </section>
-
-      <section>
-        <h3 className="font-mono text-sm text-content">What it can propose</h3>
-        <div className="mt-3 flex flex-wrap gap-2">
-          {PROPOSABLE.map((p) => (
-            <span
-              key={p}
-              className="rounded-full border border-focus/40 px-3 py-1 font-mono text-xs text-focus"
-            >
-              {p}
-            </span>
-          ))}
-        </div>
-        <p className="mt-3 text-muted">
-          Every one of those is a command the drain applies through the deterministic path described
-          in the other tabs - this console has no code path that gates, sizes, or sends an order on
-          its own.
-        </p>
-      </section>
-    </PanelShell>
-  );
-}
diff --git a/web/components/explain/panels.test.tsx b/web/components/explain/panels.test.tsx
deleted file mode 100644
index 3481be0..0000000
--- a/web/components/explain/panels.test.tsx
+++ /dev/null
@@ -1,40 +0,0 @@
-import { fireEvent, render, screen } from "@testing-library/react";
-import { describe, expect, it } from "vitest";
-import { ExplainShell } from "./ExplainShell";
-import { TAB_META } from "./types";
-
-// Every subtab's exact <h2> title, keyed by its tab-bar short label — walking the whole
-// shell this way catches a panel that fails to render, a title typo, or a tab that got
-// wired to the wrong panel, in one pass.
-const EXPECTED_HEADING: Record<string, string> = {
-  Overview: "The system, in one pass",
-  Data: "Data in",
-  Ideas: "Finding trades",
-  Gate: "The risk gate",
-  Claude: "Claude's role",
-  Approve: "Approval & execution",
-  Watching: "Watching & adjusting",
-  Dashboard: "This dashboard",
-};
-
-describe("every System Explanation subtab", () => {
-  it("covers every entry in TAB_META", () => {
-    const shortLabels = Object.values(TAB_META).map((m) => m.short);
-    expect(new Set(Object.keys(EXPECTED_HEADING))).toEqual(new Set(shortLabels));
-  });
-
-  for (const [short, heading] of Object.entries(EXPECTED_HEADING)) {
-    it(`renders the ${short} panel with its map, ties-into, and source refs`, () => {
-      render(<ExplainShell />);
-      fireEvent.click(screen.getByRole("button", { name: short }));
-
-      expect(screen.getByRole("heading", { name: heading })).toBeDefined();
-      // Every panel mounts the shared pipeline map (the "Finding Trades" box is present on
-      // every subtab, active or not).
-      expect(screen.getByRole("button", { name: "Finding Trades" })).toBeDefined();
-      // Every panel (Overview included, via its SourceRefs list) cites at least one real
-      // source file so "under the hood" never renders empty.
-      expect(screen.getByText("Under the hood")).toBeDefined();
-    });
-  }
-});
diff --git a/web/components/explain/types.ts b/web/components/explain/types.ts
deleted file mode 100644
index ea3959c..0000000
--- a/web/components/explain/types.ts
+++ /dev/null
@@ -1,42 +0,0 @@
-// Shared vocabulary for the System Explanation tab. One `TabKey` per subtab; `TAB_META`
-// gives every other component (the shell's tab bar, the pipeline map, the ties-into chips)
-// a single source of truth for labels so they can never drift out of sync with each other.
-
-export type TabKey =
-  | "overview"
-  | "data"
-  | "ideas"
-  | "gate"
-  | "claude"
-  | "execution"
-  | "watching"
-  | "web";
-
-export const TAB_META: Record<TabKey, { label: string; short: string }> = {
-  overview: { label: "Overview", short: "Overview" },
-  data: { label: "Data In", short: "Data" },
-  ideas: { label: "Finding Trades", short: "Ideas" },
-  gate: { label: "The Risk Gate", short: "Gate" },
-  claude: { label: "Claude's Role", short: "Claude" },
-  execution: { label: "Approval & Execution", short: "Approve" },
-  watching: { label: "Watching & Adjusting", short: "Watching" },
-  web: { label: "This Dashboard", short: "Dashboard" },
-};
-
-export const TAB_ORDER: TabKey[] = [
-  "overview",
-  "data",
-  "ideas",
-  "gate",
-  "claude",
-  "execution",
-  "watching",
-  "web",
-];
-
-export type TieIn = { tab: TabKey; reason: string };
-
-// A file path plus a one-line note on what lives there, rendered by <SourceRefs/> at the
-// foot of every panel — the bridge from "here's the simple version" back to the real code
-// and the exhaustive docs (ARCHITECTURE.md / STATUS.md), for whoever wants to go deeper.
-export type SourceRef = { path: string; note: string };
diff --git a/web/features/explain/ExplainPage.test.tsx b/web/features/explain/ExplainPage.test.tsx
index c926785..386d054 100644
--- a/web/features/explain/ExplainPage.test.tsx
+++ b/web/features/explain/ExplainPage.test.tsx
@@ -1,3 +1,4 @@
+import { existsSync } from "node:fs";
 import { render, screen } from "@testing-library/react";
 import { describe, expect, it } from "vitest";
 import { PAGES } from "@/features/search/pages";
@@ -42,6 +43,12 @@ describe("ExplainPage", () => {
     expect(text).not.toMatch(/seamless|robust|unlock|elevate/i);
   });
 
+  it("replaces the eight-tab explainer, which is gone, and the search list describes the new page", () => {
+    // vitest runs from web/, so this is web/components/explain.
+    expect(existsSync("components/explain")).toBe(false);
+    expect(PAGES.find((p) => p.href === "/explain")?.hint).toBe("The system in plain English");
+  });
+
   it("makes each link a 44px row on a phone", () => {
     render(<ExplainPage />);
     for (const link of screen.getAllByRole("link")) expect(link).toHaveClass("min-h-11", "md:min-h-0");
diff --git a/web/features/search/pages.ts b/web/features/search/pages.ts
index 65e74c1..fe78b0e 100644
--- a/web/features/search/pages.ts
+++ b/web/features/search/pages.ts
@@ -22,7 +22,7 @@ export const PAGES: PageHit[] = [
   { label: "Universe", href: "/research/universe", hint: "The names the scan covers", words: ["would own", "watchlist", "scan"] },
   { label: "News", href: "/news", hint: "Feed and calendar", words: ["headlines", "earnings", "calendar"] },
   { label: "What Claude knows", href: "/more/claude", hint: "The market picture and what each call reads", words: ["regime", "picture", "limits"] },
-  { label: "How it works", href: "/explain", hint: "The pipeline in plain English", words: ["explain", "help"] },
+  { label: "How it works", href: "/explain", hint: "The system in plain English", words: ["explain", "help"] },
   { label: "Import a statement", href: "/ledger/import", hint: "Upload an IBKR activity CSV", words: ["csv", "upload"] },
   { label: "More", href: "/more", hint: "Bot, theme, income target, system status", words: ["settings", "halt", "target", "theme"] },
 ];
````

## Section D: More and Open Decisions (Tasks 8-9) · model: sonnet (effort high)

**Reads:** this section; `web/app/more/page.tsx`; `web/components/ui/Button.tsx`; `web/DESIGN.md` "Open Decisions"
(read only; the patch edits it).

**Spec for da-vinci (Tasks 8 and 9; give it this):** Task 8: one more row in More's links card, after Universe:
"Value book" bold, "Its candidates lead Research; each name's file is on its stock page" muted 13px, the chevron;
nothing else on More moves. Task 9: a disabled quiet button keeps no fill and dims its ink to muted (History's,
Spreads' and Activity's end-of-range arrows); a disabled primary or secondary still drops to muted ink on sunk; the
favicon is an ink "I" on a sage-paper rounded square. No new token, colour, font, radius or elevation. Record "no
change" in each row.

**Entry checks:**

- [x] **D1. Section C landed.** In `<W>`: `git log --oneline main..HEAD` shows the seven task commits of Sections A-C;
  vitest **1620 in 153 files**; tsc and lint clean; G1 empty; G2 both greps; G7 the one layout line.
- [x] **D2. Both patches apply on the tree as it is** (their `DESIGN.md` hunks are disjoint): `git apply --check
  <S>/p7/T8.out` and `git apply --check <S>/p7/T9.out` each print nothing.
- [x] **D3. Starting shape.** `ls web/app/icon.svg` fails; `grep -c "disabled:bg-sunk" web/components/ui/Button.tsx`
  prints `1` (the base line); `grep -c "RESOLVED" web/DESIGN.md` prints `2`.

**Section exit:** two task commits; vitest **1622 in 153 files**; tsc, lint clean; G1, G2, G3, G4 (20 rows), G5 (the
Section C list plus `web/components/ui`), G6, G7; `git status --short` clean.

### Task 8: More

**Files:** Modify `web/app/more/page.tsx` (+ `page.test.tsx`), `web/DESIGN.md` (the More line in Components and the
More surface); this plan (Progress log).

**What it does (ruling 22):** a "Value book" row on More, and the More surface rewritten to say what the page holds
now (it named "the System Explanation pages").

- [x] **Step 1: Check and apply `T8`.** `git status --short` shows three ` M` files: `web/DESIGN.md`,
  `web/app/more/page.test.tsx`, `web/app/more/page.tsx`.
- [x] **Step 2: Red check.** `git stash push -- web/app/more/page.tsx`, then `cd web && npx vitest run app/more`
  ends `1 failed | 8 passed (9)`, then `git stash pop`.
- [x] **Step 3: Gate.** `npx vitest run app/more`: 9 passed. Full vitest **1621 in 153 files**; tsc, lint clean; G3
  exit 0.
- [x] **Step 4: Commit** `feat(web): More names the value book and says where it shows` with the Progress log row
  (and the Section D entry row).

<!-- block T8 -->
````diff
diff --git a/web/DESIGN.md b/web/DESIGN.md
index 45c2c62..04d2d47 100644
--- a/web/DESIGN.md
+++ b/web/DESIGN.md
@@ -460,7 +460,7 @@ the magnifier means search alone); the phone tab bar (64px, white, hairline abov
 holds Home, Trades, Portfolio, Activity and More, and marks More current on Research, Universe,
 stock and News pages, which a phone reaches through More.
 
-**More**: the bot card, the theme toggle (Light, Dark, Follow OS, on the strategy-switch track), the income target card, a Search row first in the links card (a phone has no rail and no shortcut), links to Research, Universe, News, Ledger, How it works, What Claude knows and statement import, system status, and Credits (the chart library's licence link).
+**More**: the bot card, the theme toggle (Light, Dark, Follow OS, on the strategy-switch track), the income target card, a Search row first in the links card (a phone has no rail and no shortcut), links to Research, Universe, the Value book (to Research, since the book has no page of its own), News, Ledger, How it works, What Claude knows and statement import, system status, and Credits (the chart library's licence link).
 
 **Regime and limits card** (What Claude knows): "Regime and limits", with when it was recorded at the right of the title. Per index (SPY, QQQ) a heading, the regime as a status word (flag amber above normal, neutral at normal), one plain line (the daily base, what raised it today, a bottoming-signal ease, or "Matches the daily base") and the CSP limits as figure lines under a perforation: Budget and Per trade as a percent of the normal limit, New puts a day ("No limit" or the count), Guaranteed lots a day. Up to three flag lines come first when they apply, each a flag word with one sentence beside it, in this order: "Off in config", "Suspended today" (`/regime off`, the limits shown are not applied) and "Cuts paused today" (today's circuit breaker has tripped: "The circuit breaker tripped, so Claude's size cuts are recorded but not applied until tomorrow"). Below the indices, the leveraged-ETF ceilings grouped by multiple ("3x (TQQQ, SOXL): 60% of the regime's size when calm, 30% when the name or its market is under stress") and Claude's size cuts as a sentence ("applied (paper)", "recorded only (live)"). When today's circuit breaker has tripped (Claude zeroed most of the day's auto puts) the cut sentence says so itself ("applied (paper), paused today.") so it is true when read alone, and the flag line above carries the state. The breaker is a flag word, not a plain sentence: it is the one state on the card besides `/regime off` that changes what happens today, so it joins that stack, in the first screen at phone width, instead of sitting below both indices. What the limits mean sits in a closed plain Disclosure. No regime yet: "No regime recorded yet" with a hatched n/a.
 
@@ -1157,7 +1157,7 @@ overhaul Part 5) on the Position page's frame.
   limits. It replaced the eight-tab System Explanation pages (2026-11-07).
 
 ### More
-Read and Operate. How it works (the System Explanation pages), What Claude knows (a link to its own surface), Bot controls, Theme, the monthly income target, Ledger import, Credits.
+Read and Operate. The bot card, Theme, the monthly income target, then one card of rows: Search, Research, Universe, the Value book (to Research: its candidates lead there, and each name's file is on its stock page; no page of its own), News, Ledger, How it works (the seven plain-English cards), What Claude knows, statement import; then system status and Credits.
 
 ### What Claude knows
 Read. Dials as the project default; the only thing that moves is a disclosure. Added 2026-10-22 for
diff --git a/web/app/more/page.test.tsx b/web/app/more/page.test.tsx
index 645830a..9d4ea4e 100644
--- a/web/app/more/page.test.tsx
+++ b/web/app/more/page.test.tsx
@@ -35,11 +35,18 @@ describe("More page", () => {
   it("links to the pages that have no tab on a phone", () => {
     renderWithQuery(<MorePage />, served);
     expect(screen.getByRole("link", { name: /How it works/ })).toHaveAttribute("href", "/explain");
-    expect(screen.getByRole("link", { name: /Research/ })).toHaveAttribute("href", "/research");
+    expect(screen.getByRole("link", { name: /^Research/ })).toHaveAttribute("href", "/research");
     expect(screen.getByRole("link", { name: /News/ })).toHaveAttribute("href", "/news");
     expect(screen.getByRole("link", { name: /Import a statement/ })).toHaveAttribute("href", "/ledger/import");
     expect(screen.getByRole("link", { name: /How it works/ })).toHaveTextContent("The system in plain English, and where to see it");
   });
+
+  it("names the value book, which has no page of its own, and says where it shows", () => {
+    renderWithQuery(<MorePage />, served);
+    const row = screen.getByRole("link", { name: /Value book/ });
+    expect(row).toHaveAttribute("href", "/research");
+    expect(row).toHaveTextContent("Its candidates lead Research; each name's file is on its stock page");
+  });
   it("offers Search first, for a phone, which has no rail and no shortcut", () => {
     renderWithQuery(<MorePage />, served);
     const seen = vi.fn();
diff --git a/web/app/more/page.tsx b/web/app/more/page.tsx
index a8bf230..c6f50f4 100644
--- a/web/app/more/page.tsx
+++ b/web/app/more/page.tsx
@@ -12,6 +12,9 @@ import { openSearch } from "@/lib/search";
 const LINKS = [
   { href: "/research", label: "Research", sub: "Search, watchlist, sectors, universe" },
   { href: "/research/universe", label: "Universe", sub: "The names the scan covers; edit would-own and watchlist" },
+  // The value book has no page of its own (HANDOFF ruling 4): its candidates lead Research, a held name's plan
+  // is on Home's Value card, and each name's file is on its stock page.
+  { href: "/research", label: "Value book", sub: "Its candidates lead Research; each name's file is on its stock page" },
   { href: "/news", label: "News", sub: "Feed, calendar and ticker briefs" },
   { href: "/activity?view=ledger", label: "Ledger", sub: "Broker trades and per-ticker roll-ups" },
   { href: "/explain", label: "How it works", sub: "The system in plain English, and where to see it" },
@@ -50,7 +53,7 @@ export default function MorePage() {
             </button>
           </li>
           {LINKS.map((l) => (
-            <li key={l.href} className="border-t border-border">
+            <li key={l.label} className="border-t border-border">
               <Link href={l.href} className="flex items-center justify-between gap-3 py-3">
                 <span>
                   <span className="block font-bold">{l.label}</span>
````

### Task 9: The Open Decisions

**Files:** Modify `web/components/ui/Button.tsx` (+ `primitives-a.test.tsx`), `web/DESIGN.md` (the Buttons rule, the
Open Decisions, a Decision Log entry); create `web/app/icon.svg`; this plan (Progress log).

**What it does (rulings 3, 23):** closes the six Open Decisions on their defaults; the only behaviour change is the
disabled quiet button, which stops drawing a filled circle.

- [x] **Step 1: Check and apply `T9`.** `git status --short` shows three ` M` files (`web/DESIGN.md`,
  `web/components/ui/Button.tsx`, `web/components/ui/primitives-a.test.tsx`) and `?? web/app/icon.svg`.
- [x] **Step 2: Red check.** `git stash push -- web/components/ui/Button.tsx`, then `cd web && npx vitest run
  components/ui/primitives-a.test.tsx` ends `1 failed | 11 passed (12)`, then `git stash pop`.
- [x] **Step 3: Gate.** `npx vitest run components/ui features/trades features/activity`: 28 files, 310 passed (the
  three users of a disabled quiet button). Full vitest **1622 in 153 files**; tsc, lint clean; G1, G2, G3, G4 (20
  rows: `next build` lists `app/icon.svg` as `○ /icon.svg`), G5 (with `web/components/ui`), G6, G7; `grep -c
  "RESOLVED" web/DESIGN.md` prints `8`.
- [x] **Step 4: Commit** `feat(web): close the design system's open decisions; a disabled quiet button only dims`
  with the Progress log row and the Section D exit row.

<!-- block T9 -->
````diff
diff --git a/web/DESIGN.md b/web/DESIGN.md
index 04d2d47..c409a4c 100644
--- a/web/DESIGN.md
+++ b/web/DESIGN.md
@@ -479,7 +479,7 @@ the panel appears in place beneath it.
 **Buttons**: primary lime, secondary pressed sage, quiet (no fill, sage on hover, e.g. the sheet's
 44px Close), all fully round, 17px title type. Hover deepens one step;
 focus-visible draws a 2px ink ring at 3px offset; pressed scales to 0.98 when motion is allowed;
-disabled drops to muted ink on sunk with no lime; loading keeps the label and adds "…" (no spinner when the wait is a
+disabled drops to muted ink (a primary or secondary button on sunk, with no lime; a quiet button stays transparent and only dims); loading keeps the label and adds "…" (no spinner when the wait is a
 command poll, since the receipt already states progress).
 
 **Range chips** (1D 1W 1M 3M YTD All): selected is an ink fill, never lime or green, so selected
@@ -1219,25 +1219,31 @@ sibling keys; re-run the check after edits.
 ## Open Decisions
 
 - **Monthly income target: RESOLVED 2026-10-15.** The operator sets it on More (none, a fixed amount, a percent of the account, or a percent of an amount); `web.monthly_income_target_pct` remains the fallback. The meter reads "No target set" until one is set.
-- **Product name in the shell:** "IBKR Income" is inferred; confirm or rename.
-- **Logo and favicon:** none exist; a wordmark set in Hanken Grotesk 800 is the interim.
-- **Icons:** lucide-react, as built; confirm.
-- **Sheet exit:** a 180ms slide out. The sheet closes immediately today because the review sheet
-  unmounts with its approval; adding the exit means keeping the approval through it.
-- **The decide controls' look:** a lime, round primary Approve (and round Reject, Halt and dialog
-  buttons) needs a reviewed restyle of the protected `DecideControls`, `ConfirmAction`,
-  `HaltControl` and `AutonomyControl`.
-- **A disabled quiet button (proposed 2026-10-19):** the Buttons rule drops every disabled button to
-  muted ink on sunk, so a quiet button that cannot be pressed (History's and Spreads' day arrows at
-  the end of the range, and Activity's month stepper at the first month and at this month) shows a filled circle while the live one is bare, which reads backwards.
-  Proposed: a disabled quiet button stays transparent and only dims. It changes a shared
-  component's rule, so it waits for the operator.
+- **Product name in the shell: RESOLVED 2026-11-07.** "IBKR Income", as built (the operator took the default).
+- **Logo and favicon: RESOLVED 2026-11-07.** The wordmark is the text "IBKR Income" in Hanken Grotesk 800; the
+  favicon is a text mark, an ink "I" on a sage-paper rounded square (`web/app/icon.svg`, the paper and ink values,
+  no new colour). No drawn logo.
+- **Icons: RESOLVED 2026-11-07.** lucide-react, as built.
+- **Sheet exit: RESOLVED 2026-11-07.** The sheet closes immediately (the review sheet unmounts with its approval);
+  no 180ms exit. Motion's "Exits are faster than entrances" holds for every other exit.
+- **The decide controls' look: RESOLVED 2026-11-07.** The protected `DecideControls`, `ConfirmAction`,
+  `HaltControl` and `AutonomyControl` keep their legacy bordered look inside sheets: the recorded exception to the
+  round-button rule, so the safety controls are never restyled without their own review.
+- **A disabled quiet button: RESOLVED 2026-11-07.** A quiet button that cannot be pressed (History's and Spreads'
+  day arrows at the end of the range, Activity's month stepper at the first month and at this month) stays
+  transparent and only dims; a disabled primary or secondary still drops to muted ink on sunk
+  (`components/ui/Button.tsx`).
 - **The unknown grey: RESOLVED 2026-10-14.** The light `unknown` is now `#61685d` (4.72:1 on
   pressed sage, 5.20:1 on paper, 5.76:1 on white), so small "n/a" passes AA anywhere, including the
   legacy pages that Parts 2-4 have yet to restyle.
 
 ## Decision Log
 
+- 2026-11-07: **The Open Decisions closed** (web overhaul Part 7, Task 9; the operator took all six defaults on
+  2026-11-07). "IBKR Income" as a text wordmark, a text-mark favicon, lucide icons, the immediate sheet close, the
+  protected decide controls' bordered look as the recorded exception, and a disabled quiet button that stays
+  transparent and only dims (the shared Button rule changed for the quiet variant only). No new token, colour,
+  font, radius or elevation.
 - 2026-11-07: **How it works rebuilt small** (web overhaul Part 7, Task 6; the operator's answer (a)). Seven short
   cards of plain English replace the eight-tab System Explanation, which said nothing of spreads, the value book,
   regime sizing, capital release, the news thread or the roll redesign. No new token, colour, font, radius or
diff --git a/web/app/icon.svg b/web/app/icon.svg
new file mode 100644
index 0000000..7271ef8
--- /dev/null
+++ b/web/app/icon.svg
@@ -0,0 +1,6 @@
+<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
+  <!-- The text-mark favicon (DESIGN.md Open Decisions, resolved 2026-11-07): ink on sage paper, the paper and ink
+       token values, no new colour. -->
+  <rect width="32" height="32" rx="8" fill="#f2f4ef"/>
+  <text x="16" y="23" text-anchor="middle" font-family="Hanken Grotesk, system-ui, sans-serif" font-size="20" font-weight="800" fill="#111410">I</text>
+</svg>
diff --git a/web/components/ui/Button.tsx b/web/components/ui/Button.tsx
index 8d1e02f..2b9f8da 100644
--- a/web/components/ui/Button.tsx
+++ b/web/components/ui/Button.tsx
@@ -10,8 +10,10 @@ export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
 
 const VARIANT: Record<ButtonVariant, string> = {
   // Lime means act: only the primary variant may carry it.
-  primary: "bg-primary text-on-primary enabled:hover:bg-primary-deep",
-  secondary: "bg-sunk text-content enabled:hover:bg-sunk-deep",
+  primary: "bg-primary text-on-primary enabled:hover:bg-primary-deep disabled:bg-sunk",
+  secondary: "bg-sunk text-content enabled:hover:bg-sunk-deep disabled:bg-sunk",
+  // A quiet button that cannot be pressed stays transparent and only dims, so the one you cannot
+  // press never looks fuller than the one you can (DESIGN.md Open Decisions, resolved 2026-11-07).
   quiet: "bg-transparent text-content enabled:hover:bg-sunk",
 };
 
@@ -28,7 +30,7 @@ export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button
         "inline-flex min-h-11 items-center justify-center gap-2 rounded-full px-[18px]",
         // DESIGN.md title type (17px, 700); the 0.98 press is motion, so reduced motion drops it.
         "text-[1.0625rem] font-bold transition-transform duration-[90ms] motion-safe:enabled:active:scale-[0.98]",
-        "disabled:cursor-default disabled:bg-sunk disabled:text-muted",
+        "disabled:cursor-default disabled:text-muted",
         VARIANT[variant],
         block && "w-full",
         className,
diff --git a/web/components/ui/primitives-a.test.tsx b/web/components/ui/primitives-a.test.tsx
index b72e6c4..26c0256 100644
--- a/web/components/ui/primitives-a.test.tsx
+++ b/web/components/ui/primitives-a.test.tsx
@@ -7,6 +7,22 @@ import { SegmentedControl } from "./SegmentedControl";
 import { StatusWord } from "./StatusWord";
 
 describe("Button", () => {
+  it("dims a disabled quiet button without filling it, while a disabled primary or secondary drops to sunk", () => {
+    render(
+      <>
+        <Button variant="quiet" disabled>Quiet</Button>
+        <Button variant="primary" disabled>Primary</Button>
+        <Button variant="secondary" disabled>Secondary</Button>
+      </>,
+    );
+    const quiet = screen.getByRole("button", { name: "Quiet" });
+    expect(quiet).toHaveClass("bg-transparent", "disabled:text-muted");
+    expect(quiet.className).not.toContain("disabled:bg-sunk");
+    for (const name of ["Primary", "Secondary"]) {
+      expect(screen.getByRole("button", { name })).toHaveClass("disabled:bg-sunk", "disabled:text-muted");
+    }
+  });
+
   it("defaults to type=button so it never submits a form by accident", () => {
     render(<Button>Review</Button>);
     expect(screen.getByRole("button", { name: "Review" })).toHaveAttribute("type", "button");
````

## Section E: Finish (Tasks 10-11) · sonnet; then opus review, sonnet fix pass

**Entry checks:**

- [ ] **E1. Section D landed.** In `<W>`: `git log --oneline main..HEAD` shows the nine task commits; vitest **1622 in
  153 files**; tsc and lint clean; G1, G2, G7.
- [ ] **E2. Task 10's patch applies:** `git apply --check <S>/p7/T10.out` prints nothing.
- [ ] **E3. A browser for Task 11:** `ls ~/.npm/_npx/*/node_modules/playwright-core/package.json` prints at least
  one path (the prototype used `~/.npm/_npx/e41f203b7505f1fb/node_modules/playwright-core`). None: stop and ask.

### Task 10: Docs (sonnet, effort medium)

**Files:** Modify `STATUS.md`, `ARCHITECTURE.md`, `web/CLAUDE.md`; this plan (Progress log).

**What it does (ruling 24):** the doc-update table's rows for a feature built and new `features/` folders.

- [ ] **Step 1: Check and apply `T10`.** `git status --short` shows ` M ARCHITECTURE.md`, ` M STATUS.md`,
  ` M web/CLAUDE.md`.
- [ ] **Step 2: Stale-phrase check.** `grep -c "components/explain" web/CLAUDE.md` prints `0`;
  `grep -c "components/explain" ARCHITECTURE.md` prints `1` (the sentence saying it was deleted);
  `grep -c "Parts 1-7 built" STATUS.md` prints `1`; `grep -c "features/news" ARCHITECTURE.md web/CLAUDE.md` prints a
  non-zero count for each file.
- [ ] **Step 3: Fill the commit range** in the new STATUS Built section's first paragraph (after "the plan's Progress
  log holds each task's commit, gate and rulings"), from `git log --oneline main..HEAD`, by hand with the Edit tool.
  Docs only: no test run.
- [ ] **Step 4: Commit** `docs: web overhaul Part 7` with the Progress log row (and the Section E entry row).

<!-- block T10 -->
````diff
diff --git a/ARCHITECTURE.md b/ARCHITECTURE.md
index ab4f4d2..6dfd492 100644
--- a/ARCHITECTURE.md
+++ b/ARCHITECTURE.md
@@ -1607,8 +1607,10 @@ reskinned without an edit. The structure it added:
   **Part 5 (2026-11-06, `docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md`) recomposed the stock
   page** (`features/stock/`, below). **Part 6 (2026-11-06,
   `docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md`) recomposed Research and Universe
-  and put search in the shell** (`features/research/`, `features/universe/`, `features/search/`, below). Parts 7-8
-  (News, More and How it works; the value record) and order control have no plan yet.
+  and put search in the shell** (`features/research/`, `features/universe/`, `features/search/`, below). **Part 7
+  (2026-11-07, `docs/superpowers/plans/2026-11-07-web-overhaul-7-news-more-how-it-works.md`) recomposed News and How
+  it works, added More's Value book row and closed `web/DESIGN.md`'s Open Decisions** (`features/news/`,
+  `features/explain/`, below). Part 8 (the value record) and order control have no plan yet.
 - **`app/` boundaries and titles** — web overhaul Part 4: the root `layout.tsx` sets `metadata.title` to
   `{ default: "IBKR Income", template: "%s · IBKR Income" }`; each server page exports its own `metadata`, and a
   client page gets a sibling server `layout.tsx` that exports `metadata` (or `generateMetadata` for a dynamic
@@ -1711,21 +1713,19 @@ picker submitting `ledger_import`, feed status incl. the Google Sheet mirror lin
 actions with a mark-reviewed button submitting `ledger_ca_reviewed`, import history).
 `BackToLedger` is the way back (the old `LedgerNav` tab strip was deleted in Part 4); `format.ts`/`types.ts` hold display helpers and response types.
 
-`app/news/` + `components/news/` is the News console (reads `GET /news/*`): `page.tsx` is the feed
-(`NewsFeed` with group chips and a symbol filter, each post a `NewsCard` rendered from the stored
-`CardPayload` — 📘/📈 grid as a table, `VerdictPill` with text and icon, book line, links,
-image — beside `CalendarColumn`), and `[symbol]/page.tsx` (`NewsTicker`: latest brief and chart,
-the ticker's recent stories, next earnings, and `BriefRequest`, which submits `news_brief` through
-the command queue). The rail's `News` entry comes from `lib/nav.ts` (on a phone, News is reached
-through More).
-
-`app/explain/page.tsx` + `components/explain/` is the System Explanation console — a static,
-plain-English walkthrough of how the whole pipeline works (adapted from "The pipeline, stage by
-stage" above), not a data surface: eight subtabs (Overview/Data/Ideas/Gate/Claude/Execution/
-Watching/This-Dashboard) each mount the shared `<PipelineMap/>` with that subtab's stage
-highlighted — every box is a live nav control, so the map doubles as cross-tab navigation — plus a
-`<TiesInto/>` chip list at the foot of each panel linking to related subtabs with the reason why,
-and a `<SourceRefs/>` list pointing back at the real modules.
+`app/news/` + `features/news/` + `components/news/` is the News console (reads `GET /news/*`; web overhaul Part 7
+put it on the payslip). `page.tsx` only mounts `features/news/NewsPage`: the title, the Market card, then "Latest"
+(`NewsFeed`: group chips, a labelled symbol field, each post a `NewsCard` rendered from the stored `CardPayload`, the
+explanation labelled as the news model's reading, `VerdictPill` an ink pill with text and icon) beside "This week"
+(`CalendarColumn`, one card). `[symbol]/page.tsx` mounts `features/news/NewsTickerPage`: a back link, the ticker, a
+Stock page link and Refresh, `BriefRequest` (submits `news_brief` through the command queue), then the `NewsTicker`
+body (next earnings, the latest brief and chart, the name's notes, recent stories). The rail's `News` entry comes from
+`lib/nav.ts` (on a phone, News is reached through More).
+
+`app/explain/page.tsx` + `features/explain/ExplainPage.tsx` is How it works (web overhaul Part 7 rebuilt it small and
+deleted the eight-tab `components/explain/`): seven static cards of plain English (a day from scan to order, who
+decides what, the four books, sizing and the market, rolls and freeing cash, what keeps it safe, where to look), each
+ending in links to the pages that show it. No request; the copy changes by hand when the system changes.
 
 ---
 
diff --git a/STATUS.md b/STATUS.md
index b6c77d7..a8a9628 100644
--- a/STATUS.md
+++ b/STATUS.md
@@ -347,6 +347,35 @@ Operator to-dos: re-copy `config/examples/value.yaml`'s `telegram:` and `prompt_
 
 ---
 
+## Built (2026-11-07 — web overhaul Part 7: News, More and How it works)
+
+Plan: `docs/superpowers/plans/2026-11-07-web-overhaul-7-news-more-how-it-works.md` (branch `feat/web-overhaul-7`;
+the plan's Progress log holds each task's commit, gate and rulings). Web only: no API route or field, no Python file,
+no command site, no protected file, no new token. The operator's five answers of 2026-11-07 (HANDOFF 5.4) are the
+plan's rulings 2-6.
+
+- **Carried (Tasks 1-2):** the rail's Search row is an outlined field, so the current page is the rail's only
+  pressed-sage row; a sector's IV-rank count reads "(7 with history)"; on the stock page a sentiment source with no
+  score and no count says n/a once, sample counts and the tranche sentence are tabular, and the statements' scroll
+  hint shows below 1024px.
+- **News (Tasks 3-5):** `features/news/NewsPage` and `NewsTickerPage` in the Stock/Research frame; the feed
+  ("Latest") with shared chips and a labelled symbol field; the calendar as one card ("This week") that says empty,
+  loading and failed instead of vanishing; a post's explanation labelled "The news model's reading" (the news model
+  falls back to a local one); the verdict pill in ink (a forecast is not money); the ticker page links to the stock
+  page, and its brief request is the secondary button (the `news_brief` command unchanged).
+- **How it works (Tasks 6-7):** seven static cards in `features/explain/ExplainPage` replace the eight-tab System
+  Explanation (`components/explain/`, 26 files, deleted), which predated spreads, the value book, regime sizing,
+  capital release, the news thread and the roll redesign. A test holds every "See it on" link to a page the search
+  palette lists.
+- **More and the Open Decisions (Tasks 8-9):** a "Value book" row on More (to Research; the book has no page of its
+  own); `web/DESIGN.md`'s six Open Decisions resolved on their defaults: the "IBKR Income" wordmark, a text-mark
+  favicon (`web/app/icon.svg`), lucide icons, the immediate sheet close, the protected decide controls' bordered look
+  as the recorded exception, and a disabled quiet button that stays transparent and only dims
+  (`components/ui/Button.tsx`).
+- **Known limitation:** How it works is hand-written copy; it must be edited when the system changes.
+
+---
+
 ## Built (2026-11-06 — web overhaul Part 6: Research, Universe and search)
 
 Plan: `docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md` (branch `feat/web-overhaul-6`;
@@ -1213,7 +1242,7 @@ the first alias with any facts was wrong), `select_periods` (enforces `kind`, la
 | **P2 — Options console (M1+M2+M3 built 2026-09-06, reviewed; M4 Tasks 4.1+4.2+4.3+4.4 built 2026-09-06; M5 Tasks 5.1+5.2+5.3+5.4 built 2026-09-07; M6 Tasks 6.1+6.2+6.3+6.4 built 2026-09-07; M7 Tasks 7.1-7.7 built 2026-09-07 — P2 complete)** | **M1 — Write foundation:** the intent queue exists, the drain runs with no registered handlers, and no web action can reach an order until M3. `AppCommandRow` (`src/storage/models.py`) + `src/storage/app_commands.py` (enqueue/dedupe/mark/expire helpers); `src/api/models/commands.py` (`CommandKind` enum, typed payloads per kind, `validate_payload`, `dedupe_key_for`, `CommandStatus` — `UniversePayload.list_name` is `Literal["would_own", "watchlist"]` so `sectors`/`leveraged_etfs` fail parsing); `src/api/trading_db.py` gains a write-scoped `get_command_engine` + `command_session` with a `before_flush` listener (`WriteFenceViolation`) that rejects any flush targeting a non-`app_commands` table; `src/api/commands.py` is the only module allowed to import `get_command_engine`/`command_session` (`submit` enqueues, `get_status` reads through the read-only engine, `clear_confirm_token` clears a live-mode token after confirmation); `src/api/routers/commands.py` adds `POST /commands`, `GET /commands/{id}`, `POST /commands/{id}/confirm` (owner-only, dedupe returns 200 not 201, live-mode order-reaching intents get a `confirm_token`); `src/notify/command_drain.py` + `_command_drain_loop` in `approval_service` (fails unknown kinds loudly, isolates throwing handlers, skips commands awaiting confirmation, runs with `ib is None`, writes `command_drain_heartbeat` to `system_settings` after every cycle so `/options/controls` can tell a live drain from a dead one); `tests/test_web_fence.py` gains three P2 fence tests (write-handle leak — greps for both `get_command_engine` and `command_session`, command writer names no other table, trading path still never imports the web layer); the token proxy (`web/app/api/[...path]/route.ts`) moves `API_TOKEN` server-side — `NEXT_PUBLIC_API_TOKEN` is purged from the repo, the built bundle no longer contains the token. **M2 — Read surfaces:** the console exists and is worth opening, still unable to do anything. `GET /options/approvals` + `/approvals/{id}` (`src/api/routers/options.py`, `src/api/models/options.py`) — a four-table join (approval/candidate/risk-verdict/claude-review) through the read-only engine, snapshot-first when the candidate has been pruned, the five review fields rendered separately never as one blob. `GET /options/assessed` implements the promotable table from spec §5.2 exactly (`risk_gate`/`generator` never promotable), ranked like `scan.py::_rank_assessed`, `limit` caps the total across groups not per symbol. `GET /options/orders`, `/fills`, `/shorts` (nulls stay null — `avg_fill_price`/`mark`/`unrealized_pnl` never fabricate `0`; `shorts.as_of` is the snapshot's capture time, not request time). `GET /options/controls` reads `command_drain_heartbeat` against twice the poll interval — never reuses `/health`'s research-worker heartbeat, defaults to unhealthy, never `true` on a drain that has never run. Web: `web/app/options/page.tsx` + `[approvalId]/page.tsx`, `web/components/options/*` (`ApprovalsList`/`ApprovalCard`, `AssessedBrowser` with stage badges that are never colour-alone, `OrdersTable`/`FillsTable`/`ShortsTable`, `ControlsStrip`, `ApprovalDetail`/`ReviewPanel`/`IdealZoneBar`/`AlternativesTable`) — no approve/reject/promote/roll control anywhere, asserted by a frontend test. The rail flip (`src/api/routers/meta.py`) makes `/options` available. A Sonnet verification pass (2026-09-06) live-browser-tested every tab and the detail page against the real dev stack and found the console **completely unreachable** for reasons outside M1/M2's own code: `web/.env.local` still carried the pre-M1 `NEXT_PUBLIC_API_URL`/`NEXT_PUBLIC_API_TOKEN` names instead of the migrated `API_URL`/`API_TOKEN`, so every proxied request 500'd; and `app_commands` (M1 Task 1.1) had never been created in the real `data/income_system.db` because table creation only runs via the trading daemon's own `init_db()` startup path, which nobody had triggered since the model was added. Both are environment/ops gaps, not code defects, and are now fixed locally (`.env.local` corrected, `init_db()` run once). The pass also found and fixed two real code defects: `GET /options/approvals/{id}` raised `MultipleResultsFound` (500) whenever a candidate had been assessed across more than one scan run — completely ordinary, since `risk_verdicts` stores one row per assessed contract *per run* — fixed by ordering both the verdict and review lookups by `created_at` descending and taking the newest; and `web/app/options/[approvalId]/page.tsx` was missing `"use client"`, crashing on every real navigation to it (masked in tests by the component-level test harness). **None of M1 or M2 had ever been `git commit`ed** despite every task's checklist saying so — this is almost certainly why a later M3 session, working from git-tracked state, concluded the console UI "never landed" even though it existed on disk and worked once the environment gaps above were fixed; see `Web plan/milestones/P2/M3-approve-reject.md`'s correction note. All gates green after the fixes: `python -m pytest -q` (1755 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (100 passed) `&& npm run lint && npm run build`, plus a live click-through of every `/options` tab and an approval detail page with zero console errors. **M3 — Approve and reject (built 2026-09-06, opencode/glm-5.3):** the first web action that can cause an order to exist, through the exact Telegram code path. `src/notify/command_drain.py` registers `approve`/`reject` handlers that call `approval_service._process_button` **unchanged** (a monkeypatch test fails if a refactor forks the mutation); an already-decided approval is `applied` neutrally ("Already {status}" in `result.decision`), a replayed drain creates no second order (all four §4.5 idempotency layers hold, asserted in `tests/test_drain_approve_reject.py`), and neither handler needs `ib` — TWS down still queues the order. The drain stores a handler's result dict verbatim and gains `CommandFailed(reason, detail)` for machine-readable failures. The live-mode second confirmation now fails closed exactly per spec §4.6: a wrong/missing token is **403 and does not clear the field** (`tests/test_live_confirmation.py` covers token creation by kind, the drain's skip, the confirm-then-apply round-trip, the 403/409 split, and the TTL sweep), the outstanding `confirm_token` is surfaced through the owner-only `CommandStatus` so the frontend can complete the round-trip, and confirming a not-awaiting command is 409. `tests/test_write_path_invariants.py` asserts the phase invariants in one place: every `/options`+`/commands` route is owner-gated (globbed via route introspection), no route module imports the write handle, Telegram and the console cannot double-decide an approval into two orders, a crashed drain re-applies exactly once, and the API still holds no `ib_async` import. Web: `web/lib/receipt.ts` (`receiptState` — pending never renders as applied, `submitted` only when an order is working, `filled` only when a fill exists, stalled stated in words), `CommandReceipt` (the §9.2 signature component — intent id always visible, humanised failure reasons, no spinner when stalled), `ConfirmAction` (confirm dialog: exact contract/count, case-sensitive typed-word gate for M6's halt, focus trap + Escape + focus return, aria-modal, reduced-motion entry), `web/lib/commands.ts` (`submitCommand`/`confirmCommand`/`useCommandStatus` polling every 2s while pending, stopping at a terminal state), and `DecideControls` — the shared decide flow on both the approval card and the detail page: confirm dialog before any request, one `POST /commands`, controls disabled while in flight, a decided approval renders its decision not controls, 403 renders a permission message, and in live mode a distinct clearly-labelled second LIVE confirmation (cancelling it leaves the intent queued and unconfirmed, stated in the receipt). The M2 no-action-buttons guards evolved with the milestone: the controls now exist and are asserted wired through the confirm gate. **The existing execution-time `[CONFIRM LIVE]` path is untouched and still fires after a web live approve.** All gates green: `python -m pytest -q` (1776 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (130 passed) `&& npm run lint && npm run build`. **M4 — Promote, Tasks 4.1+4.2+4.3+4.4 (built 2026-09-06):** promote is now a real gated action, belt and braces. **Task 4.1 — the API-boundary promotable-stage guard:** `src/api/routers/commands.py`'s `assert_promotable` refuses `POST /commands` for a `promote` before any `app_commands` row exists unless the candidate's most recent `risk_verdicts` row is at `score_floor`/`dedupe`/`top_n` (spec §5.2's promotable table) — `risk_gate`/`generator` are never promotable, `passed` already has an approval, an unknown `candidate_id` is `404`, a non-promotable stage is `409 {"reason": "stage_not_promotable", "stage": ...}`. **Task 4.2 — the drain handler re-prices and re-gates for real:** `src/notify/command_drain.py`'s `promote` handler does not trust the stored row it was asked to promote — it re-runs the single-ticker pricing path (`src.orchestrator.scan._price_and_gate_ticker`, extracted from `run_ticker_scan` as a pure refactor — same chain fetch, analytics, CC/CSP screens, scoring, `validate_candidates` gate, and `record_assessments` audit write, zero behavior change to `run_ticker_scan` itself) for the requested symbol, searches the gate-passed output for the exact `(strategy, strike, expiry)`, and only then calls the new `src/execution/promote_pipeline.py::queue_promoted_for_approval` (mirrors `roll_pipeline.queue_roll_for_approval`'s `has_active_order` guard and `CandidateRow`/`ApprovalRow` upsert, minus the generation half — it takes the fresh `TradeCandidate` directly) to raise a PENDING approval. Nothing from the stored `RiskVerdictRow` reaches the approval except the tuple used to find the fresh match; every number on the approval — including a re-gate that now rejects (`gate_rejected`, reasons surfaced verbatim, by design) — comes from this run. Failure reasons (`broker_unavailable`, `chain_unavailable`, `contract_not_priced`, `gate_rejected`, `score_below_minimum`) are documented verbatim in `docs/web/commands.md`. `drain_once` now awaits a handler's result when it returns one (coroutine handlers, needed for promote's re-scan; every earlier sync handler is unaffected). All gates green: `python -m pytest -q` (1804 passed), `ruff check .`, `mypy src`. **Task 4.3 — the promote control and its receipt in the frontend (built 2026-09-06):** `AssessedBrowser`'s per-contract `<li>` was extracted into its own `web/components/options/AssessedRow.tsx` component (a pure, behavior-preserving extraction — every existing `AssessedBrowser.test.tsx` test kept passing unmodified), which now carries a Promote button rendered only when `promotable` is true and `strike`/`expiry` are both non-null (a promotable row with either unexpectedly null falls through to the non-promotable rendering rather than send `null` to the API). Promoting reuses the M3 decide flow exactly: `ConfirmAction` first (explaining in one sentence that the contract is priced and gated again and an approval appears only if it still passes; a `score_floor` row's dialog additionally shows the blended score and `promote_note`'s configured-minimum text verbatim), then `submitCommand("promote", {candidate_id, symbol, strategy, strike, expiry})` fires once, `useCommandStatus` polls to a terminal state, and `<CommandReceipt/>` renders the outcome unmodified (`order` is always `null` — a promote never has approve/reject's working-order lifecycle) — a live-mode response routes through the same second LIVE confirmation `DecideControls` uses. On `applied`, a "View approval" link to `/options/{approval_id}` renders when `result.approval_id` is non-null. `AssessedBrowser` now also fetches `GET /options/controls` itself (same pattern as `ApprovalsList`) so a promoted row's receipt can state a dead drain in words. All gates green: `python -m pytest -q` (1805 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (150 passed) `&& npm run lint && npm run build`. **Task 4.4 — the promote refusal tests (built 2026-09-06):** `tests/test_write_path_invariants.py` gains the belt-and-braces coverage for the whole milestone: `test_no_promote_path_exists_for_a_gate_rejected_contract` enqueues a promote command directly (bypassing Task 4.1's API-boundary guard entirely, the way a malformed or bypassed request would) for a `risk_gate`-staged contract and asserts the drain handler's own re-gate still refuses it; `test_the_promote_handler_runs_the_real_rules_engine` wraps (not mocks) `validate_candidates` with a spy to prove the real Rules Engine is what's called, not a stand-in; `test_promotable_stages_match_the_spec_exactly` pins `PROMOTABLE_STAGES == {"score_floor", "dedupe", "top_n"}` so a future edit that widens it fails here first. **M5 — Roll on demand, Tasks 5.1+5.2+5.3+5.4 (built 2026-09-07, opencode/glm-5.2):** the operator can ask the system to propose a roll for any open short, without waiting for the intraday monitor to fire an alert. Two steps, never one: the console proposes; the operator approves that proposal through M3's path. **Task 5.1 — the `roll_request` drain handler:** `src/notify/command_drain.py`'s `_roll_request` resolves the position from a live `get_positions(ib)` read, fetches a fresh chain + IV/technical stats through `src.execution.roll_pipeline.fetch_roll_inputs` (the shared chain-fetch path extracted from the monitor's `_try_queue_roll`, which was refactored to call it — behavior unchanged; the same three helpers composed inline are now one function two callers share, so the web and the monitor cannot drift on how a roll is priced), and calls `queue_roll_for_approval` **unchanged**. The handler disambiguates the pipeline's `None` **before** calling it: it runs `generate_roll_candidates(..., defensive=True)` itself to derive the same candidates the pipeline will choose from (same function, same inputs, same deterministic ids), and checks `_existing_roll_in_flight` against **every** one of them, not just the top-ranked one (post-M5 verification fix, 2026-09-07 — see "Bug fixed" note below) — covering both an active order (`active_order_for`, the new row-level companion to `has_active_order` in `src/storage/orders.py`) and an existing PENDING approval. Either → `roll_already_working` with `detail.approval_id` so the receipt links to the in-flight proposal; empty/failed chain → `chain_unavailable` with the provider message; no candidates → `no_qualifying_roll`; non-short or absent position → `not_an_open_short` / `position_not_found`; `ib is None` → `broker_unavailable`. The PENDING-approval check is what closes the monitor-vs-web race `has_active_order` alone would miss (the monitor's roll raises a PENDING `ApprovalRow`, no `OrderRow` until approved) — the milestone's headline acceptance criterion ("a monitor alert and a web request produce exactly one approval") requires it. `tests/test_drain_roll.py` carries the nine specified tests (seven from the plan + `position_not_found` + `chain_unavailable`), mocking only the IBKR/network boundary so the real `generate_roll_candidates` economics run. Failure reasons documented verbatim in `docs/web/commands.md`'s roll_request section. **Task 5.4 — roll degradation tests (built 2026-09-07):** `tests/test_write_path_invariants.py` gains three invariants: a behavioral tripwire + source scan proving the handler never reaches `execute_roll` directly (no `roll_executor` import, no `execute_roll(` call in `command_drain.py` or `roll_pipeline.py`); the verbatim token grep proving no `max_debit`/`min_delta_reduction`/`roc_pct` leaked into `command_drain.py`; and a `wraps`-spy on `generate_roll_candidates` at both call sites proving `defensive=True` flows through the handler's pre-check and the pipeline's internal call (the web roll is the monitor's roll). Reuses the `drain_env`/`fake_chain` fixtures from `tests/test_drain_roll.py` the same sanctioned way the file already imports the promote fixtures. **Task 5.2 — the roll control on the shorts list (built 2026-09-07):** `web/components/options/ShortsRow.tsx` extracted from `ShortsTable` (the same extraction `AssessedRow` got from `AssessedBrowser`), carrying the row's cells plus the confirm-then-submit-then-receipt flow that mirrors `AssessedRow`'s promote control exactly. The control is labelled "Propose a roll" (not "Roll" — the button does not roll the position, and the copy says so); `ConfirmAction` states plainly that the system will price a roll, raise it for approval, and nothing executes until that proposal is approved; `submitCommand("roll_request", {position_symbol})` fires once; `useCommandStatus` polls to terminal. `no_qualifying_roll` renders as a plain sentence in a `data-state="answered"` box (no `text-loss` chrome) — special-cased in `ShortsRow` so `CommandReceipt` stays untouched and every existing receipt test stays green. `roll_already_working` renders the failed receipt plus a "View the roll already in flight" link to `result.detail.approval_id`; success renders a "View approval" link to `result.approval_id`. The control is disabled while in flight and wired through the live-mode second confirmation (roll_request is in `_LIVE_CONFIRM_KINDS`). `ShortsTable` now fetches `GET /options/controls` (same pattern as `ApprovalsList`) so a roll receipt can state a dead drain in words; defaults healthy while loading. The M2 "asserts no roll button exists" guard evolved into the roll-control suite (17 tests in `ShortsTable.test.tsx`). **Task 5.3 — roll alerts on the shorts list (built 2026-09-07):** `_TRIGGER_LABELS` + `humanize_trigger` moved from `src/notify/formatters.py` to `src/monitor/triggers.py` (beside the codes they name); `formatters._humanize_trigger` is now an alias import, so every existing formatter caller works unchanged and the identity `formatters._humanize_trigger is triggers.humanize_trigger` is asserted in `tests/test_api_shorts.py`. `RollAlertSummary` gains `trigger_label` (humanised server-side via the shared mapping) and `claude_recommendation` (passed through from `RollAlertRow`, nullable). The API router imports `humanize_trigger` from `src.monitor.triggers` — not the notify layer — so the "API must not pull in the notify layer" fence holds. The web renders `trigger_label` verbatim, the alert age as text via `relativeAge`, and Claude's view labelled "Model opinion (Claude): ..." — distinct from any deterministic number on the row. A position with no alerts renders nothing extra (not "No alerts"). **A Sonnet verification pass (2026-09-07)** checked the opencode/glm-5.2 build against this plan and the live gate (test count, ruff, mypy, vitest, lint, build all reproduced exactly as claimed) and found one real defect in Task 5.1's own new code: `_roll_request` derived the same candidate `queue_roll_for_approval` would pick and checked only that single, top-ranked candidate for an in-flight roll. Under `defensive=True` every candidate's `roc_pct` is hardcoded `0.0` (rolls are judged on risk reduction, not yield, per D4), so `generate_roll_candidates`'s ROC-desc sort is a no-op tie and "the top-ranked candidate" is really just whichever qualifying quote the chain happened to list first — a property of chain order, not economics. Two fetches taken minutes apart (the monitor's, then the web's) can list the same qualifying strikes in a different order, so the monitor's already-PENDING candidate can silently drop to second-or-later without ceasing to qualify — and the handler would then fail to recognise it as in flight, racing the monitor into a second approval for the same position, exactly the case the milestone's headline acceptance criterion exists to prevent. Fixed by checking every one of `generate_roll_candidates`'s qualifying candidates against `_existing_roll_in_flight`, not just `candidates[0]` — bounded to the handful of strikes/expiries one chain fetch returns, so the cost is negligible. Regression test: `tests/test_drain_roll.py::test_an_in_flight_roll_is_caught_even_when_no_longer_top_ranked` (constructs two qualifying candidates whose chain order flips between the monitor's fetch and the web's, and confirms it reproduces the double-approval against the pre-fix code). Also flagged, not fixed (pre-dates M5, lives in `rolling.py`'s N20-era economics, out of scope for a drain-handler fix): the same `roc_pct = 0.0` fact means the monitor's own roll selection has never actually picked the "best" defensive roll by any economic measure, only the first one the chain lists — worth a human look at whether defensive rolls should rank by delta-reduction, liquidity, or credit instead of an always-tied ROC. All gates green after the fix: `python -m pytest -q` (1827 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (163 passed) `&& npm run lint && npm run build`. **M6 — Controls, Tasks 6.1+6.2+6.3+6.4 (built 2026-09-07, opencode/glm-5.3):** halt, resume and the autonomy rung are reachable from the browser, with the confirmation weights deliberately asymmetric. **Task 6.1 — the drain handlers:** `src/notify/command_drain.py` registers `halt`/`resume`/`set_autonomy`, thin resolvers over the same `system_settings` helpers Telegram's `/halt`, `/resume`, `/autonomy` use (`set_halted`/`set_autonomy_level` — one halt flag, read through `HALT_KEY`; a token-grep test pins that the literal `execution_halted` never appears in the drain). All three apply with `ib is None`: halting matters most exactly when something is wrong, and "TWS is unreachable" is a common shape of wrong. Halt/resume are idempotent (`applied`, never `failed` — halting an already-halted system satisfies the intent; so does resuming an un-halted one, resolving the M1 doc's `not_halted` failure mode as a satisfied intent instead); an empty halt reason is stored as `"halted from the web console"` so `/status` and the console always say something; `resume` records who released the switch in the command's `result` (`released_by`); each handler sends a Telegram notification — the one place a handler notifies, because control-plane changes have no order-poll loop to report them later, and a halt raised from the browser must be visible wherever the operator is. `set_autonomy` enforces the same promotion evidence gate Telegram does (`promotion_blockers` must be empty, else the command fails with `promotion_refused` + `detail.blockers`) so the web is not the rung ladder's back door; demotion always applies. `tests/test_drain_controls.py` carries 13 tests including the six specified verbatim. **Task 6.2 — payload validation:** `HaltPayload.reason` is capped at 200 chars (`422` past it — the reason is rendered by `/status` and the halt banner, an unbounded string there is a rendering bug waiting to happen), and the empty-payload kinds (`halt`/`resume`/`set_autonomy`/`refresh`) are `extra="forbid"` so a client typo is caught rather than ignored — all at parse time, before a command row exists (asserted). Control kinds carry no `dedupe_key` (M1's convention, pinned) and are never in `_LIVE_CONFIRM_KINDS` — the deliberate asymmetry, stated in a comment at the set so it does not look like an oversight: the live token is for intents that can reach an order, and a halt must never be slowed by a second step (asserted for halt with `cfg.is_live` true). **Task 6.3 — the controls panel:** `web/components/options/HaltControl.tsx` (halt is ONE CLICK, no dialog — speed is the feature, and a test name says so; resume requires the typed word RESUME, disabled until it matches exactly case-sensitively) and `AutonomyControl.tsx` (four rungs rendered from the API's `rungs` array, never hardcoded; a rung change click-through confirms showing current and target rungs; a refused promotion renders `promotion refused` with the blockers through the receipt). `ControlsStrip` now hosts both plus an unmissable halted banner at the top of the console (reason and time as text, fill and text never colour alone; honest "unknown time" when no halt command row exists, e.g. a breaker trip) and a `drain_healthy: false` line stating "the trading service is not draining commands" beside the controls — a queued-but-undraining halt is this milestone's worst case. Both controls disable while their own command is in flight, render `CommandReceipt`, invalidate the controls query on terminal so the strip moves on the next poll, and route a live-mode response through the same second LIVE confirmation (unreachable in practice for these kinds, but the shape is shared). `ConfirmAction`'s docstring corrected: the typed word is used by `resume` in M6, not `halt` (the milestone refined design §9.3's first draft). `GET /options/controls` gains `halted_at`, derived from the most recent applied `halt` command's `applied_at` — the "no new setting keys" rule and the banner's "time it was halted" are reconciled without a new key, and a breaker-tripped halt honestly renders no time rather than a fabricated one. 22 new frontend tests across `HaltControl.test.tsx`, `AutonomyControl.test.tsx`, `ControlsStrip.test.tsx`. **Task 6.4 — controls invariants:** `tests/test_write_path_invariants.py` gains the three specified tests (parametrised every-control-kind-applies-without-a-broker over the reused `drain_env` fixture; `test_control_kinds_never_require_live_confirmation` pinning `_LIVE_CONFIRM_KINDS`; `test_the_halt_key_is_the_same_one_telegram_uses` with the verbatim token grep). All gates green: `python -m pytest -q` (1856 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (185 passed) `&& npm run lint && npm run build`. **A Sonnet verification pass (2026-09-07)** checked the opencode/glm-5.3 build against this plan and the live gate (all six commands reproduced exactly as claimed) and found one real defect: `GET /options/controls`' `halted_at` derivation had no lower bound, so a resumed web halt followed by a later, command-row-less halt (a circuit-breaker trip, or a Telegram `/halt` — neither writes an `AppCommandRow`) surfaced the *earlier* halt's timestamp instead of the honest `null` design decision 1 promised for exactly that case; the one existing null-case test only covered a fresh DB with no prior halt rows and never exercised the halt→resume→halt sequence. Fixed by bounding the halt lookup (`routers/options.py::controls`) to applied strictly after the most recent applied `resume` row. Regression test: `tests/test_api_controls.py::test_halted_at_does_not_leak_a_stale_timestamp_from_a_prior_halt_cycle`. All gates green after the fix: `python -m pytest -q` (1857 passed), `ruff check .`, `mypy src` (web gate unaffected, not re-run). **M7 — Universe editing (Tasks 7.1-7.7 built 2026-09-07):** the two soft universe lists — `would_own` and `watchlist` — become editable from the browser, without `sectors` or the risk engine ever becoming reachable from the web. **Task 7.1 — the override store:** `UniverseOverrideRow` (`src/storage/models.py`, unique on `(symbol, list_name)`) holds one row per operator add/remove — upper-cased `symbol`, `action: "add"|"remove"`, `created_by`/`created_at` audit trail; `src/storage/universe_overrides.py`'s `set_override`/`clear_override`/`all_overrides` each take an explicit `session`, and `set_override` is a total-replace upsert — a later call for the same pair overwrites `action`/`created_by`/`created_at` in place, so an add followed by a remove is one row, never two to reconcile at read time. **Task 7.2 — the composer:** `src/common/universe.py::effective_universe()` composes `universe_overrides` onto `config/universe.yaml`, returning a dict shaped exactly like `get_config().universe`. Only `would_own`/`watchlist` are overridable (`OVERRIDABLE_LISTS = frozenset({"would_own", "watchlist"})`); every other key — `sectors`, `strike_bands`, `indexes`, `actively_wheeling`, `leveraged_etfs` — passes through byte-identical, proven even against a stray override row inserted directly under `list_name="sectors"`. A `remove` override on a symbol currently in `actively_wheeling` is ignored when composing `would_own` — you cannot stop being willing to own something you are actively wheeling. An unreadable overrides table falls back to the YAML base untouched and logs a warning; it never raises and never empties the universe. A 60-second TTL cache (a plain `(dict, time.monotonic())` tuple) avoids a DB round-trip on every read; `invalidate_universe_cache()` forces recompute so a web edit is visible immediately in the process that applied it, not up to 60s later. Ordering is deterministic: YAML file order, then added symbols in `created_at` order. **Task 7.3 — six consumers migrated** from `get_config().universe` to `effective_universe()`: `src/strategies/cash_secured_put.py` (the CSP eligibility check — the single most consequential edit in the milestone, proven end-to-end by a test that adds an override and confirms `generate_csp_candidates` actually changes its output), `src/orchestrator/scan.py` (symbol selection), `src/orchestrator/eod_report.py` (two sites — the daily IV-history refresh set and the EOD watchlist report), and `src/api/routers/universe.py` / `routers/research.py` (three read sites across the two files). `src/engine/risk_engine.py`, `src/ibkr/market_data.py`'s `strike_bands`, and every `actively_wheeling`/`sectors` read elsewhere are deliberately untouched — not overridable. An autouse `tests/conftest.py` fixture resets the TTL cache around every test. **Task 7.4 — the write path:** `GET /universe` gains `lists: [{name, overridable, entries: [{symbol, overridden, removed, created_by, created_at}]}]` (four lists, `indexes`/`watchlist`/`would_own`/`actively_wheeling`, only the latter two `overridable`) and flips `editable` to `true`; `would_own`/`watchlist` entries are the union of the YAML base and every override row for that list, not just the filtered effective list, so a removed YAML-base symbol stays visible (greyed out) with a revert path. New routes `POST`/`DELETE /universe/{list_name}/{symbol}` (owner-only, thin wrappers over the same command-queue path `POST /commands` uses) narrow `list_name` to `Literal["would_own", "watchlist"]` so any other value is `422` before a command row can exist; an unknown symbol (checked against the research symbol directory) is `404`; removing an `actively_wheeling` symbol specifically from `would_own` is `409`. The drain handlers `_universe_add`/`_universe_remove` (`src/notify/command_drain.py`) call `set_override` — never `clear_override`, since a remove must always record an explicit suppressing row, even for a YAML-base symbol, because deleting the row would silently do nothing for one — then `invalidate_universe_cache()`. Neither handler can fail (all validation already happened at the API boundary) and neither sends a Telegram notification, deliberately — a universe edit is reversible, non-urgent config, unlike halt/resume/set_autonomy. **One fix-loop round, the only one across the whole milestone:** the initial `GET /universe` entries-union silently dropped a genuinely reachable state — a symbol added via override then removed again, leaving a non-base `action="remove"` row — fixed so every override row for a non-base symbol appears in `entries`, tagged `removed = (action == "remove")`. **Task 7.5 — the frontend:** `web/components/universe/{UniverseList,OverrideBadge,AddSymbol}.tsx` and a rewritten `web/app/universe/page.tsx` consume the new shape (`web/lib/commands.ts` gains `submitUniverseCommand`); add/remove controls render only on `would_own`/`watchlist`, with `indexes`/`actively_wheeling` rendered read-only and noted as YAML-managed. Adding to `would_own` opens a confirmation naming the actual consequence — the system may sell cash-secured puts on the symbol and the operator may be assigned its shares; adding to `watchlist` fires immediately with no dialog (a reporting list, never reaches an order). An overridden entry renders `OverrideBadge` (author, timestamp, a revert control that fires the opposite action of the entry's current state). The symbol picker is a typeahead over `GET /research/search`, so a typo cannot become a `404`. Every mutation renders `CommandReceipt` and stops polling at a terminal command status. The wheeling-vs-dip-watch tag the pre-M7 page showed within `would_own` was preserved. **Task 7.6 — the fence:** `tests/test_web_fence.py` gains three tests: no module under `src/claude/eval/` or `src/research/` can write a universe override; `src/engine/risk_engine.py` never mentions `effective_universe`/`universe_overrides` anywhere in its text; `OVERRIDABLE_LISTS == frozenset({"would_own", "watchlist"})` exactly, pinned so a future widening fails here first. All gates green: `python -m pytest -q` (1920 passed), `ruff check .` (clean), `mypy src` (clean), `cd web && npx vitest run` (203 passed) `&& npm run lint && npm run build` (both clean). **Final whole-branch review fix round (2026-09-07), one commit, seven findings:** `universe_add`/`universe_remove` lost their dedupe key in `dedupe_key_for` — a stable `f"{kind}:{list_name}:{symbol}"` key let a later, semantically different request (e.g. the second `remove` in remove→add→remove) dedupe to an earlier request's already-`applied` command row, so the API returned `200`/`applied` while the override table never actually changed; both kinds now join halt/resume/set_autonomy/refresh under `dedupe_key_for(...) is None`, so a repeat POST/DELETE always creates a fresh command (idempotent in effect via the upsert-only handlers, not via dedupe). The generic `POST /commands` route gained the same unknown-symbol `404` check (`src/api/deps.py::assert_known_symbol`, shared with the thin wrappers) the `POST`/`DELETE /universe/{list_name}/{symbol}` routes already had, closing a path that let an owner smuggle an override for a non-existent symbol straight past those wrappers. `GET /universe`'s `removed` field is now derived directly from the override row's `action` plus the `actively_wheeling` guard (matching `_compose_list`'s own guard condition) instead of from `effective_universe()`'s cached composed list — that cache is invalidated only in the exec process that runs the drain, so the API process's own cache instance could read up to 60s stale right after a removal, showing a just-removed symbol as still present with a revert badge that fired the wrong action. `created_at` is now normalized through `routers/options.py`'s `_as_utc` before serializing, so a naive SQLite timestamp doesn't silently render at the wrong relative age in a non-UTC browser. `effective_universe()` now copies (not aliases) every passthrough container one level deep, so its return value can never share object identity with the `lru_cache`-shared `sectors`/`indexes`/`actively_wheeling` config the risk engine reads. `test_the_overridable_set_matches_the_spec_exactly` now pins all four independent declarations of `{"would_own", "watchlist"}` (`OVERRIDABLE_LISTS`, `routers/universe.py::_OVERRIDABLE`, `UniversePayload.list_name`, and both route functions' `list_name` parameters), not just the first. `ARCHITECTURE.md` now notes `effective_universe()`'s `session_scope()` read (and `checks/warnings.py`'s transitive dependency on it) as a deliberate, documented exception to the API's read-only-trading-DB invariant. All gates green again: `python -m pytest -q`, `ruff check .`, `mypy src`, `cd web && npx vitest run`. **Not built, plainly:** no order ticket (spec §4.3, a standing P2 scope decision from M1, not new to this milestone); no Tailscale (same, standing since earlier milestones); and — the one limitation unique to this milestone, by deliberate design — **no override for `sectors`**: it feeds `risk_engine.py`'s concentration limits and stays file-only, unreachable from the web at every layer (API `422` via the `Literal` path-parameter type, the composer's byte-identical passthrough, and the fence test above). `clear_override` (Task 7.1) is built and independently tested but unused by any handler — revert is achieved through the opposite command (`POST`/`DELETE`), not a dedicated hard-revert route; it remains available for a future feature. No Telegram notification fires for a universe edit, deliberately. ~~`refresh`'s command kind (spec §6.6) still has no registered handler anywhere in the codebase~~ **Registered 2026-09-09** — P3/P4 M1 Task 1.4 (`src/notify/command_drain.py::_refresh`) gave it its handler: it captures positions + account values and writes one `portfolio_snapshots` row (`source="refresh"`), creating no approval and no order; `docs/web/commands.md` documents it. P3 (Portfolio), P4 (Profitability tracker), and P5 (Mobile) remain deferred — see the rows immediately below. |
 | **P3 — Portfolio (M1 — the portfolio spine — built 2026-09-09, opencode/glm-5.3; M2 — the portfolio read API — built 2026-09-10, opencode/glm-5.3; M3 — the portfolio UI — built 2026-09-10)** | **M1:** nothing user-visible — no route, no component, no nav change. The API cannot ask IBKR anything, so the two processes that already hold an IB connection now write down what IBKR said, into a table the API reads. **The new table:** `PortfolioSnapshotRow` (`portfolio_snapshots`, `src/storage/models.py`) + `src/storage/portfolio_snapshots.py` — append-only, **no unique constraint** (two rows may share a `captured_at`: a refresh moments after a monitor write must not fail; newest `id` wins a tie), deliberately separate from `position_snapshots` (whose one-row-per-ET-day contract assignment auto-detection diffs — never written by anything new, pinned by a row-count test), pruned by the EOD run to `storage.portfolio_snapshot_retention_days` (default 30) beside `purge_old_risk_verdicts`; `save/load_latest/latest_capture_time/prune` never raise (the monitor calls save from a live event loop). **The two writers:** (1) the intraday monitor's `_maybe_write_snapshot` (`src/monitor/intraday.py`) — called at the *end* of `_refresh_subscriptions` with the positions that pass already fetched (never a second `get_positions`), rate-limited by `market_data.portfolio_snapshot_interval_minutes` (default 15) through a gate that reads the table's newest `captured_at` from the DB (a restart can't burst snapshots; a refresh's row counts toward the interval), RTH-only, account fetch under `asyncio.wait_for`, and wrapped so no exception can escape into `_refresh_loop` — a dead refresh task would silently stop roll alerts for every position opened after that moment, and that failure mode has its own test (`tests/test_monitor_snapshot.py`); (2) the `refresh` drain handler (`src/notify/command_drain.py::_refresh`, the command kind P2 left unregistered — now registered): captures positions + account now, writes one `source="refresh"` row, ignores the monitor's gate, fails `broker_unavailable` without a broker (never writes stale data as fresh), fails `snapshot_failed` on a bad write, sends no Telegram, and creates no approval and no order — the phase's no-new-order-path assertion lives in `tests/test_drain_refresh.py`. **The fallback chain:** `src/api/portfolio_source.py::read_portfolio` → `PortfolioReading` — three rungs (newest `portfolio_snapshots` row; else newest `position_snapshots` + the account block out of `journal.payload["eod_summary"]["account"]` (optional there, validated whole through `AccountSnapshot.model_validate`); else `source="none"`, `snapshot=None` — never a zeroed-out snapshot, because a portfolio page rendering zeros is indistinguishable from an account that's genuinely empty). A corrupt row on any rung falls through rather than failing; `as_of` is the capture time everywhere (via `as_utc_opt`), never request time. **Config keys:** `market_data.portfolio_snapshot_interval_minutes`, `storage.portfolio_snapshot_retention_days` (both documented in `ARCHITECTURE.md`/`SETUP.md`). **The read-side schema:** `PortfolioSnapshot` (`src/common/schemas.py`; `account` optional only on the API's eod rung). **M2:** four owner-only read routes (`src/api/routers/portfolio.py` + `src/api/models/portfolio.py`, mounted under `/portfolio`), all rendering what `read_portfolio` found — no second data path. `GET /summary`: account values as `Sourced` (`Source.IBKR`, `fresh_for` twice the snapshot interval — one missed capture reads stale) beside the exposure block (open positions/shorts/campaigns, net delta per the EOD formula, cash secured against short puts only at `strike × contracts × 100`, buying-power utilisation `null` not `0.0` when buying power is zero, assignment-risk count through the shared M0 predicate). `GET /positions`: grouped by underlying (a `null` `underlying` groups under its own symbol, never dropped), **both cost bases reported** — `avg_cost` from IBKR, `adjusted_cost_basis` from campaigns for assignment shares (both adjusted fields `null` otherwise), `unrealized_pnl` against the former and `unrealized_pnl_adjusted` against the latter so a profitable assigned position can't look like a loss; `moneyness` from the group's stock price else the latest `price_history` close (read-only, the same table `routers/research.py::_hv30_for` reads), `null` when unknown; `dte` `null` never `0`. `GET /campaigns`: the wheel threads with `status`/`symbol` filters, `opened_date` desc with open before closed at the same date, `as_of` request time (written on fill, not captured — documented in the route so nobody "fixes" it), financials gross of commissions (M0 Task 0.4), a pruned candidate still rendering as a leg with `known: false`; `load_campaigns`'s dicts now carry `leg_candidate_ids` for the join. `GET /calendar`: expiries grouped by date over `horizon_days` (default 45, max 365), the `consequence` table exactly as specified (ITM short put `assigned`; ITM short call `called_away` only with stock held, else `assigned`; short OTM/ATM `expires_worthless`; unknown moneyness `unknown` — a real value, never defaulted). Every route's `none` rung is a **200 with explicit emptiness** (`account: null` / `groups: []` / `days: []` + `source="none"` + a plain-words `note`), never a 404 and never zeros. 47 new tests across `tests/test_api_portfolio_{summary,positions,campaigns,calendar}.py`, plus shared fixtures in `tests/conftest.py` (`seed_portfolio_snapshot`, `seed_position_snapshot`, `seed_journal`, `seed_campaign`, `seed_assigned_campaign`, and the `short_put`/`short_call`/`long_put`/`stock` builders) that M4 reuses. `docs/web/openapi.json` and `web/lib/api-types.ts` regenerated (M0 Task 0.5's freshness test green). Gate: `python -m pytest -q` (2043 passed), `ruff check .`, `mypy src` all green. **A verification pass (2026-09-10, independent audit post-build) reproduced the full gate exactly as claimed and confirmed every artifact, then found and fixed four defects in the built code** (each with its own regression test, 47 → 53 across the four files, suite 2049): (1) `GET /positions`' `_stock_leg` called `storage.campaigns.adjusted_cost_basis_for` — which opens the storage engine's read-write `session_scope` from inside the API process — as its *primary* path, inverting the read-only-engine invariant the route itself documented; the read-only query is now primary (mirroring `adjusted_cost_basis_for`'s newest-open-assigned-campaign rule, also fixing a latent `MultipleResultsFound` on two assigned campaigns for one symbol); (2) `OptionLeg.right`/`strike` fabricated `"C"`/`0.0` for snapshots that carried neither and computed `moneyness` against the fabricated pair — both now `null` and `moneyness` requires all three of spot/right/strike; (3) the calendar's horizon gate used a UTC cutoff while its `dte` measured ET — two clocks in one route; both now ET; (4) `GET /campaigns` read the never-pruned `campaigns` table unbounded — now capped by a `limit` query param (default 50, max 200), the same discipline `load_campaigns` and the other list routes follow. **M3 (Tasks 3.1-3.6):** the `/portfolio` console itself — `Money` (`.hatch` unknown, signed figures, `kind`/`complete` rendered as words, never colour alone) and `FreshnessLabel` (Task 3.1); `PortfolioShell` mounting `SummaryPanel` once above a Positions/Campaigns/Calendar tab bar that never remounts it (Task 3.2); `PositionsPanel`/`PositionGroup` grouping stock and option legs by underlying, both cost bases reported (Task 3.3); `CampaignsPanel`/`CampaignThread` — collapsible wheel threads with a real backend-filtered `status`/`symbol` query, gross-of-commissions financials (Task 3.4); `CalendarPanel` and `RefreshControl` — the expiry grid with consequence text per entry, and the one write this page offers, a one-click `POST /commands{kind:"refresh"}` with no confirmation dialog (Task 3.5); the nav flip (`portfolio.available: true`) plus doc updates (Task 3.6). Every panel self-fetches its own route; what each reads from its response differs (`SummaryPanel` alone reads both `source` and `degraded`, `CampaignsPanel` reads neither — `CampaignsResponse` carries only `{as_of, campaigns}`). A whole-branch cross-cutting fix pass (2026-09-10) then closed six Important findings the six tasks' individual reviews couldn't see: `RefreshControl` now self-fetches `GET /options/controls` for the real `drain_healthy` instead of a hardcoded `true`; all four panels poll every 30s so the freshness label doesn't freeze at mount; `CampaignThread`'s `net_premium`/`adjusted_cost_basis`/`realized_stock_pnl` now pass `Money`'s `complete={false}`, since `/portfolio/campaigns` is documented gross of commissions. |
 | **P4 — Profitability tracker (M4 — the P&L engine — built 2026-09-10, opencode/glm-5.3; M5 — the P&L surfaces — built 2026-09-11, opencode/glm-5.3; M6 — system performance and close-out — built 2026-09-11)** | **M4:** the paired realised-P&L accounting rule now exists once, in `src/reporting/` — a package the web layer may read and the trading path may not import (third, read-only analytics tier, both fence directions asserted in `tests/test_web_fence.py`). **Task 4.1 — the dependency inversion:** `fill_economics` and `classify_outcome` moved **verbatim** out of `src/claude/eval/reconcile.py` into `src/reporting/legs.py` (frozen dataclasses replace the tuples; the one addition is `commissions_complete`, which no existing caller reads). `reconcile.py` imports them from there — the fenced reconciler depends on the neutral read-only module, which the fence allows (`eval/` may import a read-only module; the fence stops it reaching the engine). The four reconcile test files pass **unchanged** at the recorded baseline (150). **Tasks 4.2–4.6 — the builders:** the six P&L schemas (`PnlLeg`/`CampaignPnl`/`PnlBucket`/`PnlSummary`/`EquityPoint`/`EquityCurve`, `src/common/schemas.py` — `PnlLeg.outcome` reuses `VerdictOutcome` so the reporting layer and the outcome ledger share one outcome vocabulary); `build_legs` (one `PnlLeg` per filled candidate, newest first; pruned candidates still produce legs with nulls; paper/live filterable and never silently mixed; assignment read from `CampaignRow.assigned`; `roc_pct` credit-over-collateral, `None` when collateral is unknown; `annualized_pct` `None` at `days_held=0`); `build_campaigns` (wheel threads; stock leg read from `CampaignRow`, never recomputed; `snapshot=None` means every unrealised field `None`, never zero; campaign-less legs land in synthetic per-symbol threads so thread legs always sum to the leg count; marks come from the same `PortfolioSnapshot` the portfolio page renders, and a closed leg's `unrealized_pnl` stays `None` forever); `build_summary` (pure; **raises `ValueError` on a mixed paper/live leg list** — the one raise in `src/reporting/`; `win_rate` `None` with nothing closed; `commissions_complete` is the AND of every leg's flag; best/worst chosen among closed legs only; buckets ordered realised-descending, ties by label); `equity_curve` (one point per `JournalRow`; `gaps` lists missed **trading days** — weekends/holidays are not gaps — never interpolated; `net_liquidation` read through `AccountSnapshot.model_validate` so payload drift surfaces as `None`, never a KeyError; `journal.realized_pnl` surfaces as `premium_cashflow` under its true name; `cumulative_realized` sums legs closed on or before each point). **Task 4.7 — the wheel-scenario suite:** five end-to-end scenarios (CSP expiring worthless, the full wheel with called-away stock, a roll chain, missing commission data, paper-vs-live side by side) with hand-written expected literals, plus the three cross-checks: the ledger and the reporting layer agree on every closed trade (one accounting rule — Task 4.1's whole point), the campaign rollup and the leg sum agree gross-vs-gross, and the gross and net views differ by exactly the commission total. **No routes and no UI** — the `/pnl/*` surfaces are M5. **Its numbers have not been reconciled against a broker statement** — the engine is built and tested against seeded data; a live-verification pass comparing `build_legs` output against IBKR's own fills/P&L report remains outstanding, as it does for the rest of the web platform. Gate at close: `python -m pytest -q` (2141 passed), `ruff check .`, `mypy src` all green. **M5 (Tasks 5.1-5.7, built 2026-09-11, opencode/glm-5.3):** the `/pnl` surfaces — every route a thin renderer over `src/reporting/` (the single accounting rule holds at the API boundary too). **Task 5.1 — `GET /pnl/ledger` + `GET /pnl/summary`** (`src/api/routers/pnl.py` + `src/api/models/pnl.py`): `as_of` is request time (the ledger is computed on read) while `marks_as_of` is the snapshot time behind every unrealised figure, from the same single `read_portfolio` call the portfolio page reads (proven by a test comparing the two responses' stamps); filters echo back verbatim; `build_summary`'s mixed-book `ValueError` becomes a `422 {"reason": "mixed_book"}` answer, never a 500 and never a mixed total, while the ledger may still list both books; `n_legs` is checked at the client boundary against the sum of every campaign thread's leg count (synthetic threads included). **Task 5.2 — `GET /pnl/equity`:** `build_legs` feeds `equity_curve` unchanged; `book=all` allowed here deliberately (a curve is a display choice, not a headline total — the asymmetry with the summary is documented in three places so nobody "fixes" it); `premium_cashflow` never named `realized_pnl` anywhere in the response. **Task 5.3 — `GET /pnl/ledger.csv` + the proxy allowlist:** the CSV is built from the same `build_legs`/`build_campaigns` calls the JSON route uses, with unit-suffixed headers (`credit_usd`, `net_pnl_usd`, `roc_pct`, `days_held`), a `book` column, `None` as an empty cell (never `0`), and a dated `Content-Disposition` filename; the proxy (`web/app/api/[...path]/route.ts`) gains an explicit two-name `FORWARDED_RESPONSE_HEADERS` allowlist (`Content-Type`, `Content-Disposition`) — not a passthrough, with its own pinning test so a copy-all regression fails. **Tasks 5.4-5.6 — the UI** (`web/app/pnl/page.tsx` + `web/components/pnl/{PnlShell,LedgerTable,CampaignRow,LegRow,LedgerFilters,SummaryPanel,BreakdownTable,EquityChart}.tsx`): the ledger grouped by campaign with `<button aria-expanded>` threads; no unknown renders as a zero anywhere (open leg's realised is `n/a`, `win_rate: null` is `n/a`, `marks_as_of: null` renders "no marks available" and every unrealised cell `n/a`, gross qualifier on incomplete commissions); a `422 mixed_book` renders a labelled book-choice group in plain words — a normal situation, not an error state; the equity chart renders gaps as gaps (`connectNulls={false}`), never animates (`isAnimationActive={false}`), reads colours from CSS custom properties at mount, labels `premium_cashflow` under that name, states the start date in words, and mirrors its real props onto `data-series` wrapper elements because Recharts does not expose them as DOM attributes; filters drive the query string so the CSV export link carries the same filters (one composition in `PnlShell`, never two); `Money` reused from `components/portfolio/` in every leg/campaign/summary figure — no second money component; `FreshnessLabel`/`DegradedNotice` are not used on this page (the ledger and summary carry their own `marks_as_of`/`mixed_book` renderings instead). Best/worst legs in the summary link into the ledger tab (filtered to that leg's symbol, the closest cross-reference the ledger's filters expose). **Task 5.7 — nav flip + docs + regen:** `pnl` flipped `available: true` in `_SECTIONS` (every section now available, no note), `tests/test_api_meta.py` updated, `docs/web/api.md` documents all four routes with the `as_of` vs `marks_as_of` distinction and the `mixed_book` refusal, `web/CLAUDE.md` gains the `app/pnl/`+`components/pnl/` layout entries and the proxy-allowlist section, `README.md`/`ARCHITECTURE.md` rows updated, `docs/web/openapi.json` + `web/lib/api-types.ts` regenerated (freshness test green). **Conftest:** the M4 `db` fixture pointed the storage engine at a private `t.db` while the API client read `income_system.db` — invisible while builders were called directly, exposed the moment a route test crossed the boundary — so tests/conftest.py gained a `db` override that rebinds the storage engine to the client's file (via the `client` fixture) plus a shared `seed_wheel` fixture; M4's own suite passes unchanged at its recorded baseline. **The M4 broker-statement caveat still stands:** the engine and now the surfaces are built and tested against seeded data; a live-verification pass comparing the ledger against IBKR's own fills/P&L report remains outstanding. Gate at close: `python -m pytest -q` (2175 passed), `ruff check .`, `mypy src`, `cd web && npx vitest run` (334 passed, 42 files) `&& npm run lint && npm run build` — all six green. **Also fixed in passing (pre-existing flake, exposed at this timezone):** the portfolio calendar tests and the conftest position builders seeded expiries from the local clock while `routers/portfolio.py` measures dte and its horizon gate on the ET exchange calendar — whenever the two calendars straddle midnight (any evening after 8pm ET, or running the suite from a non-ET machine) every default-dte position lands one day past the 45-day horizon and the calendar tests fail on `days[0]`. The builders (`short_put`/`short_call`/`long_put`) and the calendar tests' `_day()`/boundary assertions now derive from `_et_today()` (tests/conftest.py), the same clock the route itself reads. **M6 (Tasks 6.1-6.4, built 2026-09-11):** the score-vs-outcome evidence `src/claude/eval/score_metrics.py` already produced gets its reader, and the two fences this phase leans on are enforced by tests rather than by intention. **Task 6.1 — `GET /pnl/system`:** the one P&L route that reads behind the `src/claude/eval/` fence, and the reason is written down in its own docstring and in `docs/web/api.md` — `CLAUDE.md` already says everything `eval/` produces "is read by a human, never auto-applied," and this route is that human's reader, not a breach of it. It calls `score_outcome_report(since, until)` and returns exactly what it gets (a test spies on the call and asserts exactly one), adds a new `VerdictAgreement` figure computed here from `ledger.load_records(closed_only=True)` (Claude-vs-baseline agreement rate plus each side's win rate, windowed on `outcome_date` the same way the report is), and answers the empty case with the report's own "nothing to correlate yet" note rather than a `404`. `agreement_rate`/`claude_win_rate`/`baseline_win_rate` are `null` with zero closed rows, never `0.0`. **Task 6.2 — the System tab:** `SystemPanel`/`ScoreBucketTable`/`CorrelationTable` (`web/components/pnl/`), wired into `PnlShell` as a third tab with its own since/until window state, independent of the ledger's filters. `SystemPanel` is presentational (a `data` prop, like `EquityChart`) since the shell owns the fetch. Every note in the report renders in full and in order — the read-only "re-derive the scoring config by hand" sentence is why the surface is allowed to exist, and it is not the UI's to paraphrase; a bucket with `n` under 5 is labelled "small sample" in words; `n_closed: 0` renders the note and no tables at all, never empty tables with `n/a` rows; the only controls anywhere on the tab are the two date inputs, asserted by a test that counts every button/input/select in the panel. **Task 6.3 — five new fence tests** (`tests/test_web_fence.py`): no module under `src/api/` can write the verdict ledger or reference the scoring config by filename; the API still writes exactly one table (re-asserting the P2 guarantee, with the same `trading_db.py` exception the existing P2 test already carries, since that module *defines* the write handle rather than using it); `src/reporting/` never touches a DB session; `save_portfolio_snapshot` still has exactly its two intended callers (the monitor and the drain). One real trip surfaced and was fixed during this task: `pnl_system`'s own docstring named the scoring config by its literal filename in prose, tripping the new check even though it was never a code reference — reworded, not weakened, since the fence's point is that the name should be unreachable from `src/api/` by grep. **Task 6.4 — close-out:** re-derived rather than re-asserted — every command failure reason in `src/notify/command_drain.py` (extracted correctly this time, accounting for the multi-line `CommandFailed(...)` calls the milestone's own literal grep missed, same class of gap the P2 close-out log already flagged) appears in `docs/web/commands.md`; `docs/web/openapi.json` and `web/lib/api-types.ts` both regenerate to an empty diff (generated directly from the checked-in `openapi.json` file rather than via `npm run gen:api` against `:8787`, since a live API instance was already running there for other purposes and was left untouched); `README.md`'s layout table and `ARCHITECTURE.md`'s folder guide were already accurate for every P3/P4 module before this pass (confirmed, not re-written). **P3 and P4 are both complete. Not built:** P5 (mobile/responsive shell), operator notes on legs and campaigns, a materialised P&L table, intraday equity history beyond the snapshot retention window, and any Tailscale or remote hosting. **The ledger's numbers have not been reconciled against a broker statement** — every P&L figure across P3 and P4 is built and tested against seeded data; a live-verification pass comparing `build_legs`/`build_campaigns` output against IBKR's own fills/P&L report remains outstanding. Gate at close: see the implementation log in `Web plan/P3-P4-IMPLEMENTATION-PLAN.md` for the exact numbers. |
-| **Web overhaul (Parts 1-6 built; Parts 7-8 and order control not started, 2026-10-13 onward)** | **Part 1 built 2026-10-14** (`docs/superpowers/plans/2026-10-13-web-overhaul-1-foundation-home.md`): the payslip design system (`web/DESIGN.md`), the new shell and Home, and three read-only routes (`GET /portfolio/value`, `GET /pnl/month`, `GET /spreads/positions`). **Part 2 (Trades) built 2026-10-19** (`docs/superpowers/plans/2026-10-19-web-overhaul-2-trades.md`, see "Built (2026-10-19 — web overhaul Part 2)" below). **Part 3 (Portfolio and Activity) built 2026-10-28** (`docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md`, see "Built (2026-10-28 — web overhaul Part 3)" below). **Part 4 (cleanup, honesty and the value gaps) built 2026-11-05** (`docs/superpowers/plans/2026-11-05-web-overhaul-4-cleanup-honesty-value-gaps.md`, see "Built (2026-11-05 — web overhaul Part 4)" above): it deleted the legacy files Parts 2 and 3 left unmounted, removed `GET /nav`, made unknown say "could not read" instead of none, gave the value book its places (the drain note, Needs you, Portfolio, At IBKR) and added route titles and the not-found and error pages. **Part 5 (the stock page) built 2026-11-06** (`docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md`, see "Built (2026-11-06 — web overhaul Part 5)" above). **Part 6 (Research, Universe and search) built 2026-11-06** (`docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md`, see "Built (2026-11-06 — web overhaul Part 6)" above). **Not started, no plan yet (HANDOFF section 5):** Part 7, News, More and How it works; Part 8, the value record (gated on a month of paper record); and order control (cancelling a working order from the web), on its own track with a spec first. |
+| **Web overhaul (Parts 1-7 built; Part 8 and order control not started, 2026-10-13 onward)** | **Part 1 built 2026-10-14** (`docs/superpowers/plans/2026-10-13-web-overhaul-1-foundation-home.md`): the payslip design system (`web/DESIGN.md`), the new shell and Home, and three read-only routes (`GET /portfolio/value`, `GET /pnl/month`, `GET /spreads/positions`). **Part 2 (Trades) built 2026-10-19** (`docs/superpowers/plans/2026-10-19-web-overhaul-2-trades.md`, see "Built (2026-10-19 — web overhaul Part 2)" below). **Part 3 (Portfolio and Activity) built 2026-10-28** (`docs/superpowers/plans/2026-10-23-web-overhaul-3-portfolio-activity.md`, see "Built (2026-10-28 — web overhaul Part 3)" below). **Part 4 (cleanup, honesty and the value gaps) built 2026-11-05** (`docs/superpowers/plans/2026-11-05-web-overhaul-4-cleanup-honesty-value-gaps.md`, see "Built (2026-11-05 — web overhaul Part 4)" above): it deleted the legacy files Parts 2 and 3 left unmounted, removed `GET /nav`, made unknown say "could not read" instead of none, gave the value book its places (the drain note, Needs you, Portfolio, At IBKR) and added route titles and the not-found and error pages. **Part 5 (the stock page) built 2026-11-06** (`docs/superpowers/plans/2026-11-06-web-overhaul-5-stock-page.md`, see "Built (2026-11-06 — web overhaul Part 5)" above). **Part 6 (Research, Universe and search) built 2026-11-06** (`docs/superpowers/plans/2026-11-06-web-overhaul-6-research-universe-search.md`, see "Built (2026-11-06 — web overhaul Part 6)" above). **Part 7 (News, More and How it works) built 2026-11-07** (`docs/superpowers/plans/2026-11-07-web-overhaul-7-news-more-how-it-works.md`, see "Built (2026-11-07 — web overhaul Part 7)" above). **Not started, no plan yet (HANDOFF section 5):** Part 8, the value record (gated on a month of paper record); and order control (cancelling a working order from the web), on its own track with a spec first. |
 | **P5 — Mobile** | A native app is deliberately not built. The web console is responsive since web overhaul Part 1 (phone tab bar, bottom sheets, 44px phone targets on the new surfaces). |
 
 Invariants (see `CLAUDE.md` and `Web plan/P0-P1-design.md` §4.3/§4.7 and `Web plan/P2-design.md` §4.2): the API process holds no
diff --git a/web/CLAUDE.md b/web/CLAUDE.md
index 1ee97e4..9cda05b 100644
--- a/web/CLAUDE.md
+++ b/web/CLAUDE.md
@@ -210,31 +210,17 @@ app/                App Router pages and the root layout
                     `ledger/import` keep their routes, sit in <LedgerShell/> (components/ledger/),
                     lead back with <BackToLedger/> in place of the old sub-navigation, and open a trade
                     in the Sheet. The rail still marks Activity current on them.
-  news/             News thread (docs/superpowers/specs/2026-10-09-news-thread-design.md
-                    §7.6). `/news` mounts <NewsFeed/>: group chips (All / Macro /
-                    Market / Tickers / Earnings / Briefs, `aria-pressed`) and a symbol
-                    filter over GET /news/feed, each post a <NewsCard/>, with
-                    <CalendarColumn/> (GET /news/calendar?days=7: economic events and
-                    earnings, held names marked "held" in words) beside it.
-                    `news/[symbol]` mounts <NewsTicker/>: the latest brief (its chart
-                    inlined from GET /news/posts/{id}), the last 72 h of story clusters,
-                    the next earnings date, and <BriefRequest/>, which POSTs a
-                    `news_brief` command and shows a <CommandReceipt/> (polls the ticker
-                    every 3 s while the request is pending or running). A missing
-                    news.db (`available: false`) reads "The news service has not written
-                    anything yet", never an error. Read-only otherwise.
-  explain/          System Explanation console. Static content - no react-query, no
-                    fetch anywhere on the page - a plain-English walkthrough of how the
-                    pipeline works, adapted from ARCHITECTURE.md's "The pipeline, stage by
-                    stage" section, so
-                    a non-technical reader can visualise the system without reading the
-                    .md files directly. <ExplainShell/> owns one `useState<TabKey>` (same
-                    shape as the old Portfolio and P&L tab bars, since deleted) across eight subtabs -
-                    Overview, Data In, Finding Trades, The Risk Gate, Claude's Role,
-                    Approval & Execution, Watching & Adjusting, This Dashboard - mapped
-                    1:1 to `TabKey`/`TAB_META`/`TAB_ORDER` in `components/explain/types.ts`,
-                    the one place every other piece (tab bar, pipeline map, ties-into
-                    chips) reads labels from so they can't drift apart.
+  news/             News (web overhaul Part 7 put it on the payslip). `/news` mounts
+                    features/news/NewsPage (the frame, the Market card, then <NewsFeed/> "Latest" and
+                    <CalendarColumn/> "This week" in two single-track columns); `news/[symbol]` mounts
+                    features/news/NewsTickerPage (a back link, the ticker, a Stock page link, Refresh,
+                    <BriefRequest/>, then the <NewsTicker/> body: next earnings, the latest brief with its
+                    chart, the name's notes, Recent stories). <BriefRequest/> POSTs a `news_brief` command
+                    and shows a <CommandReceipt/> (the ticker polls every 3 s while it is pending or
+                    running). A missing news.db (`available: false`) reads "The news service has not
+                    written anything yet", never an error. Read-only otherwise.
+  explain/          How it works (web overhaul Part 7): `page.tsx` only mounts features/explain/ExplainPage,
+                    seven static cards of plain English. No request.
 components/          Where new code goes (web overhaul Part 4, HANDOFF D4): `features/`. `components/`
                     keeps `ui`, `shell`, the protected `options` controls, `value` and the survivors
                     below; the earlier idea of folding the domain folders into `features/` was cut.
@@ -698,73 +684,17 @@ components/          Where new code goes (web overhaul Part 4, HANDOFF D4): `fea
                     to Activity, Ledger). The old LedgerNav tab strip was deleted in Part 4. Every
                     view root is one `grid-cols-1` column: a page-level grid with no column template
                     is sized by its widest table and would clip the page on a phone.
-  news/             NewsCard (title, SGT+ET time, headline line with up to 3 inline
-                    source links opening in a new tab, the textbook-vs-actual grid,
-                    the 🧠 read with bull/bear, <VerdictPill/> - verdict as text plus an
-                    icon, never colour alone - book and setup impact, digest sections,
-                    update lines, optional chart), NewsFeed, CalendarColumn,
-                    NewsTicker, BriefRequest (mirrors RefreshControl), `types.ts`
-                    (mirrors src/api/models/news.py and the CardPayload schema) and
-                    `format.ts` (SGT/ET time labels, verdict labels). Plain <img> for
-                    the chart data URI and third-party thumbnails (`no-referrer`):
-                    next/image would need every news host in remotePatterns.
-  explain/          PipelineMap (the "you are here" diagram every subtab mounts at its
-                    top: the five straight-line pipeline stages - data/ideas/gate/claude/
-                    execution - as clickable boxes with the active one aria-current, plus
-                    the watching loop and this-dashboard side nodes below, each a real nav
-                    control via `onNavigate`, not decoration - this is what makes "every
-                    subtab shows how it ties into the others" literally true rather than a
-                    line of copy), PanelShell (the shared per-subtab layout: PipelineMap,
-                    title + dek, freeform children, then TiesInto and SourceRefs - kept in
-                    one place so no panel can forget a piece; runs the full width of the
-                    main pane, no `max-w` cap - a first pass capped it at 70ch for prose
-                    readability, matching the rest of this app's body-text convention, but
-                    that same cap was also squeezing every FactCard grid and RangeBar down
-                    to prose width, so it was dropped for all eight subtabs rather than
-                    left in for some and not others), TiesInto (a reasoned chip
-                    per related subtab - not just a label, a sentence on WHY they connect -
-                    clicking one calls the same `onNavigate` the tab bar and the map use),
-                    SourceRefs ("under the hood": the real file paths behind the plain-
-                    English version, for anyone who wants to go past it), Callout (a
-                    raised-by-lightness box for a hard invariant or notable guarantee -
-                    "no LLM can place an order" - elevation marks it as load-bearing, per
-                    this app's own rule; a `tone` prop - info/positive/caution, default
-                    info - layers a second, deliberate accent on top by REUSING the app's
-                    existing semantic tokens rather than inventing new ones: info=focus
-                    (general emphasis, the app's one existing accent), positive=gain
-                    (a safety guarantee - "paper by default"), caution=unknown (a
-                    limitation or a "not yet automatic" caveat) - each tone also changes
-                    the border treatment, not just the colour, so it still reads without
-                    colour, same rule StageBadge/CheckRibbon already follow elsewhere in
-                    this app), Tag (the small mono uppercase eyebrow a `<FactCard/>` or an
-                    Overview card carries, coloured by the same three-tone palette),
-                    FactCard (one bordered box per scannable fact - a tag, a title, a short
-                    body - what every panel's enumerated content renders as instead of a
-                    bullet list, since a list reads as one undifferentiated block and a
-                    card grid reads as several distinct facts at a glance; an optional
-                    `bodyClass` overrides the default caption-weight body text for a caller
-                    whose content is substantive rather than incidental - reused this way by
-                    `components/options/ReviewPanel.tsx`, the same cross-domain-reuse
-                    convention `pnl/` already follows for `portfolio/Money`), RangeBar (a
-                    labelled 0-100 range - "CSP delta target: 0.15-0.30" against "0.0 (deep
-                    OTM) .. 1.0 (deep ITM)" - GatePanel's strike-targeting visual: the bound
-                    labels sit ABOVE the track rather than inside the filled region, so a
-                    narrow band's own two numbers can never collide into each other, which
-                    a first pass with inline labels did), and one content panel per
-                    `TabKey` (OverviewPanel/DataPanel/IdeasPanel/GatePanel/ClaudePanel/
-                    ExecutionPanel/WatchingPanel/WebLayerPanel) - each panel's prose is
-                    sourced from ARCHITECTURE.md's matching "The pipeline, stage by stage"
-                    section (WebLayerPanel
-                    instead mirrors docs/web/architecture.md's two-engine-model description,
-                    since that mechanism isn't in README.md), built from FactCard grids and
-                    Callouts rather than plain paragraphs wherever the content is a set of
-                    parallel facts (ExecutionPanel additionally draws the four-rung
-                    autonomy ladder as an increasing-fill bar row; WatchingPanel and
-                    WebLayerPanel render their enumerated lists - the monitor's six
-                    triggers, what this dashboard can propose - as a wrapped row of
-                    `rounded-full border-focus/40 text-focus` chips). Every `SourceRefs`
-                    file path is a real path checked against the tree at write time, not a
-                    guess.
+  news/             Restyled in place in web overhaul Part 7: NewsCard (a Card: title, a flag "Critical",
+                    SGT+ET time, the headline line with up to 3 source links that say they open a new
+                    tab, the textbook-vs-actual grid, the explanation in a pressed-sage block labelled
+                    "The news model's reading" (the news model may fall back to a local one, so never
+                    "Claude's" alone), <VerdictPill/> as an outlined ink pill with its icon (a forecast
+                    is not money: never green or red), digest sections, updates, optional chart),
+                    NewsFeed ("Latest": SegmentedControl chips, a labelled FIELD), CalendarColumn (one
+                    card, "This week", that says empty, loading and failed in words), NewsTicker (the
+                    ticker page's body), BriefRequest (the `news_brief` command site, outside G2's
+                    features grep; the secondary Button), `types.ts` and `format.ts`. Plain <img> for
+                    the chart data URI and third-party thumbnails (`no-referrer`).
   value/            The value book (value book Part 6, Section F). ValueCard (react-query on
                     GET /value/book, key ["value","book"]: the ceiling as a sum and a Stub, the
                     breakers as words, the held names with their next exit, the open proposals;
@@ -810,6 +740,10 @@ features/
   search/           Web overhaul Part 6: pages.ts (PAGES, the console's own pages, and `matchPages`: every
                     typed word must match a page's name, hint or words; at most five). The palette is
                     components/search/CommandPalette; the open event is lib/search.ts.
+  news/             Web overhaul Part 7: NewsPage (`/news`) and NewsTickerPage (`/news/[symbol]`), the
+                    frame around components/news/ (see app/news above).
+  explain/          Web overhaul Part 7: ExplainPage and PARTS, How it works as seven static cards, each
+                    with "See it on" links that must be in features/search/pages.ts (a test holds it).
   universe/         Web overhaul Part 6: UniversePage (see app/research/universe above).
   stock-value/      The value book's view of one name on the stock page (value book Part 6, Section G).
                     ValueBlock (react-query on GET /value/{symbol}, key ["value","ticker",SYMBOL]:
````

### Task 11: The da-vinci finish by a fresh reviewer (sonnet, effort high)

**Spawned by the orchestrator as a new subagent with no prior context.** Its prompt: this plan's Global Constraints,
rulings 2-25, `web/DESIGN.md` (the News, How it works and More surfaces, the Buttons rule), "Invoke the `da-vinci`
skill first and run `critique`, then `audit`, then `polish` over News, a ticker's news page, How it works, More and
the rail", "never the live API, never inside `web/`, never on port 3000".

- [ ] **Step 1: The synthetic API.** `mock7` was extracted in A0 to `<S>/p7/mock7.out`. Copy it to `<S>/p7/mock7.py`
  and run it in the background: `python3 <S>/p7/mock7.py` (port 8798). It serves the News feed (a critical macro post
  with its explanation, grid and source links; a digest with a model reading; a plain earnings post), the week's
  calendar (a printed release, one with no forecast, one to come; NVDA held, KO), NVDA's ticker page (a brief, two
  story clusters, next earnings), Research (for the rail and the sectors' count), More and the shell's reads, and
  `/claude/context` as the offline app's empty answer.
- [ ] **Step 2: A scratch build served on 3102.** G4's copy and build in `<S>/p7/build` (keep it), then in the
  background: `cd <S>/p7/build/web && API_URL=http://127.0.0.1:8798 API_TOKEN=mock npx next start -p 3102`. Wait until
  `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3102/news` prints 200.
- [ ] **Step 3: Captures.** Copy `capture7` to `<S>/p7/capture7.cjs`, `mkdir -p <S>/p7/shots`, then
  `node <S>/p7/capture7.cjs <a playwright-core directory from E3> <S>/p7/shots > <S>/p7/report.json`. It captures
  News, `/news/NVDA`, How it works, More and Research at 320, 390 and 1440 px, light and dark, **in chunks by scrolling
  `main`**, and prints per page `hscroll` measured on `main`, the `h2` order and, on a phone, every control in `main`
  under 44 px. Expected (checked in the prototype): `hscroll` 0 everywhere and no `pageErrors`; News `Market`,
  `Latest`, `This week`; `/news/NVDA` `What the news service keeps on NVDA`, `Recent stories`; How it works the seven
  titles in ruling 20's order; More `Theme`, `Monthly income target`, `Credits`; Research `Top opportunities`, `Your
  watchlist`, `Sectors by IV rank`. Under 44 px on a phone: exactly ruling 25's accepted set. Open and look at every
  capture (the rail's outlined Search field at 1440, the sectors' "(7 with history)", the verdict pill in ink, the
  model's reading block, the calendar card, the seven cards).
- [ ] **Step 4: critique, audit, polish.** Start from ruling 25's open finding (the emoji alone above a long title on a
  phone). Fix what they find, each behaviour fix with a test written red first; no new token (a proposal waits for
  the operator); nothing in the protected files; no change to How it works' words without the operator. Record every
  finding not fixed, with a reason, in the Progress log row.
- [ ] **Step 5: Gate and commit.** Every web gate; G1-G5, G7; stop the two background servers
  (`pkill -f "next start -p 3102"`, `pkill -f mock7.py`); remove `<S>/p7/build` by literal path (symlink first).
  Commit `fix(web): da-vinci finish of News, More and How it works` (if nothing changed, record "no change" and commit
  only the log row).

<!-- block mock7 -->
````python
"""A synthetic API for web overhaul Part 7's visual check (Task 11). Never the live one.
News: a critical macro post with the explanation, grid and source links; a digest with a model reading; a plain
earnings post. The calendar: two releases (one printed with no forecast) and two earnings (one held). NVDA's ticker
page: a brief, two story clusters and next earnings; any other ticker has no brief. Research (for the rail's Search
field and the sectors' count), More and the shell's reads. /claude/context is the offline app's empty answer
(no news service yet), so the Market card shows its "no market picture" state."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

AT = "2026-11-07T15:00:00Z"
CTX = json.loads(r"""{"as_of":"2026-11-07T15:00:00Z","available":false,"picture":null,"regime":null,"regime_enabled":true,"suspended_today":false,"limits":[],"leveraged_enabled":true,"leveraged":[{"symbol":"DPST","leverage":3,"calm_fraction":0.6,"stressed_fraction":0.3},{"symbol":"LABU","leverage":3,"calm_fraction":0.6,"stressed_fraction":0.3},{"symbol":"SOXL","leverage":3,"calm_fraction":0.6,"stressed_fraction":0.3},{"symbol":"TQQQ","leverage":3,"calm_fraction":0.6,"stressed_fraction":0.3},{"symbol":"TSLL","leverage":2,"calm_fraction":0.8,"stressed_fraction":0.5},{"symbol":"UPRO","leverage":3,"calm_fraction":0.6,"stressed_fraction":0.3}],"claude_cut_mode":"applied","claude_cut_breaker_tripped_today":false,"account_mode":"paper","calls":[{"kind":"trade_review","label":"Trade review","blocks":["Market picture","Your book","Name notes","News","Candidates"]},{"kind":"roll_review","label":"Roll review","blocks":["Market picture","Name notes","Position","Live quote","System proposal"]},{"kind":"spreads_picker","label":"Spreads picker","blocks":["Market picture (as of build)","Tape","Events","Headlines","Menu"]},{"kind":"news_expert","label":"News expert","blocks":["Facts","Clusters","Market picture"]},{"kind":"eod_journal","label":"EOD journal","blocks":["Market picture","Today's trades"]},{"kind":"scan","label":"/scan","blocks":["Market picture","Name notes","Sector","News","Candidates"]},{"kind":"dossier_builder","label":"Dossier builder","blocks":["Facts","Clusters","Market picture"]}],"dropped":[],"dropped_total":0,"not_reviewed_7d":0,"dossiers":[],"without_notes":[]}""")


def post(pid, kind, title, emoji, **payload):
    base = {"kind": kind, "title": title, "emoji": emoji, "when": AT, "grid": [], "links": [], "updates": [],
            "sections": [], "headline_line": None, "facts_line": None, "explanation": None}
    base.update(payload)
    return {"id": pid, "kind": kind, "subject": payload.get("subject"), "posted_at": AT, "stage": "explained",
            "critical": kind == "macro_print", "silent": False, "has_chart": False, "payload": base}


POSTS = [
    post(3, "macro_print", "CPI hotter than expected", "🔴",
         headline_line="CPI m/m 0.4% vs 0.3% est",
         links=[{"name": "BLS", "url": "https://www.bls.gov/x"}, {"name": "Reuters", "url": "https://r.example/1"}],
         facts_line="Core 0.3% m/m · 3.1% y/y · shelter +0.5%",
         grid=[{"asset": "stocks", "textbook": "🔴", "actual": "🔴 ES=F -1.20%"},
               {"asset": "bonds", "textbook": "🔴", "actual": None}],
         explanation={"headline": "h", "what_happened": "w", "read": "Inflation is re-accelerating in services, which keeps a December cut off the table.",
                      "bull": "core goods cooling", "bear": "shelter sticky", "verdict": "further_downside_likely",
                      "confidence": "medium", "book_impact": "NVDA 165P sits 3.1% out of the money.",
                      "setup_impact": "", "evidence": ["F1"]}),
    post(2, "digest", "Midday movers", "📊",
         sections=[{"title": "Movers", "items": [
             {"text": "NVDA -4.0% on export headlines", "read": "Profit taking after a long run.", "verdict": "priced_in", "links": []},
             {"text": "KO +1.1%", "read": None, "verdict": None, "links": []}]}]),
    post(1, "earnings", "AAPL beats on services", "📈", subject="AAPL", headline_line="EPS 1.64 vs 1.60 est"),
]

ROUTES = {
    "/options/controls": {"as_of": AT, "autonomy": {"level": "full", "label": "Full"}, "rungs": [], "halted": False,
                          "halt_reason": None, "halted_at": None, "mode": "paper", "drain_healthy": True,
                          "drain_last_seen": AT, "pending_commands": 0},
    "/options/approvals": {"as_of": AT, "approvals": []},
    "/system/status": {"as_of": AT, "rows": []},
    "/pnl/target": {"as_of": AT, "source": "none", "target": {"mode": "off", "amount": None, "pct": None, "base": None}},
    "/pnl/month": {"as_of": AT, "book": "paper", "spreads_available": True, "pay": {"month": "2026-11-01", "month_start_value": None}},
    "/claude/context": CTX,
    "/news/calendar": {"as_of": AT, "available": True,
                       "econ": [{"title": "CPI m/m", "scheduled_at": "2026-11-10T13:30:00Z", "impact": "high", "forecast": "0.3%",
                                 "previous": "0.2%", "actual": "0.4%", "surprise_dir": "up"},
                                {"title": "Retail sales m/m", "scheduled_at": "2026-11-12T13:30:00Z", "impact": "high", "forecast": None,
                                 "previous": None, "actual": "1.1%", "surprise_dir": None},
                                {"title": "FOMC minutes", "scheduled_at": "2026-11-13T19:00:00Z", "impact": "high", "forecast": None,
                                 "previous": None, "actual": None, "surprise_dir": None}],
                       "earnings": [{"symbol": "NVDA", "report_date": "2026-11-19", "timing": "amc", "eps_est": None, "eps_actual": None,
                                     "status": "scheduled", "held": True},
                                    {"symbol": "KO", "report_date": "2026-11-12", "timing": "bmo", "eps_est": None, "eps_actual": None,
                                     "status": "scheduled", "held": False}]},
    "/value/top": {"as_of": AT, "available": True, "list_name": "deep_value", "items": []},
    "/watchlist": {"as_of": AT, "items": []},
    "/research/sectors": {"as_of": AT, "sectors": [
        {"sector": "Semiconductors", "count": 7, "change_pct": 1.5, "best": {"symbol": "NVDA", "change_pct": 3.1},
         "worst": {"symbol": "INTC", "change_pct": -2.4}, "avg_iv_rank": 71.2, "iv_rank_count": 7},
        {"sector": "Banks", "count": 4, "change_pct": -0.3, "best": {"symbol": "JPM", "change_pct": 0.4},
         "worst": {"symbol": "C", "change_pct": -1.1}, "avg_iv_rank": 40.0, "iv_rank_count": 1}]},
}


def ticker(sym):
    if sym != "NVDA":
        return {"as_of": AT, "available": True, "symbol": sym, "latest_brief": None, "clusters": [], "next_earnings": None, "request": None}
    brief = post(9, "brief", "NVDA brief: export rules and the data-centre quarter", "📰", subject="NVDA",
                 headline_line="Shares -4.0% after new export rules",
                 explanation={"headline": "h", "what_happened": "w", "read": "The rules cut a small slice of China revenue; guidance already excluded it.",
                              "bull": "data-centre demand", "bear": "more rules", "verdict": "overreaction_likely",
                              "confidence": "low", "book_impact": "", "setup_impact": "", "evidence": []})
    return {"as_of": AT, "available": True, "symbol": "NVDA", "latest_brief": brief, "request": None,
            "next_earnings": {"symbol": "NVDA", "report_date": "2026-11-19", "timing": "amc", "eps_est": None, "eps_actual": None,
                              "status": "scheduled", "held": True},
            "clusters": [{"id": 1, "headline": "US widens chip export rules to more Gulf buyers", "source_count": 6, "last_seen": AT,
                          "links": [{"name": "Reuters", "url": "https://r.example/2"}, {"name": "Bloomberg", "url": "https://b.example/3"}]},
                         {"id": 2, "headline": "Nvidia supplier flags longer lead times", "source_count": 1, "last_seen": AT, "links": []}]}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        path, q = url.path, parse_qs(url.query)
        if path == "/news/feed":
            body, code = {"as_of": AT, "available": True, "posts": POSTS}, 200
        elif path.startswith("/news/ticker/"):
            body, code = ticker(path.rsplit("/", 1)[1].upper()), 200
        elif path.startswith("/news/posts/"):
            body, code = {"as_of": AT, "available": True, "post": POSTS[0], "chart_data_uri": None}, 200
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
    HTTPServer(("127.0.0.1", 8798), Handler).serve_forever()
````

<!-- block capture7 -->
````js
// Captures for web overhaul Part 7, Task 11. Usage:
//   node capture7.cjs <path to playwright-core> <output dir> [base url]
// News, a ticker's news page, How it works, More and Research at 320, 390 and 1440 px, light and dark. The shell scrolls <main>, not the document, so each page is captured in
// viewport-high chunks by scrolling <main>, and the sideways overflow is measured on <main>.
// Never point it at the live API or the operator's next dev on 3000.
const { chromium } = require(process.argv[2]);
const outDir = process.argv[3];
const base = process.argv[4] ?? "http://127.0.0.1:3102";
const PAGES = [["news", "/news"], ["news-nvda", "/news/NVDA"], ["explain", "/explain"], ["more", "/more"], ["research", "/research"]];
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
      report.push({ width, theme, pageErrors: errors });
      await page.close();
    }
  }
  console.log(JSON.stringify(report, null, 1));
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
````

---

## Operator to-dos

1. Before Section B, overturn any of rulings 13-19 you dislike (the News frame, "Latest" and "This week", the news
   model's label, the ink verdict, the ticker page). Before Section C, rulings 20-21 (How it works' seven cards and
   their words). Before Section D, rulings 22-23. After that they cost a rework.
2. After the merge: no restart is needed unless a Python file changed (none is planned); `next dev` recompiles. Fill
   the Restart row either way.
3. Look once at News and How it works on a phone in dark mode, and read How it works' seven cards end to end: they
   are the console's only hand-written account of the system.
4. Housekeeping from the HANDOFF (7.3 item 4).

## Self-review (run by the plan's author, 2026-11-11)

- **Spec coverage.** HANDOFF 5.4 outline and answers: Q4 and Q5 (Tasks 1-2), L4 and S5 News and Q3 (Tasks 3-5), L5,
  S5 How it works and Q1 (Tasks 6-7), L6 (Task 8), S4 and Q2 (Task 9), docs (Task 10), the finish (Task 11).
- **Prototype.** As the Plan written row: every patch was cut from a per-task git history of a prototype that passed
  the web gates at every task, the Python gates on `main` and a scratch build, was rendered against `mock7` at three
  widths in both themes, and was re-applied in order to a fresh copy of `main` for the full gate.
- **Placeholders.** None: every change is a patch; the two scripts are given in full; commands carry expected output.
- **Consistency.** `NewsPage`/`NewsTickerPage` (routes, tests, DESIGN.md, docs), "Latest"/"This week" (components,
  tests, DESIGN.md, capture expectations), "The news model's reading" (NewsCard, test, DESIGN.md, STATUS), `PARTS`
  (ExplainPage, test), "The system in plain English" (pages.ts, More, tests), the six RESOLVED entries (DESIGN.md,
  D3, Task 9's gate).
