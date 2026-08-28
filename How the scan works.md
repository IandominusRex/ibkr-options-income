# How the scan works

*Written 2026-08-27, updated 2026-08-28 (dip_watch seed-only at startup; universe trimmed from
46 to 32 `would_own` names later the same day — membership counts below reflect the trim, but the
measured timing figures (percentiles, the `56s + 29.9s × n` fit, "5 times in 66 runs", etc.) were
captured before it and describe the pre-trim 46-name universe; the per-symbol cost model itself
doesn't change, only how many symbols there are to multiply it by). Reflects
`src/orchestrator/scan.py`, `src/notify/approval_service.py` (`_intraday_scan_loop`),
`config/universe.yaml`, and `config/settings.yaml → market_data` / `scheduler` as they stand
today.*

This document answers one question: **which tickers get looked at, how hard, and when.**

The confusion this clears up is that there is no single "scan." There are **three separate
clocks** and **two very different costs**, and the numbers you've seen quoted (15 min, 120 min,
3%, 2%, 0.5%) each belong to a different one of them.

---
In my own words:
1. At startup, all tickers in actively_wheeling PLUS any stock I currently hold (whether or not
it's in would_own) get a FULL IBKR options chain fetch. Dip_watch names (would_own − actively_wheeling,
currently 15) are NOT chain-fetched unconditionally at startup: each gets a cheap yfinance probe,
and only ones that gapped ≥3% overnight (in either direction — a gap-up is a legitimate CSP setup
at the open via IV expansion / news; a gap-down is the dip rule) get a chain fetch. Dip_watch names
that didn't gap get a yfinance-seeded baseline (no chain fetch) — the 3% drop gate works from
cycle 1 onward against that yfinance baseline. A dip_watch name with no persisted baseline at all
(first-ever run, or DB wiped) is also seed-only: accept no overnight detection for the first day;
the drop gate works from cycle 1. Candidates that pass the system's criteria (strategy screening
→ risk gate → score ≥55 → best strike per name → top 10) are sent to me via Telegram.

Each symbol gets tagged with the time ITS OWN chain fetch finished — not one shared timestamp for
the whole run, so symbols fetched early in a long sweep are tagged earlier than ones fetched late
(seed-only dip_watch names get a NULL timestamp, since no chain was fetched).

2. Every 15 minutes, a cheap yfinance probe is sent to check for price movements.
Actively_wheeling: [>0.5% price movement either side]
Dip_watch (Would_own - actively_wheeling): [>3% price movement downwards]
Held: [>2% price movement upwards]

These are ADDED together, not picked between. A symbol sitting in two buckets gets tested against
both rules and any one firing is enough. So a name I hold AND actively wheel still gets its 0.5%
either-side gate, and a held dip-watch name still gets its 3% dip gate — holding a position never
makes a ticker get scanned LESS.

If it passes any of its thresholds (measured from the last fetch price, so drift accumulates), the
ticker is eligible and gets an option chain fetch from IBKR. If a symbol gets an options chain
fetch, it gets a new tag for when the options chain was fetched

Two more rules fire on top of the price ones:
- Anything that produced a passing candidate on its LAST fetch gets refetched EVERY cycle,
  regardless of price movement, until a fetch finds nothing. This is usually the most common
  reason a symbol gets fetched
- Anything with no baseline price yet, or whose probe failed, gets fetched once to establish one
  — **except** dip_watch names at a full-sweep cycle (startup / manual `/scan`), which get
  seed-only instead (a yfinance baseline persisted without a chain fetch). At a normal intraday
  cycle this rule still fetches a no-baseline dip_watch name, but that only happens if the
  startup sweep somehow left it without one (a probe failure, or a brand-new ticker added to
  `would_own` mid-session).

3. If a symbol under actively_wheeling or held doesn't receive an options chain fetch after 120
minutes, the symbol gets a forced fetch. It is sent through the forced IBKR scan to fetch the
options chain, and the timer resets. Dip_watch names are NEVER on this timer.
The check is strictly ">120 min" against a stamp written when that symbol finished, and it's only
evaluated at the 15-minute marks — so in practice it fires on the 9th cycle (~2h15m), not the 8th.

4. Each cycle has a fetch budget (600s). If more symbols are material than fit — which happens in
a sell-off, when everything crosses its bar at once — the best-ranked ones get fetched (retries
first, then live candidates, then whoever dropped furthest relative to its own threshold) and the
rest are deferred to next cycle, where they go first. So the cycle always finishes on time instead
of overrunning and costing me the next scan entirely.

5. New-entry scans stop after 15:00 ET, so the last chain fetch of the day is at 14:45. Profit-take
and loss-exit checks keep running until the close. Also, if a scan takes longer than 15 minutes,
the next cycle's SCAN is skipped entirely (profit-take and loss-exit checks still run — they
happen before the scan in the loop) — a sweep of all 46 takes ~28 min at measured cost,
but with dip_watch seed-only the startup sweep usually fetches only `actively_wheeling` ∪ held
(plus any dip_watch names that gapped overnight), which is notably faster, so a cold start no
longer costs the 09:45 cycle on most days.

===== EXAMPLE =====
sample list:
Actively_wheeling: [SOXL, TQQQ, UPRO, RGTI, META, HOOD]
Dip_watch: [GOOGL, AAPL, MAGS, PLTR]
(would_own = both of the above = 10 names)

Held: [SOXL, TQQQ, PLTR, MARA, RGTI, META]
(MARA is held but NOT in would_own → it can only ever produce a covered call, never a CSP)

So the effective gate per ticker, after unioning:
| SOXL  | aw + held | 0.5% either side, OR 2% up | CC + CSP |
| TQQQ  | aw + held | 0.5% either side, OR 2% up | CC + CSP |
| RGTI  | aw + held | 0.5% either side, OR 2% up | CC + CSP |
| META  | aw + held | 0.5% either side, OR 2% up | CC + CSP |
| UPRO  | aw        | 0.5% either side           | CSP only |
| HOOD  | aw        | 0.5% either side           | CSP only |
| PLTR  | dip + held| 3% down, OR 2% up          | CC + CSP |
| GOOGL | dip       | 3% down                    | CSP only |
| AAPL  | dip       | 3% down                    | CSP only |
| MAGS  | dip       | 3% down                    | CSP only |
| MARA  | held only | 2% up                      | CC only  |

at 930am ET when the market opens, the 7 aw+held names (SOXL, TQQQ, UPRO, RGTI, META, HOOD,
MARA — de-duplicated) are sent through the IBKR options chain. Each takes ~35s to fetch
(measured from this deployment's own logs, n=385 real fetches: median 35s, mean 37s, p90 58s).
The 4 dip_watch names (GOOGL, AAPL, MAGS, PLTR — but PLTR is also held, so it's already in the
chain-fetch set above) get a yfinance probe: GOOGL/AAPL/MAGS that didn't gap ≥3% overnight are
seed-only (no chain fetch, yfinance baseline persisted). Say MAGS gapped up 5% overnight → it
also gets a chain fetch. [Total chain fetches: 8 (7 aw+held + MAGS); 3 dip_watch names seed-only]

930am: SOXL finishes [tagged at 930am]
... ...
932am: RGTI finishes [tagged at 932am]
933am: HOOD finishes [tagged at 933am]
... ...
938am: MAGS finishes [tagged at 938am]  (gapped overnight → fetched)
... ...
940am: MARA finishes [tagged at 940am]
[GOOGL, AAPL — seed-only: yfinance baseline persisted, no chain fetch, NULL timestamp]

===
There are some valid options that pass the gate, gets sent to user via telegram
say SOXL and HOOD produced passing candidates
===

945am: second cycle (the 930am sweep was the first)
Cheap yfinance scans on all 11 positions. No significant price changes
- BUT SOXL and HOOD produced candidates last fetch, so they get refetched anyway [retagged 945am]

10am: third cycle
Cheap yfinance scans on all 11 positions. assume no significant changes
- SOXL and HOOD refetched again if they're still producing candidates

......

1015am: fourth cycle
Cheap yfinance scans on all 11 positions.
- There is a > 0.5% DROP in the price of SOXL. It gets a full options chain fetch [tagged 1015am]
  (this works because SOXL keeps its actively_wheeling rule even though I hold it — under the old
  behaviour the held rule would have overridden it and needed +2% UP, so nothing would happen)
- There is a > 3% dip in PLTR. It gets a full options chain fetch [tagged at 1016am]
  (same thing — PLTR is held, but it keeps its dip-watch rule, so the dip still counts)
- MARA is down 4% but it's held-only and not in would_own, so nothing fires. A drop on a name I
  can only write calls on isn't an opportunity — and my existing calls are watched separately by
  the always-on monitor daemon
===
There are some valid options that pass the gate, gets sent to user via telegram
===

1030am scan, 1045am scan, 11am scan, 1115am scan, 1130am scan all run - uneventful

1145am: tenth cycle
Cheap yfinance scans on all 11 positions.
- There is a 2% increase in the price of MARA → fetched for a new covered call
===
There are some valid options for MARA that pass the gate, gets sent to user via telegram
===

On top of the cheap yfinance scan, it has been > 2 hours since the 930am sweep for the
actively_wheeling and held tickers that haven't been refetched since. Because each was tagged with
its own finish time, they don't all expire in the same cycle:

1145am: TQQQ [tagged 931am → 134 min] gets refetched, retagged 1145am
1146am: UPRO [tagged 932am → 134 min] gets refetched, retagged 1146am
1147am: RGTI [tagged 932am → 135 min] gets refetched, retagged 1147am
1148am: META [tagged 934am → 134 min] gets refetched, retagged 1148am
(GOOGL, AAPL, MAGS are dip_watch → never on this timer, skipped)
===
no valid options for these
===

12pm, 1215pm scan all run - uneventful

1230pm: thirteenth cycle
Cheap yfinance scans on all 11 positions.

Since it has been >120 minutes since SOXL and PLTR received a full options fetch
1230pm: SOXL finishes [retagged at 1230pm]
1231pm: PLTR finishes [retagged at 1231pm]

===
There are some valid options for PLTR that pass the gate, gets sent to user via telegram
===

...continues until 245pm. After 3pm no new-entry scans run at all.

---

## 1. The two costs — this is the whole point

Everything below exists to answer one question cheaply: *is it worth paying the expensive cost
for this ticker right now?*

| | What it is | Roughly what it costs | Can it produce a trade? |
|---|---|---|---|
| **Cheap probe** | One `fast_info` last-price lookup per symbol (yfinance), all symbols fanned out concurrently | Sub-second for the whole list | **No** |
| **Expensive fetch** | The full IBKR option chain: `reqSecDefOptParams` → strike selection → `qualifyContractsAsync` → `reqMktData` per contract, in batches, under a ~90-line limit | **~35s per symbol** — measured, n=385: median 35s, mean 37s, p75 46s, p90 58s, p99 152s. A sweep that fetches all 46 is therefore ~28 min; with dip_watch seed-only the startup sweep usually fetches fewer (aw ∪ held + gapped dip_watch only) | **Yes — this is the only thing that can** |

Those percentiles are the load-bearing numbers for everything below. A least-squares fit over 19
real full-universe cycles in this deployment gives the whole cost model:

```
scan duration  =  56s  +  29.9s × (material symbols)
                  ^^^      ^^^^^
         fixed per cycle   per chain fetch
```

The **56s intercept** is work every cycle pays regardless of how many chains it fetches: analytics
and Reddit sentiment run for *every* symbol, material or not (they feed the buy-to-own screen and
the Claude prompt), plus VIX, account, scoring, review and Telegram. Measured over 125 real cycles
the gate keeps the median at **1** material symbol (mean 3.8) — but 6% of cycles went over 20, and
5 went to all 46, which the model puts at ~23 min. Observed worst case: **30.1 min**.

**No chain fetch → no candidates.** A symbol that skips the chain still runs its analytics
(IV, technicals, fundamentals) and Reddit sentiment that cycle — those are cheap yfinance/Reddit
calls — but with no option quotes, neither the covered-call screen nor the cash-secured-put screen
runs for it, so it cannot produce a card. Every threshold in this document is a rule for
**deciding who pays the expensive cost.**

---

## 2. The three clocks

| Clock | Interval | What fires | Scope |
|---|---|---|---|
| **The scan loop** | **every 15 min**, RTH only, aligned to :00/:15/:30/:45 | One scan cycle: cheap-probe everyone, then chain-fetch the ones that qualify | `would_own` ∪ currently-held stocks |
| **The staleness safety net** | **every 120 min, per symbol** | Force one chain fetch for a symbol that hasn't had one in 2 hours | `actively_wheeling` ∪ held — **never dip-watch** |
| **The position monitor** | continuous, event-driven (`src/monitor/intraday.py`) | Roll alerts, delta drift, assignment risk on **positions you already have** | Your open short options |

The third one is not a "scan" at all and shares none of these thresholds. It is a separate
always-on daemon subscribed to `pendingTickersEvent`. **It is why the held-position gate in §4 is
allowed to be up-only** — nothing about managing an existing short call depends on the 15-minute
scan.

### When the 15-minute loop actually runs

Cycles land on ET clock marks: **09:30, 09:45, 10:00 … 14:45** — 22 new-entry cycles a day. A
cycle is skipped entirely (no scan, no probes) when any of these is true:

| Skip reason | Effect |
|---|---|
| Outside RTH, weekend, or market holiday | Nothing runs |
| Past `scheduler.entry_cutoff` (**15:00 ET**) | Profit-take + loss-exit checks still run; **no new-entry scan** |
| Execution halted (`/halt`) | Same — closing risk is always allowed, opening it is not |
| IBKR data-farm health probe on SPY fails | Cycle skipped, forced reconnect, operator notified |
| The previous cycle's scan is still running | Cycle lost, counted, operator warned (throttled) |

So the last chain fetch of the day happens at **14:45**, not 16:00.

---

## 3. What is actually in the scan set

`config/universe.yaml` has four lists, and they do **not** all mean "scanned."

```
all_symbols  =  would_own  ∪  stocks you currently hold
```

That is the entire scan set. `indexes:` and `watchlist:` are **not read by the scan loop at all.**

| List in `universe.yaml` | Count | Read by the scan loop? | What it's actually for |
|---|---|---|---|
| `indexes:` + `watchlist:` | 16 + 24 | **No** | The documented universe. Feeds nightly IV-history and price-history appends (EOD, 16:15 ET) and the `/health` IV-staleness check. Nothing else. |
| `would_own:` | **32** | **Yes — this is the scan set** | The CSP allowlist. A cash-secured put can only ever be recommended on a name in here. |
| `actively_wheeling:` | **17** | Yes — a subset of `would_own` | The core rotation. The only names on the sensitive 0.5% gate and the only ones the 120-min net covers. |
| *(derived)* dip-watch = `would_own` − `actively_wheeling` | **15** | Yes, but cheaply | Names you'd accept assignment on, but don't need checked constantly. Chain-fetched only on a real drop. |
| `sectors:` / `strike_bands:` | — | Yes, but not for selection | Concentration bucketing and strike-band overrides. |
| `universe_archive.yaml` | 22 | **No — not loaded by the app at all** | Reasoning kept for tickers you've decided against. |

**Eight tickers are documented but never scanned** — they're in `indexes:`/`watchlist:` but not in
`would_own`, so unless you hold the stock they never see a chain fetch:
`XLV, MSFT, TLT` (thin premium), `LABU, TSLL, DPST` (CC-only leveraged, deliberately never
`would_own`), `TEM, IONQ` (CC-only). If you *do* hold one, it enters the scan set as a held
position and gets covered-call candidates — just never CSP ones.

### The three treatments, side by side

| | **Actively wheeling** | **Dip-watch** | **Held stock** |
|---|---|---|---|
| Who | 17 core names in `actively_wheeling` | the other 15 in `would_own` | any stock position > 0 shares, whatever list it's in |
| Cheap probe | every cycle | every cycle | every cycle |
| Chain fetch trigger | **±0.5%** move (`intraday_rescan_move_pct`) | **−3%** drop only (`dip_pull_in_pct`) | **+2%** rise only (`held_position_move_pct`) |
| Direction | either way | **down only** | **up only** |
| 120-min staleness net | **yes** | **no — never** | **yes** |
| Can produce | CSP (and CC if you hold it) | CSP (and CC if you hold it) | CC (and CSP too, if it's also in `would_own`) |
| Why that direction | you want both sides: a dip is an entry, a rally may open a better CC strike | a rally is **never** a reason to newly sell a put on a name outside the core | a new CC needs room to sell an OTM strike, which only a rally creates; a drop is the monitor's job, not this gate's |

**A symbol can be in more than one column, and the rules add up (2026-08-28).** If you hold
shares of an `actively_wheeling` name, it keeps its ±0.5% gate **and** gains the +2% rally
trigger — it is not demoted to the held rule. A held dip-watch name keeps its −3% dip gate, gains
the same rally trigger, and picks up the 120-min net it wouldn't otherwise have.

The reason the rules union rather than override: the buckets answer *different questions about the
same fetch.* "Held" asks "is there room for a new covered call?"; `actively_wheeling`/dip-watch ask
"is this a CSP entry?" A name you hold and wheel has both questions live at once, because
`screen_csp_candidates` runs for every `would_own` symbol whether or not you hold it
(`src/strategies/cash_secured_put.py:93`) — holding only seeds the concentration budgets.

This was a real bug until 2026-08-28: `held` won outright, so owning shares of a core wheel name
silently dropped it from ±0.5% to +2%-up-only, shrinking the 17-name rotation to just the names you
*didn't* hold. The more of the wheel you actually ran, the less the 0.5% gate did.

---

## 4. The materiality gate — the actual rule

Every 15-minute cycle, `_compute_material_symbols` decides who gets a chain fetch. Six rules,
**OR'd together** — clearing any one makes a symbol material:

| # | Rule | Applies to | Cost to evaluate |
|---|---|---|---|
| **(d)** | Cleared the risk gate **and** the score floor on its last fetch | anyone | free (read from DB) |
| **(f)** | This symbol's **own** last fetch was > 120 min ago | `actively_wheeling` ∪ held **only** | free (read from DB) |
| **(e)** | No usable price baseline yet, or the probe failed | anyone | free |
| **(a)** | Live spot **≥ +2%** above its last-fetch price | held stock | one cheap probe |
| **(b)** | Live spot **≥ ±0.5%** from its last-fetch price | actively wheeling — held or not | one cheap probe |
| **(c)** | Live spot **≤ −3%** below its last-fetch price | dip-watch — held or not | one cheap probe |

Rules (a)-(c) are **OR'd across buckets too**, not just with the rest of the list: a symbol in two
buckets is tested against both and any one firing is enough.

Two overrides sweep **everything** unconditionally:

- **Cold start** — no `scan_state` rows at all. At a normal intraday cycle this fetches everyone
  once to seed baselines. At a full-sweep cycle (startup / manual `/scan`) the path is different:
  `actively_wheeling` ∪ held names are fetched unconditionally, but dip_watch names get seed-only
  (yfinance baseline persisted, no chain fetch) unless they gapped ≥3% overnight — see point 1.
- **First eligible cycle after the process starts** (`startup_full_sweep_done`). A manual `/scan`
  also counts and sets the same flag, so a restart followed by a manual scan doesn't sweep twice.
  Same dip_watch seed-only behavior as a cold start.

A third override sweeps **only specific named symbols**, regardless of movement:

- **The retry queue** (`must_include_symbols`, 2026-08-28). If a cycle's half-dead-socket circuit
  breaker fires mid-sweep (three consecutive option-chain timeouts by default —
  `market_data.max_consecutive_chain_timeouts` — the scan bails rather than grind the rest of
  the universe one `symbol_timeout_seconds` at a time; see `SETUP.md`'s troubleshooting table
  for the full "Scan blocked" story), everything from the start of the failing run onward is
  never reached that cycle. Those symbols carry forward as `bot_data["pending_retry_symbols"]`
  and get forced through the gate on the *next* intraday cycle — a targeted retry, not a second
  full sweep, since everything else that cycle already fetched is fresh in `scan_state`. If that
  retry also gets cut short, the still-unreached subset carries forward again; symbols that make
  it through drop out of the queue. A restart clears the queue in effect (the next eligible cycle
  is a forced full sweep anyway, per the override above). The queue is intraday-loop state only
  — a manual `/scan` doesn't read or clear it, though a clean full sweep naturally refreshes
  `scan_state` for whatever was pending anyway, so the next intraday cycle's forced retry just
  ends up re-confirming already-fresh data rather than finding anything stale.

### The single most important detail: the baseline is the last **fetch**, not the last cycle

A symbol's baseline price is only rewritten when its chain is actually fetched. So the percentages
above are measured against **whenever that symbol last paid the expensive cost** — which may be
hours ago.

This means **drift accumulates.** A dip-watch name that leaks −0.4% every cycle for two hours has
still moved −3% from its 09:30 baseline and gets pulled in — it isn't required to drop 3% in one
15-minute step. Conversely, a name that gets fetched often has its baseline reset often, so it
needs a genuine fresh move each time.

**Where the baseline number comes from matters.** For a symbol whose chain was fetched, the
baseline is `TechnicalStats.price`, which prefers a spot derived from the option chain by
**put-call parity** (`spot ≈ strike + call_mid − put_mid`, median across same-strike pairs) over
the yfinance quote. That was fine while the chain carried both rights at every in-band strike.

Since `_build_chain_contracts` went **OTM-only** (calls only at `strike >= spot`, puts only at
`strike <= spot`), a strike carrying *both* rights — the only kind parity can use — no longer
exists, except where spot lands exactly on a strike. Parity went from abundant to structurally
impossible, and the function silently fell back to *"the tightest-spread option's strike"* — a
strike, not a price, quantized to the chain's increment. On a $150 name with $2.50 strikes that is
up to ±$1.25 = **0.83% error, larger than the 0.5% gate itself**, which would manufacture phantom
moves and mask real ones on every `actively_wheeling` name.

Fixed 2026-08-28 by `infer_spot_from_quotes(..., require_parity=True)` at the two call sites that
feed `spot_override`: no parity pair now yields `None`, so the caller falls through to the yfinance
probe price it already holds. That is strictly better than the old behaviour, because it puts the
**baseline and the next cycle's probe on the same data source** — the gate no longer compares an
IBKR-derived number against a yfinance one. Callers inside `iv.py` that only rank strikes by
distance to spot (term-structure slope, skew, 30-day ATM IV) keep the loose fallback, where half a
strike increment is harmless.

The **timestamp** is per symbol too, taken when that symbol's own fetch completes rather than once
for the whole run (2026-08-28). Before that, everything in a sweep shared one stamp written when the
run *finished*, which overstated the freshness of whatever was fetched early by up to the sweep's
duration and gave the entire cohort one identical staleness clock — so they all expired together in
a single later cycle. Per-symbol stamps spread that expiry across the same span the sweep took,
which matters because **a burst longer than 15 minutes overruns the cycle and costs the next one
entirely.** The effect is bounded by sweep duration: a 25-minute sweep splits across roughly two
cycles, not into 46 evenly-spaced singletons. Ordinary price movement is still the bigger
desynchronizer.

Two details about rule (f) that are easy to get wrong:

- **The comparison is strictly `> 120 min`, against a stamp written when the scan run *finishes*,
  not when the cycle started.** A symbol fetched during the 10:00 cycle stamps ~10:02, so it is
  118 minutes old at the 12:00 cycle and is not forced until 12:15. The net fires on the **9th**
  cycle after a fetch, not the 8th.
- **It is scoped to `actively_wheeling ∪ held` and nothing else.** The 15 dip-watch names have no
  timer of any kind — they are purely event-triggered by a −3% drop and can hold a morning
  baseline all day.

### Rule (f): why "per symbol" matters

The old rule was: *if the single stalest name in the core is over 120 min, force-fetch the entire
core.* One quiet name (MSFT on a slow week) dragged 18 perfectly fresh siblings into one
synchronized burst.

The rule now runs each symbol against **its own** clock. A name that keeps moving 0.5%+ and
refetching naturally never needs the safety net at all, and names desynchronize on their own as
the day goes on. It does not make any individual symbol refresh faster or slower — each still gets
at most one forced fetch per 120 minutes of its own inactivity. It only eliminates the drag-along
fetches.

---

## 5. A real-life scenario

A simplified 6-ticker universe, so the whole day fits in one table:

| Ticker | Bucket | Held? | Threshold that applies |
|---|---|---|---|
| **NVDA** | actively_wheeling | no | ±0.5% |
| **HOOD** | actively_wheeling | no | ±0.5% |
| **SPY** | actively_wheeling | **yes, 100 sh** | **±0.5% OR +2% up** — both rules apply |
| **AAPL** | dip-watch | no | −3% down only |
| **MSFT** | dip-watch | no | −3% down only |
| **TSLL** | `indexes:` only, not in `would_own` | no | **never scanned** |

The daemon started at 09:12 this morning.

### 09:30 — first eligible cycle → forced full sweep

Nothing to gate against, and the startup flag is unset. NVDA, HOOD, and SPY (actively_wheeling
∪ held — SPY is both) get a chain fetch unconditionally. AAPL and MSFT are dip_watch: each gets a
yfinance probe instead. Say neither gapped ≥3% overnight → both are seed-only (yfinance baseline
persisted, no chain fetch). TSLL is not in `all_symbols` and is not touched.

| Ticker | Baseline written | Produced a passing candidate? |
|---|---|---|
| NVDA | 180.00 | ✅ yes |
| HOOD | 118.00 | ✅ yes |
| SPY | 640.00 | no |
| AAPL | 232.00 (yfinance seed — no chain fetch) | — |
| MSFT | 315.00 (yfinance seed — no chain fetch) | — |

**3 chain fetches.** ~1.5 minutes. `cleared_floor = {NVDA, HOOD}`.

If AAPL or MSFT had gapped ≥3% overnight (up or down), it would have been chain-fetched too — a
gap in either direction is a legitimate CSP setup at the open. The yfinance-seeded baseline means
rule (c) drop-only works from cycle 1 onward against that baseline, sourced end-to-end from
yfinance (no IBKR/yfinance mismatch).

### 09:45

Cheap-probe all five first (sub-second), then decide:

| Ticker | Probe | vs. baseline | Verdict |
|---|---|---|---|
| NVDA | 180.30 | +0.17% | **fetch** — rule (d), cleared the floor last time. The move alone wouldn't have. |
| HOOD | 117.60 | −0.34% | **fetch** — rule (d) |
| SPY | 640.50 | +0.08% | skip — needs +2% |
| AAPL | 231.50 | −0.22% | skip — needs −3% |
| MSFT | 315.20 | +0.06% | skip |

**2 chain fetches.** NVDA and HOOD get new baselines (180.30 / 117.60). Say only HOOD passes this
time → `cleared_floor = {HOOD}`.

### 10:00

| Ticker | Probe | vs. baseline | Verdict |
|---|---|---|---|
| NVDA | 181.40 | +0.61% vs **180.30** | **fetch** — rule (b), a genuine 0.5% move off the 09:45 baseline |
| HOOD | 117.20 | — | **fetch** — rule (d) again |
| SPY | 641.00 | +0.16% | skip |
| AAPL | 230.90 | −0.47% | skip |
| MSFT | 315.00 | −0.06% | skip |

**2 chain fetches.** NVDA baseline → 181.40.

### 10:45 — an AAPL selloff and an SPY rally

| Ticker | Probe | vs. baseline | Verdict |
|---|---|---|---|
| AAPL | 224.60 | **−3.19%** vs 232.00 (09:30) | **fetch** — rule (c). This is the dip pull-in: AAPL has been outside the rotation all morning and one real drop brings it in. CSP candidates get generated for it this cycle. |
| SPY | 653.00 | **+2.03%** vs 640.00 (09:30) | **fetch**. Note it would already have fired at +0.5% via rule (b) — SPY is `actively_wheeling`, and holding it doesn't take that rule away. Rule (a) matters only for a held name in no other bucket. |
| MSFT | 322.00 | **+2.22%** | **skip** — the gate is down-only for dip-watch. A rally is not a reason to newly sell a put on a name outside the core rotation. |
| NVDA | 181.60 | +0.11% vs 181.40 | skip |
| HOOD | 117.30 | — | fetch if still cleared_floor |

Note AAPL's −3.19% accrued gradually across five cycles, never dropping 3% in any single 15-minute
step. The baseline-is-last-fetch rule is what caught it.

### 12:15 — the staleness net fires, for exactly one symbol

Last-fetch stamps going into this cycle: NVDA **10:02**, HOOD 12:02, SPY 10:47, AAPL 10:47,
MSFT **09:33**.

| Ticker | Age | Verdict |
|---|---|---|
| **NVDA** | **133 min** | **forced fetch** — rule (f) |
| HOOD | 13 min | not stale |
| SPY | 88 min | not stale |
| AAPL | 88 min | not stale |
| MSFT | **162 min** | **not forced** — dip-watch is permanently excluded from the net |

Note the cycle this lands on. NVDA was fetched during the 10:00 cycle, but the check is strictly
`> 120 min` against a stamp written at the *end* of that scan run (~10:02), so at the 12:00 cycle
it is only 118 minutes old and survives. It fires one cycle later. **In practice the net fires on
the 9th cycle after a fetch, not the 8th — an effective worst-case cadence of ~2h15m, not 2h00m.**

**1 forced fetch.** Under the old group rule, NVDA crossing the line would have dragged SPY and
HOOD along too — 3 fetches where 1 was needed.

**MSFT is the case worth internalizing.** It can sit on its 09:30 baseline all day. That is
deliberate: it is cheap-probed every single cycle, so nothing is missed — it just needs a real
−3% from 315.00 (i.e. ≤ 305.55) to earn a chain fetch, and the 3% window measured from the morning
price gets *easier* to trip as the day goes on, not harder.

### The day in one table

| Cycle | Chain fetches | Why |
|---|---|---|
| 09:30 | **3** | forced full sweep (first cycle after process start) — aw ∪ held only; AAPL, MSFT seed-only |
| 09:45 | 2 | NVDA, HOOD — cleared floor |
| 10:00 | 2 | NVDA (0.5% move), HOOD (cleared floor) |
| 10:15–10:30 | 1–2 | HOOD, occasional NVDA |
| 10:45 | 4 | AAPL (−3% dip pull-in), SPY (+2% rally), NVDA, HOOD |
| 11:00–11:45 | 1–2 | mostly HOOD |
| 12:15 | 1 | NVDA — staleness net (133 min since its 10:02 stamp) |
| 12:30–14:45 | 1–3 | ordinary moves + staleness, spread out |
| 15:00 onward | **0** | past `entry_cutoff` — profit-take and loss-exit checks continue, no new-entry scan |

Roughly **3 fetches at the open, then 1–4 per cycle**, versus 5 every cycle if held names were
unconditional and all 15 dip-watch names sat on the 0.5% gate. The startup sweep is now cheaper
than it used to be — dip_watch seed-only saves ~2 chain fetches (more if the dip_watch list is
larger than this 2-name example).

---

## 5b. The per-cycle fetch budget

The gate filters beautifully in normal conditions and then stops filtering exactly when it matters.
In a broad sell-off **every** `would_own` name crosses its bar in the same cycle — correlation goes
to 1, and a gate built on per-symbol movement has nothing left to reject. 46 fetches ≈ 23 min inside
a 15-minute cycle.

An overrun is not merely slow. It sets `scan_running`, so the **next cycle's scan is skipped
entirely** — your new-entry cadence silently halves to 30 min at the worst possible moment.
(Profit-take and loss-exit checks still run; they precede the scan in the loop, so risk management
is never starved.) This already happened 5 times in 66 runs.

`market_data.chain_fetch_budget_seconds` (**600s**, 0 disables) caps chain-fetching per cycle. When
it runs out, remaining material symbols are **demoted to immaterial** — analytics still run, the
chain is skipped, the cycle finishes on time — and they are carried in
`ScanResult.unreached_symbols` → next cycle's `must_include_symbols`, where they rank first. A
cluster drains across consecutive on-time cycles instead of one burst that eats the following one.
It never aborts the run.

**Why 600s:** `900s cycle − 56s overhead − 150s (symbol_timeout_seconds) = 694s`. The 150s is
overshoot headroom — the budget can only be checked *between* symbols, so a fetch starting one tick
under the deadline can still run to its timeout. Rounded down to 600 (~20 fetches), the worst case
is `600 + 150 + 56 = 806s < 900s`: it cannot overrun.

**Priority order** — which fetches a capped cycle buys, highest first:

| Rank | Who | Why |
|---|---|---|
| 1 | `must_include` (deferred last cycle) | Otherwise the tail of a long queue starves while fresh movers keep cutting in |
| 2 | Cleared the score floor last fetch | A live, tradeable candidate going stale. Repricing something actionable beats discovering something new |
| 3 | **Movers, by multiple of their own bar** | Comparable across buckets: a dip-watch name down 6% (2.0× its 3% bar) outranks an `actively_wheeling` name down 0.6% (1.2× its 0.5% bar). In a sell-off the deepest drops are the best CSP entries |
| 4 | Staleness-only (didn't move) | Quiet by definition — that's why nothing else fired for it |

`_move_ratio()` computes rank 3 **and** is what the gate itself uses as its boolean (`>= 1.0`), so
the gate and the ranker cannot drift apart about what "moved" means.

Manual `/scan` is never budgeted — it is operator-initiated and expected to sweep in full.

### Why a shorter cycle would make this worse

The intuition that a 10- or 5-minute cycle would spread fetches out and break up clusters is
backwards, because **the 56s overhead and the 150s margin are paid per cycle regardless of its
length.** That fixed 206s is 23% of a 15-minute cycle, 34% of a 10-minute one, and 69% of a
5-minute one:

| Cycle | Budget | Fetches/cycle | **Fetches/hour** | Fixed cost | Time to drain 46 |
|---|---|---|---|---|---|
| 30 min | 1594s | 53.3 | 106.6 | 11% | 26 min |
| 20 min | 994s | 33.2 | 99.7 | 17% | 28 min |
| **15 min** | **694s** | **23.2** | **92.8** | **23%** | **30 min** |
| 10 min | 394s | 13.2 | 79.1 | 34% | 35 min |
| 5 min | 94s | 3.1 | 37.7 | 69% | 73 min |
| 4 min | 34s | 1.1 | 17.1 | 86% | 162 min |

Shortening the cycle **lowers** hourly throughput *and* makes a sell-off cluster take longer to
drain. Below ~3.5 min the budget goes to zero and the loop does nothing but overhead.

What a shorter cycle *does* buy is **detection latency** — you notice a 3% drop within 10 min
instead of 15. But in a sell-off you are throughput-bound, not latency-bound: 46 names want
fetching and you can only buy 23 of them per cycle. Paying 15% throughput for 5 minutes of latency
makes the queue drain slower, which is the wrong trade precisely when it matters.

**15 minutes is at the knee and should stay there.** If you want more throughput, attack the 29.9s
per-fetch cost (`max_strikes_per_symbol`, or the wide `strike_bands` overrides on the slowest names
— SOXL 42s, NBIS 39s, HOOD 36s median), not the cycle length.

## 6. Things that bypass all of this

| Trigger | What it does |
|---|---|
| **`/scan`** (manual, no ticker) | **Full sweep — `actively_wheeling` ∪ held names chain-fetched unconditionally; dip_watch names seed-only unless they gapped ≥3% overnight.** Faster than the old "fetch every symbol" sweep. Also sets the startup flag so the next 15-min cycle doesn't repeat it. |
| **`/scan TICKER`** | Single ticker, chain + analytics + screens + risk gate, **ignoring universe membership entirely** — any ticker that qualifies as an IBKR stock works, in `would_own` or not. |
| **Daemon restart** | The next eligible cycle is a forced full sweep, regardless of the 120-min timer. |
| **EOD report (16:15 ET)** | Appends today's ATM IV and closing price for `indexes ∪ watchlist ∪ would_own` (~60 names) to the history tables. Not a scan — no chains, no candidates. |
| **`src/monitor/intraday.py`** | Continuous, event-driven, on your open short options. Roll alerts, delta drift, assignment risk. **Completely independent of every threshold above.** |

**Buy-to-own is a separate cadence, not covered by any threshold above (2026-08-28).** Every
cycle — including one the materiality gate skips entirely for chain fetches — still scores the
buy-to-own screen, because it only needs technicals/IV/fundamentals, which run for every `would_own`
symbol every cycle regardless of materiality. What changed is the *Telegram send*: it used to go out
every 15-min cycle; now `_intraday_scan_loop` only sets `include_buy_list=True` on the first cycle
each ET calendar day that completes cleanly, so the message fires once a day instead of ~26 times.
A cycle that errors, gets skipped, or loses the scan lease doesn't count, so the gate simply waits
for the next one rather than losing the day. Manual `/scan` always sends the full buy list.

---

## 7. Quick reference — the numbers and where they live

| Number | Config key | Meaning |
|---|---|---|
| **15 min** | `scheduler.intraday_loop_minutes` | How often a scan cycle runs during RTH |
| **15:00 ET** | `scheduler.entry_cutoff` | Last new-entry scan is 14:45 |
| **120 min** | `market_data.force_full_scan_minutes` | Per-symbol staleness net; `actively_wheeling` ∪ held only. 0 disables |
| **0.5%** | `market_data.intraday_rescan_move_pct` | `actively_wheeling`, not held — either direction |
| **2%** | `market_data.held_position_move_pct` | Held stock — **up only**, and *added to* the name's other bucket rule rather than replacing it |
| **3%** | `market_data.dip_pull_in_pct` | Dip-watch — **down only**, never swept on a timer |
| **600s** | `market_data.chain_fetch_budget_seconds` | Per-cycle chain-fetch ceiling; overflow defers to next cycle. 0 disables |
| 17 / 15 / 32 | `universe.yaml` | `actively_wheeling` / dip-watch / `would_own` |

**Where to change behaviour:** thresholds in `config/settings.yaml → market_data`, membership in
`config/universe.yaml`. Moving a ticker between `actively_wheeling` and dip-watch is the single
biggest lever on scan cost — it swaps a name between "checked at 0.5%, either direction, plus a
120-min floor" and "checked at 3% down, event-triggered only."

---

## 8. Common confusions, answered directly

**"Is the initial scan different from the 15-minute scan?"**
Same code path, one flag different. The first eligible cycle after the daemon starts passes
`force_full_sweep=True`, which fetches `actively_wheeling` ∪ held names unconditionally and
gives dip_watch names seed-only (yfinance baseline, no chain) unless they gapped ≥3% overnight.
Every cycle after that runs the normal gate, where a no-baseline dip_watch name *would* be
fetched by rule (e) — but the startup sweep already seeded it, so that never fires on cycle 2.

**"Does the 120-minute scan replace the 15-minute one?"**
No. There is no separate 120-minute scan. It's a *rule inside* the 15-minute cycle: "also fetch
anything in the core that hasn't been fetched in 2 hours." It adds symbols to a cycle that was
going to run anyway.

**"When a symbol's 2-hour timer expires, does the whole core get refetched?"**
No — **only that one symbol.** That was the old rule ("if the single stalest name in the core is
over 120 min, force-fetch the entire core"), and it is exactly what was removed on 2026-08-27. Each
symbol now runs an independent clock off its own last fetch.

**"If everything is fetched in the same sweep, don't they all go stale together anyway?"**
They used to — the check was per symbol but every stamp in a sweep was identical, because the
timestamp was written once when the whole run finished. Since 2026-08-28 each symbol is stamped when
its own fetch completes, so a 25-minute sweep's cohort expires across ~25 minutes (about two cycles)
rather than all in one. It's a bounded improvement, not a full rotation schedule — ordinary price
movement is still what really scatters the clocks.

**"Why don't my dip-watch names ever get scanned?"**
They're probed every cycle; they just rarely earn a chain fetch, which is the design. A −3% drop
from their last-fetch price pulls them in. They are excluded from the 120-min net on purpose —
including them would put all 32 names back on a timer and defeat the split. At startup /
manual `/scan`, dip_watch names are seed-only (no chain fetch) unless they gapped ≥3% overnight —
the same exclusion at a different point in the cycle.

**"Why didn't my held position get rescanned when it dropped 5%?"**
Only if that name is in **no other bucket** — i.e. you hold it but it isn't in `would_own`. The
held gate is up-only because it exists to find *new* covered-call strikes, and a drop doesn't
create one; your existing short calls are watched continuously by the event-driven monitor instead.
It still gets refreshed within 120 minutes via the staleness net.

If the name **is** in `would_own`, a 5% drop absolutely does fetch it — via its `actively_wheeling`
(±0.5%) or dip-watch (−3%) rule, which holding does not remove. That was broken until 2026-08-28,
when `held` overrode the bucket instead of adding to it.

**"Does holding a stock make it get scanned more, or less?"**
More, never less. Holding *adds* the +2% rally trigger on top of whatever rule the name already had.
Holding is not a bucket you get moved *into* — it's a rule that gets layered on.

**"Why is a name being fetched every single cycle even though it's barely moving?"**
Rule (d) — it cleared the risk gate and the score floor on its last fetch, so it stays material
until a fetch produces no passing candidate for it. That's intentional: a live, tradeable
candidate should be repriced every cycle.

**"I added a ticker to `watchlist:` and nothing happened."**
`watchlist:` and `indexes:` are not read by the scan loop. Add it to `would_own:` for CSPs (and to
`actively_wheeling:` as well if it should be in the core rotation), and give it a `sectors:` entry
so the concentration cap can bucket it — the scan logs a warning for any symbol missing one.
