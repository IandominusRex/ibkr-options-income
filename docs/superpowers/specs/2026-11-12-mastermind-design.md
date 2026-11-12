# The Mastermind — Claude as the best-informed mind on the book — design

Date: 2026-11-12 · Status: **revision 2, for operator review**. Revision 1 (commit 6f5317f, same
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
deterministic envelope let stock plus put collateral run at 1.2–1.4× net liquidation, and its gross
cap never fired. Early phases stay record-only, because there is no evidence yet.

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
  carries more risk.
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
codified (§6.2), and Claude measured on what is left over. Nothing yet shows Claude's entry
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
| Stock plus put collateral ran above NLV for a month | Last snapshot of each session, (stock + short-put strike × 100) / NLV: between **1.18 and 1.44** on every session from Oct 13 to Nov 11 except Oct 26 (1.08). It peaked at 1.44 on Nov 5. If every put open on Nov 11 were assigned, gross long would be $810.8k (1.26×). |
| The gross cap never fired | `max_gross_notional_pct: 100.0`, but the check runs only inside `if vx.active and is_csp` (`risk_engine.py:527`). `vx.active` requires `value.book.enabled` (`books.py:115`). No `risk_verdicts` row has ever carried `gross_notional_cap`. The private `config/value.yaml` now says `enabled: true`, yet a HOOD 75P passed on Nov 9 at ~1.39×. Whether the running daemon had the book enabled at the time is **unverified**. Either way, the wheel had no working gross cap. |
| The breakers tripped, then the slow one was removed | `approval.log` shows 15 trip lines on 11 local dates from Oct 12 to Nov 11: the daily 3% loss leg and, until Nov 5, a drawdown leg **from the all-time high-water mark** (Oct 12, 23, Nov 3, 4). Commit `544e32e` (Nov 5) replaced it with a rolling 3-session 6% window because a standing drawdown re-halted every morning. NLV went from $784.6k (Oct 13) to $645.8k (Nov 11), −17.7%, with a $577.5k session-end low on Nov 5. A slide of under 2% a session never trips 6% in 3 sessions. The ledger records no deposit or withdrawal in the window (one $824 interest credit). A trip halts new openings; it does not stop assignments, which is how stock grew while NLV fell. |

**Conclusion.** Rev 1 said "the bottleneck is knowledge and placement, not the model." That holds
for the reviewer's inputs. But the larger findings are not about Claude:

- the deterministic envelope let gross exposure run at 1.2–1.4× NLV;
- the one slow breaker was removed on Nov 5;
- the book's loss sits in assigned stock that policy forbids from earning premium.

Envelope repair (§6) and book repair (§7) are where the money is. Claude's knowledge layer (§8) is
where its future authority is earned.

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
   single-name −40% shock. The book must stay inside operator-set drawdown and margin bounds in both.
   The test runs on the deterministic envelope first (§6.4). On today's numbers it would fail.
5. **Breakers are deterministic and human-held**: the daily loss leg, the drawdown leg, the slow
   breaker (§6.3), the kill switch and `LIVE_TRADING`.
6. **Humans only:**
   - `apply_live`, every rung change, the envelope, config, the universe, risk limits and the
     primary metric;
   - Claude never edits its own envelope, metric, breakers or promotion state;
   - the evaluation machinery never feeds a gate, a weight or a size (the existing `eval/` fence).
7. **Fallback = Python's baseline.** That covers an Ollama-produced, malformed, ungrounded, stale or
   missing output. Ollama never produces a lever value or a plan.
8. **Isolation.** A call that decides has no tools. Untrusted text (news, web) never sits in the
   context of a tool-bearing call that can also decide.

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
5. **It credits the safety to the wrong thing.** The book went to 1.44× NLV with no Claude authority
   at all. Safety comes from the envelope, not from the direction of the lever.

**The replacement.** For every lever application, Python computes the book after the action on a
fixed set of risk measures:

- net dollar delta;
- loss under an index −10% move (beta-scaled per name);
- committed collateral;
- gross notional / NLV;
- risk units per name, per sector and for the tech-linked group.

An application is **risk-reducing** only if it is no worse on every measure. Otherwise it is
**risk-changing**, whatever the contract count. The class decides the evidence bar (§11.5) and
whether the rung needs envelope repair first (§15).

| Action | Class |
|---|---|
| Cut an opening CSP's size | reducing |
| Close a short put early | reducing |
| A covered call written on held shares | reducing on delta and the −10% loss; it caps recovery (judged against the D11 metric) |
| Withhold a covered call | **changing** (raises delta) |
| Veto a roll | **changing** (forces assignment) |
| Nominate a name for the scan | **changing** (adds trades) |
| Size above the deterministic size | **changing** |
| A strike nearer the money | **changing** |

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
| **R3 size within a cap** | Sizes above the deterministic size, up to a fixed cap in risk units. Never above the unscaled hard caps or the **regime-scaled ceiling**: easing the regime is D9, never granted here | integer above `B`, up to the fixed cap | **changing** | Envelope repair landed (§6); the always-most-aggressive replay and the analytic worst case pass; R2 clean; the R0 "reclaim" record (what Claude would have added) positive under both valuations; a full shadow decider book over ≥ one leg of each kind | Written exception plus the cap in risk units. Note: today the deterministic size already sits at the cap or the regime ceiling, so R3 has little room |
| **R4 strike from a menu** | Chooses strike and expiry from the gate-passed chain menu, including one notch riskier than baseline, inside the fixed envelope | Python-built chain menu | **changing** | As R3, plus a clean R3 record | Written exception |
| **R5 propose trades** | Proposes trades of Python-defined classes: book repair (§7), hedges, opportunistic entries. Python builds, prices and gates them | Python-defined trade classes; a fixed "autonomy envelope" in dollars | depends on the trade | Tap-only from the start (outside the ladder). Auto only after R4 is clean, plus its own replay | Written exception per trade class |
| **X1 exits, tap** | Proposes close / assign instead of the policy's answer, on the existing decision card | Python-feasible exits | n/a (a human decides) | None (a tap adds no authority) | D4 |
| **X2 exits, auto** | Chooses among Python-feasible exits that are **risk-reducing** by §4 (for example, close instead of roll) | feasible exits ≤ the policy's risk | reducing | ≥ 100 roll-stream episodes clustered by short; beats the policy and the random control | Written exception. Never a veto that forces a leveraged-ETF assignment unless the 2026-10-14 ruling is reopened |

The destination is the top of each row with `AutonomyLevel.FULL`.

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
- **Demotion is automatic** on a breaker trip, on the slow breaker (§6.3), and on the posterior rule
  in §11.7.

## 6. Envelope repair (prerequisite phase)

Envelope repair must land before any risk-changing rung (R3, R4, auto R5). It is deterministic,
backtestable and ruled by the operator (D13). It is worth doing even if Claude never gets another
lever.

### 6.1 A gross-exposure cap that always runs

Make the existing check unconditional for opening CSPs: wheel stock plus CSP collateral (plus the
value book's claim and earmarks when it is active) ≤ `max_gross_notional_pct` of NLV.

- **First, find out why it never fired** with `value.book.enabled: true` in the private config.
- At 100%, today's book (1.26× on Nov 11) would block every new CSP. The operator rules on:
  - the level;
  - whether excess blocks new adds only (proposed) or also triggers repair proposals (§7);
  - whether assigned-at-risk collateral (puts in the money) counts at strike or at a delta-weighted
    value.

### 6.2 A correlated-exposure cap and a stacking rule

- **A tech-linked group cap** in risk units, over the `regime.tech_linked` list (23 names).
- **A deterministic stacking rule**, for example: halve, or block, a new CSP when the name already
  has an open short at an overlapping expiry, an in-the-money short, or ≥ k same-day fills.
- **Backtest both against the 10 `claude_cut` rows and the ledger.** If they reproduce most of the
  cuts, build them, and measure Claude on the residual. The record already shows the TQQQ cuts
  reacted to same-day fills, so the rule must read the live book at decision time.
- **A standing rule-harvest report** (human-read, never auto-applied). When ≥ k of Claude's
  applications share a codifiable rationale, the report names a candidate deterministic rule.

### 6.3 A slow drawdown breaker

- **A rolling 20–30-session drawdown leg** beside the 3-session one.
- **What it does on a trip.** It does not halt all trading; the all-time high-water-mark leg was
  removed on Nov 5 because it re-halted every morning in a standing drawdown. Instead it:
  - demotes every risk-changing Claude rung to record-only;
  - blocks risk-changing levers;
  - scales the CSP budget by an operator-set fraction.
  - It is reset by a human.
- **What it cannot do: stop assignment.** Gross exposure has to be controlled by §6.1, not by a
  breaker.

### 6.4 The survivability harness

- **The analytic worst case and the always-most-aggressive replay** (§3 line 4), on the 17-month
  `price_history` / `iv_history` panel with the `sizing_counterfactual.py` machinery.
- **State its limits.** The panel has one bull leg and this sell-off. It has no 2020 or 2022.
- **Run it on the deterministic envelope first.** It must pass before any rung that adds risk is
  proposed.

## 7. Book repair

The book's loss is inventory, not new flow. Every lever in rev 1 acted on new CSPs.

**The facts** (§2.3):

- 93.4% of NLV is long stock;
- $436.5k is underwater (−$131.0k);
- 64.8% of NLV is in AMD, GOOGL and NVDA;
- no calls are held, because `min_strike_vs_basis: 1.00` rejects every covered call below basis
  (21,362 contract rejections since Nov 1).

1. **The first move is an operator ruling on `min_strike_vs_basis` (D14), made by replay.**
   - The options: keep 1.00; 0.95; 0.90 with a delta cap; or per name.
   - The replay is deterministic, on the 17-month panel. For each setting it shows the premium
     harvested, the assignments below basis it would have caused (SOXL at a $153 basis against $66
     is the hard case), and the drawdown.
   - A rough size, **unverified**: 1–1.5% a month on $437k is ~$4–6k of forgone premium a month,
     before the earnings blackout and the IV/RV gates thin it.
2. **Then tap-only repair proposals that Python builds.** Each trading day Python builds a menu per
   underwater name, priced, gated and shadow-valued:
   - covered-call overlays at the ruled floor (or, as a named exception to N18 per proposal, below
     it);
   - "stop adding" (no new CSPs on the name);
   - later, trims and protective puts.

   Claude's role:
   - It chooses which proposals to surface and endorse, with reasons tied to fact ids. That is a
     selection from a Python menu.
   - The operator taps.
   - **Every proposal is shadow-valued whether tapped or not**, so operator selection does not
     contaminate the record.
   - Python sends nothing without a tap.
3. **Build order follows what exists.**
   - Covered-call overlays use the existing CC generator and order builder.
   - **Protective puts need a buy-to-open path, and trims need a stock-sell path.**
     `order_builder.py` builds option limit orders and BAG combos only. Each new order class must
     pass the Rules Engine twice, qualify its contract and use fresh quotes, and each is its own plan
     task.
4. **Decision 30 stands.** Claude never holds, delays or moves a covered call's strike. Proposing an
   overlay for a human to tap is not a hold.
5. **The plan's "reduce" stance lands here.** It becomes a repair proposal, never an automatic sale.

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

- NLV, cash, margin cushion;
- committed collateral vs deployable;
- gross / NLV;
- drawdown on the 3-session and slow windows, and the breaker state;
- concentration by name, sector and tech-linked group;
- scenario P&L for index −5%, −10% and +5% (beta-scaled).

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

- **Macro dates:** a **static FOMC / CPI / PPI / NFP / PCE / retail-sales schedule in config**
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
| ~17:30, trading days (after EOD and after-close earnings) | **The brief**, a one-shot | Opus | Tomorrow's plan (§9.3) |
| 08:45 | **Pre-open check, deterministic Python, no LLM.** Did a plan falsifier fire? Did a High-impact print land outside its playbook band? Did a pre-market earnings release or an overnight gap beyond k ATR hit a planned name? | none | A list of invalidated plan items |
| 08:45–09:20, only if the check flagged items | **Amendment** for the flagged names | Opus | Item-level amendments |
| Intraday, on a trigger (regime change, index shock, breaker trip, ±2 ATR on a held name) | **Amendment** for the affected names, ≤ 2 a day | Opus | Item-level amendments |
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
- a **dumb rule** (the §6.2 stacking rule): it tests whether the value can be codified;
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

## 13. Interaction with existing systems

- **Wheel:**
  - the candidate review gains the plan (with the plan-blind holdout);
  - `claude_cut` gains the plan input (record-only first);
  - the roll review gains structured agree / disagree and X1;
  - covered calls are untouched except through tap-only book-repair proposals.
- **Spreads:** unchanged. It keeps its own day plan and picker, and the wheel brief's thesis is not
  fed to it (correlated failure, confounded records).
- **Value book:**
  - the brief reads the value view, sanity-bounded;
  - the second written exception is unchanged, except the sanity quarantine (Phase 0) and the
    driver conversion question (D15);
  - a name may be `no_adds` for the wheel and READY for the value book, and the plan says why both
    hold.
- **Regime:** Claude's regime read is recorded beside the deterministic regime, never in place of
  it (D9).

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
| N18: `min_strike_vs_basis: 1.00` | `risk_limits.yaml` | Not addressed | **Put to the operator (D14)**, by replay |

## 15. Phasing

| Phase | Content | Claude's authority | Gate to the next phase |
|---|---|---|---|
| **0 Cleanup** | Delete the prices and IV text from `_UNIVERSE_CONTEXT` (keep tiers and structural rules; add HACK and IGV rows). **Quarantine the value fair-value fault:** withhold any VALUE NOTE whose Python fair value / price is outside [0.1, 10], flag the name in the value book, and diagnose GOOGL and META (units vs method; a change to a value rule bumps `ruleset_version`). Fix the S19 title consistency check. Date the dossier prose. Add spot, entry credit, unrealised, basis and earnings to the roll prompt, and fix its "Entry delta" label. Drop "default to sell" from the rubric. Stop writing `claude_memory`. Fix the 2-day actuals look-back. Stamp model and prompt versions on review rows. Score the existing spreads plans (§11.9). Backtest the stacking rule against the `claude_cut` rows | unchanged (`claude_cut` as today) | none |
| **1 Envelope repair** (can run beside Phase 2) | Find why `gross_notional_cap` never fired; make the gross cap unconditional; add the tech-linked group cap; add the stacking rule if the backtest supports it; add the slow breaker; build the survivability harness and run it on the deterministic envelope | unchanged | Operator rulings D13; the harness passes on the deterministic envelope. **Required before any risk-changing rung** |
| **2 Knowledge** | The fact layer (§8): book truth, the dry-run roll answer, the 45-day calendar (static config + earnings), the sourced market-state additions, the track record (if D18 allows), freshness and grounding. **Facts go into the existing reviewer and roll prompts first** | unchanged | Blinded claim audit of reviews passes |
| **3 Brief, record-only** | `mastermind.db`, the one-shot process, the post-close brief, the 08:45 check, amendments, `plan_view`; R0 shadow on every decision episode; structured roll agree / disagree; the probability guardrail; the web page. Tap-only book-repair proposals (X1 and §7) once D14 is ruled | **R0 everywhere.** X1 and repair taps (a human decides) | ≥ 60 sessions; pre-registered evidence report per §11 |
| **4 R1 plan input, applied in paper** | `min(det, review_cut, plan_cap)` applied in paper; the pause on amendments goes live | R1 (reducing) | D1 promotion ruling on the record |
| **5 R2 select, applied in paper** | A menu ≤ baseline risk, plus skip; cross-scan allocation only if the regret test supports it | R2 (reducing) | §5.1 bar; third written exception |
| **6+ Risk-changing rungs** | R3 size within a fixed cap, R4 strike menu, auto R5 by trade class, X2 auto exits; each with a full shadow decider book first | one rung at a time | Phase 1 complete; survivability test per rung; §5.1 bars; a written exception each |
| **Live** | The operator reads each lever's record and flips `apply_live` one lever at a time; a live process re-validates its rungs at startup | | |

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
| **D5** | Books governed | **Wheel only.** Spreads keeps its own plan and picker; value is a sanity-bounded read input | None |
| **D6** | Promotion and demotion bars | **Replaced by §11:** pre-registered, decision episodes, random placebo and dumb-rule controls at the interval's lower bound, the fixed valuation rule with sign agreement, regime coverage, bars by class, a posterior demotion rule with a minimum count, a tail rule and stated false-demotion rates | None on substance. Opus favoured a full shadow decider book early; Sonnet a cheaper per-episode menu valuation. **Adjudicated:** per-episode valuation from Phase 3; a full shadow book only for risk-changing rungs |
| **D7** | Where and when | **A launcher-scheduled one-shot** (own process = own exception boundary; fresh code each run; no news budget): the brief at ~17:30 ET, a deterministic pre-open check at 08:45 ET, conditional amendments; `data/mastermind.db`; a pause of at most 20 minutes once L1 applies | Sonnet's last position: the news scheduler is acceptable for v1, with a single brief at 09:00–09:15. Opus: a post-close one-shot plus a pre-open check. **Adjudicated** on R3 information merits: both batches of information, and retry slack, without the news process's budget and failure domain |
| **D8** | Cost cap | **A per-kind call and token governor for robustness**, not a dollar cap and not an architectural driver. Ollama never plans; a Sonnet degrade is not an outage plan; a missing plan means the deterministic system | Sonnet's load estimate (+~43% context tokens, nearly all Opus) is **unverified** and secondary under R3 |
| **D9** | Claude easing the regime | **Never applied.** A record-only shadow of "would ease" reads, and of Claude's view on ladder-blocked and regime-trimmed lots | None |

### 16.2 New decisions (the reviewers' D10–D18, merged)

| D | Question | Recommendation |
|---|---|---|
| **D10** | Confirm the destination and the permanent hard lines (§1, §3), including the survivability test and fixed-terms envelopes | Adopt; add the hard lines to CLAUDE.md as the invariant's second half when Phase 3 lands |
| **D11** | The objective and primary metric: what "better" means | Income per risk-unit-day with a loss-tail term; the operator sets the exchange rate between income and drawdown. Everything in §11 depends on it |
| **D12** | The risk-classification test (§4): the measures and their tolerances | Adopt the five measures; zero tolerance for "reducing" |
| **D13** | Envelope repair settings (§6): the gross cap level and scope; the tech-linked group cap; the stacking rule; the slow breaker's window, threshold and action | Rule after the Phase 1 backtests; the level for the gross cap is the most consequential (100% would block every new CSP today) |
| **D14** | Book repair (§7): `min_strike_vs_basis` by replay; tap-only covered-call overlays as named N18 exceptions; hedges and trims deferred until their order paths exist | Rule on the floor first; overlays next |
| **D15** | The value book's clamped drivers: grandfather or convert to Python-built menus | Grandfather now with the Phase 0 sanity quarantine; plan the conversion, since a relative cap imported Python's GOOGL / META fault |
| **D16** | The evaluation design (§11), pre-registered in the plan | Adopt |
| **D17** | Fidelity and fallback | Backend stamped on every row; an Ollama day counts as missing; missing days logged with their cause; the blinded claim audit before any brief reaches a lever |
| **D18** | Reopen decision 1 for the deterministic track record (§8.5) | Reopen for deterministic outcome facts only |
| **D19** | The calendar source | Static FOMC / BLS / BEA dates in config; earnings from the blackout's provider; consensus only inside the one-week window; fix the actuals look-back |
| **D20** | Score the existing 22 spreads plans before building the brief | Yes (Phase 0) |
| **D21** | What Claude sees of its own scorecard | Only buckets with ≥ 100 resolved items; Python recalibrates instead |

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
