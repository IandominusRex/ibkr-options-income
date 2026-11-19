---
run: 1
title: "Run 1: the paper account under the pre-envelope rules"
status: closed
account: ibkr_paper            # IBKR paper; no real money was at risk
currency: usd
start_date: 2026-06-22
end_date: 2026-11-18
boundary_event: "the operator liquidated every share and every short put, 2026-11-18 18:53:28-18:53:54 UTC"
sessions:
  whole_run: 106               # SPY sessions 2026-06-22 .. 2026-11-18 (the last one partial)
  autonomous: 36               # 2026-09-30 .. 2026-11-18, autonomy "full" in paper
  autonomous_start_date: 2026-09-30
  system_dormant: "2026-06-25 .. 2026-08-11, no log line, order, fill or journal row"
nlv_usd:
  start: 787576                # 2026-06-22 close; SGD 1,010,027 x 0.77976 [M]
  peak: 817551                 # 2026-10-07 close (the last SGD-era row); SGD 1,046,465 x 0.78125 [V]
  peak_date: 2026-10-07
  trough_close: 571098         # 2026-11-05 close, the end-of-day journal row
  trough_close_date: 2026-11-05
  trough_intraday: 566411      # 2026-11-17 10:43 ET, 15-minute snapshots (they start 2026-10-19)
  trough_intraday_at: "2026-11-17T15:43Z"
  end: 588867                  # the first flat portfolio snapshot, 2026-11-18 19:01:47 UTC
  end_at: "2026-11-18T19:01:47Z"
  end_latest_flat: 589025      # the next snapshot, 19:16:48 UTC, still flat
return_pct:
  from_start: -25.23           # to end
  from_peak: -27.97            # to end
  from_start_to_2026-11-17_close: -26.37
  from_peak_to_2026-11-17_close: -29.06
  start_to_peak: 3.81
max_drawdown_pct:
  from_peak_close_basis: -30.15   # 2026-11-05 close
  from_peak_intraday: -30.72      # 2026-11-17 10:43 ET
benchmarks_pct:                # total return, yfinance adjusted closes [W]
  basis: "2026-11-18 is the latest 5-minute bar the feed had (10:52 ET), about 3 hours before the account's final mark; the _to_2026-11-17 windows are clean"
  start_to_end:                # 2026-06-22 -> 2026-11-18
    account: -25.23
    spy: -1.88
    qqq: -11.02
    spy_qqq_50_50: -6.45       # monthly rebalanced
    smh: -31.54
    jepi: 3.92
    jepq: -6.57
    xyld: 1.38
    qyld: -2.83
    svol: -4.86
  peak_to_end:                 # 2026-10-07 -> 2026-11-18
    account: -27.97
    spy: -6.26
    qqq: -13.43
    spy_qqq_50_50: -9.87
    smh: -26.74
    jepi: 0.59
    jepq: -10.37
    xyld: -4.17
    qyld: -7.53
    svol: -12.88
  start_to_2026-11-17:
    account: -26.37
    spy: -1.36
    qqq: -10.88
    spy_qqq_50_50: -6.12
    smh: -31.22
    jepi: 4.29
    jepq: -6.49
    xyld: 1.87
    qyld: -2.65
    svol: -4.49
  peak_to_2026-11-17:
    account: -29.06
    spy: -5.76
    qqq: -13.30
    spy_qqq_50_50: -9.56
    smh: -26.39
    jepi: 0.95
    jepq: -10.29
    xyld: -3.72
    qyld: -7.37
    svol: -12.54
  start_to_peak:               # 2026-06-22 -> 2026-10-07
    account: 3.81
    spy: 4.67
    qqq: 2.79
    spy_qqq_50_50: 3.80
    smh: -6.56
    jepi: 3.31
    jepq: 4.24
    xyld: 5.80
    qyld: 5.09
    svol: 9.21
  peak_to_2026-11-05:          # the account's close-basis trough
    account: -30.15
    spy: -5.69
    qqq: -14.61
    spy_qqq_50_50: -10.20
    smh: -28.37
    jepi: 0.50
    jepq: -11.51
    xyld: -3.69
    qyld: -8.72
    svol: -10.33
  max_drawdown_since_peak:     # on closes, 2026-10-07 .. 2026-11-18
    account: -30.15
    spy: -6.42
    qqq: -14.61
    spy_qqq_50_50: -10.20
    smh: -28.37
    jepi: -3.26
    jepq: -11.51
    xyld: -4.40
    qyld: -9.02
    svol: -14.69
realised_beta:                 # daily NLV returns against daily total returns
  window: "2026-10-19 .. 2026-11-17, 21 returns, the last RTH portfolio snapshot of each session"
  to_qqq: 1.90
  r2_qqq: 0.94
  to_spy: 2.67
  r2_spy: 0.77
  to_smh: 1.02
  to_spy_qqq_50_50: 2.27
  alt_journal_eod_2026-10-09_to_2026-11-17: {to_qqq: 1.80, to_spy: 2.63, to_smh: 0.96, to_spy_qqq_50_50: 2.20, n: 26}
  spec_figure_22_sessions: {to_qqq: 1.87, to_spy: 2.74}   # [S] Mastermind §2.4
attribution_usd:
  method: "peak close (2026-10-07) to the booked liquidation; ledger flows plus the 2026-10-07 position marks; the residual is interest and accruals [M]"
  total_change_peak_to_end: -228683
  manual_stock: -163358                 # AMD 300, BAC 1000, GOOGL 300, MARA 1000, NVDA 500, SOXL 500
  manual_stock_nvda_soxl_bought_on_peak_day: -97862
  wheel_assigned_stock: -62132          # GOOGL 200, HIMS 2000, PLTR 300, NVDA 300
  option_book_net: -4575                # premium, stops, rolls and the 12 buy-backs at the liquidation
  spreads_paper: 642
  stock_commissions: -49
  interest_and_residual: 788
  share_manual_pct: 71.4
  share_system_pct: 28.6                # everything that is not manual stock
  system_loss_pct_of_peak_nlv: -8.0
  start_anchored_total_change: -198709
  start_anchored_manual_stock: -136645
  start_anchored_unexplained_after_interest: -6575   # SGD-era conversion at one rate is the likely cause [M]
premium_usd:                   # the wheel's option executions in the ledger, spreads excluded [V]
  sold_gross: 59358            # includes roll legs
  sold_gross_puts: 53186
  sold_gross_calls: 6172
  sold_excluding_roll_legs: 44875      # [M]: less 14,483 of roll new-leg credits from the fills table
  bought_back: 59301
  option_commissions: 270
  net_option_cash_after_commissions: -213
  by_month: {2026-06: 370, 2026-09: 2504, 2026-10: 44165, 2026-11: 12319}
realised_put_pnl_usd:          # IBKR's realised column; an assigned put books zero
  ibkr_column_before_liquidation: -9959
  ibkr_column_including_liquidation_buybacks: -10657
  leveraged_tqqq_soxl: -11042
  non_leveraged: 1083
trades:
  wheel_orders: {total: 324, filled: 116, partial: 6, cancelled: 170, rejected: 32}
  wheel_fill_rows: 142
  approvals: {total: 290, approved: 247, expired: 43, rejected: 0, approved_since_2026-09-30: 243, recorded_as_system: 175, unattributed_before_the_decided_by_field: 68, recorded_as_web_or_telegram: 0}
  ledger_executions_effective: 331      # 354 rows less 23 superseded; 39 of them are the liquidation
  option_contracts_sold: 259
  option_contracts_bought: 259
  spreads_paper_positions: 3            # in the account
  spreads_baseline_positions: 15        # simulated, no account effect
assignments:
  events: 8
  contracts: 48
  by_name: {MARA: 10, GOOGL: 2, PLTR: 3, HIMS: 30, NVDA: 3}
  shares_assigned_gross: 4800
  shares_from_assignment_at_the_end: 3800
  long_put_exercises: 1                 # the HIMS +10 long put, 2026-10-30
exits:                         # contracts, net of premium, before commissions [M]
  profit_take: {contracts: 51, net_usd: 7400}
  loss_exit: {contracts: 49, positions: 13, underlyings: [TQQQ, SOXL], net_usd: -12478}
  rolls: {executed: 10, contracts: 23, net_credit_usd: 1517}
  manual_closes_at_liquidation: {contracts: 12}
claude:
  trade_verdicts_since_2026-10-01: {sell: 79, wait: 0, none: 2}
  trade_verdicts_all: {sell: 85, wait: 14, none: 13}
  priority_equals_python_rank: {matching: 92, comparable: 99}
  claude_cut: {rows: 11, real_cuts: 10, contracts_before: 34, contracts_after: 14, resolved_with_pnl: 5, net_loss_avoided_usd: 6257, p_two_sided: 0.19, applied: paper_only}
  value_verdicts: {total: 40, current: 31, decided_effective: 30, agree_with_python: 26, effective_differs_from_python: 3, value_orders: 0}
  spreads_ai: {day_plans: 28, opus: 25, ollama: 2, failed: 1, picks: 20, baseline_letter: 4, skip: 16}
  headless_calls_2026-10-15_to_2026-11-18: {calls: 919, notional_usd: 23.43}
rule_set:
  git_first: 959b7a1           # the commit current when the system first ran in the window, 2026-06-22
  git_last_running_at_liquidation: b9d8243
  git_main_head_at_boundary: 4121b2d
  commits_in_range: 878
  autonomy_full_from: 2026-09-30   # 920dd7e
  envelope_enforce: record     # built, merged 2026-11-18 12:22Z, nothing enforced; the glide never started
  switches_at_boundary: {envelope_enforce: record, stacking_rule: "on", cc_basis_floor: 0.90, leveraged_entry: record, leveraged_sleeve: "off", leveraged_cc_auto: "off", tech_cap: "off", t20_limit: "off", slow_breaker: "off", index_1x: "off", bridge: "off", hedge_instrument: none, hedge_monetisation: none, spreads_paper: "off", spxw_ready: "off"}
  breakers: {daily_loss_halt_pct: 3.0, drawdown_halt_pct: 6.0, drawdown_window_days: 3}
  state_at_boundary: "execution halted by the operator at 18:52:03Z (/halt); autonomy full; paper (the connection banner reads PAPER, port 4002)"
---

# Run 1: the paper account under the pre-envelope rules, 2026-06-22 to 2026-11-18

**Tags.** Every figure carries one: **[V]** verified here from the database, logs or git;
**[M]** a model or an approximation, method stated; **[W]** yfinance (web), not the account;
**[S]** taken from a spec and not re-derived here; **[U]** could not be verified. See
[../README.md](../README.md) for how to use a record. Log times are local (+0800) unless marked Z (UTC).
Commit dates are local. The ledger's `trade_time` for executions the live feed booked before the
2026-11-18 restart is eight hours behind UTC (BAC sold at 16:02:59Z reads 08:02:59); the
liquidation rows read as UTC [V].

**Sources.** `data/income_system.db` (journal, `portfolio_snapshots`, `position_snapshots`,
`broker_executions`, `fills`, `orders`, `approvals`, `campaigns`, `verdict_ledger`, `sizing_actions`,
`envelope_snapshots`, `fx_rates`, `price_history`, `iv_history`, `system_settings`), `data/spreads.db`,
`data/value.db`, `logs/approval.log`, `git log` and the reflog, and the two specs
(`2026-11-12-mastermind-design.md` §2.4, §6A, §16.0; `2026-11-13-risk-envelope-design.md` §2). Every
database was opened `mode=ro`. Queries are in §12.

## 1. Summary

Run 1 was the paper account's life from 2026-06-22 to 2026-11-18. It started at about $787.6k,
peaked at $817.6k on Oct 7, and ended at $588.9k when the operator liquidated every position on
Nov 18: **−25.2% from the start and −28.0% from the peak** [V, M]. Over the same windows SPY lost 1.9%
and 6.3%, QQQ 11.0% and 13.4%, a 50/50 SPY/QQQ mix 6.5% and 9.9%, and SMH 31.5% and 26.7% [W]. The
deepest close was $571.1k on Nov 5 (−30.1% from the peak), the day SPY fell 4.4% and the account fell
12.9%.

**Two periods.** Until Sep 30 the account was mostly cash plus 300 AMD shares bought by hand. The
system filled one order (a MARA put, Jun 24) and was off for seven weeks (Jun 25 to Aug 11). The
account tracked the 50/50 benchmark to the peak (+3.8% against +3.8%). From Sep 30 autonomy was
`full` in paper: **36 sessions of autonomous trading, and all of the drawdown happened in them**.
Run 1 is a seven-week test of the wheel, not a five-month one.

**Where the loss came from.** About 71% (−$163k) came from stock the operator bought by hand
(AMD, BAC, GOOGL, MARA, NVDA, SOXL), of which NVDA and SOXL, both bought on the peak day, were
−$98k. About 27% (−$62k) came from shares the wheel was assigned (GOOGL, HIMS, PLTR, NVDA), which
closed $62k under their strikes. The options book as a whole roughly broke even in cash: $59.4k of
premium sold, $59.3k paid to close, −$0.2k after commissions. Leveraged-ETF puts lost $11.0k; every
other name made $10.8k. The spreads book made $0.6k in the account. Interest paid $6.3k.

**Verdict** (Mastermind §2.4, stated again on the evidence here).

- **Judged as an income system, the system failed in this episode.** The account's realised beta to
  QQQ was about 1.9 and to SPY about 2.7 over 21 sessions. That is a leveraged long-tech book with a
  premium overlay. All the premium the wheel sold in the run ($59.4k, $44.9k excluding roll legs) is
  less than the $62k its own assigned shares closed below their strikes, and under a third of the
  loss.
- **The failure is risk control, not the idea of selling premium.** There was no working
  account-level limit. The drawdown breaker measured from the all-time high was replaced on Nov 5 by a
  3-session window. Nothing the operator bought by hand was counted. Puts kept being sold into a book
  already at 1.3 to 1.5 times gross, on the same factor and partly on the same names.
- **The system's own trading lost about $65k, 8.0% of peak NLV,** while QQQ lost 13.4% and JEPQ
  10.4%. Taken alone that is not a disaster. It was layered on a book whose risk the manual stock had
  already spent.
- **This is not evidence that the premium idea cannot work, and there is no evidence yet that it
  does.** One sector crash, seven autonomous weeks, paper fills, one regime. The one result that is
  evidence, the realised put P&L, is negative (§4).
- **What makes it a lesson and not only a loss:** the fixes are specified and mostly built. None was
  enforced at the boundary: `envelope_enforce` read `record`, the glide had not started, and the only
  limit switched on was the per-name stacking rule, about 20 minutes before the operator halted
  trading (§10). Until they are on and verified, the system that failed is the system that is
  running.

## 2. Timeline

Account events (A) and system changes (S) on one table. Merge dates are from the reflog; the
branches were fast-forwarded unless noted.

| Date | Event | Source |
|---|---|---|
| 06-15 | A: 300 AMD bought by hand at $548.17, a week before the run | ledger id 1 [V] |
| 06-22 | **Run starts.** First end-of-day journal row: NLV SGD 1,010,027, $787.6k [M]. Book: AMD 300 and cash | journal [V] |
| 06-24 | A: first approved order and first fill: MARA 12P x10 at $0.37 | `fills` 1, approval 9 [V] |
| 06-25 to 08-11 | S: **the system was off.** `approval.log` has no line between Jun 26 01:25 and Aug 12 23:55 (+0800); no order, fill or journal row, and no commit in July. Seven weeks | `approval.log`, `orders`, journal, git [V] |
| 07-17 | A: the MARA put is assigned: 1,000 shares at $12 | ledger ids 4, 18 [V] |
| 08-12 | EOD journal resumes ($759.8k) | journal [V] |
| 09-09 | S: `portfolio_snapshots` starts being written (rows are kept only from Oct 19) | git `0d3e702`; table [V] |
| 09-23 | A: BAC 1,000 at $56.08 and GOOGL 300 at $349.45 bought by hand. S: CSP delta band widened to 0.20-0.35, two large-position slots (`94415ec`) | ledger; git [V] |
| 09-30 | **S: autonomy `full` in paper (`920dd7e`).** First autonomous option fills: TQQQ 74P x10, AMZN 245P x4, GOOGL 335P x2 | `system_settings`, `fills` [V] |
| 10-07 | **A: NVDA 500 at $237.75 and SOXL 500 at about $153.4 bought by hand. NLV peak at the close, $817.6k.** S: trade ledger merged | ledger ids 25-31; journal; git [V] |
| 10-09 | S: news thread merged; account snapshot reported in USD, not SGD (`099fd0a`). The journal is USD from this day | git; journal [V] |
| 10-09 | S: daily credit-spreads book live in paper mode (built Oct 8) | memory, git [S] |
| 10-10, 10-11 | S: option-contract cache merged (Oct 10); roll redesign built (Oct 11) | git [V] |
| 10-12 | S: spreads Claude picker merged. **A phantom 24.6% drawdown trips the breaker and halts entries** (USD NLV against an SGD high-water mark) | `e136547`; `14cbf9a`; `approval.log` [V] |
| 10-13 | S: USD high-water mark fix (`14cbf9a`) | git [V] |
| 10-14 | A: first −4.5% day; daily-loss breaker trips. S: web overhaul Part 1 merged; the daemons start on a feature branch missing the roll fix | `approval.log`; memory [V, S] |
| 10-15 | S: `/resume` acknowledges a breaker halt and rolls run through it (`4be3078`); slim `claude -p` (`35052ef`). A: first executed roll (GOOGL); last covered call sold (AMD 590C); first baseline spreads trade | `fills`; git; `spreads.db` [V] |
| 10-19 | S: web overhaul Part 2 | git [V] |
| 10-22 | **S: market-picture merge (`ee87286`):** regime sizing, scale-in ladder, `claude_cut`, news expert. A: −5.3% day | git; journal [V] |
| 10-23 | **A: HIMS roll, IBKR error 103 "Duplicate order id"; +10 long Oct 30 28P left behind** (§9). First spreads paper trade. Drawdown-leg trip, $79,022 | ledger ids 170-202; `approval.log` [V] |
| 10-24 to 10-26 | IB Gateway down from Oct 24 10:00 to Oct 26 13:58 SGT, cause not investigated | memory [S] |
| 10-26 | A: GOOGL 200 assigned at $350 and $345, the first assignment of the autonomous period | ledger ids 209-212 [V] |
| 10-28 | S: web overhaul Part 3. A: last leveraged put sold (TQQQ 65P Nov 6 x3) | git; ledger [V] |
| 10-29, 10-30 | S: value book Parts 1 and 3 merged. A (Oct 30): PLTR 300 assigned at $195; the HIMS long put is exercised (−1,000 shares at $28); −4.6% day | git; ledger [V] |
| 11-02 to 11-04 | Drawdown-leg breaker trips on three consecutive sessions (standing drawdown). Value Parts 4 and 5 merged Nov 4 | `approval.log`; git [V] |
| 11-05 | **A: SPY −4.4%, QQQ −6.5%, SMH −11.2%; the account −12.9% (−$84.4k) to $571.1k, the close-basis low.** Daily breaker trips at 11:28 ET. S: `544e32e` replaces the standing drawdown leg with a rolling 3-session 6% window; value Part 6 merged | journal; `approval.log`; git [V] |
| 11-06 | A: HIMS 3,000 assigned at $28 (net +2,000 shares). S: web overhaul Part 5 | ledger; git [V] |
| 11-09, 11-13 | A: NVDA 100 assigned (Nov 9), 200 more (Nov 13), at $205-$210, against 500 manual shares | ledger [V] |
| 11-10 | A: spreads phantom close: 2 lots filled late, the book kept a phantom (§9) | `spreads.db` row 12 [V] |
| 11-12 | S: `9da9e8a` (spreads late fills, regime noise, roll noise, ITM roll-down rule), services restarted. Mastermind spec drafted | git; `approval.log` [V] |
| 11-13 | Risk-envelope spec committed. A: −4.4% day | git; journal [V] |
| 11-14 | S: the risk-envelope build starts (Sections A-K, Nov 14-18). Spreads become shadow-only until a backtest bar passes (`f449267`); no leveraged CSP outside the sleeve (`465ff29`) | git [V] |
| 11-16 | A: −5.0% day; breaker trip. The baseline spreads book starts six consecutive stop-losses (Nov 16-18) | journal; `spreads.db` [V] |
| 11-17 | A: intraday low $566.4k at 10:43 ET (−30.7%). Breaker trip | snapshots [V] |
| 11-18 12:22Z | S: **risk envelope merged to main (`2f40cd0`)**; services restarted 12:30Z | reflog; `approval.log` [V] |
| 11-18 15:00Z | First envelope snapshot: S10 24.4% against a 24.0% L(t), `enforce` = `record`, nothing refused | `envelope_snapshots` [V] |
| 11-18 18:23-18:32Z | Operator sets envelope switches by CLI; `stacking_rule` goes `on` at 18:32:30Z | `system_settings` [V] |
| 11-18 18:35Z, 18:46Z | Error 10197, a competing login on the account: the scan is blocked twice (§9) | `approval.log` [V] |
| 11-18 18:52:03Z | **Operator `/halt`** | `system_settings` [V] |
| 11-18 18:53:28-18:53:54Z | **The liquidation: 39 executions in 26 seconds** (§6) | ledger ids 316-354 [V] |
| 11-18 19:00:59Z | S: `fix/envelope-candidate-betas` merged (`4121b2d`); services restarted 19:01Z | reflog [V] |
| 11-18 19:01Z | First flat snapshot, NLV $588,867. The reconciler books 7 manual put closes. At 19:17:21Z all 18 `campaigns` rows read `closed` | snapshots; `approval.log`; `campaigns` [V] |

## 3. Account curve

### 3.1 Weekly NLV, in USD

Source: the end-of-day journal (after the close, 16:15 ET). Rows before Oct 9 are SGD converted at the
ledger's SGD rate: 0.77976 for every date before Sep 30 (the only ledger rate before Sep 30), the
day's rate from Sep 30 [M]. That single rate can be off by up to about 0.4% (about $3k) for dates in
July to September. SPY, QQQ and SMH are `price_history` closes (price return) indexed to 100 on
Jun 22 [V]; the benchmark summary in §3.2 uses total return [W].

| Week ending | Last NLV row | NLV (USD) | vs start | vs peak | SPY | QQQ | SMH |
|---|---|---|---|---|---|---|---|
| Jun 26 | Jun 24 | 783,289 | −0.5% | | 99.1 | 97.4 | 93.7 |
| Jul 3 to Aug 7 | none | | | | | | |
| Aug 14 | Aug 12 | 759,804 | −3.5% | | 103.7 | 98.4 | 88.1 |
| Aug 21 | none | | | | | | |
| Aug 28 | Aug 27 | 755,055 | −4.1% | | 103.5 | 98.1 | 86.4 |
| Sep 4 | none | | | | | | |
| Sep 11 | Sep 11 | 765,704 | −2.8% | | 102.6 | 97.2 | 85.7 |
| Sep 18 | none | | | | | | |
| Sep 25 | Sep 24 | 806,166 | +2.4% | | 103.0 | 100.8 | 90.5 |
| Oct 2 | Oct 1 | 799,015 | +1.5% | | 102.6 | 100.9 | 93.1 |
| *Oct 7 (peak)* | Oct 7 | *817,551* | *+3.8%* | *0.0%* | *104.4* | *103.0* | *94.2* |
| Oct 9 | Oct 9 | 795,309 | +1.0% | −2.7% | 104.5 | 102.2 | 90.9 |
| Oct 16 | Oct 16 | 717,262 | −8.9% | −12.3% | 102.5 | 96.5 | 81.4 |
| Oct 23 | Oct 23 | 701,552 | −10.9% | −14.2% | 102.0 | 95.8 | 79.5 |
| Oct 30 | Oct 30 | 665,656 | −15.5% | −18.6% | 101.5 | 93.9 | 78.8 |
| *Nov 5 (trough)* | Nov 5 | *571,098* | *−27.5%* | *−30.1%* | *98.4* | *88.0* | *67.5* |
| Nov 6 | Nov 6 | 600,612 | −23.7% | −26.5% | 98.7 | 89.2 | 69.9 |
| Nov 13 | Nov 13 | 618,615 | −21.5% | −24.3% | 101.3 | 92.5 | 73.4 |
| Nov 18 (end) | Nov 18 19:01Z | 588,867 | −25.2% | −28.0% | 97.8† | 89.2† | 69.0† |

† the latest bar the feed had, 10:52 ET [W].

Gaps [V]. The journal has 40 rows in five months: none from Jun 25 to Aug 11 (the system was off),
six from Aug 12 to Sep 29, and none for Oct 8 or Oct 12. SPY, QQQ and SMH all closed lower on Oct 8
than on Oct 7, so Oct 7 is very likely the peak close, but the peak is the highest observed close,
not a proven maximum [U]. The 15-minute `portfolio_snapshots`
exist only from Oct 19 (older rows are pruned), and their last row of a session is up to $6.4k away
from the journal (Nov 5: $577.5k at 15:46 ET against $571.1k at 16:15 ET).

### 3.2 Windows against the benchmarks

Total return [W] (yfinance adjusted closes). The 50/50 is SPY/QQQ rebalanced monthly. "To Nov 17"
is the last window with a complete close on both sides.

| Window | Account | SPY | QQQ | 50/50 | SMH | JEPI | JEPQ | XYLD | QYLD | SVOL |
|---|---|---|---|---|---|---|---|---|---|---|
| Start (Jun 22) to the peak (Oct 7) | +3.8% | +4.7% | +2.8% | +3.8% | −6.6% | +3.3% | +4.2% | +5.8% | +5.1% | +9.2% |
| Peak to Nov 5 (account trough) | −30.1% | −5.7% | −14.6% | −10.2% | −28.4% | +0.5% | −11.5% | −3.7% | −8.7% | −10.3% |
| Peak to Nov 17 close | −29.1% | −5.8% | −13.3% | −9.6% | −26.4% | +1.0% | −10.3% | −3.7% | −7.4% | −12.5% |
| Peak to the end (Nov 18) | **−28.0%** | −6.3% | −13.4% | −9.9% | −26.7% | +0.6% | −10.4% | −4.2% | −7.5% | −12.9% |
| Max drawdown since the peak (closes, plus the Nov 18 bar) | −30.1% | −6.4% | −14.6% | −10.2% | −28.4% | −3.3% | −11.5% | −4.4% | −9.0% | −14.7% |
| Start to Nov 17 close | −26.4% | −1.4% | −10.9% | −6.1% | −31.2% | +4.3% | −6.5% | +1.9% | −2.7% | −4.5% |
| Start to the end (Nov 18) | **−25.2%** | −1.9% | −11.0% | −6.5% | −31.5% | +3.9% | −6.6% | +1.4% | −2.8% | −4.9% |

From the peak the account lost 2.1 times QQQ, 4.5 times SPY and more than SMH. Every options-income
fund lost less than its own index (JEPQ 0.77 of QQQ, QYLD 0.56, XYLD 0.67 of SPY). The account lost
more than any index in the table. [M]

### 3.3 Risk

**Realised beta** [V, M]. Daily NLV returns against daily total returns, 21 sessions Oct 19 to Nov 17
using the last RTH snapshot of each session:

| To | Beta | R² |
|---|---|---|
| QQQ | 1.90 | 0.94 |
| SPY | 2.67 | 0.77 |
| SMH | 1.02 | 0.94 |
| 50/50 SPY/QQQ | 2.27 | 0.89 |

On the journal's end-of-day series (26 returns, Oct 9 to Nov 17) the betas are 1.80, 2.63, 0.96 and
2.20. The spec's 1.87 and 2.74 (Oct 14 to Nov 12) sit close to the same range [S]. The conclusion does
not depend on the series: the account moved about 1.8 to 1.9 times QQQ and 2.6 to 2.7 times SPY.

**The worst days** [V]. Eight of the 26 sessions from Oct 9 lost more than 4%.

| Day | Account | $ | SPY | QQQ | SMH |
|---|---|---|---|---|---|
| Nov 5 | −12.9% | −84,368 | −4.4% | −6.5% | −11.2% |
| Oct 22 | −5.3% | −39,607 | −1.2% | −2.9% | −6.0% |
| Nov 16 | −5.0% | −30,818 | −1.9% | −2.7% | −5.1% |
| Oct 30 | −4.6% | −32,277 | −1.8% | −3.5% | −7.0% |
| Oct 14 | −4.5% | −35,699 | −1.1% | −2.0% | −4.0% |
| Nov 13 | −4.4% | −28,634 | −0.4% | −1.2% | −3.0% |
| Oct 29 | −4.2% | −30,955 | −0.4% | −1.4% | −1.1% |
| Oct 16 | −4.0% | −30,062 | −1.1% | −2.5% | −3.4% |

**Breaker trips** [V, `logs/approval.log`]. 17 log lines, 15 distinct trips, on 14 sessions (ET), Oct 12
to Nov 17. Five were the drawdown leg (Oct 12, Oct 23, Nov 2, Nov 3, Nov 4); nine were the daily
mark-to-market loss leg (Oct 14, 15, 16, 22, 30, Nov 5, 10, 16, 17). The Oct 12 trip was false (§9).
A trip halts new openings. It does not stop an assignment or sell anything. On the worst day (Nov 5)
the daily leg tripped at 11:28 ET with the day about $62k down; the close was $84k down.

## 4. What the system traded

### 4.1 Scale and structure

- **Orders (the wheel):** 324 rows [V]: 116 filled, 6 partial, 170 cancelled (mostly unfilled-order
  timeouts), 32 rejected at a re-gate (25 roll re-validations: 17 `roll_credit_collapsed`, 7
  `roll_net_below_floor`, 1 `roll_delta_increase`; 6 live re-validations; 1 execution exception).
  The `fills` table has 142 rows on 30 days: 1 in June, 3 in September, 112 in October, 26 in
  November.
- **Approvals:** 290 [V]: 247 approved, 43 expired, **0 rejected by anyone**. 243 were approved after
  Sep 30: 175 are recorded `system` (Oct 19 onward, when the `decided_by` field exists) and 68
  (Sep 30 to Oct 16) are unattributed. **No approval row records a human decision, web or Telegram.**
  The operator's other lever was TWS, used for the stock buys and the liquidation.
- **Ledger:** 354 rows, 23 of them superseded duplicates, 331 effective [V]. The live execution feed
  starts Oct 6; earlier rows come from CSV and Flex statements. By `book` tag, effective rows:
  `system` 186, `spreads` 50, `manual` 95 (39 of them the liquidation). The tag is unreliable for
  the split between manual and system (§8, N2).
- **Campaigns:** 18 wheel threads (one per name and period), 4 with an assignment (MARA, PLTR, NVDA,
  HIMS), all `closed` on Nov 18 [V]. GOOGL's campaign reads `assigned = 0` although two GOOGL puts
  were assigned on Oct 26; why is [U].
- **Premium sold** [V, ledger, spreads excluded]: Jun $370, Sep $2,504, Oct $44,165 (puts $37,993,
  calls $6,172), Nov $12,319; **$59,358 in all** (puts $53,186, calls $6,172), of which about $14.5k
  were the credits on the new legs of rolls [M, fills table]. $59,301 was paid to close. The spec's
  "October puts $38.0k, calls $6.2k" matches [S, V].
- **Only 14 calls were sold**, all on AMD and GOOGL shares, the last on Oct 15. No call was written
  on any assigned or underwater share after that.
- **The ledger's `book` tag cannot separate manual buys from assignments** (§8, N2). Attribution here
  uses the execution codes (`A` = assignment) and the `fills` table, not the tag.

### 4.2 By underlying

Ledger [V], spreads excluded. "Premium sold" includes roll legs; "bought back" includes roll
closes and the 12 buy-backs at the liquidation. "Net" is after commissions and excludes any stock
result (§5, §6). `L` marks the 3x ETFs.

| Underlying | Puts sold | Calls sold | Premium sold | Bought back | Net | Assigned (contracts) |
|---|---|---|---|---|---|---|
| TQQQ L | 67 | | $10,217 | −$17,124 | **−$6,964** | |
| SOXL L | 6 | | $3,530 | −$7,595 | **−$4,078** | |
| HOOD | 9 | | $2,356 | −$6,110 | −$3,765 | |
| CRWD | 12 | | $12,705 | −$13,509 | −$823 | |
| BAC | 1 | | $51 | −$46 | +$3 | |
| SOFI | 10 | | $210 | −$100 | +$104 | |
| ASTS | 2 | | $506 | −$355 | +$147 | |
| AAPL | 3 | | $666 | −$216 | +$446 | |
| MARA | 20 | | $590 | −$80 | +$490 | 10 |
| NVDA | 5 | | $1,723 | −$745 | +$971 | 3 |
| AVGO | 4 | | $2,030 | −$934 | +$1,091 | |
| AMD | | 6 | $3,915 | −$1,785 | +$2,123 | |
| GOOGL | 15 | 8 | $7,121 | −$4,856 | +$2,237 | 2 |
| PLTR | 14 | | $3,648 | −$1,368 | +$2,264 | 3 |
| AMZN | 24 | | $4,991 | −$2,235 | +$2,727 | |
| HIMS | 53 | | $5,099 | −$2,243 | +$2,815 | 30 |
| **Total** | **245** | **14** | **$59,358** | **−$59,301** | **−$213** | **48** |

Premium retained on the 8 assigned contracts was $7,881 after commissions [V]. The shares they
delivered closed $62.1k under their strikes (§5).

### 4.3 Exits

Per position, premium less buy-back, before commissions [M, `fills`].

| Exit | Contracts | Net | Note |
|---|---|---|---|
| Profit-take | 51 | +$7,400 | 48 non-leveraged +$7,064; 3 leveraged +$336 |
| Loss exit (the 2x loss line) | 49 | −$12,478 | 13 positions, **all TQQQ or SOXL** |
| Rolls | 23 (10 rolls) | +$1,517 net credit | all 10 for a small net credit, by policy |
| Closed by the operator | 12 | | the liquidation only |
| Assigned | 48 (8 events) | | MARA 10, GOOGL 2, PLTR 3, HIMS 30, NVDA 3 |
| Exercised (a long put) | 10 | | the HIMS long put, Oct 30 (§9) |

Non-leveraged names were never bought back at the loss line: they got a defensive roll proposal or
assignment (envelope spec §2.2 [S]). That policy is how the assigned shares arose [M].

### 4.4 Leveraged against not

| | Leveraged (TQQQ, SOXL) | Everything else |
|---|---|---|
| Premium sold | $13,747 | $45,611 |
| Bought back | $24,719 | $34,582 |
| Net, after commissions | **−$11,042** | **+$10,829** |
| Stop-outs | all 49 contracts | none |
| Assigned | none | 48 contracts |
| Last put sold | Oct 28 | Nov 18 |

The −$11,042 matches the spec's −$11,042 (TQQQ −$6,965, SOXL −$4,078) [S, V]. IBKR's realised
column for puts, system and manual, is −$9,959 before the liquidation buy-backs and −$10,657 with
them [V]; the spec's −$10,169 is an earlier date (the Nov 18 AMZN closes added +$209) [S]. IBKR books
zero on an assigned put, so that column hides the $7.9k of premium retained on assigned contracts
and shows nothing of the loss on the shares. Both classes lost money in the regime: the leveraged
through stops, the rest through assignment.

### 4.5 The spreads book

`data/spreads.db`, read-only [V]. SPY 0DTE credit verticals; its own process, config and Telegram
thread.

| Mode | Trades | Wins | Losses | P&L | Commissions |
|---|---|---|---|---|---|
| `paper` (real paper fills, ledger tag `spreads`) | 3 (Oct 23, Oct 28, Nov 10) | 3 | 0 | +$647 (ledger: +$642) | $69 |
| `baseline` (simulated, no account effect) | 15 (Oct 15 to Nov 18) | 7 | 8 | **−$3,371** | $731 |

The baseline book's last six trades, Nov 16 to Nov 18, were all stop-losses (−$3,786), as SPY fell.
The spec's +$415 on 9 baseline trades (Nov 12) is superseded [S]. The paper book is unchanged since
Nov 12. The spreads book became shadow-only on Nov 14. Claude's part: 28 day plans (25 Opus, 2 Ollama,
1 failed Sonnet fallback) and 20 picks: the baseline letter 4 times (3 filled), `skip` 16 times; it
never chose a riskier letter [V].

### 4.6 The manual book, kept separate

Stock bought by hand [V, ledger codes `O;P`]: AMD 300 (Jun 15, $548.17), BAC 1,000 and GOOGL 300
(Sep 23), NVDA 500 ($237.75) and SOXL 500 (about $153.4), both on Oct 7. MARA 1,000 (assigned Jul 17
from the put approved in the queue on Jun 24) is tagged manual in the ledger and in the spec. There
was **no manual trade between Oct 8 and Nov 18 18:52Z**: every `manual`-tagged execution in that
window is an assignment or exercise row. Covered calls were written on the manual AMD and GOOGL
shares (the wheel's share count W includes manual shares by design).

### 4.7 What did not trade

The value book placed **no order**: 9 buy proposals (Nov 5 to Nov 17), 7 refused and 2 expired, every
one gated by `gross_notional_cap` and four also by `halted`; 4 funding requests lapsed [V,
`value.db`]. The hedge book has no rows and its bridge was off. The Leveraged Entry Signal wrote two
rows, on Nov 17, both "trend break, no entry" [V]. The envelope's repair proposals: **0 rows** [V].

## 5. Attribution of the loss

**Method** [M]. The change in NLV from the peak close (Oct 7, $817,551) to the booked liquidation
($588,867). For each source: ledger flows (proceeds plus commissions) from Oct 8 to Nov 18, including
the liquidation, less the source's position marks at the Oct 7 close (`position_snapshots`). Manual
stock is valued from its Oct 7 close; assigned stock from its assignment price. Everything is in cash
at the end, so no end marks are needed. The reconciliation closes to $788 of interest and accruals.

| Source | Since the Oct 7 close | Share |
|---|---|---|
| Stock bought outside the system: AMD 300, BAC 1,000, GOOGL 300, MARA 1,000, NVDA 500, SOXL 500 | **−$163,358** | **71.4%** |
| of which NVDA and SOXL, both bought on Oct 7 | −$97,862 | 42.8% |
| Stock the wheel was assigned: GOOGL 200, HIMS 2,000, PLTR 300, NVDA 300 | −$62,132 | 27.2% |
| The option book: premium, stops, rolls and the 12 buy-backs at the liquidation | −$4,575 | 2.0% |
| Spreads, paper | +$642 | −0.3% |
| Stock commissions | −$49 | 0.0% |
| Interest and accruals (the residual) | +$788 | −0.3% |
| **Total** | **−$228,683** | **100%** |

The system's side (everything that is not manual stock) is **−$65,326, 28.6% of the loss and 8.0% of
peak NLV**. The spec's figures, from marks at 18:00Z and before the booked liquidation, are −$162k
(70%) and −$69k (30%, 8.5%) [S]. The difference is the booked liquidation prices against marks and
the interest line; the conclusion is the same.

**Two classification choices.**

- MARA 1,000 (−$3.7k). The put was an order approved in the system's queue on Jun 24, the first
  fill of the run, before autonomy was `full` (the approver is not recorded [U]). The shares were
  assigned, not purchased. The ledger tags them `manual` (a CSV import has no order reference) and
  so does the spec. Moving MARA to the system column makes manual 69.8%.
- The other five stock lines were bought by hand, outside the system's order path. Its gates never
  saw them [S], and they spent the headroom the wheel then sold puts into.

**Cross-check, anchored at the start** (Jun 22 to the end, −$198,709) [M]: manual stock −$136.6k
(68.8%), wheel-assigned stock −$62.1k (31.3%), options −$0.2k, spreads +$0.6k, commissions −$0.1k.
After counting the $6.3k of interest credited, **$6.6k is unexplained** (3.3% of the loss). The likely
cause is the single SGD rate used before Sep 30 (§3.1). The peak-anchored table above is exact on its
inputs and is the one to use.

**What the income layer earned against it.** October sold $44.2k of premium; the whole run $59.4k.
Realised put P&L was −$9,959 on IBKR's column. The assigned shares closed $62.1k under their strikes,
$54.6k after the $7.5k of premium kept on the 7 contract lines (38 contracts) that delivered them.
Since Oct 7 the EOD journal's `realized_pnl` printed between −$4.7k and +$3.7k a day while NLV fell $229k. The daily
headline measured premium, not the account [V, journal].

## 6. Positions at the end and the liquidation

### 6.1 The last pre-liquidation snapshot

`portfolio_snapshots` id 1028, 2026-11-18 18:45:40Z [V]. NLV $590,426; cash $17,688 (3.0%); excess
liquidity $421,664; maintenance margin $168,762.

| Stock | Shares | Avg cost | Price | Market value | % of NLV | Unrealised |
|---|---|---|---|---|---|---|
| AMD | 300 | $548.18 | $521.68 | $156,503 | 26.5% | −$7,949 |
| GOOGL | 500 | $345.88 | $283.81 | $141,906 | 24.0% | −$31,034 |
| NVDA | 800 | $225.16 | $152.25 | $121,797 | 20.6% | −$58,328 |
| BAC | 1,000 | $56.09 | $49.18 | $49,184 | 8.3% | −$6,903 |
| PLTR | 300 | $192.27 | $157.45 | $47,236 | 8.0% | −$10,443 |
| HIMS | 2,000 | $26.65 | $17.46 | $34,912 | 5.9% | −$18,388 |
| SOXL | 500 | $153.35 | $49.23 | $24,613 | 4.2% | −$52,061 |
| MARA | 1,000 | $11.64 | $6.62 | $6,624 | 1.1% | −$5,014 |
| **Stock** | | | | **$582,776** | **98.7%** | **−$190,121** |

Short puts, 12 contracts, $184.0k of strike: CRWD 225P (Nov 20) x1, 230P, 235P x1 each and 240P x3
(Nov 27), $141.0k; HOOD 65P x2 and 84P x3 (Nov 27), $38.2k; BAC 48P x1 (Nov 27), $4.8k. Their marked
value was −$10.2k. **Gross, nominal (stock plus put strikes, over NLV): 1.30.** Three names held
71.2% of NLV. The last envelope reading (18:15Z): S10 23.4% against an L(t) of 24.0%, S20 46.7%,
U_ew 1.39, T20 23.9%, cash after every in-the-money put is assigned −$103,012 [V]. Regime: SPY
`stressed`, QQQ `crisis` since Nov 18 [V].

### 6.2 The liquidation

The ledger booked it in full: **39 executions at 18:53:28-18:53:54Z** (ids 316-354, after the 19:01Z
restart) [V]. The `/halt` was at 18:52:03Z and the first flat snapshot at 19:01:47Z. The ledger tags
them all `manual`. Every share is accounted for, and the wheel's reconciler booked the 7 put
buy-backs (`fills` 137-143, `close_reason` `manual`) at 19:01:49Z.

| Stock | Shares | Average price | Gross proceeds | IBKR realised vs its cost |
|---|---|---|---|---|
| AMD | 300 | $521.14 | $156,342.00 | −$8,116 |
| GOOGL | 500 | $283.34 | $141,668.90 | −$31,278 |
| NVDA | 800 | $151.97 | $121,577.38 | −$58,555 |
| BAC | 1,000 | $49.09 | $49,090.00 | −$7,004 |
| PLTR | 300 | $157.63 | $47,289.00 | −$6,943 |
| HIMS | 2,000 | $17.41 | $34,820.00 | −$5,834 |
| SOXL | 500 | $48.74 | $24,372.00 | −$52,305 |
| MARA | 1,000 | $6.65 | $6,650.00 | n/a |
| **Total** | | | **$581,809** | **−$170,035** |

IBKR's all-time stock total is −$169,642, after a +$392 booked on Nov 6 when the HIMS short was
covered. Commissions on the stock were $48.51. The 12 put buy-backs: BAC 48P at $0.46, CRWD 225P at $2.89,
CRWD 230P at $7.65, 235P at $9.70, 240P (x3) at $12.40, HOOD 65P (x2) at $1.51, 84P (x3) at $15.25:
**$10,667 plus $7 of commissions**. Net cash from the liquidation: **$571,087**. The share prices
were within 0.4% of the 18:45Z marks, except SOXL (1.0% lower). How the orders were sent (TWS, order
type) is not in the ledger [U].

### 6.3 The final NLV

**$588,867** at the first flat snapshot (19:01:47Z), cash $588,734, margin zero [V]. The next
snapshot (19:16:48Z) reads $589,025 and is still flat. The $158 between them is all cash (total cash
rose by the same amount), so it is not a market move; the cause is not recorded [U]. From the start
that is −25.2%, from the peak −28.0%. The spec's "$585.8k" was the 18:00Z mark. The marks at 18:15,
18:30 and 18:45Z were $583.2k, $586.3k and $590.4k, so the booked $588.9k is inside the hour's range
[V].

## 7. What Claude did in Run 1

Facts only. Claude is enrichment under the core invariant; it placed, priced and gated nothing.

**The trade verdict.** Of 112 reviewed candidates in `verdict_ledger`, 85 were "sell", 14 "wait" (all
before Oct 1) and 13 had no verdict [V]. Since Oct 1: 79 "sell", 2 none, 0 "wait". The prompt says
"Default to 'sell' unless you can cite a specific FACT (F#) or NEWS item (N#) that argues otherwise"
(`src/claude/prompts/strategist.py`, still in the code at the boundary) [V]. Claude's priority
equals Python's rank in 92 of 99 comparable rows. The 55 closed "sell" rows total −$2,171 (35 wins):
since every candidate got "sell", that is the deterministic system's P&L, not the verdict's [V].

**`claude_cut`** (the one lever on size: it may lower, never raise, an opening CSP's contracts;
paper only). 11 rows, 10 real cuts, 34 contracts reduced to 14 [V, `sizing_actions`]. Every
rationale is "the book already holds the same or a correlated bet".

| Row | Day | Candidate | Deterministic to sent | The cut contracts, valued at expiry |
|---|---|---|---|---|
| 15 | Oct 23 | CRWD 235P Nov 6 | 2 to 1 | +$268 (forgone) |
| 29 | Oct 27 | CRWD 240P Nov 20 | 3 to 3 | not a cut: "a later review kept the deterministic size" |
| 30 | Oct 27 | NVDA 205P Nov 13 | 2 to 1 | **−$3,946 (avoided)** |
| 36 | Oct 28 | TQQQ 67P Nov 20 | 6 to 2 | 0 (the sent lot never filled) |
| 37 | Oct 28 | TQQQ 65P Nov 6 | 6 to 3 | −$699 (avoided) |
| 38 | Oct 28 | TQQQ 65P Nov 20 | 3 to 1 | 0 (never filled) |
| 39 | Oct 28 | TQQQ 66P Nov 6 | 3 to 1 | 0 (never filled) |
| 46 | Nov 2 | CRWD 225P Nov 20 | 3 to 1 | unresolved; closed at the liquidation |
| 48 | Nov 2 | CRWD 235P Nov 20 | 3 to 1 | −$2,074 (avoided) |
| 55 | Nov 9 | HOOD 75P Nov 20 | 3 to 1 | +$194 (forgone) |
| 73 | Nov 16 | HOOD 65P Nov 27 | 3 to 2 | unresolved; closed at the liquidation |

Five cuts carry a P&L: **$6,257 of loss avoided in net**, mean $1,251, SD $1,778, t = 1.57,
two-sided p ≈ 0.19 on 4 degrees of freedom [M]. Without the NVDA cut it is $2,310 (the spec's figure
at Nov 12) [S]. Four rows are TQQQ on one day, and the whole record is one regime. By the spec's own
standard (decision 22), this is not yet evidence. The deterministic stacking rule, switched on 20
minutes before the halt, covers some of the same ground.

**The value verdict.** 40 verdicts, 31 current. 30 value-book rows carry a Claude verdict: 26 match
Python's verdict and 27 keep Python's effective verdict; 4 disagree (ADBE deep_value and AVGO
quality_growth were attempted upgrades, ADBE's Claude READY ending as an effective WAIT; ISRG and META
deep_value were downgrades to NO) [V, `value.db`]. Five current verdicts are clamped by the 1.5x cap
on Python's fair value (GOOGL, MSFT x2, META x2), and Python's own fair values for GOOGL ($10.86) and
META deep_value ($12.00) are broken; the root cause is unverified [V, S]. The book placed no order.

**The spreads picker and plans.** §4.5.

**Cost** [V, `python -m scripts.claude_usage --since 2026-10-15`]. 919 headless calls, $23.43
notional, Oct 15 to Nov 18: trade reviews 107 calls ($4.16), roll reviews 282 ($3.30), the news kinds
about $13, the spreads picker 37 ($1.70), value 31 ($0.61).

## 8. Lessons

L1-L12 are the spec's (§2.4), re-checked against the data. **Status at the end of Run 1:** *addressed*
(the fix works as designed), *built, dormant* (code on `main`, not enforcing), *partly*, or *not
addressed* (with the spec section that plans it). Lessons the data shows that the spec missed are
marked **NEW**.

| # | Lesson | Evidence | Fix | Status at the end of Run 1 |
|---|---|---|---|---|
| L1 | No account-level limit | The nominal gross check (`gross_notional_cap`, added Nov 4 in `f79efbd`, replaced by U_ew in `cb55ddd` Nov 15) sat behind `vx.active`, which needs the value book on. No retained wheel verdict (Nov 4-18, 171,970 rows) carries it or any envelope reason [V]. **But the value book's own gate returned `gross_notional_cap` on all 9 of its buy proposals (Nov 5-17; 7 refused, 2 expired)** while the wheel kept selling puts [V]. Gross was 1.30 at the last snapshot; the envelope's first reading was Nov 18: S10 23.2-24.4%, S20 46.3-48.7%, U_ew 1.37-1.48 [V] | S10 and U_ew (envelope spec §3.4.1-2) | **Built, dormant.** `envelope_enforce` = `record`; the glide never started; the first reading was 0.4 points over L(t) and nothing was refused → Mastermind §6A P3 |
| L2 | Breakers stop openings, never inventory | 15 trips, none stopped an assignment; 8 assignment events [V]. The standing-drawdown leg re-halted every morning from about Oct 20 [S, memory], then was replaced Nov 5 (`544e32e`) [V] | slow breaker (E14), P5 escalation at 15% (R8) | **Partly.** The 3-session 6% window is live; the 20-session `slow_breaker` is `off`; **nothing bounds inventory** and no P5 code exists → §6A P5 |
| L3 | 70% of the loss came from buys no gate saw | −$163.4k of −$228.7k (71.4%); two of the buys on the peak day, one a 3x fund [V] | manual-buy display (E13, `75af220`); a gated `/buy`, `/sell` and a 5-point budget (R10) | **Display only.** The gated path is not built → §6A P4 |
| L4 | No mandate, no benchmark | The journal's daily realised P&L stayed within −$4.7k to +$3.7k while NLV fell $229k [V] | mandate R6 (β ≤ 1.0, drawdown ≤ 1.1x the 50/50), scoreboard (P1) | **Not addressed.** `src/reporting/scoreboard.py` does not exist [V] → §6A P1 |
| L5 | S10 15% at SPY −10% is 1.5x SPY's own loss | Config at the boundary: `s10_target_pct: 15.0`, `glide_weeks: 13`, no S20 key [V]. S20 was 46.7% [V] | R7: 10% by week 26 and S20 ≤ 25% | **Not addressed** in config or code → §6A P2 |
| L6 | Correlated concentration | Three names held 71.2% of NLV [V]. NVDA 205P/210P were assigned against 500 manual shares bought at $237.75 [V]. 12 CRWD puts were sold at four strikes (225-240) over three expiries, and 6 contracts with $141k of strike were still open at the end [V] | tech-linked cap, stacking rule (E15); R11 cross-book stacking; R12 universe | **Partly.** `stacking_rule` `on` (Nov 18 18:32Z, its narrow per-name form); `tech_cap` `off`; R11 and R12 not built. 8 of 20 `actively_wheeling` names are already outside `regime.tech_linked` (BAC, HOOD, SOFI, HIMS, VST, ASTS, BE, RKLB), most of them volatile [V] → §6A P4, P6 |
| L7 | Leveraged puts lost $11.0k; the manual SOXL is −68% | TQQQ −$6,964, SOXL −$4,078; 49 contracts stopped out; SOXL 500 bought at $153.35, sold at $48.74 [V] | leveraged CSPs barred outside the sleeve (`465ff29`), UPRO/DPST out, the sleeve and LES | **Addressed by design.** The last leveraged put was sold Oct 28, before the rule. The sleeve is `off`, LES is `record`; its Nov 17 reading was "trend break, no entry" [V] |
| L8 | Assigned and underwater stock earns nothing | 0 calls sold after Oct 15; 29,147 `strike_below_basis` rejections in the retained window (Nov 4-18) [V]; **0** `repair_proposals` rows [V] | E12 replay, repair proposals; `cc_basis_floor` | **Built, dormant.** `cc_basis_floor` was set to 0.90 at 19:01Z on Nov 18, after the book was flat → §6A P3 |
| L9 | Stored IV collapsed on stress days | QQQ stored IV 14.6% on Nov 5 against 22.4% the day before and 31.7% the day after; VIX closed 28.18 from 16.61 [V] | live greeks (H7); implausible-IV flag (`cd59708`) | **Built.** The flag is forward-only: no row is flagged, and Nov 5 was not back-filled [V]. The live-IV gate is dormant under `record` |
| L10 | Execution integrity | HIMS Oct 23 (§9): two rolls executed, +10 long Oct 30 28P and 20 short Nov 6 28P instead of 10 [V]. The Nov 10 spreads phantom (§9) | spreads late fills (`9da9e8a`); P8 unintended-position alarm | **Partly.** No alarm on a long option outside the hedge book, a short stock or an unexplained size exists in the code [V] → §6A P8 |
| L11 | Build order: books and Claude authority before a working limit | 571 commits from Sep 30 to Nov 13; the web overhaul (Parts 1-7), the value book (Parts 1-6), spreads, news and the ledger dominate. The only commits before Nov 14 that change when a halt trips are the breaker fixes (Oct 13, Oct 15, Nov 5) [M, keyword count] | hard line 12, the stabilisation gate (P7, R9) | **Not addressed.** No gate code exists → §6A P7 |
| L12 | Limits shipped with their own calibration warning | `risk_limits.yaml`: "Re-derive with `python -m scripts.capacity_report` before trusting them" beside `max_risk_units_per_ticker_pct: 5.0` and `..._sector_pct: 25.0` [V] | a ruling on the values | **Not addressed.** The report was fixed on Nov 18 (`488c315`); no ruling → §6A P3 |
| N1 | **NEW.** Run 1 was seven autonomous weeks, not five months | The system was off Jun 25 to Aug 11; its first autonomous fill was Sep 30; 36 sessions in all. The account tracked the 50/50 to the peak (+3.8% each) because it was 79% cash until Sep 23 [V] | label the evaluation window by autonomous sessions | Open. Do not read Run 1's 25% as five months of income-system behaviour |
| N2 | **NEW.** The ledger's `book` tag cannot separate manual buys from assignments | Every stock execution from a CSV or Flex statement is tagged `manual`, including all 8 assigned-stock rows (MARA, GOOGL, PLTR, HIMS, NVDA) and the system's own Sep 30 to Oct 5 option trades [V]. A scoreboard that excludes `book="manual"` (P1, P4 a) would drop −$62.1k of the system's loss and flatter it | attribute by execution code (`A`), `orderRef` and `fills`, not the tag | **Not addressed.** Fix before the scoreboard is built |
| N3 | **NEW.** The units break reached a breaker | On Oct 12 the drawdown leg compared a $786,836 NLV with an S$1,044,124 high-water mark: a 24.6% phantom drawdown that halted entries [V, `14cbf9a` message]. The spec says the break "never reached a breaker" [S] | USD high-water mark (`14cbf9a`) | **Addressed** for that input. Any breaker input needs a unit and level check |
| N4 | **NEW.** History was pruned, so Run 1 cannot be fully audited | `portfolio_snapshots` rows start Oct 19, `risk_verdicts` Nov 4, `envelope_snapshots` Nov 18; the journal has 40 rows; SGD rates exist for Jun 15 and from Sep 30 only [V] | a permanent daily NLV series (the scoreboard) and retention that keeps run records | **Not addressed.** L1's "never fired" cannot be checked before Nov 4 |
| N5 | **NEW.** "Autonomy full" in paper meant every gate-passed candidate traded and nobody reviewed | 243 approvals since Sep 30: 175 recorded `system`, 68 unattributed, none web or Telegram; no approval was ever rejected [V]. The other human lever was TWS | the earned ladder (Mastermind §5) | **Open.** Run 1 gives no evidence about a human-in-the-loop wheel |

## 9. Operational incidents

Facts and state only.

**HIMS +10 long put (Oct 23, error 103).** A roll of HIMS 28P x10 (Oct 30 to Nov 6) was first sent
on order id 1020 (order row 159, 13:48Z). IBKR returned "Error 103: Duplicate order id" at 13:51Z and
the row stayed `partial`, "Recovered from reqExecutions", with 3 of 10 contracts. A second order for
the same roll (row 160) filled all 10 at 14:22Z. The ledger then shows the first order's legs
executed as well, at about 15:18-15:34Z: 10 more Nov 6 28P sold, and 10 Oct 30 28P bought **to
open**, because no short remained [V]. (That the first order's legs executed late is an inference
from the times [M].) The account held **+10 long Oct 30 28P and 20 short Nov 6 28P**. The spec says
the operator found it by hand [S]. The long put was exercised on Oct 30 (−1,000 shares at $28); the
30 short Nov 6 puts were assigned (3,000 shares at $28). Net 2,000 HIMS shares, which closed at
$17.41. The dollar cost of the duplicate is not separable from the HIMS loss. State: no alarm for an
unintended long option exists (L10).

**The phantom drawdown (Oct 12).** The drawdown breaker compared a $786,836 USD NLV with an S$1,044,124
high-water mark stored before the account snapshot switched to USD (`099fd0a`, Oct 9): a 24.6%
phantom drawdown that halted every new-entry scan on Oct 12. The halt was also invisible: the scan
posted "Scan started" and then skipped, and the alert went to the main chat only [V, `14cbf9a`
message]. State: fixed on Oct 13 (a USD high-water mark, a visible halt, a watchdog check).

**Nov 10 spreads phantom close.** A profit-take close's cancel went unconfirmed; 2 lots filled 27
seconds later; `spreads.db` kept a 2-lot phantom, entries stayed blocked on the broker/database
mismatch through Nov 11-12, and alerts misfired. It was settled by hand (`scripts.spreads_resolve`;
paper row 12, `exit_reason` `resolved_by_hand`, closed Nov 12) [V, S]. State: late-fill booking fixed
in `9da9e8a`.

**Stored IV collapsing on stress days.** QQQ's stored IV: Oct 30 16.5%, Nov 4 22.4%, **Nov 5 14.6%**,
Nov 6 31.7%; VIX 19.4, 16.6, **28.2**, 25.6 [V]. A gate or a hedge mark that reads stored IV is
loosest on the worst day. State: a live-IV measurement and an implausible-IV flag exist; the flag
applies from Nov 14 and has flagged nothing.

**Stale daemons.** Processes do not hot-reload [V, memory]. (1) The daemons started Oct 14 at 21:23
SGT while the checkout was on `feat/web-overhaul-1`, which lacked the roll fix `cf379c6`, and ran it
after the merge: leveraged "never roll" text and pending GOOGL rolls returned. (2) The daemons ran
Oct 22 code for five days, so Claude was told the 10-year yield was 0.50% (real 4.98%) in every
picture and review; fixed in `353cdd8`, live after the Oct 28 restart. (3) On Nov 16 the launcher
found a stale process from a prior session and terminated it. (4) The risk-envelope code was not
merged until Nov 18 12:22Z and not running until the 12:30Z restart. That is not a daemon fault,
but it means the envelope was never live on any day of the slide. State: the activation ledger (§6A P3 e) that would block a stale
process's signals does not exist.

**Competing IBKR login (Nov 18).** Error 10197, "No market data during competing live session":
18:35:38Z and 18:46:40Z, each blocking a scan cycle [V, `approval.log`].
It coincides with the operator's session before the liquidation (the `/halt` followed at 18:52Z); the
text says another login holds the market-data entitlement and the cause is presumed, not
established [U]. Error 10197 appears on 15 local dates since Oct 8 (Oct 8, 9, 10, 13, 14, 15, 20, 23,
27, 29, 30; Nov 3, 12, 15, 19) [V]. State: a known nuisance; the scan is blocked for as long as it
lasts.

**IB Gateway credentials visible in `ps`.** The IBC launcher that starts the Gateway
(a `bash` process, started by `scripts.start`) carries the IBC user and password arguments on its
command line, with their `fix` twins beside them, and any local user can read a process list. Only
the argument names were listed here; no value was read or recorded [V]. State: visible; not fixed.

**Smaller items** [V].
- Fills row 21 (5 GOOGL 355C sold on Oct 7 at $1.22, "Recovered from reqExecutions", limit $2.73, no
  commission) has no execution in the ledger and no position in the Oct 7 snapshot. It sits in the
  `fills` table's CC premium ($610) and nowhere else.
- All 18 `campaigns` rows were set to `closed` at 19:17:21Z on Nov 18, all at once. The spec's P9
  expected an open campaign to survive a share sale; who or what closed them is [U].
- 25 roll orders were refused by the send-time re-gate (17 `roll_credit_collapsed`, 7
  `roll_net_below_floor`, 1 `roll_delta_increase`): the second gate doing its job.

## 10. What Run 2 changes

Run 2 starts from cash in the same account (R5), with the code on `main` at `4121b2d`. **At the
boundary, trading is halted** (operator `/halt`, 18:52:03Z, still in force when this was written),
autonomy is `full`, and the account is paper (the connection banner reads PAPER, port 4002).

**Switch states** (the `show` view of `scripts.envelope`, read-only, about 19:04Z on 2026-11-18) [V].

| Switch | Value | Source |
|---|---|---|
| `envelope_enforce` | **record** | default |
| `stacking_rule` | **on** | CLI, 18:32:30Z |
| `cc_basis_floor` | **0.90** (default 1.00) | CLI, 19:01:07Z |
| `leveraged_entry` | record | CLI, 18:23:23Z |
| `leveraged_sleeve`, `leveraged_cc_auto`, `index_1x`, `spreads_paper` | off | CLI, 18:23Z |
| `hedge_instrument`, `hedge_monetisation` | none | CLI, 18:23Z |
| `tech_cap`, `t20_limit`, `slow_breaker`, `bridge`, `spxw_ready` | off | default |

The glide "starts on the first session `envelope_enforce` reads on": it has **not started**, so with a
flat book the start level is the target (spec P9). The candidate-beta fix (`4121b2d`) is what lets a
put on a name not held be measured; the services restarted about 20 seconds after it merged, so
Run 2 starts on it [V]. A flat-book measurement has not been run [U]. Breakers: daily loss 3%, drawdown 6%
over 3 sessions, `slow_breaker` off. Private config: `s10_target_pct: 15.0`, `uew_target: 1.25`,
`glide_weeks: 13`, delta band 0.20-0.35, DTE 7-28, `max_large_positions: 2`.

**The operator's rulings (2026-11-19, Mastermind §0.5 and §16.0) and whether they are built at the
boundary** [V]:

| Ruling | What | Built? |
|---|---|---|
| R5 | End Run 1; liquidate; keep the account and databases; restart from cash | Done. No `run_boundary` command or row, no `reset-glide`, no `close-flat` (§6A P9) |
| R6 | Mandate: index-like risk while earning income; beat 50/50 SPY/QQQ buy-and-hold at the same risk (β ≤ 1.0, drawdown ≤ 1.1x); LES opportunities inside it | No scoreboard (P1) |
| R7 | S10 15% by week 13, **10% by week 26**; **S20 ≤ 25%** admission limit | Not in config |
| R8 | Escalation at a 15% drawdown in paper now; automatic de-risk at a 20% hard floor **before live** | Not built (P5) |
| R9 | Hard line 12; LES `on` and HP's paper application wait for the P7 stabilisation gate | No gate; LES `record`, HP not applied |
| R10 | `/buy`, `/sell` through `stock_orders.py`, 5-point S10 budget, TWS stays usable | Not built (P4) |
| R11 | Block a new wheel CSP at ≥ 10% of NLV held and > 2 ATR underwater; halve a smaller holding | Not built; the narrow per-name stacking rule is on |
| R12 | Universe review report; IV/realised ≥ 1.05 and liquidity bars; ≥ a third of `actively_wheeling` outside `tech_linked` | Not built; 8 of 20 names are already outside `tech_linked` |
| R13 | D1-D21 and H11-H16 adopted; Run 1 shown as one labelled line | The line's keys are in this record's front matter |
| R14 | Convert the value verdict to Python-built menus now | Not built |

**What re-anchors** (spec P9). The scoreboard's baseline NLV ($588,867), its high-water mark, the
slow breaker's and P5's windows, and every §11 evaluation window start at the boundary. Run 1 stays
queryable and is never mixed into Run 2's figures. The glide must not carry an anchor taken before
the liquidation (about 24%); none exists. **What this tests:** the envelope caps how much risk the
book holds; it does not make a single put less likely to be assigned (entry deltas are unchanged,
0.20-0.35). Single assignments will still happen; the wheel's answer to one (calls at the 0.90
floor, repair proposals) is the part still unproven.

## 11. Open questions Run 2 must answer

1. **Does the repaired book stay inside the mandate when it is enforced?** With `envelope_enforce` on
   from a flat start, is the 60-session beta to the 50/50 at most 1.0 and the drawdown at most 1.1x
   the benchmark's? Run 1's beta was 2.3 to the 50/50.
2. **How much income is there at S10 10% to 15%?** Run 1 sold $59.4k of gross premium on a book at
   1.3 to 1.5x gross. The envelope spec's estimate is that one S10 point admits $80-100k of 0.25-delta
   put strike earning $4.6-5.7k a year [S, M]; nothing in Run 1 tests it.
3. **What does the wheel do with the first assignment on a flat book?** In Run 1, assigned shares
   closed $62.1k under strike and earned no call after Oct 15. Do covered calls at the 0.90 floor and
   repair proposals ever fire (0 proposals in Run 1)?
4. **Does the stacking rule, now on, stop a pile-up?** Run 1 has no evidence: it was switched on after
   the last put was sold and the book was flat within 20 minutes.
5. **Do the canaries and the activation signals show life?** A control that never fires cannot be told
   from one that does not exist (§6A P3); none of that is built.
6. **Does the operator stay out of the book?** Run 1's manual stock was 71% of the loss. R10's gated
   path is not built; will Run 2 see a manual trade, and does the 5-point budget hold?
7. **Is the universe the right one?** 60% of `actively_wheeling` names are tech-linked. The names
   outside the group include HIMS, HOOD, ASTS, RKLB, SOFI and BE, which are volatile (their betas are
   not measured here [U]). R12's "at least a third outside `tech_linked`" test is already met (40%)
   and would not have prevented the HIMS loss [M].
8. **Does Claude's one lever pay when the stacking rule covers some of the same ground?** `claude_cut` avoided
   $6.3k on 5 cuts (p ≈ 0.19, one regime). Does the verdict ever say anything but "sell"?
9. **The value book:** the GOOGL and META fair-value fault is unresolved, and its gate returned the
   gross cap on all 9 buy proposals. Does a READY ever become a bought position, and does the
   capital-release path ever close a put?
10. **Can the record be audited?** Run 2 needs a permanent daily NLV series, the book tags by code and
    `orderRef`, and retention that outlives a month (N2, N4).

## 12. Figures that differ from the specs, what could not be verified, and the queries

**Differences, and which is right.**

| Figure | Spec | This record | Right one |
|---|---|---|---|
| Final NLV; return from start; from peak | $585.8k at 18:00Z; −25.6%; −28.3% | $588,867 flat at 19:01Z; −25.2%; −28.0% | This record: it is booked cash |
| The units break and the breakers | "the break never reached a breaker" | Oct 12: a phantom 24.6% drawdown halted entries (`14cbf9a`) | This record |
| MARA 1,000 | "from a pre-system manual put" | an approved queue order on Jun 24 (`fills` 1, approval 9); shares assigned Jul 17 | This record. The spec's grouping is kept for comparability (§5) |
| Manual share of the loss; the system's | −$162k (70%); −$69k (30%, 8.5%) | −$163.4k (71.4%); −$65.3k (28.6%, 8.0%) | This record: booked prices, not marks |
| The trough | $577.5k "session-end low" and −30.1% | close basis $571.1k (journal); intraday $566.4k (Nov 17 10:43 ET) | Both numbers are right; they are different series |
| `claude_cut` | 10 rows, 9 cuts, 31 to 12; $2,311, n = 4, p ≈ 0.37 | 11 rows, 10 cuts, 34 to 14; $6,257, n = 5, p ≈ 0.19 | This record (NVDA resolved, HOOD added) |
| "sell" verdicts since Oct 1 | 75 of 76 | 79 sell, 2 none, of 81 | This record (later date) |
| Priority equals rank | 88 of 95 | 92 of 99 | This record (later date) |
| Beta to SPY and QQQ | 2.74, 1.87 | 2.67, 1.90 (21 sessions); 2.63, 1.80 on the journal | Same conclusion; the series differs |
| Spreads baseline book | +$415 on 9 trades | −$3,371 on 15 trades | This record (six stops Nov 16-18) |
| Realised put P&L | −$10,169 | −$9,959 (−$10,657 with the liquidation buy-backs) | This record (a later date) |
| Gross cap "never fired" | no `risk_verdicts` row carries it | true for the wheel's rows; the value book's gate returned it on all 9 buy proposals | Both, for different books |
| Length of the test | "six weeks" | 36 autonomous sessions (seven weeks) | This record |

**Could not be verified.**

- The peak is the highest observed close; there is no Oct 8 row [U].
- SGD-era NLV conversions use one rate before Sep 30 (±$3k) [M]; the start-anchored attribution
  leaves $6.6k unexplained after interest.
- `risk_verdicts` and `portfolio_snapshots` are pruned, so "never fired" and the 15-minute curve
  cannot be checked before Nov 4 and Oct 19.
- The benchmark feed's last bar is 10:52 ET on Nov 18, about three hours before the account's final
  mark; the `_to_2026-11-17` windows are the clean ones [W].
- How the liquidation orders were sent; who closed the campaigns at 19:17Z; the cause of the Oct
  24-26 Gateway outage; the cause of the $158 cash difference between the two flat snapshots; and
  whether a flat-book envelope measurement works on `4121b2d` [U].
- The Oct 14 stale branch, the 10-year yield error, the Oct 24-26 Gateway outage and the operator
  finding the HIMS long put by hand are cited from the memory notes and the spec [S]. The mechanism
  of the HIMS duplicate (a late execution of the first order) is inferred from the times [M].

**Queries.** All read-only. Run them from the repo root.

```bash
T='file:data/income_system.db?mode=ro'
# the account curve (convert the SGD-era rows as in 3.1)
sqlite3 "$T" "select entry_date, json_extract(payload,'$.eod_summary.account.net_liquidation'), json_extract(payload,'$.eod_summary.account.captured_at') from journal order by id"
# the last pre-liquidation snapshot and the flat ones
sqlite3 "$T" "select id, captured_at, json_extract(account,'$.net_liquidation'), json_array_length(positions) from portfolio_snapshots order by id desc limit 6"
# the liquidation (the ledger booked it at 18:53Z on 2026-11-18)
sqlite3 "$T" "select id, trade_time, contract_ident, quantity, price, proceeds, commission, ibkr_realized_pnl from broker_executions where superseded_by is null and trade_time >= '2026-11-18 18:53' order by id"
# premium sold and bought back, spreads excluded
sqlite3 "$T" "select round(sum(case when quantity<0 then proceeds end)), round(sum(case when quantity>0 then proceeds end)), round(sum(commission)) from broker_executions where sec_type='OPT' and book!='spreads' and superseded_by is null"
# assignments
sqlite3 "$T" "select contract_ident, quantity, trade_date from broker_executions where codes like '%A;C%' and sec_type='OPT' and superseded_by is null"
# Claude's size cuts
sqlite3 "$T" "select id, action_day, underlying, strike, deterministic_contracts, sent_contracts, shadow_pnl_expiry, resolved_at from sizing_actions where kind='claude_cut' order by id"
# the spreads book and the value book's refusals
sqlite3 "file:data/spreads.db?mode=ro" "select mode, count(*), sum(realized_pnl_usd>0), round(sum(realized_pnl_usd)) from spread_positions group by mode"
sqlite3 "file:data/value.db?mode=ro" "select symbol, status, gate_json, created_at from value_proposals order by id"
```

The switch table is `.venv/bin/python -c "from scripts.envelope import _show; _show()"` from the repo
root. It prints and writes nothing; `python -m scripts.envelope show` calls `init_db()` first, which
this record avoided. The attribution and the benchmark tables come from short read-only Python
scripts over the same tables (Oct 7 `position_snapshots` marks, `broker_executions` flows, yfinance
adjusted closes pulled on 2026-11-18 [W]). `price_history` agrees with the yfinance series to within 0.2% from
Sep 24 on and differs from it by up to 0.8% before that, so the weekly table (price return, `price_history`)
and §3.2 (total return, yfinance) differ slightly for the early weeks.

## Evidence

This record is backed in two tiers, captured on 2026-11-19 (about 14 hours after the liquidation).

**Tier 1, committed and scrubbed: [`evidence/`](evidence/README.md) beside this file (about 4 MB).**

- `evidence/logs/` ([INDEX.md](evidence/logs/INDEX.md)): curated log excerpts, one file per incident or
  theme, each with a header naming the source file, the line range, why it matters and the section it
  supports. They cover the 17 breaker-trip lines (including the Oct 12 SGD/USD phantom trip), the
  HIMS error 103 and its recovery (Oct 23), the Nov 10 spreads phantom close, the usage-limit
  refusals, the Nov 18 error 10197 and Gateway restart, the halt and the liquidation window, the
  envelope's restarts, the Jun-Aug dormancy, the Sep 30 autonomy switch, the Oct 24-26 Gateway outage,
  the value book's refusals, the 10197 counts by date, the 24 commits the record cites and the config
  and prompt text it quotes.
- `evidence/data/` ([INDEX.md](evidence/data/INDEX.md)): CSV extracts read read-only from the Tier 2
  database copies, each with its source table, query, row count and columns. The NLV series (the
  journal, with the SGD-era conversion marked [M], and 960 portfolio snapshots recovered from the live
  table plus ten older database copies), the position
  snapshots, `broker_executions` (354 rows; the `account` and `raw` columns are dropped), orders,
  fills, campaigns, `sizing_actions` (including `claude_cut`), `risk_verdicts` (summarised by day and
  reason, plus the 1,304 gate-stage rows), `envelope_snapshots`, approvals (no message ids or
  bodies), the verdict ledger, the spreads positions, picks and day plans (no prompts), the value
  book's proposals and verdicts, SGD rates, SPY/QQQ/SMH/SOXX closes and the 919 headless-call usage
  lines behind section 7's cost.
- Scrubbed: the account number is `DU-PAPER`; no Telegram ids or tokens, credentials, prompts or
  addresses.

**Tier 2, local only and git-ignored: `data/runs/run-1/` on the operator's machine (about 450 MB).** It is
**not in the repository**. `logs/` holds a gzip copy of every file in `logs/` as it stood on
2026-11-19 (raw and **unscrubbed**: they contain the account number), and `db/` holds a consistent
`.backup` copy of `income_system.db`, `spreads.db`, `value.db`, `news.db` and `research.db`
(gzipped), plus `db/older-backups/`: ten older consistent copies of `income_system.db` (the daily
backups of Nov 10-18 and the pre-fix backups of Sep 30, Oct 1 and Oct 6) that still hold snapshots and
risk verdicts the live tables have since pruned. The manifest, with every file's size and sha256 and
the capture time, is `data/runs/run-1/MANIFEST.md`. If the machine is lost the raw files go with it; the Tier 1 extracts
are what survives in git.

Not backed by an excerpt or extract (listed in full in
[evidence/logs/INDEX.md](evidence/logs/INDEX.md)): the liquidation orders' route, who closed the
campaigns at 19:17:21Z, the Oct 14 branch state and the 10-year-yield error, the implausible-IV
flag's "flagged nothing", the yfinance total returns and the scripts for sections 3.3 and 5 (their
inputs are all in `evidence/data/`).
