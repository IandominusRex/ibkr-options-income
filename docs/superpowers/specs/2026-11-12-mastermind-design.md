# The Mastermind — Claude as the best-informed mind on the book — design

Date: 2026-11-12 · Status: **draft for operator review** (direction from the operator, evidence from
the 2026-11-12 audit of Claude's memory and knowledge layer, §2). Decisions marked **OPEN** in §12
are the operator's to make before an implementation plan is written
(superpowers:writing-plans). Nothing here changes the core invariant until the operator rules on
it in writing, as was done for `claude_cut` (2026-10-20/21) and the value verdict (2026-10-28/29).

## 1. Intent

The operator wants Claude to be the **Mastermind**: the mind with the most market knowledge on this
account, which knows which trades are best to enter or execute, and which not to, given current
conditions — and which knows *more* than a diligent human operator would, so that its judgment
makes the book's decisions measurably better.

"Knows more than a human" is concrete, not rhetorical. A human operator cannot, every morning:

- read every open position's live P&L, assignment odds, collateral and correlation at once;
- recall every trade this system ever made on a name, in this regime, and how it ended;
- read every filing, headline and earnings reaction for 40 names;
- hold a 45-day calendar of every event that can move any position;
- state calibrated probabilities and be scored on them, day after day, without fatigue or mood.

Claude can, **if it is given that knowledge and asked the right questions at the right moments**.
Today it is given little of it and asked almost nothing (§2). The design closes that gap first
(knowledge, §4), then gives Claude a daily job (the brief, §5), then — one lever at a time, each
measured against a deterministic baseline and each a written exception to the core invariant —
lets its judgment change what the book does (§6).

What the Mastermind is **not**: a price oracle, an order placer, or a replacement for the Rules
Engine. Its edge is breadth, recall, consistency and calibration, not prediction magic. Every
number it acts on is computed by Python; Claude contributes judgment, and the judgment is scored.

## 2. Evidence: where Claude stands today (audit, 2026-11-12)

| Finding | Evidence |
|---|---|
| Claude only sees what already passed the gate | The trade reviewer runs on Rules-Engine-approved candidates. With the regime at crisis/stressed and the scale-in ladder blocking (Nov 5–11), the scan logged "0 Claude reviews" 31 times on Nov 10–11; 2 trade reviews since Nov 4. When markets are hardest, Claude is silent. |
| The persistent memory is write-only | `claude_memory` (861 rows) is written every scan; `_load_memory` has no production caller (STATUS removed the block). 778 rows are deterministic "buy" rows; 56 have an outcome. |
| Claude cannot see the book's real state | `book_context` shows share cost but no spot: unrealised ≈ **−$136k on a $646k NLV** (NVDA −$34.8k, SOXL −$43.7k, GOOGL −$26.2k, HIMS −$11.7k) is invisible. No committed collateral, concentration %, drawdown, or the system's own record per name. |
| Static knowledge is five months stale | `_UNIVERSE_CONTEXT` (≈1.5K tokens, every review) carries June prices: QQQ ~$470 (now $675), GOOGL ~$165 ($293), SOXL ~$25 ($66), HIMS ~$35 ($21); "RGTI IVR 9.5%, wait for >40"; HACK/IGV missing. |
| Some injected numbers are wrong | VALUE NOTE fair values: GOOGL $16.29 vs ~$293 price, META (deep_value) $18 vs ~$628 — likely a per-share/units bug; 22 rows with margin of safety under −500%. Picture story S19 titled "term structure inverted" while its own text says contango. Oct CPI `actual` never recorded. |
| Horizons are too short | Event calendar looks one week ahead; trades run 3–5 weeks (Dec 8–9 FOMC absent). Dossier prose is budget-starved ("daily call budget spent — 29 names wait") and undated in the prompt. |
| The verdict is a rubber stamp | 75 of 76 Oct–Nov verdicts "sell" (the rubric says "default to sell unless you can cite…"); nothing reads it; sell verdicts −$2,788 over 53 closes. |
| The one lever that bites has paid | `claude_cut`: 10 cuts, 34 → 15 contracts; 4 resolved ≈ **+$2.3k** of loss avoided (TQQQ 65P +$699, CRWD 235P +$2,074, −$268, HOOD 75P −$194); NVDA 205P pending (≈ +$2.8k). Every rationale: "already holds the same bet" — Claude acts well on what it can see. |
| Roll reviews are unmeasured spend | 33% of all calls (265 since Oct 15; 53 on Nov 11); 607 of 617 alerts store no recommendation; the deterministic decision ignores them. |
| The value verdict works as a brake | 3 of 31 Claude verdicts changed Python's, all downward (ADBE READY→WAIT, META/ISRG WAIT→NO), correctly rejecting the bad fair values. |

Conclusion: the reasoning is good when Claude has the facts (the HOOD 75P review of 2026-11-09
cited the open ITM 85Ps and CPI/PPI inside the window and cut 3 → 1). The bottleneck is
**knowledge and placement**, not the model.

## 3. Goals, non-goals, anti-goals

**Goals**

1. Claude holds a complete, fresh, grounded picture of the book, the market, the calendar, every
   name and **the system's own history** — every fact dated and sourced (§4).
2. Claude produces one structured, dated **plan** a day, before the open, covering every held name
   and every name the scan could trade, with falsifiable reasons and calibrated probabilities (§5).
3. Claude's plan reaches decisions through **bounded, reduce-first levers**, each a written
   exception, each measured against the deterministic baseline it overrides, each with a breaker,
   paper-first and record-only in live until reviewed (§6).
4. Every Claude judgment is **scored**: decisions by counterfactual P&L against the baseline,
   probabilities by Brier score and calibration curves (§7).
5. Claude is consulted **when it matters most** — including when the gate blocks everything, on a
   regime change, a shock, and an event on a held name — not only when a candidate passes.

**Non-goals**

- Claude placing, pricing or sizing-up an order; Claude setting strikes; Claude moving a stop.
- Replacing the deterministic regime, ladder, roll policy, or Rules Engine.
- Free-text "memory" of Claude's past opinions fed back as authority (spec decision 1 of the
  market-picture design stands: outcomes are facts, opinions are not).

**Anti-goals** (failure modes the design must make impossible or visible)

- Overconfidence: a view without a probability, a falsifier and an expiry is rejected by the
  validator.
- Stale knowledge presented as current: a block past its freshness limit is dropped or labelled.
- Hallucinated numbers: every number Claude cites must match a fact id (grounding, §4.7).
- Lever creep: no lever exists without an operator ruling, a breaker, a counterfactual record and
  a promotion gate.
- Silent cost growth: a token budget per call kind with a hard daily cap (§10).

## 4. Knowledge: what the Mastermind must know

All facts are built by **deterministic Python** (no LLM), carry `as_of` and `source`, and are
assembled into one context per call kind. Claude never writes a fact; it reads them.

### 4.1 Book truth (new — the largest gap)

Per position: spot, unrealised $ and %, distance to strike in $, % and ATRs, delta, days to expiry,
extrinsic left, **probability of assignment** (from delta and the BS model already in
`analytics/black_scholes.py`), the cost if assigned (shares × strike − credits, against current
price), and the roll policy's current answer. Per name: shares, wheel-adjusted basis, unrealised,
open shorts, total exposure if every put assigns. Account: NLV, committed CSP collateral vs
deployable, cash, margin cushion, drawdown vs the 3-session high, the circuit breaker state,
concentration by name, sector and the tech-linked group, and **scenario P&L** for the index −5%,
−10% and +5% (beta-scaled per name). Built read-only in `src/reporting/` style (no writes).

### 4.2 Market state

Today's market picture (kept), plus: the regime inputs with their history (VIX, VIX/VIX3M, term
structure 9D/30D/3M, realised vs implied), index breadth (% above 50/200-day), sector relative
strength over 5/20/60 days, rates (2y/10y, curve), the dollar, credit (HYG/LQD spread proxy), the
SPY GEX map the spreads book already builds, and the put/call skew of each index. Each with its
1-year percentile so Claude can say "unusual" with evidence.

### 4.3 The event horizon (45 days)

Every event that can move a held or tradable name before the longest open expiry plus 30 days:
earnings (date, time, **implied move vs the name's last 8 realised earnings moves**), FOMC, CPI,
PPI, NFP, PCE and retail sales (**consensus, prior, and the actual once printed** — an unrecorded
actual on a High-impact event raises a data alert), ex-dividend dates, monthly opex and index
rebalances. One calendar, shared by the brief, the reviews and the web.

### 4.4 Per-name knowledge

The dossier (kept; prose **dated** in the prompt, refreshed on a priority queue — held names and
names with an event inside 10 days first — so the budget is never spent on idle names), IV rank,
IV term and skew, technical levels (supports the ladder uses, 50/200-day, ATR), the value book's
view **only when its inputs pass sanity bounds** (fair value / price in [0.1, 10], else the line
is withheld and a data alert raised), recent 8-Ks, and the news piles.

### 4.5 Self-knowledge: the track record (replaces `claude_memory`)

Deterministic outcome facts from `verdict_ledger`, `sizing_actions`, the reporting P&L and the
ledger: per name, per strategy, per regime and per setup (delta band, DTE band, IV-rank band):
trades, win rate, average P&L, loss exits, assignments, rolls and how they ended, over 30/90/365
days. Plus **Claude's own scorecard**: its cuts and their counterfactual, its plan stances and how
the name moved, its Brier score per question type (§7). This is how the Mastermind knows what has
and hasn't worked *here*, which no human operator recalls reliably.

### 4.6 World knowledge refresh

Claude's training knowledge has a cutoff; the market does not. Two sources keep it current: the
news process (kept) and, **OPEN decision D3**, a bounded web-research turn in the daily brief (the
CLI's WebSearch, capped at N searches, results summarised into dated, sourced facts that the
grounding step can cite). Without D3 the news process is the only window.

### 4.7 Freshness and grounding

Every block has a freshness limit (book: 5 min intraday; picture: 6 h; dossier prose: 3 trading
days; calendar: 1 day; track record: 1 day). A stale block is labelled `STALE since …` or dropped.
Every number in Claude's structured output that is not a probability must match a fact id within
tolerance (the pattern of `src/news/grounding.py`); an ungrounded output falls back to the
deterministic baseline and is counted.

**Cleanup of today's inputs (Phase 0):** delete the price/IV numbers from `_UNIVERSE_CONTEXT`
(keep tier and structural rules; add HACK/IGV); withhold broken value fair values; fix the
picture-title consistency check (S19); extend the calendar horizon; date the dossier prose; add
spot, entry credit, unrealised, basis and earnings to the roll prompt (and fix its "Entry delta"
label); stop writing `claude_memory` (or drop it) once §4.5 exists.

## 5. The daily cycle: what Claude is asked, and when

| When | Call | Model | Output (structured, validated) |
|---|---|---|---|
| 08:30 ET, trading days | **The brief** | Opus | The day's plan (§5.1) |
| On trigger (regime change, index shock, an event or ±2 ATR move on a held name, the circuit breaker) | **Re-brief** for the affected names | Opus | A plan amendment, dated |
| Every scan with candidates | Candidate review (kept), now **against the plan** | Sonnet | Per candidate: fits the plan or not, contracts cut (lever L0/L1), rank among gate-passed peers (L2) |
| Every roll / close decision | Exit view | Sonnet | Agree / disagree with the deterministic answer, a probability, a reason — stored, scored (lever L3 later) |
| 16:30 ET | **Debrief** | Sonnet | What moved against the plan; which falsifiers fired; the day's probability questions resolved (scored by Python, not Claude) |
| Weekly (Sat) | **Retrospective** | Opus | Lessons as dated text with the evidence ids behind each — shown to the operator and in the next briefs as *notes*, never applied to config |

### 5.1 The plan (one per trading day)

- **Market thesis**: 3–5 sentences; the regime as Claude reads it vs the deterministic regime;
  2–3 **falsifiers** ("if SPY closes under 732.71, the bottoming read is wrong").
- **Per name** (held and tradable): stance — `add` / `hold` / `no_adds` / `reduce`;
  `max_new_lots` (an integer, reduce-only against the deterministic size); `until` (a date or an
  event id); key level; the reason (fact ids); and **probability questions** with an expiry, e.g.
  P(NVDA closes ≥ 205 on Nov 13) = 0.03, P(assignment of HOOD 85P) = 0.7.
- **Per open short**: preferred outcome (roll / assign / close / hold) with a probability and the
  reason — compared with the roll policy's answer.
- **Opportunities**: names or setups the deterministic scan is not looking at today that Claude
  thinks deserve evaluation (lever L2), with why.
- **Avoid list**: names Claude would not add to at any size today, with the falsifier that would
  lift it.

The validator rejects a plan whose stances lack reasons, whose probabilities lack expiries, whose
numbers are ungrounded, or whose `max_new_lots` exceeds the deterministic size (reduce-only by
construction). A rejected or missing plan means **the deterministic system runs unchanged** — the
Mastermind is never a dependency (as today's fallback rule).

## 6. Levers: how judgment reaches the book

Each lever is a separate, written exception to the core invariant, ruled on by the operator before
it is built, with the same shape as `claude_cut`: one clamped Python function, paper-applied and
record-only in live (`apply_live: false`) until the record has been read, a daily breaker, an
Ollama- or malformed-produced value meaning the deterministic answer, and a counterfactual row for
every application.

| Lever | What Claude may do | Bound | Why it is safe | Status |
|---|---|---|---|---|
| **L0** size cut | Lower an auto-opened CSP's contracts | integer, ≤ deterministic | exists | built (`claude_cut`) |
| **L1** plan caps | Apply the plan's `no_adds` / `max_new_lots` / `until` to new CSPs **and** covered calls on a name for the day | reduce-only; expires with the plan | can only make the book take less risk; deterministic gates unchanged | **OPEN D1** |
| **L2a** ranking | Order gate-passed candidates when the budget, the regime or the daily limit allows fewer than pass | a permutation of the gate-passed list; nothing added | the spreads picker pattern: Claude picks from a menu Python built and gated | **OPEN D2** |
| **L2b** nomination | Add a name or setup to the next scan's evaluation list | the deterministic scan, gate and sizer still decide everything | it can only cause Python to *look*; every order still passes the Rules Engine twice | **OPEN D2** |
| **L3** exit veto / proposal | Veto a deterministic roll (fall back to the policy's no-roll answer), or propose an early close **with a tap** | veto = the policy's own fallback; close = operator tap | a veto never adds risk the policy did not already choose; a close waits for a human (the value book's rule) | **OPEN D4** |

Explicitly **not** levers: anything that raises a size, lowers a gate, sets a price or strike,
adds a name to `universe.yaml`, edits config, or sends without a Rules Engine pass.

Promotion between levels requires the §7 record to clear its bar on paper first.

## 7. Measurement: is the Mastermind better?

Every lever application stores the deterministic baseline next to Claude's decision, and the
outcome is reconciled on close (the `sizing_actions` / `verdict_ledger` pattern):

- **Counterfactual P&L** per lever: what the baseline would have made vs what Claude's decision
  made, with the dollars avoided and forgone shown separately (today's L0 record already does this).
- **Calibration**: every probability in the plan resolves to 0/1 on its expiry date; Python scores
  the Brier score per question type and draws a reliability curve. A Mastermind that says 0.7 must
  be right ~70% of the time; one that is not is shown that in its next brief.
- **Stance accuracy**: `no_adds` / `avoid` names vs the name's move over the stance's life, against
  a naive baseline (the regime alone).
- **Promotion bar (proposal, OPEN D6)**: ≥ 30 resolved applications, counterfactual net positive,
  Brier below the naive baseline's, no breaker trips in the last 10 sessions. **Demotion**: two
  consecutive weeks net negative turns the lever back to record-only automatically.
- A web page under `/more/claude` (extending today's "What Claude knows") shows the plan, the
  scorecard and every lever's record.

## 8. Placement and fences

- `src/mastermind/` — **enrichment tier**: prompt builders, the brief/debrief/retrospective calls
  (through `src.claude.cli` only, slim, outside the repo), the plan validator and grounding. On
  `tests/test_eval_skills.py`'s enrichment list. Imports nothing from `src.engine`,
  `src.execution`, `src.strategies`.
- Fact builders (§4.1–4.5) — **read-only, deterministic**: `src/reporting/` (book truth, track
  record) and `src/analytics/` (market state additions), so the engine may read the same facts
  without importing enrichment.
- The plan store — its own table(s) written only by `src/mastermind/`; the trading path reads the
  **validated, clamped** caps through a neutral reader `src/common/plan_view.py` (the
  `value_view` pattern: read-only, plain SQL, no enrichment import), and only the reduce-only
  fields. The lever functions live in `src/engine/` beside `claude_cut`.
- Process: the brief and debrief run in the news process's schedule or a new `scripts/run_mastermind.py`
  with no IBKR connection (**OPEN D7**); re-briefs are enqueued by the trading process as
  commands, never called inline on the order path.
- A fence test like `tests/test_value_fence.py` for the new package and the reader.

## 9. Interaction with existing systems

- **Wheel**: L1 caps apply after the ladder and the regime (a further reduce-only clamp); the
  candidate review gains the plan; roll reviews become the plan's "per open short" view plus a
  stored agree/disagree (and shrink to one per decision key per day).
- **Spreads**: the spreads picker keeps its menu; the brief's market thesis and falsifiers are
  added to its context (no new lever unless ruled).
- **Value book**: the plan reads the value view (sanity-bounded); the value verdict exception is
  unchanged. A name can be `avoid` for the wheel and READY for the value book — the plan must say
  why both hold.
- **Regime**: Claude's regime read is recorded beside the deterministic regime, never replaces it.

## 10. Cost and models

Brief (Opus, ~25–40K context, ~3K out) once a day; re-briefs ≤ 3 a day; debrief and retrospective
small; candidate reviews unchanged; roll reviews **fewer** (one per decision key per day). Estimate
at today's prices: ≈ $1.5–3 a day notional, offset by cutting the 33% of calls spent on unmeasured
roll reviews. Hard daily cap per call kind in config; past the cap the deterministic system runs
alone. Ollama never produces a lever value (existing rule).

## 11. Phasing

| Phase | Content | Lever status |
|---|---|---|
| 0 | Input cleanup (§4.7 list); value fair-value quarantine; roll prompt fields; verdict rubric honest (drop "default to sell"); stop the write-only memory | none |
| 1 | Book truth, track record, 45-day calendar, market-state additions; dated, grounded context assembly | none |
| 2 | Daily brief + debrief + weekly retrospective; plan store; calibration scoring; web page | record-only (every lever computed, none applied) |
| 3 | L1 plan caps | paper-applied, live record-only |
| 4 | L2a ranking, L2b nomination | paper-applied after Phase 3 clears the bar |
| 5 | L3 exit veto / tap-proposal | paper, after Phase 4 |
| Live | Operator reads the record per lever and flips `apply_live` one at a time | |

## 12. Decisions for the operator

- **D1** Approve L1 (plan caps, reduce-only, CSP + CC, day-scoped) as the third written exception?
- **D2** Approve L2a ranking and/or L2b nomination? (L2b is the "find the best trades" lever.)
- **D3** Allow a bounded web-research turn in the brief (N searches/day), or news process only?
- **D4** L3: roll veto (auto, fallback to the policy's answer) and/or close proposals (tap only)?
- **D5** Which books does the plan govern: wheel only, or also spreads and value?
- **D6** The promotion and demotion bars (§7).
- **D7** Where the brief runs (news process vs a new mastermind process) and its time (08:30 ET?).
- **D8** Daily cost cap.
- **D9** Should Claude's regime read ever ease the deterministic regime (raise budgets)? Proposed
  answer: **no** — it is risk-raising; record it beside the regime only.

## 13. Open questions to research before the plan

- Which probability questions are worth asking daily (assignment, ±X% by expiry, earnings move vs
  implied) so the calibration record fills fast enough to be meaningful within ~6 weeks.
- Whether the brief should see the previous day's plan (continuity) — and how to stop it anchoring
  on its own past calls (proposal: show the previous plan *with its scored outcomes*, never alone).
- How to score L2b nominations fairly (a nominated name the gate rejects is not a Claude loss).
- The GOOGL/META value fair-value bug: an input/units fault or the method — must be resolved in
  Phase 0 before any value number reaches the brief.
