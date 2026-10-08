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

## 2b. Create your own config files

The repo ships **templates** — `config/settings.example.yaml`, `risk_limits.example.yaml`,
`scoring_weights.example.yaml`, `universe.example.yaml` and `spreads.example.yaml` (the daily
credit-spread system, off by default). Your own copies (the files without `.example`) are
**git-ignored**, so your account IDs, limits, weights and universe never reach GitHub:

```bash
for f in settings risk_limits scoring_weights universe spreads; do
  cp config/$f.example.yaml config/$f.yaml
done
```

Edit `config/settings.yaml` and friends from then on. If one of your files is missing, the system
falls back to the example and logs a warning, so a fresh clone still runs. **When you pull an
update that adds new config keys**, the code defaults cover them; diff your file against the
example (`diff config/settings.yaml config/settings.example.yaml`) to adopt any new setting
explicitly. The test suite always reads the examples (`IBKR_CONFIG_USE_EXAMPLES=1`, set in
`tests/conftest.py`), never your copies. The other files in `config/` (`research*.yaml`,
`symbol_directory_overrides.yaml`, `universe_archive.yaml`) are shared reference data and stay
committed.

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
TELEGRAM_THREAD_SPREADS=4308 # Daily credit-spread system (src/spreads/)

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
   `TELEGRAM_THREAD_ACCOUNT`, and `TELEGRAM_THREAD_SPREADS` for the optional daily credit-spread
   system). Leave a variable unset for DMs or plain (non-forum) groups.

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
   and unzip it to `~/Applications/ibc`, then make its scripts executable — the zip drops the
   execute bit, and `start_gateway.sh` refuses to launch ("IBC not found") without it:
   `chmod u+x ~/Applications/ibc/*.sh ~/Applications/ibc/scripts/*.sh`.
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

**Auto-start with launchd:** `./ibkr install --with-gateway` (see §6c "Run it as a background
service (launchd)") writes and loads the `com.ibkr.gateway` `LaunchAgent` for you —
`RunAtLoad`, `KeepAlive: false` (IBC owns Gateway's own restart cycle, including the daily
restart the "One-time GUI step" above configures, so launchd shouldn't fight it by relaunching
the wrapper script itself). There's exactly one way to install this agent; don't hand-write a
plist for it. `--with-gateway` installs it *alongside* `com.ibkr.supervisor` (the Python
daemons) in the same command — the daemons' own `connect_with_retry` backoff already tolerates
Gateway not being up yet at boot, so which one launchd starts first doesn't matter. To add
`com.ibkr.gateway` to an already-installed stack, re-run `./ibkr install --with-gateway`; to
remove it, `./ibkr uninstall` and re-`install` without the flag.

The agent runs `start_gateway.sh` as a child of the repo's `.venv/bin/python` rather than
exec'ing it directly. macOS privacy protection (TCC) refuses launchd's `/bin/bash` access to
anything under `~/Desktop` (`logs/launchd-gateway.log`: `Operation not permitted`, exit 126),
while the venv python already holds that grant — the supervisor agent depends on it too.

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
(`backfill_iv --symbols NEWTICKER` backfills just the new symbol instead of the whole universe,
if you'd rather not re-run the full set.) Also add the symbol to the `sectors:` map so
concentration limits work correctly. For an
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
| `portfolio.max_large_positions` | 2 | Job 3 (deliberateness). How many concurrent positions may exceed `max_collateral_per_ticker_pct` via a large-position slot (raised 1 → 2 on 2026-09-23). Measured on **cumulative** per-ticker collateral — what the account already holds in the name plus the new lot — so a name already at the cap can't quietly take another. Each slot is still individually bounded by `max_pct_per_ticker_large`, so two slots means up to 50% of net liq combined across both names, not a change to either one's own ceiling. |
| `portfolio.max_pct_per_ticker_large` | 25.0 | Job 3. Hard ceiling for a large-slot position, **cumulative** raw collateral in one ticker as % of net liq. This is also the backstop on the paths that can't seed the risk-unit tallies from live IV (the order-approval re-gate, the single-ticker deep-dive, the CSP sizer): whatever those paths know about a candidate's IV, one name can never exceed this in raw collateral. |
| `portfolio.max_new_positions_per_run` | 10 | Max new positions a single scan may propose. New live users should start at 1–3. |
| `covered_call.delta_min` / `delta_max` | 0.20 / 0.35 | Delta range for covered-call strikes |
| `covered_call.min_strike_vs_basis` | 1.00 | Reject CC if strike is below cost basis (prevents locking in a loss on the shares) |
| `cash_secured_put.delta_min` / `delta_max` | 0.20 / 0.35 | Delta range for cash-secured-put strikes (widened 2026-09-23 from 0.15/0.30 — now the same band as covered calls, for more premium at the cost of a higher assignment rate) |
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
| `ideal_zone.em_lo_mult_call` / `em_lo_mult_put` / `em_hi_mult` | 0.30 / 0.18 / 1.20 | Where the ideal strike band sits, in expected moves (1σ = spot × IV × √(DTE/365)). Both CC and CSP screen 0.20–0.35Δ, but puts and calls do NOT map to the same sigma distance at equal delta, so the **inner-edge floor** is split per right: a 0.20–0.35Δ call sits at ~0.48–1.17σ (`em_lo_mult_call: 0.30` covers it with margin), while a 0.20–0.35Δ put can run as close as ~0.21σ on a high-vol/long-DTE name at the 0.35-delta end (`em_lo_mult_put: 0.18` covers it with ~0.03σ margin). A single shared floor can't satisfy both — low enough for the widened put range also drags the CALL inner edge close enough to spot to let a ~0.46-delta covered call read "in zone" (`tests/test_output_fidelity.py::test_ideal_call_band_never_endorses_an_at_the_money_write`). `em_hi_mult` (the outer edge) stays shared — 1.20 brackets both rights' outer bound with margin. After the band snaps to a level, its inner edge is clamped back to the right's own floor, so it can never slide to at-the-money. |
| `ideal_zone.support_pull_pct` | 3.0 | How close a support/resistance level must be (% of the band edge) for the band to snap to it. The snap moves the **outer** edge onto the level; the inner edge stays clamped at the right's own `em_lo_mult_call`/`em_lo_mult_put`, so the band stretches rather than sliding toward spot. |
| `ideal_zone.earnings_widen_mult` | 0.25 | Extra cushion, in expected moves, when earnings fall inside the option's life |
| `ideal_zone.min_credit_edge_pct` | 10.0 | **Feeds the primary income gate.** Premium demanded over Black-Scholes fair value priced at *realised* vol (HV30). The floor is priced at **that contract's own strike** (not the band's anchor) and is never below the `income.min_roc_pct` / `min_annualized_yield_pct` noise floors, so "clears fair value" means the credit beats all three. When `income.require_vrp_edge` is true (default), a candidate whose premium falls below this floor is rejected with `premium_below_fair_value` — raise to insist on a richer entry, at the cost of fewer candidates. |
| `ideal_zone.buy_margin_of_safety_pct` | 8.0 | Discount applied to the analyst mean target when placing the "buy shares below" level |

The auto-close circuit breakers live in `config/settings.yaml → automation`:

| Setting (YAML path) | Default | What it means |
|---|---|---|
| `automation.max_auto_trades_per_day` | 10 | Max new-exposure entry orders opened per ET trading day (auto or manual). 0 disables. |
| `automation.daily_loss_halt_pct` | 3.0 | Auto-engage the `/halt` kill switch when today's **mark-to-market** loss exceeds this % of net liquidation — measured from the prior EOD position snapshot's summed `unrealized_pnl`, not fill cashflow (D3: a day the system sells premium into a real drawdown always shows a positive *cashflow*, so the old cashflow-based measure never caught it). 0 disables. |
| `automation.drawdown_halt_pct` | 10.0 | Auto-engage the `/halt` kill switch when net liquidation falls this % below its trailing high-water mark (`system_settings.get_high_water_mark`). Catches a slow bleed that no single day's loss trips. 0 disables. |
| `automation.max_loss_multiple` | 2.0 | The loss line: cost-to-close reaching this multiple of the entry credit. Shorts on `leveraged_etfs` are bought back (checked every 15 minutes during the intraday loop); every other short gets a defensive roll proposal (Approve/Reject card) from the intraday monitor instead of a close. 0 disables both. |
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
- `missing_iv_rank_score` (default 50, Task 9) — the `iv_score` a candidate gets when it has no
  IV rank yet (a new/thin symbol with little `iv_history`), instead of scoring 0 under IV's 30%
  weight and silently missing `min_candidate_score`. Leave at 50 (neutral); set to 0 to go back to
  treating a data gap as the worst possible IV rank. Also read by `strategies/rolling.py` (fix
  round 1) for the roll card's `iv_score` line — display-only there, since rolls sort by
  `roc_pct` and never pass through `min_candidate_score`.

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

> **Normal operation on macOS: use `./ibkr`, not the commands below.** `./ibkr install` once, then
> `./ibkr start` / `./ibkr restart` / `./ibkr stop` / `./ibkr status` (§6c). The stack then runs as a
> background service with no terminal and no Ctrl-C — `./ibkr stop` is how you stop it.
> `python -m scripts.start` below is the foreground/debug way to run the same thing; don't run both.

### Option A — single launcher (foreground; `./ibkr` runs this for you in the background)

`scripts/start.py` is the one command that brings up every long-running Python service —
the approval service, the intraday monitor, the web API (§6a), and the research worker (§6a)
— together, auto-restarting any of them if it crashes:

```bash
python -m scripts.start
```

Logs are written to `logs/approval.log`, `logs/monitor.log`, `logs/api.log`, and
`logs/research.log`. Stop with Ctrl-C (only when run in a terminal; under `./ibkr`, use `./ibkr stop`).
Flags: `--no-monitor`, `--no-approval`, `--no-api`, `--no-research`, `--no-spreads`, each skipping one
service (`--no-eod` skips the built-in EOD scheduler — see §7).

> The web API and research worker need the `web` extra (`pip install -e ".[web,dev]"`, §6a)
> and `WEB_API_TOKEN`/`SEC_CONTACT_EMAIL` in `.env`. If you haven't set those up yet, pass
> `--no-api --no-research` — otherwise those two subprocesses just crash-loop (visible in
> `logs/api.log`/`logs/research.log`) while the IBKR daemons run fine. Not started here: the
> Next.js frontend (§6a "The web frontend") — that's a separate `npm run dev`, since it's a
> Node process, not a Python script.

> **Clean stop, guaranteed:** Ctrl-C/SIGTERM sends every daemon SIGTERM, waits up to 10s, then
> SIGKILLs anything still alive — a hung shutdown can no longer leave an orphaned survivor behind
> (2026-08-27: one did, kept polling Telegram for 30+ minutes, and fought the next restart over
> both the bot token and its clientIds). On startup, before launching anything, the launcher also
> scans for and kills any *other* process still running one of this project's own daemon modules
> — whatever the cause (a crash, a laptop sleep, a second `scripts.start` started by accident),
> a restart always starts from a clean slate.
> The sweep never touches its own parent/ancestors or any `caffeinate` process, so the
> launchd supervisor's `caffeinate -i -s` wrapper (§6c) survives it and keeps the Mac awake
> (fixed 2026-09-30 — before that, every launchd start killed its own caffeinate wrapper).

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

**macOS launchd:** don't hand-write a plist for one daemon — `./ibkr install` (see §6c "Run it
as a background service (launchd)" below) wraps the **whole** Option A stack (`scripts.start`,
so approval + monitor + API + research worker + the EOD scheduler together) plus the
out-of-process watchdog under launchd's `KeepAlive`, which is what this section is otherwise
hand-rolling piecemeal. Use that instead.

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

Both processes are started automatically by `python -m scripts.start` (§6) — that's the
normal way to run them. Run one standalone only when you want it up in isolation (e.g.
iterating on the API without the IBKR daemons):

```bash
python -m scripts.run_api
```

| Command | What it does |
|---|---|
| `python -m scripts.run_api` | Starts the web API on `config/research.yaml → api.host:port` (default `127.0.0.1:8787`). Requires `WEB_API_TOKEN` in `.env`. No IBKR connection. Included by default in `scripts.start` — opt out with `--no-api`. |
| `python -m scripts.run_research_worker` | Runs the research ingestion worker (APScheduler). Populates `data/research.db` from SEC EDGAR — the symbol directory first, then weekly refreshes; a nightly warm-tier refresh (daily bars + news for watchlisted/recently-viewed symbols, at `research.tiers.warm_refresh_hour_et`, default 04:00 ET); delayed intraday quotes every 15 min during RTH. Holds no IBKR connection, no clientId. Requires `SEC_CONTACT_EMAIL` in `.env`. Included by default in `scripts.start` — opt out with `--no-research`. |

Endpoints available now: `GET /health` (no auth), `GET /me`, `GET /nav`, and
`GET /research/search?q=<ticker>` (bearer token). See `docs/web/api.md` for the full
reference. The research worker populates the `symbols` table from SEC EDGAR so search has
something to search — on first start, give it a few moments (or run it once standalone) to
pull the symbol directory before search will return results.

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

## 6b. Out-of-process watchdog (optional but recommended)

`python -m scripts.watchdog` is a **one-shot health check**, deliberately meant to run outside
`scripts.start`'s supervised process tree — see `src/ops/watchdog.py`. The point: every other
alert path in this system (the monitor's triggers, the approval service's own heartbeat) lives
*inside* one of the processes `scripts.start` supervises, so if the whole stack (or the Mac it
runs on) stops, nothing is left running to say so. This script is designed to be scheduled
separately, by launchd or cron, so it keeps working when everything else has stopped.

It checks: the `scripts.start` supervisor process is alive, the configured IBKR port accepts a
connection, the command-drain and (during market hours) intraday-monitor heartbeats are fresh,
the intraday scan loop has completed recently during RTH, the EOD report finished today after its
scheduled time, and no universe/held symbol's IV history has gone stale. A failing check sends a
plain-text Telegram alert (re-sent every `watchdog.realert_minutes` while it stays failing, with a
"recovered" notice once it clears); it has no IBKR connection and no clientId, and writes only
`data/watchdog_state.json`.

Run it by hand once to confirm Telegram delivery works:

```bash
python -m scripts.watchdog
```

Then schedule it — every `watchdog.interval_seconds` (default 300 = 5 min) is a reasonable
cadence. On macOS, `./ibkr install` (§6c, right below) does this for you, alongside the
supervisor itself; there is exactly one supported way to schedule it on macOS — see §6c rather
than hand-writing a plist or a crontab line. On Linux/Windows (no launchd), a crontab line or
Task Scheduler entry running `python -m scripts.watchdog` every `watchdog.interval_seconds`
is still the way to go — see §7's Windows Task Scheduler recipe for the equivalent pattern.

**Known limitation:** none of this can detect the Mac itself being powered off or asleep — a
powered-off machine runs no launchd/cron job at all, so nothing alerts. If that matters to you,
sign up for a free dead-man-switch ping (e.g. [healthchecks.io](https://healthchecks.io)) and set
`watchdog.deadman_url` in `config/settings.yaml` to the ping URL — the watchdog GETs it on every
run where every check passes, and that external service is what notices the pings stopping and
emails/texts you.

---

## 6c. Run it as a background service (launchd)

`./ibkr` (repo root) is the single control script for everything in §6/§6a/§6b except
`npm run dev` (the Next.js frontend — a separate Node process). `install`/`uninstall`/`start`/
`stop`/`status` are a thin wrapper over `python -m scripts.launchd <cmd>` (run that directly if
you'd rather script against it than `./ibkr`); `logs`/`watchdog`/`autonomy` are handled by
`./ibkr` itself. Up to three launchd `LaunchAgent`s are involved (see `scripts/launchd.py`):

| Label | Runs | Restart policy |
|---|---|---|
| `com.ibkr.supervisor` | `caffeinate -i -s <venv-python> -m scripts.start` — the whole Option A stack (approval service, monitor, API, research worker, EOD scheduler) | `KeepAlive` — launchd restarts it if it ever exits, `ThrottleInterval` 30s |
| `com.ibkr.watchdog` | `<venv-python> -m scripts.watchdog` | `StartInterval` = `watchdog.interval_seconds` (default 300s) — a one-shot health check, entirely outside the supervisor's process tree (§6b) |
| `com.ibkr.gateway` (opt-in, `./ibkr install --with-gateway`) | `scripts/ibc/start_gateway.sh` (§4 "Automating Gateway login with IBC") | `RunAtLoad` only — IBC owns Gateway's own restart cycle, so launchd doesn't fight it |

**Seeing it running / stopping it:** `./ibkr status` (pid + health checks), `./ibkr logs approval`
(live tail), Telegram `/status`, or Activity Monitor → search `python` / `caffeinate`. Stop with
`./ibkr stop`. There is no terminal window and nothing to Ctrl-C.

**`caffeinate -i -s`** wraps the supervisor so the Mac won't idle- or system-sleep out from
under the trading stack while it's running on AC power (the same class of incident as the
2026-09-11 research-worker sleep freeze — see the troubleshooting table below). It does **not**
prevent a *closed-lid* sleep on battery — keep the Mac plugged in, or on a wired connection with
"Prevent automatic sleeping when the display is off" enabled, for unattended operation.

**Toggling `caffeinate`:** it is tied to the stack's lifetime, not a separate switch. While the
stack is up (`./ibkr start`) the Mac is kept awake; after `./ibkr stop` no caffeinate process
remains (check: `pmset -g assertions | grep -A2 caffeinate` — any entries left are other
programs'). To let the Mac sleep, stop the stack; a sleeping Mac freezes scans, the monitor and
the EOD report.

```bash
./ibkr install                 # writes + loads com.ibkr.supervisor and com.ibkr.watchdog
./ibkr install --with-gateway  # also installs com.ibkr.gateway
./ibkr status                  # state + pid per agent, then the watchdog's own health checks
./ibkr stop                    # unloads the supervisor (+ gateway if installed) — NOT the watchdog
./ibkr start                   # reloads/restarts the supervisor (+ gateway)
./ibkr restart                 # stop, then start (supervisor + gateway only)
./ibkr uninstall                # unloads and deletes every installed agent's plist, watchdog included
./ibkr logs approval             # tail logs/approval.log (also: monitor|api|research|eod|spreads|watchdog|supervisor)
./ibkr watchdog                  # run one watchdog health check right now (not through launchd)
./ibkr autonomy [level]         # show/set the autonomy rung (scripts/autonomy.py)
```

**Running paper on `full` (Task 12):** `config/settings.yaml → automation.paper_skip_promotion_gate`
(default `false` in code, shipped `true` in this repo's checked-in config) lets a **paper-mode**
process skip the autonomy ladder's fill-count evidence gate (>=20 fills, >=60% fill rate, >=1
risk-reducing close) so `./ibkr autonomy full` can succeed immediately, before that evidence
exists. At `full`, a candidate that passes the deterministic risk gate auto-queues and executes
with no approval tap — **remember `/halt` in Telegram**: it stops all new order
queuing/transmission immediately (closing risk still runs), and is the fastest way to intervene
if a scan cycle at `full` does something you don't like. `./ibkr logs approval` tails what the
approval/execution daemon is doing in real time.

**Before you ever set `LIVE_TRADING=true`, demote by hand: `./ibkr autonomy manual`.** A
promotion *request* on a live process always runs the real evidence check regardless of this
flag — but the stored rung itself lives in the same DB for paper and live, so a `full` reached
here on paper does not reset itself just because the mode flag changed. There is a backstop
(`approval_service` re-validates and demotes the stored rung to `manual` on every live startup
if the evidence doesn't hold — see `STATUS.md`'s Task 12 fix-round-1 entry), but it's exactly
that: a backstop, not the plan. It counts **live** fills/orders only (`is_live` must match the
running mode — paper fills never count as live evidence; fixed 2026-09-30, before which a paper
`full` run's own fills let `full` carry into live), and it only runs when `approval_service`
starts. See the "Live-cutover safety checklist" in §12 below.

**The watchdog stays loaded across `stop`/`start`/`restart`** (fixed 2026-09-30). Only
`install` loads `com.ibkr.watchdog` and only `uninstall` unloads it — a stopped stack is exactly
what the watchdog exists to alert on, so expect its `supervisor`/heartbeat alerts while you've
stopped the stack on purpose (`./ibkr uninstall` removes the watchdog too, if you want it silent). Before this
fix `./ibkr stop` unloaded the watchdog too, so a stopped stack never alerted.

`install` refuses to run over a terminal-launched `scripts.start` that's still alive —
two supervisors would fight over clientIds (`config/settings.yaml → ibkr.client_ids`). The
check (`python -m scripts.launchd preflight`) runs **every time**, whether or not the supervisor
label is already loaded: it lists every `scripts.start` process (`pgrep -f scripts.start`),
excludes the launchd-managed supervisor's own process tree (its pid from `launchctl print` plus
every descendant, walked via `ps -eo pid,ppid`), and refuses if anything is left over. Stop the
terminal session (Ctrl-C) first.

Every plist is built with Python's `plistlib` (`scripts.launchd.render_plists`) — no
hand-editing, no string templating of a repo path that contains a space (`~/Desktop/IBKR
Investments`). The interpreter used is the repo's own `.venv/bin/python` (left as the unresolved
symlink chain deliberately — resolving it changes `sys.prefix` away from the venv and drops
every third-party dependency off `sys.path`; launchd execs through the symlink itself at the OS
level, same as any `exec()`).

**`watchdog.deadman_url`** (`config/settings.yaml`) is worth setting once `./ibkr install` is
your normal way to run this: it's the only thing that notices the Mac itself being off or
asleep, since no watchdog cycle runs at all in that case — sign up for a free ping URL (e.g.
[healthchecks.io](https://healthchecks.io)) and the watchdog GETs it on every all-clear run.

**Known environment caveat (2026-09-29):** on at least one verification machine, the framework
build of Python that `python.org`'s macOS installer ships (the one `.venv/bin/python` resolves
through) hangs inside its own interpreter bootstrap (`getpath_readlines`, before any of this
project's code runs) specifically when spawned by the *real* system launchd — reproduced with a
bare `python -c "print(...)"` plist, no caffeinate, no reference to this repo at all, so it is
not something `./ibkr`/`scripts.launchd` can fix. The launchd control plane itself (install,
`KeepAlive` respawn, stop/start, the watchdog's alert/recovery cycle) is unaffected, since all of
that depends only on process *existence* (`pgrep -f scripts.start`), not on the process finishing
startup — but the daemons themselves never come up. If `./ibkr status` shows a stable pid that
never spawns approval/monitor/api/research children (check with `pgrep -fl scripts.run_`) and
`logs/launchd-supervisor.log` stays empty, this is almost certainly it. `./ibkr status`'s own
health checks say the same thing a different way: `supervisor` only proves the *process*
exists, so it reads OK even while wedged — but `command_drain`/`monitor`/`scan_loop` only turn
fresh once `approval_service` is actually running its loop, so those staying persistently
`[FAIL]` alongside a permanently-`[OK]` `supervisor` is exactly this wedge, not an unrelated
problem. The most likely fix:
grant Full Disk Access (System Settings → Privacy & Security → Full Disk Access) to
`/Library/Frameworks/Python.framework/Versions/3.12/Resources/Python.app` — the same class of
fix §7's cron tip below already documents for `~/Desktop`/`~/Documents` project locations.
Running the exact same command from an interactive Terminal session is unaffected either way.

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
- A run that hangs (e.g. an IBKR account-summary fetch stuck looping through a connectivity
  flap) is killed after `scheduler.eod_timeout_minutes` (default 60) rather than blocking every
  later EOD run forever — see the troubleshooting table below.

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
automatically if the machine reboots. The macOS-native way is a launchd plist — see **§6c "Run
it as a background service (launchd)"** above: `./ibkr install` writes and loads
`com.ibkr.supervisor` (`RunAtLoad` + `KeepAlive`, so it survives both a reboot and a crash — the
two layers of restart protection this section used to hand-write a plist for) alongside the
out-of-process watchdog, in one step.

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

This starts the approval service, intraday monitor, web API, and research worker at boot
(pass `--no-api`/`--no-research` in the `-Argument` string above to skip either). Task
Scheduler will not restart them if they crash mid-day — `scripts.start`'s built-in
supervisor handles that.

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

`backfill_iv` fetches one year of historical IV (via IBKR) for the trading universe unioned with
whatever is currently held (read from the latest `position_snapshots` row — the same holdings
union the EOD IV append uses). Pass `--symbols AMD,BAC` to backfill an explicit list instead
(e.g. right after adding a new ticker, or a symbol acquired outside the watchlist/would-own
lists); `--help` shows the full usage. `backfill_prices` fetches ~1y of daily OHLCV (via
yfinance) into `price_history`. Both take a few
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
3. **Run `./ibkr autonomy manual`.** If the paper account has been running at `whitelist`/`full`
   (Task 12's `paper_skip_promotion_gate`), demote it by hand before touching `.env` — the
   stored rung lives in the same DB for paper and live, so it does not reset itself just because
   `LIVE_TRADING` changes. (`approval_service` re-validates the stored rung and demotes it to
   `manual` automatically on every live startup if the fill evidence doesn't hold — see
   `STATUS.md`'s Task 12 fix-round-1 entry — but that is a backstop for a missed step, not a
   substitute for doing this deliberately.)
4. Open `.env` and change `LIVE_TRADING=false` to `LIVE_TRADING=true`.
5. In `config/settings.yaml`, confirm `ibkr.live_port` is `4001` (IB Gateway live default). If you are using TWS instead, set it to `7496`.
6. Restart all processes (approval service, monitor, cron).
7. The system will print a **prominent banner** on startup confirming it is in LIVE mode and
   which account it is connected to. Verify this before approving any trade.
8. Start with a single small position to validate the full end-to-end flow.

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
- [ ] **Paper-only promotion bypass off, and the rung demoted by hand (Task 12):**
      `settings.yaml → automation.paper_skip_promotion_gate` must be `false`. It ships `true` in
      this repo's checked-in config so the paper account can run `full` without first
      accumulating fill evidence — `promotion_blockers` ignores it (with a warning) whenever
      `LIVE_TRADING=true`, but that only ever gates a fresh promotion *request*. The stored rung
      itself lives in the same DB for paper and live, so also do step 3 above (`./ibkr autonomy
      manual`) — don't rely on `approval_service`'s live-startup re-check (Task 12 fix round 1)
      to catch a rung you forgot to demote; it's the backstop, not the plan.
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

**Ollama review quality** (Task 10, production-shaped since fix round 1 — replays stored
`candidates` rows through the local reviewer, with the real analytics/history/market-conditions a
live scan would send, to validate a `claude.ollama_model` swap or a prompt change before
committing to it in `config/settings.yaml`. **Not a pure read (fix round 2):** it never writes
`candidates`, approvals, orders, `claude_memory`, or the verdict ledger, but because it reuses
`scan.py`'s own `_fetch_analytics` to build the production-shaped prompt, it may populate the
shared `price_history` and `fundamentals_cache` caches — the same idempotent rows a live scan
writes when it runs analytics for these symbols; stubbing that out was considered and rejected,
since it would make the eval diverge from the real prompt again):

```bash
python -m scripts.review_eval --model qwen3.5:4b --runs 2
python -m scripts.review_eval --model qwen3.5:9b --ids <candidate_id> --runs 1
python -m scripts.review_eval --model qwen3:8b --since 2026-06-01 --limit 10

# Cold-load measurement (unload the model first; --timeout gives a generous client-side wait so
# a slow cold load isn't cut off before you can see how long it really took):
ollama stop qwen3.5:4b
python -m scripts.review_eval --model qwen3.5:4b --runs 1 --limit 10 --timeout 400
```

Prints, per run, the real `/api/generate` metadata (`prompt_eval_count`, `eval_count`,
`total_duration`/`load_duration` — needed to size `ollama_num_ctx`/`ollama_timeout_seconds`
against the actual prompt), how many *distinct* requested candidates came back reviewed (a model
returning a duplicate `candidate_id` while silently missing a different one is reported honestly,
not counted as full coverage), each review's verdict/evidence/confidence, then the aggregate
verdict distribution and the empty-`evidence` rate. Bypasses `ollama_runner`'s circuit breaker and
`claude.enabled` (builds the prompt and POSTs to `/api/generate` directly), so it works even while
the production circuit is open. See "Model choice" in §14 below for the Task 10 evaluation results
this produced.

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
against a local `qwen3.5:4b` model (Task 10, 2026-09-29 — see "Model choice" below). The verdict
learning loop (§13 — ledger, reconciliation, score-vs-outcome analysis) is unaffected since it
doesn't call Claude at all.

**1. Install Ollama and pull a model:**

```bash
brew install ollama
ollama serve &                       # or: brew services start ollama
ollama pull qwen3.5:4b               # ~3.4GB; the active model — see "Model choice" below.
```

**2. Choose a backend in `config/settings.yaml → claude`:**

```yaml
claude:
  backend: "ollama"           # "cli" | "ollama" (active here) | "cli_then_ollama"
  ollama_host: "http://localhost:11434"
  ollama_model: "qwen3.5:4b"
  ollama_timeout_seconds: 180
  ollama_num_ctx: 24576       # context window (tokens) — must cover prompt + JSON output
  ollama_keep_alive: "2m"     # unload quickly between calls — see "Model choice" below
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

**Model choice (Task 10, re-decided 2026-09-29; re-verified fix round 1, 2026-09-30).** The review
path is now **schema-constrained** (`ollama_runner._generate` sends Ollama's `format` as a JSON
Schema — `REVIEW_SCHEMA` — not the bare `format: "json"` string) and the prompt carries a
deterministic **FACTS** block (`F1`-`F7`: moneyness, breakeven cushion, earnings-vs-expiry timing,
fair-value edge, IV rank/RV, and — full-universe path only, see the fix-round-1 note below — a
gate-pass line) plus a **DECISION RUBRIC** that defaults to `"sell"` on a gate-passing candidate
unless a specific fact argues otherwise — see the `src/claude/` table in `ARCHITECTURE.md`. This
fixed the pre-Task-10 failure mode: 6/6 single-candidate reviews came back `"wait"` and a
3-candidate prompt reviewed only 1/3 candidates.

Initial evaluation (Task 10) used `scripts/review_eval.py` against real stored candidates (7 rows,
all META/AMZN CSPs) at 2 runs each, but built the prompt with no `analytics`/`market_conditions`/
`history` — understating the real prompt a scan sends. Fix round 1 corrected this:
`review_eval.py` now reuses `scan.py`'s own `_fetch_analytics`/`_load_memory` and
`get_market_conditions` (the exact functions the real scan calls, none needing an IBKR
connection), and the re-measurement below uses a 10-candidate batch — `risk_limits.yaml`'s
`portfolio.max_new_positions_per_run` ceiling, the largest a real scan sends:

| Model | Download | Reviewed | Verdicts | Empty evidence | Cold-start (first call) |
|---|---|---|---|---|---|
| `qwen3:8b` (was active) | 5.2 GB | 7/7 (warm run) | all `sell` | 0/7 | **timed out** (>120s) |
| **`qwen3.5:4b` (active now)** | **3.4 GB** | **14/14 (both runs)** | all `sell` | **0/14** | **80.7s — no timeout** |
| `qwen3.5:9b` | 6.6 GB | 7/7 (warm run) | 5 sell / 1 wait / 1 skip | 0/7 | timed out (>120s) |
| `gemma4:e4b-it-qat` | 6.1 GB | 14/14 (both runs) | all `sell` | 0/14 | 76.8s — no timeout |

(Table above: original 7-candidate, non-production-shaped run, kept for the download-size/model
comparison across four models. `qwen3:8b`/`qwen3.5:9b`/`gemma4:e4b-it-qat` were not re-run
production-shaped — the ruling that motivated fix round 1 only requires re-testing an alternative
if the active model *fails* the production-shaped re-check, and it didn't.)

**Fix-round-1 re-check, `qwen3.5:4b` only, production-shaped, 10-candidate batch (2026-09-30):**

| Run | Candidates reviewed | Verdicts | Empty evidence | `prompt_eval_count` | `eval_count` | Wall time |
|---|---|---|---|---|---|---|
| Warm | 10/10 | all `sell` | 0/10 | 12,461 | 2,222 | 99.6s |
| Cold (`ollama stop` first) | 10/10 | all `sell` | 0/10 | 12,461 | 2,568 | 110.4s |
| Warm (after num_ctx/keep_alive change) | 10/10 | 8 sell/1 wait/1 skip | 0/10 | 12,461 | 2,443 | 103.3s |
| Cold (after num_ctx/keep_alive change) | **9/10 distinct** (1 duplicate `candidate_id`, 1 candidate never reviewed) | 9 `sell`/1 dup | 1/10 | 12,461 | 2,629 | 113.8s |

`prompt_eval_count` was identical (12,461) across all four calls — deterministic given the same
candidates/analytics/history/market-conditions. `eval_count` (the model's own output length)
varied 2,222-2,630. Every run cleared "not all wait" and "≥90% non-empty evidence"; three of four
runs cleared "every candidate reviewed" — the fourth returned a duplicate review for one
`candidate_id` and silently never covered a different one, a occasional small-model robustness gap
`review_eval.py` now reports explicitly (it counts *distinct* `candidate_id`s covered, not raw
review-object count, and prints any requested id left uncovered) rather than masking it as "10/10".
This did not change the model pick — `qwen3.5:4b` still clearly outperforms the pre-Task-10
baseline (1/3 reviewed) and no other model was shown to do better under the same harness — but is
recorded here for anyone tuning the prompt further.

`qwen3.5:4b` is the smallest model, met every acceptance criterion in **every** run including a
cold start (the 6-9 GB alternatives needed a warm model already resident to finish inside the
original `ollama_timeout_seconds: 120`), and a spot-checked full review (see `STATUS.md`) correctly
read an OTM put as OTM, a genuinely ITM put (real live spot had moved) as ITM, and a post-expiry
earnings date as no-risk — the two specific misreadings Task 10 set out to fix. It also frees
~1.8GB vs the prior `qwen3:8b`. Alternatives (from the original 7-candidate comparison):
- **`qwen3.5:9b`** — showed more verdict diversity (sell/wait/skip) on the same candidates,
  arguably more nuanced judgment, but at 2x the download and a cold load that blew the original
  120s timeout in this environment (14 GB RSS already in use, 7/8 GB swap in use before any model
  loads) — a worse fit for the RAM-constrained M3 Pro this runs on.
- **`gemma4:e4b-it-qat`** — comparable results to `qwen3.5:4b` (14/14 reviewed, 0 empty evidence,
  no cold-start timeout) but 1.8x the download for no measured quality gain over the smaller model.
- **`qwen3:14b`** — ruled out without testing: ~9.3GB weights + ~2.7GB KV cache at 16k context
  (~12GB) exceeds what's free on this Mac.

**`think: true` was tried and rejected:** it is hardcoded `false` in `ollama_runner._generate`
(hybrid-reasoning `<think>` traces otherwise fight the schema constraint and bloat latency). A
manual test with `think: true` on `qwen3.5:4b` against the same 7-candidate prompt **did not
complete within 180s** (`httpx.ReadTimeout`) — well past the original `ollama_timeout_seconds:
120` — so it stays off.

**Expectations:** a small local model is noticeably less reliable at nuanced multi-signal judgment
than Claude — expect occasional validation failures (which fail soft to `[]`/`None`, same as a CLI
failure) and, per the fix-round-1 finding above, an occasional duplicate/missed candidate_id on a
larger batch. Schema-constrained `format` grammar-forces valid JSON matching the schema shape, but
the *content* (which facts the model actually reasons from, and whether every requested id gets
exactly one review) still depends on the model following the prompt — `evidence` being non-empty
and every candidate_id appearing exactly once are both rough proxies, not guarantees.

**`ollama_num_ctx` (24576, raised from 16384 in fix round 1).** The requested window must cover
the *whole prompt plus the generated JSON*, or Ollama silently left-truncates the prompt (dropping
the universe context + candidates at the start) and/or cuts the output mid-JSON — both yield
unparseable output and dropped reviews. **Measured 2026-09-30** on the production-shaped
10-candidate prompt: `prompt_eval_count` a stable 12,461 tokens, `eval_count` up to 2,630 — a worst
observed total of ~15,100, which was **92% of the old 16384 ceiling** (inside the ~20%-of-capacity
danger zone). The earlier Task-10 measurement (8,413 tokens on a 7-candidate, non-production-shaped
prompt) understated real usage because it omitted the analytics/history/market-conditions blocks a
real scan sends — **do not use that smaller figure to justify a lower `ollama_num_ctx`.** 24576
leaves ~40% headroom over the worst observed total. Re-measure with `scripts/review_eval.py`
(prints `prompt_eval_count`/`eval_count` every run) before changing this again — never lower it
without checking your own longest prompt still fits. RAM estimate: `qwen3.5:4b` is roughly half of
`qwen3:8b`'s parameter count, so its per-token KV cache should be roughly half-sized too — at
24576 tokens the estimated KV cache is still smaller than `qwen3:8b`'s was at the old 16384, a
combination this system ran under for months without incident.

**`ollama_keep_alive` (2m, lowered from 10m in fix round 1 — the prior justification was wrong).**
The 15-minute intraday scan cycle (`scheduler.intraday_loop_minutes`) is already *longer* than any
keep_alive value below 15m, so the scan loop's own review call was **already cold-loading every
cycle** under the old 10m setting — lowering it to 2m changes nothing for the scan loop
specifically; it only stops holding the model resident for 10 minutes nothing in the scan loop
actually uses. Checked the other three callers for a real 2-10 minute gap that would lose a
warm-call benefit under 2m but keep it under 10m: `write_journal_narrative` fires once/day at EOD,
never close in time to anything else; single-ticker `/scan TICKER` is ad-hoc/manual with no fixed
cadence; `review_roll` fires per triggered position from `monitor.intraday.fire_alerts` — when
several positions cross a threshold together (e.g. a correlated market move), those calls land
seconds apart on the same `ThreadPoolExecutor`, well inside even a 2-minute window; a *lone* roll
alert following a >2-minute gap now cold-loads, but that path already tolerates extra latency (the
Telegram send simply waits on the review) and its prompt is a single object, smaller than the
10-candidate review prompt measured above. No deterministic 2-10 minute repeated-call cadence was
found, so `keep_alive` moved to `2m`.

**`ollama_timeout_seconds` (180, raised from 120 in fix round 1) folds in the cold-load
measurement above:** warm wall time measured 99.6-103.3s, cold (`ollama stop` first) 110.4-113.8s
— both on the production-shaped 10-candidate prompt. 180 leaves real margin over the slowest
cold figure (110.4s), and since `keep_alive: 2m` means most calls are now effectively cold loads
(see above), the timeout must comfortably clear a cold call, not just a warm one — this Mac's OS
file cache was still warm from repeated recent use during measurement, so a genuinely cold
model (first use in days, or after heavier memory pressure has evicted its pages) could plausibly
be slower than what was measured. Latency is typically 100-115s per call on Apple Silicon for the
4B model with a 10-candidate production-shaped prompt.

### News-grounded review (Task 11, 2026-09-30) — no API key needed

Every review the Ollama backend produces now also sees recent news. Two pieces, both **keyless**
(no signup, no API key — `data.news_search_provider: google_news`, `src/data/google_news_backend.py`,
keyless Google News RSS search):

1. **A static `=== NEWS ===` block** (`src/claude/news_context.py`) injected into the strategist
   prompt on both the full-universe and single-ticker (`/scan TICKER`) paths — recent headlines
   per candidate symbol plus 3 broad-market headlines, numbered `N1`...`Nk` so the prompt's
   DECISION RUBRIC can cite them in `evidence` alongside the deterministic `F#` facts.
2. **A bounded tool-calling research turn** (`src/claude/ollama_tools.py`) — before the final
   review, the model gets one `/api/chat` turn with a `search_news` tool available and an
   explicit budget; it may call it up to `claude.max_tool_rounds` times for anything the NEWS
   block left open (e.g. "AAPL guidance", "Fed meeting this week"), or not call it at all. Any
   failure here (a model without tool support, a timeout, a malformed response) is logged and
   falls straight back to the Task 10 single-shot `/api/generate` path — this is enrichment, it
   can only add to a review, never block one.

**One switch turns the whole thing off:**

```yaml
claude:
  tool_research_enabled: false   # default: true — set false to fully revert to Task 10 behaviour
```

With it `false`, no NEWS block is built, no `/api/chat` research call is made, and
`review_candidates` goes straight to the original single-shot `_generate` (`/api/generate`) path
— byte-identical to the pre-Task-11 prompt. The other Task 11 keys (`news_per_symbol`,
`news_days`, `news_max_items`, `max_tool_rounds`, `tool_research_timeout_seconds`,
`news_fetch_budget_seconds`) only matter while it's `true` — see the `src/claude/` and
`settings.yaml` rows in `ARCHITECTURE.md` for what each one tunes.

**Time bound (2026-09-30):** the whole review — NEWS fetch, research turn, final call and the
single-shot fallback — shares one deadline, `tool_research_timeout_seconds +
ollama_timeout_seconds` (240s), plus at most one `review_min_call_seconds` floor (60s) for a late
fallback: never more than 300s. The intraday chain-fetch budget
(`market_data.chain_fetch_budget_seconds`, 350s) is sized against that 300s — if you raise either
timeout, re-check the sum in `config/settings.yaml` (a test will fail if it no longer fits in the
15-minute cycle).

**Live-measured (2026-09-30, `qwen3.5:4b`, this deployment):** `python -m scripts.review_eval
--model qwen3.5:4b --runs 2` against 7 real stored candidates (META/AMZN CSPs, the only rows in
the default `--since` window) with the NEWS block wired in measured `prompt_eval_count=10,248`
(vs. 12,461 for the same-shaped prompt without news at 10 candidates in the Task 10 table above —
not directly comparable candidate-for-candidate, but confirms the NEWS block's token cost is
modest relative to the rest of the prompt) and wall time 76-89s, both runs 7/7 reviewed, 0/14
empty evidence — comfortably inside `ollama_timeout_seconds: 180`. None of the 7 candidates cited
an `N#` id: every fetched headline was routine business news (product launches, AI partnerships)
with no thesis-breaking development and no earnings inside any trade's window, so the DECISION
RUBRIC's "cite `N#` only when it argues against `sell`" instruction correctly produced zero
citations — a manual `build_news_block(["META", "AMZN"], ...)` call confirmed real, current
headlines were present (13 items, real sources/dates), so the absence of citations reflects the
model correctly judging them irrelevant, not an empty or broken NEWS block. Separately, a direct
live call to `ollama_tools.research_turn` (one META candidate, `tool_research_enabled=True`)
confirmed `qwen3.5:4b` **does** call the `search_news` tool live — it asked `"META earnings
October 2026 guidance"`, the tool executed against the real `GoogleNewsSearchProvider`, and the
new results were numbered continuing from the NEWS block's existing `N#` ids — end-to-end in
2.1s (warm). A full `review_candidates(..., tool_research_enabled=True)` call for one candidate
completed in 33.3s and returned a review citing NEWS ids (`N3`, `N5`).

---

## 15. Trade ledger (optional)

**Status: built on `feat/trade-ledger` (docs/superpowers/plans/2026-10-05-trade-ledger.md) —
the ingestion backend and read-only API, plus the dashboard pages `/ledger` (overview),
`/ledger/trades`, `/ledger/ticker/[symbol]` and `/ledger/import`. Everything below works from the
CLI or the dashboard.** A broker-truth
ledger of every execution the IBKR account has ever recorded — not just what this system placed
— rolled up into trades → tickers → portfolio, with CSV/Flex/live ingestion and a one-way mirror
to a Google Sheet.

1. **Import your history.** Download an IBKR Activity Statement as CSV (Client Portal →
   Performance & Reports → Statements → Activity → the date range you want → CSV), then:
   ```bash
   python -m scripts.ledger_import ~/Downloads/<statement>.csv --dry-run  # parse + count, writes nothing
   python -m scripts.ledger_import ~/Downloads/<statement>.csv            # import for real
   ```
   Or use the dashboard's `/ledger/import` page (choose the CSV file; it shows the result, feed
   status, corporate actions awaiting review, and import history). The **first** import (CSV or Flex) locks the ledger to that statement's account — every later
   import for a different account fails `account_mismatch`. Override the lock explicitly with
   `ledger.account` in `config/settings.yaml` if you need to set it before importing (e.g. to
   reserve the real account while only paper history exists so far).
2. **Flex Web Service** (keeps the ledger current automatically — pulled once per day, inside
   the EOD report, step 7b, after the Telegram send, so a slow Flex poll never delays it):
   - Client Portal → Performance & Reports → Flex Queries → Activity Flex Query. Sections:
     **Trades** (level of detail **Execution**), **Cash Transactions**, **Corporate Actions**,
     **Conversion Rates**. Format XML; date format `yyyyMMdd`; time format `HHmmss`; separator
     `;`. Period: **Last 7 Calendar Days** (the nightly pull only needs to cover since
     yesterday).
   - Client Portal → Settings → Flex Web Service → enable it, generate a token. Put
     `IBKR_FLEX_TOKEN` and `IBKR_FLEX_QUERY_ID` (the query's numeric id, not its name) in
     `.env`.
   - Optional one-time FX backfill: create a second query with a 365-day period (Conversion
     Rates only is enough) and run `python -m scripts.ledger_flex_pull --query-id <that id>`
     once — this seeds `fx_rates` for the USD summary further back than the daily 7-day pull
     ever will on its own.
   - Verify before relying on it: `python -m scripts.ledger_flex_pull --dry-run` fetches and
     parses without writing, and prints executions/cash/FX counts plus a `codes` breakdown —
     confirm expiries and assignments show up with codes like `C;Ep` (expired) and `A;C`
     (assigned-and-closed).
   - If `IBKR_FLEX_TOKEN`/`IBKR_FLEX_QUERY_ID` aren't set, both the EOD step and
     `scripts.ledger_flex_pull` are no-ops (the script prints a message and exits 0) — the
     ledger runs fine on CSV + live fills alone, just without the automatic daily catch-up.
3. **Google Sheet mirror** (optional — a one-way, read-only copy of the ledger in a spreadsheet
   you already have open day to day; `gspread`/`google-auth` are base dependencies — already
   installed by `pip install -e ".[dev]"` in step 2, no separate extra needed):
   - Create a Google Cloud project, enable the **Google Sheets API**, create a **service
     account**, and download its JSON key.
   - Share your spreadsheet with the service account's email (as **Editor**).
   - Set `GOOGLE_SHEETS_CREDENTIALS_PATH` (path to the JSON key) and `LEDGER_SHEET_ID` (the id
     in the sheet's URL, between `/d/` and `/edit`) in `.env`.
   - **Which tabs it writes** is set by `ledger.sheets_tabs` in `config/settings.yaml`, a map of
     role → tab **gid** (the number after `gid=` in the tab's URL — *not* the spreadsheet id):
     `options` (one row per option trade), `buy_and_hold` (one row per ticker with open stock
     lots: shares, avg cost, cost basis, source bought/assigned, dividends — native currency, so
     SGD/GBP lines stay SGD/GBP), `tickers` (per-ticker roll-up) and `summary` (portfolio
     summary + an `Updated (UTC)` row). Each listed tab is **fully rewritten** whenever the
     ledger changes (throttled to at most once per `ledger.sheets_min_interval_seconds`, default
     60s), so don't hand-edit or add columns inside them. A role you leave out (e.g. a credit
     spreads tab) and every other tab are never read or written. With `sheets_tabs: {}` the
     mirror falls back to creating three tabs it owns: `Ledger (auto)`, `Tickers (auto)`,
     `Summary (auto)`. The mirror carries no unrealized P&L (no live marks in the sheet).
4. **Optional: see manual TWS trades intraday, not just at the nightly Flex pull.** In TWS,
   Global Configuration → API → Settings → set **Master API client ID = 14** — this is the
   approval service's exec connection, and with the master id set, IBKR delivers
   `commissionReportEvent`s for trades placed from *any* client on the account, including a
   manual fill you place by hand in TWS itself, so the ledger picks it up the same day instead
   of waiting for the next Flex pull.
   **Caveat:** the exec process's orphan-fill reconciliation matches by contract as a
   fallback, so with the master id set a manual TWS sell-to-open of the exact same contract as
   a recoverable SUBMITTED, REJECTED or CANCELLED system order could be booked as that order's
   fill. Leave the setting off if you routinely place manual trades in contracts the system
   also trades.
5. **Checking it worked:** the CLI commands above print what they did. From a running API
   (`python -m scripts.run_api`), `curl -H "Authorization: Bearer $WEB_API_TOKEN"
   http://localhost:8787/ledger/summary` (or `/ledger/trades`, `/ledger/tickers`) confirms the
   book is populated; `GET /ledger/imports` reports the Flex/Sheets feed status (`configured`,
   `last_run`, `last_status`/`last_error`) and the last 50 import runs — the same data the
   dashboard's `/ledger/import` page renders (including the "Google Sheet mirror: failing: …"
   line).

Also update:
- Troubleshooting rows: `account_mismatch` on a ledger import, a Flex `1012` error, and the
  Sheets mirror not updating — see the Troubleshooting table below.

---

## 16. Daily credit spreads (optional)

A second, isolated system that trades same-day SPY credit spreads beside the wheel, in the same
paper account and through the same IB Gateway. It ships **disabled** and, once enabled, in
**shadow** mode: it records the trades it would have made (simulated fills with slippage and
commission) and places no orders.

### What it costs

| Item | Needed for | Cost |
|---|---|---|
| IBKR **OPRA Top of Book** (US options L1) | Live SPY/SPX option quotes | USD 1.50/mo, waived above USD 20/mo commissions. You likely already have it for the wheel |
| IBKR **Cboe index data** (SPX index value) | The SPX spot the GEX map is built around (SPY's own price comes from the stock quote the wheel already uses) | A few USD/mo. Check Client Portal → Settings → Market Data Subscriptions for the current package name and price. Without it the service logs "no index price" and builds no map |
| **ThetaData Options Standard** | The backtest only (tick-level NBBO since 2016, SPX index since 2022) | USD 80/mo. Subscribe for one month, run the backtest (it caches to `data/spreads_bt/`), then cancel |

### Enable it

1. Add `TELEGRAM_THREAD_SPREADS=<topic id>` to `.env`, or leave it empty for the main chat.
2. Copy the template: `cp config/spreads.example.yaml config/spreads.yaml` (your copy is git-ignored). Make sure your private `config/settings.yaml` has `spreads: 30` under `ibkr.client_ids`.
   - **Sizing:** the book trades as if it had `risk.starting_capital_usd` ($100,000), plus whatever it has realized since. Each spread is sized so a full loss is `risk.max_loss_pct_of_capital` (10%) of that, about 21 SPY spreads at the start. Your account's own size (about $1M on paper) is not used.
   - Fill in `risk.ex_dividend_dates` with SPY's upcoming ex-dividend dates (quarterly); no new call spreads go on those days or the day before.
3. In `config/spreads.yaml`, set `enabled: true` and keep `mode: shadow`. Restart: `./ibkr restart` (the supervisor starts `scripts.run_spreads` with the other daemons; `--no-spreads` skips it).
4. Each trading day you get, in the spreads thread: the 09:31 ET GEX map (spot, regime, expected move, put wall / flip / call wall), every entry and exit, and a 16:10 ET summary. Entries are rare by design: the system sells only after the market has moved at least half a day's expected move and stopped extending it for 10 minutes, and only on the side against that move. An entry message names its gamma regime; **NEGATIVE GAMMA** trades are taken on purpose and tagged so you can judge them later.
5. Weekly: `python -m scripts.spreads_report --mode shadow`. Compare **win rate against break-even win rate**. A 90% win rate with a 95% break-even is a losing strategy. The report repeats the numbers for negative vs positive gamma, puts vs calls, gap days and each exit reason; `--csv data/spreads_trades.csv` exports every trade with its tags.
6. Maintain `risk.events` yourself: `- {day: 2026-10-28, label: FOMC}` blocks a whole day; `- {day: 2026-08-28, until: "10:30", label: Fed chair speech}` blocks entries only until 10:30 ET. CPI and PPI print before the open, so they usually need no entry.
7. **Stop new entries instantly:** `touch data/spreads.halt`. Exits keep running. Delete the file to resume.

### Backtest before paper

1. Install and start the Theta Terminal (v3, port 25503).
2. Run the one-time symbol check: `curl "http://127.0.0.1:25503/v3/option/list/expirations?symbol=SPXW&format=csv" | head`. If that's empty, set `backtest.option_symbol: "SPX"`.
3. Run `python -m scripts.spreads_backtest --start 2026-06-01 --end 2026-06-30 --csv data/spreads_bt/june.csv`.
4. Compare one setting at a time (the cache makes reruns free):
   - profit take: `--profit-take 50` vs `--profit-take 80`
   - entry rule: `--trigger move` (sell after a stalled move) vs `--trigger always` (the original every-check rule)
   - negative gamma: `--negative-gamma allow` vs `--negative-gamma skip`

   Each run prints the settings it used, the totals, average hold and MAE, and the breakdown by regime, side, trigger, gap day and exit reason.

### Moving to paper orders

Only do this if shadow **and** backtest both show positive expectancy after costs.

1. During RTH, run `python -m scripts.spreads_combo_check --short <spot−60> --long <short−5>`. TWS must show the BAG as a **credit**. If it shows a debit, stop: see STATUS.md.
2. Still during RTH, run `python -m scripts.spreads_combo_check --short <spot−5> --long <short−5> --fill`. It opens a one-lot near the money and closes it straight away, then prints `OK` or `MISMATCH` for each fill price's sign (the executor expects a negative average for the opening credit and a positive one for the closing debit), followed by every execution IBKR reported with its secType and commission. Any `MISMATCH`: stop and see STATUS.md. Note in STATUS.md whether a `secType=BAG` line appears and whether every line has a commission: the executor waits for a commission on every fill. If it says the close did not fill, close the SPY spread by hand in TWS at once.
3. Leave the trade ledger on your **real** account. It tracks one account and ignores paper fills by design (`ledger.account`; changing it to the paper account would make every real-account import fail `account_mismatch`). Paper spread results live in `data/spreads.db`: `python -m scripts.spreads_report --mode paper`.
4. Set `mode: paper` and restart.
5. If the Spreads thread says *the broker does not hold all of* a spread, a leg is still live at IBKR: check the position in TWS and close the rest by hand; do not mark it settled. If it says the broker *shows neither leg* of a spread, or that a spread *expired … but spreads.db still holds it open*: check TWS for what happened (an assignment, or a close that filled while the Gateway was down), then record it with `python -m scripts.spreads_resolve --spread-id <id> --debit <price paid per share> [--contracts N] [--commission USD]`.

Live trading is not supported by this build. The service refuses to run with `LIVE_TRADING=true`.

### Commands

| Command | What it does |
|---|---|
| `python -m scripts.run_spreads` | The spreads service (clientId 30). Normally started by `scripts.start` / `./ibkr restart`; `--no-spreads` skips it. Logs to `logs/spreads.log` (`./ibkr logs spreads`) |
| `python -m scripts.spreads_report --mode shadow\|paper [--csv path]` | Results from `data/spreads.db`, split by every trade tag |
| `python -m scripts.spreads_backtest --start … --end … [--profit-take N] [--trigger move\|always] [--negative-gamma allow\|skip] [--csv path]` | ThetaData minute replay of the live rules. A day whose data won't load is listed as skipped instead of ending the run |
| `python -m scripts.spreads_combo_check --short K --long K [--fill]` | Paper-only check of the combo order sign: display only by default, a filled-and-closed one-lot with `--fill` |
| `python -m scripts.spreads_resolve --spread-id ID --debit D [--contracts N] [--commission C]` | Settle by hand a spread the service can no longer close (it expired while still open, or the broker no longer holds it) |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Spreads thread says *"could not build the GEX map (no chain or no index price)"* | No Cboe index-data subscription for SPX, or the Gateway lost its data farm | Check Client Portal → Settings → Market Data Subscriptions, then run `python -m scripts.healthcheck` |
| Shadow mode records no spreads for days | Expected on quiet days: the move trigger sells only after a move of at least half the day's expected move has stalled | Check that the SPY session stats arrive (`python -m scripts.healthcheck`), and run `python -m scripts.spreads_backtest ... --trigger always` to see what the original every-check rule would have done |
| Spreads thread says *"entries blocked — broker and spreads.db disagree"* | A paper spread was closed or changed outside the system, a fill was missed during a Gateway restart, or an opening order is still working at IBKR | Compare the TWS positions and open orders with `data/spreads.db → spread_positions`. Settle a spread the broker no longer holds with `python -m scripts.spreads_resolve`, or close a stray position by hand. The service re-checks every 30 s and unblocks entries by itself once they agree |
| Spreads thread says *"IB Gateway is disconnected with N spread(s) open"*, or *"URGENT … past the time stop"* | The Gateway (or its connection) is down while spreads are open, so exits are paused | Restore the Gateway. Past the time stop, close the SPY spreads by hand in TWS before the bell: SPY settles in shares |
| Spreads thread says a fill *"… check_fill:positive_sign"* (or `negative_sign` / `off_ladder`) | IBKR reported the combo's average fill price with an unexpected sign or outside the ladder | The magnitude was recorded. Compare it with the fill in TWS and fix the row with `scripts.spreads_resolve` if needed; report it: the sign convention was verified on paper on 2026-10-08, so a surprise means IBKR changed something |
| Config load fails with *"… exceeds market_data.max_concurrent_lines"* | With `spreads.enabled: true`, the wheel's scan batch, the spreads lines and the monitor's reserved lines together exceed the configured market-data cap | Lower `spreads.max_market_data_lines` or `market_data.chain_batch_size`, or raise `market_data.max_concurrent_lines` if your login really has the headroom |
| Config load fails with *"spreads.book_underlyings [...] also appear in config/universe.yaml"* | SPY, XSP or SPX is in the wheel universe (the committed example used to list SPY). They are reserved for the daily credit-spread book | Remove it from `config/universe.yaml`: the two books may never share an underlying |
| Every approved order fails at once with *"Live re-validation failed: delta drifted outside target band … live mid collapsed well below the approved premium"* | Before 2026-09-30, repeat scans read a re-subscribed contract's **cached** ib_async ticker, so candidates were priced from quotes 15–30 min old and the send-time re-gate (correctly) rejected them against a fresh quote | Fixed by `req_fresh_mkt_data` — restart the daemons (`./ibkr restart`) to pick it up. The failure message now shows *live mid vs approved* and *live Δ vs approved*: a small gap is a genuine market move (expected — the gate is working); a large, systematic gap on every order means stale data again |
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
| Web status shows "IBKR connection" disconnected after Gateway was stopped or restarted (`logs/system.log`: `reconnect failed after 20 attempts — now watching 127.0.0.1:4002`) | Gateway was down — or sitting at its login/2FA screen — longer than the ~16-minute fast-retry window. The daemons then drop to **watch mode**: every 60s they probe the Gateway API port (a bare TCP connect, no clientId) and reconnect on their own once it answers, so no process restart is needed. For unattended nightly restarts, still set up §4 "Automating Gateway login with IBC" so Gateway logs itself back in | Start Gateway and finish logging in; the daemons reconnect within ~60s. If they don't, check the port is listening (`lsof -nP -iTCP:4002 -sTCP:LISTEN`). A daemon started *while Gateway was already down* never attaches a reconnector — restart `python -m scripts.start` in that case |
| The 15-min intraday scan never fires after a restart — `logs/system.log` shows `Approval service running` but no `Intraday loop started`, and the startup happened during a TWS connectivity drop (`Error 1100`) | The approval service started against a half-dead TWS socket (handshake succeeded, but data requests time out). Startup fill-reconciliation called `reqExecutions`, which hung waiting for an event that never arrived, blocking the intraday-scan task from being created. **Fixed (2026-06-23):** `reqExecutions` is now timeout-bounded and the scan loop is armed before startup reconciliation | If you see this on an unpatched build, restart `python -m scripts.start` once TWS connectivity is restored. After the fix it self-recovers (the reconcile pass is skipped and logged) |
| After a restart, `/account` / `/status` / `/scan` / `/positions` say "IBKR account unavailable", and the logs show `Error 326` ("client id is already in use") → `Peer closed connection. clientId 15 already in use?` → `Could not connect IBKR scan connection` | The restart was fast enough that IB Gateway still held the previous session's clientId when the new scan connection tried to grab it. **Fixed (2026-06-24):** `connect_with_retry` retries with backoff so Gateway can release the id, and the launcher waits `STARTUP_GRACE_SECONDS` before starting daemons | Self-recovers within the retry window. If it persists, wait 30–60s before restarting, or restart IB Gateway to clear the stuck clientId. Exec (orders) and monitor connect on their own client IDs, so order execution is unaffected |
| A 🛑 *Scan blocked* message arrives on Telegram, every symbol in the prior cycle timed out (`option chain for X exceeded symbol_timeout_seconds`), and the logs show `Error 1100` flapping beforehand | The scan socket went **half-dead** mid-session — `isConnected()` still reports connected (TCP handshake up) but TWS has lost its IBKR data farm, so every chain request times out. Left unguarded, one cycle grinds for ~2h and blocks every later 15-min cycle. **Fixed (2026-06-24):** a pre-scan `probe_market_data_health` snapshot and a consecutive-timeout circuit breaker detect the dead farm, notify you with the exact reason, and force a reconnect. **Extended (2026-08-28):** the message now also names which symbols never got reached this run and confirms they're queued for the next cycle (`pending_retry_symbols`) — see `How the scan works.md` §4, "The retry queue". **Diagnosis (2026-09-09):** the block message now carries the probe's *root-cause classification* — from the IBKR error codes observed during the probe window — instead of the old hardcoded "Error 1100" label, which mislabelled a real `Error 10197` competing-session block on 2026-09-08. Read the diagnosis line before acting: `10197` means another login on the same IBKR account holds the live-data entitlement (IBKR Mobile, second TWS/Gateway, Client Portal web) and a reconnect will NOT fix it — close the other session, or register a second username for the bot (IBKR supports this for exactly this case). `1100` means Gateway lost its upstream link (the forced reconnect usually recovers it). `354`/`10089`–`10091` mean no market-data subscription for the probe symbol. `1101`/`1102` mean the link is flapping (wait one cycle) | Follow the action hint in the message. For 1100/generic: self-recovers — the cycle is skipped, `ib_scan.disconnect()` triggers `AutoReconnect`, and the queued symbols are forced through the gate on the next 15-min cycle regardless of whether they've moved, so nothing is silently stranded. If blocks persist, restart `python -m scripts.start` once TWS shows all data farms connected. For 10197: close the other logged-in session; a reconnect won't help, and the Gateway stays stuck until it logs in again — under IBC the loop restarts it automatically (`gateway_recovery`, see the 10197 row below), otherwise restart Gateway by hand. Tune `market_data.health_probe_timeout_seconds` / `max_consecutive_chain_timeouts` if needed |
| The scan thread is silent for the full ~15–25 min of a full sweep or multi-symbol retry, with no sense of progress until results (or a block) finally arrive | Before 2026-08-28 the intraday loop ran `run_scan` with no progress callbacks — the `_Tracker` progress-bar renderer already existed for manual `/scan` but was never wired up for the 15-min loop. **Fixed:** `_run_intraday_scan` now sends its own live-updating "🔍 Scanning…" message (progress bar + current symbol, e.g. `⚙️ Option chain — SOFI (31/46)`) before every spawned cycle, edited in place (throttled to ~1 edit/2s) as the scan progresses, same renderer `/scan` uses | Nothing to do — the message appears automatically on every spawned cycle (including quick 1–2 symbol ones, which just flash through 0%→100%) |
| `/status` is sent during a half-dead-socket episode (see the 🛑 *Scan blocked* row above) and never gets any reply at all — not even an error | `isConnected()` only reflects the TCP/exec-socket handshake, which stays up through the half-dead-socket state, so `handle_status_command` took the "IBKR connected" branch and awaited `get_account_snapshot_async` (`accountSummaryAsync`) with no timeout — it hung forever waiting on a data-farm response that never arrived, so the coroutine never reached `reply_text`. **Fixed (2026-08-27):** the account-snapshot fetch is now bounded by `market_data.health_probe_timeout_seconds` (same budget as the scan loop's own health probe); on timeout it logs a warning and replies with the rest of `/status` (positions, pending approvals, open orders) minus the account section | Self-recovers on a patched build — you still get a reply, just without the account-totals line, within `health_probe_timeout_seconds`. On an unpatched build, wait for TWS to show all data farms connected and retry `/status` |
| Only the terse `⚠️ Intraday scan cycle skipped: data-farm health probe failed (half-dead socket)...` warning arrives — the detailed 🛑 *Scan blocked* message above never shows up, and `logs/approval.log` has `Intraday loop: failed to send scan-blocked notice` followed by a `telegram.error.BadRequest: Can't parse entities: character '(' is reserved...` traceback | The 🛑 *Scan blocked* send itself was broken: it interpolated the plain-English block reason (which contains literal parentheses, e.g. `(half-dead socket)`) into a MarkdownV2 message without escaping it, so Telegram rejected the whole message and the failure was swallowed. This affected every block since the 2026-06-24 fix above shipped — the "notify you with the exact reason" behavior never actually worked. **Fixed (2026-08-13):** the reason is now escaped with `_md_escape` before being sent | Self-recovers on a patched build — you'll get both the 🛑 detail message and the ⚠️ skip warning going forward. On an unpatched build the skip warning alone is enough to know a reconnect is in progress; check `logs/approval.log` for the specific block reason |
| No "Scan blocked" Telegram message during a data-farm outage → fixed 2026-09-29 (unescaped hint); if still silent, check `logs/approval.log` for `scan-blocked notice` | The pre-scan health probe's `action_hint` was interpolated into the MarkdownV2 message unescaped, so a hint containing MarkdownV2-reserved characters (parentheses, periods, etc. — e.g. "Restart Gateway (Error 1100).") still broke the send even after the 2026-08-13 `reason`-escaping fix above, and `_notify_scan_blocked` had no fallback if the MarkdownV2 send failed | **Fixed (2026-09-29):** the call site now sends `_md_escape(probe.action_hint)`, and `_notify_scan_blocked` retries as a plain-text send (no `parse_mode`, no escapes) if the MarkdownV2 attempt still raises. If the alert is still silent, check `logs/approval.log` for the `scan-blocked notice: MarkdownV2 send failed — retrying as plain text` warning (MarkdownV2 failed but plain text should have gone out) or `Intraday loop: failed to send scan-blocked notice` (both attempts failed — a real Telegram outage) |
| A manual `/scan` finishes and shows an ordinary (often empty) results screen, but `logs/approval.log` shows `N consecutive chain timeouts — aborting run, socket appears half-dead (processed X/46 symbols)` with `X` well short of the universe size | The half-dead-socket circuit breaker fired mid-scan and `run_scan` sent whatever partial results it had gathered — with no indication anything was cut short. `handle_scan_command` only checked `result.lease_skipped`, never `result.aborted_unhealthy` (the intraday loop already checked it). **Fixed (2026-08-13):** the `/scan` progress message is now edited to report `processed/total` symbols and that results are partial, and a reconnect is forced the same way the intraday loop does | Self-recovers — a forced reconnect fires automatically. On a patched build just re-run `/scan` once the reconnect completes (a few seconds). On an unpatched build, check `logs/approval.log` for the "consecutive chain timeouts" line to know whether a short results screen is a real empty scan or a truncated one |
| A 15-min intraday cycle you expected (e.g. `13:30 ET`) never shows a `🔄 Scan started` message and `logs/approval.log` has no `Intraday loop: RTH cycle starting` line for it at all — not even a skip warning — while the *previous* cycle's `scan: processing <TICKER>` lines are still advancing past the 15-min mark | The prior cycle's scan was legitimately slow on a perfectly healthy connection (not a dead socket — no circuit breaker involved) and ran past 15 minutes, most commonly right after a restart: with no `scan_state` history yet, the S1 materiality gate treats the entire universe as material (`intraday materiality gate — 46/46 symbols material`) instead of the usual filtered subset, and several large chains can each take 50–60s. **Fixed (2026-08-13):** the scan now runs as its own task (`_run_intraday_scan`, spawned via `asyncio.create_task`) instead of being awaited inline, so the loop keeps hitting every 15-min mark (and its profit-take/loss-exit checks) regardless of how long a previous scan is still taking; an overrun now correctly logs/notifies "previous scan still running" on the next mark instead of vanishing | Self-recovers — this is expected for the first cycle or two after a restart while `scan_state` warms up; later cycles narrow back to the materiality-gated subset and finish well under 15 minutes. On an unpatched build, no action self-corrects the missing cycle — the next mark after the slow scan finishes will just resume normally |
| The EOD Telegram summary is very late or never arrives, and `logs/eod.log` shows a long run of `reqHistoricalData: Timeout` + `Error 162 … Historical Market Data Service … query cancelled`, one symbol per minute | IBKR's **historical-data farm (HMDS)** was down for the EOD session — the account read succeeds but every `OPTION_IMPLIED_VOLATILITY` request in `_append_daily_iv` times out. Left unguarded, ib_async's 60s default × the full universe delayed the (IV-independent) P&L summary and Telegram send by ~1 hour. **Fixed (2026-06-24):** each request is bounded to 8s (`_IV_REQUEST_TIMEOUT_S`) and a run of 5 consecutive failures (`_IV_MAX_CONSECUTIVE_FAILURES`) triggers a check | On a patched build the report self-recovers (logs `aborting IV append after N consecutive failures` only when the farm is confirmed down), sends the summary, and lets `iv_history` age one day — it back-fills on the next healthy EOD run or via `scripts.backfill_iv`. On an unpatched build, kill the hung `scripts.run_eod` and re-run it once TWS shows the HMDS farm connected |
| `iv_rank` looks stuck/stale for most of the universe for days or weeks (checks ribbon shows the same IV-rank-driven rejects every scan; `iv_history` rows for most symbols stop advancing) while a couple of symbols keep getting fresh rows | **Root cause found 2026-09-11:** the consecutive-failure check above used to assume 5-in-a-row meant the whole HMDS farm was down and `break`, unconditionally aborting every symbol later in the alphabetically-sorted universe — for a month, only AAPL/AMZN (first in sort order) kept updating while a chronic failure in one or a few other symbols (alphabetically between AMZN and ARKK) silently froze the rest. Since `iv_rank` is a hard gate (`min_iv_rank: 30`) and the largest single scoring weight (0.30), this made good-premium candidates for the frozen symbols fail `iv_rank_below_minimum`/`score_below_minimum` for reasons that had nothing to do with their actual vol. **Fixed:** the failure run now calls `probe_market_data_health` before bailing — a confirmed-unhealthy probe still aborts fast (old behaviour), but a healthy probe means the failures are isolated to a few bad symbols, which now get skipped (logged at WARNING with the symbol name) while every symbol after them still gets attempted | On a patched build this self-heals within a day or two once the fix ships (the previously-skipped symbols resume getting fresh `iv_history` rows every EOD run). To backfill the gap immediately: `python -m scripts.backfill_iv`. Check `logs/eod.log` for `EOD IV append failed for <SYMBOL>` (now WARNING, not silent DEBUG) to see which symbol was chronically failing and why |
| EOD summary is missing entirely (no Telegram message, no new `JournalRow`) and `logs/system.log` (the launcher, not `logs/eod.log`) shows `EOD exceeded 60 min — killed` | **Task 4b (2026-09-29) fix working as intended**, not a bug: the run hung — most likely the account-summary fetch looping through IBKR's 1100/1102 nightly-reset connectivity flap (Error 322, "Maximum number of account summary requests exceeded") — and `scripts.start`'s supervisor killed it (SIGTERM, then SIGKILL after `STOP_GRACE_SECONDS`) after `scheduler.eod_timeout_minutes` (default 60) rather than letting it block every later EOD run forever, as it used to (2026-09-29 evidence: one run was still alive >11h after starting) | Check `logs/eod.log` for what it was stuck on at the time of the kill. If it's the account-summary fetch, the connection now also carries the same 1102 guard (`suppress_account_summary_on_reconnect`) the approval service's exec connection has, and bounds the fetch to 120s with a fallback to the last `portfolio_snapshots` row (`_fetch_account_snapshot`) — so a genuine account-summary hang should now resolve on its own well under the 60-min ceiling; a kill after the fix ships points at a different stuck step. Re-run by hand with `python -m scripts.run_eod`, or wait for tomorrow's scheduled run; raise `eod_timeout_minutes` in `config/settings.yaml` if a slow-but-healthy run (e.g. a large IV backfill) is a false positive |
| Re-running `python -m scripts.run_eod` for a day that already has a journal entry | Expected — the EOD run is idempotent | `_write_journal` upserts by `entry_date`: the existing `JournalRow` is replaced with the new run's numbers (every field but `created_at`), not skipped or duplicated. This also means a repeat run still reaches the reconciler, assignment auto-detection, and tomorrow's position-snapshot baseline — before the 2026-09-09 fix, a same-day re-run raised `IntegrityError` on the first (insert-only) journal write and silently skipped all three. |
| IBKR error 10091 floods the log and zero CC/CSP candidates are generated for a symbol | `market_data_type: 1` (live) set but no real-time subscription for that symbol — IBKR sends no bid/ask, so `strict_mid = None` on every quote | Set `config/settings.yaml → ibkr.market_data_type: 3` (delayed). Delayed data provides bid/ask for all symbols; delta is supplied by the Yahoo Finance fallback. Only switch to `1` if you have verified full subscriptions. |
| IBKR error 354 floods the log and candidates have `greeks_source=black_scholes` | No live model-greeks subscription — the system fell back to Black-Scholes via Yahoo Finance | Acceptable for paper trading with `market_data_type: 3`. For live trading, subscribe to the **US Equity and Options Add-On Streaming Bundle** and set `market_data_type: 1` so IBKR model greeks flow through (required by the live-greeks gate). |
| IBKR error 10197 "No market data during competing live session" — or an approved order ends `rejected` with detail "Execution exception" and the log shows `No live ask received for <id> within 10.0s` | Another login on the same IBKR username (IBKR Mobile, a second TWS/Gateway, Client Portal) holds the market-data entitlement, so the send-time quote never arrives and the order is refused before it is placed. **The running Gateway stays stuck even after that session logs out** — only a fresh Gateway login brings the data back (2026-10-02) | Close the competing session. With Gateway under IBC (`./ibkr install --with-gateway`), the intraday loop then **restarts Gateway automatically** on the next blocked cycle (`gateway_recovery` in `settings.yaml`: 30-min cooldown, 3/day; the 🛑 *Scan blocked* message says what it did). With a hand-started Gateway, restart it yourself. For a permanent fix, register a second username for your phone/web logins. Nothing is placed on a quote timeout; the next scan re-queues the candidate if it still qualifies. |
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
| Ticker page price chart is empty | **Fixed 2026-09-11:** `GET /research/{symbol}/bars` now does a one-time on-demand backfill the first time a symbol has zero `daily_bars` rows, instead of only ever being populated by the nightly warm-tier cron — a first-ever view of any symbol should now show a real chart immediately. If it's still empty: the on-demand fetch itself failed (check `logs/api.log` for "On-demand daily-bar backfill failed for \<SYMBOL\>", usually a yfinance outage) | Check `GET /health → worker_heartbeat` for the worker's own health; retry the page (the backfill is best-effort and re-attempts on every view with zero rows), or run one warm refresh manually: `python -c "from src.research.ingest.quotes import refresh_warm_tier; refresh_warm_tier()"` |
| Web search returns no results for any ticker | The research worker hasn't run yet — `data/research.db` has no `symbols` rows | Run `python -m scripts.run_research_worker` once on first start; it pulls the SEC symbol directory (~10k tickers). Search works after the first successful job |
| The research worker (`scripts.run_research_worker`) goes quiet for hours/days with nothing in its log — no errors, no warnings, just silence — until the process is manually restarted | The Mac went to sleep (lid closed, no `caffeinate`, no launchd `KeepAlive`) and froze every thread in the process for as long as it was asleep. **Fixed 2026-09-11:** the scheduler no longer drops a job it discovers late (`misfire_grace_time=None` in `build_scheduler()`) — it runs the moment the process next gets CPU time instead of silently skipping forever, so a restart is no longer required after a sleep/wake cycle | This is a *recovery* fix, not sleep prevention — the worker still does nothing while the Mac is actually asleep, it just resumes correctly once it wakes (lid open, scheduled wake) instead of needing a manual kill + restart. To stop the Mac sleeping at all while the worker should be running, run the whole stack under `./ibkr install` (§6c) — its `com.ibkr.supervisor` agent already wraps `scripts.start` in `caffeinate -i -s` with `KeepAlive`, which is exactly this fix |
| Ticker page's AI summary panel says "unavailable" and the Generate button does nothing | `research.summary.backend` is set to `anthropic`/`openai` but `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` is missing in `.env`, or `claude_cli` is set but `claude` isn't on PATH and `claude.enabled` is false | Set the matching `.env` key, or switch `research.summary.backend` to `ollama` (requires `ollama serve` running) — a failed generation fails soft to `pending`, never an error |
| A ticker page (or `/options`) is missing data/fields you know were just fixed in code — price, day change, checks, IV all blank, or an approval card's timestamp is empty | `scripts.run_api`/`scripts.run_research_worker` run under plain `uvicorn.run()`/APScheduler with **no hot-reload** — a process started before your latest pull or edit keeps serving the old code indefinitely, however new the files on disk are. `next dev` (the frontend) does hot-reload on its own, so this only ever looks like a frontend bug | Check how long the process has been up (`ps -o pid,lstart,command -p $(pgrep -f scripts.run_api)`) against your last commit/edit time; if the process predates it, kill and restart both `python -m scripts.run_api` and `python -m scripts.run_research_worker` |
| Watchlist/ticker-page "Day" change is blank right after a symbol's first-ever view, or reads like a meaningless small number that drifts every 15 minutes | **Fixed 2026-09-14:** `change_pct` used to be the delta between two consecutive 15-min quote polls (`refresh_quotes`) — `None` until a second poll ever ran, and never a real day-over-day figure even once it was set. It's now `_day_change_pct()` in `ingest/quotes.py`: the change versus the most recent completed session's close in `daily_bars`, available from the very first poll. A first-ever view also no longer waits for that poll at all — `materialize()`'s `_quote()` seeds a quote on demand (`refresh_quote_for`) the moment a symbol with no `QuoteRow` is viewed | If it's still blank: the on-demand fetch itself failed (check the API log for "On-demand quote fetch failed for \<SYMBOL\>") or the symbol has no `daily_bars` history yet and the backfill also failed — retry the page, or run `python -c "from src.research.ingest.quotes import refresh_quotes; refresh_quotes()"` during market hours |
| `./ibkr restart` prints `start com.ibkr.supervisor: FAILED — Bootstrap failed: 5: Input/output error` and the stack stays stopped | `launchctl bootout` returned before launchd had finished removing the old supervisor job, so `start`'s `bootstrap` raced it (fixed 2026-09-30: `stop` now waits up to 30s for the label to unload) | Run `./ibkr start`. If `./ibkr stop` itself reports `still loaded after 30s`, check `./ibkr status` and `logs/launchd-supervisor.log`, then `./ibkr start` once it shows not loaded |
| The watchdog alerts `eod: …` after a day on which the supervisor restarted (crash + `KeepAlive` respawn, `./ibkr restart`, a reboot) around 16:15 ET | A supervisor restart while `scripts.run_eod` was running kills that EOD child with it; the relaunched supervisor only catches up an EOD that *never started* that day, so the interrupted run is lost and `eod_completed` is never written for today | Run it by hand once the stack is back: `python -m scripts.run_eod` (idempotent — safe to re-run). The watchdog's `eod` check clears on its next cycle after it finishes |
| `python -m scripts.ledger_import <file>.csv` (or the `ledger_import` command) fails `account_mismatch` | The statement's account doesn't match the one the ledger is already locked to (its first-ever CSV/Flex import, or an explicit `ledger.account` in `config/settings.yaml`) — most often a paper-account statement imported after the real account was already locked in, or vice versa | Confirm which account the ledger is tracking: `GET /ledger/imports` or the `ledger_account` row in `system_settings`. Import the matching account's statement instead, or clear/change `ledger.account` before the first import if you genuinely meant to switch accounts (there is no "re-lock" command — it is a deliberate one-way guard, R8) |
| `python -m scripts.ledger_flex_pull` (or the EOD step 7b) fails with `Flex error 1012: ...` | The Flex Web Service token expired or was revoked | Regenerate the token in Client Portal → Settings → Flex Web Service and update `IBKR_FLEX_TOKEN` in `.env` |
| The Google Sheet isn't updating | The mirror is unconfigured, erroring, or just hasn't hit its sync interval yet | Check `GET /ledger/imports` → `sheets: {configured, last_run, last_error}` (the same status the dashboard's `/ledger/import` page shows as "Google Sheet mirror: failing: …"). `configured: false` means `GOOGLE_SHEETS_CREDENTIALS_PATH`/`LEDGER_SHEET_ID` aren't both set; a non-null `last_error` is redacted (never contains the sheet id or credentials path) but still names the failure type. Confirm `LEDGER_SHEET_ID` is the spreadsheet id (the long string between `/d/` and `/edit`), not a tab gid, that every gid in `ledger.sheets_tabs` exists in that spreadsheet, and that the spreadsheet is shared with the service account's email as Editor, and that `ledger.sheets_min_interval_seconds` (default 60s) has actually elapsed since the last ledger change |
