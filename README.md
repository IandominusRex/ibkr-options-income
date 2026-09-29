# IBKR Options Income System

A semi-autonomous options-income trading system for an Interactive Brokers account. It scans your
holdings and a watchlist every 15 minutes during market hours, scores and ranks covered-call and
cash-secured-put opportunities, gets a plain-English review from Claude, and sends the top candidates
to your phone via Telegram.

> **A four-rung autonomy ladder**, not a binary switch. `OBSERVE` (default, fresh install) proposes
> only — nothing opens, and Approve/Reject buttons are withheld. `MANUAL` requires your explicit
> Telegram tap on every trade. `WHITELIST` auto-opens listed symbols and sends everything else to
> you. `FULL` auto-opens anything that clears the deterministic gates. Change rungs with
> `/autonomy <level>` — promotion up a rung is refused until the account has demonstrated evidence
> (>=20 fills, >=60% fill rate, a risk-reducing close having fired); demotion is always allowed.
> Every order is re-validated by the deterministic risk engine before it executes at every rung.
> Auto-close (profit-take + loss-exit) is a **separate** switch, `automation.auto_close_enabled`,
> independent of the autonomy rung. At WHITELIST/FULL the system trades the **deterministic,
> gate-passing slate**; Claude's review is shown for the record but never filters or gates what
> executes (the fence). To raise the auto-open bar, raise `weights.min_candidate_score` — not via
> Claude.

---

## What it does

| Time | What happens |
|---|---|
| **Every 15 min (RTH)** | Intraday loop: checks profit-take/loss-exit targets, runs a fresh scan (full sweep on first cycle each session); candidates a symbol's autonomy rung clears (WHITELIST/FULL) auto-execute, everything else sends an approval request (buttons withheld at OBSERVE) |
| **During market hours** | Event-driven monitor watches open positions for delta drift, IV spikes, ex-dividend and early-assignment risk, and the mechanical **21-DTE management point** (while closing, rolling, or holding are all still viable — not first at 7 days, deep in the gamma window); alerts you to roll when needed |
| **4:15 PM ET (auto)** | End-of-day report: P&L summary, journal entry, tomorrow's watchlist |
| **Any time** | Telegram bot commands (see below) — query the system interactively from your phone |
| **When you approve** | Execution engine re-validates, builds a limit order at mid-price, places it, and confirms the fill back to Telegram |

### Telegram commands

| Command | What it does |
|---|---|
| `/scan` | Run a full on-demand pipeline scan (CC/CSP/buy opportunities) — full universe sweep, always reviews fresh. Each strategy thread also gets an **"Assessed — not approved"** block listing the contracts that were priced and set aside, with the gate each failed |
| `/scan AAPL` | Single-ticker deep-dive: fetch option chain for one symbol, run analytics, show best CC/CSP/buy result with a Claude/Ollama verdict. Holistic context: a **💬 Sentiment** line (composite StockTwits + news + optional Reddit, 0-100 with 1-day trend), a **🌐 Market & Sector** line (VIX regime + how the name's sector / the broad market are trading + relative strength) and a **🧠 Read** — a plain-English synthesis explaining what the IV/VRP/delta/RSI numbers mean together and the overall sentiment; a **🎯 ideal strike zone + minimum credit** beside the contract actually on offer (derived from support/resistance, expected move, earnings timing and Black-Scholes fair value at realised vol — the credit floor is priced at *that* contract's strike, so "clears fair value" compares like with like), the runner-up qualifying strikes, an **"Other contracts considered"** list naming every contract that didn't make it and why, and a **🎯 Levels** block with the share-entry price. When a strategy has no qualifying option it shows the closest failed contract and *why* — never silence. When it never even priced a contract (e.g. shares not held for a CC, or a CSP on a symbol outside `would_own` like a leveraged ETF) it instead shows an **informational fair-value zone** computed straight from technicals/IV/fundamentals, clearly labeled as not a recommendation |
| `/autonomy` | Show current autonomy rung (OBSERVE/MANUAL/WHITELIST/FULL) and promotion progress toward the next one |
| `/autonomy <level>` | Change rungs — promotion is refused until the evidence gate (>=20 fills, >=60% fill rate, one risk-reducing close) is met; demotion always succeeds |
| `/status` | Compact overview: account summary + all active short options sorted by expiry + pending approvals |
| `/positions` | Live portfolio: stocks and options with market value and unrealized P&L |
| `/account` | Account balances: net liquidation, buying power, margin, excess liquidity |
| `/pending` | List all pending approvals with score and time-to-expiry |
| `/fills` | Recent fills from the last 7 days with quantity, price, and credit received |
| `/calendar` | Per-day P&L calendar for the last 30 days (net premium cashflow per day) |
| `/campaigns` | Wheel campaigns per symbol: CSP→assignment→CC chain with cumulative net premium and adjusted cost basis |
| `/campaigns open` | Same as `/campaigns` but filtered to open (in-progress) campaigns only |
| `/expire` | Expire all pending approvals (clears the queue without executing) |
| `/health` | System health check: IBKR connections, database, time since last scan, pending/open counts |
| `/help` | List all commands |

### Telegram topic routing

Messages are routed to separate forum topics so each thread stays focused. Defaults match
the IDs listed below; override any `TELEGRAM_THREAD_*` variable in `.env` to match your group.

| Topic (thread ID) | Env var | Content |
|---|---|---|
| **2** (`TELEGRAM_THREAD_SCAN`) | `TELEGRAM_THREAD_SCAN` | Scan-started pings, startup notification, overrun warnings, skipped-symbol card, data-provenance summary — general ops/system messages |
| **52** (`TELEGRAM_THREAD_CSP`) | `TELEGRAM_THREAD_CSP` | Cash-secured put candidates (or "unchanged" digest / "no candidates" diagnostic each cycle) |
| **54** (`TELEGRAM_THREAD_CC`) | `TELEGRAM_THREAD_CC` | Covered-call candidates on currently-held underlyings |
| **56** (`TELEGRAM_THREAD_BUY`) | `TELEGRAM_THREAD_BUY` | Buy-to-own recommendations (stocks worth owning to sell CCs against) |
| **58** (`TELEGRAM_THREAD_ACCOUNT`) | `TELEGRAM_THREAD_ACCOUNT` | Account snapshot: net liq, holdings with nested CCs/CSPs, per-position unrealized P&L % — sent fresh at 09:00 ET then edited in-place each cycle |

## How it works — the full walkthrough, in plain English

The sections below walk the entire system end to end, in the order things actually happen: from
"what stocks does it even look at" to "how does money leave the account." Each one has two parts —
**How it works** (the real mechanism) and **In plain English** (the same thing, no jargon). Skip
around with the links below, or read straight through.

**Jump to:** [The universe](#the-universe--what-it-watches) ·
[Scanning](#scanning--gathering-fresh-data-every-15-minutes) ·
[The analyst bench](#the-analyst-bench--iv-technicals-fundamentals-liquidity-sentiment-and-the-macro-backdrop) ·
[Fair value / the ideal zone](#fair-value--the-ideal-zone) ·
[Generating trade ideas](#generating-trade-ideas) ·
[Scoring](#scoring-and-ranking) ·
[Position sizing and risk](#position-sizing-and-risk--the-rulebook) ·
[Claude's review](#claudes-second-opinion) ·
[Telegram + the autonomy ladder](#telegram-and-the-autonomy-ladder) ·
[Placing the order](#placing-the-order--execution) ·
[Watching positions all day](#watching-positions-all-day--the-intraday-monitor) ·
[Rolling a position](#rolling-a-position) ·
[Managing losses](#managing-losses-and-circuit-breakers) ·
[The wheel](#the-wheel--campaigns) ·
[End of day](#end-of-day--the-daily-report) ·
[Learning from outcomes](#learning-from-outcomes--the-fence) ·
[Backtesting](#backtesting) ·
[Safety net, summarized](#safety-net-summarized) ·
[What's changing next](#whats-changing-next)

---

### The universe — what it watches

**How it works.** `config/universe.yaml` lists three overlapping sets of tickers: a **watchlist**
(names it scans and will sell covered calls against *if you already own them*), a **`would_own`**
list (names it's allowed to sell cash-secured puts on, because if assigned it's genuinely fine to
end up holding the stock), and an **`actively_wheeling`** subset of `would_own` — the core rotation
it scans every 15-minute cycle (GOOGL, NVDA, AMZN, MAGS, BAC, META, PLTR, HOOD, SOFI, HIMS,
NBIS, ASTS, RKLB, RGTI, MARA, TQQQ, UPRO, SOXL, DPST). Everything else in `would_own` ("dip-watch" —
sector ETFs like XLV/XLP, SPY, QQQ, AAPL/MSFT/JPM, and more) isn't scanned every cycle at all — it's only
pulled into a scan when its price *drops* 3%+, since a rally is never a reason to sell a new put on
a name outside the core rotation. Tickers are also grouped into three risk tiers for reference —
**safe bets**, **moderate**, and **risky** — independent of the `actively_wheeling`/dip-watch split.
Leveraged ETFs are call-only and never `would_own` **except TQQQ/UPRO/SOXL/DPST**, a deliberate,
confirmed exception — the account accepts daily-decay risk on assignment for those four
specifically (DPST joined this exception 2026-09-29). AMD is watchlist-only (CC income against an
existing 300-share position) and deliberately not in `would_own` — no CSPs. Tickers ruled out
entirely (never traded) live in `config/universe_archive.yaml`, outside the app's read path.

**In plain English.** This is the shopping list, in three tiers of eagerness. One column says
"stocks we'll write calls against if we already own them." The next says "stocks we're actually OK
ending up owning if a put gets exercised" — but within that list, a smaller "actively wheeling"
core gets checked constantly, while the rest only gets a second look after a real dip, so the
system isn't burning IBKR requests re-checking option chains on names that haven't moved. A
leveraged ETF is normally kept off the would-own list entirely — nobody wants to wake up owning a
3x-leveraged fund — except the four named above, where that tradeoff was made on purpose.

### Scanning — gathering fresh data every 15 minutes

**How it works.** During market hours a loop wakes up every 15 minutes, clock-aligned to ET
quarter-hours (9:30, 9:45, ...). Rather than re-pulling every option chain from IBKR every single
cycle (which would exhaust the ~100 concurrent market-data-line limit IBKR allows), an **intraday
materiality gate** only re-fetches a name's option chain when something about it changed: it moved
past its bucket's threshold since its **last fetch** (0.5% either way for `actively_wheeling`, a 2%
**rally** for a held stock, a 3% **drop** for dip-watch — a symbol in two buckets is tested against
both and any one firing is enough), or it cleared the score floor last cycle. A full sweep is
guaranteed on the first cycle after every process (re)start, and each symbol is force-refreshed
once **its own** last fetch is over 120 min old as a staleness safety net. A manual `/scan` from
Telegram and the startup full sweep fetch `actively_wheeling` ∪ held names unconditionally, but
dip_watch names are **seed-only** (yfinance baseline persisted, no chain fetch) unless they gapped
≥3% overnight — a gap in either direction is a legitimate CSP setup at the open. Behind the
scenes, daily price history is stored in SQLite and only the missing days are re-fetched from
Yahoo Finance, so the system doesn't re-download a year of bars every run.

**In plain English.** Every 15 minutes, it checks in on your positions and the watchlist — but
intelligently, only pulling fresh option prices for things that actually moved or that you own,
instead of hammering the broker's servers with the same requests over and over. You can also force a
full, fresh look any time by typing `/scan`.

### The analyst bench — IV, technicals, fundamentals, liquidity, sentiment, and the macro backdrop

**How it works.** For every symbol under consideration, several independent calculations run:
**IV Rank/Percentile** (is implied volatility high or low relative to its own past year?), **VRP** —
Volatility Risk Premium (current IV minus 30-day realized volatility; positive means the options
market is pricing in more movement than the stock has actually been making, which is the edge a
premium seller is paid for), an **IV/RV ratio** gate (rejects candidates where that richness isn't
present), **technicals** (RSI, MACD, moving averages, ATR, support/resistance levels, and a
trending-up/down/sideways regime classifier), **fundamentals** (free cash flow, debt, dividend
safety, next earnings date), **liquidity** (bid/ask spread, open interest, and volume — filtering out
options too thin to actually trade), a **composite sentiment score** (StockTwits self-tagged
bullish/bearish posts, recent news headlines, and optional Reddit, all scored with a lexicon-based
tone analyzer, blended into one 0–100 number), and a **macro backdrop** computed once per scan — VIX
and its term structure, the 10-year Treasury yield, SPY's recent tape, and broad-market headline
tone.

**In plain English.** This is the research team. Before anyone proposes a trade, they check: is
volatility "expensive" right now compared to how much the stock actually moves? Is the stock trending
or choppy? Are the company's finances solid? Can you actually get in and out of this option without
getting a bad price? What's the crowd's mood on this stock, and what's the overall market doing? None
of this makes a decision by itself — it just feeds the next steps.

### Fair value — the ideal zone

**How it works.** For each stock, `analytics/fair_value.py` computes an **expected move**
(spot price × IV × √(days-to-expiry/365)), then places an **ideal strike band** inside that move,
snapped toward the stock's own support/resistance levels, widened around earnings, and floored at
cost basis for covered calls. It also computes a **minimum credit** — the Black-Scholes fair value
of the option at *realized* (actual, historical) volatility, plus a required edge on top — making the
"am I being paid enough for this risk" question explicit and numeric, rather than a vibe.

**In plain English.** This is the price tag the system writes for itself before shopping. "A put
around here, for at least this much money, is a fair deal — anything cheaper isn't worth the risk."
Every contract actually offered gets compared against that tag.

### Generating trade ideas

**How it works.** Four generators turn the analysis into concrete, priced trades: **covered calls**
(for stocks you already own, find the best strike/expiry to sell against them), **cash-secured puts**
(for `would_own` names, find strikes that pay well without excessive assignment risk — sized to
however much room your account actually has left, not the maximum lot you could theoretically
afford), **rolling** (for existing short options nearing expiry or drifting in-the-money, propose the
best replacement trade), and **buy-to-own** (stocks worth buying specifically so you can write
covered calls against them later, filtered down to only the strongest handful). Every generator keeps
a record of contracts it *considered and rejected*, tagged with every reason it failed — so a quiet
scan still shows its work instead of going silent.

**In plain English.** This is where "sell the AAPL July $200 call for $1.50" actually gets written
down. Nothing here decides whether the trade is allowed — it just proposes candidates, and even the
rejects are kept around so you can see what was looked at and why it didn't make the cut.

### Scoring and ranking

*(Updated: Modernization Phases 1–5 are complete in code: extended Greeks + American pricer, provider abstraction, phase/relative-strength classification, buy-recommendation overhaul, and disk-persisted fundamentals/sentiment cache.)*


**How it works.** Each candidate gets normalized 0–100 scores across IV rank, technicals,
fundamentals, liquidity, and sentiment, blended by configurable weights (`config/scoring_weights.yaml`)
into one number. Candidates below a minimum score floor, or that lose out to a better strike on the
same underlying, are dropped — and *why* each one was dropped ("a better strike on this name already
took the slot" vs. "the batch was full") is recorded rather than silently vanishing.

**In plain English.** Once you have several plausible trades, you need to rank them. This step scores
and sorts them so the best few rise to the top — and keeps a note of why anything that didn't make
the cut got cut.

### Position sizing and risk — the rulebook

**How it works.** This is the one part of the system with **no AI involved at all** — pure,
deterministic Python (`src/engine/risk_engine.py`), and the *only* path to an order. It enforces,
cumulatively across the whole account, not just one trade at a time:

- **Cash feasibility** — a reserve (the greater of 20% of available cash or a $10,000 floor) is set
  aside first; cash-secured puts may only use what's left ("deployable cash").
- **Concentration, measured in risk units** (`collateral × IV × √(days-to-expiry/365)`, not raw dollar
  size — so a $65,000 position in a calm stock and a $15,000 position in a wild one can be compared
  fairly). Per-ticker and per-sector caps apply.
- **Large-position slots** — at most two positions at a time are allowed to exceed the standard
  per-ticker cap (each up to a hard ceiling), so a couple of deliberate, high-conviction bets are
  possible without the whole book turning into a pile of oversized bets.
- **The income gate** — a candidate must offer a premium above its computed fair value plus an edge
  (the VRP floor above); a couple of very low bars on return-on-capital and annualized yield exist
  only to filter out obvious noise, not as the primary test.
- Plus IV-rank and IV/RV-ratio floors, a DTE (days-to-expiry) window, a required delta range, and an
  earnings-date blackout.

Every check runs **twice**: once when the candidate is ranked, and again right before the order is
sent, against a fresh live quote — so a stale price can't slip a bad trade through.

**In plain English.** This is the compliance officer who can't be talked out of anything — not even
by Claude. However good an idea sounds, if it breaks a rule (too much cash, too concentrated in one
name or sector, doesn't pay enough for the risk, wrong timing), it's rejected, automatically, with no
exceptions. This layer is why the system can be trusted not to do something reckless even if every
other layer above it made a mistake.

### Claude's second opinion

**How it works.** The handful of top candidates that survive the rulebook get sent to a language
model (production runs a local model, `qwen3:8b` via Ollama, since this deployment has no `claude -p`
subscription access — the same code path supports the Claude Code CLI too) with the candidate's
numbers, your current portfolio, and reference notes on the ticker. It writes back a structured,
plain-English verdict: a recommendation, confidence, key risks, and assignment considerations. If the
model is unavailable, times out, or returns something unparseable, the system just proceeds without
its commentary — nothing waits on it, and nothing it says can add, resize, or block a trade.

**In plain English.** Think of this as a second pair of eyes that writes you a short note — "this
looks fine because X, but watch out for Y" — in normal English instead of a spreadsheet of numbers.
It's advisory only. It cannot open a position, and it cannot stop one the rulebook already approved.

### Telegram and the autonomy ladder

**How it works.** Approved candidates are sent to your phone via a Telegram bot, routed into separate
topic threads (CSPs, covered calls, buy-to-own ideas, account snapshots, general ops) so each stays
readable. How much happens automatically depends on a **four-rung autonomy ladder**:
`OBSERVE` (proposals only, no Approve/Reject buttons at all — the default for a fresh install) →
`MANUAL` (every trade needs your tap) → `WHITELIST` (a list of symbols you trust auto-execute,
everything else still needs your tap) → `FULL` (anything that clears the rulebook auto-executes).
Moving *up* a rung is refused until the account has actually demonstrated it works (at least 20 real
fills, a 60%+ fill rate, and at least one automatic loss-reducing close having genuinely fired);
moving down is always allowed instantly. Closing a losing or winning position automatically is a
**separate** switch, independent of the rung — because reducing risk should never have to wait for
you to be free to check your phone.

**In plain English.** This is the "how much do I trust the robot" dial, and it only turns up when
the system has proven itself, not because someone flipped a switch. At the safest setting it just
shows you ideas. At the most autonomous setting, it can open its own trades — but only ones that
already passed every rule above, and it still can't override you, and it still closes risky positions
on its own regardless of which setting you're on.

### Placing the order — execution

**How it works.** Once approved (by you, or automatically at WHITELIST/FULL), the executor builds a
**limit order at the mid-price** — never a market order — rounded to the correct tick size, qualifies
the contract with IBKR, and re-checks it against the rulebook one final time with a live quote before
sending. In live mode, a second explicit `[CONFIRM LIVE]` tap is required per order. If the order
doesn't fill, an optional (off by default) "repricing" chase can nudge the limit price toward the
market a few times before giving up. Rolls are placed as a single atomic two-leg combo order (close
the old option, open the new one together) so there's no gap where you're holding neither or both.

**In plain English.** This is the hand that actually presses the button — but only after checking one
more time that the deal is still good, using a real-time price. It never uses a "buy/sell at whatever
price" market order, so you're never at the mercy of a bad fill.

### Watching positions all day — the intraday monitor

**How it works.** Separately from the 15-minute scan loop, an event-driven monitor subscribes to live
price ticks on every open position and checks six conditions continuously: **delta drift** (the
option has moved further in-the-money than intended), a **DTE threshold** (7 days to expiry — deep in
the "gamma window" where price swings hit hardest), a **21-DTE management point** (a deliberate
earlier checkpoint where closing, rolling, or holding are all still comfortable options — added
specifically so decisions aren't first made under time pressure), an **IV spike**, **ex-dividend
risk** (for covered calls, since early assignment risk rises around dividend dates), and
**assignment risk** (delta deep enough and expiry close enough that assignment looks likely). Any
trigger sends you an alert card explaining, in prose, what happened and why it matters.

**In plain English.** This is the lookout who doesn't wait for the next 15-minute check-in — it's
watching live, all session, and taps you on the shoulder the moment something about an open position
needs a decision, well before it becomes urgent.

### Rolling a position

**How it works.** Two different economics apply depending on why you're rolling. An **income roll**
(an unchallenged position, just rolled forward for more premium) still has to clear the normal
return-on-capital and yield floors. A **defensive roll** (rescuing a position that's moved
significantly against you) is judged differently — it's allowed to cost a small, bounded amount of
money, as long as the new position meaningfully reduces the delta (how exposed you are to further
adverse movement) and improves your breakeven. Roll *execution* (placing the order automatically)
ships off by default — today rolls are alert-only until the mechanics have been verified on a live
paper account; approving one manually still works end-to-end.

**In plain English.** Rolling means swapping a losing or expiring short option for a different one,
usually further out in time. If the position is fine and you're just harvesting more premium, it has
to still make good economic sense. If the position has gone against you and this is a rescue, the bar
changes to "does this genuinely make things safer" rather than "does this pay enough."

### Managing losses and circuit breakers

**How it works.** Two automatic exits run every cycle, independent of the autonomy rung: a
**profit-take** (buy back a short once 50% of the credit received has been captured) and a
**loss-exit** (buy back a short once the cost to close reaches a configured multiple — 2× by default —
of what you originally collected). Two account-level circuit breakers sit above individual positions:
a **daily loss halt** (trips if today's *mark-to-market* P&L, not just realized cashflow, falls a
configured percentage of net liquidation) and a **drawdown halt** (trips if net liquidation falls a
configured percentage below its recent high-water mark, catching a slow bleed no single bad day would
trip). Either one automatically engages a persisted `/halt` kill switch that stops all new order
transmission — profit-taking closes still run, since closing risk should never be blocked — until you
send `/resume`.

**In plain English.** This is the seatbelt. Individual trades get closed automatically once they've
made their money or once they've lost too much. And if the whole account has a genuinely bad day or a
slow bleed, everything new stops until a human looks at it — closing existing risk is still allowed,
because getting *out* should never be the thing that's blocked.

### The wheel — campaigns

**How it works.** When a cash-secured put gets assigned, the resulting stock position, any covered
calls later sold against it, subsequent rolls, and the eventual close are all linked into one
**campaign** per symbol — tracking cumulative net premium collected and an **adjusted cost basis**
(the assignment price minus premium already collected per share). That adjusted basis feeds back into
the covered-call gate, so a wheel that's already collected meaningful premium can write strikes below
the raw assignment price without the system reading that as "locking in a loss."

**In plain English.** "The wheel" is a classic options-income pattern: sell a put, get assigned the
stock, sell calls against it, maybe get called away, repeat. This feature tells that whole story as
one thread instead of a pile of disconnected trades, and — importantly — remembers that premium
you've already collected effectively lowers your real cost, even though the broker's raw numbers
don't show that.

### End of day — the daily report

**How it works.** At 4:15 PM ET, a scheduled job pulls the day's option premium cashflow, has the
language model write a short journal-style narrative (interpretation only — it's told not to just
restate the numbers), and sends a summary to Telegram. It also appends today's volatility observation
to the historical IV record (keeping IV rank calculations current), reconciles the outcome ledger
(matching closed trades to what actually happened), and saves a snapshot of positions used the next
day to auto-detect assignments.

**In plain English.** This is the nightly wrap-up: what happened today, in dollars and in words, plus
some quiet housekeeping so tomorrow's numbers stay accurate.

### Learning from outcomes — the fence

**How it works.** Every candidate Claude reviews gets logged — its full signal vector, Claude's
verdict, and what the deterministic rulebook would have done on its own — in an **outcome ledger**.
When a trade closes, a reconciler back-fills what actually happened (expired worthless, closed early,
assigned, not filled) and the realized P&L. Periodically, a read-only analysis buckets scores against
real outcomes to check whether the scoring weights are actually predictive. **None of this can touch
the rulebook, the sizing, or the config that gates real money** — it's enforced by a dedicated test
that fails the build if any of this code ever becomes importable from the trading path. A human reads
the evidence and decides, by hand, whether to adjust `scoring_weights.yaml`. There used to be a
feature that auto-drafted strategy adjustments from this history; it was removed because the signal
it measured is deliberately inert (Claude's opinion never actually changes what trades — so scoring
its "accuracy" doesn't mean much) and needed years of closed trades to be meaningful anyway.

**In plain English.** The system keeps a diary of every recommendation and what actually happened to
it, so that over time you (a person) can look back and ask "was this scoring approach actually right?"
— but there's a hard, tested wall between that diary and the part of the system that risks real money.
Nothing it learns can silently rewrite the rules.

### Backtesting

**How it works.** A standalone, offline simulator replays the covered-call/cash-secured-put
strategies over historical prices — either pricing entries with a fair-value approximation (validates
the mechanics, not the edge) or, more usefully, pricing them from the stock's actual historical
implied-volatility record (so it genuinely measures whether the "sell rich volatility" thesis would
have paid off). It's completely isolated from the live trading path — it imports nothing from, and is
never imported by, the engine or execution code, so nothing it computes can ever influence a real
order.

**In plain English.** This is a flight simulator: "if I'd run this strategy over the last year on this
stock, roughly how would it have done?" It's a research tool, kept firmly separate from anything that
can actually place a trade.

### Safety net, summarized

- **Paper trading by default.** Live orders are blocked unless `LIVE_TRADING=true` is explicitly set
  *and* the account is pointed at the live port — with a loud on-screen banner either way.
- **The Rules Engine is the only door to an order**, runs with zero AI involvement, and checks twice
  — once when ranking, once again with a fresh quote right before sending.
- **Claude (or the local model) can never place, size, or gate a trade** — if it's unavailable, the
  system trades the deterministic, rule-approved list anyway.
- **A second human tap is required for every order in live mode**, on top of whatever the autonomy
  rung already required.
- **Secrets never touch git** — tokens and account IDs live only in a local, gitignored `.env` file.

### What's changing next

A 2026-08-10 full-system review (`docs/superpowers/specs/2026-08-10-remediation-and-ios-app-design.md`)
found and — as of this writing — **already fixed in code** six real defects: cash-secured put sizing
disagreeing with the concentration check, an income filter that accidentally acted as a hidden ~25–30%
volatility floor (excluding calmer, safer names like SPY/GLD/TLT entirely), no genuine loss management
at all, defensive rolls being asked to hit income-trade economics they structurally couldn't,
already-collected wheel premium being invisible to the covered-call gate, and an IV-rank calculation
comparing two subtly different measurements of volatility against each other. One item remains
open — not a code fix, but a **live paper-trading verification session** (does a limit order actually
fill near mid-price on a real account, does the price-chasing logic work, does a live roll's combo
order have the right sign, does IBKR's data subscription actually deliver the greeks the system
expects). That has to be run by a human before the system moves any closer to real money.

Separately, that same document sketches (not yet built) a **read-only-plus-approval Control API** —
a private web service, reachable only over a personal Tailscale network, that can queue the exact same
approve/reject/halt actions Telegram already sends, but structurally has no code path that can place
an order itself — and a companion **native iPhone app** as a richer console for monitoring positions
and approving trades on the go. Telegram stays the actual alerting backbone either way; the phone app
would never be the only way to get a time-sensitive approval.

---

## Prerequisites

- Interactive Brokers account with **IB Gateway** installed (recommended over TWS — lighter weight, no UI overhead, same API)
- Python 3.12+
- A Telegram bot token and your chat ID
- The Claude Code CLI installed and authenticated (`claude --version`) — **or**, if you don't have
  `claude -p` access, [Ollama](https://ollama.com) running locally with a model pulled
  (`claude.backend: "ollama"`, see SETUP.md §14)

See **[SETUP.md](SETUP.md)** for the full step-by-step setup guide.

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env          # fill in Telegram token/chat-id and IBKR account
# Start IB Gateway (paper account, API enabled, port 4002)

python -m scripts.healthcheck  # verifies connection, prints account summary
python -m pytest               # all tests pass without IB Gateway
```

## Running the web app

The web console is a FastAPI JSON API + a Next.js frontend. Full setup lives in
[SETUP.md](SETUP.md); the short version:

```bash
pip install -e ".[web,dev]"        # fastapi, uvicorn, and the dev tools
# .env needs WEB_API_TOKEN (any random string) and SEC_CONTACT_EMAIL (SEC EDGAR requires it)
python -m scripts.start            # API + research worker + the IBKR daemons, all supervised
cd web && npm install && npm run dev    # Next.js on port 3000 (separate — not a Python script)
```

`python -m scripts.start` is the single command for everything on the Python side — see
[SETUP.md §6](SETUP.md) for the full daemon setup; `--no-api`/`--no-research` opt out of the
two web-tier services if you only want the trading daemons.

The AI summary panel is pluggable: set `research.summary.backend` in
`config/research.yaml` to `claude_cli` (default, reuses `src/claude/runner.py`),
`anthropic` (set `ANTHROPIC_API_KEY`), `openai` (set `OPENAI_API_KEY`), or `ollama`
(reuses the local `ollama serve` daemon). A missing key or a failed generation fails
soft to a page with no summary — enrichment, never a dependency.

## Documentation

| File | What it covers |
|---|---|
| **[SETUP.md](SETUP.md)** | Complete setup from scratch to first live trade |
| **[ARCHITECTURE.md](ARCHITECTURE.md)** | What every folder does, how the system fits together, the process/clientId model, and operational risk handling |
| **[How the scan works.md](How%20the%20scan%20works.md)** | Which tickers get scanned, how hard, and when: the three clocks (15-min loop, 120-min per-symbol staleness net, event-driven position monitor), the actively_wheeling / dip-watch / held-position split and their 0.5% / 3% / 2% gates, with a worked day-long scenario |
| **[STATUS.md](STATUS.md)** | What's built, what's deliberately not built, tech stack, known limitations, and the live-cutover gate |
| **[UNIVERSE_RESEARCH.md](UNIVERSE_RESEARCH.md)** | Deep-research findings for every ticker in the universe: tier classification, verified prices/IV ranks (Jun 2026), CC vs CSP appropriateness, leveraged-ETF rules, and data-quality notes. Injected into Claude trade reviews. |
| **[COMPETITIVE_RESEARCH_PLAN.md](COMPETITIVE_RESEARCH_PLAN.md)** | Competitive research findings (Puthouse and peer landscape) and phased implementation tracker for borrowed features C1–C11; all 5 phases complete as of 2026-06-22 |
| **[docs/modernization/README.md](docs/modernization/README.md)** | Internal modernization plan (Phases 1–5): extended Greeks, provider abstraction, phase/RS scoring, recommendation overhaul, disk cache — all complete in code |
| **`Archive/Improvement_Plans/`** | Historical: REMEDIATION.md, IMPROVEMENT_PLAN.md (N1–N23), IMPROVEMENT_PLAN_2.md, SCAN_EFFICIENCY_PLAN.md, SYSTEM_REVIEW.md, TELEGRAM_ROUTING_PLAN.md — all complete and archived |
| **[CLAUDE.md](CLAUDE.md)** | Contributor and AI-assistant guidance |
| **[ib_async_documentation.md](ib_async_documentation.md)** | IBKR API reference (ib_async library) |

## Safety

- **Paper first.** Live execution is blocked unless `LIVE_TRADING=true` in `.env` *and* the live
  port is configured. The system prints a prominent banner on every start showing which mode is active.
- The **Rules Engine** (`src/engine/risk_engine.py`) is the only path to order execution. It runs
  twice — once when ranking candidates, once again at the moment of execution against a fresh live
  quote. It contains no AI and cannot be bypassed.
- All secrets (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_THREAD_SCAN`/`_CSP`/`_CC`/`_BUY`/`_ACCOUNT`, `IBKR_ACCOUNT`) live only in `.env`, which is gitignored.

## Layout

| Path | Purpose |
|---|---|
| `config/` | Tunable YAML: connection settings, risk limits, watchlist, scoring weights |
| `src/common/` | Shared building blocks used everywhere: Pydantic schemas (`schemas.py`), config loading (`config.py`), logging, the market-hours calendar, the `@daily_cached` decorator, `universe.py` (M7) — `effective_universe()` composes operator `universe_overrides` (add/remove edits to `would_own`/`watchlist` made through the web) onto `config/universe.yaml`, 60s TTL cache, fails safe to the YAML base on a broken overrides read — and `assignment_risk.py` (M0 Task 0.3) — the one `is_assignment_risk`/`assignment_risk_thresholds` definition both the monitor (`src/monitor/triggers.py`) and the API (`src/api/routers/options.py`) read, so a short's assignment-risk flag agrees everywhere |
| `src/ibkr/` | IBKR connection, live market data, option chains, portfolio |
| `src/data/` | Provider abstraction layer between the analytics layer and external market-data backends (yfinance today; FMP/Polygon later). `protocols.py` defines the `PriceProvider`/`FundamentalsProvider`/`NewsProvider`/`SymbolDirectoryProvider`/`FilingsProvider`/`BulkPriceProvider` interfaces; `factory.py` picks the active backend from `config/settings.yaml → data.*` and caches it process-wide; `yfinance_backend.py` is the active backend (literally the existing yfinance calls wrapped in a class — no behaviour change); `breaker.py` is the shared per-provider circuit breaker wired into EDGAR and yfinance; `fmp_backend.py` is a documented-but-unwired stub. Analytics/strategies/engine never call `yfinance.*` directly — they go through `src/data/`. IBKR is *not* a provider (it's the broker + execution path, untouched) |
| `src/analytics/` | IV rank, technicals, fundamentals, liquidity scoring; `realized_vol.py` for the IV/RV richness gate (C1); `fair_value.py` computes the **ideal strike zone / minimum credit / action levels** shown beside every contract; `market_conditions.py` (macro backdrop — VIX + VIX term structure, 10y rates, SPY tape, broad-market headline tone) and `sector_context.py` (sector/market backdrop for the single-ticker deep-dive); `black_scholes.py` (full Greeks — delta/gamma/theta/vega/rho) and `american_option.py` (Cox-Ross-Rubinstein American pricer + early-exercise premium, Phase 1); fundamentals and sentiment are disk-cached via `FundamentalCacheRow`/`SentimentCacheRow` (Phase 5) |
| `src/strategies/` | Covered-call, cash-secured-put, rolling candidate generation. The CC/CSP screens return the contracts they **rejected** alongside those they passed (`_evaluation.py`), each tagged with every gate it failed — so a scan that approves nothing still shows what it looked at and why |
| `src/engine/` | Scoring, decision ranking, deterministic risk gate; `capital.py` is the shared capital model (`resolve_caps` / `max_contracts` / `seed_budgets`) that both the CSP generator and the risk gate call, so the two can never disagree about how big a position may be — concentration is measured in **risk units** (`collateral × IV × √(DTE/365)`), not raw collateral |
| `src/claude/` | Headless `claude -p` runner + local-LLM Ollama backend (`backend: "ollama"` is active by default — see SETUP.md §14), output parser, and learning-loop outcome recorder |
| `src/claude/eval/` | Outcome ledger, close reconciler, and score-vs-outcome analysis (does `blended_score` predict realized P&L) |
| `src/execution/` | Order building and execution via IBKR, plus the two web-console pipelines that raise a PENDING approval without generating the candidate themselves: `roll_pipeline.py` (P2-M5, `queue_roll_for_approval`) and `promote_pipeline.py` (P2-M7 predecessor M4, `queue_promoted_for_approval`) |
| `src/notify/` | Telegram messaging and approval service; `command_drain.py` (P2) is the web console's command-drain loop — one handler per web-command kind (`approve`/`reject`/`promote`/`roll_request`/`halt`/`resume`/`set_autonomy`/`universe_add`/`universe_remove`), applied inside `approval_service`'s process so a web action and a Telegram action share one mutation path |
| `src/monitor/` | Event-driven intraday position monitoring |
| `src/backtest/` | Offline CC/CSP income backtest (Black-Scholes-synthesised premiums over historical prices) |
| `src/orchestrator/` | EOD report, plus the scan split three ways: `scan.py` (the `run_scan`/`ScanResult` entry point — orchestration, gating, persistence; M6 adds `save_buy_candidates` calls at both the full-scan and single-ticker `/scan TICKER` call sites, so the web recommendations view reads what a scan produced without recomputing it), `scan_pipeline.py` (per-symbol data production: chain fetch, analytics, sentiment, CC/CSP screens — imports nothing from `src/notify/`, so a non-Telegram caller can run a scan), `scan_progress.py` (all presentation: the checklist + progress-bar messages a `/scan` edits in place, and the end-of-run candidate/buy/snapshot/provenance sends) |
| `src/storage/` | SQLite database models, session management, order-creation idempotency, and the `risk_verdicts.py` assessment audit trail (every contract a scan priced and why it was set aside, pruned to 14 days). `universe_overrides.py` (P2-M7) holds the `set_override`/`clear_override`/`all_overrides` helpers over `UniverseOverrideRow` — the operator add/remove edits `src/common/universe.py` composes onto `config/universe.yaml`. `portfolio_snapshots.py` (P3-P4 M1) appends point-in-time positions+account captures to the `portfolio_snapshots` table for the web portfolio — deliberately separate from the daily `position_snapshots` (whose one-row-per-ET-day contract assignment auto-detection depends on), append-only with no unique constraint, pruned by retention |
| `src/api/` | FastAPI JSON API (`scripts/run_api.py`, port 8787). No IBKR connection, no clientId — reads the trading database (read-only via SQLite `mode=ro`, plus a write-scoped engine for `app_commands` only) and the research database for the research tier. Bearer-token auth via `WEB_API_TOKEN` in `.env`. `commands.py` is the only module allowed to import the write-scoped `get_command_engine` — it enqueues an intent (`submit`) and reads its status back through the read-only engine (`get_status`), and every write route (`routers/commands.py`, `routers/universe.py`) is a thin wrapper over it. `commands.py` is the only module allowed to import the write-scoped `get_command_engine`; `portfolio_source.py` (P3-P4 M1) is the portfolio fallback chain — newest `portfolio_snapshots` row, else `position_snapshots` + the journal's account block, else an explicit "nothing captured" reading that never looks like an empty account. `routers/commands.py` (P2-M1) is the intent queue's write path (`POST /commands`, `GET /commands/{id}`, confirm); `routers/options.py` (P2-M2) is the options console's read surfaces (`GET /options/{approvals,assessed,orders,fills,shorts,controls}`), all owner-only, all read-only; `routers/universe.py` (P2-M7) adds `POST`/`DELETE /universe/{list_name}/{symbol}` beside the existing read-only `GET /universe`; `routers/portfolio.py` (P3-P4 M2) is the portfolio read surfaces (`GET /portfolio/{summary,positions,campaigns,calendar}`), all owner-only, all rendering what the fallback chain found — the empty rung is an explicit 200 with `source="none"`, never zeros; `routers/pnl.py` (P3-P4 M5) is the P&L surfaces (`GET /pnl/{ledger,summary,equity,ledger.csv}`), all owner-only, thin renderers over `src/reporting/pnl.py` — no route computes a P&L figure of its own, marks come from the same `read_portfolio` reading the portfolio page renders, a mixed paper+live summary total is refused with `422 mixed_book`, and the CSV export ships unit-suffixed headers with `None` as an empty cell, never `0` ; `routers/system.py` (the left-rail status card's backend) is `GET /system/status` (7 subsystem health rows: both databases, data providers, the command drain, the intraday monitor, the research worker, and the aggregate IBKR connection) plus `GET /system/{name}/log` (a level-filtered log tail per daemon, capped at 150 lines, `name` validated against a fixed allowlist) |
| `src/research/` | Research data layer: EDGAR ingestion, normalisation, deterministic checks, and pluggable AI summary backends. Separate SQLite database (`data/research.db`) from the trading database — one writer per database, so nightly ingest never serialises against approval_service's writes. Ingestion runs as its own process (`scripts/run_research_worker.py`) — no IBKR connection, no clientId; a failing job is logged and swallowed, and a heartbeat is written only on success. The trading system never imports this package (one-way fence). M3 adds the XBRL fundamentals pipeline: `FilingsProvider` (EDGAR companyfacts), the canonical line-item → us-gaap concept map (`config/research_concepts.yaml`), fact parsing + period selection with restatement precedence (`ingest/concepts.py`), normalisation + persistence (`ingest/fundamentals.py`), bounded materialisation with a background ingest queue (`ingest/materialize.py`), and `GET /research/{symbol}` returning per-section `Section{state, data, reason}` (a slow section is a 200 with a reason, never an error). M4 adds daily-bars/quote/news ingest (`ingest/prices.py`, `ingest/quotes.py`, `ingest/news.py`), enrichment sections in `materialize.py` (technicals/sentiment/news/quote each guarded so one outage cannot cascade), a 15-min warm-tier quote refresh **plus the nightly warm-tier bars+news refresh** (`refresh_warm_tier`, at `research.tiers.warm_refresh_hour_et`, default 04:00 ET — wired 2026-09-08; the M4 build had left it unregistered, so price charts were empty for every symbol but the manually seeded AAPL) in `jobs.py`, the `GET /research/{symbol}/bars` endpoint (lightweight-charts field names, server-side SMA 50/200), and per-provider circuit breakers surfaced on `/health`. M5 adds the checks engine: a 40-check catalogue (`config/research_checks.yaml`) loaded by `checks/definitions.py`, a four-state evaluator `checks/engine.py` (PASS/FAIL/UNKNOWN/NOT_APPLICABLE — UNKNOWN is never coerced to FAIL), the metric library `checks/metrics.py` (`build_metrics` assembles inputs from `NormalizedFinancials` + quote + real `get_iv_stats`/`get_fundamental_stats` calls — off-universe symbols degrade to `UNKNOWN`, never a fabricated value), ETF leverage warnings `checks/warnings.py` (derives the CC-only and deliberate-exception sets from `universe.yaml → leveraged_etfs`), and `checks/payload.py` assembling it all into the `ChecksPayload` that `GET /research/{symbol}` returns (`checks: Section[ChecksPayload]`). Full catalogue with every threshold: `docs/web/checks.md`. M6 adds `GET /research/recommendations` (the scan's buy-to-own list, read through the trading DB read-only, no re-scoring), `GET /research/sectors` (sector cards ordered by average IV rank), `GET /watchlist` + add/remove, `GET /universe` (read-only `universe.yaml`), and `GET /research/{symbol}/options` (the on-demand options-income checks lens — real `iv_rank`/`vrp_points` for a universe symbol, honest `UNKNOWN` for an off-universe one, reusing `checks/metrics.py`/`checks/payload.py` unmodified). M7 adds the pluggable AI summary (`summary/protocol.py` `Summary`/`SummaryProvider`, `summary/context.py` `build_context` — computed values only, never asks the model to calculate, `summary/prompt.py` `build_prompt` — the contract every backend shares, `summary/claude_cli.py` `parse_summary` — shared parser, `summary/{anthropic,openai,ollama}.py` — three transport backends each failing soft to a no-summary page, `summary/service.py` — caching keyed on `(symbol, model, prompt_hash, data_as_of)` with `cache_ttl_hours`, `summary/factory.py` `get_summary_provider` reading `research.summary.backend`, and `GET/POST /research/{symbol}/summary` — GET makes no model call, POST generates on demand) |
| `src/reporting/` | **P3-P4 M4 — the P&L engine.** The third, read-only analytics tier: downstream of everything, upstream of nothing. `legs.py` holds the paired realised-P&L accounting rule (`fill_economics`, `classify_outcome`), moved **verbatim** out of `src/claude/eval/reconcile.py` so the reconciler and the reporting layer share one implementation — `reconcile.py` imports it from here. `pnl.py` holds the read-only builders over the trading DB (`build_legs`, `build_campaigns`, `build_summary`, `equity_curve`) whose honesty rules the P&L surfaces are built on: `net_pnl` is `None` while a leg is open (never `0.0`), unknown unrealised is `None` (never zero), `build_summary` **raises** on a mixed paper/live list, and the journal's `realized_pnl` column is surfaced under its true name `premium_cashflow`. Imports nothing from `src.claude`; `engine/`/`execution/`/`strategies/` may never import it — asserted in `tests/test_web_fence.py` |
| `src/ops/` | **Scan-loop remediation Task 5 — out-of-process watchdog.** `watchdog.py` is a one-shot health check (`scripts/watchdog.py`, run by launchd/cron every `watchdog.interval_seconds`) that runs **outside** every process it monitors — the 2026-09-15..22 outage went unnoticed because the only alerting lived in the process that had stopped. Six pure-function checks (`supervisor`, `gateway_port`, `command_drain`, `monitor`, `scan_loop`, `eod`, plus `iv_history` — seven in total) read heartbeats from `system_settings` and `iv_history`; `decide_alerts` is the ok↔fail state machine persisted to `data/watchdog_state.json` (send on transition, re-alert every `realert_minutes`, recovery notice on fail→ok); `send_telegram` posts plain text with no `parse_mode`, so a MarkdownV2 escaping bug elsewhere can never silence it. No IBKR connection, no clientId. `watchdog.deadman_url` (optional) is pinged on every all-clear run — the only thing that can notice the Mac itself being off or asleep |
| `web/` | Next.js research console (App Router, TypeScript, Tailwind v4). Dark-only token system in `app/globals.css`; IBM Plex Sans/Mono; `cmdk` command palette (`⌘K`) over the SEC symbol directory; left rail driven by `GET /nav`. Ticker page at `/stock/[symbol]` renders a price chart (lightweight-charts candlesticks + volume + SMA 50/200), technicals panel, sentiment panel, news panel, and normalised SEC statements with filing traceability; polls while a section is pending. M5 adds the checks section (`components/checks/`): `CheckRibbon` (one segment per check, state carried by `data-state` + hatch texture not colour alone, score line reads "X of evaluable" never "X of total"), `ChecksSection` (click-to-expand `<button aria-expanded>` per category, renders leveraged-ETF decay warnings), and `CheckRow` (statement + actual + threshold + state; unknown renders `n/a`, never `0`) — rendered as the first section below the price chart. M6 adds the landing page (`app/page.tsx`: search, then `components/home/WatchlistTable.tsx`, then `SectorGrid.tsx`/`SectorCard.tsx` ordered by IV rank) and `app/universe/page.tsx` (originally a read-only `universe.yaml` browser — superseded by the M7 rewrite described below). M7 adds `components/stock/SummaryPanel.tsx` — the AI summary panel (Generate button when nothing is cached, distinct labelled regions for thesis/bulls/bears/watch/caveats, model + `data_as_of` attribution line, caveats always visible) wired in as the last ticker-page section. P3 M3 adds `app/portfolio/page.tsx` and `components/portfolio/` — the portfolio console: positions grouped by underlying, campaigns wheel history, expiry calendar, with account balances above a tab bar. P4 M5 adds `app/pnl/page.tsx` and `components/pnl/` — the P&L console: every trade opened and closed grouped by campaign thread, the summary breakdowns, and the equity curve (gaps render as gaps, no animation), with a CSV export that carries the same filters. `app/options/` (P2) is the options console: `page.tsx` (approvals, assessed, orders/fills/shorts, controls) and `[approvalId]/page.tsx` (approval detail — review, ideal-zone bar, alternatives) — every approve/reject/promote/roll/halt/resume/autonomy action goes through `ConfirmAction` → `submitCommand`/`useCommandStatus` → `CommandReceipt`, the same intent-queue round-trip every write action in the console uses. `app/universe/page.tsx` (P2-M7) consumes `GET /universe`'s `lists[]` shape through `components/universe/{UniverseList,OverrideBadge,AddSymbol}.tsx` — add/remove controls on `would_own`/`watchlist` only, `indexes`/`actively_wheeling` read-only. `app/explain/page.tsx` + `components/explain/` is the System Explanation console — a static, plain-English walkthrough of how the whole pipeline works (adapted from the "How it works" section below), not a data surface: eight subtabs (Overview/Data/Ideas/Gate/Claude/Execution/Watching/This-Dashboard) each mount the shared `<PipelineMap/>` with that subtab's stage highlighted — every box is a live nav control, so the map doubles as cross-tab navigation — plus a `<TiesInto/>` chip list at the foot of each panel linking to related subtabs with the reason why, and a `<SourceRefs/>` list pointing back at the real modules. Reads only the web API on port 8787 — holds no broker connection |
| `Archive/dashboard/` | Streamlit read-only dashboard (archived; restore to `dashboard/` to reinstate) |
| `scripts/` | Command-line entrypoints, including `capacity_report.py` — a read-only account-sizing diagnostic: one row per `would_own` symbol showing how many contracts the account can actually support right now and which constraint would stop the next one — `ibc/start_gateway.sh` (launches IB Gateway via IBC to automate its login/daily-restart; see `SETUP.md` §4), `run_api.py` (starts the web API on port 8787; requires `WEB_API_TOKEN` in `.env`, holds no IBKR connection), `run_research_worker.py` (runs the research ingestion worker; requires `SEC_CONTACT_EMAIL` in `.env`, holds no IBKR connection), and `watchdog.py` (one-shot out-of-process health check, `python -m scripts.watchdog`, run by launchd/cron — see `src/ops/`; holds no IBKR connection) |
| `tests/` | pytest suite (IBKR mocked; no TWS needed) |

---

*This software is for personal use. Trading options involves substantial risk of loss.*
