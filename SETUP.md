# Setup Guide

Everything you need to get the system running, from a fresh machine to your first approved trade.

---

## 1. Prerequisites

Before you start, make sure you have:

- **Interactive Brokers account** with Trader Workstation (TWS) or IB Gateway installed.
  Download from [ibkr.com](https://www.interactivebrokers.com/en/trading/tws.php).
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
# .venv\Scripts\activate           # Windows

# Install all dependencies
pip install -e ".[dev]"
```

To also enable the Streamlit dashboard:

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
TELEGRAM_CHAT_ID=987654321      # Your personal chat ID (see step 4)
LIVE_TRADING=false              # Keep false until you are ready to go live
```

### How to create a Telegram bot

1. Open Telegram, search for **@BotFather**, and start a chat.
2. Send `/newbot`, choose a name (e.g. "MyIBKRBot"), and copy the token it gives you.
3. Send any message to your new bot, then visit
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser.
4. Find `"chat":{"id":...}` in the response — that number is your `TELEGRAM_CHAT_ID`.

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
strike price if the put is exercised).

### `config/risk_limits.yaml`

Conservative defaults are pre-configured. Key settings to review:

| Setting | Default | What it means |
|---|---|---|
| `max_position_pct` | 5% | Max % of portfolio in one ticker |
| `delta_min` / `delta_max` (CC) | 0.20 / 0.35 | Delta range for covered-call strikes |
| `delta_min` / `delta_max` (CSP) | 0.15 / 0.30 | Delta range for cash-secured-put strikes |
| `min_dte` / `max_dte` | 14 / 45 | Days-to-expiry range for new positions |
| `earnings_blackout_days` | 14 | Reject candidates expiring within N days of earnings |
| `min_roc` | 1.0% | Minimum return-on-collateral to consider a trade |

### `config/scoring_weights.yaml`

Controls how much weight each factor gets when ranking candidates (IV rank, technicals,
fundamentals, liquidity, assignment risk). You can leave these at the defaults to start.

---

## 6. Set up the approval service (background daemon)

The approval service is a long-running process that:
- Listens for Telegram button presses (Approve / Reject)
- Holds the execution connection to IBKR (clientId 14) and a market-data connection (clientId 15)
- Places orders for approved candidates
- Responds to interactive commands sent from your Telegram chat

Start it in a terminal window or as a background service:

```bash
python -m scripts.run_approval_service
```

Keep this running at all times during market hours. On macOS you can use `launchd`; on Linux use
`systemd` or `screen`/`tmux`.

### Using the Telegram bot

Once the approval service is running, you can interact with the system from your phone at any time:

| Command | What you get |
|---|---|
| `/scan` | Triggers a full pipeline scan — same as the morning cron. Results arrive as Approve/Reject messages with Claude's full reasoning. |
| `/positions` | Live snapshot of all open positions (stocks and options), with market value and unrealized P&L per position. |
| `/account` | Account balances: net liquidation, total cash, buying power, maintenance margin, excess liquidity. |
| `/health` | Connection status for both IBKR links, database reachability, time since last scan, and counts of pending approvals and open orders. Use this to confirm the service is healthy before the morning scan. |
| `/status` | Compact overview: account totals, all active short options sorted by days-to-expiry, and pending approval / open order counts. Good morning check. |
| `/help` | Lists all available commands. |

Trade approval messages include Claude's full reasoning: why the trade is attractive, key risks, tradeoffs, assignment considerations, rolling considerations, and confidence level — all embedded in the message before the Approve / Reject buttons.

---

## 7. Set up the intraday monitor

The intraday monitor watches your open positions for roll alerts during market hours:

```bash
python -m scripts.run_monitor
```

Run this in a separate terminal window. It will alert you via Telegram if delta drifts too far,
IV spikes, DTE drops below the threshold, or an ex-dividend date approaches.

---

## 8. Set up the daily cron jobs

The morning scan and EOD report run on a schedule. Add these to your crontab with `crontab -e`
(times are in ET, adjust for your timezone):

```
# Morning scan — 9:45 AM ET Monday-Friday
45 9 * * 1-5 cd /path/to/IBKR\ Investments && .venv/bin/python -m scripts.run_morning >> logs/morning.log 2>&1

# EOD report — 4:15 PM ET Monday-Friday
15 16 * * 1-5 cd /path/to/IBKR\ Investments && .venv/bin/python -m scripts.run_eod >> logs/eod.log 2>&1
```

Replace `/path/to/IBKR\ Investments` with the actual absolute path to your project folder.

---

## 9. Backfill IV history (one-time)

IV Rank requires at least 30 days of historical implied-volatility data. Run this once on setup:

```bash
python -m scripts.backfill_iv
```

This fetches one year of historical IV for every symbol in your universe. It takes a few minutes.
Future scans will update the history incrementally.

---

## 10. Run the test suite

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

## 11. Start the Streamlit dashboard (optional)

The dashboard gives you a read-only view of your portfolio, open candidates, IV conditions, and
trade history:

```bash
streamlit run dashboard/app.py
```

Open `http://localhost:8501` in your browser. The dashboard reads from the SQLite database
(`data/income_system.db`) and does not connect to IBKR.

---

## 12. Going live

**Do not rush this step.** The system must have run successfully in paper mode for several weeks
before switching to live.

When you are ready:

1. Verify at least 10–20 successful paper trades have filled and confirmed back to Telegram.
2. Open `.env` and change `LIVE_TRADING=false` to `LIVE_TRADING=true`.
3. In `config/settings.yaml`, confirm `ibkr.live_port` matches the port your live TWS uses (default: 7496).
4. Restart all processes (approval service, monitor, cron).
5. The system will print a **prominent banner** on startup confirming it is in LIVE mode and
   which account it is connected to. Verify this before approving any trade.
6. Start with a single small position to validate the full end-to-end flow.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `ConnectionRefusedError` on healthcheck | TWS/Gateway not running or API not enabled | Start TWS and check API settings (Step 4) |
| `clientId already in use` | Another process using the same IBKR client ID | Check `config/settings.yaml` for the `client_ids` map; each process needs a unique ID |
| No Telegram messages | Wrong `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` | Re-check `.env`; test with `python -c "from src.notify.sender import send_message; import asyncio; asyncio.run(send_message('test'))"` |
| Approval button presses do nothing | Approval service not running | Start `python -m scripts.run_approval_service` |
| Zero candidates every scan | Liquidity gates too strict, or no positions/universe configured | Check `config/risk_limits.yaml` thresholds and `config/universe.yaml` |
| `claude: command not found` | Claude Code CLI not installed or not on PATH | Run `claude --version`; install if missing |
