# Risk envelope, leveraged-ETF policy and the spreads book — design

Date: 2026-11-13 · Status: **revision 3 (2026-11-14), ruled (§6.2)**; revision 3 adds the Leveraged Entry Signal (§0.2, §2.7, §3.5.1). Sequenced
**before** the Mastermind (`2026-11-12-mastermind-design.md`, now revision 4). That spec's envelope
repair, book repair and spreads decisions now live here; it references this spec as a prerequisite.
Revision 2 adds bought index puts as a **bridge hedge** during the glide (§0.1, §2.6, §3.10) and
decisions H1–H10; Claude's roles in hedging and the directional track are in the Mastermind (its §10.6–10.8).

**How this was produced.** Two reviewers (Opus and Sonnet) researched the operator's request
independently, then rebutted each other. The operator made eight binding rulings in the same session
(§0). A final review adjudicated every point still in dispute and re-verified the contested facts
against the code, git, the logs and copies of the databases (`sqlite3 .backup`, taken 2026-11-13
02:08 +0800). No `scripts.run_*` module was imported or run. The account is IBKR **paper** (`DUQ`
prefix), so every trading record below is paper evidence.

Tags: **[V]** verified for this spec; **[M]** a model, with its assumptions stated; **[W]** a web or
secondary source; **[U]** unverified. Reviewer findings are cited as **O2** / **S2** (critiques) and
**O2R** / **S2R** (rebuttals).

## 0. The operator's rulings (2026-11-13, binding)

| # | Ruling |
|---|---|
| OR1 | **0DTE: the reviewers' merged plan.** No new 0DTE book; no naked, strangle or long 0DTE, recorded as rejected with the evidence. Fix the existing spreads book: a static macro calendar, a link to the account halt and breaker, the Nov 10 phantom-close lesson, risk caps of about 0.5% of NLV per trade, 1% per day and −2% per month. Run the backtest the plan required. Then move spreads to SPX/XSP (check the wing-quote width condition), which frees SPY. State evidence bars for paper and for live |
| OR2 | **The SPY clash:** recommend freeing SPY by moving spreads to SPX/XSP, after the backtest, with the fence changes listed. An operator decision, with VOO/IVV as the fallback |
| OR3 | **The shock limit uses a glide path.** Primary limit: a beta shock-loss budget (target about 15% of NLV at SPY −10%). It starts at today's level and steps down over a set period. Meanwhile a new put is allowed only if it does not worsen the shock loss. Book repair (covered calls, trims, proposed with a tap) does the shrinking. No rule forces a sale. Paired with an unconditional exposure-weighted gross backstop |
| OR4 | **Leveraged puts** off by default; CSPs go on unleveraged underlyings. Leveraged puts only through the bottoming lot, at most 2 lots, a sleeve of about 3%. No VRP / fair-value waiver for them. Leveraged collateral counts at its leverage. Drop UPRO and DPST. SOXX, not SMH, is SOXL's twin |
| OR5 | **"Cash reserve" is the wrong frame.** Replace it with the envelope deciding headroom, a deployment rule by tail class inside it, limit levels raised only on stabilisation, and T-bills for idle cash if relevant. Answer the "missing income" worry with numbers |
| OR6 | **Claude's rungs.** Utilisation bands and limit levels are the operator's. Allocation inside the envelope (leveraged vs unleveraged) is R3. Strike/expiry is R4; the spreads picker's menu has an inside strike, so it is R4-type and paper only. Add a nonlinear-gap measure to the Mastermind's risk classification |
| OR7 | One combined spec, sequenced before the Mastermind; decisions prefixed **E** |
| OR8 | Update the Mastermind to match; move what this spec takes over and reference it back |

### 0.1 Revision 2 (2026-11-14): long options

The operator asked: *"what about buying puts and calls as a trading strategy? these are different
from 0DTE credit spreads. I wanted the mastermind to be able to buy puts when relevant."* He chose
the scope: **index hedges and directional bets**. Event protection and stock replacement are out of
scope. Two reviewers (Opus, Sonnet) researched it independently and rebutted each other, cited here
as **O3 / S3** (critiques) and **O3R / S3R** (rebuttals). The operator then ruled (binding):

| # | Ruling |
|---|---|
| OR9 | **The hedge is a bridge with a review gate.** A small index-hedge programme, owned by Python and run on a fixed schedule, runs only during the 13-week glide. Continuing past the glide needs an operator review, with a conditional sunset. Budget about 0.25% of NLV a month. Trims and covered calls are the main repair, and the spec says so. New hedge size is blocked at VIX ≥ 25; a self-funding roll is still allowed. **No S10 or U_ew admission credit:** opens are gated on S10_gross, which closes the "every position revalued" loophole, including puts bought by hand in TWS. Hedged S10 is for display and the survivability harness only. Gates read live greeks, not stored `iv_history`. Shadow valuation uses captured quotes |
| OR10 | **Claude gets a small auto budget for buying puts, in paper only** (the operator's choice over the reviewers' tap-only recommendation, knowing it cannot be proven skilful), in addition to the reviewers' merged roles. Specified in the Mastermind (its §10.7) |
| OR11 | **Directional bets are shadow-only (Track D).** No order path in v1. Specified in the Mastermind (its §10.8) |
| OR12 | **The instrument:** XND first if a 2–4 week shadow quote-capture bar passes, otherwise QQQ with no wheel QQQ shorts while a QQQ hedge is open and the E8/E9 conflict handled explicitly. Reject SPY/SPX/XSP, VIX calls and index collars. The hedge has its own book (`hedge:<id>`), disjoint from the other books at contract and underlying level |

What revision 2 changes here: §2.6 (evidence), §3.1 (the hedge row), §3.4.1 (S10_gross, live
greeks), §3.4.3 (T20, S-SMH), §3.9 (Claude's place), **new §3.10 (the bridge hedge)**, §4 (phasing),
§5, §6 (**H1–H10**), §7 and §8. The Mastermind's revision 4 holds Claude's hedge roles, the paper put
budget, Track D, the premium-cost dimension of its §4, and decisions H11–H16.

### 0.2 Revision 3 (2026-11-14): a dip-entry signal for the leveraged sleeve

The operator asked to use the McClellan oscillator with the 50- and 200-day averages to load up on
3x ETFs through CSPs or outright buys. The study behind it is §2.7. The operator then ruled (binding):

| # | Ruling |
|---|---|
| OR13 | **Our own signal, not the stock McClellan oscillator:** the Leveraged Entry Signal (LES, §3.5.1). A trend gate (the governing index above its 200-day), a pullback (RSI(2) under 5 or a close under the 50-day), and a McClellan-style breadth washout computed on the **Nasdaq-100** constituents, which sets the size tier |
| OR14 | **The trend gate governs the CSP sleeve too.** Above the 200-day, LES drives sleeve CSPs and share buys. Below it, only §3.5's bottoming and drawdown trigger may open a sleeve CSP, at half the tier, and no share is bought |
| OR15 | **A paper share-buy path for TQQQ and SOXL, built now.** Inside the sleeve and the envelope, refused in live. A position is held until the trend breaks (2 consecutive index closes under the 200-day), with no time stop |
| OR16 | **Signal-scaled sleeve up to 6%:** 3% of NLV (leverage-weighted) on a pullback, 6% with the breadth washout, always inside S10_gross ≤ L(t) and U_ew. This replaces E7's flat 3% |
| OR17 | **Breadth data:** the free thetrading.tools series (from 2016-11; personal-use licence, attribution) for history, plus the system's own daily count from Nasdaq-100 constituent closes going forward |

## 1. Intent

The operator's request, verbatim:

> "Firstly, Before implementing and creating the plan, I want to explore 0DTE options as another
> layer of a potential trading strategy and income stream. Through this, there is intraday capital
> efficiency, and the complete elimination of overnight gap risk (similar to credit spreads), as well
> as having more exposure to opening short positions. Buying Calls/Puts are also an option to explore
> for this.
> Secondly, I want to do further research into how puts on 3x leveraged stocks should be opened.
> Currently, i believe the system limits how many positions can be opened if there is too large of a
> drop, and waits. I think that the system should, on a normal basis, only open CSPs on unleveraged
> ETFs and stocks. i.e. for TQQQ, it should open on QQQ, SPY on UPRO, and SOXX/SMH on SOXL.
> Furthermore, I am unsure if Cash should be reserved to open only when there is a signficant drop
> (and whether I will be sitting on too much cash and therefore missing out on income). What is the
> best way to go about this?"

**The short answers.**

1. **0DTE.** The system already has a 0DTE book: the spreads book sells 0DTE SPY credit spreads.
   The evidence does not support a second one, naked or two-sided structures, or buying 0DTE
   options. The existing book needs its missing safety links, its skipped backtest and a move to
   cash-settled SPX. At this account's size it is a measurement instrument, not an income stream (§3.1–3.3).
2. **Leveraged puts.** The operator's direction is right. Leveraged puts become a small,
   drawdown-only sleeve, counted at their leverage, with no fair-value waiver. Routine CSPs go on
   unleveraged underlyings. QQQ needs a one-lot collateral class to be reachable at all (§3.5–3.6).
3. **Cash.** The account is not sitting on cash. Cash is 9% of NLV, stock is 94%, and the CSP
   budget ran at a median 98% of its limit for a month. The binding problem is too much high-beta
   stock, not idle money. A shock-loss envelope replaces the reserve idea. The income at stake in
   holding back is small next to the loss at stake in not repairing the book (§3.8).
4. **Buying puts (revision 2).** A small Python-run index-put bridge during the glide, on the
   Nasdaq-100, at about 0.25% of NLV a month, earning no envelope headroom. It is insurance, not
   repair: at the Nov 5 low a hedge sized for 7 points of S10 would have cut about a quarter of the
   loss, a proportional trim would have cut more, and a standing QQQ hedge lost 5.6–10.6% of its
   notional a year in the backtest. **Trims and covered calls remain the main repair** (§3.10).
   Directional long options stay in shadow (Mastermind §10.8).

**Why this comes before the Mastermind.** The Mastermind's risk-changing rungs need a repaired
envelope, a survivability harness and book repair. This spec is that work, plus the policy changes
the operator asked for. None of it depends on Claude.

## 2. Evidence (corrected)

### 2.1 The book and the envelope today [V]

Snapshot 2026-11-12 18:05Z unless stated.

| Fact | Value | Source |
|---|---|---|
| NLV, cash | $648.6k; cash $58.7k (**9.0%**) | `portfolio_snapshots` |
| Stock | $608.0k (**93.7%**); AMD 26.9%, GOOGL 23.3%, NVDA 15.3% | same |
| Short-put collateral | $207.7k (CRWD $141.0k, NVDA $41.5k, HOOD $25.2k) | same |
| Maintenance margin, excess liquidity | $184.6k (28.5%); $463.9k (71.5%) | same |
| Stock bought outside the system | AMD 300, BAC 1,000, GOOGL 300, NVDA 500, SOXL 500 (book `manual`, codes `O;P`): **$431.3k, 70.9% of stock** | `broker_executions` |
| Puts in the money vs cash (Nov 11 closes) | NVDA 205P/210P ($41.5k, expire Nov 13) and CRWD 230/235/240P ($118.5k): **$160.0k of strike against $58.7k of cash** | same + `price_history` |
| Gross, nominal: (stock + put strike × 100) / NLV | **1.08–1.53, mean 1.31** (last snapshot of each session, Oct 13–Nov 12). Nov 5 ran 1.46–1.53 all session. Mastermind rev 2's "1.18–1.44, peak 1.44" understated it | `portfolio_snapshots` |
| Gross, leverage-weighted (TQQQ/SOXL × 3) | **1.30–1.88, mean 1.53**; 1.36 on Nov 12 | same |
| Shock loss S10: SPY −10%, beta-scaled | Linear (delta) **19.1%** (betas capped at 2) / **21.3%** (Blume) / **26.2%** (raw 250-session OLS). Full revaluation, Blume betas: **22.0%** | `price_history`, `iv_history`; scratch `r3_shock.py`, `r3_fullreval.py` |
| CSP budget use, Oct 13–Nov 10 | Put collateral / (EL − max(20% EL, $10k)): **median 98%, peak 114% (Nov 5)**; 56% on Nov 11–12. The excess-liquidity budget was the brake that worked; maintenance margin never approached a limit | `portfolio_snapshots`; `capital.py:93-103` |
| The gross cap | `max_gross_notional_pct: 100` runs only inside `if vx.active and is_csp` | `risk_engine.py:527` |
| The breakers | The daily leg sums the **wheel's** positions' unrealised P&L (spreads legs excluded from the snapshot). The 3-session drawdown leg reads account NLV, which includes spreads P&L. A trip sets `system_settings.execution_halted`, which the spreads process never reads | `circuit_breakers.py:11-21`; `system_settings.py:31` |

### 2.2 Puts by class, and the leveraged ETFs [V unless tagged]

| Fact | Value |
|---|---|
| Realised put P&L, IBKR's column, system + manual books | TQQQ **−$6,965**, SOXL **−$4,078**: leveraged **−$11,042**. All other names **+$874** (CRWD −$3,735 included). Total −$10,169 |
| What that column hides | IBKR books zero realised on an assigned put; the premium goes into the stock's basis. On a cash basis (O2R, not re-derived here): leveraged −$11.0k, all closed, none assigned; non-leveraged closed +$3.4k; non-leveraged assigned +$7.3k of premium against roughly −$40k marked on the assigned shares. **Both classes lost money in this regime**, leveraged through stops, unleveraged through assignment |
| Premium sold | October: puts $38.0k (leveraged $12.7k), calls $6.2k |
| Never traded by the wheel | QQQ, SMH, SPY, UPRO, DPST (the 50 SPY rows are the spreads book's) |
| Put quotes with spread ≤ 10% of mid, Oct 29–Nov 12 | QQQ **97.8%** (581/594), SOXL 39.0%, SMH 38.2%, TQQQ 21.6%, **UPRO 0.45%** (25/5,504), **DPST 0.03%** (3/10,322) |
| Why QQQ never opens | One lot is $69.0k, 10.6% of NLV, above `max_collateral_per_ticker_pct: 10`; it needs a large slot, and AMD and GOOGL hold both. QQQ's 491 `no_headroom` rejects split by date: the budget on Nov 5, lot size on Nov 11 (S2R) |
| The SOXL shares | A manual buy on Oct 7 at $153.35, now $66.08 (−57%). Not an assignment |
| SOXL's twin | Last 250 sessions of daily returns: on SOXX β **2.96**, R² **0.998**; on SMH β 3.40, R² 0.979. SOXX is not in `price_history` or `iv_history` |
| Index drawdowns on the 17-month panel | QQQ ≥ 10% below its 60-session high on **8** sessions, ≥ 8% on 19. SMH ≥ 10% on **81** sessions (23% of the panel), ≥ 20% on 8. One-year realised vol: QQQ 21.3%, SMH 42.4%, SPY 13.7% |
| "Off" cannot be expressed today | `per_trade_cap` returns `max(1, …)` for a leveraged ETF (`regime_limits.py:185`) |
| The fair-value waiver | `vrp_waiver` exempts any name-level bottoming lot, leveraged or not (`regime_limits.py:274-307`) |
| The delta window | CSP `delta_min 0.20`, `delta_max 0.35`; `bottoming.signal_delta_max 0.25` "must be above delta_min: checked at load" |
| What the wheel does at its 2× loss line | Non-leveraged names: a defensive roll proposal or assignment, **never a buy-back** (2026-10-02; `triggers.py:247-276`). Leveraged: roll first, buy back only if no roll qualifies (2026-10-14) |

### 2.3 The spreads book (the existing 0DTE book) [V]

| Fact | Value |
|---|---|
| Structure | SPY 0DTE 5-wide credit verticals, one side a day, short delta ≤ 0.15, after a stalled move; 15:45 forced close (SPY settles in shares) |
| Size | `max_loss_pct_of_capital 0.10` × `starting_capital_usd 100000` = $10k per trade (1.5% of NLV); daily loss limit 10% of the notional capital |
| Record (`spread_positions`) | **baseline** (simulated) 9 trades, **+$415**, commissions $484; **paper** 3 trades, **+$647**, commissions $69 |
| Break-even | Realised **79.7%** from one stop-loss (−$492), against 7 of 9 wins (Wilson 95% interval 45–94%, S2R). The engine's own figure, shown to Claude, is 93.5–94.9%: a parameter, not a finding. With measured costs the structural figure is about 75–85% (O2R 81–89% at $0.20–0.30 credits; S2R 75–77%) |
| Costs | Entry crossing (`credit_mid − credit_natural`) is **$0.01 on all 165 candidates**; the shadow model charges $0.04 per spread per side (4×). Paper commissions ran $0.27–0.41 a leg against the modelled $0.65 |
| What Claude's skips cite | All 8 skips cite costs or a cost-derived break-even; 6 of the 8 also cite a plan rule |
| The picker's menus | 12 picks: baseline 4, skip 8. An "inside" (riskier) item was on 2 menus and never chosen |
| FOMC, Oct 28 | Baseline row 5 and paper row 6 opened 15:46–15:47Z and closed 18:07–18:13Z (11:46–14:13 EDT), across the 14:00 decision. `config/spreads.yaml:73` `events: []` |
| Halt | Only the file `data/spreads.halt` (`service.py:674`). The account link is a $10k excess-liquidity floor |
| Nov 10 | A profit-take close's cancel went unconfirmed; 2 lots filled 27 s later; `spreads.db` kept a 2-lot phantom; entries stayed blocked on the broker/DB mismatch through Nov 11–12; alerts misfired; settled by hand (`scripts.spreads_resolve`). Late-fill booking fixed in `9da9e8a` |
| The backtest | Never run. `data/spreads_bt` does not exist. The plan's rule ("switch to `mode: paper` only if shadow **and backtest** both show positive expectancy after costs", plan line 707) was skipped. The harness exists (`scripts/spreads_backtest.py`, `src/spreads/backtest/`) and has never run against a real ThetaData terminal |
| SPY on Nov 5 | Open 765.47 on a −0.17% gap; low 732.71, **−4.28% from the open**; close −4.41%. The day's damage was intraday |
| SPXW quotes | `gex_maps` stores the SPXW map, not leg quotes: SPXW wing widths are **unmeasured** |

### 2.4 Outside evidence and models

**0DTE literature.**

- Vilkov, "0DTE Trading Rules" (SPX, 2016–2024): unhedged 0DTE strategies "seldom paid off gross
  of costs"; the variance premium is "positive but tiny"; P&L follows realised skewness [W,
  secondary summaries].
- Muravyev & Ni (JFE 2020; S&P 500 options, 2004–2013, delta-hedged, gross at mid): option returns
  about −1.0% close-to-open and +0.3% open-to-close. Option sellers are paid overnight, not intraday
  [W, abstract]. On a 0DTE straddle +0.3% is about $0.02, below one half-spread (S2R).
- Beckmeyer, Branger & Gayda (2023): retail SPX 0DTE traders lost about $358k a day after daily
  expiries began; about 60% of it costs [W, secondary]. Cboe: over 95% of 0DTE trades are
  risk-defined [W, vendor].
- S&P 2016–2026: the overnight gap is about 25% of close-to-close variance; a strike one expected
  move from the open is touched on about a third of days [M, S2].
- Reg T on a naked broad-index put: about $106k per SPX contract near 1% OTM [W + M]. IBKR's house
  margin on 0DTE, its expiration-day liquidation practice and the after-hours exercise cut-off are
  **[U]** (IBKR pages returned 403).

**Put-writing by market state, with the system's loss line [M, this revision].** Weekly entries,
0.25-delta 30-day puts on the S&P 500, 1991–2026, IV = VIX × 1.05, credit × 0.98, 21-session horizon.
"Hold" holds to expiry (S2's study). "2× line" re-marks daily at that day's VIX × 1.05, takes 50%
profit and buys back when the cost to close reaches 2× the credit, at mid, no slippage. Return is per
dollar of strike, over cash.

| Bucket | n (months) | Hold: mean / 5th pct / worst | 2× line: mean / 5th pct / worst |
|---|---|---|---|
| All | 1,803 (431) | +0.48% / −2.0% / −28.9% | +0.07% / −1.7% / −5.6% |
| Calm (drawdown > −3%, VIX < 20) | 965 (288) | +0.33% / −1.5% / −28.9% | +0.01% / −1.4% / −5.6% |
| VIX ≥ 25 | 299 (115) | +1.06% / −1.7% / −16.5% | +0.28% / −2.8% / −5.4% |
| Drawdown ≤ −10% | 150 (58) | +0.95% / −4.9% / −10.6% | +0.19% / −3.2% / −5.4% |
| Drawdown ≤ −8% | 217 (84) | +0.61% / −5.6% / −21.5% | +0.15% / −3.0% / −5.4% |

Readings: elevated-IV entries beat calm ones under both valuations, so the sign survives the loss
line; the level falls by about three-quarters; calm-period index puts with a buy-back stop earn
about nothing (−0.04% in 2010+). Neither column is the wheel: for a non-leveraged name the wheel rolls
or takes assignment at the line (§2.2).

**Leveraged-ETF puts** [M, S2, 2010–2026 real ETFs, BS with a realised-vol IV proxy]: per unit of
underlying risk the 3× put adds nothing; worst trades −61% to −70% of strike. Conditional on the
underlying ≥ 8% below its 60-day high, the mean rises sharply (TQQQ +3.9% a trade against +0.45%
near the high), but synthetic 3× S&P puts lost money in 2001, 2002 and 2008, worst −55%. With the
2× buy-back line in a daily-mark simulation the 3× put's total turns negative (TQQQ −16% of
collateral against +14.7% held). In the account's own data SOXL's IV/realised ratio is 0.98: no
variance premium.

**The SOXL basis** [M]. With SOXX at 8% drift and 40% vol, the 3× fund's median log drift is
−0.48 a year. S2 quoted "P(regain the $153.35 basis) ≈ 14%". That figure is P(above the basis **on
a given date** 1–3 years out). Under the same assumptions the chance of **touching** the basis within
a year is about 36%, and ever about 57%. Neither is a forecast. Neither is the right question
either, because the basis is sunk.

**Covered-call capacity** [M, flat IV from `iv_history`, before earnings blackouts and IV/RV gates]:
0.25-delta 30-day calls on today's stock would sell about **$12.6k a month**. Only **$4.0k** of that
(AMD) has a strike at or above basis, which is all `min_strike_vs_basis: 1.00` allows.

**What covered calls do to S10** [M, full revaluation]: calls on every holding move S10 from 22.0%
to **20.2%**. A delta-linear measure would claim 16.7%. In a −10% index move a call's protection is
bounded by its premium. This decides how S10 must be computed (§3.4.1).

### 2.5 Corrections to the reviewers' record

| Claim | Status |
|---|---|
| O2: "leveraged ETFs are 109% of the realised put loss" | **Withdrawn by O2R.** IBKR's realised column books zero on assigned puts. The case against leveraged puts rests on the per-risk and tail evidence |
| O2: a 70% gross-utilisation band, "no new CSP until U < 0.70" | **Withdrawn by O2R.** Stock alone is 93.7% of NLV; the band is a forced-sale mandate (S2R) |
| O2: "Reg T margin is the one brake that has worked" | **Wrong** (S2R, verified): the EL-derived budget bound; maintenance never neared a limit |
| O2: a literal cash floor, cash − Σ ITM put strikes ≥ 0 | **Rejected** (§3.4.7): $160.0k of ITM strike against $58.7k of cash blocks every CSP |
| O2: break-even 79%, commissions 54% of gross | One stop-loss decides the 79%; the $899 gross was after simulated slippage, so friction was larger (S2R) |
| S2: break-even 95% | **Withdrawn by S2R:** the engine's parameter, with entry slippage counted twice (O2R) |
| S2: "the EL budget was never binding" | **Withdrawn by S2R:** median 98%, verified |
| S2: the spreads picker is R2 | **Withdrawn by S2R:** an inside strike makes it R4-type |
| S2: "50% base, 100% at VIX ≥ 25" as account policy | **Withdrawn by S2R** (a dedicated cash sleeve, not this book) |
| S2: SMH lot relief; SOXL β 3.41 | **Withdrawn:** SMH fits under 10%; 3.41 is the beta to SMH |
| S2: SPX commission share 1–3% | **Withdrawn by S2R** (ignored slippage) |
| S2: "P(regain basis) ≈ 14%" | **Mislabelled** (§2.4): a fixed-date probability, not a touch probability |
| Both: SPX cuts commissions 72–90% | **True only at the old $10k cap.** At 0.5% of NLV only SPXW 25-wide keeps it (§3.3) |
| Both: leveraged lots at delta ≤ 0.20 | **Collides with `delta_min 0.20`** and the load check (§3.5) |
| Both: a fixed index drawdown (8% or 10%) for leveraged lots | **Does not scale:** SMH sat ≥ 10% below its high on 23% of the panel's sessions (§3.5) |
| O2R: re-run the tail-class lean-in "under the system's 2× stop" | Done (§2.4). But the wheel does not stop a non-leveraged name at the line; it rolls or is assigned |
| Mastermind rev 2: gross peaked at 1.44 | **1.53** (Nov 5) |

### 2.6 Long options: evidence (revision 2)

Re-verified for this revision against the code and copies of the databases taken 2026-11-13
16:39 +0800. Every hedge cost below is a **Black-Scholes model with an assumed skew** [M]: no
historical index option quotes exist in the estate, so none of these costs is measured.

**The book and the indexes [V].**

| Fact | Value | Source |
|---|---|---|
| Book NLV against index returns, 22 sessions Oct 14–Nov 12 (daily regression) | SPY β 2.74, **R² 0.77**; QQQ β 1.87, **R² 0.94**; SMH β 1.03, **R² 0.94**. Both reviewers got the same figures independently; re-run here | `portfolio_snapshots`, `price_history`; scratch `h/basis.py` |
| The slide | NLV Oct 14 → Nov 5 −23.3% while SPY fell 4.8%, QQQ 11.2%, SMH 20.7%. From the Oct 13 NLV ($784.6k) to the Nov 5 low ($577.5k): −26.4% | same |
| S10 vs a tech scenario on the Nov 12 book, full revaluation | S10 **22.3%**; **T20** (the 23 `regime.tech_linked` names −20%, TQQQ/SOXL at 3× capped at −100%, every other name β × −5%) **23.7%**. S10's *level* matched the realised event; its *label* (SPY −10%) and its hedge mapping did not | scratch `s3r_t20.py` |
| A hedge's credit under the two scenarios (60 DTE, Nov 11 IVs, skew 0.8 [M]) | Gain per 100 of notional, S10 / T20: SPY 95P 4.57 / 1.68 (ratio **0.37**); QQQ 95P 7.68 / 12.42 (1.62); SMH 95P 14.52 / 11.31 (0.78). An SPY hedge credited under S10 would deliver about a third of that under the scenario that happened | scratch `s3r_credit.py` |
| Stored IV on stress days | QQQ `iv_history` (source `ibkr`) against VXN: Oct 16 17.0% / 27.1; Oct 22 18.9% / 28.7; Oct 30 16.5% / 28.5; **Nov 5 14.6% / 38.3**; Nov 6 31.7% / 34.0. The stored IV collapses on exactly the worst days | `iv_history`; FRED `VXNCLS` |
| SPY IV history | **Ends 2026-10-05** (QQQ and SMH run to Nov 12) | `iv_history` |
| What a gate on stored IV would do | Full revaluation of the short puts at a collapsed IV understates S10, G10, P20 and the +10-vol sensitivity: **the gate is loosest exactly when it should be tightest**. IV-rank floors misfire on the same days. A hedge marked at 14.6% on Nov 5 is worth a fraction of its real mark, which biases any hedge record against the hedge | — |
| Index option chains stored | `option_quotes` holds 8 SPY, 18 QQQ and 27 SMH chain samples, all Jun 15–25, 2026 (S3). There is no index-leg quote history for Oct–Nov | `option_quotes` |
| No buy-to-open path exists | `Strategy` = {COVERED_CALL, CASH_SECURED_PUT, ROLL} (`schemas.py:26-29`); `build_limit_order` returns `LimitOrder(action="SELL")` (`order_builder.py:26-48`); every monitor and exit skips `position >= 0` or keeps `position < 0` (`triggers.py:29,53,82,111,143,181,261`; `roll_policy.py:64`; `intraday.py:712`; `profit_take.py:253,448`; `roll_executor.py:87`; `capital_release.py:169`). A bought option would be **unmanaged**: no roll, no close, no expiry handling | code |
| Collateral | `capital.py:179` counts only short puts; a long put adds none | code |
| External-close reconciliation | `reconcile_external_closes` (`reconciliation.py:482`) books any option BOT execution that is not on an `OrderRow` and matches a wheel short still net short as a **manual close** of that short. A hedge order kept out of `OrderRow` is invisible to its own-order skip | code |
| Exercise | An ITM QQQ or SPY long put at expiry auto-exercises: it sells the ETF's shares (wheel shares if the wheel holds them, a short stock position if not). XND and SPX are cash-settled and European [W: Nasdaq XND fact sheet] | — |

**What a hedge would have done in this slide [M on V prices; VXN-based IV, skew 0.3–0.8].**

| Hedge | Premium, % of NLV | Loss at the Nov 5 low | Loss on Nov 11 |
|---|---|---|---|
| None | — | −26.4% | −17.7% |
| QQQ 95% put, 60 DTE, sized for 7 points of S10 | 1.2–1.4 | **−19.5%** (covers 26% of the loss) | −15.5% (13%) |
| QQQ 95/85 put spread, same sizing | 1.5–1.7 | −19.8% | −14.8% (16%) |
| QQQ 90% put, 60–90 DTE (O3's 15-contract hedge, re-priced at VXN) | 1.6–2.6 | covers 25–30% | covers 5–9% |
| SPY 95% put, same sizing | 1.0–1.9 | −22.2% | −17.5% (1%) |
| A pro-rata trim of 32% of the book on Oct 13 (approximate) | none | **−18.0%** | **−12.1%** |

The one number: **a hedge sized to remove 7 of the 22 S10 points would have cut the loss at the
Nov 5 low by about a quarter (−26% → about −19.5%), and by 5–17% of it on Nov 11–12 after the
rebound, depending on strike: about a tenth.** Its premium was about 1–2% of NLV. A proportional trim
beat every put at both dates. The budgeted bridge of §3.10 buys about a third of that size. (O3's
first "~30%" used the wrong base and stored IV; S3's "95–99%" is delivered ÷ credited, not coverage.)

**Carry and timing [M].**

| Fact | Value | Source |
|---|---|---|
| Always-on index puts, long history | 1.8–4.4% of hedged notional a year, calibrated to Israelov's PPUT drag (S&P 1991–2026, NDX 2002–2026; O3). 4.3–6.9% a year at skews 0.3–1.0 (S3). The calibration is one point; skew is the largest uncertainty | O3, S3; Israelov, "Pathetic Protection" [W, secondary] |
| A standing QQQ hedge on this panel (8 non-overlapping rolls, Jun 2025–Nov 2026, held to expiry) | **−5.6% to −10.6% of notional a year; 0 of 8 rolls won.** With a 2× take-profit: −2.7% to −6.9% | scratch `s3r_standing.py` |
| Buying when stressed (S&P 1990–2026, 1,806 overlapping 60-day entries, 95% put) | Payoff per $ of premium: VIX < 15 **0.43**; 15–25 **0.70**; **25–35 0.20**; ≥ 35 0.29 | scratch `s3_cond.py` |
| In this slide | A QQQ 95% put bought on the first VIX ≥ 25 close (Nov 5, the low) lost **66–79%** of its premium by Nov 11. Bought on Oct 14 (SMH below its 50-day) it was worth +356–422% at the trough | S3, re-run in O3R |
| Monetisation | On NDX 2002–2026 a 2× take-profit trimmed the bleed by 0.1–1.5 points of notional a year; 3× and 5× were no better than holding. The multiple is fragile | scratch `s3r_monet.py` |
| Learnability of timing | A 95% put paid more than it cost in 12 of 215 non-overlapping 60-day windows. Detecting a rule that cuts the bleed by a quarter needs ~670–1,070 windows; independent ≥ 10% drawdowns run 0.62 a year (S&P), 1.19 (NDX), 1.26 (SOX). **Decades** | S3 `s3_sd.py`, `s3_eps.py`; O3 §A.4 |
| Hedge-funded CSP headroom | One S10 point admits ~$80–100k of 0.25-delta put strike by full revaluation, earning $4.6–5.7k a year held to expiry or $0.7–0.85k with the 2× line (§2.4 rates). The hedge's net carry is $4.3–7.5k a year per point. **At best break-even**, and the wheel's realised put P&L is −$10.2k | O3, S3R `s3r_csp_s10.py` |
| Trims vs hedges per unit of risk | Trims cost ~0.3–0.6% of NLV a year per S10 point (CAPM, ERP 3–6%); puts ~0.4–1.2% net. Israelov: a divested portfolio matched PPUT's return with a third smaller worst drawdown [W] | O3, S3 |

**XND (Nasdaq-100 micro, 1/100 of NDX)** [W, unverified]: about $28.3k a contract; European,
cash-settled. One third-party snapshot (Nov 12) shows **total open interest ~19.9K, ~2.0K traded, and
an average bid/ask of ~30% of mid across the whole chain** (wings included). The whole chain's open
interest is smaller than one QQQ strike's (27,575 on QQQ 680P, Jun 25 [V, `option_quotes`]). **XND
liquidity is unmeasured;** IBKR's routing, fees and paper behaviour for XND are [U].

### 2.7 Dip signals for 3x ETFs: evidence (revision 3)

The study ran on 2026-11-14 as a scratch replay, not repo code.
- **Breadth:** thetrading.tools' free series, 2016-11 to 2026-11. It is computed from that provider's own
  stock universe, not official NYSE counts [W]. The ratio-adjusted oscillator computed here matched the
  provider's published values exactly [V].
- **Prices:** yfinance.
- **"Synthetic 3x":** 3 × the index's daily return − 3%/yr, for history before the real ETFs.
- **Timing:** signal on the close, entry at the next close. Costs beyond ETF fees are ignored [M].

| Finding | Numbers |
|---|---|
| **The 200-day is the robust part** | Holding TQQQ only while QQQ > 200-day, 2017–2026: CAGR 35.0% vs 37.5% buy-and-hold, worst drawdown −56% vs −82%. Gayed and Bilello report the same for 2x S&P 1928–2015 [W] |
| **The NYSE McClellan oscillator: no consistent edge** | TQQQ 40-session returns after oscillator < −50 / −70 / −90 with QQQ > 200-day: +13.1% / +10.6% / +2.3%, against +8.1% from a random day. The result flips with the threshold, and n = 9–34 [V, 2017–2026 only] |
| **It missed the Nov 2026 dip** | QQQ fell 14.8% from its 60-day high on Nov 5. NYSE oscillator low −1, Nasdaq-100 oscillator low −17: the selloff was narrow and led by tech |
| **Dip buys under the 200-day lose, out of sample** | Before 2017, RSI(2) < 5 with the index under its 200-day: 10-session synthetic 3x return QQQ −0.5%, SOXX −1.1%. Drawdown ≥ 1σ₆₀ plus a reversal bar: worst 40-session result −79% |
| **Pullbacks above the 200-day beat a random day** | Before 2017, 20-session synthetic 3x returns: QQQ RSI(2) < 5 +4.3% vs +1.7% random-above-200-day; SOXX +7.5% vs +3.1%. 2017–2026: QQQ +2.9% vs +4.5% (worse), SOXX +9.6% vs +7.1% |
| **The breadth washout adds a little** | Above the 200-day with Nasdaq-100 oscillator < −40 and RSI(2) < 10, 2017–2026, 20 sessions: SOXX +12.2% vs +7.1%, QQQ +5.0% vs +4.5%. **No out-of-sample test is possible** (data from 2016) |
| **LES as a whole** (pullback entry, hold to a trend break) | QQQ synthetic 2000-06 to 2016: CAGR 10.9%, max DD −65%, Sharpe 0.46, against 4.2% / −84% / 0.31 for the 200-day filter and −15.7% / −99.9% / 0.20 for buy-and-hold. SOXX: 10.2% / −77% / 0.44 against 4.7% / −90% / 0.35. 2017–2026 real ETFs: TQQQ 25.4% / −62% / 0.71 (below both, 35.0% / 0.85 and 37.5% / 0.81); SOXL 38.1% / −77% / 0.81 (the best of the three) |
| **Data** | IBKR's AD-NYSE index is live-only, and historical requests have been reported to fail [W, 2015]. Official NYSE breadth history (1960s on) is sold by McClellan Financial [W] |

The LES parameters were chosen **after** seeing these numbers. The replay in the plan is therefore a
reproduction check, not an independent test. The forward `record` period is the only clean evidence.

## 3. Decisions

### 3.0 Adjudications where the reviewers still disagreed

| Point | O2 / O2R | S2 / S2R | Decision | Why |
|---|---|---|---|---|
| Primary limit | Shock budget, after withdrawing the 70% band | Shock budget S10 | **S10, full revaluation, with a glide path** (OR3) | Both converged; the band cannot be met without selling |
| Gross backstop level | ~1.0 leverage-weighted for new adds | 1.5 | **1.25 target, gliding from today's 1.36** (E5) | At 1.0 the backstop is the literal cash-secured floor: it binds before S10 on any book of beta ≥ 1, so it would be the primary in disguise. At 1.5 it never binds for beta ≥ 1, because S10 ≤ 15% already forces gross ≤ 1.5/β. At 1.25 it binds only when the book's average beta is below ~1.2, which is where a linear shock measure understates the financing risk of full assignment |
| Literal cash-secured floor | Proposed in O2 | Blocks every CSP | **Rejected as a gate**; shown as a fact | Verified ($160.0k ITM vs $58.7k cash). It also flips with moneyness tick by tick. Financing risk is the backstop's job |
| CC below basis on leveraged shares | Move toward it; keep the D14 replay; don't quote 14% | Risk-reducing; P(regain) ~14%; adopt now | **Allowed as a class floor, surfaced only as tap-only repair proposals, delta ≤ 0.25, confirmed by the D14 replay** (E12) | Reducing on delta and S10 (Mastermind §4). The basis is sunk. But SOXL's VRP is about zero, so it is a hedge at a fair price, not an income engine. Its crash protection is its premium. The bigger reducer of the 3× gap and decay tail is the de-lever proposal |
| Leveraged drawdown trigger | ≥ 8% (O2R) | ≥ 10% (S2R) | **Volatility-scaled: ≥ 1.0 × the governing index's 60-session σ** (≈ 10.4% for QQQ, ≈ 20.7% for SOXX/SMH today) | A flat 10% fired on 81 SMH sessions (23%), so for semis it is no drawdown condition; SMH at 20% and QQQ at 10% are equally rare (8 sessions each). On S&P history the −8% bucket carries the Feb 2020 first leg (worst −21.5% held) and has the lower mean under both valuations |
| Index collateral class | One lot ≤ 12%, {QQQ, SMH, SPY} | ≤ 15%, {QQQ, SPY, VOO} | **One lot ≤ 15% of NLV, {QQQ, SPY}; VOO/IVV only as the SPY fallback; SMH/SOXX out** (E9) | SPY is 11.7% of today's NLV; at 12% a 3% NLV fall puts it out of reach, and NLV fell 17.7% in a month. SMH fits under 10% already and is semis-concentrated |
| Spreads book as evidence | The R2/R4 evidence lab | A machinery pilot only | **A machinery pilot, plus its own R4-type record. Never evidence for a wheel rung** | Skill at choosing a 0DTE SPY spread says nothing about cutting or selecting wheel entries. The pre-registration, placebo and valuation machinery transfers |
| Break-even | ~80–85% | 75–80% realistic | **About 75–85%; the book runs at or below break-even.** Recalibrate the shadow slippage (4× measured) before the picker's record counts | Both converged; the data cannot tell 75% from 95% at n = 9 |
| SPX vs XSP | Undecided until narrow SPX widths are measured | XSP "worst of both" (withdrawn in part) | **SPXW 25-wide, 1 lot, if its measured all-in cost per $1k of max loss is no worse than SPY's; XSP only for settlement if SPXW fails** (E3) | At the new cap XSP 5-wide needs as many leg-fills as SPY; only SPXW keeps the commission saving (§3.3) |
| Tail-class deployment | Accepts the index-1× lean-in; re-run under the 2× stop first | Index 1× not cut in stress, inside the envelope | **Adopt for index 1× only, record-only until a wheel-faithful replay** (E10) | My re-run: the sign survives the 2× line, the level drops by three-quarters. The wheel rolls or takes assignment instead, so the activating replay must model that |
| Muravyev & Ni | "The most important counter" | Sharpens the null | **It sets H0** for any 0DTE promotion: intraday expectancy after measured costs ≤ 0 | A gross-at-mid, 2004–2013 result; its sign matters more than its size |

### 3.1 0DTE: no new layer

**The correction the operator needs.** 0DTE closed before the bell, or cash-settled, removes the
overnight quarter of daily variance, **and with it the part of the day in which option sellers have
historically been paid**. What remains is the intraday three-quarters: FOMC afternoons, flash moves,
days like Nov 5. "Complete elimination of overnight gap risk" is true of the gap leg and wrong as a
statement about risk. "Intraday capital efficiency" is turnover, not cheaper margin: a defined-risk
spread's margin is its width at 0DTE or 30DTE, and the account is not short of capital (§2.1).

**Rejected (OR1), with the evidence:**

| Structure | Why rejected |
|---|---|
| A second 0DTE book | It would duplicate the spreads book's process, gate, GEX map, executor, market-data lines and fence, and compete with it for the same flow and margin |
| Naked short 0DTE puts or calls | About $106k of Reg T margin per SPX contract; a Nov 5 day costs about $26k per contract against a ~$300 credit (O2, [M]); fails survivability (Mastermind §3 line 4) on today's book |
| Short strangles | Both tails of the above |
| Long 0DTE calls or puts for income or direction | Negative expected value on average, the other side of the variance premium; retail buyers' losses (Beckmeyer et al.); no evidence of directional skill (the spreads plan's bias was neutral 18 of 22 days, never bullish) |
| 0DTE as the wheel's hedge | Wrong tenor: the damage was a multi-week slide (NLV −17.7% Oct 13–Nov 11). **Revision 2:** the hedge, if any, is the 60–120-day Nasdaq-100 bridge of §3.10, run by Python; the rejection of long 0DTE options stands unchanged |
| "More short positions" | The account is already 94% long stock; more short premium adds the same sign of risk |

**Deferred, not rejected:** iron condors and flies, as Python-built shadow menu items valued daily,
only after the backtest (§3.2 g) shows the single-side spread is positive after costs.

### 3.2 Fix the spreads book

All deterministic, inside `src/spreads/` (and `scripts/run_spreads.py` config), behind
`src/spreads/risk.py::validate`, which stays the only gate and runs twice.

| # | Change | Detail |
|---|---|---|
| a | **Static macro calendar → `risk.events`** | One static FOMC / CPI / PPI / NFP / PCE schedule in config, published a year ahead, shared with the Mastermind's 45-day calendar (its D19). Default: no new entries on an FOMC decision day; 08:30 ET prints land before the entry window and get no block unless the operator sets one (E2). Dates are checked against federalreserve.gov and bls.gov when the file is written ([U] today: the reviewers used aggregators) |
| b | **Account halt link** | Each cycle `src/spreads/service.py` reads `src.storage.system_settings.is_halted()` and the slow breaker's state (§3.4.5). A trip blocks new entries; exits keep running. `service.py` is the one spreads module the fence lets import `src.storage` |
| c | **Spreads P&L in the daily leg** | The wheel's mark-based daily loss leg adds the spreads book's realised and open P&L for the day, read through a neutral read-only `src/common/spreads_view.py` (`mode=ro`, plain SQL, the `value_view` pattern; it imports no `src.spreads`). The drawdown legs already see it through NLV. A trip card shows the loss by book |
| d | **The Nov 10 lessons** | Keep the late-fill path (`9da9e8a`) under a test. Keep the broker/DB-mismatch entry block: it failed safe. On SPY, a failed 15:45 close leaves after-bell exercise exposure; cash settlement removes it, which is the main settlement argument for §3.3. After the move, `let_expire` lets far-OTM legs expire instead of chasing a close on a fast tape |
| e | **Risk in % of NLV** | The process reads NetLiquidation from its own account summary. Max loss per trade ≤ **0.5%** of NLV (contract count from it); realised plus open loss today ≥ **1%** → no entries today; month to date ≤ **−2%** → no entries until the next month, reset by a human. `starting_capital_usd` stops setting size. The $10k excess-liquidity floor becomes a share of NLV (E2) |
| f | **A cost standard** | `shadow_slippage_per_leg` = the measured median crossing plus a stated margin; commission = IBKR's actual schedule for the instrument, exchange fees included; `be_nominal_exits` recomputed before Claude sees it. Fixed before any record window opens |
| g | **The backtest** | ThetaData Options Standard (~$80 a month, plan line 706) through the existing harness. SPY and SPXW (XSP if the subscription has it). ≥ 3 years including 2020 and 2022 if the subscription reaches them, otherwise the longest available, stated. At the cost standard (f) and the new caps (e). Report expectancy after costs, break-even win rate, worst day, worst 20 sessions, and the tag breakdowns. Expect harness fixes: it has never touched a real terminal |
| h | **Mode until (g) passes** | `mode: shadow`, the plan's own rule (E1) |

**Evidence bars.**

| Gate | Bar |
|---|---|
| **Paper** (back to `mode: paper`, or any new menu item) | The backtest (g) shows expectancy after measured costs > 0 at the lower bound of a 90% session-clustered interval, and a worst 20-session loss ≤ 2% of NLV at the new caps. For the SPX move, also §3.3's cost condition |
| **Live** (needs a separate live plan; `run()` idles under `LIVE_TRADING=true` today) | Pre-registered before data. ≥ 120 traded sessions spanning ≥ 1 down and ≥ 1 up/calm leg (about a year or more at today's ~0.45 trades a session). H0: intraday expectancy after measured costs ≤ 0. The mean per episode after measured costs, with a 90% session-clustered lower bound > 0, against the baseline and a matched random-entry control. A paper-vs-backtest slippage reconciliation. No day worse than 1% of NLV. A 1-lot live SPXW trial first. The account couplings (b, c) live. A good outcome is not assumed: the evidence in §2.4 predicts a fail, which is acceptable, because the book's product is evidence |

### 3.3 Move spreads to SPX and free SPY (OR1, OR2; E3)

**Recommendation.** After the backtest, run SPXW in shadow beside SPY for 2–4 weeks, measuring real
SPXW wing quotes. If the cost condition holds, move the traded leg to SPXW and free SPY for the wheel.

**What the new cap does to the instrument choice.** At 0.5% of NLV (~$3.2k) the plan's "$5k
trigger" is no longer met, and the reviewers' 72–90% commission saving (computed at $10k) holds only
for a wide SPX spread:

| Instrument at ~$3.2k max loss | Lots | Leg-fills per round trip | Commission vs SPY |
|---|---|---|---|
| SPY 5-wide | 6 | 24 | — |
| XSP 5-wide | 6 | 24 | the same count; Cboe fees on top [U] |
| SPXW 10-wide | 3 | 12 | about half |
| **SPXW 25-wide** | **1** | **4** | **about −80%** before SPX's higher per-contract fees [U] |

**The wing-quote width condition.** SPXW is used only if its all-in round-trip cost (commission,
exchange fees and measured crossing) per $1,000 of max loss is no worse than SPY's, measured over the
shadow window. Indicatively [M]: at SPY's measured $0.01 entry crossing and 6 lots, SPXW 25-wide
breaks even at roughly $0.10 of quoted width per wing leg. If SPXW fails and XSP passes, XSP buys
cash settlement alone (operator's call). If both fail, the book stays on SPY and SPY stays reserved.

**Config** (plan lines 596-599): `underlying: SPX`, `underlying_sec_type: IND`, `trading_class:
SPXW`, `exchange: CBOE`, `exits.let_expire: true`, `gex.scale_to_underlying: 1.0`. The GEX source is
already SPX.

**The fence changes, together, in one plan task** (book = underlying still holds: SPX and SPY
contracts are distinct, and a cash-settled book never produces SPY shares):

- `config/spreads.yaml` and `config/examples/spreads.yaml`: `book_underlyings: [SPX, XSP]`.
- `Config._spreads_isolated`: no logic change; it now admits SPY to `universe.yaml`. Its test fixtures change.
- `src/common/books.py`: no code change (it reads config; `_DAILY_ROOTS` already maps SPXW).
- **The ledger.** `_tag_spreads` tags by underlying at ingest, and already-tagged rows are safe. But a
  later import of pre-cutover SPY rows (a Flex backfill, a rebuild) would no longer be tagged, and
  `_tag_books` could attach one to a wheel SPY order with the same order id. Add a dated rule, e.g.
  `spreads.retired_underlyings: {SPY: <last spreads session>}`: SPY executions on or before that
  date are tagged `spreads`.
- The rules engine's `reserved_for_spreads_book`, the web override's 422, the drain's refusal and
  `get_positions()` follow config.
- Tests: `tests/test_spreads_fence.py`, `tests/test_wheel_spreads_isolation.py`,
  `tests/test_spreads_config.py`.
- `config/universe.yaml`: SPY into `indexes` / `would_own`, `sectors: SPY: index`; delete the line 51
  comment ("S&P 500 exposure is wheeled via UPRO").
- CLAUDE.md's spreads-fence text ("SPY, SPX, XSP"), ARCHITECTURE.md, SETUP.md §16,
  UNIVERSE_RESEARCH.md and `strategist.py` `_UNIVERSE_CONTEXT`.
- **Cutover:** the spreads book flat in SPY, between sessions, both processes restarted (daemons do
  not hot-reload).

**The fallback (OR2).** If SPY stays reserved: VOO or IVV for the wheel, only after they pass the
liquidity gate in shadow (no measurement exists; S&P-proxy options are thin, and UPRO's 0.45% shows
how thin proxies fail). The third option is no S&P sleeve at all, which the book has run without for
five weeks.

**Why SPY matters to the wheel.** It is the only index CSP outside `regime.tech_linked`. Under the
tech-linked group cap (§3.4.4), which this book saturates, it is the one index put that adds premium
without adding to the binding group. Its IV/realised ratio was the best of the pairs measured
(1.22–1.27; S2, O2R).

### 3.4 The envelope (moved from Mastermind §6)

Deterministic, human-set, backtested. It decides whether any opening that adds risk may proceed.

#### 3.4.1 Primary: the shock budget S10 (OR3; E4)

**Definition.** S10 = the loss, as a share of NLV, if SPY falls 10% in one step, with:

- every position **fully revalued**: Black-Scholes at current IV for options; IV unchanged, plus a
  sensitivity at +10 vol points;
- each underlying moved by β × −10%, with β the Blume-adjusted 250-session beta to SPY (0.67 β +
  0.33);
- leveraged ETFs moved by leverage × the governing index's β, capped at −100%;
- the value book's holdings included when the book is active.

S20 (SPY −20%) is reported beside it. Full revaluation is required because a linear measure credits
covered calls with three times the crash protection they give (§2.4). That error would let a
covered-call-then-new-put loop add tail risk while S10 read flat.

**Level and glide.**

- **Target:** 15% of NLV at SPY −10% (operator's figure).
- **Start:** S10 measured on the day the rule goes live, rounded up to the next whole percent (≈ 22% today).
- **Glide:** the limit L(t) steps down linearly each week to the target over 13 weeks (E4).

**The rule.** An opening position that adds to S10 (a CSP, a sleeve lot, and later any R3/R4 item)
is allowed only if S10 after the trade ≤ L(t). While the book is above L(t), only openings that do
not raise S10 pass. Closes, covered calls and rolls are not tested against L(t): rolls stay governed
by `roll:`, and their effect on S10 is reported. **No rule forces a sale.**

**Long options, and the loophole (revision 2, OR9; H1).** As first written, "every position fully
revalued" includes a long put. Any bought put, including one bought by hand in TWS, would lower S10
and open room for new CSPs under L(t), with no rule on its tenor, basis or decay. So:

- **S10_gross** revalues every share and every *short* option, and **no long option, whoever bought
  it** (the hedge book, Claude's paper puts, a manual TWS order). **Every admission test reads
  S10_gross**: the L(t) rule above, and the same convention for S20, G10, P20 and T20 wherever they
  classify or gate.
- **S10_net** includes long options. It is shown everywhere beside S10_gross and feeds the
  survivability harness (§3.4.6). It never admits a trade.
- This lands in E0, before any buy-to-open path exists, because the loophole exists without one.
- Any later headroom credit for a hedge needs its own ruling after the review gate (H10).

**IV for the gates (revision 2, OR9; H7).** Admission-time S10_gross, G10, P20 and T20 reprice each
option at the **live IV from IBKR model greeks**, fetched through `req_fresh_mkt_data` at decision time
and again at send time, not from `iv_history`. Stored IV collapsed on the worst days (Nov 5: 14.6%
against VXN 38.3; §2.6). The daily display may use stored IV only after the sanity check of §3.10.8,
and labels it.

**What the glide will feel like, honestly.**

- Covered calls on every holding lower S10 by about 1.8 points (22.0% → 20.2%).
- The remaining ~5 points come only from shares called away in a rally, or from trims the operator
  taps. For scale: selling the SOXL shares is about 2.6 points; AMD alone is 7.0 points of S10.
- Until then, no new CSP opens. The operator rules on that knowing it (E4).

#### 3.4.2 Backstop: exposure-weighted gross, unconditional (OR3; E5)

- **Definition.** U_ew = (stock MV × leverage factor + Σ short-put strike × 100 × leverage factor +
  the value book's claim when active) / NLV. ITM puts count at strike.
- **Unconditional.** Remove the `vx.active` condition at `risk_engine.py:527`, so the check runs for
  every opening CSP. Investigate first why it never fired with `value.book.enabled: true` in the
  private config (Mastermind rev 2 §2.3, still unverified).
- **Level.** The limit for new risk-adding opens glides from today's 1.36 to a **1.25** target over
  the same 13 weeks; existing positions above it are not touched. The reasoning is in §3.0.

#### 3.4.3 The nonlinear-gap measure (OR6)

S10 is linear in beta, so it reads a TQQQ lot that replaces equal beta-dollars of QQQ as *lower*
risk: same delta, same linear loss, less collateral. That is wrong. Two scenarios, computed by full
revaluation, are added:

- **G10:** a one-day index −10% gap, with leveraged ETFs at leverage × their index move (capped at −100%);
- **P20:** a −20% index path over 10 sessions, with daily reset applied to leveraged ETFs along a fixed,
  pre-registered path.

They feed the Mastermind's §4 classification (a choice worse on G10 or P20 is risk-changing) and
the brief's facts. They are display and classification measures, not limits: the leveraged sleeve
cap bounds that tail (§3.5). Evidence: SOXL fell −38.7% on Nov 5; 17 days of ≤ −20% in 4,195 sessions (S2).

**The tech scenarios (revision 2; H8).** S10 is a one-factor SPY measure, and the damage was a
tech/semis factor move (book R² 0.94 on QQQ and SMH, 0.77 on SPY; §2.6). Two scenarios are added:

- **T20:** the 23 `regime.tech_linked` names −20% (leveraged ETFs at their leverage, capped at
  −100%), every other name β × −5%, full revaluation. 23.7% on the Nov 12 book, against S10 22.3%.
- **S-SMH:** SMH −30% with SPY −8%, names scaled by their beta to SMH. The semis sub-factor, for SOXL
  and the semis names.

Both are **display, survivability-harness and classification** measures, and T20 is a member of the
scenario grid for any future hedge credit (H10). **Neither is a limit.** Adjudicated (§3.10.0): T20
sits within 1.4 points of S10 today, so a T20 limit at the same target would not bind before S10, and
for tech-linked names it duplicates the leverage-weighted group cap (§3.4.4, E15). The E1 replay
reports T20 against a QQQ-beta-scaled variant (O3R's objection that T20 moves 23 names equally), and
**if T20 − S10 exceeds 3 points on adoption day or after, it returns to the operator as a candidate
binding limit** (H8).

#### 3.4.4 Correlated exposure: tech-linked group cap and stacking rule (moved from Mastermind §6.2)

- **A tech-linked group cap** in risk units over `regime.tech_linked` (23 names), **leverage-weighted** (TQQQ and SOXL count 3×).
- **A deterministic stacking rule:** for example, halve or block a new CSP when the name already has
  an open short at an overlapping expiry, an ITM short, or ≥ k same-day fills.
- **Backtest both against the 10 `claude_cut` rows and the ledger first.** If they reproduce most of
  the cuts, build them, and measure Claude on the residual.
- **A standing rule-harvest report,** human-read and never auto-applied.

#### 3.4.5 A slow drawdown breaker spanning books (moved from Mastermind §6.3)

- **The leg:** a rolling 20–30-session drawdown leg on account NLV, beside the 3-session one. NLV
  already includes spreads P&L.
- **On a trip:** it demotes every risk-changing Claude rung to record-only, blocks risk-changing
  levers, scales the CSP budget by an operator-set fraction and **stops spreads entries** (§3.2 b).
  A human resets it.
- **What it cannot do:** stop an assignment. Gross is §3.4.1–3.4.2's job.

#### 3.4.6 The survivability harness (moved from Mastermind §6.4)

The analytic worst case and the always-most-aggressive replay, on the 17-month panel, with the
`sizing_counterfactual.py` machinery.

- **What it covers:** S10, U_ew, G10 and P20, plus the spreads book at its caps as a loss source
  (−2% of NLV a month at worst). Revision 2: also T20 and S-SMH, each computed gross and net of long
  options, with the hedge book and Claude's paper puts at their captured marks.
- **When it runs:** on the deterministic envelope first, before any risk-changing rung is proposed.
- **Its limits:** one bull leg and one sell-off; no 2020 and no 2022.

#### 3.4.7 Retire the "cash reserve" (OR5; E11)

- **`cash_reserve_pct` stays a margin buffer only.** It is 20% of excess liquidity (`capital.py:96-100`),
  never cash, and is not a policy lever. The CSP budget keeps its EL ceiling, with the envelope
  binding first.
- **Do not enable Portfolio Margin** while the budget derives from EL: PM would raise EL and silently
  widen the budget (S2R).
- **The literal cash-secured floor is rejected** (§3.0). The brief and the web show "cash after
  every ITM put is assigned" as a fact.

### 3.5 Leveraged-ETF policy (OR4; E7, E8)

**Default: no leveraged CSP.** New `leveraged_sizing.csp_mode: drawdown_only`. `per_trade_cap`
returns 0 for a leveraged name outside the sleeve (a code change: today it floors at 1). TQQQ and
SOXL leave `actively_wheeling` and stay `would_own`. UPRO and DPST leave the universe's trading
lists (OR4). LABU and TSLL stay CC-only.

**A sleeve lot opens only when all of these hold** (revision 3 changes conditions 1 and 8; see §3.5.1):

1. **Signal:** with the governing index **above** its 200-day, the LES pullback fires (§3.5.1); conditions 2
   and 3 then do not apply. With it **below** its 200-day, the name's or the governing index's bottoming
   signal fires (existing machinery), conditions 2 and 3 hold, and the lot sizes at half the tier.
2. **Drawdown:** the governing unleveraged index is ≥ 1.0 × its 60-session σ below its 60-session
   high, with σ₆₀ = one-year realised vol × √(60/252). Today that is ≈ 10.4% for QQQ and ≈ 20.7% for
   SOXX (SMH as proxy until SOXX history exists).
3. **IV rank** ≥ 50.
4. **DTE** 7–14.
5. **Delta** inside a sleeve window of its own, recommended 0.15–0.20 (E7). The reviewers' "≤ 0.20"
   sits on `delta_min 0.20`, so the load check that keeps `signal_delta_max` above `delta_min` changes
   for the sleeve.
6. **The fair-value floor applies:** `vrp_waiver` returns False when `leverage_factor` is not None.
   SOXL's IV/realised median is 0.98, and the floor rejected 5,264 of 10,127 SOXL put evaluations (S2R).
7. **Pace:** one lot per name per 3 sessions; at most 2 lots open.
8. **Sleeve cap (revision 3, OR16):** the LES tier, leverage-weighted, across all leveraged names and
   counting sleeve CSP collateral and LES shares together. That is 3% of NLV on a pullback and 6% with
   the breadth washout; below the 200-day it is half the tier (1.5%). At today's prices a TQQQ lot is ~$6k
   of collateral, ~$18k (2.8% of NLV) at leverage, and a SOXL lot is ~$5.5–6.6k, ~$16.5–20k at leverage.
   So the 3% tier is **one lot**, the 6% tier is two, and the 1.5% half tier is **zero lots** until NLV
   grows or the ETF's price falls. A lot never rounds up.
9. **Envelope:** each lot passes S10 and U_ew.

**Governing indexes:** TQQQ → QQQ; SOXL → **SOXX**. Add SOXX to the research worker's price and IV
history (absent today).

**Counted at leverage everywhere exposure is measured:** `ticker_collateral`, the CSP budget, U_ew,
the tech-linked group cap and the sleeve cap. Risk units already scale through IV.

**The record against this rule** [V, counterfactual only]:

- **Blocked:** every leveraged put the book opened (Sep 30–Oct 28, −$11,042). QQQ reached 10% below
  its high only on Nov 2–11, and SMH reached 20% only on Jul 28–29 and Nov 4–11.
- **Not yet valued:** the lots the sleeve *would* have opened in those windows. The replay values
  them before activation (§4, E1 phase).

**Assignment of a sleeve lot:** the 2026-10-14 roll ruling stands. On assignment, the leveraged
covered-call carve-out and the de-lever proposal apply (§3.7).

#### 3.5.1 The Leveraged Entry Signal (revision 3; OR13–OR17)

LES is deterministic tier and pure: price bars and breadth counts in, a signal out. No LLM output reaches
it. It is computed per governing index G (QQQ for TQQQ, SOXX for SOXL) on each completed daily close and
fails closed: missing bars, fewer than 200 sessions or a stale breadth count means no signal.

| Part | Rule | What it does |
|---|---|---|
| **Trend gate** | G's close > its 200-day simple average | Decides whether LES applies at all. Below it, only §3.5's bottoming path may open a sleeve CSP, at half the tier, and LES buys nothing |
| **Pullback** | Trend gate holds **and** (RSI(2) of G < 5 **or** G's close < its 50-day average) | Opens the **3% tier**: a sleeve CSP (conditions 4–9) or LES shares |
| **Breadth washout** | The Nasdaq-100 breadth oscillator (below) ≤ −40 on any of the last 5 sessions, with the pullback firing | Lifts the tier to **6%** |
| **Trend break (exit)** | 2 consecutive closes of G under its 200-day | Sells every LES share position on that ETF (paper, automatic). Open sleeve CSPs stay under the wheel's roll rules |

**The breadth oscillator** (inspired by McClellan, but built for this book). The stock McClellan oscillator
uses NYSE breadth, which held up through the Nov 2026 tech selloff (§2.7). The book's leveraged risk is
Nasdaq-100 and semiconductor risk, so LES counts the Nasdaq-100 constituents instead:
`RANA_t = (adv − dec) / (adv + dec) × 1000`, then `osc_t = EMA_0.10(RANA) − EMA_0.05(RANA)` (the 19- and 39-day
smoothing constants). History comes from the free thetrading.tools series (`ndx_advancing` / `ndx_declining`, from
2016-11). Going forward the system makes its own count each night from constituent closes, from a committed
constituent list refreshed quarterly. Where both sources exist, a gap of more than 10 points is flagged and the
system's own count is used.

**Shares.** An LES buy is a whole-share limit order at mid in TQQQ or SOXL for the tier's room: the tier's
leverage-weighted cap, minus the sleeve exposure already open, divided by the leverage. It also needs:
- S10_gross ≤ L(t) and U_ew ≤ L_ew(t) after the buy (a 3x share counts at leverage × the index β);
- `leveraged_entry` set to `on` in paper;
- one buy per ETF per 3 sessions.

A pullback signal that persists adds no new lot until the pace allows one and the tier has room. LES shares
are their own book: orderRef `les:<id>`, a ledger tag `book="les"`, never wheel shares. So the wheel never
writes a covered call against them, the value book never counts them, and a trim never sells them.

**Why the trend gate.** From 1999 to 2026, buying 3x dips under the 200-day lost money out of sample, while
pullbacks above it beat a random entry. The breadth tier rests on 2016–2026 data only (§2.7). The share
position's drawdowns stay severe (−62% to −77% on the position). That is why it is a sleeve: at the 6% tier,
leverage-weighted, the shares are about 2% of NLV, so a −77% drawdown costs about 1.5% of NLV.

**Activation.** `leveraged_entry` ships `record`: every would-be buy and exit is written with its envelope
result. It turns `on` in paper when the LES replay PASSes (the criterion is the plan's), and is refused in
live.

### 3.6 The index class and the universe (E8, E9)

**`portfolio.broad_index_etf_collateral_pct: 15` for `broad_index_etfs: [QQQ, SPY]`** (SPY once
freed):

- One lot of a listed name may reach 15% of NLV without a large slot; further lots need a slot.
- It still counts in the sector, tech-linked, U_ew and S10 tests.
- VOO/IVV join only as the SPY fallback, after a liquidity measurement.
- SMH and SOXX stay out: sector funds, semis-concentrated, and SMH fits under 10% anyway.

**Universe edits** (operator ruling in E8; each triggers the doc-update rule for `universe.yaml`):

- QQQ (and SPY after §3.3) into `actively_wheeling`.
- SOXX into `would_own` as dip-watch, to log its option liquidity before any use.
- SMH stays dip-watch.
- QQQ will still meet the tech-linked group cap while the book is semis- and tech-heavy. SPY will not.

### 3.7 Book repair (moved from Mastermind §7)

The loss is inventory, not new flow: 93.7% of NLV is stock, 70.9% of it bought outside the system,
and $436.5k of it underwater (−$131.0k, Mastermind rev 2 §2.3). Book repair is how the glide path
shrinks S10 without a forced sale.

1. **`min_strike_vs_basis` (N18), ruled by replay (E12).**
   - Options: keep 1.00; 0.95; 0.90 with a delta cap; per name.
   - **A leveraged-ETF class floor of none, delta ≤ 0.25**, surfaced only as tap-only proposals until
     the replay confirms it.
   - The replay, on the 17-month panel, shows per setting: premium harvested, assignments below
     basis, drawdown, and S10 over time.
   - Size: about $12.6k a month of 0.25-delta call premium on today's stock [M], of which $4.0k is
     allowed today.
2. **Tap-only repair proposals Python builds each day.** Each is priced, gated by the Rules Engine
   twice, quoted fresh and shadow-valued whether tapped or not. Each card shows S10, U_ew and L(t)
   before and after.
   - Covered-call overlays at the ruled floor, and the leveraged carve-out.
   - "Stop adding" on a name.
   - **Trims**, which need a stock-sell order path (does not exist).
   - **De-lever** for leveraged shares: sell the 3× shares, optionally buying the unleveraged twin at
     up to the same beta-dollars. It needs stock sell and buy paths.
   - Protective puts on single names: **out of scope** (revision 2; the operator scoped long options
     to index hedges and directional bets). They would also net against wheel CSPs on the same names
     and exercise into wheel or value shares. The index bridge is §3.10, and it is not repair.
3. **The SOXL 500 shares are the named hard case.**
   - A call at 0.25 delta (~$95, +43%) sells about $1.7k a month [M].
   - It reduces delta. It is roughly zero-EV at SOXL's measured VRP. Its crash protection is its premium.
   - It risks being called away in a V-rebound (+62% in four sessions off Nov 5).
   - The de-lever proposal removes the gap and decay tail; the call does not.
4. **Discretionary stock buys.** The system cannot gate a manual TWS order. The brief and the web show
   S10 and U_ew before and after any manual buy, and the next day's L(t) headroom (E13).
5. **Unchanged:** decision 30 stands (Claude never holds, delays or moves a covered call), and the
   Mastermind's "reduce" stance becomes a repair proposal, never an automatic sale. Which proposals
   Claude surfaces and endorses is the Mastermind's part (its §7).

### 3.8 Deployment by tail class, and the "missing income" answer (OR5; E10)

**Layer 1, the envelope (§3.4), decides whether there is headroom.** Today there is none.

**Layer 2 deploys headroom by the instrument's tail class:**

| Class | Members | Regime response inside the envelope |
|---|---|---|
| `index_1x` | QQQ, SPY (VOO/IVV as fallback) | `regime.csp.budget_multiplier_by_class.index_1x: {normal 1.0, cautious 1.0, stressed 0.8, crisis 0.5}` in place of {1.0, 0.7, 0.4, 0.1}. **Record-only until a wheel-faithful replay** (roll or assign at the loss line, per 2026-10-02) on S&P 1991–2026 and the 17-month panel agrees in sign under both valuations |
| Single names and sector funds | everything else | Unchanged: idiosyncratic and slow-bear tails |
| Leveraged | TQQQ, SOXL | The sleeve only (§3.5) |

The evidence for the index class is in §2.4. Elevated-IV entries beat calm ones under hold and under
a 2× buy-back line, and calm index puts with a stop earn about nothing. The current throttle cuts
index puts hardest exactly when they pay best. It stays right for single names and leveraged funds.

**Limit levels rise only on stabilisation.** After the glide reaches its target, S10, U_ew or the
sleeve cap rise only on all three of:

- the market-level bottoming signal: a VIX spike ≥ 25% within 10 sessions, now ≥ 15% off its peak,
  and the index ≥ 1% above its 10-session low;
- the survivability harness passing at the new level;
- an operator ruling.

Stabilisation is a tail cap, not an edge source. On S&P history it halved the worst trade at VIX ≥ 25
(−23.7% → −12.8%) without raising the mean, and it discarded about 80% of elevated-IV entries [M,
S2R]. That is why it governs limit raises, not the class throttle.

**Idle cash.** None today: cash is $58.7k, about $17k after the Nov 13 NVDA assignment. If idle cash
appears:

- IBKR credits interest on cash balances [U: rate and tiers not checked], and cash behind a CSP keeps
  earning it, so a put's increment over cash is only its variance premium.
- T-bill ETFs add little over that interest.
- US-domiciled ETFs carry US-situs estate exposure for a Singapore non-resident; directly held T-bills
  or cash are simpler. This is general information, not tax advice.

**"Am I sitting on too much cash and missing income?" The numbers.**

| Question | Answer |
|---|---|
| Is there idle cash? | No. Cash 9.0% of NLV, stock 93.7%, puts $207.7k against $58.7k of cash. The CSP budget ran a **median 98%** of its limit Oct 13–Nov 10 and peaked at 114% |
| What did the income layer earn? | October sold $38.0k of put premium. Realised put P&L since the first wheel fill is **−$10.2k** (IBKR's column), and the assigned shares are marked about −$40k below their strikes (O2R). Gross premium is not income |
| What would a reserve cost? | S&P put-writing earned **+0.48%** of strike per ~month held to expiry and **+0.07%** with a 2× buy-back line: about 5.7% or 0.85% a year over cash [M]. Holding back 10% of NLV ($65k) forgoes **$0.6k–$3.7k a year** |
| What is at stake in not repairing? | Each point of S10 is **$6.5k per −10% index move**. Today's 22.0% against the 15% target is about **$45k of extra loss in one −10% move** |
| Where does income come from during repair? | Covered calls on the held stock: about $12.6k a month of premium at today's IVs [M], $4.0k of it allowed by today's basis floor. That income **reduces** risk; new puts on a 94%-long book add it |
| When does put income come back? | When repair brings S10 under L(t). Then the index class is not cut in stress, which is the one place the evidence says leaning in pays |

### 3.9 Claude's place (OR6)

Nothing here changes the core invariant. The Rules Engine and `src/spreads/risk.py::validate` remain
the only gates.

| Decision | Class | Who |
|---|---|---|
| S10 and U_ew levels, the glide, the sleeve cap, class multipliers, betas, exposure weights, the stabilisation test | envelope | **The operator only.** Never a rung |
| `claude_cut` lowering any CSP, leveraged or index | reducing | R1 (exists) |
| Choose, from a Python-built equal-exposure menu, an item no riskier than the baseline on every measure **including G10 and P20** (e.g. the index lot or skip when the baseline is a sleeve lot) | reducing | R2 |
| **The allocation lever: choose leveraged vs unleveraged inside the envelope** (the leveraged item fails G10/P20) | changing | **R3**, inside the sleeve cap, after the envelope is live and the harness passes |
| Strike and expiry from a gate-passed chain menu | changing | **R4** |
| The spreads picker (menu includes an inside strike) | changing | **R4-type, grandfathered in paper, record-only in any live plan.** Its record is evidence for the spreads book and a pilot of the Mastermind's measurement machinery; never evidence for a wheel rung |
| Which book-repair proposals to surface and endorse | a selection; a human taps | Mastermind §7 (R5 classes) |
| **Revision 2.** Whether the hedge bridge exists; its budget, instrument, structure family, schedule, size rule, stress block, monetisation rule and review gate | envelope | **The operator only**; Python runs it (§3.10) |
| A daily "would hedge" stance; tap-only "buy puts now" and "cash in / roll down" proposals; a shape choice at a scheduled roll at fixed spend | R0; tap; reducing within the programme's spend | Mastermind §10.7 (R5-H) |
| Claude's paper put budget: when to spend one fixed unit, and on which Python-built menu item | **changing (cost)**; reducing on every risk measure | Mastermind §10.7 (**HP**): paper only, record-only in live, no S10 credit |
| Directional ideas | outside the ladder | Mastermind §10.8 (Track D, shadow only) |

R0 now: shadow every sleeve trigger, every band-relevant day and every equal-exposure menu (index
lot, leveraged equivalent, index put vertical, skip), each item shadow-valued.

### 3.10 Index hedges: the bridge (revision 2; OR9, OR12)

#### 3.10.0 Adjudications where the reviewers still disagreed

| Point | O3 / O3R | S3 / S3R | Decision | Why |
|---|---|---|---|---|
| Budget | ≤ 0.35% of NLV per rolling 30 days; ≤ 1.25% for the bridge | Pilot 0.25% a month, 2% a year | **Net premium ≤ 1.0% of NLV₀ over the bridge, accruing at 0.25% a month with a two-month opening allowance; open premium at cost ≤ 0.6%** (§3.10.3) | Disagree with both on the unit. A rolling-30-day cap on premium paid is breached on day one by any 60–120-day put (one of ~2 points costs ~0.4–0.6% of NLV up front), so it pushes the programme to 30-day far-OTM puts: the instrument both reviewers called the optimiser trap. Net premium, accrued, fits the tenor. 1.0% over the ~4 months the bridge holds protection (13 weeks plus the last put's run-off) is the operator's ~0.25% a month |
| Size rule | min(budget, S10_gross − L(t)) | min(budget, λ × (S10_gross − target)), λ ≤ 0.5 | **S3R's, λ = 0.5** | L(t) starts at today's S10 rounded up, so O3R's rule hedges nothing on day one. Measured against the target, the hedge shrinks as repair works: the conditional sunset OR9 asks for |
| Self-funding roll under the stress block | Net debit ≤ 0.1% of NLV | Rolls exempt | **Net debit ≤ 0, contracts not increased** | OR9 says self-funding. A roll that adds premium in stress is new spend at the worst price (0.20 on the dollar, §2.6) |
| Instrument | XND first, if ≤ 8% of mid and ≥ 15 contracts displayed on ≥ 80% of captures | XND only on a measured bar (≤ 8% median, ≥ 30 executable), else QQQ | **Capture both for 20 sessions in E0. XND if its quote bar passes and its all-in cost per protected point is ≤ 1.5× QQQ's; else QQQ** (OR12) | Neither tied the bar to cost against the alternative. XND's structural gains (cash settlement, no netting, no margin channel, no E8/E9 conflict) are worth a premium, but not any premium: at the one ~30% chain-average spread seen, friction on 10–15 contracts could exceed a month's carry |
| QQQ fallback vs E8/E9 | Accept S3's disjointness | QQQ out of `actively_wheeling` during the pilot | **E8 stands as ruled. While a QQQ hedge is open the Rules Engine refuses any wheel QQQ opening, and the hedge refuses to open while the wheel holds any QQQ short or share; E9's QQQ lot is inert in that window** | S10_gross above L(t) blocks new CSPs during the bridge anyway, so the cost is nil. A rule, not a universe edit, leaves E8 intact when the bridge ends |
| Coverage | −26% → −19.5% at the low (a quarter); ~15% by Nov 11 | 25–30% at the low; 5–13% on Nov 11–12 | **About a quarter at the low; 5–17% on Nov 11–12 by strike, about a tenth** (§2.6) | Re-run: S3's 95/85 spread delivered 2.9 points of 17.7 on Nov 11 (16%), outside S3's range; O3's 15% is the top of the range, not its middle |
| Tech scenario | T20, then withdrawn for S-QQQ / S-SMH from positions | S-QQQ / S-SMH, then withdrawn for T20; T20 display only | **T20 and S-SMH: display, harness, credit grid. Not limits; a 3-point trigger returns T20 to the operator** (§3.4.3) | T20 needs no second per-name beta (S3R) and uses a config list that exists. At 23.7% against S10's 22.3% a T20 limit would not bind first, and it duplicates the group cap |
| Monetisation | Take half at 3× cost when the index is ≥ 1σ₆₀ down | 2× take-profit, replayed first | **None active until the E1 replay rules one; hold to the roll date meanwhile.** 2× is the leading candidate | S3R's replay: 3× was worse than holding on the 95% put. The multiple is fragile, so it is ruled on a replay, not chosen in a spec |
| Who owns the programme | Operator ruling + a fence; not a core-invariant exception | A new written exception even with no Claude in it | **O3R's** | The invariant concerns LLM involvement and the Rules Engine being the only path. A Python programme gated by `validate_hedge` twice breaks neither. The written exception is Claude's paper budget (Mastermind §10.7) |
| Minimum build | Own `hedge_*` tables so the 20+ SELL-is-open sites never see a hedge row | 13 items incl. a hedge manager and a `reconcile_external_closes` skip | **The union, minus S3R's seven-builder reporting carve-out** (§3.10.10) | O3R is right that separate tables make the wheel-table carve-out unnecessary. But separation *creates* the reconciliation hole: a hedge order absent from `OrderRow` drops out of the own-order skip (§2.6), so S3R's `hedge:` skip is required. Broker-ledger builders still see hedge executions and filter `book="hedge"` |
| Stress trigger | VIX ≥ 25 or VXN ≥ 90th percentile | Same, or either up > 30% in 5 sessions | **VIX ≥ 25 (ruled) or VXN ≥ its 1-year 90th percentile (recommended)** | The instrument is priced off VXN. The 5-session rise rule had no evidence offered for it |

#### 3.10.1 What the hedge is for, said plainly

- **Trims and covered calls are the main repair.** Per unit of risk removed, a trim costs about half
  what a put costs (§2.6; Israelov). At the Nov 5 low a hedge sized for 7 points of S10 cut about a
  quarter of the loss, and a proportional trim cut more, at both dates.
- **A standing hedge does not pay here.** On this panel a rolled QQQ hedge lost 5.6–10.6% of its
  notional a year, and 0 of 8 rolls won [M].
- **What the bridge is:** a small cushion against a second leg down while repair works, for shares
  the operator chooses not to sell (the SOXL basis, AMD/GOOGL/NVDA at about 65% of NLV, the manual
  stock). It is the second-best answer to that choice, not a source of return.
- **It earns no envelope headroom** (§3.10.7). Hedge-funded CSP headroom is at best break-even (§2.6).

#### 3.10.2 Life: a bridge, a review gate, a conditional sunset (H2)

- **Start:** on the operator's ruling, after the E2 envelope is live, the §3.10.10 build passes its
  tests and the instrument is chosen (§3.10.4).
- **End:** at E4, when L(t) reaches the target. A late start means a short bridge. From E4 nothing
  new is bought or rolled; the open position is sold at its roll date.
- **Conditional sunset inside the bridge:** the size rule (§3.10.5) is measured against the 15%
  target, so the hedge shrinks to zero as repair closes the gap, whatever the date.
- **The review gate:** at E4, or earlier if the size rule has been zero for 20 sessions, the operator
  reads a one-page record: premium spent, value returned in each down leg, and what a trim, the
  schedule at equal spend and no hedge would have done, beside the E1 replay. **The default is off.**
  Continuing needs a fresh ruling, under the same rules, at no more than 2% of NLV a rolling year.

#### 3.10.3 Budget (H3)

Fixed terms (Mastermind §3 line 3): NLV₀ is NLV on the bridge's first day, converted to dollars once.

| Cap | Level |
|---|---|
| Net premium over the bridge (paid, less received from sales and cash settlement) | **≤ 1.0% of NLV₀** (~$6.5k today) |
| Pace | Cumulative net premium ≤ 0.25% of NLV₀ × (months elapsed + 2), under the cap above |
| Open premium at cost | ≤ 0.6% of NLV₀ |
| On renewal, if ruled | ≤ 2% of NLV per rolling 12 months, hard |
| Its line | Its own, outside the CSP budget. Claude's paper put budget is a separate line (Mastermind §10.7) |

At today's prices this buys about **1.5–2.5 points of S10 protection** [M]: a third of the 7-point
gap at most. The hedge cushions the repair; it does not do it.

#### 3.10.4 Instrument (OR12; H4)

| Instrument | Verdict | Reason |
|---|---|---|
| **XND** (Nasdaq-100 micro) | **First, if the E0 capture passes** (§3.10.0 bar) | Right factor (the QQQ index, R² 0.94). Cash-settled and European: no exercise into anyone's shares, no early assignment of a vertical's short leg, no T−2 rule. Never the same contract or underlying as any other book, so "book = underlying" attribution works unchanged and no same-underlying margin offset can widen the CSP budget. Liquidity unmeasured (§2.6) |
| **QQQ** | **Fallback** | Right factor; 97.8% of put quotes ≤ 10% of mid (§2.2). American and physically settled: **an ITM long put at expiry auto-exercises**, selling wheel shares or opening a short stock position. So: closed by T−2 sessions, with a lapse instruction (`IB.exerciseOptions`, action 2; paper behaviour [U]) if that close fails; contract-clash rules both ways; no wheel QQQ shorts or shares while it is open (§3.10.0); attribution by `hedge:` orderRef and `conId` |
| SPY, SPX, XSP | **Rejected** | Wrong exposure: R² 0.77, and an SPY put delivers about a third of its S10 credit under T20 (§2.6). The spreads fence: all three are `book_underlyings` today; after E3 SPX/XSP stay there and `books.py` (`is_spreads_underlying`, `_DAILY_ROOTS`) would tag a hedge as spreads; SPY goes to the wheel. SPX is ~$763k a contract (1.2× NLV). SPY settles in shares |
| NDX | Rejected | ~$2.8M a contract (4.4× NLV) |
| SMH / SOXX | Not in v1 | SMH put quotes ≤ 10% of mid only 38.2% of the time (§2.2); premium ~2× QQQ's; SOXX has no history. S-SMH is displayed |
| VIX calls | **Rejected** | Contango carry; the damage was a slide (VIX 16.4–27.2 Oct 22–Nov 12, one spike), not a spike; no tech factor; a second pricing model on a forward |
| Index collars with a short index call | **Rejected** | The call leg is a naked short index call against single-stock longs, which the Rules Engine refuses (no naked short legs, ever). It sells cheap index calls to buy rich index puts and caps the rebound (SOXL +62% in four sessions off Nov 5) |
| Single-name protective puts | Out of scope | §3.7 |

#### 3.10.5 Structure, size, schedule, monetisation (H5)

- **The menu family:** outright puts or put verticals on the chosen instrument; long-leg delta
  0.15–0.30 (about 90–95% of spot); 60–120 DTE at open, 90 targeted; a vertical at least 10% of spot
  wide. No ratio, calendar or diagonal; no naked short leg.
- **The default item** is the one with the best *minimum* protection per premium dollar across
  {S10, S20, T20, G10, P20}. The floors (DTE ≥ 45, long-leg delta ≥ 0.15) stop any optimiser, Python
  or Claude, from picking the short-dated far-OTM put that buys S10 cheaply and decays to nothing on a
  slow slide (S3 §1.2).
- **Size:** points protected = min(budget-limited points, 0.5 × max(0, S10_gross − 15%)). The hedge's
  delta never exceeds 50% of the book's beta-weighted delta, so the hedge never turns the book short.
- **Schedule, not trigger:** buy on the bridge's first day; roll at ≤ 30 DTE remaining (sell the old
  item, buy the current default); one position at a time.
- **Monetisation:** none until the E1 replay rules one (2× cost is the leading candidate). Until then
  the hedge is held to its roll date. Early closes happen only by an operator tap (including
  Claude's tapped "cash in" proposal, Mastermind §10.7).

#### 3.10.6 The stress block (OR9; H6)

- **No new hedge size** on a session after a VIX close ≥ 25 (ruled) or a VXN close at or above its
  one-year 90th percentile (recommended).
- **A self-funding roll is still allowed:** net debit ≤ 0 and no more contracts. Otherwise the hedge
  is held, and closed by T−2 on the QQQ route.
- An account halt or a slow-breaker trip also blocks new size; a self-funding roll is still allowed.
- **Why:** a 95% put bought at VIX 25–35 returned 0.20 on the dollar against 0.43–0.70 in calm
  states; bought on Nov 5 it lost 66–79% in four sessions; the same hedge cost about 55% more on
  Nov 11 than on Oct 13 (§2.6). "Relevant" arrives after the price does.
- The block applies to the programme and to any tapped "buy puts now" proposal, which draws on the
  programme's budget. **Claude's paper put budget is exempt**, by the decision and for the reasons in
  Mastermind §10.7.

#### 3.10.7 Envelope accounting (OR9; H1)

- **Admission reads S10_gross** (§3.4.1): no long option, from any source, creates S10 headroom.
  S10_net is display and harness only.
- **U_ew** counts stock and short-put strike, so a long put adds nothing to it and earns no room. The
  spec states it so that no later edit adds a credit.
- **Collateral, sector, group and tech-linked caps:** the hedge book is excluded.
- **Breakers:** hedge marks enter the daily loss leg **net**, read through `src/common/hedge_view.py`;
  a trip card shows the loss by book. The drawdown legs already see the hedge through NLV.
- **The margin channel:** IBKR may margin a long and a short put on one underlying as a spread [U],
  lowering maintenance margin and raising EL, which the CSP budget reads (`capital.py:93-103`). XND
  never pairs with a wheel position; the QQQ rule (§3.10.0) closes the channel on the fallback.

#### 3.10.8 Data: live greeks, a sanity check, captured quotes (OR9; H7)

1. **Gates read live greeks** (§3.4.1), at decision and at send time.
2. **An IV sanity check on `iv_history` writes:** index ETFs against a ratio band to the VIX family
   (QQQ's normal ratio to VXN is about 0.87; Nov 5 was 0.38), single names against their own
   20-session median. Out-of-band rows are flagged, not used, and raise a data alert.
3. **Leg-quote capture from E0:** bid, ask and size for every hedge menu item's legs (XND and QQQ),
   twice a session at fixed times, into `hedge_quotes`, inside the market-data line budget. **All
   shadow valuation** (the programme, every menu item, Claude's picks, Track D) uses captured mids with
   the measured half-spread. Black-Scholes is a labelled fallback only.
4. **SPY IV capture restarts in E0** (it stopped on Oct 5).

#### 3.10.9 Book, attribution and fence (OR12; H9)

- **The book:** `book="hedge"`. Order refs `hedge:<id>` (the programme) and `hedge:claude:<id>`
  (Claude's paper budget), written before `placeOrder` (the value-book pattern).
- **Underlying-level disjointness:** `hedge.underlyings` in config. For XND, `Config` refuses any
  overlap with `universe.yaml` or `spreads.book_underlyings` (the `_spreads_isolated` pattern). On the
  QQQ fallback (a universe name) it is the Rules-Engine rule of §3.10.0 instead.
- **Contract-level disjointness, both ways:** `validate_hedge` refuses a buy in any contract another
  book holds; the Rules Engine refuses a wheel short in any contract the hedge book holds
  (`hedge_contract_clash`). IBKR nets same-contract positions across clientIds.
- `books.py` gains `is_hedge_underlying` and `is_hedge_order_ref`; `get_positions()` drops hedge
  positions by default (by underlying for XND, by `conId` through `hedge_view` for QQQ); ledger
  ingest tags `book="hedge"` by underlying and by the `hedge:` ref; `wheel_shares` W is unaffected.
- **Placement and fence.** `validate_hedge` lives in the Rules Engine (`src/engine/risk_engine.py`),
  the one path to an order. The menu, size rule, schedule, executor wrapper and lifecycle live in a
  deterministic `src/hedge/` package run by the trading process on its own clientId. It imports no
  enrichment (`src.claude`, `src.news`, `src.value_ai`, `src.spreads_ai`, the enrichment analytics);
  `src.spreads` and `src.value` do not import it; Claude reaches it only as a menu letter through
  `plan_view` (Mastermind §12). `src/common/hedge_view.py` (`mode=ro`, plain SQL, imports only
  config) is everyone else's view. Only `src/hedge/` writes hedge rows. Enforced by
  `tests/test_hedge_fence.py` (`ast` imports, a `sys.modules` check, the writer test). CLAUDE.md gains
  a hedge-fence section when it is built.

#### 3.10.10 The minimum buy-to-open build (H9)

Hedge-only. It belongs to this spec's phases: items 1–2 in E0, the rest in E2.

| # | Item |
|---|---|
| 1 | **Quote capture** (§3.10.8) and the E0 instrument measurement. No order path needed |
| 2 | **S10_gross / S10_net, T20, S-SMH** in the shock module, with live greeks for gating |
| 3 | `Strategy.HEDGE` and a `HedgeCandidate` schema: legs, Python-computed debit, max loss and scenario credits |
| 4 | **`validate_hedge`**, pure, no LLM, at decision time and again at send time on a fresh quote: the budget caps; max loss = debit; no naked short leg; underlying in `hedge.underlyings`; contract clash; the QQQ-route rule; DTE and delta windows; quote ≤ 8% of mid, two-sided and fresh; the stress block with its self-funding carve-out; halt; hedge delta ≤ 50% of book beta-delta; refuse a `hedge:claude:` order under `LIVE_TRADING=true`. Scoped out of the income gates (ROC, yield, IV rank, IV/RV, `min_credit`), as rolls are |
| 5 | `build_hedge_order`: BUY `LimitOrder` at mid; a BAG for a vertical (a neutral copy of the roll-combo shape, not an import from the fenced `src/spreads/`); a chase with `reprice_limit("BUY", ceiling=approved debit × 1.05)` |
| 6 | `execute_hedge`: `qualifyContractsAsync` for every leg, `req_fresh_mkt_data`, the order ref before `placeOrder`, partial fills and unconfirmed cancels (the Nov 10 spreads lesson) |
| 7 | **Own tables** in the trading DB (`hedge_programme`, `hedge_orders`, `hedge_fills`, `hedge_quotes`, `hedge_marks`), written only by `src/hedge/`. The wheel's `orders` / `fills` never receive a hedge row, so the 20+ sites that read SELL as an open are untouched |
| 8 | **A hedge manager** in the trading process: schedule, roll, the T−2 close and lapse instruction (QQQ), cash settlement (XND), monetisation once ruled. Every existing monitor skips long options |
| 9 | **`reconcile_external_closes` skips an execution whose order ref starts `hedge:`** (one line and a test) |
| 10 | Attribution (§3.10.9). Builders that read the broker ledger filter `book="hedge"`; a small read-only `src/reporting/hedge.py` reports hedge P&L |
| 11 | Capital and breakers: a test that `capital.py` counts no hedge collateral and sees the debit in cash; the daily leg net through `hedge_view`; halt blocks new size |
| 12 | Fence tests and docs per CLAUDE.md: ARCHITECTURE.md (new package, models, `hedge_view`), `config/examples/risk_limits.yaml` `hedge:` block, SETUP.md if operator-facing, STATUS.md, the CLAUDE.md hedge-fence section |

**Out of v1:** directional orders, single-name protective puts, SMH, VIX options, collars, and any
BUY-open arm in the wheel's reporting builders. Whether the trade ledger's FIFO pairs a long open and
close correctly (`trade_ledger.py:834` labels a buy "Long") is a test to write, not an assumption [U].

#### 3.10.11 The programme's own record

Measured and shown, never promoted, because the bridge will see one or two down legs at most:

- premium per S10_gross point-day protected, beside the trim and covered-call costs;
- the cover ratio in each pre-registered down leg (the index ≥ 1σ₆₀ below its 60-session high), at
  the trough and at exit, against no hedge, the trim that removes the same S10, and always-on at equal
  spend;
- execution against mid, and the rolling 60-session R² of NLV on the instrument.

The decision to continue is made on prior evidence and the operator's utility (§3.10.2). Claude's
hedge records are measured under Mastermind §11.11–11.12.

## 4. Phasing

| Phase | Content | Gate to the next |
|---|---|---|
| **E0. Stop the bleeding, measure** (no new authority; risk-reducing or display only) | Spreads: §3.2 a, b, c, e, f and h (calendar, halt link, daily-leg coupling, NLV caps, cost standard, shadow mode). Wheel: leveraged CSPs off (`csp_mode: drawdown_only` with the sleeve closed); `vrp_waiver` off for leveraged names; UPRO and DPST out. S10, S20, G10, P20, U_ew and L(t) computed daily and shown (brief, web, Telegram), not yet enforced. The discretionary-buy display. SOXX into price/IV history. Docs per the CLAUDE.md table. **Revision 2:** S10_gross / S10_net (the loophole closed before any buy path), T20 and S-SMH displayed; live greeks for gating; the IV sanity check; SPY IV capture restarted; XND and QQQ hedge-menu quote capture (20 sessions) | Operator adopts this spec and rules E1, E2, E8, H1, H7 |
| **E1. Backtests and replays** | The spreads ThetaData backtest (§3.2 g). SPXW shadow cost measurement (§3.3). The survivability harness on the deterministic envelope (§3.4.6). The D14 replay (§3.7). The tech-linked cap and stacking-rule backtest (§3.4.4). The leveraged-sleeve replay (§3.5). The wheel-faithful index-class replay (§3.8). **Revision 2:** the hedge replay (default item vs none vs always-on vs trim-equivalent, the monetisation candidates, on S&P 1991–2026, NDX 2002–2026 and the 17-month panel, priced from captured quotes where they exist); the XND/QQQ cost comparison; T20 against a QQQ-beta-scaled variant | Each replay's report read by the operator; rulings E3–E7, E9, E10, E12, E14, E15, H4, H5, H8 |
| **E2. Envelope live (paper)** | S10 with the glide, and U_ew unconditional, enforced. The tech-linked cap and stacking rule if supported. The slow breaker spanning books. The index class. The leveraged sleeve. Tap-only repair proposals: CC overlays at the ruled floor and the leveraged carve-out; trims and de-lever once their order paths exist (each its own plan task). The index-class multiplier stays record-only until its replay agrees. **Revision 2:** the minimum buy-to-open build (§3.10.10 items 3–12), then **the bridge hedge in paper** on ruling H2 (its own plan task; it starts when the build passes, whatever week of the glide that is) | Harness passes on the live envelope; ≥ 20 sessions with no envelope defect |
| **E3. Spreads to SPX, SPY freed** | Only if the backtest passed and the SPXW cost condition holds (E3). The fence task of §3.3 as one change, at a flat-book cutover. Then SPY joins the index class | Operator ruling E3 |
| **E4. Glide complete** | L(t) reaches the target. Levels change thereafter only by §3.8's stabilisation rule. **Revision 2: the bridge ends** (nothing new bought or rolled); the review gate of §3.10.2 | The review: default off |

**Sequencing with the Mastermind.**

- **Mastermind Phase 0** (prompt cleanup) changes no risk and may run beside E0–E1.
- **Mastermind Phase 2 onward** waits for E2, so that every R0 record is made against the repaired
  envelope.
- **Mastermind risk-changing rungs** (R3, R4, auto R5, X2) need E2 complete and the harness passing.
- **The R3 allocation lever** also needs the leveraged sleeve live.
- **Revision 2.** Claude's paper put budget (Mastermind HP) needs the E2 buy-to-open path and the
  Mastermind's Phase 3 brief. It is not tied to the bridge and may start after the bridge has ended;
  it then uses the same `src/hedge/` order path and instrument. The forward scoring of the news
  verdicts and the spreads plan's bias (Mastermind Phase 0) needs neither and starts now.

## 5. Prior rulings this spec touches

| Ruling | Source | This spec |
|---|---|---|
| TQQQ/UPRO/SOXL as deliberate `would_own` exceptions (2026-08-27); DPST (2026-09-29) | `universe.yaml:35-38, 68-73` | **Partly reversed (OR4):** UPRO and DPST out; TQQQ and SOXL kept, drawdown sleeve only |
| Decision 32 / ruling 35: the leveraged per-trade ceiling with a floor of 1 lot | `risk_limits.yaml:259-264`; `regime_limits.py:166-186` | **Changed:** 0 outside the sleeve |
| 2026-10-22: a name-level bottoming lot is exempt from the fair-value floor | `regime_limits.py:274-307` | **Narrowed:** not for leveraged ETFs |
| 2026-10-14: leveraged ETFs "roll where possible, else assign" | `intraday.py:532` | Stands |
| 2026-10-02: a would-own short gets a defensive roll proposal at the loss line, not a loss-taking close | `triggers.py:247-276` | Stands. It is why the index-class replay must model rolls and assignment, not stops |
| Regime budget multipliers {1.0, 0.7, 0.4, 0.1} for every name | `risk_limits.yaml:183` | **Changed for `index_1x` only**, record-only until its replay |
| Spreads plan rollout rule 3: paper only after a positive backtest | plan line 707 | **Reinstated** (§3.2 h) |
| Spreads plan: SPY now, SPX "if the per-trade cap rises to roughly $5,000" | plan line 560 | **Superseded:** SPXW 25-wide on a measured cost condition at the new 0.5%-of-NLV cap |
| `book_underlyings: [SPY, SPX, XSP]` and the CLAUDE.md spreads-fence text | `spreads.yaml:12`; CLAUDE.md | **Changes at E3** if the operator rules so |
| N18: `min_strike_vs_basis: 1.00` | `risk_limits.yaml:15` | **Put to the operator (E12)** by replay, with a leveraged class floor |
| Revision 1 of this spec: "every position fully revalued" in S10; a hedge as "a 30–90-day index put spread under Mastermind R5"; "protective puts later" | §3.4.1, §3.1, §3.7 | **Revision 2:** admission reads S10_gross (no long option counts); the hedge is the §3.10 Nasdaq-100 bridge run by Python; single-name protective puts out of scope |
| E8 / E9: QQQ into `actively_wheeling` and the index class | §3.6 | **Stands.** On the QQQ hedge fallback only, a Rules-Engine rule suspends wheel QQQ openings while a QQQ hedge is open (§3.10.0) |
| The core invariant: Claude never places, sizes or gates an order | CLAUDE.md | Unchanged by the bridge (Python's). Claude's paper put budget is a new written exception, in the Mastermind §10.7 |

## 6. Open decisions for the operator

These are numbered E1–E15 so they do not collide with the Mastermind's D1–D21. The Mastermind's
D13 and D14 now point here.

| E | Question | Recommendation | Dissent / note |
|---|---|---|---|
| **E1** | Spreads mode until the backtest passes | **`shadow`**, the plan's own rule. Paper fills are not evidence of live fill quality, and paper losses lower excess liquidity in the same account | Keeping paper at the new caps would continue fill sampling; the reviewers called that sample unrepresentative of live |
| **E2** | Spreads caps and calendar | 0.5% of NLV per trade, 1% a day, −2% a month (human reset); EL floor 40% of NLV in place of $10k; no entries on FOMC decision days; 08:30 prints unblocked | The levels are "about" in OR1; the EL floor level is new (EL is 71.5% of NLV today) |
| **E3** | The spreads underlying, and SPY | After the backtest and a 2–4 week shadow cost measurement: SPXW 25-wide, 1 lot, if its all-in cost per $1k of max loss ≤ SPY's; then free SPY for the wheel with the §3.3 fence changes. If SPXW fails: XSP for settlement only, or stay on SPY | Fallback for the wheel if SPY stays reserved: VOO/IVV after a liquidity measurement, or no S&P sleeve |
| **E4** | The shock budget | S10 by full revaluation, Blume betas, leveraged at leverage × index β; target **15%** at SPY −10%; start at the measured level on adoption (≈ 22%); linear weekly glide over **13 weeks**; report S20 | Accept that no new CSP opens until trims or call-aways create room: covered calls alone reach about 20% |
| **E5** | The gross backstop | U_ew unconditional; **1.25** target, gliding from 1.36; ITM puts at strike | O2R: 1.0 (account-level cash-secured). S2: 1.5. Adjudicated in §3.0 |
| **E6** | The gap measures | G10 and P20 as classification and display measures; not limits | Making them limits would duplicate the sleeve cap |
| **E7** | The leveraged sleeve | §3.5 conditions; vol-scaled drawdown (1.0 σ₆₀); a sleeve delta window of 0.15–0.20 (load check changed); 3% of NLV aggregate, which is one lot at a time at today's prices. **Revision 3 (OR13–OR16):** the LES tier, 3% on a pullback and 6% with the breadth washout, half under the 200-day (§3.5.1) | Alternative: 3% per name with 2 lots (≈ 6% aggregate). OR4 reads as aggregate |
| **E8** | Universe | UPRO, DPST out; TQQQ, SOXL out of `actively_wheeling`; QQQ in; SOXX dip-watch for liquidity; SPY after E3 | — |
| **E9** | The index class | One lot ≤ 15% of NLV, {QQQ, SPY}; VOO/IVV only as fallback | O2R: 12% with SMH |
| **E10** | Tail-class deployment | `index_1x` multipliers {1.0, 1.0, 0.8, 0.5}, record-only until the wheel-faithful replay agrees in sign under both valuations | — |
| **E11** | "Cash reserve" and Portfolio Margin | Retire the reserve as a policy idea; `cash_reserve_pct` stays a margin buffer; no PM while the budget derives from EL | — |
| **E12** | Book repair floor (was Mastermind D14) | Rule `min_strike_vs_basis` by replay; a leveraged class floor of none at delta ≤ 0.25, tap-only first; de-lever and trims as tap-only proposals once their order paths exist | S2 would apply the leveraged carve-out now, unconditionally |
| **E13** | Discretionary buys | Show S10, U_ew and headroom before and after every manual buy; no attempt to gate TWS orders | — |
| **E14** | The slow breaker (was part of D13) | 20–30-session window on account NLV; on a trip: demote risk-changing rungs, block risk-changing levers, scale the CSP budget, stop spreads entries; human reset | Threshold set after the E1 replay |
| **E15** | The tech-linked cap and stacking rule (was part of D13) | Leverage-weighted group cap; stacking rule; both only if the backtest against the `claude_cut` rows supports them | — |

### 6.1 Revision 2: H1–H10 (long options, this spec's part)

Numbered H so they collide with neither E1–E15 nor D1–D21. The Mastermind owns H11–H16.

| H | Question | Recommendation | Dissent / note |
|---|---|---|---|
| **H1** | Admission on S10_gross (the loophole) | Adopt in E0, before any buy path: admission tests read S10_gross (no long option, from any source); S10_net is display and harness only | None. Both reviewers converged |
| **H2** | The bridge | Yes: Python-run, from the E2 ruling to E4; conditional sunset through the size rule; review gate at E4 with the default off; renewal ≤ 2% of NLV a year by fresh ruling | S3 first proposed a standing programme; withdrawn in S3R on the 0-of-8 backtest |
| **H3** | Budget | Net premium ≤ 1.0% of NLV₀ over the bridge; pace 0.25% × (months + 2); open premium at cost ≤ 0.6%; own line | O3R 0.35% / 30 days and 1.25%; S3R 0.25% a month and 2% a year. Adjudicated in §3.10.0 (unit of the cap) |
| **H4** | Instrument | XND if the 20-session E0 capture passes (median quoted spread ≤ 8% of mid on the default item's legs; displayed size ≥ the bridge's contract count on ≥ 80% of captures; all-in cost per protected point ≤ 1.5× QQQ's); else QQQ under §3.10.0's rule. SPY/SPX/XSP, NDX, VIX calls and index collars rejected; SMH not in v1 | XND liquidity is unmeasured; the one third-party snapshot (~19.9K total OI, ~30% average chain spread) is a warning |
| **H5** | Structure, size, schedule, monetisation | §3.10.5: 60–120 DTE, long delta 0.15–0.30, outright or ≥ 10%-wide vertical, default = best minimum protection per dollar over the scenario grid; size min(budget, 0.5 × (S10_gross − 15%)); roll at ≤ 30 DTE; hedge delta ≤ 50% of book beta-delta; no monetisation rule until the E1 replay | The 2× take-profit is the leading candidate; 3× was worse than holding |
| **H6** | The stress block | No new size after a VIX close ≥ 25 (ruled) or VXN ≥ its 1-year 90th percentile (recommended); self-funding roll = net debit ≤ 0, no added contracts; halt and slow breaker also block new size | O3R allowed a 0.1%-of-NLV debit as "self-funding"; not adopted |
| **H7** | Data | Gates on live greeks; the `iv_history` sanity check; leg-quote capture from E0; SPY IV capture restarted; shadow valuation on captured mids | None |
| **H8** | Tech scenarios | T20 and S-SMH as display, harness and credit-grid measures; not limits; T20 returns to the operator as a candidate limit if T20 − S10 > 3 points | O3R preferred S-QQQ / S-SMH from positions; S3R preferred T20. Adjudicated for T20 |
| **H9** | Book, fence and build | `book="hedge"`, `hedge:` and `hedge:claude:` refs, underlying and contract disjointness, `hedge_view`, `src/hedge/`, own tables, the reconciliation skip, `tests/test_hedge_fence.py`, a CLAUDE.md hedge-fence section; the §3.10.10 build | None on substance; the build list is the union adjudicated in §3.10.0 |
| **H10** | Any future headroom credit for a hedge | **None in this spec.** A later ruling, after the review gate, would need at least: credit = the minimum over {S10, S20, T20, G10, P20}; a haircut by the 60-session R² of NLV on the instrument; hedge DTE ≥ the longest admitted position's DTE + 10 sessions; ≤ 2 points; no lift while it supports open risk; a harness pass | Both reviewers: zero credit in v1. Hedge-funded headroom is at best break-even (§2.6) |

### 6.2 Rulings, 2026-11-14

The operator **adopted every recommendation in E1–E15 and H1–H10** as ruled, confirming E4 as written, E7 at 3% of NLV
aggregate, and H6 with the VXN 90th-percentile block. The data-gated rulings turn on automatically in paper on a PASS,
stay record-only in live, and can be reversed by CLI. The E3 cutover only notifies. The pass/fail criteria, the
thresholds the plan set itself, and the code facts that correct §3.4.2 (C1–C8) are in the implementation plan,
`docs/superpowers/plans/2026-11-14-risk-envelope.md` (its Rulings section).

**Revision 3 (same day), OR13–OR17:**
- The Leveraged Entry Signal (§3.5.1, evidence §2.7) changes E7. The sleeve is now LES-tiered at 3% / 6%,
  with half the tier under the 200-day, and adds paper share buys of TQQQ and SOXL held until the trend breaks.
- The plan carries LES as rulings L1–L8 and Tasks 10a, 23, 29 and 32a.
- E0 adds the breadth oscillator and records the LES state each session. E2 adds the share-buy path.

## 7. Unverified, and open research

- IBKR house margin on 0DTE and naked index options; expiration-day liquidation timing; the
  after-hours exercise cut-off (quoted at about 17:25–17:30 ET, secondary); SPX/XSP exchange fees;
  the index-data subscription cost.
- SPXW wing-quote widths (unmeasured: `gex_maps` keeps no leg quotes); VOO, IVV and SOXX option
  liquidity.
- The 2026 FOMC/BLS dates as published by the Fed and BLS (the reviewers used aggregators).
- Whether ThetaData Options Standard reaches 2020; whether the backtest harness handles SPXW roots.
- IBKR's credit interest on cash and its margin-loan rate.
- The cash-basis put split (O2R) and QQQ's reject split by date (S2R), not re-derived here.
- All [M] figures: flat-vol Black-Scholes, no skew dynamics, overlapping entries, one 17-month panel
  for the account's own names; the 2× line marked at mid without slippage. The 3× studies use a
  realised-vol IV proxy that rises with the drop by construction.
- Why `gross_notional_cap` never fired with `value.book.enabled: true` (Mastermind rev 2 §2.3).
- **Revision 2:**
  - **XND liquidity** (one third-party snapshot only), Phlx fees, IBKR routing and paper behaviour for XND.
  - **Every hedge cost and coverage figure** is Black-Scholes with an assumed skew (0.3 PPUT-calibrated
    to 0.8 from a few June 2026 chains), with no historical index option quotes; the standing-hedge
    backtest has 8 rolls; the trim comparison assumes P&L scales with exposure.
  - IBKR's margin treatment of a long and a short put on one underlying (Reg T spread offset).
  - `IB.exerciseOptions` lapse instructions on the paper account; IBKR's handling of an ITM long
    put the account cannot deliver against.
  - Whether the trade ledger's FIFO pairs a long-option open and close exactly.
  - Why SPY's `iv_history` stops on 2026-10-05, and where the SPY IV/RV ratio of §3.3 came from.
  - US-situs estate treatment of listed index options for a Singapore non-resident (not tax advice).

## 8. What the implementation plan must update

Per CLAUDE.md's doc-update table:

- **For config keys:** `config/examples/risk_limits.yaml`, `config/examples/spreads.yaml` and
  `config/examples/universe.yaml` (new keys and removed names), and ARCHITECTURE.md's config section.
- **For universe changes:** UNIVERSE_RESEARCH.md and `strategist.py` `_UNIVERSE_CONTEXT`.
- **For the spreads fence:** CLAUDE.md's spreads-fence section at E3, SETUP.md §16 and ARCHITECTURE.md
  `src/spreads/`.
- **For a new module:** ARCHITECTURE.md for `src/common/spreads_view.py` and the shock/gap module in
  `src/analytics/` (deterministic tier; imports no enrichment).
- **STATUS.md**, for every item built or deferred.
- **Revision 2:** ARCHITECTURE.md for `src/hedge/`, `src/common/hedge_view.py`, `src/reporting/hedge.py`,
  the `hedge_*` ORM rows (`src/storage/`) and the `HedgeCandidate` schema (`src/common/`);
  `config/examples/risk_limits.yaml` for the `hedge:` block (underlyings, budget, windows, stress
  block, size rule); CLAUDE.md for a hedge-fence section and the core-invariant note on Claude's paper
  put budget; SETUP.md for the operator-facing bridge and its Telegram/web surfaces; STATUS.md.
