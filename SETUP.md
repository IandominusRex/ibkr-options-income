# Setup Guide

Everything you need to get the system running, from a fresh machine to your first approved trade.

---

## 1. Prerequisites

Before you start, make sure you have:

- **Interactive Brokers account** with **IB Gateway** installed (recommended over TWS — lighter
  weight, no desktop UI overhead, same API surface). Download from
  [ibkr.com](https://www.interactivebrokers.com/en/trading/ibgateway-latest.php).
  TWS also works but uses different default ports (see Step 4).
- **Python 3.12 or newer.** Check with `python3 --version`.
- **The Claude Code CLI** installed and signed in. Check with `claude --version`.
  If not installed, follow the Claude Code setup instructions at [claude.ai/code](https://claude.ai/code).
  **Or**, if you don't have `claude -p` access, install [Ollama](https://ollama.com) and set
  `claude.backend: "ollama"` instead — see §14.
- **A Telegram account.** You will create a bot to receive trade alerts and approve trades.

---

## 2. Install the project

```bash
# Clone or download the project folder, then:
cd "IBKR Investments"

# Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate          # macOS/Linux
# .venv\Scripts\activate  | .venv\Scripts\activate.bat       # Windows

# Install all dependencies
pip install -e ".[dev]"
```

To also enable the Streamlit dashboard (currently archived to `Archive/dashboard/`; restore it to `dashboard/` first):

```bash
pip install -e ".[dev,dashboard]"
```

### Social + news sentiment (optional, but recommended — all free)

The scan blends a **composite sentiment** read (StockTwits + news headlines + optional Reddit)
into each candidate, surfaced on the `/scan TICKER` deep-dive card and to Claude. Install the
extra to enable it:

```bash
pip install -e ".[dev,sentiment]"
```

This pulls `vaderSentiment` (offline NLP scorer), `curl_cffi` (needed to reach StockTwits, which
sits behind Cloudflare), and `praw` (Reddit). **No API keys or payment are required** — StockTwits
and news (via yfinance) work out of the box. If the extra is not installed, the scan still runs;
sentiment simply reports "no data" and contributes nothing.

**Reddit is optional and off until you add free credentials.** To enable it, create a free
"script" app at <https://www.reddit.com/prefs/apps> (2 minutes, no cost) and set
`REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` in `.env`. Without them, the Reddit source is skipped
and the composite uses StockTwits + news only. (The old unauthenticated `.json` URL trick no
longer works — Reddit blocks it at the edge.)

---

## 3. Configure your secrets (.env)

Your broker account ID and Telegram credentials are kept in a file called `.env` that is never
committed to git.

```bash
cp .env.example .env
```

Now open `.env` in any text editor and fill in three values:

```
IBKR_ACCOUNT=U1234567          # Your IBKR account ID (optional — uses first account if blank)
TELEGRAM_BOT_TOKEN=123456:ABC…  # From @BotFather on Telegram
TELEGRAM_CHAT_ID=-1003902780355 # Group chat ID (negative for groups/supergroups)

# Forum-topic (thread) IDs — one per purpose. Defaults match a common setup; override
# per-group. Leave a value empty to send that category without a thread (General topic).
TELEGRAM_THREAD_SCAN=2     # System/ops: scan-started pings, startup, overrun warnings
TELEGRAM_THREAD_CSP=52     # Cash-secured put candidates
TELEGRAM_THREAD_CC=54      # Covered-call candidates
TELEGRAM_THREAD_BUY=56     # Buy-to-own recommendations
TELEGRAM_THREAD_ACCOUNT=58 # Account snapshot

LIVE_TRADING=false              # Keep false until you are ready to go live
```

### How to create a Telegram bot

1. Open Telegram, search for **@BotFather**, and start a chat.
2. Send `/newbot`, choose a name (e.g. "MyIBKRBot"), and copy the token it gives you.
3. Add the bot to your group and send any message in the target topic/thread, then visit
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
4. Find `"chat":{"id":...}` in the response — that negative number is your `TELEGRAM_CHAT_ID`.
5. If using a forum-type supergroup with topics, find `"message_thread_id":...` in the same
   response — that number identifies the topic the message was sent in. Repeat this for each
   topic you want the bot to use, and set the corresponding `TELEGRAM_THREAD_*` variable
   (`TELEGRAM_THREAD_SCAN`, `TELEGRAM_THREAD_CSP`, `TELEGRAM_THREAD_CC`, `TELEGRAM_THREAD_BUY`,
   `TELEGRAM_THREAD_ACCOUNT`). Leave a variable unset for DMs or plain (non-forum) groups.

---

## 4. Configure IBKR connection (IB Gateway)

This project uses **IB Gateway** (not TWS). Gateway is a minimal headless process — no charting
UI, lower memory, and it doesn't steal your screen. The API surface is identical.

**Port reference** (IB Gateway defaults differ from TWS):

| App | Paper | Live |
|---|---|---|
| **IB Gateway** | **4002** | **4001** |
| TWS | 7497 | 7496 |

`config/settings.yaml` is pre-configured for IB Gateway (`paper_port: 4002`, `live_port: 4001`).
If you ever switch to TWS, update those values to match.

### Enable the API in IB Gateway

1. Open IB Gateway and log in to your **paper** account.
2. Go to **Configure → Settings → API → Settings**.
3. Check **"Enable ActiveX and Socket Clients"**.
4. Confirm **Socket port** is `4002` — this matches `config/settings.yaml → ibkr.paper_port`.
5. Uncheck **"Read-Only API"** so the system can place orders.
6. Click **OK** and restart Gateway if prompted.

### Verify the connection

Start IB Gateway, then run:

```bash
python -m scripts.healthcheck
```

You should see your account number, net liquidation value, and open positions printed to the
terminal. If you see a connection error, double-check the port and that the API is enabled.

When `claude.backend` is `ollama` or `cli_then_ollama`, the healthcheck also prints an
`Ollama backend : OK/WARN …` line — it confirms the local server is reachable and the configured
`ollama_model` is pulled. A `WARN` (server down, or model not pulled) never fails the healthcheck:
LLM enrichment is optional and the pipeline runs deterministically without it. Fix a WARN by
starting Ollama (the Ollama.app, or `ollama serve`) and running `ollama pull <model>`.

### Automating Gateway login with IBC (recommended for unattended operation)

Gateway forces a full re-login roughly every 24 hours, and until that happens it just sits
disconnected — the intraday loop's own reconnect logic can't help, because there's no one to
click through the login screen. A 2026-08-27 log investigation found exactly this: real
`Error 1100` ("half-dead socket") incidents during actual RTH, plus a 5+ hour disconnected
stretch after one nightly restart because the operator wasn't awake to re-authenticate. This is
a Gateway-uptime problem, not a market-data-subscription problem — a bigger data plan doesn't
fix it.

[IBC](https://github.com/IbcAlpha/IBC) automates the login screen and the restart dialogs so a
human doesn't have to. **What it can't do:** if your account uses IBKR Mobile push-notification
2FA, IBC cannot tap "approve" on your phone for you — that's a deliberate security control, not a
gap in IBC. What it changes in practice:

- **Daily restart** — set an Auto Restart time (below) and Gateway restarts itself each day
  *without* a fresh login, because it reuses the current session's credentials. No 2FA tap needed
  for this one.
- **A missed/timed-out 2FA prompt** — IBC re-triggers the login sequence automatically
  (`ReloginAfterSecondFactorAuthenticationTimeout=yes` + `TWOFA_TIMEOUT_ACTION=restart`) so a
  fresh push is always waiting whenever you next pick up your phone, instead of requiring you to
  notice, open Gateway, and click through the login screen yourself.
- **Once a week**, IBKR requires a full cold restart (Sunday, credentials from auto-restart don't
  carry across it) — you'll still need to tap one push notification then.

**Install** (already done on this machine if you're reading this after the 2026-08-27 setup;
steps below are for a fresh machine):

1. Download the macOS build from the [IBC releases page](https://github.com/IbcAlpha/IBC/releases)
   and unzip it to `~/Applications/ibc`.
2. The repo ships a pre-configured `config.ini` you copy over the extracted one — see below for
   what's set and why. Version-pin note: `scripts/ibc/start_gateway.sh` defaults
   `TWS_MAJOR_VRSN=10.47` — update it (or export `TWS_MAJOR_VRSN` before running) if your
   installed Gateway version differs (**Help → About IB Gateway** in the app).

**`~/Applications/ibc/config.ini` — settings changed from the shipped defaults**, all
login/session-flow only; nothing order- or trade-related was touched (`AllowBlindTrading`,
`ConfirmCryptoCurrencyOrders`, etc. are left at their shipped defaults):

| Setting | Value | Why |
|---|---|---|
| `IbLoginId` / `IbPassword` | *(blank)* | Supplied at launch from `.env` via `scripts/ibc/start_gateway.sh`, never written to this file |
| `TradingMode` | `paper` | Fallback default if the wrapper script isn't used; the wrapper itself derives this from `.env`'s `LIVE_TRADING` so Gateway's mode can never drift from the app's own live-trading gate |
| `ExistingSessionDetectedAction` | `primary` | Unattended-safe: our session keeps running rather than hanging on a manual prompt |
| `AcceptNonBrokerageAccountWarning` | `yes` | Auto-confirms the paper-account disclaimer dialog (login-flow only) |
| `AcceptIncomingConnectionAction` | `reject` | IBC's own recommended setting — matches this system's existing behavior, since local (127.0.0.1) API connections already don't trigger this dialog on this setup |
| `ReloginAfterSecondFactorAuthenticationTimeout` | `yes` | Auto-retries the login sequence on a missed 2FA push instead of exiting |
| `SecondFactorAuthenticationExitInterval` | `60` | Seconds IBC waits for login to finish after you tap approve |
| `AutoRestartTime` | *(blank — see step below)* | Left to Gateway's own GUI-configured value; more reliable than guessing a time blind |

**One-time GUI step:** open Gateway → **Configure → Settings → Lock and Exit**, and set **Auto
restart** (not *Auto logoff*) to a time a little before your account's nightly forced-restart
window (commonly ~23:45–00:45 ET, but this varies — watch the first day's `logs/system.log` for
`Error 1100` timing if you're not sure, and adjust). This is what lets the daily restart skip
2FA. If you ever see a "Trusted IPs" dialog block a local connection, add `127.0.0.1` under
**Configure → Settings → API → Settings** — not needed on this setup today, but the fallback if
`AcceptIncomingConnectionAction=reject` ever behaves differently after a Gateway update.

**Credentials:** add to `.env` (see `.env.example`):

```bash
IBKR_LOGIN_ID=your_ibkr_username
IBKR_LOGIN_PASSWORD=your_ibkr_password
```

**Manual dry run first** — don't skip this:

```bash
./scripts/ibc/start_gateway.sh
```

Watch for the push notification and approve it, then confirm Gateway comes up and
`python -m scripts.healthcheck` connects normally. Only once this works should you wire it into
launchd for unattended auto-start.

**Auto-start with launchd:** create `~/Library/LaunchAgents/com.ibkr.gateway.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.ibkr.gateway</string>

  <key>ProgramArguments</key>
  <array>
    <string>/path/to/IBKR Investments/scripts/ibc/start_gateway.sh</string>
  </array>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/path/to/ibc/logs/launchd.log</string>

  <key>StandardErrorPath</key>
  <string>/path/to/ibc/logs/launchd.log</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.ibkr.gateway.plist
```

To stop it: `launchctl unload ~/Library/LaunchAgents/com.ibkr.gateway.plist`. Load this
*alongside* `com.ibkr.start.plist` (§6) — the Python daemons' own `connect_with_retry` backoff
already tolerates Gateway not being up yet at boot, so load order between the two doesn't matter.

---

## 5. Configure your universe and risk limits

These files control which stocks the system watches and how aggressively it trades. Open them in a
text editor:

### `config/universe.yaml`

Add the tickers you want the system to scan for covered calls and cash-secured puts.
The `would_own` list is the set of stocks you are genuinely happy to be assigned (i.e. own at the
strike price if the put is exercised). The `indexes:` list is scanned for CC opportunities; CSPs
are only generated for symbols that also appear in `would_own`.

**`actively_wheeling:`** (2026-08-27) is a subset of `would_own` — the core names scanned every
15-min cycle the way all of `would_own` used to be (gated by `market_data.intraday_rescan_move_pct`,
see below). Everything in `would_own` but *not* in `actively_wheeling` is "dip-watch": not scanned
every cycle at all, only pulled into a scan once its live spot has **dropped** past
`market_data.dip_pull_in_pct` (default 3%) since its last fetch — a rally is never a reason to sell
a new put on a name outside the core rotation. Keep `would_own` broad (anything you'd genuinely
accept assignment on) and `actively_wheeling` narrow (what you actually want checked constantly) —
a large `would_own` with a small `actively_wheeling` costs almost nothing extra per cycle, since
dip-watch names are cheap price-only probes, not option-chain fetches.

Note that holding a name does not move it out of its bucket: a held `actively_wheeling` name keeps
its 0.5% either-way gate *and* gains the 2%-rally trigger, and a held dip-watch name keeps its 3%
dip trigger and gains the same. The rules add up rather than replacing each other (2026-08-28).

Tickers you've decided you'll never trade don't need to stay in `universe.yaml` at all — move them
to `config/universe_archive.yaml` instead (reference-only, never loaded by the application) so the
reasoning is easy to find later instead of just disappearing.

**Adding a new ticker:** After adding a symbol to `universe.yaml`, run the IV and price
backfills to seed one year of history for it — otherwise IV Rank will be unavailable (IV score
suppressed) and the first scans will pull full price histories from yfinance on demand:
```bash
python -m scripts.backfill_iv
python -m scripts.backfill_prices
```
Also add the symbol to the `sectors:` map so concentration limits work correctly. For an
extreme-IV leveraged ETF, optionally add a `strike_bands:` override so its ~0.25-delta strike is in
scope immediately (otherwise the IV-scaled band fills in once the backfill/EOD has stored its IV).

### `config/risk_limits.yaml`

Conservative defaults are pre-configured. Key settings to review:

**`portfolio:` block (D1, Task 9) — three constraints, each in its own unit.** The order of
application is fixed in code (`engine/capital.resolve_caps`), not configurable: the cash reserve
comes off `excess_liquidity` first, and the CSP budget is a percentage of what's left
("deployable cash") — expressing both against gross cash would let the two knobs contradict each
other.

| Setting (YAML path) | Default | What it means |
|---|---|---|
| `portfolio.cash_reserve_pct` | 20.0 | Job 1 (feasibility). Reserve held free at all times, as a % of available cash (`excess_liquidity`). The reserve is the **greater** of this and `cash_reserve_absolute` — subtracted first, before anything else. |
| `portfolio.cash_reserve_absolute` | 10000 | Job 1. Absolute-dollar floor on the reserve. At $100k cash it's inert (20% = $20,000 already exceeds it); on a smaller account it dominates — e.g. at $16k cash the 20% reserve would be $3,200, but the $10,000 floor wins. |
| `portfolio.max_csp_allocation_pct_of_deployable` | 100.0 | Job 1. Total CSP collateral as a % of **deployable cash** (cash minus the reserve above) — not of net liq, not of gross cash. Lower it to hold room for share purchases (Phase 4). |
| `portfolio.max_risk_units_per_ticker_pct` | 5.0 | Job 2 (concentration), % of net liq, measured in **risk units** (`collateral × IV × √(DTE/365)`) rather than raw collateral — share price is not a risk measure. **Not comparable to the old collateral-based percentage** (risk units are typically 0.05–0.30× collateral). Examined via `scripts/capacity_report.py`: AMD's single lot alone costs ~3.06% of NLV in risk units at $300k/$100k, the floor below which AMD becomes unreachable — 5.0 is a deliberate, human-reviewed choice near the permissive end of the viable 3.1–5.0 range, not an inherited number. |
| `portfolio.max_risk_units_per_sector_pct` | 25.0 | Job 2, same unit, per sector (uses the `sectors:` map in `universe.yaml`). |
| `portfolio.max_collateral_per_ticker_pct` | 10.0 | Job 2 fallback: raw-collateral cap used only when IV is unavailable (strictly more conservative than the risk-unit cap). |
| `portfolio.max_large_positions` | 1 | Job 3 (deliberateness). How many concurrent positions may exceed `max_collateral_per_ticker_pct` via the large-position slot. Measured on **cumulative** per-ticker collateral — what the account already holds in the name plus the new lot — so a name already at the cap can't quietly take another. |
| `portfolio.max_pct_per_ticker_large` | 25.0 | Job 3. Hard ceiling for a large-slot position, **cumulative** raw collateral in one ticker as % of net liq. This is also the backstop on the paths that can't seed the risk-unit tallies from live IV (the order-approval re-gate, the single-ticker deep-dive, the CSP sizer): whatever those paths know about a candidate's IV, one name can never exceed this in raw collateral. |
| `portfolio.max_new_positions_per_run` | 10 | Max new positions a single scan may propose. New live users should start at 1–3. |
| `covered_call.delta_min` / `delta_max` | 0.20 / 0.35 | Delta range for covered-call strikes |
| `covered_call.min_strike_vs_basis` | 1.00 | Reject CC if strike is below cost basis (prevents locking in a loss on the shares) |
| `cash_secured_put.delta_min` / `delta_max` | 0.15 / 0.30 | Delta range for cash-secured-put strikes |
| `cash_secured_put.max_contracts` | 10 | Hard cap on contracts per single CSP candidate |
| `<strategy>.dte_min` / `dte_max` | 7 / 28 | Days-to-expiry range for new positions |
| `events.earnings_blackout_days` | 14 | Reject candidates that live through / open within N days of earnings |
| `income.require_vrp_edge` | true | **Primary income gate for covered calls and cash-secured puts.** Reject a candidate whose credit doesn't clear Black-Scholes fair value priced at *realised* vol (HV30) plus `ideal_zone.min_credit_edge_pct` — the variance-risk-premium thesis made explicit. Reason code `premium_below_fair_value`. Missing ideal-zone data is never a rejection, only a missed optimization. **Rolls are exempt** (along with the ROC/yield floors below) — a defensive roll deliberately pays under the new strike's fair value, so `strategies/rolling.py`'s own `max_debit`/`min_delta_reduction` bounds are a roll's real economic control, not this gate. |
| `income.min_roc_pct` | 0.15 | Noise floor only (the primary gate above replaced it). The old default of 1.0 was a hidden ~25–30% IV floor that made every low-vol name (SPY, GLD, TLT, sector ETFs) unreachable regardless of the actual variance-risk-premium edge. |
| `income.min_annualized_yield_pct` | 0.0 | Noise floor only, same history as above (old default 12.0). |
| `liquidity.min_option_volume` | 10 | Minimum daily option volume. Consider increasing to 50 for multi-contract positions. |
| `iv.min_iv_rank` | 30 | Only sell premium when IV rank is at least this (when known) |
| `live_execution.min_live_premium_ratio` | 0.80 | Send-time floor: reject a fill if the live mid drops below this fraction of the approved premium (IV-crush guard). 0 disables. |
| `live_execution.require_ibkr_greeks_when_live` | true | In LIVE mode, the delta re-gate requires IBKR-sourced greeks (never the paper yfinance fallback). |

The `ideal_zone:` block tunes the **ideal strike / ideal credit / action levels** shown beside every
contract, and changes what the cards and the reasoning prompt say. The strike band, action levels,
and (only if you raise `zone_fit` in `scoring_weights.yaml`) ranking are display/ranking-only. The
one exception is `min_credit_edge_pct`: it sizes `min_credit`, which — when `income.require_vrp_edge`
is on (the default) — **is** the primary income gate (see the `income:` table above).

| Setting (YAML path) | Default | What it means |
|---|---|---|
| `ideal_zone.em_lo_mult` / `em_hi_mult` | 0.30 / 1.20 | Where the ideal strike band sits, in expected moves (1σ = spot × IV × √(DTE/365)). Brackets the delta range actually traded (a 0.15–0.30Δ put sits at ~0.34–0.93σ, a 0.20–0.35Δ call at ~0.48–1.17σ). `em_lo_mult` doubles as the **inner-edge floor**: after the band snaps to a level it is clamped back to this cushion, so it can never slide to at-the-money. |
| `ideal_zone.support_pull_pct` | 3.0 | How close a support/resistance level must be (% of the band edge) for the band to snap to it. The snap moves the **outer** edge onto the level; the inner edge stays clamped at `em_lo_mult`, so the band stretches rather than sliding toward spot. |
| `ideal_zone.earnings_widen_mult` | 0.25 | Extra cushion, in expected moves, when earnings fall inside the option's life |
| `ideal_zone.min_credit_edge_pct` | 10.0 | **Feeds the primary income gate.** Premium demanded over Black-Scholes fair value priced at *realised* vol (HV30). The floor is priced at **that contract's own strike** (not the band's anchor) and is never below the `income.min_roc_pct` / `min_annualized_yield_pct` noise floors, so "clears fair value" means the credit beats all three. When `income.require_vrp_edge` is true (default), a candidate whose premium falls below this floor is rejected with `premium_below_fair_value` — raise to insist on a richer entry, at the cost of fewer candidates. |
| `ideal_zone.buy_margin_of_safety_pct` | 8.0 | Discount applied to the analyst mean target when placing the "buy shares below" level |

The auto-close circuit breakers live in `config/settings.yaml → automation`:

| Setting (YAML path) | Default | What it means |
|---|---|---|
| `automation.max_auto_trades_per_day` | 10 | Max new-exposure entry orders opened per ET trading day (auto or manual). 0 disables. |
| `automation.daily_loss_halt_pct` | 3.0 | Auto-engage the `/halt` kill switch when today's **mark-to-market** loss exceeds this % of net liquidation — measured from the prior EOD position snapshot's summed `unrealized_pnl`, not fill cashflow (D3: a day the system sells premium into a real drawdown always shows a positive *cashflow*, so the old cashflow-based measure never caught it). 0 disables. |
| `automation.drawdown_halt_pct` | 10.0 | Auto-engage the `/halt` kill switch when net liquidation falls this % below its trailing high-water mark (`system_settings.get_high_water_mark`). Catches a slow bleed that no single day's loss trips. 0 disables. |
| `automation.max_loss_multiple` | 2.0 | Buy to close any short whose cost-to-close has reached this multiple of its entry credit. 0 disables. Runs every 15 minutes during the intraday loop. |
| `automation.auto_close_enabled` | true | Enable auto-close: both risk-reducing loss-side exits (buy-to-close at max\_loss\_multiple × entry credit) and profit-takes (50% threshold) buy to close automatically when true; alert-only when false. Independent of the autonomy rung (`/autonomy`) — that ladder governs opening new exposure only, not closing an existing position. |

### Checking what's actually tradeable

After tuning the caps above, check their real effect instead of guessing: the capacity report
prints one row per `would_own` symbol — how many contracts fit at a given account size right now,
and which constraint (`cash`, `ticker_risk`, `sector_risk`, `csp_budget`, `ticker_collateral`,
`large_slot`, `large_ceiling`, or blank if it simply hit the per-candidate contract cap) would stop
the next one.

```bash
python -m scripts.capacity_report --net-liq 300000 --cash 100000   # hypothetical account size
python -m scripts.capacity_report                                   # live account via IBKR
```

Each row is independent — it answers "what could this symbol do on its own," not "what's left
after other candidates already took their share" (that greedy, shared-budget accounting is what
the real scan and the risk gate do). It's read-only: it never places, sizes for execution, or gates
an order. Run it whenever you change a `portfolio.*` cap to make sure a clear majority of your
`would_own` list is still reachable — a cap tight enough to quietly exclude most of the universe is
exactly the kind of bug this report exists to catch.

**Also re-run it whenever your account size changes materially**, not just when you edit a cap.
Every `portfolio:` percentage is relative to net liq or deployable cash (D1, Task 9), so the same
config can behave very differently at a different account size — `cash_reserve_absolute: 10000` in
particular is inert at $100k cash (the 20% percentage reserve already exceeds it) but becomes the
binding reserve well below that, shrinking deployable cash faster than the percentage alone would
suggest. Re-derive with `--net-liq`/`--cash` set to the new figures before trusting the caps; this
run's own baseline (46/46 `would_own` symbols tradeable at $300k NLV / $100k cash, 0 skipped for
missing data) is the number to compare against — though note that baseline predates the 2026-08-27
universe restructure (see STATUS.md's "Tradeable capacity" section): the count is unchanged but the
composition isn't, so re-run this against the current `universe.yaml` before trusting it verbatim.

The final line always states its own coverage — `Coverage: N/M requested symbols had usable
price/IV data (K skipped for missing data)` — so a data outage (no cached IV/price for a symbol)
can never look identical to "fewer symbols are tradeable." If `K` is large, fix the data gap (run
the backfills below) before trusting the tradeable count.

### `config/scoring_weights.yaml`

Controls how much weight each factor gets when ranking candidates (IV rank, technicals,
fundamentals, liquidity, assignment risk). You can leave these at the defaults to start.

Two extra knobs control what gets surfaced:
- `min_candidate_score` (default 55) — the minimum blended score for an option (CC/CSP) candidate
  to reach Claude / Telegram.
- `buy_to_own.min_score` (default 60) and `buy_to_own.max_candidates` (default 8) — the score floor
  and count cap for the "Buy-to-Own Candidates" list. Without the floor the screen surfaced *every*
  non-held, non-bearish watchlist name (e.g. 46/46 over a weekend); raise `min_score` to be pickier
  or `max_candidates` to see more names.

### `config/settings.yaml` — the `data:` block

Selects the active backend for the `src/data/` provider abstraction layer (Phase 2). Each key
names the backend for one of the three Protocols (`price_provider`, `fundamentals_provider`,
`news_provider`). Phase 2 ships only the `yfinance` backend; `fmp` is accepted (the stub exists
in `src/data/fmp_backend.py`) but raises `NotImplementedError` on use — the swap path is
documented but not wired. You can leave these at the `yfinance` defaults; swapping to FMP/Polygon
later is a config change here, not a code change.

---

## 6. Set up the daemons

Two processes must stay running during market hours:

| Daemon | Client IDs | What it does |
|---|---|---|
| Approval service | 14 (exec) + 15 (scan) | Telegram bot, order execution, interactive commands |
| Intraday monitor | 12 | Watches open positions for roll alerts |

> The approval service re-runs the scan every `scheduler.intraday_loop_minutes` (default 15) during
> market hours. To cut cost, that intraday loop uses three thresholds (2026-08-27) instead of
> unconditionally refreshing everything: an `actively_wheeling` name (`universe.yaml`) re-fetches
> its option chain once its spot has moved past `market_data.intraday_rescan_move_pct` (default
> 0.5%) since its last fetch; a held stock position re-fetches once it's **risen** past
> `market_data.held_position_move_pct` (default 2%, up only — this used to be unconditional every
> cycle regardless of direction, previously the single biggest fixed cost in the loop; up-only
> because a new CC candidate needs the room a rally creates, and existing-position risk is
> handled continuously by the separate intraday monitor daemon, not this gate — a drop is still
> caught by the staleness check below); a `would_own` name outside `actively_wheeling`
> ("dip-watch") is skipped every cycle and only pulled in once it **drops** past
> `market_data.dip_pull_in_pct` (default 3%) — a rally never triggers it. Names that just cleared
> the score floor always refresh.
>
> **These three thresholds are combined, not chosen between (2026-08-28).** A symbol that is in
> more than one bucket — a name you hold *and* actively wheel, say — is tested against every rule
> that applies to it, and any one firing is enough. Holding shares therefore never *reduces* how
> often a name is scanned; it only adds the rally trigger. (Before this, `held` won outright, so
> owning shares of an `actively_wheeling` name silently dropped it from the 0.5% either-way gate
> to 2%-up-only — shrinking the core rotation to just the names you *didn't* hold. The CSP screen
> runs for every `would_own` name whether you hold it or not, so a held wheel name genuinely has
> a CSP reason to refetch on a dip that the CC-oriented held rule cannot see.)
>
> An `actively_wheeling`/held name is also force-fetched once
> **its own** last fetch exceeds `market_data.force_full_scan_minutes` (default 120) — checked
> per symbol, not as one synchronized sweep of the whole core, so refreshes for quiet names
> spread out over time on their own instead of bursting together (never dip-watch — that timer
> doesn't apply to it at all) — as well as unconditionally on the first cycle after every service
> (re)start. Each fetched symbol records **its own** fetch timestamp (2026-08-28) rather than one
> shared run-level stamp, so the cohort from a long sweep goes stale spread across the span that
> sweep took instead of all in one later cycle.
>
> **The per-cycle fetch budget (2026-08-28).** `market_data.chain_fetch_budget_seconds` (default
> 600) caps how long one intraday cycle may spend on option-chain fetches. The materiality gate
> keeps a normal cycle tiny, but in a broad sell-off every `would_own` name crosses its bar at
> once — ~23 minutes of fetching inside a 15-minute cycle — and an overrun sets `scan_running`,
> which skips the *next* cycle's scan entirely (profit-take and loss-exit checks still run). When
> the budget runs out the remaining symbols are skipped for chains only (analytics still run) and
> retried first next cycle, so a cluster drains over consecutive on-time cycles. Do not raise this
> without also raising `scheduler.intraday_loop_minutes` — and note the coupling runs the opposite
> way to intuition: **shortening the cycle lowers hourly fetch throughput**, because the ~56s of
> fixed per-cycle work and the 150s overshoot margin are paid every cycle regardless of length
> (206s fixed = 23% of a 15-min cycle, 34% of a 10-min one, 69% of a 5-min one). Leave these at the defaults unless you want the loop more or less eager. Manual
> `/scan` always sweeps the full universe regardless (dip_watch names seed-only unless they
> gapped ≥3% overnight — see `How the scan works.md`). A full sweep (which can still happen all at
> once on a cold start) currently costs 15-25 minutes (IBKR option-chain qualification
> overhead), so it can itself overrun the interval — see `/status`. If a scan ever overruns the
> interval (or loses the scan lease), the loop counts the skipped cycle and sends a throttled
> warning; `/status` shows the per-session "🔁 N run · ⚠️ M skipped" tally so you can see intended
> (~26) vs actual scan count.
>
> `market_data.strike_band_max_pct` (default `0.40`) caps how wide the *auto* IV-scaled strike band
> can get, so an extreme-IV leveraged ETF doesn't generate a runaway option-chain fetch. An explicit
> `universe.yaml → strike_bands` per-symbol override is a deliberate choice and is **not** capped.
>
> `market_data.max_strikes_per_symbol` (default `80`, `0` disables) and `qualify_timeout_seconds`
> (default `20`) are the qualification-storm guards. Even within the band cap, a high-IV name with
> dense ($2.50) strike spacing can leave 120+ in-band strikes; the full `strikes × expirations × 2`
> cartesian used to become a several-hundred-contract qualification burst of mostly-nonexistent
> weekly strikes that flooded IBKR with `reqContractDetails` and tripped a session-wedging pacing
> lockout (this stalled the 2026-06-22 scan on SMH). `_build_chain_contracts` now builds that
> cartesian OTM-side-only per right (calls ≥ spot, puts ≤ spot) instead of both rights across the
> whole band, roughly halving it before the cap even applies. The cap keeps only the N strikes
> nearest spot, and qualification is chunked/paced/per-chunk-timeout-bounded so a stuck chunk
> yields partial results instead of hanging the symbol. Leave these at the defaults unless a
> specific name still storms.

### Option A — single launcher (recommended)

`scripts/start.py` starts **both** daemons together and auto-restarts either if it crashes:

```bash
python -m scripts.start
```

Logs are written to `logs/approval.log` and `logs/monitor.log`. Stop with Ctrl-C.
Flags: `--no-monitor` to skip the monitor, `--no-approval` to skip the approval service.

> **Clean stop, guaranteed:** Ctrl-C/SIGTERM sends every daemon SIGTERM, waits up to 10s, then
> SIGKILLs anything still alive — a hung shutdown can no longer leave an orphaned survivor behind
> (2026-08-27: one did, kept polling Telegram for 30+ minutes, and fought the next restart over
> both the bot token and its clientIds). On startup, before launching anything, the launcher also
> scans for and kills any *other* process still running one of this project's own daemon modules
> — whatever the cause (a crash, a laptop sleep, a second `scripts.start` started by accident),
> a restart always starts from a clean slate.

> **Ollama check at startup:** when `claude.backend` uses Ollama, the launcher probes the local
> model on start and logs a loud `WARNING` if it's unreachable or not pulled. This is a warning,
> **not** a blocker — the daemons start either way and simply skip LLM enrichment (shipping the
> deterministic Rules-Engine list) until Ollama recovers. Nothing auto-starts Ollama; keep the
> Ollama.app running (set it to "Open at Login") or run `ollama serve` yourself.

> **EOD report is automatic:** the launcher schedules the end-of-day report itself — at
> `scheduler.eod_report` (default 16:15 ET) on NYSE trading days it spawns a one-shot
> `scripts.run_eod`. No cron job is needed (see §7). Keep `scripts.start` running across the
> close for it to fire; if it isn't, run `python -m scripts.run_eod` by hand.

### Option B — run each daemon separately

```bash
# Terminal 1
python -m scripts.run_approval_service

# Terminal 2
python -m scripts.run_monitor
```

Keep both terminals open during market hours. **A terminal that closes kills the daemon** —
no Telegram responses, no order fills.

### Keeping daemons alive across crashes (production setup)

**Quick restart wrapper (any platform):**
```bash
while true; do python -m scripts.run_approval_service; sleep 5; done
```

**macOS launchd** — create `~/Library/LaunchAgents/com.ibkr.approval.plist`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.ibkr.approval</string>
  <key>ProgramArguments</key><array>
    <string>/path/to/IBKR Investments/.venv/bin/python</string>
    <string>-m</string><string>scripts.run_approval_service</string>
  </array>
  <key>WorkingDirectory</key><string>/path/to/IBKR Investments</string>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/ibkr_approval.log</string>
  <key>StandardErrorPath</key><string>/tmp/ibkr_approval.log</string>
</dict></plist>
```
Load with `launchctl load ~/Library/LaunchAgents/com.ibkr.approval.plist`.

**Linux systemd** — create `/etc/systemd/system/ibkr-approval.service`:
```ini
[Unit]
Description=IBKR Approval Service
After=network.target

[Service]
WorkingDirectory=/path/to/IBKR Investments
ExecStart=/path/to/IBKR Investments/.venv/bin/python -m scripts.run_approval_service
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```
Enable with `systemctl enable --now ibkr-approval`.

### Using the Telegram bot

Once the approval service is running, you can interact with the system from your phone at any time:

| Command | What you get |
|---|---|
| `/scan` | Triggers a full pipeline scan — full universe sweep with fresh Claude review. Two live messages update as it runs: a **checklist** (Account → Market data → Scoring → Claude review → Sending results) and a **dashboard** with a progress bar + ETA, the current activity, and a 🔴 error log of any symbols that were skipped. Final trade candidates arrive per-candidate on the autonomy ladder: a candidate the current rung clears (WHITELIST/FULL) auto-queues, everything else arrives as a ✅ Approve / ❌ Reject message (buttons withheld at OBSERVE — proposal only); a "Buy-to-Own Candidates" card lists the strongest few stocks to acquire for future covered calls. |
| `/scan AAPL` | Single-ticker on-demand scan. Fetches the option chain for one symbol (must be IBKR-listed), runs analytics, applies the risk gate, and replies with a compact summary: price/IV rank, a 💡 premium-environment read (what IV rank + VRP mean for selling), technicals, best CC (if you hold shares), best CSP, and buy-to-own assessment. The best CC/CSP gets a 🤖 Claude/Ollama verdict (recommendation + confidence + why/risks). When a strategy has no qualifying option, the card shows the **closest contract that failed** (strike/premium/score, marked ✗) and a `_Rejected: …_` line naming which gate(s) filtered it out (e.g. "IV rank too low", "annualized yield below floor"). The sources footer reflects what actually produced the numbers (IBKR parity spot vs yfinance, yfinance Greeks fallback). If the ticker doesn't exist on IBKR, replies "ticker not found". |
| `/autonomy` | Shows the current autonomy rung (🔭 OBSERVE / 👤 MANUAL / 📋 WHITELIST / 🚀 FULL) and progress toward the next one (fills recorded, measured fill rate, whether a risk-reducing close has fired). |
| `/autonomy <level>` | Change rungs, e.g. `/autonomy whitelist`. Promotion (moving up) is refused and the unmet criteria listed until the evidence gate is met (>=20 fills, >=60% fill rate, one risk-reducing close fired) — autonomy is arrived at, not switched on. Demotion always succeeds immediately, no confirmation needed. |
| `/halt` | 🛑 **Kill switch.** Immediately stops all order queuing/transmission (profit-take *closes* still run — closing risk is always allowed). The halt is saved, so it persists across restarts until you `/resume`. You can add a reason, e.g. `/halt market looks ugly`. Also auto-engages on a daily realized-loss breach. |
| `/resume` | Releases the kill switch; QUEUED orders resume on the next poll cycle. |
| `/status` | Compact overview: account totals, all active short options sorted by days-to-expiry, and pending approval / open order counts. Shows a 🛑 HALTED banner when the kill switch is engaged. Good morning check. |
| `/positions` | Live snapshot of all open positions (stocks and options), with market value and unrealized P&L per position. |
| `/account` | Account balances: net liquidation, total cash, buying power, maintenance margin, excess liquidity. |
| `/pending` | Lists all pending approvals by score and time-to-expiry. Useful if you want to review what's waiting before deciding. |
| `/fills` | Shows the last 7 days of executed fills: symbol, strike, quantity, fill price, and credit received. |
| `/calendar` | Per-day P&L calendar for the last 30 days — net premium cashflow per calendar day, with fill count and a running total. |
| `/campaigns` | Wheel campaigns for all symbols: the CSP→assignment→CC→close chain per ticker, with cumulative net premium collected and adjusted cost basis after assignment. |
| `/campaigns open` | Same as `/campaigns` but filtered to open (in-progress) campaigns only. |
| `/expire` | Expires all pending approvals without executing any of them. Use when you decide not to trade for the day. |
| `/health` | Connection status for both IBKR links, database reachability, time since last scan, and counts of pending approvals and open orders. |
| `/help` | Lists all available commands. |

Trade approval messages include Claude's full reasoning: why the trade is attractive, key risks, tradeoffs, assignment considerations, rolling considerations, and confidence level — all embedded in the message before the ✅ Approve / ❌ Reject buttons.

---

## 6a. The web API (optional — research tier)

The web API is a separate process from the trading daemons. It holds **no IBKR connection** and
**no clientId** — by construction it cannot reach the broker. It reads the trading database
**read-only** (enforced by SQLite's `mode=ro` URI, not by convention) and a separate research
database (`data/research.db`) for the research tier.

Install the web extra (FastAPI + uvicorn):

```bash
pip install -e ".[web,dev]"
```

Generate a bearer token and put it in `.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# .env
WEB_API_TOKEN=<that string>
SEC_CONTACT_EMAIL=you@example.com   # SEC EDGAR requires a contact in its User-Agent
```

Run it (loopback only by default; port 8787):

```bash
python -m scripts.run_api
```

| Command | What it does |
|---|---|
| `python -m scripts.run_api` | Starts the web API on `config/research.yaml → api.host:port` (default `127.0.0.1:8787`). Requires `WEB_API_TOKEN` in `.env`. No IBKR connection. |
| `python -m scripts.run_research_worker` | Runs the research ingestion worker (APScheduler). Populates `data/research.db` from SEC EDGAR — the symbol directory first, then weekly refreshes; a nightly warm-tier refresh (daily bars + news for watchlisted/recently-viewed symbols, at `research.tiers.warm_refresh_hour_et`, default 04:00 ET); delayed intraday quotes every 15 min during RTH. Holds no IBKR connection, no clientId. Requires `SEC_CONTACT_EMAIL` in `.env`. |

Endpoints available now: `GET /health` (no auth), `GET /me`, `GET /nav`, and
`GET /research/search?q=<ticker>` (bearer token). See `docs/web/api.md` for the full
reference. The research worker process (`python -m scripts.run_research_worker`) populates
the `symbols` table from SEC EDGAR so search has something to search — run it once on first
start, then it refreshes weekly on its own. See `Web plan/OVERVIEW.md` for the roadmap; the
options, portfolio, P&L and universe sections arrive in later milestones.

### AI summary backend (M7, optional)

The ticker page's AI summary panel is pluggable. Set `research.summary.backend` in
`config/research.yaml` to one of:

| Backend | `.env` key needed | Notes |
|---|---|---|
| `claude_cli` (default) | none | Reuses `src/claude/runner.py`'s `claude -p` subprocess. Only runs if `claude.enabled: true`. |
| `anthropic` | `ANTHROPIC_API_KEY` | Calls Anthropic's Messages API via `httpx` (no SDK dependency). |
| `openai` | `OPENAI_API_KEY` | Calls OpenAI's Chat Completions API via `httpx`. |
| `ollama` | none | Reuses the local `ollama serve` daemon on `localhost:11434` (the same one `src/claude/ollama_runner.py` uses). |

A missing key, a timeout, or a malformed response fails soft to a page with no summary —
the panel shows a **Generate summary** button instead. `GET /research/{symbol}/summary`
makes no model call; only `POST` (the Generate button) does.

### The web frontend (`web/`)

The Next.js console is a separate npm project under `web/`. It talks only to the web API
above — no broker, no direct database access.

```bash
cd web
cp .env.local.example .env.local     # set API_TOKEN to match WEB_API_TOKEN
npm install
npm run dev                          # http://localhost:3000
```

| Command | What it does |
|---|---|
| `npm run dev` | Dev server on `:3000` |
| `npm run build` | Production build |
| `npm run lint` | ESLint (next/core-web-vitals) |
| `npm run test` | Vitest (jsdom) |
| `npm run gen:api` | Regenerate `lib/api-types.ts` from the live `/openapi.json` (API must be up) |

Press `⌘K` (Mac) or `Ctrl+K` (Win/Linux) on any page to open the command palette and
search the symbol directory.

### Using the options console

`/options` (once the API and `web/` are both running) lets you act on what the trading system
proposed, from a browser instead of Telegram. Every action is an **intent**: the console submits
it to `POST /commands`, the running `approval_service` process drains and applies it on its own
schedule (typically within a few seconds), and the console polls the intent to a terminal state
and renders a `CommandReceipt` — nothing on the page ever claims an action succeeded before the
drain actually applied it. Live-mode order-reaching actions (approve, promote, roll_request) carry
the same second `[CONFIRM LIVE]` step execution has always required.

| Action | Where | What it does |
|---|---|---|
| Approve / Reject | `/options`, per pending approval | The exact `_process_button` mutation Telegram's ✅/❌ buttons perform — the web is a second front door onto the same order path, never a second path. |
| Promote | `/options` → Assessed tab, per gate-passed-but-not-yet-approved contract | Re-prices and re-gates the contract fresh (a stored score never gets promoted on trust) and, only if it still clears the Rules Engine, raises a PENDING approval for you to approve above. |
| Propose a roll | `/options` → Shorts tab, per open short | Prices a defensive roll for that position and raises it as a PENDING approval — it does **not** execute the roll. You still approve the proposal separately. |
| Halt / Resume / Autonomy | `/options` controls strip | The same kill switch and autonomy ladder as `/halt`, `/resume`, `/autonomy` in Telegram — one flag, one rung, read by every consumer. Halt is one click, no confirmation; Resume requires typing the word RESUME. |
| Add/remove `would_own` or `watchlist` | `/universe` | Edits the scan universe without touching `config/universe.yaml` by hand. Adding a symbol to `would_own` means the system may start selling cash-secured puts on it and you may be assigned its shares — the console shows that consequence in a confirmation before submitting. `watchlist` is reporting-only and applies immediately. `sectors` and every other list stay file-only; they are not editable from the browser at all. |

See `docs/web/commands.md` for every command kind's payload, dedupe key, and failure reasons, and
`Web plan/P2-design.md` for the full design.

---

## 7. The daily EOD report — scheduled by the launcher (no cron needed)

The end-of-day report fires **automatically from `scripts.start`** — there is no cron job to set
up. At `scheduler.eod_report` (default 16:15 ET, in `config/settings.yaml`) on NYSE trading days,
the launcher spawns a one-shot `scripts.run_eod` subprocess and logs it to `logs/eod.log`. The
last-run date is persisted to `data/eod_scheduler_state.json`, so:

- A launcher restart *after* the report already ran today will **not** re-fire it (which would
  duplicate the journal row + Telegram summary).
- A launcher start *after* the EOD time on a trading day that has **not** yet run fires the report
  immediately (catch-up).
- Weekends and NYSE holidays are skipped automatically.

> **What the report does:** `run_eod` connects to IBKR, fetches positions and P&L, generates a
> Claude journal entry, and sends an end-of-day summary to Telegram's **account snapshot** thread.
> It is short-lived (exits when done). It also covers tasks the always-on daemon does not: P&L
> accounting, journal writing, daily IV/price append, verdict ledger reconciliation, and the
> nightly DB backup. (No morning job is needed — the daemon runs a full scan every 15 minutes
> during RTH.) It also prunes two audit-history tables: `risk_verdicts` (14 days) and the
> intraday `portfolio_snapshots` (default 30 days — `storage.portfolio_snapshot_retention_days`
> in `config/settings.yaml`; a year of intraday history needs a rollup, not a longer retention).

**Requirement:** keep `scripts.start` running across the close so the scheduler can fire. The
launchd / systemd recipes below keep it alive across reboots and crashes.

To change the time, edit `scheduler.eod_report` in `config/settings.yaml` and restart the launcher.
To disable the built-in scheduler, start with `python -m scripts.start --no-eod`.

> **Manual / alternative trigger:** you can always run the report by hand with
> `python -m scripts.run_eod`. If you prefer the OS scheduler instead of the launcher (e.g. you
> don't keep `scripts.start` up 24/7), run `scripts.start --no-eod` and add this crontab line —
> the `data/eod_scheduler_state.json` guard makes the two harmless to run together, but pick one:
>
> ```
> TZ=America/New_York
> # EOD report — 4:15 PM ET Monday-Friday
> 15 16 * * 1-5 cd "/path/to/IBKR Investments" && .venv/bin/python -m scripts.run_eod >> logs/eod.log 2>&1
> ```
>
> **Tip (macOS):** cron needs Full Disk Access when the project lives under `~/Desktop` or
> `~/Documents` — add `/usr/sbin/cron` under **System Settings → Privacy & Security → Full Disk
> Access**.

---

### macOS — auto-start daemons on login with launchd

The launcher (`scripts.start`) runs the daemons *and* the EOD scheduler, so it needs to restart
automatically if the machine reboots. The macOS-native way is a launchd plist.

Create `~/Library/LaunchAgents/com.ibkr.start.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.ibkr.start</string>

  <key>ProgramArguments</key>
  <array>
    <string>/path/to/IBKR Investments/.venv/bin/python</string>
    <string>-m</string>
    <string>scripts.start</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/path/to/IBKR Investments</string>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/path/to/IBKR Investments/logs/start.log</string>

  <key>StandardErrorPath</key>
  <string>/path/to/IBKR Investments/logs/start.log</string>
</dict>
</plist>
```

Load it immediately (no reboot needed):

```bash
launchctl load ~/Library/LaunchAgents/com.ibkr.start.plist
```

To stop it: `launchctl unload ~/Library/LaunchAgents/com.ibkr.start.plist`

> **Note:** launchd restarts the process if it crashes — the same behaviour as `scripts.start`'s
> built-in supervisor, so you get two layers of restart protection.

---

### Windows — Task Scheduler

> **You usually don't need this.** If `scripts.start` stays running across the close (see
> "Auto-start daemons on Windows boot" below), it fires the EOD report itself — skip the EOD task.
> Use the steps below **only** if you run the launcher with `--no-eod` and prefer Task Scheduler to
> trigger `scripts.run_eod` instead.

Windows does not have cron. Use **Task Scheduler** (`taskschd.msc`) instead.

#### Option A — command line (fastest)

Open PowerShell **as Administrator** and run these four commands. Replace `C:\path\to\IBKR Investments` with your real path.

```powershell
# EOD report — 4:15 PM ET Mon-Fri
$action = New-ScheduledTaskAction `
  -Execute "C:\path\to\IBKR Investments\.venv\Scripts\python.exe" `
  -Argument "-m scripts.run_eod" `
  -WorkingDirectory "C:\path\to\IBKR Investments"
$trigger = New-ScheduledTaskTrigger -Weekly `
  -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
  -At "04:15PM"
Register-ScheduledTask -TaskName "IBKR EOD Report" `
  -Action $action -Trigger $trigger `
  -RunLevel Highest -Force
```

> **Timezone:** Task Scheduler always uses the system clock. Set Windows timezone to Eastern Time
> (**Settings → Time & Language → Date & Time → Time zone → Eastern Time (US & Canada)**) and the
> time above is correct. If you are in a different timezone, convert ET to local time manually.

Verify the task was created:
```powershell
Get-ScheduledTask -TaskName "IBKR EOD Report"
```

#### Option B — Task Scheduler GUI

1. Open **Task Scheduler** (search the Start menu for `taskschd.msc`).
2. In the right panel click **Create Basic Task…**
3. Name: `IBKR EOD Report` → Next
4. Trigger: **Weekly** → Next → set time `4:15 PM`, tick Mon/Tue/Wed/Thu/Fri → Next
5. Action: **Start a program** → Next
   - Program: `C:\path\to\IBKR Investments\.venv\Scripts\python.exe`
   - Arguments: `-m scripts.run_eod`
   - Start in: `C:\path\to\IBKR Investments`
6. Finish → tick **Open the Properties dialog** → **Run with highest privileges** → OK.

#### Auto-start daemons on Windows boot

To have `scripts.start` run automatically when the machine starts:

```powershell
$action = New-ScheduledTaskAction `
  -Execute "C:\path\to\IBKR Investments\.venv\Scripts\python.exe" `
  -Argument "-m scripts.start" `
  -WorkingDirectory "C:\path\to\IBKR Investments"
$trigger = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName "IBKR Daemons" `
  -Action $action -Trigger $trigger `
  -RunLevel Highest -Force
```

This starts the approval service and intraday monitor at boot. Task Scheduler will not restart them
if they crash mid-day — `scripts.start`'s built-in supervisor handles that.

---

### Linux — systemd service (recommended for servers)

For a Linux server, run the launcher (`scripts.start`) under systemd — it supervises the daemons
*and* fires the EOD report on schedule, so no cron job is required.

**Daemon service** — create `/etc/systemd/system/ibkr-start.service`:

```ini
[Unit]
Description=IBKR Options Income Daemons
After=network.target

[Service]
Type=simple
User=YOUR_USERNAME
WorkingDirectory=/path/to/IBKR Investments
ExecStart=/path/to/IBKR Investments/.venv/bin/python -m scripts.start
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start it:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ibkr-start
sudo systemctl start ibkr-start
sudo systemctl status ibkr-start   # confirm it is running
```

The EOD report is fired by the launcher itself — **no cron job is required.** (Only if you run
`scripts.start --no-eod` would you add the `15 16 * * 1-5 … scripts.run_eod` crontab line from §7.)

---

## 8. Backfill IV + price history (one-time)

IV Rank requires at least 30 days of historical implied-volatility data, and the technical
indicators/HV30 read from a daily OHLCV store. Seed both once on setup:

```bash
python -m scripts.backfill_iv
python -m scripts.backfill_prices
```

`backfill_iv` fetches one year of historical IV (via IBKR) for every universe symbol;
`backfill_prices` fetches ~1y of daily OHLCV (via yfinance) into `price_history`. Both take a few
minutes and are safe to re-run (existing rows are skipped). After the bootstrap, the **EOD run
appends one fresh IV observation and one settled daily price bar per symbol each day** (N4), so
both windows stay current without re-running the backfill — and `/scan` then reads history from
SQLite, fetching only the missing tail instead of full per-symbol histories. `/health` shows an
"IV history" line and warns if any symbol's latest observation is older than 5 days (i.e. an
appender or backfill has stopped) — re-run the backfills to recover.

---

## 9. Run the test suite

All tests can run without a live TWS connection (IBKR is mocked):

```bash
python -m pytest
```

Also run the quality checks before any code changes:

```bash
ruff check . && ruff format .    # lint + format
mypy src                          # type check
```

---

## 10. Start the Streamlit dashboard (optional, archived)

The Streamlit dashboard has been moved to `Archive/dashboard/`. To reinstate it, copy
`Archive/dashboard/` back to `dashboard/` at the project root, then:

```bash
pip install -e ".[dev,dashboard]"
streamlit run dashboard/app.py
```

Open `http://localhost:8501` in your browser. The dashboard reads from the SQLite database
(`data/income_system.db`) and does not connect to IBKR.

---

## 11. Market data subscriptions

The scan pipeline requires option **bid/ask prices** and **delta** to score and filter candidates.
Bid/ask comes from IBKR's market data feed; delta is sourced from IBKR model greeks when available,
and falls back to a Black-Scholes calculation via Yahoo Finance when not.

### Paper trading (no subscriptions — recommended default)

Use `market_data_type: 3` (delayed) in `config/settings.yaml` — this is the default. IBKR
serves 15-minute delayed bid/ask for all symbols without requiring a paid subscription. Delta is
computed via the Yahoo Finance Black-Scholes fallback, which works for all scanned symbols.

**Do not use `market_data_type: 1` (live) unless you have verified real-time subscriptions for
every symbol in your universe.** Without a subscription, type 1 returns error 10091 and sends
**no bid/ask** for that symbol — causing `strict_mid = None` on every quote and zero candidates,
even though the scan completes without errors.

Your IBKR paper account inherits subscriptions from a linked live account. If you have full US
Options streaming subscriptions on your live account, you may use `market_data_type: 1` for paper
as well, and IBKR model greeks will populate. To verify subscription inheritance on IB Gateway:
log into the **IBKR Client Portal** (interactivebrokers.com) → Settings → Account Settings →
Paper Trading section. IB Gateway has no in-app subscription panel — the Client Portal is the
only place to check.

### Going live — required subscription

Before going live, subscribe to the **US Equity and Options Add-On Streaming Bundle** via
IBKR Account Management (search for "US Equity and Options"). This provides:

- Real-time US stock + option streaming quotes via the API
- `modelGreeks` (delta, gamma, theta, vega, IV) needed for the live-greeks gate

The bundle costs ~$4.50/month and is **fully rebated** if you pay ≥$5 in commissions that month
(which any single trade will exceed). Activate via **IBKR Client Portal** → Settings →
Market Data Subscriptions (IB Gateway has no in-app subscription panel).

For live trading, set `market_data_type: 1` in `config/settings.yaml`. The live-greeks gate
(`require_ibkr_greeks_when_live: true` in `risk_limits.yaml`) blocks any live order where greeks
came from the Yahoo fallback rather than IBKR — this forces real subscriptions before live orders
can be placed.

## 12. Going live

**Do not rush this step.** The system must have run successfully in paper mode for several weeks
before switching to live, and you must have active market data subscriptions (see Step 11).

When you are ready:

1. Confirm you have the US Equity and Options Add-On Streaming Bundle active on your live account
   and that paper scans are producing real CC/CSP candidates with valid delta values.
2. Verify at least 10–20 successful paper trades have filled and confirmed back to Telegram.
3. Open `.env` and change `LIVE_TRADING=false` to `LIVE_TRADING=true`.
4. In `config/settings.yaml`, confirm `ibkr.live_port` is `4001` (IB Gateway live default). If you are using TWS instead, set it to `7496`.
5. Restart all processes (approval service, monitor, cron).
6. The system will print a **prominent banner** on startup confirming it is in LIVE mode and
   which account it is connected to. Verify this before approving any trade.
7. Start with a single small position to validate the full end-to-end flow.

### Live-cutover safety checklist (SYSTEM_REVIEW Phase 2)

These are wired into the code but **review the defaults before you flip the flag**:

- [ ] **Premium-collapse floor (F2):** `risk_limits.yaml → live_execution.min_live_premium_ratio`
      (default 0.80) — a fill is rejected if the live mid drops below this fraction of the approved
      premium. Lower it only if you understand the IV-crush exposure.
- [ ] **Live greeks required (F6):** `risk_limits.yaml → live_execution.require_ibkr_greeks_when_live`
      (default `true`) — in LIVE mode the delta gate requires IBKR-sourced greeks, never the paper
      yfinance fallback. Keep this `true` for live trading.
- [ ] **Circuit breakers:** `settings.yaml → automation.max_auto_trades_per_day` (default 10),
      `automation.daily_loss_halt_pct` (default 3.0, mark-to-market vs. the prior position snapshot —
      not fill cashflow), and `automation.drawdown_halt_pct` (default 10.0, vs. the trailing
      high-water mark). Either loss breaker auto-engages `/halt`.
- [ ] **Kill switch:** know that `/halt` stops everything instantly and `/resume` re-enables it; the
      halt persists across restarts.
- [ ] **DB backups:** the EOD run writes a rotated snapshot to `data/backups/` — confirm it is being
      created after your first EOD cycle.

---

## 13. The verdict learning loop (optional)

Once scans have run and trades have closed, the system can measure how good Claude's reviews
actually were, and whether the scoring weights are earning their keep. Nothing here can place,
size, or gate a trade — it observes and measures only.

**How it accumulates on its own:**

- Every scan writes one **outcome-ledger** row per surfaced candidate (the signals Claude saw, its
  verdict, and what the deterministic baseline would have done).
- The EOD run **reconciles** closed trades — attaching `expired_worthless` / `closed_early` /
  `not_filled` outcomes and realized P&L. You can also run it on demand:

  ```bash
  python -m scripts.reconcile_outcomes
  # An option that was actually assigned (not expired worthless):
  python -m scripts.reconcile_outcomes --assigned <candidate_id>
  ```

**Score-vs-outcome** (read-only; does `blended_score` actually predict realized P&L? — use it to
decide, by hand, whether `config/scoring_weights.yaml` should change):

```bash
python -m scripts.evaluate_scores
python -m scripts.evaluate_scores --since 2026-05-01 --json
```

**Headless-subprocess hardening.** The `claude` block in `config/settings.yaml` constrains the
unattended CLI (it runs ~26+×/day): `max_turns` (default `1` — a single agentic turn),
`disallowed_tools` (the `--disallowedTools` denylist; defaults to all tools), and `model` (pins the
enrichment model, default `claude-sonnet-4-6`). Set `max_turns: 0` / `disallowed_tools: ""` /
`model: ""` to omit the corresponding flag. These bound the subprocess itself; the fence already
keeps Claude's output out of the execution path.

---

## Backtesting a strategy (optional)

Deterministic, offline-ish sizing tool — no IBKR connection, no DB writes. It pulls historical
daily closes from yfinance and simulates CC/CSP income (the system has no historical option chains,
so this is an approximation — see `STATUS.md`).

```bash
# v1 (fair-value, HV-priced — validates plumbing, not the edge):
python -m scripts.backtest --symbol AAPL --strategy cash_secured_put --delta 0.30 --dte 30

# v2 — price entries from stored IV (measures the variance-risk premium), with the 50% take
# and an IV-rank gate (needs scripts.backfill_iv / the EOD appender to have populated iv_history):
python -m scripts.backtest --symbol AAPL --strategy cash_secured_put \
    --use-stored-iv --profit-take 0.50 --min-iv-rank 30
```

v1 prices premiums with Black-Scholes from trailing realised vol — fair value by construction, so
the expected edge is ≈ 0. v2 (`--use-stored-iv`) prices entries from the symbol's stored daily IV,
so the report's **Mean VRP** (IV − HV) and net P&L reflect the actual variance-risk-premium edge;
`--profit-take` and `--min-iv-rank` test the management rules with/without IV-rank gating. The
covered-call P&L is the *option overlay* only (premium minus call-away intrinsic); the underlying's
own appreciation is the buy-&-hold line.

For a compact 4-line summary suitable for pasting into a decision prompt, or to backtest across
historical earnings cycles (C10/C11):

```bash
# Compact 4-line summary:
python -m scripts.backtest_candidate --symbol AAPL --strategy cash_secured_put \
    --delta 0.30 --dte 30 --compact

# Earnings-cycle mode — segmented by prior earnings dates + optional vol-crush entry:
python -m scripts.backtest_candidate --symbol AAPL --strategy cash_secured_put \
    --delta 0.30 --dte 30 --earnings --blackout-before 14 --vol-crush-dte 14
```

To have the same per-candidate backtest injected automatically into the Claude strategist prompt at
scan time (so the reasoning layer sees historical behaviour for each surfaced strike/DTE/delta), set
`claude.backtest_in_prompt: true` in `config/settings.yaml`. It is **off by default** because it adds
a yfinance fetch per candidate while the prompt is built; it is enrichment only and never affects the
deterministic gates.

---

## 14. Local-LLM (Ollama) backend for Claude review

Since June 15, 2026, `claude -p` (the headless CLI this system shells out to ~26+×/day) draws from
a separate monthly **Agent SDK credit** pool billed at API rates, with no rollover. If you'd rather
not depend on that credit — or don't have `claude -p` access at all — you can run the
strategist/roll/EOD reviews against a local model via [Ollama](https://ollama.com) instead.

**This is the active configuration for this deployment** (`backend: "ollama"`, no `claude -p`
access): every review (`review_candidates`, `review_roll`, `write_journal_narrative`) runs
against a local `qwen3:8b` model. The verdict learning loop (§13 — ledger, reconciliation,
score-vs-outcome analysis) is unaffected since it doesn't call Claude at all.

**1. Install Ollama and pull a model:**

```bash
brew install ollama
ollama serve &                       # or: brew services start ollama
ollama pull qwen3:8b                 # ~5GB; comfortable headroom on an 18GB Mac alongside TWS. qwen3:14b (~9GB) if you have the RAM.
```

**2. Choose a backend in `config/settings.yaml → claude`:**

```yaml
claude:
  backend: "ollama"           # "cli" | "ollama" (active here) | "cli_then_ollama"
  ollama_host: "http://localhost:11434"
  ollama_model: "qwen3:8b"
  ollama_timeout_seconds: 120
  ollama_num_ctx: 16384       # context window (tokens) — must cover prompt + JSON output
  ollama_keep_alive: "10m"    # keep model resident between a scan's successive calls
  ollama_temperature: 0.2     # low = disciplined JSON
```

- **`"cli"`** — `claude -p` only. Requires CLI access; not usable in this deployment.
- **`"ollama"`** (**active here**) — every review (`review_candidates`, `review_roll`,
  `write_journal_narrative`) runs against the local model only. No `claude -p` calls, no Agent
  SDK credit usage.
- **`"cli_then_ollama"`** — tries `claude -p` first; if it's unavailable, times out, or returns
  unparseable output (including a hit Agent SDK credit limit), falls back to the local model
  automatically. Switch to this (or `"cli"`) if `claude -p` access becomes available and you want
  Claude to be the primary reviewer again.

**Model choice.** `qwen3:8b` (~5GB) is the active model here — it leaves comfortable memory
headroom on an 18GB Mac alongside TWS/Gateway, and `ollama_runner.py` sends `think: false` so its
hybrid-reasoning `<think>` traces don't fight the `format: "json"` output. Alternatives:
- **`qwen3:14b`** (~9GB, Q4_K_M) — more reasoning depth; use it if you have the RAM (needs
  ~16–18GB free) and want stronger multi-signal judgment.
- **`phi4:14b`** — similar ~9GB footprint, strong structured-output/instruction-following, and
  (not being a hybrid-reasoning model) has no thinking-mode/JSON interaction to worry about — a
  simpler, more predictable choice if `qwen3`'s output proves flaky.

**Expectations:** a small local model is noticeably less reliable at nuanced multi-signal judgment
than Claude — expect more conservative (`wait`) verdicts and occasional validation failures (which
fail soft to `[]`/`None`, same as a CLI failure). `format: "json"` constrains Ollama's output to
valid JSON, but schema-validity (matching `ClaudeReview`/`RollReview`) still depends on the model
following the prompt's instructions. `ollama_runner.py` also raises `num_ctx` to `16384` (config
`ollama_num_ctx`, vs Ollama's 4096 default): the requested window must cover the *whole prompt plus
the generated JSON*, or Ollama silently left-truncates the prompt (dropping the universe context +
candidates at the start) and/or cuts the output mid-JSON — both yield unparseable output and
dropped reviews. A worst-case full scan (10 candidates + 30 memory rows + VIX + spots) measures
~6.3k input tokens; 10 JSON verdicts add ~1.5–2.5k, so 8192 was too tight. Lower `ollama_num_ctx`
to `8192` if `qwen3:8b` OOMs on an 18 GB Mac (a single-ticker `/scan` prompt is much smaller and
fits comfortably). `ollama_keep_alive` (default `10m`) keeps the model resident so a scan's
successive calls don't each pay a reload. Latency is typically 5–40s per call on Apple Silicon for
an 8B model, depending on prompt length and memory pressure.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ConnectionRefusedError` on healthcheck | IB Gateway not running, API not enabled, or wrong port | Start IB Gateway and check API settings (Step 4). Confirm `config/settings.yaml → ibkr.paper_port` matches the Socket port set in Gateway (default `4002`). |
| `clientId already in use` | Another process using the same IBKR client ID | Check `config/settings.yaml` for the `client_ids` map; each process needs a unique ID |
| No Telegram messages | Wrong `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, or one of the `TELEGRAM_THREAD_*` vars | Re-check `.env`; confirm values by visiting `https://api.telegram.org/bot<YOUR_TOKEN>/getMe` (validates the token) and re-running steps 3–5 for the chat/thread IDs. With the approval service running, send `/health` to confirm round-trip messaging. |
| Messages arrive in wrong topic | `TELEGRAM_THREAD_SCAN` / `_CSP` / `_CC` / `_BUY` / `_ACCOUNT` missing or incorrect | Re-check the `message_thread_id` from `getUpdates` for a message sent in the correct topic, and set the matching `TELEGRAM_THREAD_*` variable. |
| Approval button presses do nothing | Approval service not running | Start `python -m scripts.run_approval_service` |
| Zero candidates every scan | Liquidity gates too strict, or no positions/universe configured | Check `config/risk_limits.yaml` thresholds and `config/universe.yaml` |
| `/scan` progress message shows "Scan failed" with a ❌ stage | A critical stage (account fetch or scoring) threw an unexpected exception | Check the approval service logs for the full traceback; restart TWS/Gateway if the account stage fails |
| `/scan` progress freezes on one symbol (e.g. "32/46 — SOFI") and never advances | That symbol's option-chain fetch hung waiting on an IBKR response that never arrived (pacing violation, error 10197 competing-session lockout, or a stuck `qualifyContractsAsync`) | Wait up to `market_data.symbol_timeout_seconds` (default 150s) — the scan logs `option chain for SOFI exceeded symbol_timeout_seconds=... — skipping this symbol` and continues with the remaining symbols. If it still never recovers, the process itself has hung; restart it. |
| Every symbol from one point on times out (`option chain for X exceeded symbol_timeout_seconds`), and the logs show an `Error 200, No security definition has been found` storm just before it | A high-IV name built a several-hundred-contract qualification burst of mostly-nonexistent weekly strikes, tripping an IBKR pacing lockout that wedged the session (the 2026-06-22 SMH stall). This is now guarded: `market_data.max_strikes_per_symbol` caps the strike count, qualification is chunked/paced/timeout-bounded, and `drain_market_data_lines` reclaims leaked lines after each failed symbol | If you still hit it, lower `market_data.max_strikes_per_symbol` (default 80) or `qualify_timeout_seconds`, and restart the process to clear any session-level pacing lockout |
| `/scan` progress reaches "Sending results" but nothing arrives | The follow-up message threw an unhandled exception (e.g. malformed MarkdownV2) | Check `logs/approval.log` for `telegram.error.BadRequest` around the scan's completion time; the scan itself likely succeeded — check `scan complete — run_id=... CC=... CSP=... buy=...` in the same log |
| `/scan TICKER` freezes at "🔍 Scanning NVDA…" and never shows a result, but `logs/approval.log` shows `ticker_scan complete — NVDA CC=… CSP=… buy=…` | The single-ticker result card failed to render as MarkdownV2 (Telegram `BadRequest: Can't parse entities`) and the edit error was swallowed. **Fixed (2026-06-24):** the honest-sources footer now escapes its parentheses (`(parity)`/`(fallback)`), and `_ticker_edit_msg` logs the failure at `WARNING` instead of `debug` so a future render bug is visible | On an unpatched build, look for `ticker_scan: failed to edit message` (now WARNING) and a `telegram.error.BadRequest` in `logs/approval.log`; the scan succeeded, only the message render failed |
| After stopping and restarting `scripts.start`, `/status` says "IBKR connection unavailable", `🔁 0 intraday scans run` even minutes later, and `logs/system.log` shows `Error 326 client id is already in use` → `Peer closed connection` → `Could not connect IBKR scan connection` right after startup | A prior `run_approval_service` didn't actually exit when stopped — `_stop_all` used to `SIGTERM` + immediately `sys.exit(0)` with no check that the child died, so a hung shutdown left an orphan still holding clientIds 14/15 and still polling Telegram (`telegram.error.Conflict: terminated by other getUpdates request`). The new process's *one-shot* startup connect then lost the clientId race, exhausted its bounded retries, and — unlike the persistent post-connect `AutoReconnect` — never retries again for the rest of that process's life, so `/status`/`/scan`/`/positions`/`/account` and the intraday loop's `ib_scan.isConnected()` guard stay dark until you restart. **Fixed (2026-08-27):** see "Clean stop, guaranteed" above — shutdown now force-kills stragglers and startup kills any it still finds | On a patched build this shouldn't happen; if it still does, `ps aux \| grep scripts.run_approval_service` for more than one PID and kill the extra one, then restart `python -m scripts.start` |
| IBKR daemons stop reconnecting after a TWS/Gateway restart (`reconnect failed after 20 attempts — giving up`) | TWS/Gateway's nightly restart (~midnight ET) outlasted the 20-attempt reconnect window — commonly because nobody was available to click through the login/2FA screen for hours. Set up §4 "Automating Gateway login with IBC" so Gateway restarts and reconnects on its own instead | Restart TWS/Gateway, then restart `python -m scripts.start` (or just the affected daemon) — the reconnect loop only runs once per process lifetime |
| The 15-min intraday scan never fires after a restart — `logs/system.log` shows `Approval service running` but no `Intraday loop started`, and the startup happened during a TWS connectivity drop (`Error 1100`) | The approval service started against a half-dead TWS socket (handshake succeeded, but data requests time out). Startup fill-reconciliation called `reqExecutions`, which hung waiting for an event that never arrived, blocking the intraday-scan task from being created. **Fixed (2026-06-23):** `reqExecutions` is now timeout-bounded and the scan loop is armed before startup reconciliation | If you see this on an unpatched build, restart `python -m scripts.start` once TWS connectivity is restored. After the fix it self-recovers (the reconcile pass is skipped and logged) |
| After a restart, `/account` / `/status` / `/scan` / `/positions` say "IBKR account unavailable", and the logs show `Error 326` ("client id is already in use") → `Peer closed connection. clientId 15 already in use?` → `Could not connect IBKR scan connection` | The restart was fast enough that IB Gateway still held the previous session's clientId when the new scan connection tried to grab it. **Fixed (2026-06-24):** `connect_with_retry` retries with backoff so Gateway can release the id, and the launcher waits `STARTUP_GRACE_SECONDS` before starting daemons | Self-recovers within the retry window. If it persists, wait 30–60s before restarting, or restart IB Gateway to clear the stuck clientId. Exec (orders) and monitor connect on their own client IDs, so order execution is unaffected |
| A 🛑 *Scan blocked* message arrives on Telegram, every symbol in the prior cycle timed out (`option chain for X exceeded symbol_timeout_seconds`), and the logs show `Error 1100` flapping beforehand | The scan socket went **half-dead** mid-session — `isConnected()` still reports connected (TCP handshake up) but TWS has lost its IBKR data farm, so every chain request times out. Left unguarded, one cycle grinds for ~2h and blocks every later 15-min cycle. **Fixed (2026-06-24):** a pre-scan `probe_market_data_health` snapshot and a consecutive-timeout circuit breaker detect the dead farm, notify you with the exact reason, and force a reconnect. **Extended (2026-08-28):** the message now also names which symbols never got reached this run and confirms they're queued for the next cycle (`pending_retry_symbols`) — see `How the scan works.md` §4, "The retry queue". **Diagnosis (2026-09-09):** the block message now carries the probe's *root-cause classification* — from the IBKR error codes observed during the probe window — instead of the old hardcoded "Error 1100" label, which mislabelled a real `Error 10197` competing-session block on 2026-09-08. Read the diagnosis line before acting: `10197` means another login on the same IBKR account holds the live-data entitlement (IBKR Mobile, second TWS/Gateway, Client Portal web) and a reconnect will NOT fix it — close the other session, or register a second username for the bot (IBKR supports this for exactly this case). `1100` means Gateway lost its upstream link (the forced reconnect usually recovers it). `354`/`10089`–`10091` mean no market-data subscription for the probe symbol. `1101`/`1102` mean the link is flapping (wait one cycle) | Follow the action hint in the message. For 1100/generic: self-recovers — the cycle is skipped, `ib_scan.disconnect()` triggers `AutoReconnect`, and the queued symbols are forced through the gate on the next 15-min cycle regardless of whether they've moved, so nothing is silently stranded. If blocks persist, restart `python -m scripts.start` once TWS shows all data farms connected. For 10197: closing the other logged-in session is the only real fix — blocks will repeat every cycle until it's closed. Tune `market_data.health_probe_timeout_seconds` / `max_consecutive_chain_timeouts` if needed |
| The scan thread is silent for the full ~15–25 min of a full sweep or multi-symbol retry, with no sense of progress until results (or a block) finally arrive | Before 2026-08-28 the intraday loop ran `run_scan` with no progress callbacks — the `_Tracker` progress-bar renderer already existed for manual `/scan` but was never wired up for the 15-min loop. **Fixed:** `_run_intraday_scan` now sends its own live-updating "🔍 Scanning…" message (progress bar + current symbol, e.g. `⚙️ Option chain — SOFI (31/46)`) before every spawned cycle, edited in place (throttled to ~1 edit/2s) as the scan progresses, same renderer `/scan` uses | Nothing to do — the message appears automatically on every spawned cycle (including quick 1–2 symbol ones, which just flash through 0%→100%) |
| `/status` is sent during a half-dead-socket episode (see the 🛑 *Scan blocked* row above) and never gets any reply at all — not even an error | `isConnected()` only reflects the TCP/exec-socket handshake, which stays up through the half-dead-socket state, so `handle_status_command` took the "IBKR connected" branch and awaited `get_account_snapshot_async` (`accountSummaryAsync`) with no timeout — it hung forever waiting on a data-farm response that never arrived, so the coroutine never reached `reply_text`. **Fixed (2026-08-27):** the account-snapshot fetch is now bounded by `market_data.health_probe_timeout_seconds` (same budget as the scan loop's own health probe); on timeout it logs a warning and replies with the rest of `/status` (positions, pending approvals, open orders) minus the account section | Self-recovers on a patched build — you still get a reply, just without the account-totals line, within `health_probe_timeout_seconds`. On an unpatched build, wait for TWS to show all data farms connected and retry `/status` |
| Only the terse `⚠️ Intraday scan cycle skipped: data-farm health probe failed (half-dead socket)...` warning arrives — the detailed 🛑 *Scan blocked* message above never shows up, and `logs/approval.log` has `Intraday loop: failed to send scan-blocked notice` followed by a `telegram.error.BadRequest: Can't parse entities: character '(' is reserved...` traceback | The 🛑 *Scan blocked* send itself was broken: it interpolated the plain-English block reason (which contains literal parentheses, e.g. `(half-dead socket)`) into a MarkdownV2 message without escaping it, so Telegram rejected the whole message and the failure was swallowed. This affected every block since the 2026-06-24 fix above shipped — the "notify you with the exact reason" behavior never actually worked. **Fixed (2026-08-13):** the reason is now escaped with `_md_escape` before being sent | Self-recovers on a patched build — you'll get both the 🛑 detail message and the ⚠️ skip warning going forward. On an unpatched build the skip warning alone is enough to know a reconnect is in progress; check `logs/approval.log` for the specific block reason |
| A manual `/scan` finishes and shows an ordinary (often empty) results screen, but `logs/approval.log` shows `N consecutive chain timeouts — aborting run, socket appears half-dead (processed X/46 symbols)` with `X` well short of the universe size | The half-dead-socket circuit breaker fired mid-scan and `run_scan` sent whatever partial results it had gathered — with no indication anything was cut short. `handle_scan_command` only checked `result.lease_skipped`, never `result.aborted_unhealthy` (the intraday loop already checked it). **Fixed (2026-08-13):** the `/scan` progress message is now edited to report `processed/total` symbols and that results are partial, and a reconnect is forced the same way the intraday loop does | Self-recovers — a forced reconnect fires automatically. On a patched build just re-run `/scan` once the reconnect completes (a few seconds). On an unpatched build, check `logs/approval.log` for the "consecutive chain timeouts" line to know whether a short results screen is a real empty scan or a truncated one |
| A 15-min intraday cycle you expected (e.g. `13:30 ET`) never shows a `🔄 Scan started` message and `logs/approval.log` has no `Intraday loop: RTH cycle starting` line for it at all — not even a skip warning — while the *previous* cycle's `scan: processing <TICKER>` lines are still advancing past the 15-min mark | The prior cycle's scan was legitimately slow on a perfectly healthy connection (not a dead socket — no circuit breaker involved) and ran past 15 minutes, most commonly right after a restart: with no `scan_state` history yet, the S1 materiality gate treats the entire universe as material (`intraday materiality gate — 46/46 symbols material`) instead of the usual filtered subset, and several large chains can each take 50–60s. **Fixed (2026-08-13):** the scan now runs as its own task (`_run_intraday_scan`, spawned via `asyncio.create_task`) instead of being awaited inline, so the loop keeps hitting every 15-min mark (and its profit-take/loss-exit checks) regardless of how long a previous scan is still taking; an overrun now correctly logs/notifies "previous scan still running" on the next mark instead of vanishing | Self-recovers — this is expected for the first cycle or two after a restart while `scan_state` warms up; later cycles narrow back to the materiality-gated subset and finish well under 15 minutes. On an unpatched build, no action self-corrects the missing cycle — the next mark after the slow scan finishes will just resume normally |
| The EOD Telegram summary is very late or never arrives, and `logs/eod.log` shows a long run of `reqHistoricalData: Timeout` + `Error 162 … Historical Market Data Service … query cancelled`, one symbol per minute | IBKR's **historical-data farm (HMDS)** was down for the EOD session — the account read succeeds but every `OPTION_IMPLIED_VOLATILITY` request in `_append_daily_iv` times out. Left unguarded, ib_async's 60s default × the full universe delayed the (IV-independent) P&L summary and Telegram send by ~1 hour. **Fixed (2026-06-24):** each request is bounded to 8s (`_IV_REQUEST_TIMEOUT_S`) and a circuit breaker aborts the IV loop after 5 consecutive failures (`_IV_MAX_CONSECUTIVE_FAILURES`), so a dead farm bails in ~40s and the summary still sends on time | On a patched build the report self-recovers (logs `aborting IV append after N consecutive failures`), sends the summary, and lets `iv_history` age one day — it back-fills on the next healthy EOD run or via `scripts.backfill_iv`. On an unpatched build, kill the hung `scripts.run_eod` and re-run it once TWS shows the HMDS farm connected |
| Re-running `python -m scripts.run_eod` for a day that already has a journal entry | Expected — the EOD run is idempotent | `_write_journal` upserts by `entry_date`: the existing `JournalRow` is replaced with the new run's numbers (every field but `created_at`), not skipped or duplicated. This also means a repeat run still reaches the reconciler, assignment auto-detection, and tomorrow's position-snapshot baseline — before the 2026-09-09 fix, a same-day re-run raised `IntegrityError` on the first (insert-only) journal write and silently skipped all three. |
| IBKR error 10091 floods the log and zero CC/CSP candidates are generated for a symbol | `market_data_type: 1` (live) set but no real-time subscription for that symbol — IBKR sends no bid/ask, so `strict_mid = None` on every quote | Set `config/settings.yaml → ibkr.market_data_type: 3` (delayed). Delayed data provides bid/ask for all symbols; delta is supplied by the Yahoo Finance fallback. Only switch to `1` if you have verified full subscriptions. |
| IBKR error 354 floods the log and candidates have `greeks_source=black_scholes` | No live model-greeks subscription — the system fell back to Black-Scholes via Yahoo Finance | Acceptable for paper trading with `market_data_type: 3`. For live trading, subscribe to the **US Equity and Options Add-On Streaming Bundle** and set `market_data_type: 1` so IBKR model greeks flow through (required by the live-greeks gate). |
| IBKR error 10197 "No market data during competing live session" | A competing IB Gateway or TWS session is open simultaneously | Close the competing session, or ensure each session uses a distinct clientId and a separate IB Gateway / TWS instance. |
| IBKR error 300 "Can't find EId with tickerId" floods the log | Benign cleanup: ib_async tries to cancel a market data subscription that already timed out | Safe to ignore — these fire after each option chain batch and do not affect scan results. |
| "Unknown contract" warnings for half-dollar strikes (e.g. JPM 292.5) | IBKR doesn't list those non-standard strikes for that expiry | Normal — the strike grid for some underlyings uses $5 or $10 increments; half-dollar strikes are skipped automatically. |
| `claude: command not found` | Claude Code CLI not installed or not on PATH | Run `claude --version`; install if missing |
| `RuntimeError: There is no current event loop` or `socket.socketpair()` crash on healthcheck | Windows + Python 3.14: `ProactorEventLoop` fails on startup | Fixed automatically in `connection.py` (switches to `WindowsSelectorEventLoopPolicy`). If you still see it, ensure you are running the installed version and not an older cached `.pyc`. |
| `ollama: request to http://localhost:11434/api/generate failed: ... Connection refused` | `claude.backend` is `"ollama"`/`"cli_then_ollama"` but `ollama serve` isn't running | Run `ollama serve` (or `brew services start ollama`); verify with `curl http://localhost:11434` |
| `ollama: output parsed to empty list` / `ollama roll: unparseable output` | The local model's JSON didn't match the `ClaudeReview`/`RollReview` schema — often a context-window overflow on a large full scan, which truncates the prompt or the JSON output | Fails soft (same as a `claude -p` failure) — the pipeline proceeds with the deterministic list. If it happens mainly on full `/scan` (not single-ticker), raise `ollama_num_ctx`; otherwise try a larger/different `ollama_model`. |
| Web API returns 403 on `/research/search` | `SEC_CONTACT_EMAIL` missing in `.env` — SEC EDGAR rejects requests without a contact in the User-Agent | Set `SEC_CONTACT_EMAIL=you@example.com` in `.env` and restart `python -m scripts.run_research_worker` (the worker makes the EDGAR calls, not the API) |
| Web API returns 401 on every request | `WEB_API_TOKEN` in `.env` doesn't match `API_TOKEN` in `web/.env.local` (or the proxy's `Authorization: Bearer <token>` header is missing) | Generate a token with `python -c "import secrets; print(secrets.token_urlsafe(32))"`, set it in both `.env` files, and restart both the API and `npm run dev` |
| Search returns "No match" for everything in the web console (but works via `curl` against :8787) | An old build of the token proxy dropped the query string — `?q=…` never reached the backend | Rebuild the frontend (`cd web && npm run build && npm start`, or restart `npm run dev`); fixed 2026-09-08 |
| A watchlist remove or live-mode confirm shows "the command could not be created" while the backend actually succeeded | An old proxy turned upstream 204s into 500s (a 204 must carry a null body) | Same fix — rebuild/restart the frontend; fixed 2026-09-08 |
| Ticker page price chart is empty (every symbol but AAPL) | The research worker's nightly warm-tier refresh hasn't run yet (first run at `warm_refresh_hour_et`, default 04:00 ET) or the worker isn't running | Check `GET /health → worker_heartbeat`; either wait for the nightly job or run one warm refresh manually: `python -c "from src.research.ingest.quotes import refresh_warm_tier; refresh_warm_tier()"` |
| Web search returns no results for any ticker | The research worker hasn't run yet — `data/research.db` has no `symbols` rows | Run `python -m scripts.run_research_worker` once on first start; it pulls the SEC symbol directory (~10k tickers). Search works after the first successful job |
| Ticker page's AI summary panel says "unavailable" and the Generate button does nothing | `research.summary.backend` is set to `anthropic`/`openai` but `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` is missing in `.env`, or `claude_cli` is set but `claude` isn't on PATH and `claude.enabled` is false | Set the matching `.env` key, or switch `research.summary.backend` to `ollama` (requires `ollama serve` running) — a failed generation fails soft to `pending`, never an error |
