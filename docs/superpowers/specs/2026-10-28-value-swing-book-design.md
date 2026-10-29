# The Value book — healthy companies, bought below worth, held until it runs

Date: 2026-10-28 · Status: **draft, awaiting operator approval** (nothing is built)
Revised 2026-10-28 with two operator changes: **the ticker file** (every name analysed is kept, fresh on
search, in two parts — §6.9, §8.3) and **exit-plan re-evaluation** when something moves a held stock
(§7.1). Then two fixes from the review: a **wider evidence universe with a ranked monthly record**
(§6.1, §6.8) and **three exit policies shadowed side by side** (§7, §12).
**Revision 2 (2026-10-28, operator Q&A — §19 records every answer):** two lists, **deep value** and
**quality growth** (§6.0); the filter loosened to *health is hard, price is judgement*; **Claude decides
the verdict on healthy names**, sets fair value through bounded drivers that Python computes and
clamps (≤ 1.5× Python's), and that fair value reaches sizing and the wheel's put ceiling (§8.2), with
a Python-only baseline recorded beside it; a ticker may be **held by the wheel and the value book at
once** (§9.2); the live exit policy defaults to `value` (§7); puts and shares go to paper together
(§9). Sections superseded by revision 2 say so in place.
**Revision 3 (2026-10-29, adversarial Opus review + operator answers, §19):**
- **Contradictions fixed.** Automatic exits read Python's fair value only; a Claude-lowered value
  waits for a tap. Shock stops apply only under `full`. The clamp is one rule.
- **Share tracking redesigned so the books can share a ticker from day one:** an `orderRef` tag on
  every value order, a value-owned approval and executor on clientId 31, an independent wheel share
  count, and fail-closed reads.
- **Banks and cyclicals get their own health sets.**
- **The growth valuation is loosened** (8% discount rate, half of stock-based pay).
- **Claude's driver bounds are tightened,** with a circuit breaker.
- **The go-live section now says what it can and cannot prove,** and the point-in-time backtest
  (Stage 1b) is mandatory.
- **A calibration dry run is the first build step.**
Builds on: `src/research/` (SEC fundamentals + the 40-check engine), `src/news/dossier.py` ("what
Claude knows"), `src/regime/` (market regime), `src/spreads/` (the pattern for a second book in the
same account), `src/strategies/buy_candidates.py` (the covered-call-suitability list this does not
replace).
Argued before writing: an Opus review of the first draft of this direction (adversarial; its
points are folded in below and the ones that changed the design are marked **[Opus]**). A Sonnet
sweep of ~50 external systems is the source of the "borrowed / rejected" table in §15.

## 0. In plain English

The system today sells options for income. This adds a **fourth book that buys shares of healthy,
strong companies when they trade below what the business is worth, holds them while the price climbs
toward that worth, and sells when the story breaks or the climb is done.** It keeps two lists:
**deep value** (good businesses priced as if they were bad — a bank like BAC, a cyclical like MU near
the bottom of its cycle) and **quality growth** (great, growing businesses at a fair price — GOOGL or
META on a bad quarter, and names like them you know less well).

It grows in three stages, and you can stop after any of them:

1. **A scorecard (days).** Every night, Python looks at the S&P 500 and your own lists and answers,
   from filings and prices, with no AI: *Is this a healthy business that will survive? Which list
   does it belong on? Roughly what is it worth?* **Health is a hard line** — a company that fails it
   is NO, whatever anyone thinks of the story. Behind the scenes the scorecard *pretends to trade*
   its own picks and keeps score against the market — the Python-only baseline.
   Nothing it works out is thrown away: every company it has ever looked at keeps a **ticker file**,
   and when you search a company on Research the file is shown — or, if it is out of date or missing,
   rebuilt on the spot, because the numbers are cheap to compute.
2. **Claude as the analyst — and the judge (weeks).** For the healthy names Python ranks highest,
   and for any company you ask about, Claude reads the filings and the news and decides: **READY**
   (buy now), **WATCH** (right company, wait for the price to settle), **WAIT** (right company, wrong
   price) or **NO** — with its own fair value, the story, the bear case and what would prove it wrong.
   Claude does not type a fair value; it picks the assumptions (growth, margins, discount rate) inside
   fixed bounds and **Python does the arithmetic**, then caps the result at 1.5× Python's own number.
   That page of notes is "what Claude knows" about the company, and it refreshes when a filing lands,
   earnings come out, the price jumps, or you `/scan` it.
3. **Money (only after the evidence, paper first).** Two ways to act, switched on together. *Sell a
   put* through the existing wheel at a strike no higher than the price worth paying — how a **WAIT**
   company is played. Or *buy shares* of a **READY** company from a dedicated pot, with its own gate
   and Telegram thread — even a company the wheel already trades (the system tracks whose shares are
   whose). Each position carries its exit plan from day one: sell half at fair value, sell the rest
   if the story breaks or fair value falls below the price, with a −30% emergency stop. When
   something moves a held stock — an outsized price move, earnings, a filing that signals trouble —
   Python notices and **re-evaluates the plan**: it may tighten it or propose a sale, never loosen it,
   and a headline alone never changes what the company is worth.

What it will look like: a **Top opportunities** strip on Research with a Deep value and a Quality
growth tab (company, READY/WATCH, a bar showing price vs fair value, the margin of safety, "buy
shares" or "sell a put at or below $X");
a rebuilt stock page that opens with the verdict and answers your three checklist questions before
showing any raw data; a **Value** card on Home beside CSPs, CCs and Credit Spreads; and `/value` in
Telegram.

## 1. Intent

The operator wants Research to behave like a value-investing layer: surface strong, healthy,
undervalued companies with real upside, let the system act on them with a dedicated pot of capital,
and hold each until the price has run up on the undervaluation — then sell on a deterministic sign
that the run has peaked or is reversing.

**What the operator said** (condensed from their messages):
- Mostly Python and deterministic calculation. Claude "when necessary" to build DCFs/models,
  justify, and bring in news and the market picture.
- Everything researched is added to "what Claude knows" for that stock and stays fresh as news
  arrives and `/scan` runs.
- `/stock/ticker` is lackluster; rebuild it.
- A top-of-`/research` section of the highest-potential companies, to hold for weeks/months **or sell
  puts on**; the system acts on it with dedicated capital; a new subsystem on Home next to CSPs,
  CCs and Credit Spreads, plus value-stock trades.
- A Claude skill for the per-stock verdict, in the shape of `da-vinci`.
- His checklist: (1) is the business doing what we bought it for — a headline alone changes
  nothing; no, or a high P/E, means the price ran ahead of earnings; (2) a margin of safety — pay
  well under worth, worth from profitability + moat, balance sheet and a free-cash-flow valuation;
  (3) how much to buy depends on the cycle; protect the downside in a bear market.
- **Holding period (2026-10-28):** "long enough for the price to run up based on the undervalued
  stock, and based on deterministic calculations, sell when it starts reversing or when it has
  topped." Not a fixed number of weeks.
- **The ticker file (2026-10-28):** the Python layer must not discard what it parses. Keep a ledger of
  every stock it analyses; when a stock is searched on Research, show that layer, or build it
  instantly so the data is fresh. Two parts per ticker: the deterministic data, cheap to generate;
  and the AI analysis, run manually when the stock is researched, and **automatically for stocks that
  pass the deterministic checks and are to be recommended**.
- **Re-evaluating exits (2026-10-28):** every position gets its exit plan from day one, but news or a
  change that causes a significant move must trigger a re-evaluation of that plan, and **the
  deterministic Python decides when**.
- **Revision 2 (2026-10-28):** "I am okay with lowering the filter guard and letting Claude have more
  say and leeway. As long as the stocks that are proposed are healthy, strong companies with high
  potential for growth and survivability, that's a go." Two lists — healthy strong companies "GOOGL,
  META etc, and any stock like these", and deep value "perhaps MU, BLOOM, BAC". The full Q&A is §19.

**Success** is not "it picks winners". It is: after two or three quarters of forward shadow record,
a human can read one report and say whether the picks beat the market and a do-nothing control, net
of the exits, on closed trades — **and whether Claude's verdicts beat the Python-only baseline** — and
every number that reached an order was computed by Python, either from sourced inputs or from
Claude-chosen drivers that Python bounded and clamped (§8.2). There is **no**
assumption that this has an edge; the design exists to measure it **[Opus]**.

## 2. Who decided what

| | |
|---|---|
| **Operator decided** | A value/quality layer; a top strip on Research; a dedicated capital pot; a new book on Home; the checklist above; Claude supplies analysis. A kept ticker file per analysed name, fresh on search, in two parts. Deterministic triggers that re-evaluate a held position's exit plan. **Revision 2 (§19):** two lists (deep value, quality growth); health and earnings-quality gates stay hard; fair value no longer the lowest method; Claude decides the verdict on healthy names, its fair value sets size and reaches the wheel's put ceiling, capped at 1.5× Python's; shared tickers between wheel and value book; timing strict for deep value, soft for growth; healthy, fairly priced high-flyers allowed on the growth list; `value` exit policy by default; puts and shares together; the go-live bar of §12 as written; a tight Claude budget with the right model per job. |
| **My calls (change them freely)** | Three stages with the money last; the exit engine's exact shape (§7); `src/value_ai/` as the Claude package; clientId 31; the validation gate (§12). The ticker file's mechanics (§6.9); which names are "recommended" for the automatic Claude run (§8.3); the trigger list and its thresholds (§7.1); shadow-running re-evaluated vs original plans. Revision 2: the two lists' entry rules (§6.0); median-of-methods and the growth DCF (§6.5); the driver bounds Claude chooses within (§8.2); the share-attribution mechanics (§9.2); size tiers per list (§9.5); the model routing and budget numbers (§8.5). |
| **Revision 3 (§20)** | Operator: size from Claude's margin of safety; growth valuation loosened (r 8%, half SBC); sharing from the first share purchase; assigned puts are wheel stock. My calls, from the review: everything in §20's "fixed without asking" table. |
| **Operator, 2026-10-29 (§14)** | Pot 70% wheel / 30% value; stop and thesis exits send without a tap in auto mode, per the autonomy ladder; not a US taxpayer (no wash-sale rule). My calls: the ready-buffer reservation, one shared pot with a 70% per-list cap, 20 positions max. No open decisions remain. |

## 3. Goals, non-goals, anti-goals

**Goals**
- Every proposed company is **healthy, strong and built to survive** — the operator's one
  non-negotiable, enforced by Python gates Claude cannot override (§6.4).
- One verdict per company, with every number traceable to a filing, a price, or a Claude-chosen
  assumption that Python bounded and computed — and every threshold written down where the operator
  can read it (`config/value.yaml`).
- The same verdict on the Research strip, the stock page, Telegram and Claude's own notes — one
  computation, many readers.
- A shadow record from the first night, so there is evidence before there is money.
- Exits that are mechanical and decided at entry, not improvised in a drawdown — and re-evaluated by
  rule, not by mood, when an event moves the stock.
- Claude's knowledge of a company stays fresh without anyone asking.
- Nothing computed is thrown away: any name ever analysed has a ticker file and a history, and a
  search never shows stale numbers that could have been recomputed.

**Non-goals (v1)**
- No covered calls on value-book shares (§9.2; the wheel's own shares in a shared ticker are the
  wheel's). No options on the value book at all except puts through the wheel.
- No shorting, no leverage, no ETFs, no pre-profit or REIT names (reasons in §6.5).
- No intraday trading. Verdicts and exit checks run on daily closes; orders go out the next session.
- No auto-tuning. Nothing the shadow ledger measures may change a threshold on its own.
- No second AI model scoring the first.

**Anti-goals — what would make this a failure even if it technically works**
- An unhealthy company on either list. A pre-profit, over-indebted or diluting name proposed because
  Claude liked the story is the failure this design exists to prevent. (Revision 2 drops the old
  "no momentum names" anti-goal: a healthy, fairly priced PLTR or CRWD may sit on the growth list —
  §6.0. The deep-value list should still look like insurers, banks, industrials, healthcare, energy.)
- Any path by which **an unbounded or unverified** Claude number reaches an order: Claude chooses
  assumptions inside fixed bounds, Python computes and clamps (§8.2); a malformed reply means the
  Python baseline, never a guess. Claude never sets a price, places an order, or overrides the risk
  gate or a health gate.
- A "dedicated" pot that the wheel quietly spends (§9.3).
- Thresholds that drift after a loss. The ruleset is versioned and frozen (§12).
- A pretty page whose verdict nobody can reproduce from the filings.

## 4. What exists, and what is missing

Exists (so this builds on it, not beside it): SEC companyfacts → `financials` in `research.db`
(`src/research/ingest/`); 40 pass/fail checks (`config/research_checks.yaml`, `src/research/checks/`);
yfinance `FundamentalStats` (P/E, FCF, debt/equity, analyst targets, `src/analytics/fundamentals.py`);
technicals and support levels (`src/analytics/technicals.py`, `support_levels.py`, `scale_in.py`);
the market regime (`src/regime/`, `src/storage/regime_state.py`); the per-name dossiers
(`src/news/dossier.py`, ~33 names, hourly numbers, Claude prose a few times a day, `/scan` and
reviews refresh them through `dossier_touches`); the neutral renderers (`src/common/dossier_text.py`).

Missing: any notion of what a company is **worth**; a moat/quality composite; a verdict; a screen
over more than the wheel's names; a stock-buy order path (`Stock(` appears only in contract
construction and one fresh-quote read — no module places a stock buy); a way to reserve cash for a book (`src/engine/capital.py::resolve_caps` hands the
wheel the account's whole excess liquidity); point-in-time fundamentals (`select_periods` takes the
*latest* filing, right for display, wrong for any backtest); and a stock page that leads with an
answer.

Facts verified in the code while writing this (they shape the design):
1. `src/orchestrator/scan_pipeline.py:273` passes **any** held `STK` position in a scanned symbol to
   the covered-call screen. Value shares in a name the wheel scans would be written against.
2. `resolve_caps` has no per-book carve-out. A sleeve is fiction until it has one.
3. Headless Claude runs with `--tools ""` and `--disable-slash-commands`
   (`src/claude/cli.py::build_cmd`, slim mode): a skill cannot load there.
4. The `reserved_for_spreads_book` rule (`risk_engine.py:253`, `command_drain.py`, `api/deps.py`) is
   the pattern for keeping a book's names out of the wheel — but spreads' book is a fixed list; this
   one is dynamic (§9.2).

## 5. The shape

```
                 nightly + on filings               on demand / on events
  EDGAR facts ─┐                                  ┌─ /scan NAME, news, earnings, filing
  prices ──────┼─► src/value/  (deterministic) ◄──┤
  regime ──────┘     │  data-quality ─ quality ─ valuation ─ timing ─ verdict ─ exit plan
                     │                │
                     ▼                ▼
                data/value.db    shadow ledger  ──► scripts/value_report.py   (the evidence)
                     │
        ┌────────────┼──────────────────────────────┐
        ▼            ▼                              ▼
  src/api (ro)   src/value_ai/ (Claude)                Stage 3: src/value/risk.py gate
  /research strip   verdict · drivers · thesis · facts  ─► approval ladder ─► stock order
  stock page        └─ validated, bounded, computed and clamped by src/value/ ─┘
  Home · Telegram
```

Two tiers, same split the rest of the repo uses. **`src/value/` is deterministic**: it computes the
health gates, the baseline verdict, every number, and in Stage 3 the orders. **`src/value_ai/` is
Claude**: it proposes a verdict, valuation drivers, prose and extracted facts as plain data;
`src/value/` validates the shape, bounds the drivers, does the arithmetic, clamps the result and
stores it (§8.2). Revision 2 lets that validated verdict decide entries on healthy names — the one
place Claude's judgement reaches an order, written as an exception to the core invariant (§18).
`scripts/run_value.py` is the only module that imports `src/value_ai/` — exactly the `spreads` /
`spreads_ai` arrangement, where Claude also picks and Python re-gates.

## 6. Stage 1 — the scorecard (`src/value/`, no Claude, no orders)

Nothing here imports `src.claude`, `src.news`, `src.value_ai` or any enrichment module.

### 6.0 Two lists (revision 2, operator decision; the entry rules are my call)
Every name that passes the health gates (§6.4) is placed on one or both lists:

| | **Deep value** | **Quality growth** |
|---|---|---|
| What it is | A good business priced as if it were a bad one | A great, growing business at a fair price |
| Looks like | Banks and insurers (BAC), industrials, healthcare, energy, cyclicals near the bottom of their cycle (MU) | GOOGL or META after a bad quarter, and less familiar names with the same shape |
| Extra entry rule (beyond health) | None — cheapness is the point | 5-year revenue CAGR ≥ 10% (or FCF/share CAGR ≥ 10%), 5-year median ROIC ≥ 15%, gross-margin standard deviation ≤ 5 points |
| Python fair value (§6.5) | Median of A, B (haircut growth), C; justified P/TBV for banks and insurers | D (growth DCF, revision 3 loosened inputs), median with C once C exists; A shown as the floor |
| Python's required margin of safety (normal regime) | 25% | 10% |
| Timing (§6.6) | Strict: must have stopped falling | Soft: refused only below its 200-day SMA *and* at a new 52-week low |
| Size tiers by margin of safety (§9.5) | 25–35% → 3%, 35–45% → 5%, > 45% → 8% of the pot | 10–20% → 3%, 20–30% → 5%, > 30% → 8% |

A name that qualifies for both is filed on the one where its rank score (§6.8) is higher and tagged
with both. **High-flyers** (PLTR, CRWD, HOOD) may sit on the growth list when they pass health and the
price does not assume more growth than they have delivered — but the health gates the operator kept
will likely still refuse several of them today (GAAP losses inside the last five years, share
dilution above 3%/yr). That is the gates doing what the operator asked of them. Pre-profit names
(RKLB, ASTS, NBIS) stay out of both lists.

### 6.1 Universe
Names the operator might own for months: `universe.yaml` (`would_own` ∪ `watchlist`) plus a
committed S&P 100 snapshot (`config/value_universe.csv`, with its as-of date). ETFs and leveraged
ETFs are `not_applicable`. Wheel names (GOOGL, META, BAC…) are ranked like any other; revision 2
lets the value book hold them alongside the wheel (§9.2), and offers a put through the wheel too
(§9.1).

**Two universes (revision 2026-10-28).** The universe above is the **trading universe**: the names the
strip shows and Stage 3 may act on. The **evidence universe** is wider: a committed S&P 500 snapshot
(`config/value_evidence_universe.csv`, with its as-of date) scored nightly by the same code into the
same ticker files (§6.9), used only by the shadow ledger (§6.8). A strict rule set might fire READY a
handful of times a quarter on a hundred names; on five hundred, and with the ranked record below, the
evidence arrives in quarters rather than years. Cost: ~500 companyfacts payloads once, then ETag
reuse; the research worker already rate-limits EDGAR at 10 req/s.

### 6.2 Data, and point-in-time honesty **[Opus]**
- Fundamentals: SEC companyfacts through the existing `src/research/ingest/` path (10 req/s, ETag
  reuse). Prices: the existing bulk price provider. Shares/market cap: EDGAR cover-page share
  count × price, **cross-checked against yfinance market cap**.
- `select_periods` gains an `as_of` argument: the value *first filed* on or before that date, not the
  latest. Display keeps latest-wins; every scorecard and every shadow-ledger row uses `as_of`.
- Restated figures never leak into a past verdict. Prices carry yfinance's survivorship bias
  (delisted tickers are absent); the ledger says so on every report.

### 6.3 Data-quality gate (runs first; a failure is `UNKNOWN`, never `FAIL`)
EDGAR vs yfinance market cap within 10%; at least five annual periods; latest filing no older than
a config age; share-class mapping applied (GOOG/GOOGL); units supported. A name that fails here
shows why and is not ranked.

### 6.4 Health gates — hard, a conjunction, and Claude cannot override them
The operator's non-negotiable is "healthy, strong companies with survivability", so these stay strict
under revision 2. All must pass (thresholds are defaults in `config/value.yaml`); a failure is `NO`
whatever Claude thinks:
- **Financial health (operating companies):** Piotroski F-score ≥ 6; Altman Z > 1.8; profitable in ≥ 4
  of the last 5 years; free cash flow positive TTM and in ≥ 3 of 5; net debt / EBITDA ≤ 3.0; interest
  coverage ≥ 4.
- **Earnings quality and dilution (operating companies):** Beneish M ≤ −1.78; diluted share count
  growth ≤ 3%/yr (stock-based comp that buys the owner nothing).
- **Banks and insurers get their own health set** (revision 3). A bank's interest expense *is* its
  cost of goods, so coverage, FCF, Piotroski, Altman and Beneish are meaningless for it — BAC's
  coverage is ~1.3. Instead: profitable in ≥ 4 of 5 years; ROTE 5-year median ≥ 10% with standard
  deviation ≤ 4 points; tangible book per share growing over 5 years; net charge-offs / loans not
  above 1.5× its own 5-year median; CET1 ratio ≥ the regulatory minimum + 2 points (banks; from XBRL
  where tagged, otherwise `UNKNOWN` — never a silent pass); combined ratio ≤ 100% in ≥ 4 of 5 years
  (insurers); dilution ≤ 3%/yr.
- **Cyclicals are judged across the cycle, not the trough** (revision 3). For a name on the cyclical
  list (sector list, or FCF-margin variability above the config bar — §6.5), the TTM tests become
  count-of-five-years tests: FCF positive in ≥ 3 of 5, profitable in ≥ 3 of 5, and net debt / EBITDA
  on 5-year median EBITDA. Otherwise MU would fail exactly when it is cheapest.
- The **moat proxy** (5-year median ROIC, gross-margin stability) is no longer a hard gate: it is part
  of the quality-growth entry rule (§6.0) and the rank score (§6.8), and is still **called a proxy** —
  nothing here says a company *has* a moat.
These answer checklist item (1) in part (is the business healthy and doing its job); the news-side
half ("did a headline change anything?") is Stage 2.

### 6.5 Valuation — Python's fair value is the **median** of the applicable methods
*Revision 2: was the minimum. Stacked with a 25% margin, a growth haircut and lower-only Claude
adjustments, the minimum refused almost everything; the operator unticked it.* All inputs here come
from filed history; this is **Python's** fair value — the baseline, and the anchor Claude's fair value
is clamped to (§8.2).

| Method | What it is | Use |
|---|---|---|
| **A. Earnings power** | Normalised, SBC-adjusted free cash flow per share ÷ (r − g_floor), r = 9%, g_floor = 2% | The floor value. Normalised FCF = TTM FCF − SBC; for cyclicals (sector list, or FCF-margin variability above a config bar) use the 5-year median FCF margin × TTM revenue |
| **B. Reverse DCF** | Solve the 10-year FCF/share growth the price implies (fade linearly to 2.5%, r = 9%). Pass if implied ≤ 0.7 × realised 5-year FCF/share CAGR (realised capped at 15%). Fair value B = the same DCF run at that haircut growth | The "has the price run ahead of earnings?" test, as the operator put it |
| **C. Own-history percentile** | Median of the company's own 10-year EV/FCF (or P/E) applied to normalised FCF | Added once point-in-time price history is in place; absent until then |
| **D. Growth DCF** (quality growth only) | 10-year DCF on growth-normalised FCF/share at the realised 5-year FCF/share CAGR, capped at 20%, fading linearly to 2.5%, **r = 8%**. Growth-normalised FCF = TTM FCF − **50%** of SBC (revision 3, operator: "loosen the growth valuation") | The "fair price for a grower" method. B without the haircut is the same DCF at r = 9%, so it is not counted as a second method for this list; D stands alone until C exists |
| *Forward DCF with user scenarios* | Shown on the page, labelled illustrative, **never gates** | It is a reverse DCF with more knobs |
| *Analyst targets* | Dropped. Not used anywhere. | Consensus is a sentiment signal, not a value |

`python_fair_value = median(the list's methods, where present)` (§6.0; with two methods present, their
mean). *What the loosened growth inputs buy (revision 3, rough 2025 figures — FCF ~$73B, SBC ~$24B,
12.2B shares, 14% realised growth): GOOGL's D moves from ~$101 (r 9%, full SBC) to ~$151; Claude's
clamp allows up to ~$227 and a ~$204 entry ceiling. At a ~$300 price that is still a ~30% fall, not
a normal dip — the calibration dry run (§17) prints the real numbers for GOOGL, META, BAC and MU
before v1 is frozen, and the operator decides then whether to loosen further.* `margin_of_safety = (fair_value − price) / fair_value`. The median needs no weights to tune and
one outlying method cannot move it far. Method B's "implied growth ≤ 0.7 × realised" is the same
fact as "price ≤ fair value B" seen from the other side, so it is **displayed** (it is the plainest
way to say "the price ran ahead of earnings") and is not a second gate. A terminal value above 75% of the DCF's enterprise
value, or a discount rate at or below the terminal growth rate, marks method B `unreliable` and drops
it (checks borrowed from Anthropic's `validate_dcf.py`).

**Sector rules** — each is `not_applicable` with a stated reason, never `FAIL`:
- Banks, insurers: FCF methods are N/A; use justified P/TBV = (ROTE − g) / (r − g) × tangible book
  per share; no Altman Z.
- REITs: N/A (FFO is not reliably tagged in XBRL).
- Pre-profit, biotech, negative-FCF names (RKLB, ASTS, NBIS): ineligible. The page shows only the
  reverse-DCF line ("the price implies 38%/yr for ten years").

### 6.6 Entry timing — strict for deep value, soft for growth **[Opus]**, revision 2
A hard Python gate on both lists (the operator kept it): a Claude READY whose timing fails is shown
and stored as WATCH.
- **Both lists:** not within 10 sessions before earnings. (Revision 3: there is no
  `options.earnings_clear`; the window is a new `value.yaml` key, and the earnings dates — which live
  in `news.db`'s `earnings_events` — are handed to `src/value/` as plain data by
  `scripts/run_value.py`, with yfinance's next-earnings date as the fallback. Missing date → `UNKNOWN`
  timing, never a pass.)
- **Deep value — strict.** Cheap *and* still making new lows is the classic trap. Price above its
  200-day SMA, **or** 6-month relative strength vs SPY not in the bottom 30%; and has stopped
  falling — a close above the 20-day SMA after the low.
- **Quality growth — soft.** Buying a dip in a long uptrend is normal for a grower, so it is refused
  only when the price is below its 200-day SMA **and** at a new 52-week low.

### 6.7 The verdict — Python's baseline, then Claude's call (revision 2)
Python always computes its own **baseline verdict** from §6.3–§6.6, per list:
- `NO` — a health gate failed, or fair value is missing.
- `WAIT` — healthy; the margin of safety is not there yet (price above
  `entry ceiling C = fair value × (1 − required margin of safety)`). The "good company, wrong price"
  list, and the natural home of the put idea (§9.1).
- `WATCH` — healthy and cheap enough; timing does not pass yet.
- `READY` — all pass.
- `UNKNOWN` — data quality (§6.3).

**The effective verdict** (what the strip shows and Stage 3 acts on):
- `NO` and `UNKNOWN` from Python are final. **Claude cannot lift a name over a health or data gate.**
- On every healthy name Claude has read (§8.3), **Claude's verdict replaces Python's**, with Claude's
  fair value (computed and clamped by Python, §8.2) replacing Python's in C, the margin of safety and
  the size tier.
- Python's timing gate still applies on top: a Claude READY with timing failing is WATCH.
- A healthy name Claude has not read yet (budget, §8.5), or whose Claude reply was malformed, keeps
  Python's baseline verdict, labelled "Python only".
- Both verdicts are stored on every ticker file and every shadow row, so the Python-only baseline is
  recorded beside Claude's on the same dates (§6.8, §12) — as the spreads book records its
  `baseline` beside Claude's pick.

Ranking inside a state is by Python's rank score (§6.8), then liquidity — so Claude decides *which
state* a name is in and Python orders the names within it. The strip shows READY, then WATCH, then
WAIT, per list. The required margin of safety is 25% (deep value) or 10% (quality growth) in a normal
market (§9.6 scales it with the regime) and applies to Claude's fair value as much as to Python's.

### 6.8 Shadow ledger and report
`data/value.db` table `value_shadow`: for every `READY` signal — Claude's effective READY and
Python's baseline READY as **two separate tracks**, so the report can say whether Claude's judgement
beat the rules — a hypothetical entry at the *next session's open*, the list, the fair value and
margin of safety at the time, the exit plan (§7) and the ruleset version; then each simulated exit
event, the exit date/price/reason, and returns at 21/63/126 sessions **and** at exit, each against
SPY. Control groups enter on the same dates: names that passed health but failed valuation, and
names that passed valuation but failed health.
`python -m scripts.value_report` prints the record with the numbers beside the benchmark.

READY signals from the **evidence universe** (§6.1) enter the shadow ledger too, tagged with their
universe, so the go-live count of §12 is not starved by a narrow list.

**The ranked record (revision 2026-10-28).** Threshold signals answer "do the entry rules work"; they
are too rare to answer "does the method pick better companies". So, at each month-end, every scored
name in the evidence universe gets a continuous **rank score** — the mean of a value percentile
(margin of safety, or normalised FCF yield where fair value is missing) and a quality percentile
(F-score, 5-year median ROIC, gross-margin stability; data-quality failures excluded; for the growth
list, realised growth joins the quality side). Recorded **per list** as hypothetical equal-weight
portfolios held to the next month-end: the **top tenth**, the **bottom tenth**, and the whole scored
universe, each against SPY. This is how the published systematic value work is tested (Gray &
Carlisle's QV ranks and holds the cheapest decile) and it yields ~50 names a month from day one. The
score's definition lives in `config/value.yaml` under the ruleset version. It never feeds a gate or a
size; it orders names within a verdict state (§6.7) and decides which healthy names Claude reads
first (§8.5).
The ruleset (`value_rules: vN` plus a hash of `config/value.yaml`'s rule keys) is frozen before
outcomes are looked at; a change is a version bump, at most quarterly.

### 6.9 The ticker file — every name analysed is kept (operator decision, 2026-10-28)
Nothing the scorecard computes is thrown away. Every name it ever scores — the nightly universe, and
any name looked up on Research, through `/scan NAME` or `/value NAME` — gets a **ticker file** in two
parts:

- **Part 1, the numbers** (deterministic, cheap, always present): the data-quality result, every
  quality gate with its actual value and threshold, each valuation method, fair value, margin of
  safety, timing state, verdict, and — for a held or shadow position — its exit plan and its
  re-evaluations (§7.1). Stored in `value.db` as a latest row per name **plus an append-only
  history**: a history row whenever the verdict, fair value, margin-of-safety band or any gate result
  changes, and one row per session for names in the ranked universe (the shadow ledger and the page's
  "what changed since last time" read the same history). Every row carries its **input fingerprint**:
  the latest accession used, the price date, the regime state, the ruleset version.
- **Part 2, Claude's analysis** (§8.3): on request for any name; automatic for names the system
  recommends or holds.

**Fresh on search.** Part 1 costs one companyfacts payload the research layer already caches, one
price series and some arithmetic, so a name is never shown stale when it could be recomputed:
- Opening a name compares the stored fingerprint with the current one (latest accession in
  `research.db`, latest price, regime, ruleset). Equal → the stored file is shown. Different, or no
  file → Part 1 is recomputed **during the request**, inside the Research page's existing
  materialisation budget (`research.tiers.materialization_budget_seconds`), with the page's existing
  PENDING-then-poll behaviour when EDGAR has to be fetched first. If the filings are already in
  `research.db`, the answer is arithmetic and arrives with the page.
- **Still one writer.** The computation is a pure function: `src/value/scorecard.py` takes financials,
  prices, regime and config and returns a `ValueScorecard`, with no I/O. The API may import that module
  and `src/value/schemas.py` (nothing else from `src.value`) to compute on the spot; it never writes
  `value.db`. It records a `value_snapshot` intent in `app_commands` **carrying the input fingerprint
  it used** (the accession, the price bar's date and close, the regime state, the ruleset version),
  and the value process persists the scorecard for exactly that input set — not for whatever the
  price has moved to since — so the page and the ledger agree. *(My call; a value-process RPC would
  add a second network surface for no gain.)*
- **Inputs are loaded by one neutral, read-only module** (revision 3): `src/common/value_inputs.py`
  reads `research.db` (`mode=ro`: financials via `select_periods`, daily bars) and the regime record
  through `src.storage.regime_state.load_regime_state`, and computes the technical inputs the scorecard
  needs (200/50/20-day SMA, ATR(14), relative strength, beta) with the deterministic
  `src/analytics/technicals.py`. It imports no enrichment and no `src.value`, so the API and the value
  process load identical inputs without the API importing more of `src.value` than the fence allows.
- **What stays fresh without being opened:** the ranked universe (nightly) and held and shadow names
  (nightly, plus the event checks of §7.1). A name looked up outside the universe is **followed** for
  `value.ticker_file.follow_days` (default 30) after its last view and refreshed nightly while
  followed; after that its file stays in the ledger, labelled with its age, and is recomputed the next
  time it is opened. Nothing is deleted.
- **Where the inputs come from.** Financials are read from `research.db` (`mode=ro`) through the pure
  `src.research.ingest.concepts.select_periods` (gaining `as_of`, §6.2) and `src.research.schemas` —
  the only `src.research` imports `src/value/` may make (§16). **The research worker owns every SEC
  fetch** (revision 3): companyfacts, the daily `submissions/CIK*.json` poll that yields new
  accessions and 8-K item tags (§7.1, §8.5), and the filing text that grounding (§8.2) and filing
  reads need — each a new job kind on the existing `IngestJobRow` queue, written to `research.db`. The
  value process only reads; it never opens an SEC client. Point-in-time `as_of` reads come from
  `CompanyFactsRawRow` (the raw payload keeps every filing of every value), since `FinancialRow` keeps
  only the latest; at S&P 500 scale that is ~500 raw payloads of a few MB each — accepted, and
  measured in the dry run (§17).
- Names the scorecard does not cover (ETFs, REITs, pre-profit) still get a file: verdict
  `not_applicable` with its reason, plus the reverse-DCF line where it applies.
- Part 1 holds Python's baseline verdict and is never altered by Part 2. The effective verdict combines
  the two by the rules of §6.7 and is stored alongside; the ranking reads Part 1 only.

## 7. The exit engine — "hold while it runs, sell when it turns"

Deterministic, evaluated once a day on closing prices, identical in the shadow ledger and (Stage 3)
the live book. The plan is written at entry and stored; it does not move except by these rules.

**Three exit policies, shadowed side by side (revision 2026-10-28).** Cheap stocks usually take
quarters to years to reach fair value, and the evidence on trailing stops is that they lower
volatility more often than they raise returns. Whether this engine helps or merely sells winners
early is an empirical question, and the shadow ledger can answer it for free. Every shadow entry is
carried under three policies at once:
- **`full`** — everything in this section, including §7.1's re-evaluations.
- **`value`** — sell half at fair value; sell the rest only on a thesis exit, a fair value re-marked
  below the price, or a catastrophe stop at −30% from average cost. No trailing stop, no RSI or SMA
  peak signal.
- **`hold12`** — hold 252 sessions, exiting earlier only on a thesis exit or the −30% catastrophe stop.

`value_report` prints the three side by side on the same entries (return, return vs SPY, max
drawdown, holding time, turnover). The live book (Stage 3) runs **`value`, pre-registered** (operator,
revision 2; revision 3 makes it pre-registered rather than picked from the record, since choosing the
best of three on the same short record is selection bias). `full` and `hold12` are diagnostics: they
exist in the ledger alone and can never send an order. Changing the live policy is a version bump with
a written reason. The bullets below define `full`; `value` and `hold12` use only the catastrophe stop,
the at-fair-value half-sale (`value` only), the thesis exits and §7.1.

**Which fair value an exit reads (revision 3).** The half-sale target uses the **effective** fair
value (§6.7). Every exit that **sends without a tap** — the stops, the deterministic thesis exits,
"fair value re-marked below the price" — reads **Python's** fair value only. If the effective (Claude)
fair value would have fired one of those exits while Python's does not, the result is a **sell
proposal that waits for the operator's tap**, never an automatic sale. So no Claude number can cause
an order to send on its own.

- **Initial stop** at average cost − 3 × ATR(14), but never wider than 15% below it. Close below it →
  sell. With tranches (§9.5) the average cost is recomputed after each add and the stop is
  recomputed from it, but a stop is **never lowered**.
- **Half-way arm.** Once the close is ≥ entry + 50% of the distance to fair value, the stop becomes
  a **trailing (Chandelier) stop**: highest close since entry − 3 × ATR(14), never below the
  breakeven. This is "let the run go, give back a little, sell on the turn".
- **At fair value.** First close ≥ fair value: propose selling **half** (the value gain is banked),
  and tighten the trailing stop on the rest to 2 × ATR(14). The remainder is the "ride the peak"
  part. Fair value is re-marked only when a new filing lands, up or down.
- **Peak/top signal.** While armed: a close below the 20-day SMA after having closed above fair
  value, or RSI(14) falling back through 70 after a close above 75, sells the remainder. (Either
  signal on its own; defaults, all in config.)
- **Thesis exits (deterministic, no AI).** F-score falls to ≤ 3, Altman distress, a going-concern
  flag in the filing, or fair value recomputed below the current price × 0.9 with the price under its
  50-day SMA → sell proposal.
- **Claude's exit (revision 2).** Claude's review of a held name returning BROKEN, or its verdict
  turning NO, raises a **sell proposal that always waits for the operator's tap** — unlike the
  deterministic stops and thesis exits above, it never sends on its own, whatever §14 question 4
  decides.
- **Review cards, not exits.** A Claude-chosen kill-trigger fires (§8.4); nine months with no
  progress; fair value falls but the price has not. These put a card on Telegram and the page; they
  never sell on their own.
- Earnings: holding through them is allowed (the 8% name cap bounds the gap); new entries are
  barred inside the 10-session window.
Risk-reducing exits (a stop, a thesis exit) follow the same convention as the wheel's closes: they
do not wait for the autonomy ladder once the book is live (§14, question 4).

### 7.1 Re-evaluating the plan when something moves the stock (operator decision, 2026-10-28)
The plan is set at entry, but the market does not wait for the next filing. **Python decides,
deterministically, when a held or shadow position's plan is re-evaluated, and what may change.**
Claude decides neither.

**Triggers** (defaults; every threshold in `config/value.yaml → reevaluation`, under the ruleset
version):

| # | Trigger | Rule | Severity |
|---|---|---|---|
| 1 | Abnormal move, one session | The day's return net of what **its sector ETF** explains (revision 3 — against SPY alone a −6% semis day fires every semiconductor at once; the sector→ETF map is config, SPY where none fits), beta over 250 sessions, divided by the standard deviation of that residual over the prior 60 sessions excluding the day itself: \|z\| ≥ 3. Backstop for short histories: a raw move ≥ 10%. Either direction. | Major |
| 2 | Abnormal drift | Five-session cumulative residual, same scaling: \|z\| ≥ 3 (the slow bleed or run no single day flags) | Minor |
| 3 | Earnings released | The `earnings_events` date passes — always, whatever the move | Minor (Major with #1) |
| 4 | Filing | A 10-Q/10-K (fair value re-mark, §7). An 8-K whose EDGAR item tags include 1.03 (bankruptcy), 3.01 (delisting notice) or 4.02 (prior statements no longer reliable) → Major; 1.01/2.01 (material deal), 2.05/2.06 (restructuring, impairment), 4.01 (auditor change), 5.02 (CEO/CFO departure) → Minor. Item tags come from the `submissions/CIK*.json` feed §8.5 already polls — no text reading. | as stated |
| 5 | News volume spike | The name's item count over 24 h ≥ 4× its 30-day daily median and ≥ 5 items, from the deterministic `news_items` columns only (the `sentiment.py` rule), handed in as plain data by `scripts/run_value.py` | Minor |
| 6 | Kill-trigger near | A Claude-chosen predicate (§8.4) within 10% of firing — Python evaluates it | Minor |
| 7 | Regime | The market regime steps to stressed or crisis: every held name | Minor |
| 8 | Quiet | 90 days with no re-evaluation (the thesis-tracker's quarterly floor) | Minor |

Checked on every close for every held and shadow position; #1 and #4 also hourly during RTH for held
names (delayed quotes from the existing bulk price provider — no IBKR line). An hourly hit only opens
the re-evaluation, pauses adds and raises the card; every level change waits for the close, because
"the shock session's low" does not exist until then (revision 3). Corporate actions
(splits, special dividends, spin-offs) are not triggers: levels are rebased mechanically and the
rebase is recorded. One re-evaluation is open per name at a time; a trigger within three sessions
joins it unless its severity is higher.

**What a re-evaluation does, in order**
1. **Pause adds.** No further tranche (§9.5) until it closes. Stops are never paused.
2. **Recompute Part 1** (§6.9) on current data. The plan may change only in these ways:
   - **Fair value moves only on filed data** — a new 10-Q/10-K, or grounded facts (§8.2).
     **Price and news alone never move fair value** (the operator's "a headline alone changes
     nothing"): a drop with the filings unchanged makes the name cheaper, not worse, and the card
     says so. Claude's fair value obeys the same rule (revision 2): between filings a Claude re-read
     may *lower* its drivers, never raise them; at a new 10-Q/10-K they may move either way, inside
     the clamp of §8.2. A Claude-lowered fair value can only ever produce a tap-to-sell proposal (§7).
   - **The stop tightens, never loosens.** A shock raises ATR; a stop recomputed from it that sits
     below the current stop is ignored.
   - The half-sell level follows a re-marked fair value — down freely, up only on a new filing.
   - A gate now failing flips the verdict to NO → the existing thesis exit (§7).
   - An 8-K 1.03, 3.01 or 4.02 is a thesis exit proposal on its own, under every policy.
   - **Shock stops apply under `full` only** (revision 3; `value`, the live policy, has no tight stop
     to move, and inventing one after a headline gap would contradict "a drop makes the name
     cheaper"):
     - *Down-shock (Major, downward):* the stop rises to at least the shock session's low − 0.5 ×
       ATR(14) measured before the shock.
     - *Up-shock (Major, upward):* the trailing stop arms at once (as if the half-way arm of §7 had
       fired), trailing from the shock session's low.
   - **Under `value` and `hold12`**, a shock pauses adds, raises the card and queues Claude's review;
     the only price exit remains the −30% catastrophe stop. The shadow ledger shows whether `full`'s
     shock stops would have saved money.
3. **Claude's review** (held positions only — shadow positions and the regime trigger #7 make no
   Claude call, revision 3): an automatic Part 2 run (§8.3) with the trigger in the prompt, writing
   INTACT / WEAKENED / BROKEN and, if it chooses, lower drivers. Shown beside the plan. BROKEN (or a
   verdict of NO) raises a sell proposal that waits for the operator's tap (§7). It never moves a
   stop and never sends an order itself.
4. **A card:** Major → a Telegram card in `TELEGRAM_THREAD_VALUE` the same day; Minor → the daily
   digest. One line each for what fired, the plan before, the plan now, and why — the diff of levels.
5. **Recorded** in `value_reevaluations`: trigger, severity, plan before and after, Claude's review
   state once it lands, ruleset version.

**Fence.** Triggers 1–4 and 6–8 are computed in `src/value/` from prices, EDGAR and the regime record.
Trigger 5 and Claude's review arrive through `scripts/run_value.py` as plain data. Trigger 5 may only
**open** a re-evaluation or a card. Claude's review may additionally lower fair value (through
bounded drivers, §8.2) and raise a tap-only sell proposal; neither can move a stop or send an order
(unit tests feed each alone and assert exactly that).

**Measured like everything else.** From the moment a trigger fires, the shadow ledger carries the
position twice — the re-evaluated plan and the original plan untouched — so the report can say whether
re-evaluation saved money or only churned. If it churns, the thresholds move by version bump, never
after one loss.

## 8. Stage 2 — Claude as the analyst (`src/value_ai/`)

The package imports nothing from `src.value`, the trading path, `src.notify`, `src.ledger` or
`src.storage`; it reaches Claude only through `src.claude.cli.build_cmd` (workdir outside the repo,
slim, per `CLAUDE.md`). It reads `data/news.db` (dossiers, clusters, earnings events) through
`src.news.store.readonly`, like `spreads_ai`. It receives the scorecard on the request and
**returns plain data** (a verdict, valuation drivers, prose, proposed facts, trigger picks).
`scripts/run_value.py` hands that to `src/value/`, which validates it, bounds and computes it, verifies
the facts (§8.2) and stores it: `src/value/` is the only writer of `value.db` and never imports
`src.claude`.

### 8.1 What Claude writes (all labelled as Claude's, everywhere it appears)
- **Verdict (revision 2):** READY / WATCH / WAIT / NO for each list the name is on, with one line why.
  It decides the effective verdict on healthy names (§6.7).
- **Valuation drivers (revision 2):** the assumptions behind Claude's fair value, chosen inside fixed
  bounds — Python does the arithmetic (§8.2).
- **Profile:** what the business is and what moves it (the existing dossier already has one; reuse).
- **Why it is cheap:** one paragraph, citing the scorecard's numbers and the news clusters it read.
- **Thesis:** what has to be true for the price to run to fair value, in plain words.
- **Bear case:** the strongest case against, in a short-seller's voice (the InvestSkill `bear-case`
  structure).
- **Kill-triggers:** picked from a fixed menu (§8.4).
- **Review state** after a filing/earnings: INTACT / WEAKENED / BROKEN with one line why.
Prompts are versioned, return strict JSON, and are validated name by name (the existing
`validated_items_call` pattern). A malformed or missing reply means "no notes", never a guess.

### 8.2 What Claude may supply as numbers — drivers Python computes, and grounded facts (revision 2)
*Supersedes the first draft's "extracted facts only, and only to lower". The operator chose to give
Claude the verdict and the fair value; this section is how that is done without letting a typo or a
hallucinated growth rate become a position.*

**Claude chooses assumptions; Python does every piece of arithmetic.** Claude never returns a fair
value as a number. It returns **drivers**, each inside a bound in `config/value.yaml →
claude_bounds`, and `src/value/claude_valuation.py` (deterministic) runs the DCF from them:

| Driver | Bound (default; tightened in revision 3) |
|---|---|
| FCF/share growth, years 1–5 | −10% to the lower of 30% and the realised 5-year CAGR **+ 5 points** |
| Growth, years 6–10 | fades linearly from the year-5 rate to the terminal rate |
| Terminal growth | 0% to **2.5%** |
| Discount rate | the list's Python rate to 12% — **≥ 9%** deep value, **≥ 8%** quality growth (never below the rate Python uses) |
| Normalised FCF margin | within ±5 points of the 5-year median, never above the 5-year best |
| Banks and insurers instead | sustainable ROTE within ±4 points of the 5-year median; same discount bounds |

*Why tightened (revision 3):* the review ran the DCFs. At the first draft's loosest bounds (30%
growth, r = 8%, terminal 3%) a grower is worth ~92× FCF against Python's ~25×, so the clamp, not
Claude's judgement, set the value for any name Claude liked — and the 75% terminal-value check never
fired inside those bounds. With these bounds a realistic upside is ~1.2–1.3× Python's, and the clamp
is a backstop.

A driver outside its bound is clamped to it and the clamp is recorded; a missing or malformed driver
set means no Claude fair value (Python's baseline stands). The Anthropic `validate_dcf.py` checks
apply: terminal value above 75% of enterprise value → Claude's fair value is marked `unreliable` and
not used.

**The clamp (operator decision: 1.5×) — one rule (revision 3).** `claude_fair_value` is capped at
**1.5 × Python's fair value** (§6.5), and the **capped value is the effective fair value**. The
uncapped number is stored and shown with a "clamped" label for the operator to read; nothing waits on
a review, and the gate has no separate "held" reject. Lowering is never capped. Where Python has no
fair value (a method absent), Claude's cannot be used either.

**The Claude breaker (revision 3, modelled on `claude_cut`'s breaker in
`src/engine/regime_limits.py`).** Claude's verdict stops applying — every name falls back to Python's
baseline until the operator resets it — when, over a rolling 20 sessions, either Claude's READY count
exceeds `value.claude.breaker.ready_multiple` (default 3) × the baseline's READY count, or the clamp
binds on more than `value.claude.breaker.clamp_rate` (default 25%) of Claude's fair values. The
report prints both rates every day. Size follows Claude's margin of safety as the operator decided
(§9.5); the breaker and the tighter bounds are what keep that from running away.

**Grounded facts.** A 10-K is still where an LLM earns its keep, so Claude may propose **facts**, each
with the accession number and a verbatim quote: one-off items to strip out or add back (asset sales,
tax benefits, restructuring and legal charges), segment revenue, guidance ranges, backlog, customer
concentration, covenant terms, share-class counts. `src/value/grounding.py` (deterministic) checks
every one:
- XBRL-tagged → the value must match companyfacts for that accession within 0.5%.
- Otherwise → the quoted span must appear verbatim in the fetched filing text and the number must be
  present in that quote (the `src/news/grounding.py::grounded` rule).
- Any failure drops the fact. A grounded fact may adjust normalised FCF **in either direction**
  (revision 2 — an add-back of a one-off cash charge was impossible before, and penalised exactly the
  setups deep value looks for), and the adjusted FCF feeds Claude's DCF only, never Python's baseline.

**Where Claude's fair value reaches (operator decision: all of it).** The effective verdict (§6.7), the
entry ceiling C and the margin of safety, the size tier (§9.5), the half-sale level and thesis exit
(§7), and the **wheel's put ceiling** (§9.1). That last is a change to the wheel: before revision 2 no
Claude number reached it. Its reach is bounded by construction — the ceiling only ever *restricts*
which strikes a value-suggested put may use; the wheel's own generator, delta, yield floors,
`premium_below_fair_value` and Rules Engine apply unchanged, so a higher Claude fair value can at most
relax a restriction the value layer itself added.

**What Claude still never does:** set a price or a limit, choose a strike, place, size directly, or
skip a gate; lift a name over a health or data gate; move a stop.

**Paper and live.** Applied in paper. In live, Claude's verdict and fair value apply only after the
go-live review of §12 has read the Claude-vs-baseline record (`value.claude.apply_live: false` until
then, and while false the live book uses Python's baseline verdict and fair value). This is a written
exception to the core invariant, recorded in root `CLAUDE.md` beside `claude_cut` (§18).

### 8.3 "What Claude knows" — Part 2 of the ticker file
Two halves, kept apart so the tier line holds: the deterministic half is Part 1 of the ticker file
(§6.9 — scorecard, fair value, gates, exit plan, verdict history, every change of state with its reason
and date); Claude's half (profile, thesis, bear case, chosen triggers, accepted extracted facts, review
state) sits in `value.db` tables labelled `source = claude`, read only by display code and Claude's
prompts. Revision 2 adds one table the gate does read: `value_claude_verdicts` — the validated
verdict, the clamped drivers and the Python-computed fair value, nothing else. `risk.py` reads that
table and never a prose or fact table (a fence test greps for it).

**When Part 2 runs** (operator decision 2026-10-28; the exact automatic set is my call):
- **Automatically**, within the budget of §8.5: the healthy names at the top of Python's rank score
  in the trading universe (top 15 per list), every **held** position on entry and on every
  re-evaluation (§7.1), and a WAIT name the strip offers a put on (§9.1). Shadow positions get no
  Claude call of their own (revision 3): the Claude track in the shadow ledger is made of the verdicts
  Claude wrote for trading-universe names, so its results never depend on queue order. Because Claude's verdict now
  decides entries, a healthy name Claude has not read keeps Python's baseline verdict, labelled
  "Python only" — Claude is never a dependency: a missing reply means the baseline, not a stall.
- **On request** for any name: a **Run Claude's analysis** button on the stock page, or
  `/value NAME analyse` in Telegram — each an intent drained by the value process, first in the queue
  (§8.5).
- **Two depths.** A *standard read* (Part 1, the dossier when one exists, the news clusters, the latest
  earnings release; ~3K tokens without the release, 10–20K with it — revision 3, so Python passes the
  release's financial tables as numbers and only the outlook section as text) writes the verdict, drivers, profile, why-cheap, thesis,
  bear case, triggers and review state. A *filing read* (§8.2) adds grounded extracted facts; Python
  slices the filing to the sections that matter first (§8.5), so it costs ~15–25K tokens rather than a
  whole 10-K's 30–80K. Automatic runs are standard reads, except held and READY names, which get a
  filing read on each new 10-K/10-Q. A request runs a standard read and offers the filing read.
- **Tied to the numbers it saw.** Part 2 stores the Part-1 fingerprint it was written against. When
  Part 1 changes materially (verdict, any gate, fair value by more than 5%), Part 2 is shown as
  "written against the scorecard of <date>" and, for a name in the automatic set, queued for a rerun.
- **One Claude section per page.** Once Stage 2 ships, Part 2 replaces the Research page's existing
  on-demand summary (`src/research/summary/`) for every name with a ticker file. *(My call: two AI
  write-ups of one company on one page will eventually contradict each other.)* A neutral renderer `src/common/value_text.py`
(imports only `src.common.schemas`) produces the compact `VALUE NOTE` block that the trade review,
roll review and `/scan NAME` prompts read for any name that has a verdict — so a CSP review on
GOOGL knows "value READY, fair value $X, ceiling $Y" without a second lookup. Same shape and same
rule as `dossier_text.py`.

### 8.4 Kill-triggers — a menu, not free text
Claude chooses up to five from a fixed vocabulary of predicates that Python can evaluate every run:
`revenue_yoy < x for n quarters`, `fcf_ttm < 0`, `net_debt_to_ebitda > y`, `diluted_shares_yoy > z`,
`gross_margin < m`, `insider_selling_cluster`, `guidance_cut`, `customer_loss` (the last three from
grounded facts). Python bounds each threshold, evaluates it on every refresh, and a firing trigger
raises a review card.

### 8.5 Freshness — when the file is rebuilt, and what it costs
- **Deterministic recompute (free, hourly/nightly):** a new 10-Q/10-K accession (poll the EDGAR
  `submissions/CIK*.json` feed daily), an earnings event, a ±15% move since the last snapshot, a
  split or corporate action, or a `/scan NAME` (the existing `dossier_touches` row; `approval_service`
  imports nothing from `src.value`, it only records the touch it already records).
- **Claude prose rebuild (budgeted):** on a filing, on earnings, on a news story about the name that
  the news process files in pile 1 or 2 of its three (`docs/superpowers/specs/2026-10-20-market-picture-design.md` §7),
  or when a kill-trigger is within 10% of firing. **Never on price alone.**
- **Budget (operator: "tight, but slightly looser", revision 2):** Claude reads only the top 15
  healthy names per list in the trading universe, held names, puts on offer, and your requests —
  never the 500-name evidence universe or a shadow position, which stay Python-only. A name is re-read only
  when its fingerprint or the triggers above change, so the steady state is a handful of reads a day.
  Caps: `value.standard_reads_per_day: 15` and `value.deep_reads_per_day: 3`, separate from the
  dossier's 4 calls × 6 names. Priority: your requests, then re-evaluations of held names (§7.1),
  then held names' filings, then the top-ranked unread names, then stale re-reads. In filing season the
  queue grows; prose carries its age and a stale label rather than silently ageing, and an unread name
  keeps Python's baseline verdict.
- **Spend tokens only on judgement (operator: "parse information correctly using the correct
  models").** Python does every piece of parsing that does not need judgement, before any model sees
  the name: XBRL figures from companyfacts, 8-K item tags from the submissions feed, earnings dates,
  price history, and **slicing a filing** to the sections a reader needs (Item 1 Business, 1A Risk
  Factors, 7 MD&A, the segment and debt notes) so no model pays to read boilerplate. Each call kind
  has its own model in `config/value.yaml → models` (the repo's per-call-kind pattern, through the slim
  `cli.build_cmd`):

  | Call kind | Default model | Why |
  |---|---|---|
  | `verdict` (standard read: verdict, drivers, thesis) | Sonnet | The judgement that reaches orders |
  | `filing` (grounded fact extraction from sliced sections) | Sonnet | Quote-exact extraction; every fact is re-checked by `grounding.py` anyway |
  | `review` (re-evaluation, INTACT/WEAKENED/BROKEN) | Sonnet | Can raise a sell proposal |
  | `prose` (profile/why-cheap refresh when only the news changed) | Sonnet, Haiku once it passes | Wording only; no verdict or driver |

  A cheaper model takes a call kind only after it passes the repo's blinded, claim-level audit on
  that kind (no hallucination, understatement or overstatement — the bar the news and scan prompts
  use), recorded in `STATUS.md`. Opus is not a default; the interactive skill (§8.6) uses whatever
  model the session runs. `python -m scripts.claude_usage` reports value spend per call kind.
- **Only Claude may decide.** A verdict or driver set produced by the local Ollama backend
  (`claude.backend: ollama`) is shown labelled and **never** becomes the effective verdict — the
  baseline stands, exactly as `claude_cut` treats an Ollama value.

### 8.6 The skill (`.claude/skills/value/`) — interactive only **[Opus]**
A headless `claude -p` cannot load a skill or run scripts (§4, fact 3), so the per-candidate verdict
is the versioned prompt + schema above. A skill is worth building for **you**, in Claude Code:
`/value NVDA` for a deep dive. `da-vinci` is the template: a `SKILL.md` router, `reference/`,
`scripts/`, and a durable file it reads instead of re-asking.
- Modes: `deep-dive` (read the 10-K, propose grounded facts), `bear`, `thesis` (pick triggers from the
  menu), `review` (INTACT/WEAKENED/BROKEN), `postmortem`, `explain` (a plain-English read of any
  scorecard).
- `reference/`: `sector-rules.md`, `reverse-dcf-reading.md`, `forensic-checklist.md`,
  `trigger-vocabulary.md`, and `output-schema.json` — **the same file** the headless prompt uses,
  generated from `src/value_ai/prompts/`, so the two can never disagree.
- `scripts/` only shells out to `python -m scripts.value_report SYMBOL --json`. It never
  re-implements a calculator; two valuations that disagree would be worse than none.
- Durable file: the operator's `config/value.yaml → policy` (pot, per-name cap, excluded sectors,
  tax residency), which the skill reads rather than asks. Anything it saves goes through an intent
  drained by a process; the skill never opens a database.

## 9. Stage 3 — money (paper only until §12 is met)

**Both acts switch on together** (operator, revision 2): puts and share-buying reach paper at the
same stage, each behind its own gate.

### 9.1 Act one: sell a put at or below the price worth paying
For a READY, WATCH or WAIT name — a wheel name or not — the strip offers "sell a put at or below
$C", where **C is the entry ceiling of §6.7** computed from the **effective** fair value (Claude's,
clamped, where Claude has read the name — revision 2, §8.2; Python's baseline otherwise, and always
Python's in live while `value.claude.apply_live` is false). The offer appears only when a strike at
or below C actually passes the wheel's own delta and yield rules. For a WAIT name the price is above C, so the ceiling is a real constraint: "get paid while
the price comes down to a price you would be happy to own it at". For READY/WATCH the price is
already under C and the ceiling is satisfied by any out-of-the-money strike. It is a **strike
ceiling, not a target strike** **[Opus]**: a put struck 25–30% below the price on a quality name
pays almost nothing and fails the wheel's own yield floors and `premium_below_fair_value`. The
wheel's existing generator, delta and yield rules pick the strike under C or decline. (An
assignment from such a put is wheel stock — §9.2 — and is managed by the wheel's covered-call
logic, not the value book's exit engine.) Where the name is outside the wheel, "add to would_own" is one tap through the
existing universe-override intent; the wheel's gate is unchanged. A `value_view` read-only module
(`src/common/value_view.py`, SQLite `mode=ro`, imports no enrichment) is the only way the wheel
reads a ceiling; **no engine, strategy or execution module imports `src.value`**.

**The flow, end to end (revision 3; no new command kind).** The wheel's scans already assess every
CSP contract on its names and keep the assessments the existing `promote` command acts on. The strip
reads, through the API, the best assessed CSP for the name with strike ≤ C that passed the wheel's
generator. A tap sends the **existing `promote` intent** for that contract, which runs the Rules
Engine re-gate exactly as today. If no assessed contract ≤ C exists, the card offers the existing
`/scan NAME` instead. The ceiling is re-checked when the intent is drained: `promote` reads C through
`value_view` and refuses `above_value_ceiling` if the strike is now above it. That refusal can only
narrow, never widen, what the wheel would send. Assigned shares are wheel stock (operator, revision
3).

### 9.2 Act two: buy shares — one ticker, two books, every share attributed (revision 2)
*Supersedes the first draft's "disjoint underlyings". The operator chose to let the value book hold a
wheel name (GOOGL, META, BAC…) while the wheel trades it. IBKR nets same-ticker shares across
clientIds into one position, so the system has to know whose shares are whose — this is where a
covered call written against the wrong shares would come from, so the rules are strict.*
*Revision 3 redesigns the mechanics after the review found the revision-2 version unbuildable. The
first-draft rule tagged books by clientId, but `ParsedExecution` (`src/common/schemas.py`) has no
clientId and Flex/CSV rows carry none; ledger ingest matches books by `ib_order_id`
(`src/ledger/ingest.py::_tag_books`), which collides across clientIds; and "wheel = broker − value"
made the reconcile circular. Sharing is on from the first share purchase (operator, revision 3), so
these rules ship with Stage 3 and are proven by the fault drills below.*
- **Every value order carries `orderRef = "value:<lot_id>"`.** IBKR keeps `orderRef` on the order,
  on every execution and in Flex statements (`orderReference`), so ownership survives restarts and
  reaches the broker-truth ledger. The value service writes a **pending-lot row before `placeOrder`**,
  so a fill can never arrive for a lot `value.db` does not know. `ParsedExecution` gains an `order_ref`
  field (filled from `Execution.orderRef` in `src/ledger/live.py`, from `orderReference` in Flex/CSV),
  and ledger ingest tags `book="value"` from it. Order ids are never used to tell books apart.
- **Two independent counts, so the reconcile can catch something.**
  - **V** comes from `value.db`: filled value lots plus the open quantity of pending value orders,
    rebuilt after a restart from the ledger's `value:` rows.
  - **W** is the wheel's own count from the trading database and the ledger: wheel fills plus
    assignments and exercises, never "broker minus V".
  - Before every order on a shared ticker and once a session: **broker quantity = W + V_filled**.
  - A value fill missing its tag is counted twice (once in W from the ledger, once in V from the
    lot) and so shows up as a mismatch.
- **The wheel sees only its own shares, and errs short.** `src/common/books.py` gains
  `value_shares(symbol)` (read-only from `value.db`, including pending value buys). `get_positions()`
  gives the wheel `min(W, broker − V)`, never below zero. The covered-call screen (`scan_pipeline.py:273`,
  fact 1) therefore writes only against wheel lots of 100. A race in which a value fill lands first
  makes the wheel see *fewer* shares, never more.
- **Fail closed.** If `value.db` cannot be read, the wheel uses W alone and writes no covered call on
  any ticker where broker ≠ W (unexplained shares).
- **The wheel's cost basis is the wheel's.** IBKR's `avgCost` blends both books. On a shared ticker,
  the covered-call strike floor (`src/strategies/covered_call.py`) and `adjusted_cost_basis_for`
  (`src/storage/campaigns.py`) are computed from W's own lots, so a value purchase never moves the
  wheel's strike floor.
- **Exposure is counted once, across both books.** The wheel's name and sector concentration limits
  add `books.value_exposure(symbol)` back in, and the value gate counts the wheel's shares and CSP
  collateral on the ticker. A combined cap (`portfolio.max_combined_name_pct`) stops GOOGL becoming a
  third of the account through two books at once.
- **Sells never cross books.** A value sell is capped at
  `min(value lots, broker quantity − 100 × open wheel short calls)`, so it can never leave a covered
  call uncovered, even when attribution is in doubt.
- **Mismatch is `book_attribution_mismatch`.**
  - Both books freeze on that ticker: no opens, no new calls.
  - A Telegram alert goes out.
  - Only a value-book stop or thesis sale, under the cap above, may still send.
  - A human clears it.
- **Fault drills before the first paper share purchase** (operator chose sharing from day one, so
  these are build acceptance, not a later switch): assignment on a shared ticker, a partial value
  fill, a restart mid-order, a split, a manual TWS trade, Flex-only arrival of a fill, and `value.db`
  unreadable. Each is a unit test plus one scripted paper drill. All must pass before the first buy.
- **Tax:** the operator is not a US taxpayer, so wash-sale rules do not apply and no wash-sale reject is
  built (§14).

### 9.3 The pot — "dedicated" has to mean something
**Size (operator, 2026-10-29): 70% wheel, 30% value.** `config/value.yaml → sleeve.pct_of_net_liq:
30` — the pot's capital at cost (unspent cash + cost of open value lots) is capped at 30% of net
liquidation. My calls, to make 30% cheap to carry:
- **Reserve what the book can use soon, not the whole 30% at once.** Reserving 30% of idle cash on
  the first night would cut the wheel's income by about 30% while the value book holds nothing.
  The reserved amount is `spent + ready_buffer`, where `ready_buffer = sleeve.ready_buffer_positions`
  (default 3) × the name cap, never above the 30% ceiling. The rest of the 30% stays usable by the
  wheel until the value book grows into it. Value entries are tranched and not urgent, so waiting
  for wheel collateral to free up costs little.
- **The two lists share one pot,** each capped at `sleeve.max_list_share_pct` (default 70%) of it,
  so neither list can crowd the other out.
- **Per name:** 8% of the pot, which is 2.4% of the account at a full pot. `max_positions` defaults
  to 20.

`config/value.yaml → sleeve`. Two changes outside `src/value/`, both Rules-Engine edits
the operator must approve:
The arithmetic is set here, because it is the guard for failure mode 1 (revision 3):
1. **`resolve_caps` subtracts the value book's whole contribution to excess liquidity**, not only its
   unspent cash. `resolve_caps` hands the wheel `excess_liquidity − reserve`. On a margin account,
   buying $X of stock with cash lowers excess liquidity by only the maintenance requirement (~25% of
   $X), so subtracting only unspent cash would hand the wheel ~75% of every dollar the value book has
   spent.
   - **The fix:** `books.value_liquidity_claim() = reserved pot cash (the ready buffer above) + Σ value market value × (1 − m)`,
     where m is the maintenance rate.
   - **The rate m:** IBKR's per-position requirement where available, else 25%. The lower rate
     subtracts more, so it errs safe.
   - This is subtracted from `excess_liquidity` before the reserve is taken.
2. **The value book is cash-only:** a buy's cost must fit in the unspent pot (`sleeve_exhausted`), so
   it never borrows (the "no leverage" non-goal).
3. **A gross cap across both books:** stock market value (wheel and value) + CSP collateral ≤
   `portfolio.max_gross_notional_pct` (default 100%) of net liquidation. The Rules Engine checks it
   for every CSP; the value gate checks it for every buy.
Uninvested sleeve cash stays cash.

### 9.4 The gate — `src/value/risk.py::validate`
Deterministic code, run at decision time and again at send time on a fresh quote
(`req_fresh_mkt_data`, `LimitOrder` only). Reject reasons: `sleeve_exhausted`, `name_cap` (≤ 8% of
the pot, so a −30% gap costs ≤ 2.4% of it), `combined_name_cap` (§9.2), `book_attribution_mismatch`,
`max_positions`, `verdict_not_ready`, `mos_below_required`, `health_gate_failed` (re-checked here,
whatever the verdict says), `data_unreliable` (EDGAR vs yfinance disagree, or an MoS above 60% — that
goes to review, never straight through), `gross_notional_cap` (§9.3), `timing_not_ready`,
`earnings_within_window`, `trend_brake`, `sleeve_breaker`, `illiquid`
(position above 1% of average daily dollar volume), `price_stale_at_send`. What an LLM produced reaches
it only as the validated row of `value_claude_verdicts` — a verdict from a fixed set and a fair value
Python computed from bounded drivers and clamped (§8.2) — and in live only once
`value.claude.apply_live` is true. The gate itself makes no model call.

### 9.5 Sizing and entry
Position size = pot × conviction tier, capped at the name cap and the combined cap (§9.2). Python
computes the size; the margin of safety it reads is the **effective** one (Claude's clamped fair value
where present — operator decision, revision 2). Default tiers per list (config; §6.0): deep value
25–35% → 3% of the pot, 35–45% → 5%, above 45% → 8%; quality growth 10–20% → 3%, 20–30% → 5%, above
30% → 8%. A margin above 60% goes to review (§9.4). Entry in up to three tranches (default: ⅓ at READY,
⅓ on the next higher low or support-zone fill with the gates still passing, ⅓ on a close above the
50-day SMA) using the existing `scale_in` machinery.

### 9.6 The cycle — what "protect the downside" means mechanically **[Opus]**
A fast VIX regime is a poor clock for a hold of months. So:
- **The regime sets how demanding the entry is, not whether you are forced out.** Required margin of
  safety by regime: deep value normal 25%, cautious 30%, stressed 35%, crisis 40%; quality growth
  10%, 15%, 20%, 25%. It applies to Claude's fair value as much as Python's. A value book buys *more
  carefully* in a bear market, not never. (Regime read via the deterministic
  `src.storage.regime_state` path; value sits in the same tier as `src/regime/`.)
- **A slow trend brake:** SPY's month-end close below its 10-month SMA stops new entries and lowers
  the pot's exposure cap from 100% to 50%. No selling by regime alone.
- **Sleeve drawdown breaker:** −15% from the pot's high stops new entries; −25% proposes trimming to
  half. A human resets it.
- The biggest downside lever is account-level (§9.3): the pot lowers the wheel's leverage.

### 9.7 Execution, process, surfaces
- **The stock-order path is `src/value/executor.py`**, as `src/spreads/executor.py` is for spreads
  (revision 3). It is not in `src/execution/`: importing `src.execution` loads `src.claude.memory`,
  which would break the value process's `sys.modules` fence. It uses `LimitOrder`,
  `qualifyContracts`, the send-time re-gate and the `orderRef` tag (§9.2). Paper only; `run()` idles
  when `LIVE_TRADING=true`, as spreads does, until a separate live plan exists.
- **Value approvals live in `value.db`, and only clientId 31 sends** (revision 3). The wheel's
  `_process_button` path sends from the exec clientId (14), which would make the shares wheel stock.
  So a value proposal is a `value.db` row. Its Telegram and web Approve/Reject taps are `app_commands`
  intents (new kinds `value_approve` / `value_reject`) drained by the value service, which re-gates
  and sends. `approval_service` imports nothing from `src.value`; it only forwards the tap as an
  intent, as the web does.
- `scripts/run_value.py`: its own process, **no IBKR connection in Stages 1–2**; clientId 31 in Stage 3
  (`ibkr.client_ids.value`, in `config/settings.yaml` and its example); registered in `./ibkr`.
- Own config `config/value.yaml` (private) and `config/examples/value.yaml` (committed); own database
  `data/value.db` with its own `ValueBase`, one writer package (`src/value/`); own Telegram thread
  `TELEGRAM_THREAD_VALUE`; proposals follow the approval and autonomy ladder's rules, applied by the
  value service from `value.db` (above).
- API: `src/api/value_db.py` reads `value.db` SQLite `mode=ro`; no write routes. Web writes are
  intents (`app_commands`) drained by the value service, like every other web action.

## 10. What it looks like

**Research page.** A **Top opportunities** strip above the watchlist with two tabs, **Deep value** and
**Quality growth**: up to ten cards each, READY first. Each card: company, list and verdict (READY,
WATCH, WAIT) with who decided it ("Claude" or "Python only"); a single bar with the price, fair value,
the entry ceiling, the stop and the half-sell price marked; margin of safety; three plain-English
reasons; "Buy shares" (READY) and "Sell a put ≤ $C" (the best existing CSP candidate under the
ceiling, when one passes the wheel's rules); how fresh the file is. Claude's one-line note appears
only when present, labelled "Claude".

**Stock page.** Verdict first: state, fair value vs price, margin of safety, the exit plan in one
sentence ("stop $X · sell half at $Y · then trail"). Then your three questions as three blocks —
*Is the business still doing its job?* (quality gates, what changed since last time, kill-triggers
and their distance to firing), *What is it worth?* (Python's methods side by side with the median
marked, then Claude's fair value with the drivers it chose, any clamp applied and the 1.5× cap drawn,
the reverse-DCF line, each number with its filing and date; Python's and Claude's verdicts side by side
when they differ), *How much, and when?* (timing state,
tranche plan, what the regime asks of the margin of safety). For a held name, the plan's
re-evaluations (§7.1) as a short dated list — what fired, levels before and after. Each part of the
ticker file shows its age (§6.9); Part 1 is recomputed on open when its inputs moved. Then the chart
with fair value and stops drawn on it, **What Claude knows** (thesis, bear case, review state, labelled
as Claude's, with the scorecard date it was written against and a **Run Claude's analysis** button), and
below all that the existing checks, statements, technicals, sentiment and news as detail. Unknown is
`n/a`, never zero (`web/DESIGN.md`). **UI work is built with the `da-vinci` skill**, subagents told
to use it, with its critique/audit finish.

**Home.** A **Value** book card beside CSPs, CCs and Credit Spreads: pot used, open positions with
their next exit level, today's proposals. Wherever Home distinguishes kinds today (positions filter,
pay stub, today's trades, realised calendar) a `value` kind joins, read through `value_db.py` the
way spreads is.

**Telegram.** `/value` (the top list), `/value NVDA` (one-name card, built fresh per §6.9),
`/value NVDA analyse` (queue Claude's analysis, §8.3), proposal cards with Approve/Reject for buys and
sells, re-evaluation cards (§7.1), reviews and breaker notices in `TELEGRAM_THREAD_VALUE`.

## 11. Trades, orders and the ledger (Stage 3 plumbing)
Value orders and fills land in `value.db` (`value_positions`, `value_orders`, plus the tranche plan
and exit plan per position) and reach the broker-truth ledger the way every fill does (live feed, Flex, CSV, through the one
writer `src/ledger/ingest.py`), tagged `book="value"` by `src/common/books.py`. The pay stub and realised P&L gain a
`ValuePayInput` (plain values read by the API; `src/reporting/` never imports `src.value`). A
postmortem per closed position (entry, fair value then and now, each exit event, return vs SPY,
which gate was closest to wrong) is written by `scripts/value_report.py` and read by a human.

## 12. Validation — what must be true before any real order

No edge is assumed. The weeks-to-months value signal is weak on its own; the combinations with
support are value + profitability + trend, and the one short-horizon edge — momentum — is exactly
what "buy near the 52-week low" fights **[Opus]**. Hence §6.6 and §7.
- **What this bar can and cannot show (revision 3).** The shadow ledger runs from the first night
  with the ruleset frozen (§6.8). Its forward record catches plumbing faults, gate errors and
  disasters. It **cannot prove an edge** in the time available:
  - Six to nine monthly decile spreads, with a typical spread volatility of ~3.5% a month, would need
    on the order of 200 months to show 0.5%/month at t = 2.
  - Closed trades inside three to six months under `value` are mostly stop-outs, thesis exits and
    quick runs, so that sample is biased.
  Therefore:
  - **Returns are measured at fixed horizons on every entry, marked to market** (21/63/126 sessions),
    not on closed trades alone, with errors clustered by entry date.
  - **Stage 1b — a point-in-time backtest of Python's rules — is mandatory, not optional.** It uses
    EDGAR with `as_of`, prices with the survivorship caveat printed, and the same frozen ruleset. It is
    the only way to learn about the rules quickly.
  - **Claude cannot be backtested**: its training data already contains the outcomes. Its only
    evidence is the forward Claude-vs-baseline record.
  - The 30-entry count below counts entries of the **track that will run live** (Claude's effective
    verdicts if `apply_live` will be on, else the baseline). Evidence-universe entries count only
    toward the baseline track.
- **Do not go live if any holds:** mean 63-session excess return over SPY ≤ 0 across ≥ 30 entries of
  the live track (above), under the `value` policy; Stage 1b shows the rules losing to SPY; the ranked
  record's top tenth has not beaten both SPY and the bottom tenth over the window; any order passed a
  gate that should have failed; any PASS rested on a stale or
  cross-source-inconsistent number; the paper sleeve's drawdown exceeded 1.5× SPY's over the same
  window; or the pot cannot be funded without lowering the wheel's reserve. A paper sleeve of at
  least three months, then a human reads the report — the same cutover discipline as the other books.
  (Operator confirmed this bar as written, revision 2.)
- **Claude vs the baseline.** The report shows Claude's effective-verdict track beside Python's
  baseline track on the same dates, per list, plus how often the 1.5× clamp bit. It is not a separate
  pass/fail line; it is what the operator reads before turning `value.claude.apply_live` on (§8.2). If
  Claude's track trails the baseline, live runs on the baseline.
- Rule changes: quarterly, by version bump, never after seeing a single loss.

## 13. Failure modes, worst first, and the cheapest guard

1. **Stacked beta.** Shares on top of a 100%-deployed put book on correlated tech, shared cash, a
   crash. *Guard:* the pot's reservation and the gross notional cap (§9.3).
2. **A wrong number becomes a 50% margin of safety.** XBRL concept or unit errors, GOOG/GOOGL, a
   stale yfinance field. *Guard:* data-quality gate (§6.3); MoS above 60% goes to review only.
3. **Value traps and falling knives bought at full size** — peak-earnings cyclicals, banks before a
   credit turn. *Guard:* timing gate, normalised earnings, F-score floor, thirds, the 8% cap.
4. **Book interference** — now that tickers are shared (revision 2): a covered call written against
   value shares, a value sale eating wheel shares, a blended cost basis, two books stacking one name.
   *Guard (revision 3):* `orderRef` attribution, two independent counts, the wheel's view erring short
   and failing closed, wheel-only cost basis, the sell cap, the combined name cap, freeze on mismatch,
   and the fault drills before the first buy (§9.2); the wash-sale question is §14.
5. **A confident story overpays** (revision 2). Claude's verdict now decides entries, and a persuasive
   growth case is exactly how a good company gets bought at a bad price. *Guard:* health gates Claude
   cannot lift (§6.4); drivers bounded by the company's own history and Python doing the arithmetic;
   the 1.5× clamp; the required margin of safety applied to Claude's number; the Python baseline
   recorded beside it; record-only in live until the operator has read that comparison.
6. **Persuasive prose plus threshold-tweaking after a loss** turns a no-edge system into a
   confident one. *Guard:* frozen versioned ruleset, benchmark-relative postmortems, a small pot,
   Claude's text always labelled.

## 14. Open decisions — the operator's

1. ~~The pot?~~ **Answered (2026-10-29): 70% wheel / 30% value**, with a ready-buffer reservation, one
   pot shared by both lists and each list capped at 70% of it (§9.3).
2. ~~May a wheel name be held as shares by the value book?~~ **Answered (revision 2): yes, shared**
   (§9.2).
3. ~~Claude's adjustments in live?~~ **Answered (revision 2):** Claude decides on healthy names; in live
   only after the go-live review has read the Claude-vs-baseline record (`value.claude.apply_live`).
4. ~~Stop and thesis exits without a tap?~~ **Answered (2026-10-29): yes in auto mode, as with the
   rest of the system.** The value book follows the existing autonomy ladder: in auto mode the
   deterministic stops and thesis exits send without a tap. Buys follow the same ladder as the wheel's
   opens. Claude-originated sells still always wait for a tap (§7) — no Claude number sends an order
   on its own.
5. ~~Breadth?~~ **Answered by the review fix:** trade the S&P 100 + your lists; score the S&P 500 for
   evidence (§6.1).
6. ~~Tax residency?~~ **Answered (2026-10-29): not a US taxpayer.** No wash-sale rule is built; the
   value gate has no `wash_sale_window` reject.

No open decisions remain.

## 15. What we borrowed, and what we did not

| Source | Taken | Left |
|---|---|---|
| `tradermonty/claude-trading-skills` | `trader-memory-core`'s forward-only thesis lifecycle (IDEA → ENTRY_READY → ACTIVE → CLOSED/INVALIDATED), kill criteria, review-due dates, time stop; the screener's "scripted funnel, the model may explain but not override"; the drawdown breaker | The data layer (needs FMP); outcome scoring by raw return sign |
| `yennanliu/InvestSkill` | thesis INTACT/WEAKENED/BROKEN, `bear-case`, SBC-adjusted FCF, margin-of-safety bands by style, a dated sources-and-confidence block, the "thesis-break gate" idea | Prompt-only structure: the model fills every number and the method weights |
| Anthropic financial-services `dcf-model` / comps | The validator checks (g < WACC, terminal value share, centre cell = base); since revision 2, LLM-chosen drivers — but bounded by the company's own history, with Python doing the arithmetic and clamping the result | Unbounded LLM-chosen drivers |
| Anthropic financial-services `thesis-tracker` | Falsifiable thesis, the quarterly review floor (§7.1 trigger 8) | Prompt-only storage |
| `thetagang` (IBKR, deterministic) | Capital-base views, the slow absolute-trend deadband, a bounded external-provider schema | — |
| `virattt/ai-hedge-fund` | Horizon-stamped scoring, hash-chained ledger idea | LLM-emitted signals |
| `JerBouma/FinanceToolkit`, `edgartools` | Pure Piotroski/Altman/Beneish formulas; EDGAR standardisation maps | — |
| Damodaran data library | Industry margins and an equity risk premium instead of model-chosen inputs | — |
| `swing-finder.org` | Exit-rule conventions; the idea of ranking by distance to support | Its track record is back-filled across four model generations in six weeks and unbenchmarked: not evidence |
| `openclaw-stock-analyzer` | Nothing (LLM-scored moat, "<30% of the 52-week range = heavy buy" is the falling-knife rule) | All of it |
| `claudecowork.im` equity analyst | — | An LLM issuing Buy/Hold/Sell and a position size breaks the core invariant |
| `smartxterminal.com` | The operator's three-part checklist, taken from the operator directly | The site itself could not be read (bot check) |
| Gray & Carlisle, *Quantitative Value* | Testing by ranked deciles held equal-weight, not by threshold hits (§6.8) | — |
Full catalogue (~50 systems, with how each was judged): the Sonnet sweep's `value-landscape.md`.

## 16. Fences and tests (to add with the code)
- `tests/test_value_fence.py`: `src/value/` imports nothing from `src.claude`, `src.news`,
  `src.value_ai`, `src.spreads*`, `src.notify`, `src.api`, and from `src.research` only
  `src.research.ingest.concepts` and `src.research.schemas` (§6.9); `src/api/` imports from `src.value`
  only `src.value.scorecard` and `src.value.schemas`, and `scorecard.py` performs no I/O; `src/value_ai/` imports
  nothing from `src.value`, the trading path, `src.storage`, `src.ledger`; only `scripts/run_value.py`
  imports `src.value_ai`; `engine/`, `execution/`, `strategies/` import only `src.common.value_view`
  and `src.common.books`; `risk.py` reads no `source = claude` table except `value_claude_verdicts`
  (revision 2) and makes no model call; a `sys.modules` check that the value process loads no wheel
  layer. Imports parsed with `ast`, as in `test_spreads_fence.py`.
- `tests/test_web_fence.py` additions: only `src/api/value_db.py` opens `value.db`; the API still
  writes exactly one table; only `src/value/` constructs `value.db` rows.
- Unit tests: `select_periods(as_of=…)` returns first-filed values; each quality gate and valuation
  method on fixtures including a restatement, a share-class case, a bank and a cyclical; the exit
  engine as a state machine (stop, arm, half-sell at fair value, trail, peak signal, thesis exit);
  the ticker file (fingerprint equal → stored file, changed → recompute; the API path and the value
  process produce identical scorecards; history rows only on change; follow-window expiry); every
  re-evaluation trigger on fixtures, debounce, "fair value never moves on price or news alone", "the
  stop never loosens", down- and up-shock rules, and trigger 5 / Claude's review alone leaving the plan
  unchanged; the month-end ranked portfolios (deciles, ties, excluded names); the three exit policies
  on one fixture entry, and that only the live-chosen policy can reach an order;
  grounding (accepts matching, drops mismatched); every gate reject reason; the
  `resolve_caps` reservation; the pre-registered ruleset hash.
- Revision 2 unit tests: a Claude READY cannot lift a health-gate or data-gate failure; every driver
  out of bounds is clamped and recorded; a fair value above 1.5× Python's is held and the cap used; a
  malformed, missing or Ollama-produced reply leaves Python's baseline as the effective verdict;
  between filings Claude's drivers can only lower fair value; `apply_live: false` makes the live book
  use the baseline; both shadow tracks are written; the two lists' entry rules, required margins and
  size tiers; timing strict vs soft; share attribution (clientId → book, assignments and manual trades →
  wheel, the wheel's view excludes value shares, a value sell capped at value lots, the combined cap,
  freeze on mismatch); a Claude sell proposal never sends without a tap.
- Revision 3 tests:
  - **Exits:** no automatic exit reads Claude's fair value, and a Claude-only exit is always a tap
    proposal; shock stops fire under `full` only; level changes wait for the close.
  - **Claude:** the bank and cyclical health sets; the tightened driver bounds and the single clamp
    rule; the breaker trips on the READY multiple and on the clamp rate, then falls back to the
    baseline.
  - **Share attribution:** the `orderRef` round-trip through live, Flex and CSV ingest; the pending
    lot is written before `placeOrder`; the reconcile detects an untagged value fill; the wheel's
    view errs short, and an unreadable `value.db` freezes calls on unexplained shares; the wheel's
    cost basis comes from W; a value sell is capped at broker − 100 × open calls; the seven fault
    drills (§9.2).
  - **Pot and puts:** `value_liquidity_claim` and the gross cap; `promote` refuses
    `above_value_ceiling`.
  - **Fences and inputs:** `src/common/value_inputs.py` imports no enrichment and no `src.value`;
    `src/value/` opens no SEC client; `src/value/executor.py` never imports `src.execution`.
- The three existing quality gates (`pytest`, `ruff`, `mypy src`) stay green.

## 17. Left to the builder
**The first build step is a calibration dry run (revision 3, days).** Build Stage 1's scorecard, run
it once over the S&P 500 and the operator's lists, and print a **pass funnel**: how many names fail
each health gate, each list's entry rule, the margin of safety and timing, per list. List GOOGL,
META, BAC and MU by name with every number. Also print raw-payload storage and run time. The
operator reads it, settles the growth valuation (§6.5) and any threshold that refuses everything or
nothing, and only then is `value_rules: v1` frozen and the shadow ledger started. Rules changed after
the dry run are not "tweaking after a loss"; there is no loss yet.

Table and column design for `value.db`; the exact margin arithmetic for the gross cap against the
paper account; the S&P 100 snapshot's source and refresh; how the value process learns of a `/scan`
touch without `approval_service` importing `src.value`; widening the universe; whether Stage 1b
(a point-in-time backtest) is worth its data cost; exact thresholds' final defaults (every one
lives in `config/value.yaml` and is frozen under a ruleset version); the order of web work. For the
ticker file and re-evaluation: the `value.db` history schema; how the API tells the research worker to
fetch a missing name's filings (the existing `IngestJobRow` queue is the obvious path); the residual
model's exact estimation window and its handling of the shock day itself (exclude it from its own
estimation window); parsing 8-K item tags from the submissions feed; whether the hourly RTH check is
worth its provider calls once the held count is known. For revision 2: final driver bounds; the
filing-slicing rules per form type; how `value_lots` is rebuilt from the broker-truth ledger after a
restart; the exact value of `portfolio.max_combined_name_pct`; the prompt and schema for the verdict
call, validated by the existing `validated_items_call` pattern.

## 18. Docs to update when it is built (`CLAUDE.md` trigger table)
`ARCHITECTURE.md` (folder guide for `src/value/`, `src/value_ai/`, the `value.db` data flow, the
stock page and Research strip); a **value fence** section in root `CLAUDE.md`, and a second written
exception under the Core invariant beside `claude_cut` (revision 2, §8.2): Claude's validated verdict
decides value-book entries on healthy names, and its bounded, Python-computed, clamped fair value sets
the size tier and the wheel's value-suggested put ceiling — applied in paper, record-only in live until
reviewed, never an Ollama value, never past a health gate or the Rules Engine; `config/examples/value.yaml` and the `ibkr.client_ids.value`
key; `SETUP.md` (scripts table, Telegram commands, a "Value book" section); `README.md` Telegram
commands table; `STATUS.md` (built / deferred / limits); `docs/web/commands.md` for any new
command kind; `docs/web/api.md` for the new routes.

## 19. Revision 2 — the operator's answers (2026-10-28)
After the review (for and against), the operator said: "I am okay with lowering the filter guard and
letting Claude have more say and leeway. As long as the stocks that are proposed are healthy, strong
companies with high potential for growth and survivability, that's a go." Then, question by question:

| Question | Answer | Where it lands |
|---|---|---|
| How far should Claude's say go? | Everything: ranks, upside to fair value, and the verdict on healthy names | §6.7, §8.1, §8.2 |
| Deep value, quality growth, or both? | Both, as two lists ("GOOGL, META etc" vs "MU, BLOOM, BAC") | §6.0 |
| Which guards stay strict? | Financial health; earnings quality and dilution; "don't buy while still falling" (unsure it fits). Not kept: lowest-of-methods | §6.4, §6.5, §6.6 |
| Exit style before the record picks one | Value-style | §7 |
| Wheel names in the value book? | Share a name: both books may hold the same ticker | §9.2 |
| How far does Claude's verdict reach? | All of it: decides yes/no, sets the size tier, and reaches the wheel's put ceiling | §8.2, §9.1, §9.5 |
| Timing check | Strict for deep value, soft for growth | §6.6 |
| High-flyers on the growth list? | Yes, if healthy and fairly priced | §6.0 |
| Cap on Claude's fair value | 1.5× Python's | §8.2 |
| First money step | Puts and shares together | §9 |
| Go-live bar | As written | §12 |
| Claude budget | "Tight, but slightly looser", with the right model per job to limit tokens | §8.5 |

Corrections to the operator's examples, recorded so the builder does not inherit them: **MU** is a
cyclical — "deep value" only near the bottom of its cycle, which is why cyclicals are valued on
5-year median margins (§6.5). **"BLOOM"**, if Bloom Energy (BE), is a high-growth, high-volatility
name with a short profit history and would most likely fail the health gates; if Bloomin' Brands
(BLMN), it is cheap but heavily indebted and would likely fail the debt gate. **GOOGL, META, BAC and
BE** are all wheel names today, which is what made the shared-ticker rule (§9.2) necessary.

## 20. Revision 3 — the adversarial review and the operator's answers (2026-10-29)
An Opus agent argued against the whole spec, revisions 1 and 2 included, and checked the code. Its
verdict was "build with changes". Stages 1–2 were sound; revision 2 had left about eight
contradictions, three of which touched orders, and Stage 3's shared-ticker design was unbuildable as
written. The author verified the code-level claims, all of which held:
- there is no `options.earnings_clear`;
- `ParsedExecution` has no clientId;
- `_tag_books` matches `ib_order_id`;
- the exec clientId is 14;
- `src/execution/` imports `src.claude.memory`.

**Fixed without asking (each repairs a defect, not an operator decision):**

| Fix | § |
|---|---|
| Auto-sending exits read Python's fair value; Claude-caused exits wait for a tap | §7, §7.1 |
| Shock stops under `full` only | §7.1 |
| One clamp rule: the cap applies, review is display-only | §8.2 |
| Tighter driver bounds, plus the Claude breaker and a clamp-hit metric | §8.2 |
| Bank/insurer and cyclical health sets | §6.4 |
| Earnings dates as plain data | §6.6 |
| The research worker owns every SEC fetch | §6.9 |
| A neutral input loader; the intent carries its fingerprint | §6.9 |
| Sector-ETF residuals; level changes only at the close | §7.1 |
| Shadow and regime triggers make no Claude call; realistic read sizes | §8.3, §8.5 |
| Put flow through the existing `promote` intent, with an `above_value_ceiling` re-check | §9.1 |
| `orderRef` attribution; independent W/V counts; fail-closed; wheel-only basis; sell cap; fault drills | §9.2 |
| Pot arithmetic (`value_liquidity_claim`), cash-only value book, gross cap | §9.3 |
| `src/value/executor.py`; value approvals in `value.db` sent only by clientId 31 | §9.7 |
| `value` pre-registered as the live policy | §7 |
| §1 Success wording | §1 |
| Go-live: what it can't prove, fixed-horizon returns, mandatory Stage 1b, track-specific count | §12 |
| A calibration dry run as the first build step | §17 |

**The operator's answers:**

| Question | Answer | Where |
|---|---|---|
| What sets the size tier? | Claude's margin of safety, as decided in revision 2 (the reviewer recommended the lower of the two); the tighter bounds and the breaker are the guard | §8.2, §9.5 |
| GOOGL/META only after a ~50% fall? | Loosen the growth valuation now: r = 8%, half of SBC. Rough effect: GOOGL ~$101 → ~$151 Python, ~$227 with the clamp — still a ~30% fall from ~$300; the dry run prints the real numbers | §6.5, §17 |
| When does ticker sharing switch on? | From the start of share-buying; the fault drills are build acceptance | §9.2 |
| Whose shares are an assigned value-suggested put? | The wheel's, for v1 | §9.1 |
