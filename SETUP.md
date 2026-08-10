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

---

## 5. Configure your universe and risk limits

These files control which stocks the system watches and how aggressively it trades. Open them in a
text editor:

### `config/universe.yaml`

Add the tickers you want the system to scan for covered calls and cash-secured puts.
The `would_own` list is the set of stocks you are genuinely happy to be assigned (i.e. own at the
strike price if the put is exercised). The `indexes:` list is scanned for CC opportunities; CSPs
are only generated for symbols that also appear in `would_own`.

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

| Setting (YAML path) | Default | What it means |
|---|---|---|
| `portfolio.max_pct_per_ticker` | 5.0 | Max % of net liquidation in one ticker |
| `portfolio.max_pct_per_sector` | 25.0 | Max % per sector (uses the `sectors:` map in `universe.yaml`) |
| `portfolio.max_csp_allocation_pct` | 60.0 | Max total cash collateral tied up across all CSPs (% of net liq). **New live users should start at 30–40%** and increase after validating the pipeline. |
| `portfolio.max_new_positions_per_run` | 10 | Max new positions a single scan may propose. New live users should start at 1–3. |
| `covered_call.delta_min` / `delta_max` | 0.20 / 0.35 | Delta range for covered-call strikes |
| `covered_call.min_strike_vs_basis` | 1.00 | Reject CC if strike is below cost basis (prevents locking in a loss on the shares) |
| `cash_secured_put.delta_min` / `delta_max` | 0.15 / 0.30 | Delta range for cash-secured-put strikes |
| `cash_secured_put.max_contracts` | 10 | Hard cap on contracts per single CSP candidate |
| `<strategy>.dte_min` / `dte_max` | 21 / 45 | Days-to-expiry range for new positions |
| `events.earnings_blackout_days` | 14 | Reject candidates that live through / open within N days of earnings |
| `income.require_vrp_edge` | true | **Primary income gate.** Reject a candidate whose credit doesn't clear Black-Scholes fair value priced at *realised* vol (HV30) plus `ideal_zone.min_credit_edge_pct` — the variance-risk-premium thesis made explicit. Reason code `premium_below_fair_value`. Missing ideal-zone data is never a rejection, only a missed optimization. |
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

> Note: `portfolio.max_correlated_exposure_pct` is present but **not enforced** (needs a correlation
> engine — see `STATUS.md`). The per-ticker and per-sector caps are the active concentration gates.

The AUTOMATED-mode circuit breakers live in `config/settings.yaml → automation`:

| Setting (YAML path) | Default | What it means |
|---|---|---|
| `automation.max_auto_trades_per_day` | 10 | Max new-exposure entry orders opened per ET trading day (auto or manual). 0 disables. |
| `automation.daily_loss_halt_pct` | 5.0 | Auto-engage the `/halt` kill switch when today's net realized loss exceeds this % of net liquidation. 0 disables. |

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

---

## 6. Set up the daemons

Two processes must stay running during market hours:

| Daemon | Client IDs | What it does |
|---|---|---|
| Approval service | 14 (exec) + 15 (scan) | Telegram bot, order execution, interactive commands |
| Intraday monitor | 12 | Watches open positions for roll alerts |

> The approval service re-runs the scan every `scheduler.intraday_loop_minutes` (default 15) during
> market hours. To cut cost, that intraday loop only re-fetches an option chain for a `would_own`
> name once its spot has moved past `market_data.intraday_rescan_move_pct` (default 0.5%) since its
> last fetch — held positions and names that just cleared the score floor always refresh, and a full
> sweep is forced every `market_data.force_full_scan_minutes` (default 90). Leave these at the
> defaults unless you want the loop more or less eager. Manual `/scan` always sweeps the full
> universe regardless. If a scan ever overruns the interval (or loses the scan lease),
> the loop counts the skipped cycle and sends a throttled warning; `/status` shows the per-session
> "🔁 N run · ⚠️ M skipped" tally so you can see intended (~26) vs actual scan count.
>
> `market_data.strike_band_max_pct` (default `0.40`) caps how wide the *auto* IV-scaled strike band
> can get, so an extreme-IV leveraged ETF doesn't generate a runaway option-chain fetch. An explicit
> `universe.yaml → strike_bands` per-symbol override is a deliberate choice and is **not** capped.
>
> `market_data.max_strikes_per_symbol` (default `80`, `0` disables) and `qualify_timeout_seconds`
> (default `20`) are the qualification-storm guards. Even within the band cap, a high-IV name with
> dense ($2.50) strike spacing can leave 120+ in-band strikes; the full `strikes × expirations × 2`
> cartesian then becomes a several-hundred-contract qualification burst of mostly-nonexistent weekly
> strikes that floods IBKR with `reqContractDetails` and trips a session-wedging pacing lockout (this
> stalled the 2026-06-22 scan on SMH). The cap keeps only the N strikes nearest spot, and
> qualification is chunked/paced/per-chunk-timeout-bounded so a stuck chunk yields partial results
> instead of hanging the symbol. Leave these at the defaults unless a specific name still storms.

### Option A — single launcher (recommended)

`scripts/start.py` starts **both** daemons together and auto-restarts either if it crashes:

```bash
python -m scripts.start
```

Logs are written to `logs/approval.log` and `logs/monitor.log`. Stop with Ctrl-C.
Flags: `--no-monitor` to skip the monitor, `--no-approval` to skip the approval service.

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
| `/scan` | Triggers a full pipeline scan — full universe sweep with fresh Claude review. Two live messages update as it runs: a **checklist** (Account → Market data → Scoring → Claude review → Sending results) and a **dashboard** with a progress bar + ETA, the current activity, and a 🔴 error log of any symbols that were skipped. Final trade candidates arrive as ✅ Approve / ❌ Reject messages (MANUAL) or are auto-queued (AUTOMATED); a "Buy-to-Own Candidates" card lists the strongest few stocks to acquire for future covered calls. |
| `/scan AAPL` | Single-ticker on-demand scan. Fetches the option chain for one symbol (must be IBKR-listed), runs analytics, applies the risk gate, and replies with a compact summary: price/IV rank, a 💡 premium-environment read (what IV rank + VRP mean for selling), technicals, best CC (if you hold shares), best CSP, and buy-to-own assessment. The best CC/CSP gets a 🤖 Claude/Ollama verdict (recommendation + confidence + why/risks). When a strategy has no qualifying option, the card shows the **closest contract that failed** (strike/premium/score, marked ✗) and a `_Rejected: …_` line naming which gate(s) filtered it out (e.g. "IV rank too low", "annualized yield below floor"). The sources footer reflects what actually produced the numbers (IBKR parity spot vs yfinance, yfinance Greeks fallback). If the ticker doesn't exist on IBKR, replies "ticker not found". |
| `/mode` | Shows the current trading mode (👤 MANUAL or 🤖 AUTOMATED) with a toggle button. AUTOMATED mode executes trades without approval and auto-closes positions at 50% profit. A confirmation prompt appears before enabling AUTO. |
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
| `/profile` | Shows the active trading profile (default / conservative / balanced / aggressive) and its description. |
| `/profile conservative` | Switches to the named profile — overlays tighter delta/DTE/IV/score-floor settings onto the base config for the current and future scans. Valid names: `default`, `conservative`, `balanced`, `aggressive`. |
| `/health` | Connection status for both IBKR links, database reachability, time since last scan, and counts of pending approvals and open orders. |
| `/help` | Lists all available commands. |

Trade approval messages include Claude's full reasoning: why the trade is attractive, key risks, tradeoffs, assignment considerations, rolling considerations, and confidence level — all embedded in the message before the ✅ Approve / ❌ Reject buttons.

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
> during RTH.)

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
- [ ] **Circuit breakers:** `settings.yaml → automation.max_auto_trades_per_day` (default 10) and
      `automation.daily_loss_halt_pct` (default 5.0). The loss breaker auto-engages `/halt`.
- [ ] **Kill switch:** know that `/halt` stops everything instantly and `/resume` re-enables it; the
      halt persists across restarts.
- [ ] **DB backups:** the EOD run writes a rotated snapshot to `data/backups/` — confirm it is being
      created after your first EOD cycle.

---

## 13. The verdict learning loop (optional)

Once scans have run and trades have closed, the system can score how good Claude's reviews
actually were and grow a library of human-approved reasoning skills. Nothing here can place,
size, or gate a trade — it shapes Claude's verdict and ranking only.

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

**Score the verdicts** (read-only; calibration + EV vs the baseline, held-out + per month):

```bash
python -m scripts.evaluate_verdicts
python -m scripts.evaluate_verdicts --since 2026-05-01   # held-out tail only
```

**Score-vs-outcome** (read-only; does `blended_score` actually predict realized P&L? — use it to
decide, by hand, whether `config/scoring_weights.yaml` should change):

```bash
python -m scripts.evaluate_scores
python -m scripts.evaluate_scores --since 2026-05-01 --json
```

**Grow reasoning skills** (human-gated):

```bash
python -m scripts.propose_skill                 # Claude drafts one skill from labeled history
python -m scripts.skills list                   # see active + proposed
python -m scripts.skills show <name>            # read a draft's body, rationale, and stats
python -m scripts.skills promote <name>         # activate it → injected into future review prompts
python -m scripts.skills reject <name>          # archive a draft
python -m scripts.skills retire <name>          # stop injecting an active skill
```

Only skills in `config/skills/active/` are injected. Promotion is always a manual file move you
control (visible in git). Set `claude.skills_enabled: false` in `config/settings.yaml` to disable
injection entirely. See `config/skills/README.md` for the file format and the fence.

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
against a local `qwen3:8b` model. The one exception is `scripts.propose_skill` (the
skill-proposal step of the verdict learning loop, §13), which shells out to `claude -p` directly
regardless of `claude.backend` — without CLI access it fails soft (logs a warning, writes no
proposal). The rest of the learning loop (ledger, reconciliation, verdict scoring, promotion) is
unaffected since it doesn't call Claude at all.

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

**3. Active reasoning skills and the skill-proposal loop work unchanged.**
`config/skills/active/*.md` is injected into the prompt text regardless of backend — no extra
configuration needed. The verdict learning loop (Section 13) is also backend-agnostic: ledger
rows, reconciliation, verdict scoring, and `scripts.propose_skill` all dispatch on
`claude.backend` the same way `review_candidates`/`review_roll` do — with `backend: "ollama"`,
`scripts.propose_skill` drafts its proposal via the local model too (`ollama_runner.propose_skill`,
same `format: "json"` / `think: false` / `num_ctx: 8192` handling). Promotion (`scripts.skills
promote`) is always a human-gated file move regardless of which backend drafted the proposal.

Expect skill drafting to be a harder task for a local model than reviewing candidates — it has to
find patterns across dozens of labeled trade outcomes and write a coherent, falsifiable playbook
from scratch, rather than synthesize pre-computed signals. A weak or generic draft just gets
rejected (`scripts.skills reject <name>`) — low risk, but review proposals from `qwen3:8b` more
critically than you would from `claude -p`.

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
| IBKR daemons stop reconnecting after a TWS/Gateway restart (`reconnect failed after 20 attempts — giving up`) | TWS/Gateway's nightly restart (~midnight ET) outlasted the 20-attempt reconnect window | Restart TWS/Gateway, then restart `python -m scripts.start` (or just the affected daemon) — the reconnect loop only runs once per process lifetime |
| The 15-min intraday scan never fires after a restart — `logs/system.log` shows `Approval service running` but no `Intraday loop started`, and the startup happened during a TWS connectivity drop (`Error 1100`) | The approval service started against a half-dead TWS socket (handshake succeeded, but data requests time out). Startup fill-reconciliation called `reqExecutions`, which hung waiting for an event that never arrived, blocking the intraday-scan task from being created. **Fixed (2026-06-23):** `reqExecutions` is now timeout-bounded and the scan loop is armed before startup reconciliation | If you see this on an unpatched build, restart `python -m scripts.start` once TWS connectivity is restored. After the fix it self-recovers (the reconcile pass is skipped and logged) |
| After a restart, `/account` / `/status` / `/scan` / `/positions` say "IBKR account unavailable", and the logs show `Error 326` ("client id is already in use") → `Peer closed connection. clientId 15 already in use?` → `Could not connect IBKR scan connection` | The restart was fast enough that IB Gateway still held the previous session's clientId when the new scan connection tried to grab it. **Fixed (2026-06-24):** `connect_with_retry` retries with backoff so Gateway can release the id, and the launcher waits `STARTUP_GRACE_SECONDS` before starting daemons | Self-recovers within the retry window. If it persists, wait 30–60s before restarting, or restart IB Gateway to clear the stuck clientId. Exec (orders) and monitor connect on their own client IDs, so order execution is unaffected |
| A 🛑 *Scan blocked* message arrives on Telegram, every symbol in the prior cycle timed out (`option chain for X exceeded symbol_timeout_seconds`), and the logs show `Error 1100` flapping beforehand | The scan socket went **half-dead** mid-session — `isConnected()` still reports connected (TCP handshake up) but TWS has lost its IBKR data farm, so every chain request times out. Left unguarded, one cycle grinds for ~2h and blocks every later 15-min cycle. **Fixed (2026-06-24):** a pre-scan `probe_market_data_health` snapshot and a consecutive-timeout circuit breaker detect the dead farm, notify you with the exact reason, and force a reconnect | Self-recovers — the cycle is skipped and `ib_scan.disconnect()` triggers `AutoReconnect`; the next 15-min cycle should run normally. If blocks persist, restart `python -m scripts.start` once TWS shows all data farms connected. Tune `market_data.health_probe_timeout_seconds` / `max_consecutive_chain_timeouts` if needed |
| The EOD Telegram summary is very late or never arrives, and `logs/eod.log` shows a long run of `reqHistoricalData: Timeout` + `Error 162 … Historical Market Data Service … query cancelled`, one symbol per minute | IBKR's **historical-data farm (HMDS)** was down for the EOD session — the account read succeeds but every `OPTION_IMPLIED_VOLATILITY` request in `_append_daily_iv` times out. Left unguarded, ib_async's 60s default × the full universe delayed the (IV-independent) P&L summary and Telegram send by ~1 hour. **Fixed (2026-06-24):** each request is bounded to 8s (`_IV_REQUEST_TIMEOUT_S`) and a circuit breaker aborts the IV loop after 5 consecutive failures (`_IV_MAX_CONSECUTIVE_FAILURES`), so a dead farm bails in ~40s and the summary still sends on time | On a patched build the report self-recovers (logs `aborting IV append after N consecutive failures`), sends the summary, and lets `iv_history` age one day — it back-fills on the next healthy EOD run or via `scripts.backfill_iv`. On an unpatched build, kill the hung `scripts.run_eod` and re-run it once TWS shows the HMDS farm connected |
| IBKR error 10091 floods the log and zero CC/CSP candidates are generated for a symbol | `market_data_type: 1` (live) set but no real-time subscription for that symbol — IBKR sends no bid/ask, so `strict_mid = None` on every quote | Set `config/settings.yaml → ibkr.market_data_type: 3` (delayed). Delayed data provides bid/ask for all symbols; delta is supplied by the Yahoo Finance fallback. Only switch to `1` if you have verified full subscriptions. |
| IBKR error 354 floods the log and candidates have `greeks_source=black_scholes` | No live model-greeks subscription — the system fell back to Black-Scholes via Yahoo Finance | Acceptable for paper trading with `market_data_type: 3`. For live trading, subscribe to the **US Equity and Options Add-On Streaming Bundle** and set `market_data_type: 1` so IBKR model greeks flow through (required by the live-greeks gate). |
| IBKR error 10197 "No market data during competing live session" | A competing IB Gateway or TWS session is open simultaneously | Close the competing session, or ensure each session uses a distinct clientId and a separate IB Gateway / TWS instance. |
| IBKR error 300 "Can't find EId with tickerId" floods the log | Benign cleanup: ib_async tries to cancel a market data subscription that already timed out | Safe to ignore — these fire after each option chain batch and do not affect scan results. |
| "Unknown contract" warnings for half-dollar strikes (e.g. JPM 292.5) | IBKR doesn't list those non-standard strikes for that expiry | Normal — the strike grid for some underlyings uses $5 or $10 increments; half-dollar strikes are skipped automatically. |
| `claude: command not found` | Claude Code CLI not installed or not on PATH | Run `claude --version`; install if missing |
| `RuntimeError: There is no current event loop` or `socket.socketpair()` crash on healthcheck | Windows + Python 3.14: `ProactorEventLoop` fails on startup | Fixed automatically in `connection.py` (switches to `WindowsSelectorEventLoopPolicy`). If you still see it, ensure you are running the installed version and not an older cached `.pyc`. |
| `ollama: request to http://localhost:11434/api/generate failed: ... Connection refused` | `claude.backend` is `"ollama"`/`"cli_then_ollama"` but `ollama serve` isn't running | Run `ollama serve` (or `brew services start ollama`); verify with `curl http://localhost:11434` |
| `ollama: output parsed to empty list` / `ollama roll: unparseable output` | The local model's JSON didn't match the `ClaudeReview`/`RollReview` schema — often a context-window overflow on a large full scan, which truncates the prompt or the JSON output | Fails soft (same as a `claude -p` failure) — the pipeline proceeds with the deterministic list. If it happens mainly on full `/scan` (not single-ticker), raise `ollama_num_ctx`; otherwise try a larger/different `ollama_model`. |
