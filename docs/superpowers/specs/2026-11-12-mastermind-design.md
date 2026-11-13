# The Mastermind — Claude as the best-informed mind on the book — design

Date: 2026-11-12 · Status: **revision 4 (2026-11-14), for operator review**. Revision 3 moved envelope
repair, book repair and every spreads decision into a prerequisite spec,
`2026-11-13-risk-envelope-design.md` (the **envelope spec**), and adjusted this spec to match (§0.3).
Revision 4 adds long options: Claude's hedge roles, a paper-only put budget for Claude, a shadow
directional track and a premium-cost dimension in §4 (§0.4). Everything below the §0.3 note is
revision 2's text except where §0.3 or §0.4 lists a change.

Revision 1 (commit 6f5317f, same
day) was reviewed by two independent reviewers (Opus and Sonnet), who critiqued it and rebutted
each other. The operator then made four binding rulings (§0.2). This revision adjudicates where the
reviewers still disagreed. It re-verifies every contested fact against the code, git, the logs and
copies of the databases. It rewrites the spec around an **earned autonomy ladder**, an
**envelope repair** prerequisite, **book repair** and a **measurement redesign**. Decisions marked
**OPEN** in §16 are the operator's to make before an implementation plan is written
(superpowers:writing-plans). Nothing here changes the core invariant until the operator rules on it
in writing, as was done for `claude_cut` (2026-10-20/21) and the value verdict (2026-10-28/29).

**Revision 2 in one paragraph.** Revision 1 built a ladder that stopped at "brake plus selector"
and called it safe because it only reduced contract counts. Revision 2 names the destination the
operator asked for: full autonomy, with Claude choosing from menus Python builds and gates. It
states the lines that never move. It replaces "reduce-only" with a classification by risk metric,
and it puts every grant of authority behind pre-registered evidence and a worst-choice replay. It
also finds, and puts first, a problem that exists before Claude has any authority at all: today's
deterministic envelope let stock plus put collateral run at 1.1–1.5× net liquidation (1.3–1.9×
counting leveraged ETFs at their leverage; corrected in revision 3), and its gross cap never fired.
Early phases stay record-only, because there is no evidence yet.

## 0. Changes from revision 1

### 0.1 What changed and why

Reviewer findings are cited as **O** (Opus critique), **S** (Sonnet critique), **OR** / **SR**
(their rebuttals), **R1–R4** (the operator's rulings, §0.2) and **V** (re-verified for this
revision; §2 gives the evidence).

| # | Change | Why | Driven by |
|---|---|---|---|
| 1 | §1 names the destination (full autonomy by menu choice), and §5 lays out the ladder rung by rung, mapped onto `AutonomyLevel` / `promotion_blockers` | Rev 1's ladder had no rung that adds risk and no stated end; a reader would conclude the destination did not exist | O §2.1, S §2.2, R1 |
| 2 | New §3, permanent hard lines: the channel (menu-only), a fixed-terms envelope, a survivability replay, the Rules Engine run twice | The two reviewers' invariants guard different failures; each fails alone | O §2.3, S §2.6, OR §4, SR §3.5, R1 |
| 3 | New §4: "reduce-only" replaced by a risk-metric classification | A covered-call cap raises net delta; a roll veto on a would-own put forces assignment; a nomination adds trades | O §2.2, S §1, R1 |
| 4 | New §6, envelope repair, as a prerequisite phase | Stock plus put collateral ran 1.18–1.44× NLV; `gross_notional_cap` runs only when `vx.active`; there is no slow breaker; the "same bet" cuts are a missing correlated-exposure rule | SR §3.5, S §2.4, OR §1.5, R2, V |
| 5 | New §7, book repair | 93% of NLV is long stock, $436.5k of it underwater, and `min_strike_vs_basis: 1.00` blocks every covered call on it; no lever in rev 1 touched it | O §1, S §4.5, SR §3.7, R2 |
| 6 | §2 evidence corrected | Cut count, value-verdict characterisation, roll-review share and cost offset, `book_context`, calendar source, breaker history | O §1, S §1, OR §1, SR §1, V |
| 7 | New §14, prior rulings: one reopened explicitly, the rest brought back into line | Rev 1 reversed decisions 1, 22, 29/30/34, the 2026-08-10 removals and the 2026-10-14 leveraged-ETF ruling without saying so | S §1, OR §2 |
| 8 | §9: leaner call shape. Debrief, weekly retro and the plan's per-short section dropped; per-decision roll review kept and scored; spreads day-plan pattern reused; per-item validation; apply-time clamp; time-boxed pause | Calls that feed nothing, a removed loop, two opinions on one question, all-or-nothing validation | O §3, S §3.1, OR §5, SR §3.3, §3.8 |
| 9 | §9.1: the brief moves to after the close, plus a pre-open check of the plan's invalidation conditions after the 08:30 releases | 08:30 ET is the CPI/PPI/NFP print time; timing is now chosen on market and information merits, not on quota | S §1, OR §1.4, SR §3.4, R3 |
| 10 | §10 lever decisions: L1 becomes a second input to the `claude_cut` clamp (CSP only, record-only first); L2a dropped; L2b deferred; L3 has no auto veto but has tap-only close proposals; the roll stream is scored; D9 is a record-only shadow | Evidence in §2 and §10 | O §6, S §5, OR §6, SR §5, R1 |
| 11 | §11 measurement rewritten: pre-registration, decision episodes, clustering, placebo, risk normalisation, a fixed valuation rule, Brier against market-implied, honest time-to-evidence, demotion rules with stated false-demotion rates | Rev 1's promotion bar passes a zero-skill lever half the time; its demotion rule demotes a good lever 37% of the time in 6 weeks | O §3.5, §4, S §3.2–3.5, SR §3.6, V |
| 12 | §12 placement: `data/mastermind.db`, a read-only fact layer, `plan_view`, fence tests, and a one-shot process that is its own exception boundary | Rev 1 left the store and the process open; a plan table in `news.db` breaks news-fence rule 1 | O §5, S §4.7, SR §2, OR §1.4 |
| 13 | §15 phasing rewritten: Phase 0 cleanup → envelope repair → knowledge → brief (record-only) → ladder rungs | Matches the above | R1–R4 |
| 14 | §16 decisions rewritten: D1–D9 with converged recommendations and dissent; D10–D21 added | The reviewers' D10–D18, merged and deduplicated | O §6, S §5, OR §6, SR §5 |

### 0.2 The operator's rulings this revision implements (2026-11-12, binding)

1. **End state = the earned ladder.** Full autonomy by choosing from a menu is the destination.
   Each rung has an evidence bar and needs an operator ruling first. Hard lines are permanent. Early
   phases are reduce-only or record-only because there is no evidence yet, and the spec says so,
   along with what is wrong with "reduce-only" as a safety measure.
2. **Envelope repair and book repair are both in this spec.** Envelope repair lands before any rung
   that adds risk.
3. **Brief timing is chosen on market and information merits.** Usage limits are assumed to stop
   being an issue eventually. A governor and an outage fallback stay for robustness, but quota does
   not drive the architecture. An Ollama output never produces a lever value, and degrading to
   Sonnet is not an outage plan.
4. **Edit this spec in place as revision 2**, with this section.

### 0.3 Revision 3 (2026-11-13)

The operator asked to explore a 0DTE layer, an unleveraged-first CSP policy for the 3× ETFs and a
cash reserve, and ruled that those changes come **before** the Mastermind. Two reviewers researched
it, rebutted each other, and the operator made eight rulings. The result is the envelope spec
(`2026-11-13-risk-envelope-design.md`), now a **prerequisite** of this one. Revision 3 moves out of
this spec what the envelope spec owns, and references it back.

| # | Change | Where |
|---|---|---|
| 15 | **Envelope repair moved out.** The gross cap, the tech-linked group cap and stacking rule, the slow breaker and the survivability harness are specified in the envelope spec §3.4. They are now a beta **shock-loss budget (S10) by full revaluation, with a glide path**, an unconditional **exposure-weighted** gross backstop, a leverage-weighted group cap, and a slow breaker that **spans books** (it reads account NLV, which includes spreads P&L, and a trip stops spreads entries) | §6 here is now a pointer |
| 16 | **Book repair moved out.** The `min_strike_vs_basis` ruling (with a leveraged class floor), the tap-only repair proposals and the discretionary-buy display are in the envelope spec §3.7. Claude's part, which proposals to surface and endorse, stays here | §7 |
| 17 | **§4 risk measures changed.** Collateral and gross are exposure-weighted (leveraged ETFs at their leverage). The index −10% measure is S10 by full revaluation. A **nonlinear-gap measure** (G10 one-day gap, P20 two-week path, leveraged daily reset) is added, so choosing a leveraged lot over its unleveraged equivalent classifies as risk-changing | §4 |
| 18 | **§5.1:** envelope levels are never a rung. The allocation choice inside the envelope (leveraged vs unleveraged) is R3. The **spreads picker** (its menu has an inside strike) is an **R4-type grant, grandfathered in paper, record-only in any live plan**; its record pilots this spec's measurement machinery and is never evidence for a wheel rung | §5.1, §11.9 |
| 19 | **Spreads: no longer "unchanged".** It gets the envelope spec's fixes (static macro calendar into `risk.events`, the account-halt link, NLV-based caps, a cost standard, the skipped backtest) and, on an operator ruling, a move to SPXW that frees SPY for the wheel | §13, D5 |
| 20 | **§2.3 corrected.** Gross ran 1.08–1.53× nominal (peak 1.53 on Nov 5, not 1.44) and 1.30–1.88× leverage-weighted | §2.3, §4 |
| 21 | **Phasing.** The envelope spec's phases E0–E2 precede this spec's Phase 2; its Phase 1 is replaced by a reference; risk-changing rungs need E2 complete | §15 |
| 22 | **Decisions.** D13 and D14 move to the envelope spec (E4–E5, E12, E14–E15). D5, D12 and D19 are amended | §16 |

### 0.4 Revision 4 (2026-11-14): long options

The operator asked: *"what about buying puts and calls as a trading strategy? … I wanted the
mastermind to be able to buy puts when relevant."* Scope, his choice: index hedges and directional
bets; event protection and stock replacement are out. Two reviewers researched it and rebutted each
other (O3, S3, O3R, S3R). The operator's four rulings are recorded as OR9–OR12 in the envelope spec
§0.1. The deterministic hedge (a Python-run Nasdaq-100 bridge during the glide, earning no envelope
headroom) is specified there, in §3.10. This spec holds Claude's part.

**The operator's choice, stated plainly.** Both reviewers recommended that Claude get no automatic
authority to buy puts, because timing a hedge cannot be shown to be skilful in any useful horizon
(decades of down legs) and buying when stress shows up is the costliest time to buy (0.20 on the
dollar at VIX 25–35 against 0.43–0.70 in calm states, S&P 1990–2026 [M]). The operator chose to give
Claude a **small automatic put budget in paper only**, knowing it cannot be proven skilful, to test
his "when relevant" hypothesis. It is a written exception to the core invariant, paper-applied,
record-only in live, and never promoted to live by this spec.

| # | Change | Where |
|---|---|---|
| 23 | **New hard lines 9–11**: long options earn no headroom; premium only from operator-set fixed budgets; no live opening buy caused by Claude | §3 |
| 24 | **§4 gains a premium-cost / carry dimension.** A purchase is risk-reducing only if no worse on every risk measure **and** within the deterministic baseline's spend for the period (B0) **and** outside the stress block. Spend above B0 inside a fixed budget is **changing (cost)**. Lifting or skipping a hedge is changing | §4 |
| 25 | **R5 split** into R5-R (book-repair proposals) and R5-H (hedge roles C1–C4); **HP, Claude's paper put budget**, a new exception row; **Track D** outside the ladder | §5.1 |
| 26 | **Claude's hedge roles** (C1 daily stance, C2 "buy puts now" tap, C3 "cash in / roll down" tap, C4 shape at scheduled rolls) | §10.6 |
| 27 | **The paper put budget (HP)**: Python's menu, a fixed unit of 0.1% of NLV₀ a month, at most 3 banked; Claude chooses when and which item; **exempt from the VIX ≥ 25 block** (paper only, reasons given); measured against the schedule, random timing and no hedge; a breaker | §10.7, §11.12 |
| 28 | **Track D, directional, shadow only**: Python menus, a fixed premium per idea, controls (random direction, always-call, the same view in stock), a bar of ≥ 250 ideas and ≥ 120 market-day clusters; the news `overreaction_likely` verdicts and the spreads plan's bias scored forward from now | §10.8, §11.13 |
| 29 | **Measurement**: long-option items valued from captured quotes, not stored IV; hedge, paper-budget and Track D records; honest time to evidence | §11.3, §11.6, §11.11–11.13 |
| 30 | Placement, interaction, prior rulings, phasing, decisions H11–H16, unverified | §8.1, §9.1, §12–§17 |

## 1. Intent and destination

The operator's vision, verbatim: *"I ultimately envision the system to be fully autonomous, with
claude having a significant stake in the decisions being made. What i mean by this is that Claude
has market information, optimal trade decisions, and the deterministic python calculations to
support its final decisions."*

Read literally, that is three inputs and one output:

- **Inputs:** market information; the trade decisions Python has computed and gated; Python's
  deterministic calculations.
- **Output:** Claude's final decision.

So the end state is: **Python computes every number and builds every feasible alternative, Claude
chooses among them, and Python re-validates the choice before anything is sent.** That is literally
"Claude makes the final decision", inside a menu. The repo already runs this pattern twice:

- The spreads picker (`src/spreads_ai/`). Its menu includes a strike *inside* the baseline, which
  carries more risk. Revision 3 classifies it as an R4-type grant, grandfathered in paper (§5.1).
- The value verdict. It can make the value book auto-buy, and through capital release it can close
  wheel puts.

**The destination:** `AutonomyLevel.FULL`, with Claude at the top rung of every lever in §5. Python
builds, values and gates every alternative. Claude chooses one. The Rules Engine re-gates it at
decision time and again at send time. No human taps.

**How we get there:** one rung at a time, each a written exception ruled on by the operator. Each
rung is earned by a pre-registered record (§11), and each sits behind an envelope Python can show
is survivable even if Claude picks the worst allowed option every time (§3). The pace is set by
evidence, and §11.6 is honest about how slow that evidence is.

**What the Mastermind is.** A human operator cannot, every morning:

- read every open position's live P&L, assignment odds, collateral and correlation at once;
- recall every trade this system made on a name, in this regime;
- read every filing and headline for ~40 names;
- hold a 45-day event calendar against every expiry;
- state probabilities and be scored on them without fatigue.

Claude can, if it is given that knowledge (§8) and asked the right questions (§9). Its edge is
breadth, recall, consistency and calibration, not prediction magic.

**What the evidence says so far** (§2). Claude's one demonstrated contribution, the nine "already
holds the same bet" cuts, is a correlated-exposure rule the engine lacks. That rule should be
codified (envelope spec §3.4.4), and Claude measured on what is left over. Nothing yet shows Claude's entry
judgment, because the test has never been run: the verdict rubric defaulted to "sell" and nothing
read the result.

## 2. Evidence: where Claude and the book stand (audit 2026-11-12, corrected)

Sources: copies of `income_system.db`, `value.db`, `spreads.db` and `news.db` taken to scratch,
`logs/`, `git`, and the code. The account is IBKR **paper** (the `DUQ` prefix; CLAUDE.md "paper
first"), so every record below is paper-fill evidence. Log times are local (+0800).

### 2.1 Claude's inputs and outputs

| Finding | Evidence |
|---|---|
| Claude is consulted only on what passed the gate | The scan logged "0 Claude reviews" 31 times on Nov 10–11. There were 2 trade-review calls from Nov 4 to Nov 11 (one on Nov 4, one on Nov 9). From Nov 3 to Nov 11 there was **one** new CSP candidate (HOOD 75P, Nov 9); the `candidates` rows on Nov 10–11 are rolls. |
| The persistent memory is write-only | `claude_memory` has 861 rows. 778 are deterministic "buy" rows with no outcome; 56 of the other 83 have one. `_load_memory` (`scan.py:189`) has no production caller; `_persist_memory` still runs. |
| `book_context` shows positions, not the book's state | It prints open short options **with spot and ITM/OTM**, shares **with cost only**, stop-outs of the last 5 days, and book net delta. It covers only reviewed names and their related names (`src/claude/book_context.py`). Missing: share spot and unrealised P&L, collateral, concentration, drawdown. Unrealised across the book was −$134.7k on $645.8k NLV (Nov 11 20:45Z). |
| Static knowledge is stale | `_UNIVERSE_CONTEXT` (`strategist.py:24-110`, ~1.7K tokens) carries June prices (QQQ ~$470 vs $675, GOOGL ~$165 vs $294, SOXL ~$25 vs $66) and stale IV-rank prose ("RGTI … wait for >40"). The N17 spot override (`strategist.py:532`) replaces the price for *reviewed* names only. HACK and IGV are in the universe but have no row. |
| Injected value numbers are wrong, and the cause is Python's fair value, not a units bug | VALUE NOTE GOOGL $16.29 and META (deep_value) $18.00. Python's own fair values are $10.86 and $12.00. Claude's uncapped values were $112.60 and $293.06. The 1.5× cap (`claude_valuation.py`) clipped Claude's number to 1.5× a broken baseline: `clamp_bound` is set in 5 of 31 current verdicts. There are 22 `value_effective` rows with a margin of safety below −500%. META quality_growth's Python fair value is $200.57 against ~$628, so the fault may be a method, not units. **Root cause unverified.** |
| The verdict is a rubber stamp, and its P&L is the system's | 75 of 76 verdicts since Oct 1 are "sell" (`strategist.py:716-718`: 'Default to "sell" unless…'). Closed sell-verdict rows: all dates, 53 closes, −$2,788; since Oct 1, 50 closes, −$2,996 (48 closed early at −$4,902). Every candidate got "sell", so these P&Ls measure the deterministic system, not the verdict. Claude's priority equals Python's rank in 88 of 95 comparable rows. |
| Other input defects | Picture story S19 is titled "term structure inverted"; the picture's own text says contango (VIX/VIX3M 0.91). The Oct CPI and Core CPI `actual` were never recorded; the actuals poller looks back 2 days only (`collectors.py:255-262`), so a miss is permanent. Dossier prose is budget-starved ("29 names wait", Nov 10) and undated in the prompt. |
| The calendar is limited by its source, not a setting | `econ_events` comes from ForexFactory's `ff_calendar_thisweek.json` via `this_week()` (`collectors.py:227`); its latest `scheduled_at` is Nov 13. `_EVENT_DAYS = 7` in `picture.py` sits on top of that. `news.db earnings_events` runs to Nov 19. A 45-day horizon needs a new feed: a static FOMC/BLS/BEA schedule plus the earnings dates the blackout already uses (that provider's horizon is unverified). No free source publishes consensus five weeks ahead. |
| Headless calls are tool-less by design | `claude.max_turns: 1`, with WebSearch/WebFetch disallowed (N3 hardening, `config/examples/settings.yaml`). Timeout 180 s. |

### 2.2 Claude's levers so far

| Finding | Evidence |
|---|---|
| `claude_cut`: **9 real cuts, 31 → 12 contracts** | `sizing_actions` has 10 `claude_cut` rows, 34 → 15. Row 29 (CRWD 240P) is 3 → 3 ("a later review kept the deterministic size"), so it is not a cut. Three cut lots never filled (TQQQ rows 36, 38, 39) and are valued 0. Two are pending (NVDA 205P Nov 13; CRWD 225P Nov 20). |
| **4 cuts carry P&L: $2,311 avoided in net**, in about three episodes, one regime | Avoided: TQQQ 65P +$699, CRWD 235P (Nov 20) +$2,074. Forgone: CRWD 235P (Nov 6) −$268, HOOD 75P −$194. Mean $578, SD $1,090, t = 1.06, two-sided p ≈ 0.37. Four rows are TQQQ on one day (Oct 28). By decision 22's own standard ("one week of four exits is not evidence"), this proves nothing yet. |
| Every cut rationale is "the book already holds the same or a correlated bet" | Rows 15, 30, 36–39, 46, 48, 55. The TQQQ cuts reacted to fills opened earlier the *same day*, which is live-book stacking. The engine caps risk units per ticker and per sector, but it has no cap on the `regime.tech_linked` group (23 names). Claude's prompt is compensating for a missing deterministic rule. |
| Rev 1's "the value verdict works as a brake" is wrong | Of 30 `value_effective` rows with a Claude verdict, 26 match Python's verdict and 27 keep Python's effective verdict. There are 4 disagreements. **Two are attempted upgrades:** ADBE deep_value (Python WATCH, Claude READY, **effective WAIT**) and AVGO quality_growth (WAIT → Claude WATCH → effective WAIT). ADBE's effective verdict fell *below* Python's because the price gate is computed on **Claude's** fair value ($323 vs Python's $390; `effective.py:83-92`): Claude's number contained Claude's verdict. Two are downgrades to NO: ISRG (Claude's own uncapped fair value, $47.60 vs Python's $142.23) and META deep_value (Claude's uncapped $293 is still far below a ~$612 price). Where Python's baseline is not broken low, Claude's fair value is below Python's in 22 of 26 rows. Claude is a conservative valuer that mostly passes Python through, behind a cap that imports Python's bugs. |
| Ranking has nothing to rank | 97 of 113 review calls since Oct 15 carried one candidate. Among 9 comparable multi-candidate runs, Claude reordered 2 (in five months). Contention lies *between* scans: on all 9 days with ≥ 2 new CSPs, each came from a different run. `csp_allocation_limit` fired 3 times and `regime_budget` once in 1,301 gate rejects. Earnings blackout and IV/RV gates dominate. |
| Roll reviews: 33.5% of calls, 15.6% of notional cost, a defect that is now fixed | `scripts.claude_usage` from Oct 15: 268 of 800 calls, $3.06 of $19.65. The 53 calls on Nov 11 came from a repeat-fire bug, which commit `9da9e8a` fixed (one decision card per short per action per ET day). **The share must be re-measured after that fix**, and roll reviews are not a cost offset (rev 1 §10 was wrong). 607 of 617 `roll_alerts` since Oct 15 store no recommendation, but the review is shown on the Telegram card (`intraday.py:548-575`). |
| The roll stream is the densest decision stream, but clustered | 211 `roll_decision` rows since Oct 15, over 82 short-days and 33 distinct shorts. Score it clustered by short. |
| The spreads book already runs a daily Opus plan | `spread_day_plans`: 23 days, posted ~09:33 ET. 21 written by Opus ($0.04–0.056, 9.6–21.6 s, ~1.5K-token prompt; the first four days cost $0.18). Oct 14 failed **with the Sonnet fallback** (`cli_error`). Oct 30 was written by `ollama:qwen3.5:4b` and stored with `failed=0`. `bias` was neutral on 18 days, bearish on 4 and never bullish. 12 picks: 4 "A" (baseline), 8 skip, never a riskier letter. |
| Usage-limit refusals were rarer than both reviewers counted | Production logs show CLI "usage limit reached" on two local dates: Oct 30 (18 lines, across review, roll, news and EOD kinds) and Nov 5 (2 lines). The reviewers' larger counts included `test.log` and the launcher's "Ollama not reachable" warnings (9 lines). Under R3 this does not drive the design. |
| Total Claude spend is small | $19.65 notional over 800 calls from Oct 15 to Nov 12 (~$0.70 a day). News takes $10.42 of it. |

### 2.3 The book and the envelope

| Finding | Evidence |
|---|---|
| The book is 93% long stock | Nov 11: stock market value $603.1k on NLV $645.8k (93.4%), up from 67% on Oct 13. AMD $166.6k (25.8%), GOOGL $147.0k (22.8%), NVDA $104.8k (16.2%): 64.8% of NLV in three names. The value book holds nothing (`value_orders` is empty). No call is held. |
| $436.5k of the stock is underwater | BAC, GOOGL, HIMS, MARA, NVDA, PLTR and SOXL: market value $436.5k, basis $567.6k, unrealised −$131.0k. SOXL's basis is $153.35 against $66.11. |
| Underwater stock earns nothing, by policy | `min_strike_vs_basis: 1.00` (N18): "an underwater holding generates NO covered calls". `strike_below_basis` was the top covered-call reject: 21,362 contract rejections since Nov 1 (25,678 all time). |
| Stock plus put collateral ran above NLV for a month | Last snapshot of each session, (stock + short-put strike × 100) / NLV: **1.08–1.53, mean 1.31**, Oct 13–Nov 12; it ran 1.46–1.53 all session on Nov 5. Counting TQQQ and SOXL at 3×: **1.30–1.88, mean 1.53**. (Revision 2 said "1.18–1.44, peak 1.44"; corrected in revision 3, envelope spec §2.1.) If every put open on Nov 11 were assigned, gross long would be $810.8k (1.26×). A −10% SPY move would cost about 22% of NLV by full revaluation (envelope spec §2.1). |
| The gross cap never fired | `max_gross_notional_pct: 100.0`, but the check runs only inside `if vx.active and is_csp` (`risk_engine.py:527`). `vx.active` requires `value.book.enabled` (`books.py:115`). No `risk_verdicts` row has ever carried `gross_notional_cap`. The private `config/value.yaml` now says `enabled: true`, yet a HOOD 75P passed on Nov 9 at ~1.39×. Whether the running daemon had the book enabled at the time is **unverified**. Either way, the wheel had no working gross cap. |
| The breakers tripped, then the slow one was removed | `approval.log` shows 15 trip lines on 11 local dates from Oct 12 to Nov 11: the daily 3% loss leg and, until Nov 5, a drawdown leg **from the all-time high-water mark** (Oct 12, 23, Nov 3, 4). Commit `544e32e` (Nov 5) replaced it with a rolling 3-session 6% window because a standing drawdown re-halted every morning. NLV went from $784.6k (Oct 13) to $645.8k (Nov 11), −17.7%, with a $577.5k session-end low on Nov 5. A slide of under 2% a session never trips 6% in 3 sessions. The ledger records no deposit or withdrawal in the window (one $824 interest credit). A trip halts new openings; it does not stop assignments, which is how stock grew while NLV fell. |

**Conclusion.** Rev 1 said "the bottleneck is knowledge and placement, not the model." That holds
for the reviewer's inputs. But the larger findings are not about Claude:

- the deterministic envelope let gross exposure run at 1.1–1.5× NLV;
- the one slow breaker was removed on Nov 5;
- the book's loss sits in assigned and manually bought stock that policy forbids from earning
  premium.

Envelope repair and book repair (now the envelope spec, §6–§7 here) are where the money is. Claude's
knowledge layer (§8) is where its future authority is earned.

## 3. Permanent hard lines

These never move, at any rung. Changing one is a change to the core invariant and needs its own
ruling.

1. **The Rules Engine is the only path to an order.** It runs at decision time and again at send
   time on a fresh quote. Orders are `LimitOrder` at mid, on qualified contracts, quoted through
   `req_fresh_mkt_data`.
2. **The channel: Claude never types a number that reaches an order.** It chooses one item from a
   menu Python built, valued and gated. An integer in `0..B` against a Python-computed `B` counts as
   such a menu (`claude_cut`).
   - The value book's clamped continuous drivers are the one existing departure. They are
     **grandfathered under the second written exception until converted** (D15). GOOGL's capped
     $16.29 shows why a continuous number clamped to a multiple of a Python estimate is the weaker
     pattern.
3. **The envelope is set in fixed terms**: dollars, risk units, % of NLV, contract counts. It is
   never set as a multiple of a Python estimate. A menu may be built *relative* to Python's baseline
   (one notch inside, one notch out), but the envelope that bounds every menu may not be.
4. **Survivability before every grant.** Before any rung is granted, Python replays the history with
   a decider that **always picks the most aggressive allowed option**. It also computes the
   analytic worst case: every slot filled by its worst allowed item, under an index −10% shock and a
   single-name −40% shock (revision 3: and the G10 / P20 gap scenarios, §4). The book must stay
   inside operator-set drawdown and margin bounds in both. The test runs on the deterministic
   envelope first (envelope spec §3.4.6). On today's numbers it would fail.
5. **Breakers are deterministic and human-held**: the daily loss leg, the drawdown leg, the slow
   breaker (envelope spec §3.4.5, spanning the wheel and spreads books), the kill switch and
   `LIVE_TRADING`.
6. **Humans only:**
   - `apply_live`, every rung change, the envelope, config, the universe, risk limits and the
     primary metric;
   - Claude never edits its own envelope, metric, breakers or promotion state;
   - the evaluation machinery never feeds a gate, a weight or a size (the existing `eval/` fence).
7. **Fallback = Python's baseline.** That covers an Ollama-produced, malformed, ungrounded, stale or
   missing output. Ollama never produces a lever value or a plan.
8. **Isolation.** A call that decides has no tools. Untrusted text (news, web) never sits in the
   context of a tool-bearing call that can also decide.
9. **Long options earn no headroom** (revision 4). Every admission test reads S10_gross, which
   counts no long option from any source: the hedge book, Claude's paper puts, a Track D item if one
   is ever traded, or a put bought by hand in TWS (envelope spec §3.4.1). S10_net is display and
   survivability only.
10. **Premium is spent only from fixed-terms budgets the operator sets** (revision 4): the bridge's
    and Claude's paper unit. Claude never sets a budget, a unit, a contract count, a strike, a price,
    a tenor or an exit for a bought option. It chooses a menu letter, or "no buy".
11. **No live opening buy is caused by Claude under this spec** (revision 4). Claude's paper put
    budget is record-only in live, refused by the Rules Engine under `LIVE_TRADING=true`; going live
    needs its own later ruling.

## 4. Risk classification, not "reduce-only"

**Why the early phases are reduce-only or record-only.** There is no evidence yet. That is the only
reason, and it is a good one. But "reduce-only" is a poor *safety* argument, for five reasons:

1. **Fewer contracts is not less risk.**
   - Withholding a covered call on underwater stock raises net delta and removes the premium
     cushion. It is a bet on a rally.
   - Vetoing a roll on a would-own put forces assignment at the old strike (`roll_policy.py`). On a
     leveraged ETF it forces exactly what the 2026-10-14 ruling avoids.
2. **It forbids the actions that reduce risk most.** A covered-call overlay, a hedge and a trim all
   *add* orders.
3. **Its evidence is lopsided.** A brake earns "dollars avoided" in a sell-off and "dollars forgone"
   in a rally. A record built only from brakes measures the regime and can never justify a rung that
   adds risk.
4. **It is not free of attack.** A poisoned headline that pushes `no_adds` across the universe idles
   the income engine. That is an availability attack, so every cut-type lever keeps a breaker on the
   share of flow it zeroes (as `claude_cut` does).
5. **It credits the safety to the wrong thing.** The book went to 1.53× NLV with no Claude authority
   at all. Safety comes from the envelope, not from the direction of the lever.

**The replacement.** For every lever application, Python computes the book after the action on a
fixed set of risk measures (revision 3: the definitions are the envelope spec's §3.4):

- net dollar delta;
- **S10**: the loss under a SPY −10% move, beta-scaled per name, by **full revaluation**, with
  leveraged ETFs at leverage × the governing index's beta. A delta-linear measure credits a covered
  call with about three times the crash protection it gives;
- **the nonlinear-gap measure**: **G10**, a one-day index −10% gap with leveraged ETFs at their
  leveraged move (capped at −100%), and **P20**, a −20% index path over 10 sessions with daily reset
  on leveraged ETFs;
- committed collateral, **exposure-weighted** (leveraged ETFs at their leverage);
- gross notional / NLV, **exposure-weighted** (U_ew);
- risk units per name, per sector and for the tech-linked group (leverage-weighted);
- revision 4: **T20** (the tech-linked group −20%) and **S-SMH**, the envelope spec's §3.4.3 tech
  scenarios;
- revision 4: **premium committed and carry**: the debit of any bought option, and its expected
  annualised carry per protected point of S10 and T20. It ranks non-dominated items and enters the
  record. It never gates as a multiple of a Python estimate (§3 line 3).

An application is **risk-reducing** only if it is no worse on every measure. Otherwise it is
**risk-changing**, whatever the contract count.

**The premium-cost rule (revision 4).** Every risk measure above improves when a put is bought, so
under the risk measures alone "buy fifty puts" would be risk-reducing. The reviewers' two halves are
merged (O3's cost dimension, S3R's baseline-spend gate). An application that spends premium is
**risk-reducing** only if all three hold:

1. it is no worse on every risk measure;
2. its spend is within the deterministic baseline's own spend for that period (**B0**: the bridge's
   scheduled purchase, or zero where no programme runs);
3. the stress block is clear (envelope spec §3.10.6).

Spend above B0 but inside a fixed-terms budget is **risk-changing (cost)**. Spend above every budget
is refused, not classified. Lifting, skipping, shrinking or delaying a hedge against its baseline
raises every risk measure at once, so it is **risk-changing**. The class depends on the baseline,
which is why the baseline is fixed first (the bridge's schedule). The class decides the evidence bar (§11.5) and
whether the rung needs envelope repair first (§15). Without G10 and P20, a TQQQ lot replacing equal
beta-dollars of QQQ reads as reducing: the same delta and linear loss, less collateral. With them it
is risk-changing, as its gap and decay tail say it should be.

| Action | Class |
|---|---|
| Cut an opening CSP's size | reducing |
| Close a short put early | reducing |
| A covered call written on held shares | reducing on delta and the −10% loss; it caps recovery (judged against the D11 metric). By full revaluation its crash protection is about its premium |
| Choose a leveraged lot over the unleveraged equivalent at equal beta-dollars | **changing** (worse on G10 / P20) |
| Withhold a covered call | **changing** (raises delta) |
| Veto a roll | **changing** (forces assignment) |
| Nominate a name for the scan | **changing** (adds trades) |
| Size above the deterministic size | **changing** |
| A strike nearer the money | **changing** |
| Revision 4. The bridge's scheduled default hedge (Python; no Claude) | reducing, within B0 |
| Another hedge item at the same scheduled date and spend, no worse than the default on every scenario (C4) | reducing, within B0 |
| A tapped "buy puts now" above the schedule, inside the bridge's budget (C2) | **changing (cost)**; a human taps |
| Claude's paper-budget buy (HP) | **changing (cost)**; reducing on every risk measure |
| Skip, shrink, delay, lift or early-monetise the bridge's hedge | **changing** |
| A hedge larger than 50% of the book's beta-weighted delta | refused (it would turn the book short) |
| A long call on a name or factor the book is already long | **changing**: the same bet, added |
| A long put on the book's own factor (the index or a tech-linked name) | a hedge, not a directional bet: it routes to the hedge roles and never reduces S10_gross |

## 5. The earned autonomy ladder

### 5.1 The rungs

Each rung is a written exception, ruled on by the operator, built as one clamped Python function,
applied in paper first and record-only in live (`apply_live: false`) until the record has been
read. Every rung has a breaker and a paired counterfactual on every decision episode.

| Rung | Claude's authority | Menu / bound | Class | Evidence bar before the grant (§11) | Ruling needed |
|---|---|---|---|---|---|
| **R0 shadow** | Answers on every decision episode: candidates, ladder-blocked and regime-trimmed lots, roll decisions. Nothing is applied. | Python's menu for the episode, every item shadow-valued | none | Phase 0 done: rubric honest, versions stamped | None beyond this spec |
| **R1 cut** (exists) | Lowers an auto-opened CSP's contracts. From Phase 4 the plan's cap becomes a second input: `min(deterministic, review_cut, plan_cap)` | integer `0..B` | reducing | Exists for the review cut. Plan input: ≥ 60 sessions record-only, it binds where the review did not (or the plan-blind holdout shows the reviewer ignoring the plan), it beats the matched random cut, and the claim audit passes | D1 |
| **R2 select** | Chooses one item from a Python-built menu whose items are all ≤ the baseline on every §4 measure: the baseline, one more conservative strike or size, skip. Later, a cross-scan best-of-day allocation (only if the regret test in §10.2 finds it material) | menu ≤ baseline risk | reducing | ≥ 100 decision episodes over ≥ 1 down leg and ≥ 1 up/calm leg of ≥ 10 sessions; beats the random, dumb-rule and always-skip controls at the lower bound of a day × name clustered interval on rules-based shadow P&L per risk-unit-day; same sign under expiry valuation | Third written exception, naming the menu |
| **R3 size within a cap** | Sizes above the deterministic size, up to a fixed cap in risk units. Never above the unscaled hard caps or the **regime-scaled ceiling**: easing the regime is D9, never granted here. Revision 3: also **the allocation lever inside the envelope**, choosing a leveraged lot over the unleveraged equivalent from a Python-built equal-exposure menu, inside the human-set leveraged sleeve cap (envelope spec §3.9) | integer above `B`, up to the fixed cap; or an equal-exposure menu | **changing** | Envelope repair landed (envelope spec phase E2; for the allocation lever, the leveraged sleeve live too); the always-most-aggressive replay and the analytic worst case pass; R2 clean; the R0 "reclaim" record (what Claude would have added) positive under both valuations; a full shadow decider book over ≥ one leg of each kind | Written exception plus the cap in risk units. Note: today the deterministic size already sits at the cap or the regime ceiling, so R3 has little room |
| **R4 strike from a menu** | Chooses strike and expiry from the gate-passed chain menu, including one notch riskier than baseline, inside the fixed envelope. The spreads picker is already an R4-type grant (below) | Python-built chain menu | **changing** | As R3, plus a clean R3 record | Written exception |
| **R5-R propose repair** | Proposes trades of Python-defined repair classes (§7) and, later, opportunistic entries. Python builds, prices and gates them | Python-defined trade classes; a fixed "autonomy envelope" in dollars | depends on the trade | Tap-only from the start (outside the ladder). Auto only after R4 is clean, plus its own replay | Written exception per trade class |
| **R5-H hedge roles** (revision 4) | C1 a daily stance (record); C2 "buy puts now" and C3 "cash in / roll down" proposals (tap); C4 a shape choice at the bridge's scheduled roll, at its fixed date and spend (§10.6) | the bridge's menu and budget (envelope spec §3.10) | C1 none; C2 changing (cost), tapped; C3 changing, tapped; C4 reducing within B0 | C1–C3 none (a tap adds no authority). C4: record-only through the bridge; applied in paper only on a renewed programme, by an R2-type ruling after ≥ 12 scheduled rolls of record, judged on execution and cost per protected point | C4: a written exception when applied. **Live auto: never under this spec** |
| **HP paper put budget** (revision 4, OR10) | **Automatically buys index puts in paper**: chooses *when* to spend one fixed unit (0.1% of NLV₀, accruing monthly) and *which* item from a Python-built menu (§10.7) | the hedge book's instrument only; a Python menu with "no buy"; fixed spend | **changing (cost)**; reducing on every risk measure | **None: granted by the operator without a record, paper only.** Survivability passes by construction (worst case: 3 units open, 1.2% of NLV₀ a year) | **A written exception (§10.7).** Record-only in live; never promoted by this spec |
| **Track D directional** (revision 4, OR11) | Up to 3 ideas a day from a Python menu, **shadow only, no order path** (§10.8) | Python menu; a fixed premium per idea | outside the ladder | ≥ 250 ideas and ≥ 120 market-day clusters before an order path may even be proposed (§11.13) | A separate spec and ruling for any order path |
| **X1 exits, tap** | Proposes close / assign instead of the policy's answer, on the existing decision card | Python-feasible exits | n/a (a human decides) | None (a tap adds no authority) | D4 |
| **X2 exits, auto** | Chooses among Python-feasible exits that are **risk-reducing** by §4 (for example, close instead of roll) | feasible exits ≤ the policy's risk | reducing | ≥ 100 roll-stream episodes clustered by short; beats the policy and the random control | Written exception. Never a veto that forces a leveraged-ETF assignment unless the 2026-10-14 ruling is reopened |

The destination is the top of each row with `AutonomyLevel.FULL`.

**Revision 3 additions.**

- **Envelope levels are never a rung.** The shock budget, the gross backstop, the glide, the
  leveraged sleeve cap, the tail-class multipliers, betas and exposure weights are human-held (§3
  line 6). A raised level needs the envelope spec's stabilisation rule, the harness and a ruling.
- **R2 versus R3 on leverage.** A menu that can only move toward less leverage (the index lot or skip
  when the baseline is a sleeve lot) is R2, provided every item is no riskier on every §4 measure,
  G10 and P20 included. A menu that can pick the leveraged item is R3.
- **The spreads picker is an R4-type grant.** Its menu holds a strike inside the baseline. It is
  grandfathered in paper and record-only in any live plan. In 12 picks it chose the baseline 4 times
  and skip 8, and never the inside item (offered twice). Its record measures the spreads book and
  pilots this spec's §11 machinery (pre-registration, placebo, valuation rule). **It is never
  evidence for a wheel rung**: skill at a 0DTE SPY menu says nothing about cutting or selecting
  wheel entries.

**Revision 4 additions.**

- **The bridge's existence, budget, instrument, schedule, size rule, stress block and monetisation
  rule are envelope levels** (envelope spec §3.10, §3.9): the operator's, never a rung.
- **HP is the one Claude grant made without an evidence record.** The operator chose it, in paper,
  knowing its record cannot show timing skill in any horizon this spec plans for (§11.12). That is
  why it is paper-only, record-only in live and outside promotion: a good HP record is not evidence
  for any live grant, and no rung's record is evidence for it.
- **Track D's record is never evidence for a wheel rung, nor the reverse.** Neither is the hedge
  record: hedge timing and entry selection are different skills.

### 5.2 Mapping onto `AutonomyLevel` and `promotion_blockers`

- **The two axes are orthogonal.** `AutonomyLevel` (OBSERVE / MANUAL / WHITELIST / FULL) governs
  *whether a human taps* to open. The rung governs *who decides inside the envelope*. A Claude rung
  above R0 acts only on candidates that clear `may_auto_open`, as `claude_cut` does today. On OBSERVE
  and MANUAL the card shows Claude's choice as information (decision 3's pattern).
- **Storage.** Each lever's rung lives in `system_settings`, beside the autonomy level, set only
  through an operator command.
- **Promotion** goes through `claude_rung_blockers(lever, target)`, which mirrors
  `promotion_blockers`:
  - demotion is always free;
  - promotion needs the pre-registered evidence report for that rung (§11), read and signed off
    by the operator;
  - **`automation.paper_skip_promotion_gate` never applies to a Claude rung.** It bypasses the
    autonomy evidence gate in paper today; a Claude rung earned without evidence defeats the point.
- **A live process re-validates its stored rungs at startup**, as `enforce_live_autonomy_evidence`
  does. It demotes to record-only any rung that lacks its evidence record or its `apply_live` flag.
- **Demotion is automatic** on a breaker trip, on the slow breaker (envelope spec §3.4.5), and on
  the posterior rule in §11.7.

## 6. Envelope repair (moved to the envelope spec in revision 3)

Envelope repair must land before any risk-changing rung (R3, R4, auto R5, X2). It is deterministic,
backtestable and ruled by the operator. It is worth doing even if Claude never gets another lever.
**Revision 3 moved its specification to `2026-11-13-risk-envelope-design.md` (the envelope spec)**,
which is now a prerequisite of this spec. What moved, and what changed on the way:

| Rev 2 section | Now | What changed |
|---|---|---|
| 6.1 A gross cap that always runs | Envelope spec §3.4.1–3.4.2 | **The primary limit is now a beta shock-loss budget, S10**: the loss at SPY −10%, by full revaluation, leveraged ETFs at leverage × index beta. Target about 15% of NLV; it starts at today's level (≈ 22%) and **glides** down over a set period; meanwhile an opening that adds to S10 passes only under the glide limit. No rule forces a sale. **The backstop is exposure-weighted gross (U_ew), unconditional**: the `vx.active` condition at `risk_engine.py:527` goes. ITM puts count at strike |
| — | Envelope spec §3.4.3 | **New: the nonlinear-gap measure** (G10, P20), used by §4 here |
| 6.2 Tech-linked cap and stacking rule | Envelope spec §3.4.4 | Unchanged in substance; the group cap is **leverage-weighted** |
| 6.3 Slow breaker | Envelope spec §3.4.5 | **Spans books.** It reads account NLV, which already includes spreads P&L; a trip also **stops spreads entries**; the daily mark leg adds the spreads book's P&L through a neutral read-only `src/common/spreads_view.py`. Its effect on Claude's rungs (demote every risk-changing rung, block risk-changing levers) is unchanged |
| 6.4 Survivability harness | Envelope spec §3.4.6 | Covers S10, U_ew, G10, P20 and the spreads book at its caps. §3 line 4 here still runs it before every rung |

What stays here: the dependency. Every risk-changing rung needs the envelope spec's phase E2 complete
and the harness passing (§15).

## 7. Book repair: Claude's part

The book's loss is inventory, not new flow. Every lever in rev 1 acted on new CSPs. **Revision 3
moved the deterministic part to the envelope spec §3.7**:

- the `min_strike_vs_basis` ruling by replay (its E12, was D14), with a leveraged-ETF class floor
  (none, delta ≤ 0.25, tap-only first);
- the tap-only repair proposals Python builds: covered-call overlays, "stop adding", trims, a
  de-lever proposal for leveraged shares, protective puts later;
- the new order paths they need (stock sell and buy, buy-to-open);
- the S10 / U_ew before-and-after shown on every proposal and on every manual stock buy.

Book repair is how the envelope spec's glide shrinks S10 without a forced sale. Note its arithmetic:
covered calls on every holding lower S10 by only about 1.8 points (22.0% → 20.2%), because in a crash a
call protects by about its premium; the rest needs call-aways or tapped trims.

**What stays here is Claude's role:**

- It chooses which of Python's proposals to surface and endorse, with reasons tied to fact ids. That
  is a selection from a Python menu (an R5 trade class, tap-only).
- The operator taps.
- **Every proposal is shadow-valued whether tapped or not**, so operator selection does not
  contaminate the record.
- Python sends nothing without a tap.
- **Decision 30 stands.** Claude never holds, delays or moves a covered call's strike. Proposing an
  overlay for a human to tap is not a hold.
- **The plan's "reduce" stance lands here.** It becomes a repair proposal, never an automatic sale.
- **Revision 4: a hedge is not repair.** The bridge (envelope spec §3.10) is insurance during the
  glide; trims and covered calls remain the main repair. Single-name protective puts are out of scope.

## 8. Knowledge: the read-only fact layer

Every fact is built by deterministic Python, carries `as_of` and `source`, and is read-only. Claude
reads facts; it never writes one.

### 8.1 Book truth

**Per position:**

- spot;
- unrealised $ and %;
- distance to strike in $, % and ATRs;
- delta;
- `prob_otm` (N(d2), labelled as such: delta is not P(assignment));
- DTE and extrinsic value left;
- the cost if assigned against the current price.

**Per name:** shares, wheel-adjusted basis, unrealised P&L, open shorts, exposure if every put is
assigned.

**Account:**

- NLV, cash, margin cushion, and cash after every ITM put is assigned;
- committed collateral vs deployable;
- gross / NLV, nominal and exposure-weighted (U_ew);
- S10, S20, G10 and P20, the glide limit L(t) and the headroom under it, and the leveraged sleeve's
  use (the envelope spec computes them daily from its phase E0);
- drawdown on the 3-session and slow windows, and the breaker state;
- concentration by name, sector and tech-linked group;
- scenario P&L for index −5%, −10% and +5% (beta-scaled, full revaluation);
- revision 4: T20 and S-SMH, gross and net of long options; the hedge book (position, points
  protected = S10_gross − S10_net, budget used and left, the stress-block state, the next scheduled
  roll); Claude's paper budget (units banked, open, spent); the VIX/VXN state with the conditional
  payoff per premium dollar for that state (envelope spec §2.6).

**Sources.** The news process already reads `portfolio_snapshots` and the regime record, and that
covers most of this. The **roll policy's current answer** cannot come from `evaluate_roll`, which
needs an `IB` connection and queues a PENDING approval as a side effect
(`roll_pipeline.py:272-292`). Instead the trading process writes a **dry-run roll answer** (decision
only, no approval) to its own table each cycle. The fact layer reads that table.

### 8.2 Market state

Keep today's market picture. Add only what has a deterministic, keyless source:

- the regime inputs with their history;
- realised vs implied volatility;
- sector relative strength from `price_history`;
- the SPY GEX map the spreads book builds;
- 1-year percentiles for each.

Breadth over index constituents, HYG/LQD and index skew are **each a new source**, to be sourced
and costed in the plan or dropped. Rev 1 listed them as one line.

### 8.3 The event horizon (45 days)

- **Macro dates:** a **static FOMC / CPI / PPI / NFP / PCE / retail-sales schedule in config**,
  built in the envelope spec's phase E0 and shared with the spreads book's `risk.events` (which was
  empty, so the book held a short call spread across the Oct 28 FOMC decision)
  (deterministic, published a year ahead). Consensus comes only inside ForexFactory's one-week
  window.
- **Earnings:** dates from the provider the earnings blackout uses, with the implied move set
  against the last 8 realised earnings moves (`get_earnings_history`).
- **Other dates:** ex-dividend dates and monthly opex.
- **Missing actuals:** fix the 2-day look-back. A High-impact print with no actual after 30 minutes
  raises a data alert.

### 8.4 Per-name knowledge

- **The dossier.** Its prose is dated in the prompt and refreshed on a priority queue: held names
  and names with an event inside 10 days come first.
- **Python levels:** IV rank, term and skew; the ladder's supports, the 50/200-day averages and ATR.
- **The value view, only when it passes sanity bounds.** Python fair value / price must lie in
  [0.1, 10]; otherwise the line is withheld and a data alert raised.
- Recent 8-Ks and the news piles.

### 8.5 Track record (reopens decision 1, D18)

Deterministic outcome facts from `verdict_ledger`, `sizing_actions`, the reporting P&L and the
ledger, per name, strategy, regime and setup band:

- trades, win rate, average P&L, loss exits, assignments, rolls;
- **every counterfactual under both valuations**;
- **cells with n < 10 suppressed**, Wilson intervals shown.

What stays out:

- Claude's past opinions (decision 1);
- its prior prose (decisions 19 and 26);
- its own scorecard, until a bucket has ≥ 100 resolved items (§11.8).

This needs decision 1 reopened, because decision 1 says memory is "not a record of past opinions
or trades".

### 8.6 Freshness and grounding

**Freshness limits:**

| Block | Limit |
|---|---|
| Book | 5 min intraday |
| Picture | 6 h |
| Dossier prose | 3 trading days |
| Calendar | 1 day |
| Track record | 1 day |

A stale block is labelled `STALE since …` or dropped.

**Grounding:**

- Every non-probability number in Claude's output must match a fact id within tolerance (the
  `src/news/grounding.py` pattern). An ungrounded item is dropped and counted.
- **Falsifier levels must be Python levels** (fact ids) or be labelled judgments. In the spreads
  record the picker applies the plan's pre-set triggers (7 of 8 skips cite them), so a Claude-typed
  threshold is a de facto rule.
- Numeric grounding cannot catch qualitative errors: S19 was a wrong *word*. So a **blinded
  claim-level audit** of two briefs a week (the operator's existing quality bar) runs before any
  brief reaches a lever.
- LLM-written prose (picture stories, dossiers) is labelled as such in the brief's context.
- Claude is told its training knowledge of prices and narratives is stale and must not be cited.

## 9. The daily cycle

### 9.1 Timing (on merits, R3)

The information that matters to a CSP/CC book arrives in two batches:

- **After the close:** settled closes and IV, the EOD job (`scheduler.eod_report: 16:15`), and
  after-close earnings with their first after-hours reaction.
- **Before the open:** pre-market earnings and the 08:30 ET macro prints (CPI, PPI, NFP, retail
  sales; 13:30Z in November).

A single brief at 08:30 is blind to that morning's print. A single brief at 09:00–09:15 sees it, but
it compresses the whole day's reasoning into the minutes before the open, with no room for a retry.
**So the spec uses both batches:**

| When (ET) | What | Model | Output |
|---|---|---|---|
| ~17:30, trading days (after EOD and after-close earnings) | **The brief**, a one-shot | Opus | Tomorrow's plan (§9.3). Revision 4: the hedge stance and any C2/C3 proposal (§10.6), any paper-budget letter (§10.7), up to 3 Track D ideas (§10.8) |
| 08:45 | **Pre-open check, deterministic Python, no LLM.** Did a plan falsifier fire? Did a High-impact print land outside its playbook band? Did a pre-market earnings release or an overnight gap beyond k ATR hit a planned name? | none | A list of invalidated plan items |
| 08:45–09:20, only if the check flagged items | **Amendment** for the flagged names | Opus | Item-level amendments |
| Intraday, on a trigger (regime change, index shock, breaker trip, ±2 ATR on a held name) | **Amendment** for the affected names, ≤ 2 a day | Opus | Item-level amendments. Revision 4: may carry a paper-budget letter from that session's menu (§10.7) |
| Every scan with candidates | **Candidate review** (kept, on every candidate), now with the plan in context | Sonnet | As today; `claude_cut` |
| Every roll decision (one per short per action per ET day since `9da9e8a`) | **Roll review** (kept), with a structured agree / disagree, a reason and an optional close / assign proposal | Sonnet | Stored, scored (§11), X1 |

**The pause.** While an amendment is pending, new CSPs on the affected names pause for at most 20
minutes. Then they proceed on the deterministic answer.

- The pause exists only once L1 is applied (R1 with the plan input). While the plan is record-only,
  amendments are recorded and nothing pauses, because a pause would be an effect with nothing to
  apply.
- A plan never carries over to the next day.

### 9.2 Calls dropped, and why

| Call | Rev 1 | Rev 2 | Reason |
|---|---|---|---|
| Debrief (Sonnet, 16:30) | kept | **dropped** | Python resolves and scores the day's items. The next brief reads Python's scored outcomes. The narrative fed nothing. |
| Weekly retrospective (Opus) | kept | **dropped** | It is the reasoning-playbook loop removed on 2026-08-10, and it fed Claude's own prose forward (decisions 19 and 26). Reopening it is a separate ruling. |
| The plan's per-short section | kept | **dropped** | Two opinions on one question. The roll review sees the live quote and the policy's actual proposal; an evening "preferred outcome" is conditional on a trigger that may never fire. The live view is kept. |
| Per-name probability questions | many | **few, exogenous, a guardrail** | No lever reads them. They stay only as a calibration safety check (§11.4) and are cut further if no lever uses them by Phase 4. |

### 9.3 The plan: reuse the spreads day-plan pattern

**Storage.** Start from `SpreadDayPlan` (`schemas.py:2079`) and the `spread_day_plans` table. Each
row stores the prompt, the raw response, the model, effort, latency, cost and a `failed` flag. Add
`backend` and a prompt/context version hash.

**The plan holds:**

- **A market thesis**: 3–5 sentences, Claude's regime read beside the deterministic one, and 2–3
  falsifiers on Python levels.
- **A list of name items**, for held and tradable names. Each item carries:
  - `stance`: `add` / `hold` / `no_adds` / `reduce`, an enum Python maps to a cap;
  - `max_new_lots`: an integer;
  - `until`: a date or event id;
  - the reasons, as fact ids;
  - a falsifier.

  `add` is recorded for R0 and has no effect; the schema says so, so Claude is not graded on a
  stance that is discarded. `reduce` becomes a book-repair proposal (§7).
- **Opportunities and avoids**: operator-facing notes only (L2b is deferred).

**Validation is per item.** An invalid item (no reason, an ungrounded number, a bad enum) is
dropped and counted, and the rest of the plan stands.

**`max_new_lots` is clamped at apply time:** `min(plan, deterministic)`. It is not checked at
validation, because the deterministic size does not exist until scan time.

**A missing, failed, Ollama-written or invalid plan means the deterministic system runs unchanged,
and the day is recorded as missing, with its cause.**

**The brief is blind to yesterday's plan prose.** Python diffs today's plan against yesterday's for
the operator and reports, as booleans, which of yesterday's falsifiers fired.

### 9.4 Robustness: governor and fallback (not architecture)

- **Per-kind call and token budgets**: brief 1 + 1 retry; amendments ≤ 3 a day in total. The
  remaining kinds keep today's limits. Past a budget the deterministic system runs alone.
  `scripts.claude_usage` reports the brief's share.
- **The outage plan is the deterministic system.** Degrading Opus → Sonnet helps only with
  per-model throttling. On Oct 14 the spreads plan's Sonnet fallback failed with Opus, which is
  consistent with an account-level outage (per-model limits are unverified).
- **Ollama never writes a plan.** This is the opposite of the spreads precedent on Oct 30. It never
  produces a lever value either (existing rule). An Ollama day counts as a missing day.
- A brief timeout of its own (proposed 420 s, against the global 180 s). Cost and latency at a
  30–40K context are **unmeasured**; the spreads plan's $0.045 and ~14 s are at a ~1.5K-token prompt.

## 10. Lever decisions

### 10.1 L1, plan caps: a second input to the `claude_cut` clamp

- **CSPs only.** Never covered calls (decisions 29, 30 and 34; and a CC cap is risk-changing, §4).
- **Implementation.** `regime_limits.claude_cut` gains the plan's clamped cap as a second argument:
  `min(deterministic, review_cut, plan_cap)`. It is the same function and the same exception. A
  plan cap counts only if the plan came from the CLI.
- **Record-only first** (Phase 3). Per candidate, log:
  - whether the plan cap would have changed the size;
  - whether a CLI review existed;
  - the order of attribution: plan first, then the review on the remainder.
- **The evidence so far is thin.** All 40 new CSP candidates since Oct 15 had a review. No case was
  found where a plan cap would have bound and the review was absent. The paying cuts were live-book
  stacking, which an evening cap cannot see.
- **The case for it is availability**, which is not yet observed: the plan exists before the
  session, while the review needs a call per candidate.
- **The breaker on the share of gate-passed flow zeroed** covers both inputs.

### 10.2 L2a, ranking: dropped

The evidence is in §2.2: 97 of 113 calls carried one candidate, there were 2 reorders in five
months, and the allocation gates fired 4 times in 1,301 rejects. Contention lies *between* scans
(first come, first served), not within a list.

**Before anything replaces it:** measure the regret of first-come against best-of-day on the 9
multi-candidate days, using the existing shadow valuation. If the regret is material, a cross-scan
allocation menu becomes an R2 candidate.

### 10.3 L2b, nomination: deferred

It is **risk-changing** (it adds trades). Nominated names would meet the same earnings and IV/RV
gates that account for ~90% of rejects, plus the ladder.

**For now:** "opportunities" is an operator-facing note. If it is ever built, it is record-only, it
only raises a name's materiality for the next scan, and its gate outcomes and shadow P&L are tracked
separately. A gate-rejected nomination is "no information", not a loss.

### 10.4 L3, exits: no veto; tap-only proposals; the roll stream scored

- **No auto veto, at any rung**, unless the 2026-10-14 ruling is reopened. A veto forces assignment
  on would-own puts and on leveraged ETFs.
- **X1, tap-only close / assign proposals.**
  - Each is an annotation on the existing decision card, not a new message.
  - Python builds, prices and gates the close (`close_short_position`, the N20 Close button).
  - Each proposal is shadow-valued along the hold-to-expiry and the policy path, whether tapped or
    not.
  - Proposals are capped per day.
- **The roll review stays per decision.** It gains a structured agree / disagree and a reason. It is
  scored against the policy, clustered by short (33 shorts over 82 short-days since Oct 15).

### 10.5 D9, Claude easing the regime: a record-only shadow, never applied

Record every "would ease" read, and Claude's view on every ladder-blocked and regime-trimmed lot,
as R0 decision episodes valued under the fixed rule (§11.3). That is the evidence any future ruling
on over-restriction would need. Easing itself is never granted under this spec.

### 10.6 Hedges: Claude's roles (R5-H; revision 4)

The bridge is Python's (envelope spec §3.10): its schedule, size, budget, instrument and stress block
are fixed. Claude's roles around it are the reviewers' merged set (O3R C1–C4, S3R §2.1):

| Role | What Claude does | Mechanism | Class | Why it is honest |
|---|---|---|---|---|
| **C1, the daily stance** | One of {hold the programme, add (a menu letter), cash in / lift (a leg), none}, a reason tied to fact ids, a falsifier on Python levels | R0 row in the brief, every trading day, with or without a bridge running | record | Costs nothing; valued against the programme, no hedge, a random roll date and the trim-equivalent (§11.11) |
| **C2, "buy puts now"** | Proposes one item above the schedule | Python builds, prices and gates it from the bridge's menu, inside the bridge's budget; the card shows the VIX/VXN state and the payoff per premium dollar for that state, S10_gross / S10_net and T20. **The stress block applies.** A human taps | changing (cost) | Meets "able to buy puts when relevant" without timing authority |
| **C3, "cash in / roll down"** | Proposes an early close or a roll down after a fall | An annotation on the bridge's card (the X1 pattern); Python builds and gates the order; a human taps | changing | Monetisation is where hedges are won or lost, and the multiple is fragile (envelope spec §2.6), so it stays a human decision until a rule is replayed and ruled |
| **C4, the shape at a scheduled roll** | Chooses among items at the scheduled date and fixed spend, each no worse than the default on every scenario in {S10, S20, T20, G10, P20} and inside the floors (DTE ≥ 45, long delta ≥ 0.15) | A menu letter; a missing or bad answer means the default item | reducing, within B0 | No timing: date and dollars are fixed. **Record-only through the bridge** (2–3 rolls are too few to read): the default is bought and Claude's pick is shadow-valued |

**Every proposal and pick is shadow-valued whether tapped or not.** Never granted, at any rung of
this spec: skipping, delaying, shrinking or lifting the programme automatically, or any automatic
purchase above it in live.

### 10.7 The paper put budget, HP (a written exception; revision 4, OR10)

**The exception.** In **paper**, Claude may cause an **opening buy of an index put**: it chooses
*when* to spend one fixed unit of a separate small budget and *which* item of a menu Python built.
Python builds and prices the menu, sets the contract count from the fixed unit, sends a `LimitOrder`
at mid on qualified contracts quoted through `req_fresh_mkt_data`, and gates it with
`validate_hedge` at decision time and again at send time (envelope spec §3.10.10). Claude never types a
size, a strike, a price, a tenor or an exit. Unlike `claude_cut`, which only lowers, and the value
verdict, whose READY reaches a stock buy only through Python's price and timing gates, here Claude's
choice is itself the opening decision: when, and which option. It is
**paper-applied and record-only in live**: `validate_hedge` refuses a `hedge:claude:` order under
`LIVE_TRADING=true`, and no switch in this spec changes that. Going live needs its own later ruling.

**Class (§4).** Reducing on every risk measure (net delta, S10_net, T20, G10 and P20 improve;
collateral and U_ew are unchanged). Spend is above B0, because the budget is in addition to the
programme. So it is **risk-changing (cost)**. It is granted without a §11 evidence record, by the
operator's choice: permissible only because it is paper and its worst case is its premium.

**The budget** (adjudicated from the operator's "about 0.1% of NLV a month"):

| Term | Level | Why |
|---|---|---|
| Unit | **0.1% of NLV₀** (NLV on the first day, in fixed dollars; ≈ $650 today) | The operator's figure |
| Accrual | One unit per 30 days; **at most 3 banked** | The hypothesis is about *when*. A use-it-or-lose-it monthly unit would be a schedule in disguise. The bank cap bounds what one stress episode can absorb to 0.3% of NLV₀ |
| Per buy | Exactly one unit: contracts = floor(unit ÷ the item's debit); an item that fits no whole contract is not on the menu | Fixed spend; Claude never sizes |
| Pace | At most one buy per session | A spike gets at most three buys over three sessions |
| Open at cost | ≤ 3 units | Bounds the paper loss at once |
| 12 months | ≤ 12 units (1.2% of NLV₀) | Follows from the accrual |

At today's prices one QQQ 45-day 0.30-delta put costs more than a unit [M], so on the QQQ route the
menu leans to verticals and further-OTM strikes; XND's smaller contract helps. If the E0 capture
shows the menu empty on most days, the operator may set the unit to 0.2% with 2 banked (H13).

**The menu.** Python's, built each session from captured quotes on **the hedge book's instrument
only** (XND, or QQQ under the envelope spec's §3.10.0 rule): tenors {30–45, 60–90 DTE} × long-leg
delta {about 0.30, about 0.15–0.20} × {outright, vertical at least 10% of spot wide}, plus **"no buy"
(the default)**. Floors: DTE ≥ 30, long delta ≥ 0.10, quote ≤ 10% of mid. No 0DTE, no calls, no
other underlying.

**The channel.** A letter from the brief (≈ 17:30 ET) or an amendment (§9.1), with a reason tied to
fact ids and a falsifier. Python sends in a fixed window the next session (10:00–10:30 ET; within 30
minutes of an amendment), re-quotes, recomputes the contract count **downward only**, and re-runs
`validate_hedge`. **Fallback = no buy:** an Ollama-produced, malformed, ungrounded or stale answer, or
a missing day.

**Exits are Python's.** Each buy is sold at ≤ 21 DTE remaining, or by the bridge's monetisation rule
once one is ruled. Claude's "cash in" on one of its own puts is a tapped proposal (C3), shadow-valued
both ways. There are no rolls: each unit is its own trade.

**The VIX ≥ 25 block: Claude's paper budget is exempt.** The decision and its reasons:

1. The block encodes the evidence that stressed-state buying returns about 0.20 on the dollar. The
   operator's hypothesis is that Claude can tell *which* stressed moments are worth buying. A blocked
   experiment produces no observation in the very state the hypothesis is about, so it could only
   confirm the block by construction.
2. The cost is bounded and not real: at most 3 units (0.3% of NLV₀) open, in paper.
3. The record measures the question directly: Claude's stressed-state buys against **random buys in
   the same VIX state at equal spend** (§11.12), beside the deterministic block's counterfactual.
4. The exemption is **paper-only**. Any live version would carry the block unless its own ruling,
   reading this record, lifts it.

What is **not** exempt: the account halt, the daily and slow breakers and every hard line. A trip
demotes HP to record-only (§3 line 5, §11.7), and the record keeps valuing what Claude would have
bought, so the censored days still produce counterfactual rows.

**No credit.** HP's puts are excluded from S10_gross and U_ew (hard line 9), included in S10_net and
the harness, and their marks enter the daily loss leg net, by book.

**The breaker.** HP drops to record-only, with a human reset, on any of:

- a cumulative realised and marked loss of **6 units (0.6% of NLV₀)** since the start;
- trailing the schedule control (§11.12) by **4 units over any rolling 6 months**: a cost stop,
  which will fire on noise as well as on bad timing, and says so on its card;
- any account breaker trip, the slow breaker or a halt.

**The review.** Twelve months after the first buy, or on the tail stop, the operator reads the record
and rules continue or stop. Nothing in the record promotes HP to live.

### 10.8 Track D: directional ideas, shadow only (revision 4, OR11)

Outside the ladder. **No order path in v1:** paper or live needs a separate spec, plan and ruling.
Shadow measures skill at no cost; paper orders in the `DUQ` account would spend the excess liquidity
and NLV that feed the CSP budget, the breakers and the glide (the reasoning envelope E1 applies to
spreads).

| Element | Design |
|---|---|
| Menu | Python's, daily after the close, from captured quotes: QQQ/XND, SPY, IWM and about 10 liquid single names (held names included in shadow). Items: long call or long put, ATM or 5% OTM; a debit vertical ATM/±5%; 30–60 DTE; **skip** (the default). Items quoted wider than 5% of mid are dropped |
| Claude's output | ≤ 3 ideas a day: name, direction, a menu letter, reasons as fact ids, a falsifier on Python levels. No typed numbers |
| Premium per idea | **0.25% of NLV₀, fixed dollars**; fractional contracts allowed in shadow, whole-contract feasibility recorded. Adjudicated against S3's $1,000: return on premium is scale-free, so the choice only sets the units of the loss record, and 0.25% is the size any later order path would use |
| Valuation | Captured mids with the measured half-spread on entry and exit; exit at +100% or −50% of premium or 30 DTE remaining, pre-registered; hold-to-expiry beside it; the two must agree in sign |
| Controls, same day and name | **Matched random direction** (the placebo); **always-call** (free beta: this book is ~1.9× QQQ); **the same view expressed in stock** (delta-matched shares); a 200/50-day trend rule; always-skip |
| Concentration | **A long call on a name, or a factor, the book is already long is the same bet:** flagged `same_bet`, scored separately, and barred from any future order path (with tech-linked names while the group cap binds, and QQQ/XND while S10_gross > L(t)). A long put on the book's own factor is a hedge: it routes to C1/C2 and never counts as directional skill |
| Contamination | Forward ideas only. No backtest of Claude on pre-freeze data (look-ahead and memorisation in LLM forecasts [W]) |
| Bar | §11.13 |

**Two free streams, scored forward from now (Phase 0, no new Claude call):**

- **The news verdicts.** Every `overreaction_likely` (and `further_*_likely`) explanation is scored as
  a fade at +1, +3 and +5 sessions, against a deterministic "buy any ≥ 7% one-day drop" rule and
  against the `unclear` large movers, clustered by event day. So far [V counts, S3 scoring]: 15
  `overreaction_likely` calls on 6 event-days; hit rates 46% / 54% / 50% at +1 / +3 / +5 on the 13
  ticker calls; no edge over the rule.
- **The spreads plan's bias**, scored open-to-close (the plan posts at ~09:33 ET) against the base
  rate. So far [V]: bearish on 4 days (Oct 15, 20, 23, Nov 10), SPY up open-to-close on all 4; never
  bullish; Nov 5 (−4.24% open-to-close) was neutral.

## 11. Measurement

### 11.1 Pre-registration

Before any phase's record starts, the implementation plan fixes, in writing:

- the primary metric (D11);
- the baselines and controls;
- the valuation rule;
- the clustering;
- the sample or duration;
- the promotion and demotion rules.

No metric is added after the data has been seen. Every row is stamped with the model, effort,
prompt hash and context version. These are frozen during an evaluation window, as with the
`value_rules` / `ruleset_version` pattern. A change starts a new window.

### 11.2 The unit: the decision episode

An episode is any point where Python decides, including where the gate or the ladder blocked:

- a gate-passed candidate;
- a ladder-blocked or regime-trimmed lot (`sizing_actions`: 63 rows from Oct 22 to Nov 11);
- a roll decision;
- a repair proposal.

At each episode Python builds the menu and values **every** item. On identical data it scores:

- Claude's pick;
- the baseline;
- a **matched random pick** (the placebo: it isolates selection skill from "traded less");
- a **dumb rule** (the stacking rule, envelope spec §3.4.4): it tests whether the value can be
  codified;
- **always-skip**.

The record covers every episode, applied or not, which removes the selection-on-treatment bias of
counting only applied cuts.

Missing days (no plan, a CLI error, a timeout, Ollama, a validation failure) are logged with their
cause and reported, because they are not missing at random. A **plan-blind holdout** (25% of scans:
the reviewer does not see the plan) measures anchoring.

### 11.3 The fixed valuation rule

- **Primary: `shadow_pnl_rules`.** This walks the daily closes, prices with Black-Scholes at the
  entry IV, and exits at the system's own profit-take and loss lines.
  - It is fixed because the alternative flips the sign: for `scale_in_zone`, expiry valuation says
    the blocks avoided $2,511 while rules valuation says they forwent $785. For
    `loss_exit_cooldown` it is −$4,596 against +$750. `sizing_counterfactual.py` itself says expiry
    valuation "would flatter every block made in a selloff".
- **Where a lot traded:** the exact realised P&L per contract.
- **Sensitivity:** `shadow_pnl_expiry`, reported beside the primary. A promotion needs both to agree
  in sign.
- **Partial equilibrium:** report everything as a "direct effect". A lever applied in live gets a
  day-level comparison against a shadow book.
- **Revision 4: bought options are valued from captured leg quotes** (envelope spec §3.10.8): every
  hedge menu item, HP buy and Track D idea, at captured mids with the measured half-spread.
  Black-Scholes is a labelled fallback. Stored `iv_history` is not used: it read QQQ at 14.6% on
  Nov 5 against a VXN of 38.3, which would have marked a hedge at a fraction of its value.

### 11.4 Probabilities: a guardrail only, scored against the market

- **Questions:** only exogenous ones. Example: "P(NVDA closes ≥ 205 on Nov 13)". Never one Claude's
  own action changes; "P(assignment)" becomes endogenous once an exit lever exists.
- **Baseline: the market-implied probability Python already computes** (`prob_otm` / N(d2)).
  Metric: Brier skill against it, plus resolution. A copy of delta is already calibrated, so
  "below a naive baseline" proves nothing.
- **What six weeks can show:** gross miscalibration, which is a safety check.
- **What it cannot show: skill over the market.** That needs about 2,500 independent questions for
  a 0.0025 Brier gain. Same-day questions on correlated names carry an effective N of about 2–5 a
  day, so that is years.
- **Calibration is not resolution.** The spreads plan's bias was neutral on 18 of 22 days. Never a
  promotion criterion.

### 11.5 Inference and risk normalisation

- **P&L is reported per unit of risk**: per risk-unit-day and per collateral-day. Beside it go
  income retained, change in max drawdown and tail loss, and raw dollars.
- **Clustering:** block bootstrap by trading day, clustered by name and, for rolls, by short. The
  four TQQQ cuts on Oct 28 are one cluster.
- **The interval's lower bound must clear the controls, not zero.**
- **Regime coverage:** at least one ≥ 10-session down leg and one ≥ 10-session up or calm leg before
  any promotion.
- **Bars by class:**
  - risk-reducing rungs: a judgment gate with the above;
  - risk-changing rungs: additionally a full shadow decider book over both legs and the §3
    survivability test.

### 11.6 Time to evidence (honest)

The figures reconcile both reviewers' calculations; the assumptions are stated.

| Evidence channel | What it can show | Realistic time |
|---|---|---|
| Applied-cut P&L (L0 alone) | A $100 / application edge (SD ~$1,000) needs ~620 (one-sided) to ~930 (two-sided) applications. At ~1.3 P&L-bearing cuts a week | a decade: **not a test, a judgment gate** |
| Rev 1's "≥ 30 resolved, net positive" | A zero-skill lever passes 50% of the time, a good one 71% | does not separate them |
| Decision episodes (entries + roll stream) | ~100 entry episodes and ~80 short-days a month in this regime, but the effective N is the day × name clusters. A $250 / episode edge needs ~100–150 independent clusters; a $100 edge ~600–900 | **3–6 months** for a large edge, **1–2.5 years** for a modest one |
| Stance IC (cross-sectional, 5-session index-relative returns, momentum baseline) | ~39 names, 59% tech-linked, effective N per day ~12–20 (assumption) | IC 0.10: **5–9 months**; IC 0.05: **1.5–2.5 years** |
| Brier skill vs market-implied | ~2,500 independent questions | **years**; a guardrail only |
| Regime coverage | One down leg and one up/calm leg | depends on the market; **≥ 2–3 months** at best |
| Revision 4: hedge or paper-budget **timing** (C1, HP) | Better P&L per down leg than the schedule or random timing at equal spend: ~20–40 independent down legs (O3), or ~670–1,070 non-overlapping 60-day windows (S3). Nasdaq-100 ≥ 10% drawdowns arrive ~1.2 a year | **decades: never, for this spec's purposes** |
| Revision 4: hedge cost side | Premium per protected point, execution against mid, entry-state mix | **months** (and it confirms what the literature says: it costs) |
| Revision 4: C4 shape choice | Execution and cost per protected point at fixed date and spend | ≥ 12 scheduled rolls: **~3 years** at four a year |
| Revision 4: Track D | +20 points of return on premium over random: ~250 ideas (two-sided, SD ~115%); +10 points: ~600–1,000 | **2–4 years** for +20; +10 is not attainable |

**Implication.**

- R2 (select) could be argued **3–6 months** after the R0 record starts.
- R3 and R4 (risk-changing) need envelope repair, the replay and a clean R2 record: **6–12 months at
  the earliest**.
- Full menu autonomy is **likely years away**, and it will ultimately be an operator judgment
  informed by the record, not a statistical certainty. The spec says so rather than promising six
  weeks.

### 11.7 Demotion with stated false-demotion rates

Rev 1's rule ("two consecutive net-negative weeks → record-only") was simulated for this revision
(20,000 trials; Poisson applications; SD $1,000; empty weeks reset the streak):

| Applications / week | Lever | P(demoted) by 6 / 13 / 26 weeks |
|---|---|---|
| 1.3 | good ($100 mean) | 0.37 / 0.67 / 0.89 |
| 1.3 | zero skill | 0.44 / 0.74 / 0.94 |
| 4 | good | 0.53 / 0.83 / 0.98 |
| 4 | zero skill | 0.66 / 0.92 / 0.99 |

It cannot tell good from useless, and it kills any lever within a year. **The replacement:**

1. **Statistical.** Demote when the posterior P(mean effect < 0) > 0.9 on the clustered, rules-valued
   record, with **no statistical demotion before 10 clusters**. The plan states this rule's
   false-demotion rate by simulation before the record starts, with a target of ≤ 10% for a lever
   with a $100 edge over 26 weeks.
2. **Tail.** Any single application whose added or forgone loss exceeds a fixed dollar amount
   (operator-set) demotes at once.
3. **Breakers.** Any breaker trip, including the slow breaker, demotes every risk-changing rung.

Demotion needs no evidence and is never blocked. Re-promotion needs a fresh record.

### 11.8 What Claude sees of its own record

Its Brier score and lever record are shown to it only when a bucket has ≥ 100 resolved items.
Below that the numbers are noise and invite over-correction (Goodhart). Python may recalibrate
Claude's probabilities after the fact (isotonic) instead of lecturing it. The web page under
`/more/claude` shows the operator everything.

### 11.9 Score what already exists, first

The 22 non-failed spreads day plans: Python scores their risk flags and skip conditions against
what SPY did. This costs nothing, and it says whether a daily Opus plan has resolution or collapses
to the middle, before the wheel brief is built (D20).

### 11.10 The spreads book: a pilot of this machinery, not wheel evidence (revision 3)

The spreads book is the densest stream of independent, defined-risk decisions in the estate, at
about one traded episode every two sessions, with every menu item valued. Use it to debug this
section's machinery before the wheel's record starts: pre-registration, the matched random pick,
always-skip, the fixed valuation rule, clustering by session.

- **Its record counts only for the spreads book's own R4-type grant** (§5.1). Picker skill at 0DTE
  SPY says nothing about cutting or selecting wheel entries, so it is never evidence for a wheel rung.
- **The cost standard comes first.** The picker's break-even input was a parameter (93.5–94.9%)
  built on a shadow slippage four times the measured crossing, and all 8 of its skips cite it. The
  envelope spec §3.2 f recalibrates it before any spreads record window opens.
- **Expect a null.** The spreads live bar's H0 is "intraday expectancy after measured costs ≤ 0".
  A known-near-null environment is a clean baseline for the placebo test.

### 11.11 The hedge roles (revision 4)

- **C1** (the stance) is valued daily against the programme, no hedge, a random roll date at equal
  spend, the trim that removes the same S10, and the monetisation rule once ruled.
- **C2 / C3** proposals are valued along "tapped" and "not tapped", whether or not tapped, so the
  operator's choices do not contaminate the record.
- **C4** is scored on execution against mid and cost per protected point (minimum over the scenario
  grid) against the default item: not on crash P&L, which it cannot influence.
- **Per pre-registered down leg** (the index ≥ 1σ₆₀ below its 60-session high): hedge value at the
  trough and at exit as a share of the book's loss in that leg.
- **No skill claim is made.** The record is read at the review gate as a one-page account, and the
  ruling is judgment (envelope spec §3.10.2).

### 11.12 The paper put budget (revision 4)

Pre-registered before the first buy:

- **Primary:** net P&L per unit spent, valued on captured quotes with Python's exits; expiry value
  beside it.
- **Controls, all at equal spend, on the same instrument and menu:**
  1. **the schedule:** one unit on the first session of each accrual period, the default item;
  2. **random timing:** the same number of buys on sessions drawn at random from those on which a
     unit was banked, (a) with Claude's item mix, which isolates timing, and (b) with the default
     item; 1,000 draws, Claude's percentile reported. Repeated **within each VIX state** (< 15,
     15–25, ≥ 25), so stressed-state buys are compared with random stressed-state buys;
  3. **no hedge** (zero);
  4. **the block counterfactual:** the record with every buy made under the stress block removed.
- **Per down leg:** value at the trough and at exit as a share of the book's loss in that leg.
- **The state split,** beside the S&P prior (payoff per premium dollar 0.43 below VIX 15, 0.70 at
  15–25, 0.20 at 25–35).
- **Time to evidence, plainly:** a timing claim needs decades of down legs (§11.6). A year shows
  cost, the state mix, execution and gross failures, nothing more. The operator chose HP knowing
  this; its review is a judgment on cost and behaviour, not a test of skill.

### 11.13 Track D (revision 4)

**The bar to even propose an order path** (adjudicated between O3R's ≥ 200 ideas and S3R's ≥ 250
ideas and ≥ 120 clusters):

- **≥ 250 resolved ideas and ≥ 120 distinct market-day clusters**, spanning ≥ 1 down and ≥ 1 up or
  calm leg of ≥ 10 sessions;
- the 90% lower bound of the day-clustered mean return on premium above **each** of random direction,
  always-call, the same view in stock and the trend rule; a pre-registered effect of ≥ +15 points;
- the same sign under the rule exit and hold-to-expiry.

**Why both counts.** 250 is the two-sided 80%-power sample for +20 points at a per-idea SD of about
115% (O3); 200 had no power calculation behind it. The cluster count guards against news days that
produce several correlated ideas (S3R): four names on one day is one observation, not four. At about
1.5 independent clusters a week that is ~1.5 years for the clusters and **2–4 years** for the edge.
Passing it permits only a proposal, in a separate spec, of a paper order path.

**The free streams** (§10.8) use the same machinery: fades clustered by event day against the "≥ 7%
drop" rule; the spreads bias against its base rate. Each is a smoke test that costs nothing.

## 12. Placement and fences

**`src/mastermind/` (enrichment tier)** holds the prompt builders, the brief and amendment calls,
the plan validator and grounding.

- It reaches Claude only through `src.claude.cli`: a slim call from a workdir outside the repo.
- It is on `tests/test_eval_skills.py`'s enrichment list.
- It imports nothing from `src.engine`, `src.execution`, `src.strategies`, `src.spreads*`,
  `src.value` or `src.notify.approval_service`.

**The fact layer (read-only, deterministic)** lives in `src/reporting/` (book truth, track record)
and `src/analytics/` (market-state additions).

- It writes nothing, as `test_reporting_never_writes_anything` already checks.
- The trading process writes the dry-run roll answer to its own DB.
- The fact layer reads that table and nothing it would have to compute through IBKR.

**`data/mastermind.db`** (its own `MastermindBase`).

- Only `src/mastermind/` constructs its rows.
- Not `news.db`: news-fence rule 1 forbids the trading path reading it.

**`src/common/plan_view.py`** is the trading path's only view of the plan (the `value_view` pattern):

- it opens `mastermind.db` with `mode=ro` and plain SQL;
- it imports only `src.common.config`;
- it returns only validated, clamped integers and enums for today's date;
- it is re-read at **send time**: a plan built at 17:30 applies at 15:00 the next day under a
  possibly different regime, so the send-time re-gate reads it again.

`claude_cut` stays in `src/engine/regime_limits.py`.

**The process: a one-shot `scripts/run_mastermind.py --kind brief|check|amend`**, scheduled by the
launcher the way `scripts.run_eod` is (state file, timeout, logging).

- Being its own process makes it its own exception boundary: a crash or hang cannot stall the
  trading, news or spreads loops.
- It loads current code on every run, which matters in an estate where daemons run stale code.
- Intraday triggers: the trading process records a trigger row (kind, names, time) in its own DB.
  The launcher's scheduler tick spawns an amendment if the day's budget allows. Nothing is ever
  called inline on the order path.
- No IBKR connection, no clientId.

**Fence tests**, in the style of `tests/test_value_fence.py`:

- no trading-path import of `src.mastermind`;
- only `src/mastermind/` writes `mastermind.db`;
- `plan_view` imports only config and returns only clamped ints and enums;
- the send-time re-gate re-reads `plan_view`;
- importing `src.mastermind` loads no wheel layer and no `ib_async` (a `sys.modules` test);
- `claude_cut`'s plan input ignores a non-CLI backend.

Import-based tests do not catch a DB-mediated path, which is why the writer and reader tests matter.

**Revision 4: long options.**

- The hedge package (`src/hedge/`, deterministic, envelope spec §3.10.9) reads Claude's C4 and HP
  letters only through `plan_view`, which returns a validated menu letter (or "no buy") for today's
  menu id and nothing else. It re-reads `plan_view` at send time.
- `mastermind.db` stores the C1 stance, C2/C3 proposals, C4 and HP letters, Track D ideas and their
  reasons. Python's menus, captured quotes and marks live in the trading DB's `hedge_*` tables,
  written only by `src/hedge/`; the fact layer and the brief read them through
  `src/common/hedge_view.py`.
- Track D is shadow only: its menus and marks are Python rows; nothing in Track D reaches an
  order path.
- Fence tests add: `src.mastermind` never imports `src.hedge`, and the reverse; `plan_view` returns
  only letters from today's menu; HP's `hedge:claude:` orders are refused under
  `LIVE_TRADING=true`; an Ollama backend never yields an HP or C4 letter.

## 13. Interaction with existing systems

- **Wheel:**
  - the candidate review gains the plan (with the plan-blind holdout);
  - `claude_cut` gains the plan input (record-only first);
  - the roll review gains structured agree / disagree and X1;
  - covered calls are untouched except through tap-only book-repair proposals.
- **Spreads** (revision 3: no longer "unchanged"):
  - it keeps its own day plan and picker, and the wheel brief's thesis is not fed to it (correlated
    failure, confounded records);
  - it gets the envelope spec's fixes (§3.2 there): the static macro calendar into `risk.events`,
    the account-halt and slow-breaker link, caps of about 0.5% / 1% / −2% of NLV, a measured cost
    standard, `mode: shadow` until the skipped backtest passes;
  - on an operator ruling (E3 there), it moves to SPXW, which frees SPY for the wheel;
  - its picker is an R4-type grant, grandfathered in paper (§5.1); its record pilots §11 (§11.10).
- **Value book:**
  - the brief reads the value view, sanity-bounded;
  - the second written exception is unchanged, except the sanity quarantine (Phase 0) and the
    driver conversion question (D15);
  - a name may be `no_adds` for the wheel and READY for the value book, and the plan says why both
    hold.
- **Regime:** Claude's regime read is recorded beside the deterministic regime, never in place of
  it (D9).
- **Hedge book** (revision 4): Python runs the bridge (envelope spec §3.10). Claude records a daily
  stance, proposes (tap), picks a shape at scheduled rolls (record-only through the bridge) and, in
  paper, spends its own small put budget. The bridge and HP share the instrument and the order path,
  on separate order refs and budgets.

## 14. Prior rulings this spec touches

| Ruling | Source | Rev 1 | Rev 2 |
|---|---|---|---|
| Decision 1: "memory is the state of the market, not a record of past opinions or trades" | market-picture spec §2 | Claimed it "stands", then built a track record of past trades (§4.5) | **Reopened explicitly (D18).** Recommendation: allow deterministic outcome facts (n ≥ 10, intervals, both valuations); keep Claude's opinions and prose out |
| Decisions 19 and 26: previous prose is never fed back | same | The weekly retro fed lessons into the next briefs | **In line:** retro dropped; the brief is blind to yesterday's prose; Python reports falsifier booleans |
| Decision 22: "one week of four exits is not evidence" | same | "The one lever that bites has paid" | **In line:** §2 states n = 4, p ≈ 0.37, about three episodes, one regime |
| Decisions 29, 30 and 34: no Claude covered-call hold, no second exception for CCs | same, §2 and §18 | L1 applied to covered calls | **In line:** L1 is CSP only; Claude never holds, delays or moves a CC; book-repair overlays are tap-only proposals a human decides |
| Decisions 3, 15 and 33: Claude may cut a CSP, never raise it; paper-applied, record-only live, breaker | same | L1 as a separate exception | **In line:** L1 is a second input to the same clamp |
| 2026-08-10 removals: the skill-proposal loop and verdict-EV / calibration scoring | STATUS.md "Removed 2026-08-10" | Weekly retro; Brier as a promotion bar | **In line:** retro dropped; probabilities are a guardrail scored against market-implied, never a promotion criterion. What differs from the removed scoring: exogenous questions resolved by Python against a market baseline, not a verdict's EV. Reopening the retro would be a separate ruling |
| 2026-10-14: leveraged ETFs "roll where possible, else assign" | `src/monitor/intraday.py:532` | L3 auto roll veto | **In line:** no veto at any rung unless this ruling is reopened |
| N18: `min_strike_vs_basis: 1.00` | `risk_limits.yaml` | Not addressed | **Put to the operator (D14)**, by replay. Revision 3: moved to the envelope spec (E12), with a leveraged-ETF class floor |
| TQQQ/UPRO/SOXL/DPST as `would_own` exceptions (2026-08-27, 2026-09-29); decision 32's leveraged floor of 1 lot; the 2026-10-22 fair-value waiver on bottoming lots; regime multipliers for every name; the spreads plan's backtest-before-paper rule and its SPY choice | `universe.yaml`, `risk_limits.yaml`, `regime_limits.py`, spreads plan lines 560 and 707 | — | **Revision 3:** handled in the envelope spec §5 (leveraged puts off except a drawdown sleeve; UPRO and DPST out; no waiver for leveraged lots; an `index_1x` class multiplier; backtest reinstated; SPXW on a measured cost condition) |
| The core invariant: Claude never places, sizes or gates an order; two written exceptions (`claude_cut`, the value verdict) | CLAUDE.md | — | **Revision 4:** a new written exception, HP (§10.7): in paper, Claude chooses when and which item of a Python menu to open, at a fixed unit; record-only in live. The bridge itself is Python's and needs no exception |
| Rev 3 §5.1: R5 "hedges" tap-only, auto after R4 | §5.1 | — | **Revision 4:** split. R5-H hedge roles C1–C4 (§10.6), no live auto under this spec; HP paper auto by the operator's ruling; Track D outside the ladder |
| Envelope spec OR1: no long 0DTE options | envelope spec §3.1 | — | **Stands.** No 0DTE item on any menu here |

## 15. Phasing

**Revision 3: the envelope spec is a prerequisite.** Its phases (E0 stop the bleeding and measure;
E1 backtests and replays; E2 envelope live in paper; E3 spreads to SPX; E4 glide complete) are in
its §4.

- Phase 0 below changes no risk and may run beside E0–E1.
- Phase 2 onward waits for E2, so that every R0 record is made against the repaired envelope.
- Every risk-changing rung needs E2 complete and the harness passing; the R3 allocation lever also
  needs the leveraged sleeve live.

| Phase | Content | Claude's authority | Gate to the next phase |
|---|---|---|---|
| **Prerequisite: envelope spec E0–E2** | Everything in the envelope spec through its phase E2 (see above) | unchanged | Its own gates; E2 complete before Phase 2 |
| **0 Cleanup** | Delete the prices and IV text from `_UNIVERSE_CONTEXT` (keep tiers and structural rules; add HACK and IGV rows). **Quarantine the value fair-value fault:** withhold any VALUE NOTE whose Python fair value / price is outside [0.1, 10], flag the name in the value book, and diagnose GOOGL and META (units vs method; a change to a value rule bumps `ruleset_version`). Fix the S19 title consistency check. Date the dossier prose. Add spot, entry credit, unrealised, basis and earnings to the roll prompt, and fix its "Entry delta" label. Drop "default to sell" from the rubric. Stop writing `claude_memory`. Fix the 2-day actuals look-back. Stamp model and prompt versions on review rows. Score the existing spreads plans (§11.9). (The stacking-rule backtest moved to the envelope spec's E1). **Revision 4:** pre-register and start the forward scoring of the news verdicts and the spreads plan's bias (§10.8) | unchanged (`claude_cut` as today) | none |
| **1 Envelope repair** | **Moved to the envelope spec** (revision 3): the shock budget with its glide, the exposure-weighted backstop, the gap measures, the leverage-weighted group cap and stacking rule, the slow breaker spanning books, the survivability harness | unchanged | The envelope spec's E2 complete and its harness passing. **Required before any risk-changing rung** |
| **2 Knowledge** | The fact layer (§8): book truth, the dry-run roll answer, the 45-day calendar (static config + earnings), the sourced market-state additions, the track record (if D18 allows), freshness and grounding. **Facts go into the existing reviewer and roll prompts first** | unchanged | Blinded claim audit of reviews passes |
| **3 Brief, record-only** | `mastermind.db`, the one-shot process, the post-close brief, the 08:45 check, amendments, `plan_view`; R0 shadow on every decision episode; structured roll agree / disagree; the probability guardrail; the web page. Claude's endorsement of the tap-only book-repair proposals (X1 and §7) once the envelope spec's E12 is ruled. **Revision 4:** C1 stance; C2 and C3 proposals while a bridge runs; C4 record-only; Track D shadow menus and ideas; **HP applied in paper** (it needs the envelope spec's E2 buy-to-open path and this phase's brief; it is not tied to the bridge) | **R0 everywhere**, except **HP in paper** (the operator's grant, §10.7). X1, repair and hedge taps (a human decides) | ≥ 60 sessions; pre-registered evidence report per §11. HP: its own 12-month review (§10.7) |
| **4 R1 plan input, applied in paper** | `min(det, review_cut, plan_cap)` applied in paper; the pause on amendments goes live | R1 (reducing) | D1 promotion ruling on the record |
| **5 R2 select, applied in paper** | A menu ≤ baseline risk, plus skip; cross-scan allocation only if the regret test supports it | R2 (reducing) | §5.1 bar; third written exception |
| **6+ Risk-changing rungs** | R3 size within a fixed cap, R4 strike menu, auto R5 by trade class, X2 auto exits; each with a full shadow decider book first | one rung at a time | The envelope spec's E2 complete (and, for the R3 allocation lever, its leveraged sleeve live); survivability test per rung; §5.1 bars; a written exception each |
| **Live** | The operator reads each lever's record and flips `apply_live` one lever at a time; a live process re-validates its rungs at startup. **Revision 4:** HP, C4 and Track D have no live flag in this spec | | |

## 16. Decisions for the operator

### 16.1 D1–D9 (from revision 1)

The reviewers converged on most of these. Where they still differ, the dissent is given and this
revision's adjudication is marked.

| D | Question | Converged recommendation | Dissent / adjudication |
|---|---|---|---|
| **D1** | L1 plan caps | CSP only, never CCs. The plan is shown to the reviewer; the plan cap becomes a second input to `claude_cut` (`min(det, review_cut, plan_cap)`), clamped at apply time, record-only first, with a breaker on the share of flow zeroed. Promote only if it binds where the review did not, or the holdout shows the review ignoring the plan | Opus: a plan persisted before the session is the more *available* brake when reviews fail. Sonnet: no such case in 4 weeks. **Adjudicated:** keep the availability log as the promotion trigger |
| **D2** | L2a / L2b | **L2a dropped** (evidence §10.2); measure first-come vs best-of-day regret first. **L2b deferred**; if built, record-only, labelled risk-changing, materiality-only | None remaining |
| **D3** | Web research in the brief | **No in Phases 2–3.** It conflicts with the N3 hardening, and web text grounds nothing. Later only as a separate tool-bearing researcher (allow-listed domains, structured quoted rows, never groundable fact ids) feeding a tool-less decider | None |
| **D4** | L3 exits | **No auto veto.** **Yes** to X1 tap-only close / assign proposals on the existing card, shadow-valued whether tapped or not. Keep the per-decision roll review, structured and scored by short; drop the plan's per-short section | Opus first proposed folding roll reviews into the brief, then withdrew. **Adjudicated:** keep the live review |
| **D5** | Books governed | **Wheel only** for authority. Spreads keeps its own plan and picker; value is a sanity-bounded read input. **Revision 3:** spreads gets the envelope spec's fixes and account couplings, and on a ruling moves to SPXW; its picker is classified as an R4-type grant, grandfathered in paper, record-only in any live plan; its record pilots §11's machinery and is never evidence for a wheel rung (§11.10) | Opus (envelope review): the spreads book as the R2/R4 evidence lab for the wheel. Sonnet: a machinery pilot only. **Adjudicated** for Sonnet |
| **D6** | Promotion and demotion bars | **Replaced by §11:** pre-registered, decision episodes, random placebo and dumb-rule controls at the interval's lower bound, the fixed valuation rule with sign agreement, regime coverage, bars by class, a posterior demotion rule with a minimum count, a tail rule and stated false-demotion rates | None on substance. Opus favoured a full shadow decider book early; Sonnet a cheaper per-episode menu valuation. **Adjudicated:** per-episode valuation from Phase 3; a full shadow book only for risk-changing rungs |
| **D7** | Where and when | **A launcher-scheduled one-shot** (own process = own exception boundary; fresh code each run; no news budget): the brief at ~17:30 ET, a deterministic pre-open check at 08:45 ET, conditional amendments; `data/mastermind.db`; a pause of at most 20 minutes once L1 applies | Sonnet's last position: the news scheduler is acceptable for v1, with a single brief at 09:00–09:15. Opus: a post-close one-shot plus a pre-open check. **Adjudicated** on R3 information merits: both batches of information, and retry slack, without the news process's budget and failure domain |
| **D8** | Cost cap | **A per-kind call and token governor for robustness**, not a dollar cap and not an architectural driver. Ollama never plans; a Sonnet degrade is not an outage plan; a missing plan means the deterministic system | Sonnet's load estimate (+~43% context tokens, nearly all Opus) is **unverified** and secondary under R3 |
| **D9** | Claude easing the regime | **Never applied.** A record-only shadow of "would ease" reads, and of Claude's view on ladder-blocked and regime-trimmed lots | None |

### 16.2 New decisions (the reviewers' D10–D18, merged)

| D | Question | Recommendation |
|---|---|---|
| **D10** | Confirm the destination and the permanent hard lines (§1, §3), including the survivability test and fixed-terms envelopes | Adopt; add the hard lines to CLAUDE.md as the invariant's second half when Phase 3 lands |
| **D11** | The objective and primary metric: what "better" means | Income per risk-unit-day with a loss-tail term; the operator sets the exchange rate between income and drawdown. Everything in §11 depends on it |
| **D12** | The risk-classification test (§4): the measures and their tolerances | Adopt the measures as revised in revision 3: net delta, S10 by full revaluation, the G10 / P20 gap measures, exposure-weighted collateral and gross, leverage-weighted risk units; zero tolerance for "reducing" |
| **D13** | Envelope repair settings | **Moved to the envelope spec (revision 3):** the shock budget and glide (E4), the gross backstop (E5), the gap measures (E6), the slow breaker (E14), the tech-linked cap and stacking rule (E15) |
| **D14** | Book repair | **Moved to the envelope spec (revision 3), E12:** `min_strike_vs_basis` by replay with a leveraged class floor; tap-only overlays, trims and de-lever proposals once their order paths exist. Claude's endorsement of proposals stays here (§7) |
| **D15** | The value book's clamped drivers: grandfather or convert to Python-built menus | Grandfather now with the Phase 0 sanity quarantine; plan the conversion, since a relative cap imported Python's GOOGL / META fault |
| **D16** | The evaluation design (§11), pre-registered in the plan | Adopt |
| **D17** | Fidelity and fallback | Backend stamped on every row; an Ollama day counts as missing; missing days logged with their cause; the blinded claim audit before any brief reaches a lever |
| **D18** | Reopen decision 1 for the deterministic track record (§8.5) | Reopen for deterministic outcome facts only |
| **D19** | The calendar source | Static FOMC / BLS / BEA dates in config; earnings from the blackout's provider; consensus only inside the one-week window; fix the actuals look-back. **Revision 3:** the static schedule is built in the envelope spec's phase E0 and is also the spreads book's `risk.events` |
| **D20** | Score the existing 22 spreads plans before building the brief | Yes (Phase 0) |
| **D21** | What Claude sees of its own scorecard | Only buckets with ≥ 100 resolved items; Python recalibrates instead |

### 16.3 Revision 4: H11–H16 (long options, this spec's part)

H1–H10 (the bridge, its budget, instrument, stress block, S10_gross, data, tech scenarios, fence and
build) are in the envelope spec §6.1.

| H | Question | Recommendation | Dissent / note |
|---|---|---|---|
| **H11** | The §4 premium-cost dimension | Adopt: premium committed and carry as a measure; a purchase is reducing only within B0 with the stress block clear; spend above B0 inside a budget is changing (cost); lift / skip / shrink / delay is changing; T20 and S-SMH join the measures | O3 had "within budget = reducing", withdrawn in O3R; S3R's B0 gate adopted |
| **H12** | Claude's hedge roles | C1 stance (record), C2 "buy puts now" (tap, stress block applies), C3 "cash in / roll down" (tap), C4 shape at scheduled rolls (record-only through the bridge; applied in paper on a renewed programme only after ≥ 12 rolls, by an R2-type ruling). No live auto | O3R: C4 applied in paper after 12 rolls; S3R: C4 "almost empty", no evidential weight. Both kept: it is record-only while there are too few rolls to read |
| **H13** | HP, the paper put budget | Adopt as §10.7: unit 0.1% of NLV₀, one a month, ≤ 3 banked, one buy a session, Python menu on the hedge instrument with "no buy" default, Python exits, paper only, record-only in live, no S10 credit, breaker at 6 units lost or 4 units behind the schedule in 6 months, 12-month review. If the E0 capture shows the menu mostly empty at 0.1%, a unit of 0.2% with 2 banked | Both reviewers recommended tap-only; the operator chose auto in paper (OR10) |
| **H14** | HP and the VIX ≥ 25 block | **Exempt, paper only** (§10.7: a blocked test cannot observe the state its hypothesis is about; cost bounded at 3 units; measured against random buys in the same VIX state). Breakers and halts still demote it | The alternative, keeping the block, makes the record a test of calm-state timing only |
| **H15** | Track D | Shadow only, no order path in v1; Python menus; 0.25% of NLV₀ per idea; controls random direction, always-call, the same view in stock, trend, always-skip; long calls on held names or factors flagged as the same bet; bar ≥ 250 ideas and ≥ 120 market-day clusters, both valuations, ≥ +15 points pre-registered | O3R ≥ 200 ideas at $1k; S3R ≥ 250 ideas and ≥ 120 clusters at 0.25%. Adjudicated for S3R on the power calculation |
| **H16** | Hard lines 9–11 and the free streams | Adopt the three hard lines (§3); start the forward scoring of the news verdicts and the spreads bias in Phase 0 | None |

## 17. Unverified, and open research

- **The GOOGL / META value fair-value root cause** (a units fault or the method). It must be settled
  in Phase 0 before any value number reaches a prompt.
- **Whether the running approval daemon had `value.book.enabled` on** while the gross cap stayed
  silent.
- **The earnings provider's forward horizon**, and the feasibility and cost of the breadth, credit
  and skew sources.
- **The brief's cost, latency and parse behaviour** at a 30–40K context with a 40-name plan. Only
  ~1.5K-token plans have been measured.
- **Whether usage limits are per model or per account**, and the roll-review call share after
  `9da9e8a` (re-measure after one full week).
- **The independence assumptions behind §11.6.** These are an intra-day correlation of 0.1–0.5 and
  an effective N of 12–20 per day for stance IC. The table scales if they differ.
- **The CRWD and TQQQ cut values** are taken from `sizing_actions`, not recomputed from fills.
- **Which probability questions, if any, a lever will read.** If none by Phase 4, cut them.
- **How a cross-scan allocation menu would trade the cost of waiting** against a better candidate
  later. This waits on the regret measurement (§10.2).
- **Revision 3:** the envelope, leveraged-ETF and spreads unknowns (IBKR 0DTE house margin, the
  after-hours exercise cut-off, SPXW wing widths, SOXX/VOO liquidity, ThetaData coverage) are listed
  in the envelope spec §7.
- **Revision 4:** XND liquidity and IBKR's handling of it; every hedge cost and coverage figure
  (Black-Scholes with an assumed skew, no historical index quotes); whether a 0.1%-of-NLV unit buys a
  whole contract on most days; the brief's added length with the hedge block, the HP letter and three
  Track D ideas; the news-verdict scoring so far (13 ticker calls, 6 event-days) is a smoke test, not
  evidence.
