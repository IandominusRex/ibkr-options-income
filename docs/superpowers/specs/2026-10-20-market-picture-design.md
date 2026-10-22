# Market picture, regime sizing and the news expert — design

Date: 2026-10-20 · Status: operator-approved direction; revised after an adversarial Opus review
(same day); per-name dossiers and covered-call timing added the same day (decisions 25–30,
§16–§18); **revised again 2026-10-21** after a second Opus review and a replay of the real book
(decisions 31–39, §19 — where §19 and an earlier section differ, §19 and decisions 31–39 win) ·
Next step: implementation plan (superpowers:writing-plans).

## 1. Intent

Every `claude -p` call today starts from nothing. The full-universe trade reviewer sees one VIX line
plus the recent-news block (`strategist.py:504-519`); the roll reviewer sees no market context at
all; the longest look-back anywhere is five days; and the news editor labels a regime and groups
stories into threads for one digest, then throws that away. The news feed reads as scattered items,
and Claude's "why this trade" has no sense of the larger market.

The operator wants Claude to be **aware of the current state of the market** and to give sounder,
more grounded advice from the outputs the deterministic pipeline already produces:

- A **news expert** that keeps a persistent **market picture**: the regime, the few stories actually
  moving prices, what is noise, and what is coming. News posts become advice set against that
  picture, not isolated reports.
- Every other Claude call (trade review, roll review, spreads picker, EOD journal, `/scan`) **reads
  the picture**, so its explanation of a trade is grounded in the same view of the market.
- The system **trades less when conditions are bad**: in a stressed, falling market it opens fewer
  and smaller CSPs (3 TQQQ puts instead of 10), and waits for a lower price before adding to a name.

Purely additive: Claude never invents a trade, a strike, a price or an exit.

## 2. What the operator decided

From the brainstorm:

1. **Memory is the state of the market, not a record of past opinions or trades.** The
   `=== YOUR PRIOR RECOMMENDATIONS ===` block (`strategist.py::_format_history`) is removed from the
   prompt. (`ClaudeMemoryRow` rows may keep being written for the ledger; they are no longer injected.)
2. **A deterministic regime limits size in every autonomy mode** (§4–§5). Python classifies it;
   tables the operator edits in `risk_limits.yaml` turn it into limits; the Rules Engine enforces them.
3. **Claude may cut a CSP's size below the deterministic size in auto mode — never above it** (§9).
   "Auto mode" is any candidate `may_auto_open(underlying)` clears. In OBSERVE and MANUAL the card
   shows Claude's suggested size and reason as information only.
4. **The SPY spreads book is not under the regime limits**, even in crisis (confirmed after review:
   defined risk, its own gate). The spreads picker only reads the picture when choosing strikes.
5. **News is sorted into three piles, and meaningful news must not be lost** (§7).
6. **Dropped noise is visible, not overrulable.**
7. **In a clear downturn, the next lot on a name needs a lower price**, at a zone worked out from the
   ticker's own technicals, and the ladder lifts on a confirmed rebound (§6).
8. **Two regimes, SPY and QQQ**; tech-linked names use the stricter of the two.
9. ~~**Leveraged ETFs get the same treatment as every other CSP** — no separate table.~~ **Amended
   by decision 32:** leveraged ETFs (2× and 3×) get a smaller per-trade size in every regime.
   Assignment is still acceptable.
10. **Intraday escalation thresholds** as in §4.
11. **One "What Claude knows" page** (mockup option A).

From the review (operator agreed to every recommendation, 2026-10-20):

12. **The regime shrinks the whole book's budgets**, not just the per-trade size (§5).
13. **The regime is driven mainly by fast volatility signals**; trend may make it at most one notch
    stricter; it eases on a normalised VIX term structure, with a minimum stay per regime (§4).
14. **Crisis keeps a small allowance** (starting 10% of normal) instead of stopping new CSPs outright.
15. **Claude's cut is switched on in paper**, with a counterfactual record; reviewing that record is a
    condition of the live cutover (§9, §10).
16. **An off switch**: a config switch plus a Telegram command that suspends the regime limits for the
    rest of the trading day (§5).
17. **The news floor is held names plus today's alert rules**; universe-only stories are kept and
    visible on the page, not posted (§7).
18. **A proper support detector is built** for the ladder; the percent/ATR gap is its minimum and its
    fallback (§6).
19. **Seasonality stays (labelled weak); multi-week stories stay but their survival is decided in
    Python; page tiles show context only, "last ran" is deferred.**

From the review of the week of 2026-10-13 (§14):

20. **A name-level trigger puts a single name under the scale-in ladder in any market regime**: its
    own sharp fall, a near-the-money short put on it (decision 35), or a recent loss exit on it (§6).
21. **A near-the-money short put does not block the name.** It fires the ladder, so the next lot is
    accepted only at the next zone below. The loss exit keeps running unchanged. (Amended by
    decision 35: "in the money" became "near the money" — TQQQ 75P ×10 opened $0.12 out of the
    money against the 78P and escaped a strict in-the-money test.)
22. **No exit-timing rule.** The loss exit is not delayed after the open; the market can go either
    way, and one week of four exits is not evidence otherwise.
23. **The trade reviewer sees the book**: open positions (options and shares) on each reviewed name
    and its related names, and recent stop-outs on them.
24. **A deterministic bottoming signal** eases the regime one notch at once (market level) or lets a
    lot in at the current zone (name level), with strict guards; no signal, keep waiting (§6b).

From the per-name memory discussion (operator, 2026-10-20, after the research in §18):

25. **Every name the book cares about gets a dossier** — `would_own`, `actively_wheeling` and every
    held underlying (~33 names). It is the name-level counterpart of the market picture: the state
    of the name now, not a record of past opinions (decision 1 applies) (§16).
26. **Python writes every number in a dossier and recomputes it on every build; Claude writes only a
    profile (what the business is and what moves it, weekly), the current story (cited) and upcoming
    dated events (which Python verifies).** Previous prose is never fed back (decision 19 applies).
27. **Every trade review (CSP and CC), roll review and `/scan` reads the dossiers of the names it
    covers**, before it gives its verdict.
28. **A deterministic covered-call breakout rule:** after an upside breakout (with or without news), CC
    strikes are pushed out (next resistance, lower delta) for a few sessions. It never stops CCs on
    its own (§17).
29. ~~**Claude may hold a covered call, or restrict it to a pushed-out strike, only for a dated
    upcoming event inside the call's window.**~~ **Withdrawn by decision 34 (2026-10-21):** there is
    no Claude covered-call hold and no second exception to the core invariant. Verified events stay
    in the dossier as information for the reviewers.
30. **Claude may never hold a covered call** — not for a move that already happened (the research in
    §18 does not support "good news keeps rising" for large caps; that case belongs to the
    deterministic breakout rule), and since decision 34 not for an event ahead either. Earnings stay
    with the existing earnings blackout.

From the second review and the replay of the real book (operator, 2026-10-21; evidence in §19):

31. **The book's CSP budget still shrinks with the regime (decision 12 stands), with a guaranteed
    floor.** A small number of new CSP lots per governing index per day (starting `{cautious: 2,
    stressed: 1, crisis: 1}`) may exceed the *scaled* budget, never the *unscaled* one, sized at the
    per-trade ceiling. Bottoming-signal lots use the same floor. Without it, a full book (101% of
    deployable on 2026-10-20) turns any non-normal regime into a complete stop and makes decisions 14
    and 24 dead letters.
32. **Leveraged ETFs (2× and 3×) get a smaller per-trade size in every regime, tiered by stress**
    (revised the same day to a middle ground — §19): the per-trade ceiling is `hard_max × regime
    fraction × leverage fraction`, rounded down, never below one lot unless the regime's own ceiling
    is zero. The leverage fraction is **calm** (3× → 0.6, 2× → 0.8) when the name's regime is
    `normal` and no ladder trigger holds on it, and **stressed** (3× → 0.3, 2× → 0.5) otherwise. Its
    own switch; not suspended by `/regime off`. The leverage of each name is an operator-edited map in
    config.
33. **Claude's CSP cut stays applied in paper** (decision 15 stands), and **every time it overrides
    the deterministic size the override is recorded** with an exact counterfactual, so the operator
    can see whether not following the system pays. **In live it is record-only** (the size sent is
    the deterministic one, the cut Claude would have made is recorded) until the operator, having
    reviewed the record, switches it on. Every applied cut also gets a Telegram line, and a daily
    circuit breaker ignores further cuts (and says so) when Claude zeroes most of the day's auto
    CSPs.
34. **The covered-call event hold is cut**; the **deterministic breakout rule stays** (decision 28),
    with its delta guard fixed (decision 39).
35. **The ladder is fixed and its replay is a pass/fail gate:** a confirmed recovery counts only
    closes after the anchor lot's date; a *near-the-money* short put (spot ≤ strike + 0.5 × ATR-14)
    fires it; a loss exit on a name blocks new CSPs on that name for the rest of that ET trading day;
    the week-of-2026-10-13 replay must block SOXL 100P (Oct 13), TQQQ 75P and 70P (Oct 13) and TQQQ
    68P (Oct 14).
36. **Regime classifier corrections:** the 1-year VIX-percentile rule fires only at the 90th
    percentile **and** a VIX of at least 20; an intraday escalation expires at the close (the next
    day starts from the next day's daily base, with hysteresis on the base only); today's forming bar
    never enters a daily input; a "live" value exactly equal to the prior close is treated as stale.
37. **Dossier prose is rebuilt on change, not on age:** no dossier yet, a pile-1/2 cluster naming it,
    an alert on it, or earnings reported — never merely because the prose is old — at most once per
    name every 6 hours (alerts, earnings and new names excepted), under a cap of 4 calls a day. A
    reused review is keyed to the dossier's prose and events, not to the hourly fact refresh.
38. **The counterfactual record is made trustworthy before the live cutover relies on it:** one
    never-sent CSP row per name, kind and ET day; a skipped lot is valued both to expiry and under the
    system's own profit-take and loss-exit rules; a breakout row on a name where a covered call was
    still sold that day is reported as "pushed out", not "never sent".
39. **No empty delta band:** the bottoming-lot and breakout delta guards start at 0.25 and must be
    above the strategy's `delta_min` (0.20 today), checked when the config loads.

## 3. Goals, non-goals, anti-goals

**Goals**
- A shared, persistent market picture, rebuilt from fresh numbers, read by every Claude call.
- Long-horizon context: 1-, 3- and 12-month trend, drawdown, moving averages, volatility regime,
  rates, upcoming events, and seasonality (labelled a weak signal).
- Fewer and smaller new CSPs in bad regimes, across the whole book, automatically and testably; in a
  clear downturn, further lots only at lower, technically chosen prices.
- Not sitting out the recovery: the regime eases as volatility normalises, not weeks later.
- A news feed that reads as a coherent story, with nothing meaningful silently dropped.
- The operator can see what context each Claude call works from, and what every trim, block and cut
  would have earned at full size.

**Non-goals**
- Resuming `claude -p` sessions (`--resume`/`--continue`). Memory is stored data passed into
  stateless calls.
- Any learning loop from outcomes; any auto-tuning of thresholds, weights or limits.
- Changing roll sizes or blocking rolls (§5 exemption). Changing spreads sizing.
- Overruling noise from the UI.
- Per-decision "what Claude saw" receipts, call history, picture history UI, "last ran" on tiles.

**Anti-goals — failure even if it technically works**
- Claude can **raise** a size, open a trade the deterministic pipeline did not propose, or change a
  strike, price, expiry, exit or roll decision.
- A malformed, timed-out or fallback-model answer changes a size.
- The regime blocks a roll, a close, a profit-take or a loss exit.
- Meaningful news (anything today's alert rules fire on, or anything about a held name) disappears
  because Claude called it noise.
- The picture states a number that is not in the deterministic facts, makes an uncited claim, or
  overstates a weak signal such as seasonality.
- Claude's previous opinions about the market harden into "facts" by being carried forward.
- News posts or the picture tell the operator to buy, sell, add, reduce or hedge (existing rule).
- A backtest built on realised-vol premiums is cited as evidence the regime makes or costs money.
- Claude holds back, delays or moves the strike of a covered call (decision 34: no such power).
- A full book plus a non-normal regime stops every new CSP for weeks, so the crisis allowance and the
  bottoming signal can never fire (decision 31).
- Claude's cut silently zeroes the day's auto CSPs (decision 33: a Telegram line per cut and a
  circuit breaker).
- A dossier carries a number Python did not compute, an uncited story, or last week's prose.

## 4. The deterministic regime

**Classifier.** New deterministic-tier module (e.g. `src/analytics/regime.py`), run separately for
SPY and QQQ. Inputs come through `src/data/` providers (never `yfinance` directly). It must **not**
import `src/analytics/market_conditions.py` (enrichment tier;
`tests/test_eval_skills.py::test_macro_never_reaches_the_engine`).

Regimes: `normal`, `cautious`, `stressed`, `crisis`.

**What drives it** (operator decision 13). The regime is driven mainly by signals that move with the
market now, so it does not stay "bad" for weeks after a bottom:
- **Primary (fast):** VIX level and its 1-year percentile (the percentile counts only at the 90th
  percentile **and** a VIX of at least 20 — decision 36; at the 80th it fired on a VIX of 20.0 after a
  calm year, ~20% of days by construction); the VIX/VIX3M term ratio (above 1 =
  backwardation); the index's intraday move (escalation table below).
- **Secondary (slow), at most one notch stricter:** price vs 50-/200-day averages, drawdown from the
  52-week high, 1-/3-month returns, 20-day realised vol vs its 1-year average.
- **Easing:** the regime steps down only after the VIX term structure has been back in contango for
  N consecutive days (config), and only after a minimum number of days in the current regime
  (hysteresis, config). It eases one notch at a time.

**Daily base, intraday escalation.** The daily base is computed from daily closes before the open.
On every scan and again at send time, live moves can **escalate** it immediately. Escalation is
one-way within the day **and expires at the close** (decision 36): the next day starts from the next
day's daily base, and the easing/hysteresis rules apply to the base only — a single −2.5% QQQ day
must not hold tech names restricted for four sessions. Starting escalation thresholds
(operator-approved, config-tunable):

| Trigger | → `stressed` | → `crisis` |
|---|---|---|
| SPY move on the day | −2% | −3.5% |
| QQQ move on the day | −2.5% | −4% |
| Live VIX | 30 | 40 |

Moves of 1–2% leave the intraday regime alone.

**SPY and QQQ.** Every name uses the SPY regime; a **tech-linked** name uses the stricter of the two.
Tech-linked is an **explicit list in config** (the sector tags misclassify e.g. TSLL as consumer and
MARA as crypto). It lives in the file-only part of config, out of reach of the web, like `sectors`.

**Data freshness.** The classifier must know whether each input is live or a stale last close
(`market_conditions._fetch_index_level` silently falls back today, `market_conditions.py:74-85`). A
stale intraday input cannot escalate *or* be read as calm; it is reported as stale. Two concrete
rules (decision 36): a bar dated today (ET) never enters a daily input — the index provider's
`^VIX`/`^VIX3M` frames include today's forming bar (`yfinance_backend.py:54-56`) while
`price_data.get_ohlcv` does not; and a live value exactly equal to the prior close is treated as
stale, since yfinance's `lastPrice` carries no timestamp.

**State and ownership.** The trading process (`approval_service` / the scan) owns the regime. It
persists the daily base, the escalate-only intraday state, days-in-regime and the contango counter in
the trading database, so a restart cannot relax the regime mid-day. The check at the ~30-second order
poll uses a short cache. The news process reads the record read-only through `src.storage` (precedent:
`src/news/collectors.py:36`; add a fence test). The API reads it read-only for the page. `spreads_ai`
may not import `src.storage`, so it calls `src.analytics.regime` directly (deterministic tier, allowed)
or labels the picture's embedded regime as possibly stale. If the regime cannot be computed: last
known regime with a warning; it never blocks closing risk.

**Telegram notice on every regime change** ("QQQ regime → stressed: CSP budget 30%, at most N new
CSPs today"), in the trades/orders thread.

**Backtest limits.** `src/backtest` builds premiums from trailing realised vol, so it has no variance
risk premium and no skew. It may be used to show how often each regime occurred and what the index did
afterwards; it must not be cited as P&L evidence for or against the regime.

## 5. Regime sizing

**The book's budgets shrink by regime** (operator decision 12). A regime multiplier is applied inside
`src/engine/capital.py::resolve_caps` to the CSP book budgets — `max_csp_allocation_pct_of_deployable`
and `max_risk_units_per_ticker_pct` (and the sector risk-unit budget if the builder finds it needed).
Because the generator (`capital.max_contracts`) and the gate (`risk_engine.validate_candidates`) both
go through `resolve_caps`, they stay in agreement automatically.

**A regime limit on new CSPs per day**, alongside `max_auto_trades_per_day`, which today ignores the
regime (`config/examples/settings.yaml:413`). It counts manual and auto opens.

**The per-trade ceiling stays as a second layer**: `floor(hard_max × fraction)`, size =
`min(capital-fitted size, ceiling)`.

Starting table (config; covered calls carry no limit — they sell against shares already held):

```yaml
regime:
  enabled: true
  csp:
    budget_multiplier:   {normal: 1.0, cautious: 0.7, stressed: 0.4, crisis: 0.1}
    per_trade_fraction:  {normal: 1.0, cautious: 0.6, stressed: 0.3, crisis: 0.1}
    max_new_per_day:     {normal: null, cautious: 6, stressed: 3, crisis: 1}
  thresholds: { ... }        # per index: fast/slow signals, escalation, easing, hysteresis
  tech_linked: [QQQ, TQQQ, ...]
```

**Crisis keeps a small allowance** (operator decision 14), so the system is not wholly out of the
market in the post-panic window, when puts have historically paid best.

**The guaranteed floor** (decision 31). The book is normally full: on 2026-10-20 short-put collateral
was $427.6k against $424.9k deployable (101%). Scaled by 0.7 / 0.4 / 0.1 that leaves −$130k /
−$258k / −$385k of headroom, so without a floor every non-normal regime is a full stop until the
existing puts expire (1–4 weeks), and the crisis allowance and the bottoming signal never matter.
So: up to `floor_new_per_day` new CSP lots per governing index per day (starting `{normal: 0,
cautious: 2, stressed: 1, crisis: 1}`) are allowed when the **only** thing stopping them is the
regime-scaled budget — they must still fit every **unscaled** cap, the per-trade ceiling and the daily
limit. Bottoming-signal lots (§6b) draw on the same floor. Floor lots are recorded (§10).

**Leveraged ETFs** (decision 32). The per-trade ceiling for a name in `universe.yaml →
leveraged_etfs` is `floor(hard_max × regime fraction × leverage fraction)`, at least 1 unless the
regime's own ceiling is 0. The leverage fraction has two tiers:

| Tier | When | 3× | 2× | A 10-lot TQQQ put becomes |
|---|---|---|---|---|
| calm | the name's regime is `normal` and no ladder trigger (§6) holds on it | 0.6 | 0.8 | 6 |
| stressed | the name's regime is not `normal`, or any ladder trigger holds | 0.3 | 0.5 | 3 (1 in cautious) |

Why tiered: a flat 0.3 cost about half the leveraged-ETF premium in the replay and was roughly
break-even on P&L, because the protection it buys is against tail and gap losses (a 3× ETF gapping
20% through an $80 strike costs ~$1,600 a contract — $16k on 10 lots, $9.6k on 6, $4.8k on 3), and
those cluster when the name or the market is already falling. The calm tier keeps ~71% of the
premium; the stressed tier keeps the full protection where it matters. The honest gap: a first lot
opened before any trigger (TQQQ 78P on 2026-10-07) gets the calm tier. Each name's leverage is an operator-edited map in
`risk_limits.yaml`; a listed leveraged ETF missing from the map is treated as 3× (the strictest) with
a warning. The rule has its own switch and is not suspended by `/regime off` (it is not a regime
limit). Rolls are exempt. Trims are recorded with their own kind (§10), so the operator can see what
the smaller lots cost or saved.

**Exempt: rolls, closes, profit-takes, loss exits.** Rolls go through `validate_candidates`
(`roll_pipeline.py:395`), where `contracts_exceeds_max` (`risk_engine.py:231-233`) applies and
`roll_contracts_mismatch` forces the same contract count. A naive regime cap would reject every
defensive roll in a stressed market. All regime checks are scoped out with `is_roll`, exactly as the
income gates are, with a test.

**Distinct reasons.** A trade limited or stopped by the regime says so (`regime_budget`,
`regime_ceiling`, `regime_daily_limit`), not "no headroom"/"insufficient cash"
(`cash_secured_put.py:160` today maps every <1 contract to those).

**Escalation between card and send:** the order is **trimmed down** to the current limit, never up;
if that is 0 it is rejected with the regime reason, and the order notification says so. A deliberate
exception to the gate's usual reject-don't-trim behaviour, because trimming only reduces exposure.
Opening orders already working at the broker when the regime escalates: builder to decide whether to
cancel/reduce them; at minimum the operator is told.

**Off switch** (operator decision 16): `regime.enabled` in config, plus a Telegram command that
suspends all regime limits for the rest of the trading day (it resumes automatically at the next
day's base). Not on the web. The suspension is logged and shown on the page.

## 6. The scale-in ladder: the next lot needs a lower price

In a clear downturn, a further CSP lot on a name the book already holds is accepted only once the
share price has fallen into a **target zone** worked out from that ticker's own technicals. If the
stock instead rebounds with upside momentum, adding is allowed again.

**When it applies.** Not for rolls. It applies to a name when **either**:
- the name's market regime (SPY's, or the stricter of SPY's and QQQ's for a tech-linked name) is
  `stressed` or `crisis` (per-regime switch in config); **or**
- a **name-level trigger** fires (operator decision 20), in any market regime:
  - the name's own sharp fall (e.g. a drawdown of X% over N sessions, or its 20-day average falling
    below its 50-day by Y% — thresholds in config, scaled by the name's ATR so a 3× ETF is judged on
    its own volatility);
  - the book holds a **near-the-money short put** on the name — spot at or below strike + 0.5 ×
    ATR-14 (operator decisions 21 and 35: this does not block the name; it makes the next lot wait
    for the next zone below);
  - a **loss exit** on the name within the anchor's survival window.

**Same-day block after a loss exit** (decision 35). A loss exit on a name blocks every new CSP on
that name for the rest of that ET trading day (reason `loss_exit_cooldown`), whatever the zone says.
The re-entries of the week of 2026-10-13 came 18–55 minutes after the stop-outs.

Why (the week of 2026-10-13): SOXL fell 43% and TQQQ 19% while the VIX stayed under 23 with the
curve never inverted. A market-only regime read SPY as `normal` all week; the damage came from
re-entries on the same names within an hour of a stop-out and from adding 10 lots while a 10-lot
put on the same name was in the money.

The name-level trigger lifts on the same confirmed-recovery rule below, or once its condition has
cleared (the put is closed or out of the money, the window has passed, the fall has reversed).

**A new support detector** (operator decision 18). The existing `_support_resistance`
(`technicals.py:229-248`) cannot carry a gate: it uses closes, not lows; it needs ±30-bar local
minima, so a level only appears ~6 weeks after it forms; it keeps the 3 most *recent* levels, not the
nearest below the price; and after a fresh selloff its levels are the uptrend's higher lows, all
above spot. Build a deterministic detector for the ladder: swing lows on daily **lows** over shorter
and longer windows, merged when close together, returning the levels **below the current price**,
nearest first. The existing function stays for its current display uses (or is replaced if the
builder shows the new one is better everywhere).

**The zone:**
- Anchor: the underlying's price at the fill time of the most recent CSP lot on that name, taken from
  `price_history` (this also covers hand-placed positions, positions known only from the broker
  ledger, and positions opened before this feature — the cold start).
- Minimum gap below the anchor: the larger of a regime-scaled percentage (e.g. 5% in `stressed`) and
  a multiple of ATR-14 (wider for a 3× ETF automatically).
- Target: the nearest detected support at or beyond the minimum gap, ±0.5 × ATR-14.
- Broken support: a daily close more than ~1 × ATR below a level removes it; the zone moves to the
  next level down.
- Fallback when no usable support exists: the minimum gap itself. (`IdealZone.buy_below` and the
  50/200-day averages are **not** used: `buy_below` is recomputed below the current spot every scan,
  so it can never be reached, and the averages are already above price in a downturn.)
- At or below the zone, the next lot is allowed, still under the regime limits. It becomes the anchor
  for the one after.

**Anchor lifecycle.**
- The anchor survives a profit-take or loss exit for N days (config), so a loss exit cannot clear it
  and let the next scan re-sell at full size (churn).
- Assigned shares count as a lot (the assignment price is the anchor).
- Rolls do not move the anchor.

**The rebound exit.** A deterministic **confirmed recovery** lifts the ladder for that name: N
consecutive daily closes (e.g. 2) above its 20-day average **and** above the support that last broke
(or the anchor). **Only closes dated after the anchor lot's fill date count** (decision 35): on
2026-10-13 and 10-14 the two closes *before* the anchor was set satisfied the rule and lifted the
ladder for exactly the TQQQ re-entries it exists to stop. The ladder lifts for every name when its
regime returns to `normal` or `cautious` (a name-level trigger still holds it).

**Enforcement.** One pure deterministic-tier function, used by the generator and the gate
(the `capital.py` rule), enforced at decision and send time with the reason
`scale_in_zone_not_reached`. The card and the page show the zone ("next lot: $47–49, at support
$48"); Claude explains it but cannot move it. Support levels also appear on cards for information.

## 6b. The bottoming signal: look for the opportunity, don't sit out

Operator's decision (2026-10-20, decision 24): in a fast drop the system must not simply wait for the
slow easing rules. Every scan it looks for a deterministic sign that a bottom is forming; if one
fires, it loosens one notch; if none fires, it keeps waiting. The signal is plain Python (it
loosens a limit, so no LLM may produce it). Claude explains it on the card and the page and, in auto
mode, may still only cut.

**Market-level signal** (per index, SPY and QQQ), all of:
- after a VIX spike (the VIX rose at least X% over N sessions, config), the live VIX is at least ~15%
  below that spike's peak;
- the VIX/VIX3M ratio is back below 1 (no longer inverted), if it inverted during the spike;
- the index is holding above the low of the selloff's lowest day (a higher low).

Effect: that index's regime **eases one notch immediately** (e.g. `stressed` → `cautious` sizes and
budgets), instead of waiting for N days of contango and the minimum stay. Never more than one notch,
never straight back to `normal` from `crisis`. Intraday escalation still applies: a fresh breach of
an escalation threshold cancels the signal for the day.

**Name-level signal**, all of:
- the price is inside one of the name's detected support zones (§6 detector);
- RSI-14 was below 30 within the last N sessions and has turned up (today's RSI above yesterday's);
- the last daily close is above the prior day's high.

Effect: a lot is allowed at the **current** zone without waiting for the next zone down, still under
the (possibly eased) regime limits.

**Guards on any lot opened on either signal:**
- every existing gate still applies (earnings, `min_credit` / VRP, IV floors, concentration, risk
  units, regime budgets and daily limit);
- delta at the low end of the strategy's range (config, starting at most 0.25 instead of the normal
  0.35 maximum; it must stay above the strategy's `delta_min`, 0.20 today, or no lot could ever
  pass — decision 39);
- it uses the guaranteed floor (§5) when the scaled budget is full;
- at most one signal lot per name per N sessions (config);
- it becomes the new ladder anchor, so if the bottom fails the next lot needs the next zone down;
- each is tagged `bottoming_signal` in the order snapshot and the counterfactual record (§10), so the
  operator can see whether these lots pay.

**Known interaction to check:** the VRP gate prices fair value at HV30, which stays high for weeks
after a spike while IV falls back, so `min_credit` may reject exactly these lots. The builder
measures this on the week of 2026-10-13 and reports it; changing the gate is an operator decision,
not part of this build.

## 7. The news expert and the three piles

Today: deterministic triggers (`src/news/triggers.py`) fire alerts; deterministic `noise_terms` drop
law-firm spam; the digest editor (`news/prompts.py::editor_prompt`) sees only the first 25 clusters
(`service.py:319`), labels a regime, picks threads and silently drops clusters. The feed is roughly
1,400–1,600 clusters on a weekday, and ~57% of items name a universe ticker.

**The three piles**, each with a one-line reason:
1. **Shapes the picture** — a market-wide, persisting story. Starts or extends a picture story and is
   posted.
2. **Worth telling you** — real news that does not change the picture. Posted, framed by the picture.
3. **Noise** — not posted; kept with its reason and shown on the page.

**Deterministic first.** Python pre-sorts before any LLM sees a cluster (trigger hits, held names,
macro/econ categories, source counts, topic tags) so the LLM triages a bounded, ranked batch. The
store distinguishes **judged noise** (Claude saw it and gave a reason) from **not reviewed** (most
clusters); the page shows both, labelled.

**What "posted" means:** an individual Telegram alert only for what today's deterministic triggers
fire on, plus safeguard-2 promotions, under the existing hourly cap. Otherwise piles 1 and 2 appear in
the next digest (pile 1 also in the picture). Pile 3 appears only on the page.

**Safeguard 1 — the floor** (operator decision 17). Anything today's alert rules fire on is posted.
Any story about a **held** name is at least pile 2. Claude may only move a story up from its floor.
Stories about names that are only in the universe are kept and visible on the page, not posted unless
Claude promotes them.

**Safeguard 2 — the market-reaction check.** For a judged-noise story, measure the relevant move after
it was first seen (reusing `src/news/reaction.py`): for a ticker story, the ticker's **beta-adjusted**
move (its move net of what the index explains); for a macro story, SPY/QQQ. Above a threshold, the
story is promoted and posted late: *"Dismissed earlier; the market moved X% after it. Cause not
confirmed."* Promotions are capped per window and deduplicated, so one index move cannot promote
every dismissed story at once.

**Budget.** Recent use is 5–19 news LLM calls a day against `max_calls_per_day: 40`. Selloff days are
when alerts spike, which is exactly when the picture matters most, so a share of the daily budget is
**reserved** for picture rebuilds and triage. Builder sets the split and the batch timing.

**The editor's own regime label** (`EditorOutput.regime`) is replaced by the deterministic SPY and
QQQ regimes, so no LLM-made regime exists.

## 8. The market picture

**Written by** the news process (`scripts/run_news.py`), stored in `data/news.db` as a new `NewsBase`
table (only `src/news/` writes it — news-fence rule 3).

**Contents**
- The SPY and QQQ regimes (read from the trading process's record, §4) and the numbers behind them,
  plus rates (10-year and its 1-month change), dollar, oil and gold where `src/news/facts.py` already
  has them.
- Seasonality: e.g. SPY's average return for this calendar month over the last 5 years (the price
  provider's limit; the first draft said 20) and the share of up years, **always labelled a weak
  signal**.
- Upcoming scheduled events (FOMC, CPI, payrolls, held-name earnings).
- **Stories**: up to ~5, each with a stable id, title, start date, supporting cluster ids, and a short
  Claude-written description.
- Judged noise and not-reviewed counts for the last 7 days, and any safeguard-2 promotions.

**Avoiding self-reinforcement** (operator decision 19):
- All numbers are recomputed by Python on every rebuild.
- **Story survival is decided in Python**: a story stays alive only while at least k validated new
  cluster ids attach to it within a window, matched by ticker/topic-tag overlap. Claude cannot keep a
  story alive by finding something loosely related. Story identity (id, title, start date) carries
  over; previous prose is never re-fed.
- **Every story must cite evidence ids** (clusters/facts), like the explainer's "withheld if uncited"
  rule (`explain.py:101-108`); an uncited story is dropped from the rebuild.
- Every number is checked by `src/news/grounding.py` (note: it checks numbers only and exempts small
  bare integers, `grounding.py:44` — the evidence-id rule covers causal claims). A failing rebuild
  keeps the previous picture and marks it stale.

**Cadence:** rebuilt at the pre-market and close digests, and intraday when a batch puts a new story
in pile 1, capped per day within the reserved budget. Model: `news.llm.model` (Sonnet). If the
picture is older than a staleness limit, readers are told so and still get the deterministic regime.

## 9. Who reads the picture, and Claude's size cut

A compact rendering (a few hundred tokens, so the local Ollama fallback still fits) is added to:

| Call | Today | After |
|---|---|---|
| Trade review, full universe (`strategist.py`) | VIX line + news block + prior recommendations | + picture + regime and limits; prior recommendations removed |
| `/scan TICKER` | macro block + sector + news | picture replaces/extends the macro block |
| Roll review (`prompts/roll.py`) | position, quote, deterministic proposal | + picture; still only agrees/disagrees |
| Spreads picker (`src/spreads_ai/`) | macro, SPY technicals, 6h headlines, prints | + picture; still only a menu letter |
| EOD journal (`prompts/eod.py`) | today's facts | + picture |
| News writer/digest passes | per-item facts | + picture |

**The trade reviewer also sees the book** (operator decision 23): for each reviewed name and its
related names (tech-linked list / sector), the open short options (strike, expiry, in or out of the
money), shares held and cost basis, and stop-outs in the last N days, plus the book's net delta. In
the week of 2026-10-13 the reviewer said "sell" on all 12 TQQQ/SOXL candidates with none of this in
its prompt, while the EOD journal (which did see the day's trades) flagged the re-selling.

Readers read `news.db` read-only (`src.news.store.readonly` + `queries`). Rendering lives on the
enrichment side (e.g. `src/claude/`), never in `engine/`, `execution/`, `strategies/` or `spreads/`.

**Claude's size cut** (operator decisions 3 and 15):
- `ClaudeReview` gains an optional integer `max_contracts`, a short `size_reason`, and a persisted
  **`backend`** field (cli/ollama), so a reused Ollama review is recognisable.
- The prompt states the deterministic size, that **the regime limits already price the regime**, and
  that a cut is only for information specific to this name or this trade (an event inside the
  window, a thesis-breaking story) — not for the regime itself, which would count it twice.
- Applied in the **auto branch of `src/notify/sender.py`** (the split at `sender.py:300`, before the
  snapshot is frozen at `:420`), not in the orchestrator, so the card and the size never disagree
  when autonomy changes. Formula: `min(deterministic size, max_contracts)` — the deterministic size
  already includes every regime limit — through a small pure function taking plain integers (the
  engine never imports `src.claude`).
- `0` means "not now": the candidate is not queued. This deliberately lets Claude block an auto trade,
  which today's "never gating" note on `ClaudeReview` (`schemas.py:523`) forbids; the note is amended.
- **Ignored, using the deterministic size**, when: the field is missing, non-integer, negative or above
  the deterministic size; the review failed or timed out; the review's backend is Ollama.
- CSPs only. Rolls and CCs are never cut.
- `_review_fingerprint` (`scan.py:355`) includes the deterministic size, the regime limits, the regime
  and the picture version, so a reused review's cut is never older than what it was based on.
- In OBSERVE/MANUAL the card shows "Claude suggests N of M" and the reason; approval sends M.
- **Switched on in paper from the start**; reviewing the counterfactual record (§10) is a condition
  of the live cutover (add to `STATUS.md`'s live-cutover gate).
- **Mode by account** (decision 33): `claude_cut.apply_in_paper: true`, `claude_cut.apply_live:
  false`. When the cut is not applied (live, until the operator flips it), the deterministic size is
  sent and the cut Claude would have made is still recorded (kind `claude_cut_unapplied`), so the
  same question — does not following the system pay? — keeps being answered without risking the
  live book.
- **Every override is recorded, and only overrides:** a review that keeps the deterministic size
  writes no row. A partial cut is valued exactly (withheld contracts × the traded contract's realised
  P&L per contract); a cut to 0 is shadow-valued (§10).
- **Visible:** each applied cut adds a line to the auto summary ("Claude cut TQQQ 65P 3 → 1: <reason>");
  a cut to 0 says "not sent".
- **Circuit breaker:** when Claude has cut to 0 at least `breaker_min` (4) auto CSPs and more than
  `breaker_pct` (50%) of the day's reviewed auto CSPs, further cuts that ET day are ignored (recorded
  as `claude_cut_unapplied`) and one Telegram alert says so — a prompt or schema regression cannot
  silently stop the book.

**This reverses two written rules, by the operator's decision.** The builder amends them and their
tests rather than working around them:
- `CLAUDE.md` core invariant → Claude may lower, never raise, the contract count of an auto-opened
  opening CSP, through one clamped integer path; it still never places, prices or sets any other
  field.
- News-fence rule 4 / news spec D3 → the same narrow exception.
- New tests: the cut never exceeds the deterministic size; malformed/failed/Ollama → deterministic
  size; the engine imports nothing from `src.claude`/`src.news`; rolls and CCs untouched; spreads
  sizing unreachable. Existing fence tests stay green.

## 10. The counterfactual record

Every regime trim (budget, per-trade, daily limit), leveraged-ETF trim, floor lot, ladder rejection,
loss-exit block, Claude cut (applied or not) and breakout block is recorded with: the deterministic
size it would otherwise have been, the size actually sent (or 0), the reason, the regime, the
picture version, and later the outcome. For partial cuts the counterfactual is exact (the extra
contracts × the traded contract's per-contract P&L). For trades not sent at all, the skipped contract
is **shadow-valued twice** (decision 38): to its expiry, and under the system's own profit-take and
loss-exit rules (Black-Scholes on daily closes at the entry IV) — marking to expiry alone ignores the
loss exits, which on 2026-10-16 cost $3.2k against $14.8k at assignment, and so flatters every block
made in a selloff. Never-sent CSP rows are keyed per name, kind and ET day (one row however many
strikes or cycles were rejected); a breakout row on a name where a covered call was still sold that
day is reported as "pushed out". Lives with the verdict ledger under `src/claude/eval/` (read by a human,
never fed back; the fence holds). A `scripts/` report summarises it; the page can show a one-line
total later.

## 11. The "What Claude knows" page

A new read-only web page reached from **More** (mockup option A):
- **Top:** the market picture — SPY and QQQ regimes and their limits, whether the limits are
  suspended today, the numbers behind them, the stories with start dates, seasonality labelled weak,
  upcoming events, when it was rebuilt and whether it is stale.
- **Tiles:** one per Claude call, showing which context blocks it receives. ("Last ran" deferred.)
- **Dropped:** the last 7 days of judged noise with reasons, a count of not-reviewed clusters, and
  safeguard-2 promotions.

The API reads `news.db` only through `src/api/news_db.py` and the Session-parameterised queries, the
trading DB read-only as today, and adds no write. UI work goes through the `da-vinci` skill and
`web/DESIGN.md`.

## 12. Constraints

- All fences in `CLAUDE.md` stay green except the two deliberate amendments in §9.
- Regime, sizing, ladder and support detector are deterministic tier; picture, triage and rendering
  are enrichment tier.
- News LLM calls stay within `news.llm.max_calls_per_day`, with a reserved share for the picture.
- Every new config key goes into `config/examples/*.yaml`; private configs are never committed.
- Docs per the `CLAUDE.md` update table (ARCHITECTURE, STATUS incl. the live-cutover gate, SETUP,
  README for the new Telegram command).

## 13. Token budget

Calls stay slim and stateless (`claude.slim_context`, run from `claude.workdir` outside the repo):
memory is data in the prompt, never a resumed session, so the ~40K-token ambient overhead removed on
2026-10-15 does not return. Estimates (to be measured with `scripts.claude_usage` after each phase):

**Re-estimated 2026-10-21** against the measured baseline (`scripts.claude_usage`, 2026-10-16..21: 98
calls, ~365K context tokens, **~61K context tokens a day**, range 25K–178K; a trade review is ~6.7K, a
roll review ~1.15K, an editor pass ~3.2K). The earlier "+20–40%" undercounted the fixed daily cost of
the news-side calls.

| Call | Arithmetic | Added per day |
|---|---|---|
| Trade review | +1.5–2.5K per call (picture ~400, book 500–1,000, ≤ 8 compact dossiers × ~100, size text; less the removed history) × ~6.5 calls | +10–16K |
| Roll review | ~5.5 calls × ~650 (picture + full dossier) | +3.5K |
| Spreads picker, EOD journal | 2 × ~400 | +0.8K |
| News: triage | ~5 batches × ~4.5K | +22K |
| News: picture rebuilds | 2–4 × ~5K | +10–20K |
| News: dossier prose (§16, decision 37) | 1–4 calls × 5–9K (on-change rebuilds, cap 4) | +5–36K |
| News: editor pass removed | −1.5 × 3.2K | −5K |
| **Total** | | **≈ +45–95K a day** |

That is about **1.7–2.5× a typical day** and +25–55% on a busy day (22 reviews). In notional
dollars it is under $1 a day; the real constraint is the subscription's weekly usage limit, which
the headless calls share with interactive sessions. Levers already in the design: one shared
compact rendering of the picture; deterministic pre-sorting so triage sees a short ranked batch;
review reuse keyed to the prose, not the hourly facts (decision 37); dossier prose on change only.
The builder records measured numbers per phase in the plan's Progress log.

## 14. Evidence: the week of 2026-10-13

- SPY −2.0%, QQQ −6.6%, TQQQ −19%, SOXL −43% (Oct 6 → 16); VIX peak 22.3, VIX/VIX3M never above 1.
- Realised options P&L on that week's closes ≈ −$3.9k; all loss exits (−$7.8k) were TQQQ/SOXL.
- Held shares (SOXL/AMD/NVDA/BAC/MARA/GOOGL) went from +$3.8k to −$59k unrealised (Oct 9 → 16):
  the largest risk, and out of this design's scope (no stock-risk management is proposed here).
- Loss exits vs assignment: the two puts that expired Oct 16 (TQQQ 78P ×10, SOXL 130P ×2) lost
  $3.2k by exiting vs ≈$14.8k marked at assignment. The other five were roughly even. Exits stay.
- Re-entries 18–55 minutes after stop-outs on the same name, and TQQQ 75P ×10 opened while TQQQ
  78P ×10 was in the money; ≈$3.9k of the loss exits came from such entries → §6 name-level trigger.
- **Separate bug, not part of this design:** two exits on Oct 15 were the roll policy's
  `close:delta_missing` — a data gap forcing a close. Fix separately: missing delta should wait for
  data or fall back, not close.

## 15. Left to the builder

- Exact regime thresholds, easing/hysteresis parameters and budget tables (proposed with the evidence
  the backtest can honestly give — regime frequency and forward index returns — operator tunes).
- Ladder parameters and the support detector's windows/merge rule; the anchor's survival N; the
  name-level trigger's thresholds (with the week of 2026-10-13 as a must-catch test case).
- Handling of opening orders already working when the regime escalates.
- Triage batch timing and the reserved-budget split; safeguard-2 window, threshold and cap.
- Picture table schema, story-survival k and window, staleness limit, rendering format.
- The Telegram suspend command's name.
- Phasing. Suggested: (1) regime + regime sizing + roll exemption + off switch + regime notices;
  (2) support detector + ladder; (3) triage + picture + safeguards; (4) readers + removing prior
  recommendations; (5) Claude's cut + counterfactual record + rule amendments; (6) the CC breakout
  rule and dossiers (§16–§17; the CC event hold was withdrawn, decision 34); (7) the page.
- Dossier batch size, rebuild triggers, the event-date matcher's accepted formats and the breakout
  parameters (§16–§17).

## 16. The ticker dossier

**Who gets one.** `would_own` ∪ `actively_wheeling` (the effective universe, so web overrides count)
∪ every held underlying from the wheel's positions (spreads underlyings are never held by the wheel
path). About 33 names today.

**Written by** the news process, stored in `data/news.db` (a new `NewsBase` table; only `src/news/`
writes it). The news process already has the per-ticker fact sheet (`src/news/facts.py::
build_ticker_facts`), the clusters, the triage piles (§7) and the LLM budget.

**Contents** (one record per name, latest wins; older rows kept 30 days for audit):
- **Kind:** stock, ETF or leveraged ETF (from `universe.yaml → leveraged_etfs`).
- **Facts** (Python, numbered `<SYM>:F<n>`): the ticker fact sheet (move, RSI, vs SMA200, nearest
  support and resistance, IV rank, IV/RV, earnings date, ex-dividend), 1-/3-month return, sector and
  governing regime index, 7-day deterministic sentiment (mean `det_sentiment` and item count — the
  same columns `sentiment.py` reads, news-fence rule 4).
- **Health** (Python): `strong | ok | weak | n/a | unknown` from `FundamentalStats` (quality screen,
  free cash flow, debt/equity, dividend safety); `n/a` for ETFs; each label carries its reasons.
- **Profile** (Claude, weekly, ≤ 400 characters): what the company or fund is and what moves it
  (rates, AI capex, bitcoin, the underlying index for a leveraged ETF). Labelled "Claude's summary,
  general knowledge". No numbers that are not in the facts.
- **Story** (Claude, ≤ 280 characters): what is happening to the name now, citing at least one
  pile-1/2 cluster from the last 7 days that names it. No such cluster → no story.
- **Upcoming events** (Claude proposes, Python verifies): a dated catalyst (product event, investor
  day, regulatory decision, index inclusion) that cites a cluster naming the symbol. Python keeps it
  only when the date is in the future, within 45 days, and **written in the cited cluster's text**
  (headline, item titles or summaries). Earnings are excluded (the earnings calendar and the
  earnings blackout already cover them). ETFs carry no events.

**Builds.** Facts, health and sentiment are refreshed hourly in RTH with no LLM call. Claude's parts
are rebuilt when a name is due — no dossier yet, a pile-1/2 cluster naming it since the last build,
an alert on it, or earnings reported (decision 37: **not** because the prose is old; old prose is
shown labelled with its age) — at most once per name every 6 hours except for a new name, an alert or
earnings, in batches of up to 6 names per call, under a daily cap of its own (4 calls, §13). A failed
or ungrounded build keeps the previous prose and marks it stale; numbers are never stale beyond the
hourly refresh. A reused trade review is keyed to the dossier's prose and events, not to the hourly
fact refresh (otherwise every review would be redone hourly).

**Events are information only** (decision 34). Verified upcoming events appear in the dossier and in
the reviewers' prompts; nothing acts on them.

**Readers.** A compact rendering (~70 words: kind, health, story, events, three key facts) in the
trade review for each reviewed name (at most 8, in priority order); the full rendering in `/scan
TICKER` and the roll review for the rolled name. The dossier adds nothing about the book: the
trade reviewer's book block (decision 23) already shows positions. The static `_UNIVERSE_CONTEXT`
table in `strategist.py` stays (it carries the operator's tiers and assignment rules).

## 17. Covered-call timing

**The deterministic breakout rule** (decision 28). A held name has broken out when, within the last
5 sessions, a daily close rose at least 1.5 × ATR-14 on at least 1.5× its 20-day average volume and
closed above its nearest resistance (or at a 60-session high). Until 5 sessions have passed or the
price fades (a close more than 1 × ATR below the breakout close), CC candidates on the name must have
a strike at or above a floor — the next resistance above the price, or the price + 1 × ATR,
whichever is higher — and a delta of at most 0.25 (decision 39: at 0.20 it met the CC `delta_min`
of 0.20 and left an empty band, so the rule would have stopped every CC instead of pushing it out).
A name where nothing clears the floor sells no CC that scan; that is the only way the rule "waits". A
resistance detector mirroring §6's support detector (swing highs on daily highs) is built for it.
Rolls are exempt. Not suspended by `/regime off` (it is not a regime limit); it has its own switch.
How often it would bite (measured 2026-10-21, 60-session-high branch only, 2 years): 0–10 triggers per
name, governing 0–7% of days (AMD 7.4%, PLTR 6.8%, GOOGL 5.6%; 0% for TQQQ and SOXL); it fired on
none of the eight covered calls sold 2026-10-01..15.

**Claude's event hold — withdrawn** (decision 34, 2026-10-21). Reasons: the evidence (§18) is an
average +0.7% abnormal return over ~3 days, shrinking with firm size, against a 2–3 week CC premium of
roughly 1.5–3%, so skipping the premium is likely negative expected value; few decisions qualify (all
six held stocks were below their cost basis on 2026-10-20, so `min_strike_vs_basis` already pushes
strikes far out); and it would have been a second exception to the core invariant. The core
invariant keeps exactly one exception: Claude may lower, never raise, the contract count of an
auto-opened CSP (§9).

## 18. Research behind §17 (2026-10-20)

The operator asked whether stocks typically keep rising after product announcements, and how that
differs from earnings. Summary:

- **Product announcements move prices little and briefly.** A meta-analysis of 71 studies finds an
  average abnormal return of about +0.7% with large dispersion, concentrated in a ~3-day window;
  pre-announcements draw a stronger reaction than launches; the effect shrinks with firm size
  (Grube, Maier & Bijmolt, *JPIM*; Eslami et al., EMAC 2025; Chaney, Devinney & Winer, *J. Business*
  1991).
- **Anticipation is priced before the event.** Apple averaged ~+5% in the month before iPhone events
  and usually fell on the event day ("sell the news"); a week or a month later the results were mixed
  (Bespoke via CNBC and Benzinga; small, dated samples).
- **After a news-driven jump, continuation is contested.** Moves with news drift and moves without
  news reverse (Chan 2003; Savor 2012), but with a broad news set, positive news shocks reverse while
  negative ones drift (Frank & Sanati, *JFE* 2018).
- **Earnings differ** — scheduled, with a measurable surprise — but post-earnings drift has been
  near zero for large caps since 2006 (Martineau, *CFR* 2021). The system already blocks short
  premium through earnings.
- **Covered calls** carry an uncompensated equity-reversal timing exposure (Israelov & Nielsen,
  *FAJ* 2015), so pushing strikes out after a breakout is reasonable; skipping the premium entirely
  forgoes it when implied volatility is often highest.

Hence: the past-move case is the deterministic breakout rule, which only pushes strikes out and is
recorded so the operator can see whether it pays. (The 2026-10-20 design also let Claude hold a CC for
a dated event ahead; decision 34 withdrew it.) A note on the "moves without news reverse" findings
(Chan 2003): they concern extreme monthly returns, not volume-confirmed breakouts to a new high, which
is what the rule requires; over 2 years the five sessions after a trigger averaged +1.4% to +4.1% on
GOOGL, AAPL, AMD and PLTR (4–10 triggers each — too few to prove anything, which is why it is recorded).

## 19. Second review and replay of the real book (2026-10-21)

A second Opus review of this spec and the plan, plus a replay of the plan's deterministic rules over
the real book (41 CSP opens, 2026-09-30..10-20, read-only from `data/income_system.db`; market data
from yfinance; open legs at the 2026-10-20 marks), found:

- **The market regime did nothing in the damage week.** SPY and QQQ base regimes were `normal` every
  day through 2026-10-16 (VIX 15.0–16.9, VIX/VIX3M ≤ 0.90); QQQ escalated intraday only on 10-16
  (−2.85% at the low). The losses were a leveraged-ETF and semis crash with a calm VIX — which is why
  the name-level ladder and decision 32 matter more than the index regime.
- **Full book** (decision 31), **empty delta band** (decision 39), **pre-anchor recovery and the
  $0.12 near miss** (decision 35), **multi-day intraday escalation and the 80th-percentile rule**
  (decision 36), **review-reuse churn** (decision 37), **counterfactual double counting and
  mark-to-expiry bias** (decision 38) — each fixed by the decision named.
- **How often the regime is non-normal** under these rules (SPY, 2018–2026): 46% of days (crisis
  14%); the last 12 months 25%; 2022 94%.

**Replay result with decisions 31–39** (first order: the budget multiplier is not replayed — the regime
was `normal` on every replayed day except 10-16; open legs at marks; one roll successor not netted):

| | Before | After |
|---|---|---|
| CSP opens blocked / trimmed | — | 10 / 4 |
| Contracts | 178 | 129 (−28%) |
| CSP P&L (realised + marked) | −$5,253 | −$1,298 |
| Loss exits | −$7,840 | −$3,280 |
| Winners | +$7,502 | +$6,487 |

The ladder and the same-day block stop SOXL 100P and TQQQ 75P / 70P / 68P (−$3,925 avoided). The flat leveraged-ETF
ceiling alone was roughly break-even (+$1,112 on TQQQ 78P, −$1,264 of forgone TQQQ winners), so it
was replaced the same day by the tiered middle ground. Variants of the leveraged-ETF fraction, same
replay, everything else as decided (P&L moves little because the TQQQ winners and losers nearly
cancel; the trade-off is premium against tail exposure):

| Leveraged-ETF fraction | Contracts | CSP P&L | Premium sold (of it, leveraged ETFs) | Largest leveraged-ETF lot (collateral) |
|---|---|---|---|---|
| none | 143 | −$1,116 | $22,620 ($6,840) | $78,000 |
| flat 3× 0.3 / 2× 0.5 (first draft) | 120 | −$1,268 | $19,460 ($3,680) | $26,000 |
| flat 3× 0.5 / 2× 0.7 | 126 | −$1,288 | $20,240 ($4,460) | $39,000 |
| **tiered: calm 3× 0.6 / 2× 0.8, stressed 3× 0.3 / 2× 0.5 (decided)** | **129** | **−$1,298** | **$20,630 ($4,850)** | **$46,800** |
| tiered: calm 0.7 / 0.9 | 132 | −$1,307 | $21,020 ($5,240) | $54,600 |

In this sample every stressed-tier
leveraged lot was already held to 1–3 contracts by the ladder or the regime, so the tiered and flat
0.6 rows coincide; the stressed tier matters in a slower slide where the ladder allows a lot. Not addressed by
anything here: first lots opened before any signal (SOXL 130P −$1,604) and the held-share losses
(−$53k unrealised on 2026-10-20), which stay out of scope. Three weeks dominated by one bad week is
direction, not proof.

**Expected trade frequency** (contracts sold): a normal year about 15–30% fewer (the leveraged-ETF
ceiling, the ladder, and per-trade ceilings on the ~25–35% of non-normal days); a 2022-like year
about 50–60% fewer, with the floor keeping 1–2 lots a day per index open in the worst of it.
