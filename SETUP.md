# Setup Guide

Everything you need to get the system running, from a fresh machine to your first approved trade.

---

## 1. Prerequisites

Before you start, make sure you have:

- **Interactive Brokers account** with Trader Workstation (TWS) or IB Gateway installed.
  Download from [ibkr.com]
  (https://www.interactivebrokers.com/en/trading/tws.php) or (https://www.interactivebrokers.com/en/trading/ibgateway-latest.php).
- **Python 3.12 or newer.** Check with `python3 --version`.
- **The Claude Code CLI** installed and signed in. Check with `claude --version`.
  If not installed, follow the Claude Code setup instructions at [claude.ai/code](https://claude.ai/code).
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
TELEGRAM_THREAD_ID=2            # Topic/thread ID within the group (omit for DMs or non-forum groups)
LIVE_TRADING=false              # Keep false until you are ready to go live
```

### How to create a Telegram bot

1. Open Telegram, search for **@BotFather**, and start a chat.
2. Send `/newbot`, choose a name (e.g. "MyIBKRBot"), and copy the token it gives you.
3. Add the bot to your group and send any message in the target topic/thread, then visit
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
4. Find `"chat":{"id":...}` in the response — that negative number is your `TELEGRAM_CHAT_ID`.
5. If using a forum-type supergroup with topics, find `"message_thread_id":...` in the same
   response — that number is your `TELEGRAM_THREAD_ID`. Leave it unset for DMs or plain groups.

---

## 4. Configure IBKR connection (TWS / IB Gateway)

### Enable the API in TWS or IB Gateway

1. Open TWS or IB Gateway and log in to your **paper** account.
2. Go to **Edit → Global Configuration → API → Settings** (TWS) or
   **Configure → API → Settings** (IB Gateway).
3. Check **"Enable ActiveX and Socket Clients"**.
4. Set **Socket port** to `7497` (paper TWS) — this matches the default in `config/settings.yaml`.
5. Uncheck **"Read-Only API"** so the system can place orders.
6. Click **OK** and restart TWS/Gateway if prompted.

### Verify the connection

Start TWS/Gateway, then run:

```bash
python -m scripts.healthcheck
```

You should see your account number, net liquidation value, and open positions printed to the
terminal. If you see a connection error, double-check the port and that the API is enabled.

---

## 5. Configure your universe and risk limits

These files control which stocks the system watches and how aggressively it trades. Open them in a
text editor:

### `config/universe.yaml`

Add the tickers you want the system to scan for covered calls and cash-secured puts.
The `would_own` list is the set of stocks you are genuinely happy to be assigned (i.e. own at the
strike price if the put is exercised). The `indexes:` list is scanned for CC opportunities; CSPs
are only generated for symbols that also appear in `would_own`.

**Adding a new ticker:** After adding a symbol to `universe.yaml`, run the IV backfill to seed
one year of IV history for it — otherwise IV Rank will be unavailable and the IV score will be
suppressed:
```bash
python -m scripts.backfill_iv
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
| `portfolio.max_new_positions_per_run` | 10 | Max new positions a single morning scan may propose. New live users should start at 1–3. |
| `covered_call.delta_min` / `delta_max` | 0.20 / 0.35 | Delta range for covered-call strikes |
| `covered_call.min_strike_vs_basis` | 1.00 | Reject CC if strike is below cost basis (prevents locking in a loss on the shares) |
| `cash_secured_put.delta_min` / `delta_max` | 0.15 / 0.30 | Delta range for cash-secured-put strikes |
| `cash_secured_put.max_contracts` | 10 | Hard cap on contracts per single CSP candidate |
| `<strategy>.dte_min` / `dte_max` | 21 / 45 | Days-to-expiry range for new positions |
| `events.earnings_blackout_days` | 14 | Reject candidates that live through / open within N days of earnings |
| `income.min_roc_pct` | 1.0 | Minimum return-on-collateral (%) to consider a trade |
| `income.min_annualized_yield_pct` | 12.0 | Minimum annualized yield to surface a candidate. In low-IV environments this filter is the most common reason zero candidates are returned; lower to 8–10% if needed. |
| `liquidity.min_option_volume` | 10 | Minimum daily option volume. Consider increasing to 50 for multi-contract positions. |
| `iv.min_iv_rank` | 30 | Only sell premium when IV rank is at least this (when known) |
| `live_execution.min_live_premium_ratio` | 0.80 | Send-time floor: reject a fill if the live mid drops below this fraction of the approved premium (IV-crush guard). 0 disables. |
| `live_execution.require_ibkr_greeks_when_live` | true | In LIVE mode, the delta re-gate requires IBKR-sourced greeks (never the paper yfinance fallback). |

> Note: `portfolio.max_correlated_exposure_pct` is present but **not enforced** (needs a correlation
> engine — see `STATUS.md`). The per-ticker and per-sector caps are the active concentration gates.

The AUTOMATED-mode circuit breakers live in `config/settings.yaml → automation`:

| Setting (YAML path) | Default | What it means |
|---|---|---|
| `automation.max_auto_trades_per_day` | 10 | Max new-exposure entry orders opened per ET trading day (auto or manual). 0 disables. |
| `automation.daily_loss_halt_pct` | 5.0 | Auto-engage the `/halt` kill switch when today's net realized loss exceeds this % of net liquidation. 0 disables. |

### `config/scoring_weights.yaml`

Controls how much weight each factor gets when ranking candidates (IV rank, technicals,
fundamentals, liquidity, assignment risk). You can leave these at the defaults to start.

---

## 6. Set up the daemons

Two processes must stay running during market hours:

| Daemon | Client IDs | What it does |
|---|---|---|
| Approval service | 14 (exec) + 15 (scan) | Telegram bot, order execution, interactive commands |
| Intraday monitor | 12 | Watches open positions for roll alerts |

### Option A — single launcher (recommended)

`scripts/start.py` starts **both** daemons together and auto-restarts either if it crashes:

```bash
python -m scripts.start
```

Logs are written to `logs/approval.log` and `logs/monitor.log`. Stop with Ctrl-C.
Flags: `--no-monitor` to skip the monitor, `--no-approval` to skip the approval service.

> **Note:** The cron jobs (morning scan, EOD report) are NOT started by this launcher — they
> must be scheduled separately (§7).

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
| `/scan` | Triggers a full pipeline scan — same as the morning cron. The initial reply becomes a live progress message (Account → Market data → Scoring → Claude review → Sending results) that updates as each stage completes; final trade candidates arrive as ✅ Approve / ❌ Reject messages (MANUAL) or are auto-queued (AUTOMATED). |
| `/mode` | Shows the current trading mode (👤 MANUAL or 🤖 AUTOMATED) with a toggle button. AUTOMATED mode executes trades without approval and auto-closes positions at 50% profit. A confirmation prompt appears before enabling AUTO. |
| `/halt` | 🛑 **Kill switch.** Immediately stops all order queuing/transmission (profit-take *closes* still run — closing risk is always allowed). The halt is saved, so it persists across restarts until you `/resume`. You can add a reason, e.g. `/halt market looks ugly`. Also auto-engages on a daily realized-loss breach. |
| `/resume` | Releases the kill switch; QUEUED orders resume on the next poll cycle. |
| `/status` | Compact overview: account totals, all active short options sorted by days-to-expiry, and pending approval / open order counts. Shows a 🛑 HALTED banner when the kill switch is engaged. Good morning check. |
| `/positions` | Live snapshot of all open positions (stocks and options), with market value and unrealized P&L per position. |
| `/account` | Account balances: net liquidation, total cash, buying power, maintenance margin, excess liquidity. |
| `/pending` | Lists all pending approvals by score and time-to-expiry. Useful if you want to review what's waiting before deciding. |
| `/fills` | Shows the last 7 days of executed fills: symbol, strike, quantity, fill price, and credit received. |
| `/expire` | Expires all pending approvals without executing any of them. Use when you decide not to trade for the day. |
| `/health` | Connection status for both IBKR links, database reachability, time since last scan, and counts of pending approvals and open orders. Use this to confirm the service is healthy before the morning scan. |
| `/help` | Lists all available commands. |

Trade approval messages include Claude's full reasoning: why the trade is attractive, key risks, tradeoffs, assignment considerations, rolling considerations, and confidence level — all embedded in the message before the ✅ Approve / ❌ Reject buttons.

---

## 7. Set up the daily cron jobs

Two jobs need to fire on a market-hours schedule: the morning scan (9:45 AM ET Mon–Fri) and the
EOD report (4:15 PM ET Mon–Fri). Choose the instructions for your operating system below.

> **What these jobs do:** `run_morning` connects to IBKR, runs the full scanning pipeline, and
> sends Approve/Reject messages to Telegram. `run_eod` fetches positions and P&L and sends an
> end-of-day summary to Telegram. Both are short-lived (they exit when done); the always-on
> daemons (`scripts.start`) are separate and must already be running.

> **Morning scan is optional (SYSTEM_REVIEW F5):** the always-on daemon already runs a full scan
> every 15 minutes during RTH, so `run_morning` is largely redundant. If you run both, that's safe —
> a cross-process **scan lease** now serialises scans so the cron and the daemon loop can't compete
> for the ~100 market-data line cap. You can omit the `run_morning` line entirely if you prefer to
> rely solely on the daemon loop. The `run_eod` job is still needed (the daemon doesn't run EOD).

---

### macOS / Linux — crontab

Open the crontab editor:

```bash
crontab -e
```

Paste the following (replace `/path/to/IBKR Investments` with the real absolute path):

```
TZ=America/New_York
# Morning scan — 9:45 AM ET Monday-Friday
45 9 * * 1-5 cd "/path/to/IBKR Investments" && .venv/bin/python -m scripts.run_morning >> logs/morning.log 2>&1

# EOD report — 4:15 PM ET Monday-Friday
15 16 * * 1-5 cd "/path/to/IBKR Investments" && .venv/bin/python -m scripts.run_eod >> logs/eod.log 2>&1
```

> **Timezone note:** The `TZ=America/New_York` line at the top of the crontab sets Eastern Time
> for all jobs in the file, regardless of the system timezone. Without it, a UTC server running
> `45 9 * * 1-5` fires at 9:45 UTC = 5:45 AM ET — too early.

Save and exit. Verify cron registered the jobs:

```bash
crontab -l
```

**Tip (macOS):** macOS requires Full Disk Access for `cron` if the project is under `~/Desktop` or
`~/Documents`. Go to **System Settings → Privacy & Security → Full Disk Access** and add
`/usr/sbin/cron`.

---

### macOS — auto-start daemons on login with launchd

`crontab` only schedules the two short-lived scans. The always-on daemons (`scripts.start`) need
to restart automatically if the machine reboots. The macOS-native way is a launchd plist.

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

Windows does not have cron. Use **Task Scheduler** (`taskschd.msc`) instead.

#### Option A — command line (fastest)

Open PowerShell **as Administrator** and run these four commands. Replace `C:\path\to\IBKR Investments` with your real path.

```powershell
# Morning scan — 9:45 AM ET Mon-Fri
$action = New-ScheduledTaskAction `
  -Execute "C:\path\to\IBKR Investments\.venv\Scripts\python.exe" `
  -Argument "-m scripts.run_morning" `
  -WorkingDirectory "C:\path\to\IBKR Investments"
$trigger = New-ScheduledTaskTrigger -Weekly `
  -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
  -At "09:45AM"
Register-ScheduledTask -TaskName "IBKR Morning Scan" `
  -Action $action -Trigger $trigger `
  -RunLevel Highest -Force

# EOD report — 4:15 PM ET Mon-Fri
$action2 = New-ScheduledTaskAction `
  -Execute "C:\path\to\IBKR Investments\.venv\Scripts\python.exe" `
  -Argument "-m scripts.run_eod" `
  -WorkingDirectory "C:\path\to\IBKR Investments"
$trigger2 = New-ScheduledTaskTrigger -Weekly `
  -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday `
  -At "04:15PM"
Register-ScheduledTask -TaskName "IBKR EOD Report" `
  -Action $action2 -Trigger $trigger2 `
  -RunLevel Highest -Force
```

> **Timezone:** Task Scheduler always uses the system clock. Set Windows timezone to Eastern Time
> (**Settings → Time & Language → Date & Time → Time zone → Eastern Time (US & Canada)**) and the
> times above are correct. If you are in a different timezone, convert ET to local time manually.

Verify the tasks were created:
```powershell
Get-ScheduledTask -TaskName "IBKR Morning Scan"
Get-ScheduledTask -TaskName "IBKR EOD Report"
```

#### Option B — Task Scheduler GUI

1. Open **Task Scheduler** (search the Start menu for `taskschd.msc`).
2. In the right panel click **Create Basic Task…**
3. Name: `IBKR Morning Scan` → Next
4. Trigger: **Weekly** → Next → set time `9:45 AM`, tick Mon/Tue/Wed/Thu/Fri → Next
5. Action: **Start a program** → Next
   - Program: `C:\path\to\IBKR Investments\.venv\Scripts\python.exe`
   - Arguments: `-m scripts.run_morning`
   - Start in: `C:\path\to\IBKR Investments`
6. Finish → tick **Open the Properties dialog** → **Run with highest privileges** → OK.
7. Repeat for the EOD report (name `IBKR EOD Report`, time `4:15 PM`).

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

For a Linux server, systemd is more reliable than cron for the always-on daemons, and cron handles
the two timed jobs.

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

**Cron jobs** — add as above using `crontab -e`:

```
TZ=America/New_York
45 9  * * 1-5 cd "/path/to/IBKR Investments" && .venv/bin/python -m scripts.run_morning >> logs/morning.log 2>&1
15 16 * * 1-5 cd "/path/to/IBKR Investments" && .venv/bin/python -m scripts.run_eod    >> logs/eod.log    2>&1
```

---

## 8. Backfill IV history (one-time)

IV Rank requires at least 30 days of historical implied-volatility data. Run this once on setup:

```bash
python -m scripts.backfill_iv
```

This fetches one year of historical IV for every symbol in your universe. It takes a few minutes.
After the bootstrap, the **EOD run appends one fresh IV observation per symbol each day** (N4), so
the IV-rank window stays current without re-running the backfill. `/health` shows an "IV history"
line and warns if any symbol's latest observation is older than 5 days (i.e. the EOD appender or
backfill has stopped) — re-run `python -m scripts.backfill_iv` to recover.

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

The scan pipeline requires option Greeks (`delta`, `iv`, `modelGreeks`) to score and filter
candidates. These come from IBKR's live market data feed — **delayed data (15-min) does not include
Greeks**, so running the scan without a subscription will produce zero CC/CSP candidates even though
the scan completes without errors.

### Paper trading

Your IBKR paper account **inherits subscriptions from a linked live account**. This means:

- If you have a live IBKR account with US Options data subscriptions → paper trading works fully
  with real Greeks.
- If you have no live account or no subscription → option quotes return `delta=None` and all
  CC/CSP candidates are filtered out. The scan runs, completes, and sends nothing.

To check your current subscriptions: TWS → Account Management → Market Data Subscriptions.

### Going live — required subscription

Before going live, subscribe to the **US Equity and Options Add-On Streaming Bundle** via
IBKR Account Management (search for "US Equity and Options"). This provides:

- Real-time US stock + option streaming quotes via the API
- `modelGreeks` (delta, gamma, theta, vega, IV) needed for candidate scoring

The bundle costs ~$4.50/month and is **fully rebated** if you pay ≥$5 in commissions that month
(which any single trade will exceed). Activate in TWS → Account Management → Market Data
Subscriptions.

> `config/settings.yaml → ibkr.market_data_type: 1` (live) is the correct setting for both paper
> (with subscriptions) and live. Do not change it to `3` (delayed) — delayed data has no Greeks and
> the scan will produce no candidates.

## 12. Going live

**Do not rush this step.** The system must have run successfully in paper mode for several weeks
before switching to live, and you must have active market data subscriptions (see Step 11).

When you are ready:

1. Confirm you have the US Equity and Options Add-On Streaming Bundle active on your live account
   and that paper scans are producing real CC/CSP candidates with valid delta values.
2. Verify at least 10–20 successful paper trades have filled and confirmed back to Telegram.
3. Open `.env` and change `LIVE_TRADING=false` to `LIVE_TRADING=true`.
4. In `config/settings.yaml`, confirm `ibkr.live_port` matches the port your live TWS uses (default: 7496).
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

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ConnectionRefusedError` on healthcheck | TWS/Gateway not running or API not enabled | Start TWS and check API settings (Step 4) |
| `clientId already in use` | Another process using the same IBKR client ID | Check `config/settings.yaml` for the `client_ids` map; each process needs a unique ID |
| No Telegram messages | Wrong `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, or `TELEGRAM_THREAD_ID` | Re-check `.env`; confirm values by visiting `https://api.telegram.org/bot<YOUR_TOKEN>/getMe` (validates the token) and re-running steps 3–5 for the chat/thread IDs. With the approval service running, send `/health` to confirm round-trip messaging. |
| Messages arrive in wrong topic | `TELEGRAM_THREAD_ID` missing or incorrect | Re-check the `message_thread_id` from `getUpdates` for a message sent in the correct topic. |
| Approval button presses do nothing | Approval service not running | Start `python -m scripts.run_approval_service` |
| Zero candidates every scan | Liquidity gates too strict, or no positions/universe configured | Check `config/risk_limits.yaml` thresholds and `config/universe.yaml` |
| `/scan` progress message shows "Scan failed" with a ❌ stage | A critical stage (account fetch or scoring) threw an unexpected exception | Check the approval service logs for the full traceback; restart TWS/Gateway if the account stage fails |
| `/scan` progress freezes on one symbol (e.g. "32/46 — SOFI") and never advances | That symbol's option-chain fetch hung waiting on an IBKR response that never arrived (pacing violation, error 10197 competing-session lockout, or a stuck `qualifyContractsAsync`) | Wait up to `market_data.symbol_timeout_seconds` (default 90s) — the scan logs `option chain for SOFI exceeded symbol_timeout_seconds=... — skipping this symbol` and continues with the remaining symbols. If it still never recovers, the process itself has hung; restart it. |
| `/scan` progress reaches "Sending results" but nothing arrives | The follow-up message threw an unhandled exception (e.g. malformed MarkdownV2) | Check `logs/approval.log` for `telegram.error.BadRequest` around the scan's completion time; the scan itself likely succeeded — check `scan complete — run_id=... CC=... CSP=... buy=...` in the same log |
| IBKR daemons stop reconnecting after a TWS/Gateway restart (`reconnect failed after 20 attempts — giving up`) | TWS/Gateway's nightly restart (~midnight ET) outlasted the 20-attempt reconnect window | Restart TWS/Gateway, then restart `python -m scripts.start` (or just the affected daemon) — the reconnect loop only runs once per process lifetime |
| IBKR errors 354 / 10091 flood the log during `/scan` and zero CC/CSP candidates are generated | No active US Options data subscription — delayed data has no Greeks, so every option is skipped at the delta filter | Subscribe to the **US Equity and Options Add-On Streaming Bundle** via TWS → Account Management → Market Data Subscriptions (see Step 11). Paper accounts inherit subscriptions from a linked live account. |
| IBKR error 10197 "No market data during competing live session" | A live TWS session is open at the same time as the paper session | Close the live TWS window while running the paper bot, or ensure each session uses a distinct clientId and market data subscription. |
| IBKR error 300 "Can't find EId with tickerId" floods the log | Benign cleanup: ib_async tries to cancel a market data subscription that already timed out | Safe to ignore — these fire after each option chain batch and do not affect scan results. |
| "Unknown contract" warnings for half-dollar strikes (e.g. JPM 292.5) | IBKR doesn't list those non-standard strikes for that expiry | Normal — the strike grid for some underlyings uses $5 or $10 increments; half-dollar strikes are skipped automatically. |
| `claude: command not found` | Claude Code CLI not installed or not on PATH | Run `claude --version`; install if missing |
| `RuntimeError: There is no current event loop` or `socket.socketpair()` crash on healthcheck | Windows + Python 3.14: `ProactorEventLoop` fails on startup | Fixed automatically in `connection.py` (switches to `WindowsSelectorEventLoopPolicy`). If you still see it, ensure you are running the installed version and not an older cached `.pyc`. |
