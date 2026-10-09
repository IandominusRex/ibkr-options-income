# Live paper validation — August 2026

Answers the five questions in the design spec §7.4. Every default-off execution flag depends
on these; until they are answered, nothing in the execution path has been exercised against a
real broker.

> **Status: NOT YET RUN.** This file is a scaffold (Task 15 of
> `docs/superpowers/plans/2026-08-10-remediation-phases-1-3.md`). It requires TWS or IB Gateway
> running on the paper port (4002) with the API enabled, during regular trading hours, and a
> human tapping Approve/Reject in Telegram across several live sessions — none of that is
> agent-executable. A human operator must run Steps 2-8 of the Task 15 plan section and fill in
> this table with real observations, not summaries.
>
> **Checkpoint 2 (plan-level gate):** if Question 4 comes back 0% (`greeks_source == "ibkr"`
> never populates), that blocks 100% of live income trades. Do not proceed toward live trading
> until it is resolved, or `live_execution.require_ibkr_greeks_when_live` is deliberately set
> `false` with a written justification recorded below.

| # | Question | Answer | Evidence |
|---|---|---|---|
| 1 | Fill rate of a mid-price DAY limit over 5 min, by liquidity tier (n >= 20) | | |
| 2 | Does `reprice_enabled: true` amend work (same orderId)? | | |
| 3 | Is the BAG combo sign convention correct (negative limit = net credit)? | | |
| 4 | Does `greeks_source == "ibkr"` ever populate on this subscription? | | |
| 5 | Do Tier 3 names (SOXL, MARA, RGTI) produce candidates end-to-end? | | |

## Method

Paper TWS/Gateway on port 4002, API enabled, regular trading hours. Autonomy at `manual`.
Each question below records the raw observation, not a summary — a later reader must be able
to disagree with the conclusion.

### Q1 — fill rate
For every approved order, record from `OrderRow`: symbol, liquidity tier (Tier 1/2/3 per
`universe.yaml`), limit price, bid/ask at placement, and terminal state within
`fill_timeout_minutes`. Minimum 20 orders. Report fill rate per tier.

### Q2 — reprice amend
Order id, original limit, amended limit, whether TWS showed one order or two.

### Q3 — BAG sign
Screenshot or transcription of the working combo order in TWS, showing the net limit price
and its sign, before any fill.

### Q4 — greeks source
Count of quotes with `greeks_source == "ibkr"` versus `"black_scholes"` across one full scan,
from `logs/system.log`.

### Q5 — Tier 3 coverage
For SOXL, MARA, RGTI: number of quotes priced, and the gate that stopped each if none passed.

## Conclusions and config changes

One line per flag changed, with the question number that justifies it.

_(Not yet run — see Status note above.)_
