# Risk envelope, leveraged-ETF policy and the spreads book — design

Date: 2026-11-13 · Status: **draft for operator review**. Sequenced **before** the Mastermind
(`2026-11-12-mastermind-design.md`, now revision 3). That spec's envelope repair, book repair and
spreads decisions now live here; it references this spec as a prerequisite.

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
| 0DTE as the wheel's hedge | Wrong tenor: the damage was a multi-week slide (NLV −17.7% Oct 13–Nov 11). A hedge, if any, is a 30–90-day index put spread under Mastermind R5, needing a buy-to-open path |
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
  (−2% of NLV a month at worst).
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

**A sleeve lot opens only when all of these hold:**

1. **Signal:** the name's or the governing index's bottoming signal fires (existing machinery).
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
8. **Sleeve cap:** ≤ 3% of NLV of leverage-weighted collateral across all leveraged names. At today's
   prices that is **one lot at a time**: a TQQQ lot is ~$6k of collateral, ~$18k (2.8% of NLV) at
   leverage; a SOXL lot is ~$5.5–6.6k, ~$16.5–20k at leverage.
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
   - Protective puts later, which need a buy-to-open path.
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

R0 now: shadow every sleeve trigger, every band-relevant day and every equal-exposure menu (index
lot, leveraged equivalent, index put vertical, skip), each item shadow-valued.

## 4. Phasing

| Phase | Content | Gate to the next |
|---|---|---|
| **E0. Stop the bleeding, measure** (no new authority; risk-reducing or display only) | Spreads: §3.2 a, b, c, e, f and h (calendar, halt link, daily-leg coupling, NLV caps, cost standard, shadow mode). Wheel: leveraged CSPs off (`csp_mode: drawdown_only` with the sleeve closed); `vrp_waiver` off for leveraged names; UPRO and DPST out. S10, S20, G10, P20, U_ew and L(t) computed daily and shown (brief, web, Telegram), not yet enforced. The discretionary-buy display. SOXX into price/IV history. Docs per the CLAUDE.md table | Operator adopts this spec and rules E1, E2, E8 |
| **E1. Backtests and replays** | The spreads ThetaData backtest (§3.2 g). SPXW shadow cost measurement (§3.3). The survivability harness on the deterministic envelope (§3.4.6). The D14 replay (§3.7). The tech-linked cap and stacking-rule backtest (§3.4.4). The leveraged-sleeve replay (§3.5). The wheel-faithful index-class replay (§3.8) | Each replay's report read by the operator; rulings E3–E7, E9, E10, E12, E14, E15 |
| **E2. Envelope live (paper)** | S10 with the glide, and U_ew unconditional, enforced. The tech-linked cap and stacking rule if supported. The slow breaker spanning books. The index class. The leveraged sleeve. Tap-only repair proposals: CC overlays at the ruled floor and the leveraged carve-out; trims and de-lever once their order paths exist (each its own plan task). The index-class multiplier stays record-only until its replay agrees | Harness passes on the live envelope; ≥ 20 sessions with no envelope defect |
| **E3. Spreads to SPX, SPY freed** | Only if the backtest passed and the SPXW cost condition holds (E3). The fence task of §3.3 as one change, at a flat-book cutover. Then SPY joins the index class | Operator ruling E3 |
| **E4. Glide complete** | L(t) reaches the target. Levels change thereafter only by §3.8's stabilisation rule | — |

**Sequencing with the Mastermind.**

- **Mastermind Phase 0** (prompt cleanup) changes no risk and may run beside E0–E1.
- **Mastermind Phase 2 onward** waits for E2, so that every R0 record is made against the repaired
  envelope.
- **Mastermind risk-changing rungs** (R3, R4, auto R5, X2) need E2 complete and the harness passing.
- **The R3 allocation lever** also needs the leveraged sleeve live.

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
| **E7** | The leveraged sleeve | §3.5 conditions; vol-scaled drawdown (1.0 σ₆₀); a sleeve delta window of 0.15–0.20 (load check changed); 3% of NLV aggregate, which is one lot at a time at today's prices | Alternative: 3% per name with 2 lots (≈ 6% aggregate). OR4 reads as aggregate |
| **E8** | Universe | UPRO, DPST out; TQQQ, SOXL out of `actively_wheeling`; QQQ in; SOXX dip-watch for liquidity; SPY after E3 | — |
| **E9** | The index class | One lot ≤ 15% of NLV, {QQQ, SPY}; VOO/IVV only as fallback | O2R: 12% with SMH |
| **E10** | Tail-class deployment | `index_1x` multipliers {1.0, 1.0, 0.8, 0.5}, record-only until the wheel-faithful replay agrees in sign under both valuations | — |
| **E11** | "Cash reserve" and Portfolio Margin | Retire the reserve as a policy idea; `cash_reserve_pct` stays a margin buffer; no PM while the budget derives from EL | — |
| **E12** | Book repair floor (was Mastermind D14) | Rule `min_strike_vs_basis` by replay; a leveraged class floor of none at delta ≤ 0.25, tap-only first; de-lever and trims as tap-only proposals once their order paths exist | S2 would apply the leveraged carve-out now, unconditionally |
| **E13** | Discretionary buys | Show S10, U_ew and headroom before and after every manual buy; no attempt to gate TWS orders | — |
| **E14** | The slow breaker (was part of D13) | 20–30-session window on account NLV; on a trip: demote risk-changing rungs, block risk-changing levers, scale the CSP budget, stop spreads entries; human reset | Threshold set after the E1 replay |
| **E15** | The tech-linked cap and stacking rule (was part of D13) | Leverage-weighted group cap; stacking rule; both only if the backtest against the `claude_cut` rows supports them | — |

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
