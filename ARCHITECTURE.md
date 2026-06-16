# System Architecture

A plain-English guide to how the system is built, what each part does, and how they connect.

---

## The big picture

Think of this system as a trading desk with several specialists who each do one job:

1. **Data Collector** — connects to Interactive Brokers and fetches live prices, option chains, and your account positions.
2. **Analysts** — calculate whether now is a good time to sell options on a stock (IV rank, technical trend, fundamentals, liquidity).
3. **Strategy Team** — generates specific trade candidates: "sell the AAPL July 200 call for $1.50".
4. **Risk Manager** — checks every candidate against hard rules before anything can proceed.
5. **Claude** — reviews the top candidates and writes a plain-English explanation of the tradeoffs.
6. **Telegram** — sends the candidates to your phone and collects your Approve/Reject response.
7. **Executor** — once you approve, re-checks the rules one more time with a live quote, then places the order.
8. **Intraday Watch** — monitors open positions during the day and alerts you when a roll is needed.

**You are the final decision-maker.** No order is ever placed without your explicit approval.

---

## How a trade happens (the pipeline)

```
IBKR live data
    ↓
Analytics (IV rank, technicals, fundamentals, liquidity)
    ↓
Strategy modules (generate candidate trades)
    ↓
Decision Engine (score + rank candidates)
    ↓
Rules Engine ← HARD STOP: enforces all risk limits, no AI involved
    ↓
Claude review (plain-English explanation, optional enrichment)
    ↓
Telegram → YOU approve or reject
    ↓
Rules Engine (re-checks with a fresh live quote) ← SECOND HARD STOP
    ↓
Order placed at IBKR (limit order at mid-price)
    ↓
Fill confirmation sent back to Telegram
```

Every step writes its results to the database. If any step fails, the system can resume from where
it left off. If Claude is unavailable, the pipeline continues without it — Claude enriches but
never blocks.

---

## Folder-by-folder guide

### `config/` — Tunable settings

These YAML files control how the system behaves. **You change behavior here, not in code.**

| File | What it controls |
|---|---|
| `settings.yaml` | IBKR connection (host, ports, client IDs), scan timing, execution timeouts, logging. The `claude` section also carries `skills_enabled` (default `true`) — whether promoted reasoning skills are injected into review prompts — and the N3 headless-subprocess hardening keys: `max_turns` (default `1`, a single agentic turn), `model` (pin the enrichment model id, e.g. `claude-sonnet-4-6`), and `disallowed_tools` (space-separated `--disallowedTools` denylist) so the unattended CLI can't drive tools or the filesystem. The local-LLM keys select and configure the Ollama backend: `backend` (`"cli"` code default, `"ollama"`, or `"cli_then_ollama"` — **this deployment runs `"ollama"`**, since `claude -p` isn't available), `ollama_host` (default `http://localhost:11434`), `ollama_model` (`qwen3:14b` here), and `ollama_timeout_seconds` (default `120`). The `scheduler.entry_cutoff` key (default `"15:00"`) sets the ET time after which the intraday loop stops surfacing new entries (profit-take checks still run until the close). The `automation` section holds the AUTOMATED-mode circuit breakers: `max_auto_trades_per_day` (cap on new-exposure entry orders per ET day) and `daily_loss_halt_pct` (auto-engage the kill switch on a daily realized-loss breach). The `execution.reprice_*` keys configure limit-order chase logic (`reprice_enabled`, default false; `reprice_interval_seconds`; `max_reprices`; `reprice_step_pct`) — when on, an unfilled SELL is stepped toward the bid before timing out. The `market_data.strike_band_pct` (floor, default `0.15`), `strike_band_iv_mult` (default `1.5`), and `strike_band_max_pct` (cap, default `0.40`, S8) keys drive the IV-scaled strike band (N6): the auto-computed band is clamped to `[strike_band_pct, strike_band_max_pct]` so a high-IV ETF can't explode the qualified-strike/batch count; an explicit per-symbol `universe.yaml → strike_bands` override is not clamped. `monitor.roll_execution_enabled` (default `false`, N20) turns roll alerts into approvable roll candidates. `market_data.max_concurrent_lines` is now enforced (N15): a `MarketDataCfg` validator fails config load if `chain_batch_size` exceeds it. `market_data.symbol_timeout_seconds` (default `90`) bounds how long `/scan` spends fetching one symbol's option chain — if IBKR never responds (pacing violation, error 10197 competing-session lockout), the symbol is skipped and the scan continues instead of hanging indefinitely. `market_data.spot_history_timeout_seconds` (default `10`) bounds the `reqHistoricalData` fallback inside `_get_spot`/`_get_spot_async`, which is only reached when the snapshot has neither a live tick nor a previous close. `market_data.intraday_rescan_move_pct` (default `0.005` = 0.5%) and `force_full_scan_minutes` (default `90`, `0` disables) drive the **S1 intraday materiality gate**: in the 15-min loop a `would_own` name is re-fetched only once its live spot drifts past `intraday_rescan_move_pct` from its last fetch; held names and names that cleared the score floor last cycle always fetch; and a full sweep is forced when the stalest fetched symbol exceeds `force_full_scan_minutes`. Manual `/scan` ignores the gate and always sweeps the full universe. |
| `risk_limits.yaml` | Per-ticker concentration limits, delta ranges, DTE windows, earnings blackout, minimum return. The `live_execution` section adds the send-time re-gate knobs: `min_live_premium_ratio` (reject a fill when the live mid has collapsed below this fraction of the approved premium — F2) and `require_ibkr_greeks_when_live` (in LIVE mode, require IBKR-sourced greeks for the delta gate — F6). `liquidity.morning_volume_cutoff_et` (default 10:30, N19) is the ET time before which the day-volume gate is skipped. `covered_call.min_strike_vs_basis` (default 1.00, N18) blocks below-cost-basis call writes — lower it to allow them on underwater holdings. |
| `universe.yaml` | Your watchlist (tickers to scan for CCs) and `would_own` list (stocks OK to be assigned via CSPs). Tickers are organised into three tiers: Tier 1 core (SPY/QQQ/AAPL/MSFT/NVDA/JPM/GLD/TSLA) plus sector-diversifier ETFs (XLF/XLK/XLE/XLV/XLP/XLU/XLI/TLT/SLV) that broaden the book away from its tech/crypto tilt, Tier 2 active (AMD/META/AMZN/PLTR/UBER/CRM/COIN/…), Tier 3 speculative/high-IV (SOXL/LABU/TSLL/DPST/MARA/MSTR/RKLB/…). The `sectors:` map groups every name for the per-sector concentration cap. An optional `strike_bands:` map sets per-symbol ±band overrides for the chain scanner (N6) — used for extreme-IV leveraged ETFs so their ~0.25-delta strike is in scope even before IV history exists. Leveraged ETFs (and CC-only thematics like ARKK/BITO) are in `indexes` only — never `would_own`. |
| `scoring_weights.yaml` | How much weight IV rank, technicals, fundamentals, and liquidity each get when ranking candidates. Also `min_candidate_score` (option-candidate floor) and a `buy_to_own:` block (`min_score`, `max_candidates`) governing the buy-to-own screen. |
| `skills/` | Reasoning-skill playbooks: `active/` (injected into review prompts), `proposed/` (Claude-drafted, awaiting human review), `rejected/`. Promotion is a human-gated file move via `scripts.skills`. These shape Claude's verdict + ranking only — never the gates above. |

**Rule:** Secrets (passwords, tokens) never go in these files. They go in `.env`.

---

### `src/ibkr/` — The IBKR connection layer

Handles everything that talks directly to Interactive Brokers via the `ib_async` library.

| File | What it does |
|---|---|
| `connection.py` | Opens and manages the connection to TWS/Gateway; enforces one connection per process. Provides a sync (`connect`) and async (`connect_async` / `async with`) connect with backoff, plus `AutoReconnect` — attached to the long-running daemons (approval service, monitor) it listens on `disconnectedEvent` and reconnects with capped backoff (re-subscribing market data on the monitor) so a TWS drop doesn't silently kill them. |
| `market_data.py` | Fetches live quotes, option chains, Greeks (delta/theta/IV), and historical IV data. Provides both a sync API and an `async` chain fetcher (`get_option_chain_quotes_async`) — the orchestrator uses the async one so every IBKR call runs on the `ib_async` event-loop thread (never a worker thread), respecting the line-limit batching. The strike band is **IV-scaled** (N6): `_strike_band_pct` returns `max(strike_band_pct, strike_band_iv_mult · IV · √(DTE/365))` from the symbol's latest stored IV (or a `universe.yaml → strike_bands` per-symbol override), so high-IV names widen enough to surface their ~0.25-delta strike instead of being clipped by a fixed ±15%. The auto-computed band is capped at `strike_band_max_pct` (S8) so an extreme-IV ETF can't generate a runaway strike/batch count; an explicit per-symbol override is exempt from the cap. **Scan-efficiency (S3/S7):** the async path centres the strike band on `_resolve_spot_async`, which prefers `price_data.get_ohlcv`'s latest cached daily close (free after the first scan) and only falls back to a dedicated `reqMktData(snapshot=True)` when no cached close exists — skipping a ~2s spot snapshot per symbol per intraday cycle. Per-batch quote waits and the spot-snapshot wait are **event-driven** via `_await_ready`: they return the instant ticks populate (a well-behaved batch in ~0.2–0.5s) with the old fixed `quote_sleep_seconds`/2s as a *ceiling*, not a floor. Greeks are not waited on (absent on delayed/paper data; the Black-Scholes fallback fills them), preserving the speedup on the target account. Cancel-between-batches line-cap discipline is unchanged. **Greeks fallback is layered IBKR-first (S2):** `_ticker_to_quote` takes the delta/IV from the first available IBKR per-contract computation (`modelGreeks` → `lastGreeks` → `askGreeks` → `bidGreeks` via `_pick_greeks`) so a momentarily-missing model tick still yields *genuine* IBKR greeks; quotes that have an IBKR IV but no delta are BS-filled locally by `_enrich_greeks_from_ibkr_iv` (no network); only quotes IBKR could value *neither* greeks nor IV for fall through to the expensive `_enrich_greeks_yf` Yahoo download (now instrumented — it logs how many quotes forced a Yahoo fetch and how long it took). The scan batch requests generic ticks `101,106` (option OI + implied vol) to capture the IBKR IV. Any BS-derived delta is labelled `greeks_source="black_scholes"` (never `"ibkr"`), so the F6 live-execution gate still rejects it as untrusted live greeks. |
| `portfolio.py` | Reads your current positions, account balance, buying power, and margin. `enrich_positions_with_greeks_async` populates option-position deltas from live model greeks (used by the EOD net-delta-exposure metric, which would otherwise read 0). |
| `contracts.py` | Builds valid IBKR contract objects for stocks and options; runs `qualifyContracts` to validate them |

---

### `src/analytics/` — The analysis layer

Computes signals that determine whether a trade is worth taking.

| File | What it calculates |
|---|---|
| `iv.py` | **IV Rank** (how high is current implied volatility vs. the past year?), **IV Percentile**, term structure slope, put/call skew, and **VRP** (Volatility Risk Premium = current IV% − HV30%; positive means options are pricing in more vol than realized, which is the premium seller's edge). HV30 (`_compute_hv30`) now derives from the shared `price_data.get_ohlcv` settled-close history rather than its own 3-month yfinance pull. |
| `market_conditions.py` | Fetches market-level signals once per scan (not per symbol). Currently provides **VIX** via yfinance `^VIX`. Returned as a `MarketConditions` schema and attached to `ScanResult`. VIX is shown in the scan completion message. |
| `technicals.py` | RSI, MACD, moving averages, ATR (volatility), `atr_ratio` (ATR/price — a normalised volatility measure, renamed from the misleading `trend_strength`/`_adx_proxy`, N16), support/resistance levels, and a market regime classifier (trending up/down/sideways). Settled OHLCV bars come from `price_data.get_ohlcv` (the incremental store — see below), and `_working_frame` overlays today's bar from a live price so `TechnicalStats.price` and the indicators reflect the live session, falling back to the last settled close on error. `get_technical_stats` accepts an optional `spot_override`: when the orchestrator has already inferred a live spot from the IBKR option chain via `iv.infer_spot_from_quotes` (put-call parity) this scan cycle, that value is used and `TechnicalStats.price_source="ibkr"`. It also accepts an optional `cached_yf_price` (S1 follow-up): a `fast_info` price the intraday materiality probe already fetched this cycle for a symbol whose chain was skipped — reused instead of a second `_fetch_last_price` call, still recorded as `price_source="yfinance"`. Failing both, the price comes from a fresh `_fetch_last_price` (`yf.Ticker(symbol).fast_info["lastPrice"]`, a cheap *uncached* live quote) and `price_source="yfinance"`. |
| `price_data.py` | **Incremental OHLCV loader** — the single source of settled daily bars for both `technicals.py` and HV30 (`iv.py`). `get_ohlcv(symbol)` reads the `price_history` table and fetches **only the missing tail** from yfinance (or a full year when the store is empty), persisting new settled sessions; the current forming session is never stored (callers overlay the live price). `@daily_cached`, so within a long-lived process it resolves once per symbol per day and the 15-min loop reuses it with no DB/network round trip. Replaces the old per-scan full 1y (+3mo) yfinance pulls. |
| `fundamentals.py` | Free cash flow, debt levels, dividend safety, earnings quality, and next earnings date (via yfinance) |
| `liquidity.py` | Bid/ask spread quality, open interest, and volume — filters out options that are too thinly traded to sell. The day-volume gate is **time-aware** (N19): before `liquidity.morning_volume_cutoff_et` (default 10:30 ET) `volume_gate_active()` returns False and the scan generators skip the volume check (OI + spread carry it), since day volume often hasn't printed in the first 30 minutes of RTH. |
| `sentiment.py` | Reddit/social-media sentiment scorer; returns a neutral score (50) when Reddit API credentials are absent in `.env`; integrated into the scan pipeline with a 5% weight in `scoring_weights.yaml`. The underlying `fetch_sentiment` is `@daily_cached` on the symbol (S4), so each ticker queries Reddit at most once per calendar day — the ~26 intraday scans/session reuse the first cycle's result instead of ~1,200 praw calls/day. `SentimentScorer` keeps its per-instance cache for within-scan reuse. |
| `black_scholes.py` | Black-Scholes delta computation (`bs_delta`). Pure math — no IBKR connection. Used as a fallback by `src/ibkr/market_data.py` when IBKR returns no `modelGreeks` (delayed-data paper accounts). |

---

### `src/strategies/` — Trade candidate generators

Each module takes the analytics data and generates specific trades you could place.

| File | What it generates |
|---|---|
| `covered_call.py` | Covered call candidates: for each stock you own, finds the best call strike to sell (target delta, expiry, annualized yield) |
| `cash_secured_put.py` | Cash-secured put candidates: for `would_own` stocks, finds put strikes that offer good yield without excessive assignment risk. Contract count is sized off **available cash** (`total_cash`), not margin buying power — a cash-secured put must be cash-secured; the Rules Engine then caps the *total* across all CSPs. |
| `rolling.py` | Roll candidates: for existing short options approaching expiry or breaching delta limits, suggests the best roll-forward trade. Roll credit uses a **live quote** for the current contract; if no live quote is found the candidate is skipped. |
| `buy_candidates.py` | Buy-to-own candidates: stocks from the watchlist worth buying specifically so you can sell covered calls against them. Scores each on IV rank, fundamental quality, and technical regime, then applies a score floor and count cap (`scoring_weights.yaml → buy_to_own.min_score` / `max_candidates`) so it surfaces only the strongest few — without the floor it returned every non-held, non-bearish universe name (e.g. 46/46 over a weekend). Also enriches each with price/IV/HV/VRP/RSI/SMA/earnings/dividend, an estimated monthly CC yield, and a deterministic rationale. |
| `_scoring.py` | Shared scoring helpers used by all strategy modules. `technical_score` aligns regime to **short** premium (we sell): BULLISH favours selling puts (CSP), BEARISH/SIDEWAYS favours selling calls (CC) — the opposite of buy-side alignment. `fundamental_score` is a quality/dividend step function. `make_candidate_id` is a deterministic, **date-free** hash of `strategy\|underlying\|right\|strike\|expiry` (the property that lets the 15-min loop dedupe via `has_active_order`). |

---

### `src/engine/` — The decision and safety layer

This is where candidates get ranked and filtered.

| File | What it does |
|---|---|
| `scoring.py` | Normalizes raw analytics scores (IV rank, RSI, etc.) into a 0–100 scale |
| `decision_engine.py` | Combines scores with the configured weights, ranks candidates by total score, and selects the top N |
| `risk_engine.py` | **The safety gate.** Checks hard limits and returns PASS/REJECT with reasons. No AI. `validate_candidates` is **portfolio-aware**: it walks the ranked batch in priority order and enforces *cumulative* limits — per-ticker concentration, per-sector concentration (via the `sectors:` map in `universe.yaml`), total cash-secured-put collateral (`max_csp_allocation_pct`), and the buying-power buffer — so multiple candidates can't each claim the whole account. It also gates per candidate: ROC/yield minimums, IV-rank floor (when known), DTE window, delta (required for income strategies), and the earnings blackout. `validate_live_quote` is the second pass at execution time, re-checking a single candidate against the fresh live quote (delta drift / collapsed mid). |

---

### `src/claude/` — The AI review layer

Invokes Claude to add plain-English reasoning to the top candidates.

| File | What it does |
|---|---|
| `runner.py` | Dispatches `review_candidates`, `review_roll`, and `write_journal_narrative` to a backend chosen by `config/settings.yaml → claude.backend`. **`"cli"`** (code default): shells out to `claude -p`, passing candidate data as JSON. `_build_cmd` assembles the **hardened** command (N3): `--max-turns 1`, `--disallowedTools <denylist>`, optional `--model` pin — so the unattended subprocess (~26+×/day) can't use tools or touch the filesystem. **`"ollama"`** (**active in this deployment** — no `claude -p` access): delegates entirely to `ollama_runner.py` (local `qwen3:14b`). **`"cli_then_ollama"`**: tries `claude -p` first and falls back to `ollama_runner.py` if it returns nothing (CLI unavailable, timed out, unparseable, or — relevant after the June 2026 Agent SDK credit split — the monthly `claude -p` credit pool is exhausted). `review_candidates` also forwards the scan's `MarketConditions` (VIX) and scan-time `spot_prices` (N17) so the prompt carries the macro-vol regime and *current* price levels — enrichment only, never a deterministic gate. |
| `ollama_runner.py` | Local-LLM backend mirroring `runner.py`'s three functions (plus `propose_skill`, see `proposer.py` below) against a local `ollama serve` instance (`POST /api/generate`, `format: "json"` for grammar-constrained JSON output, `temperature: 0.2`, `num_ctx: 8192` since the strategist prompt — universe context + history + active skills — can exceed Ollama's 4096 default, `think: false` to disable hybrid-reasoning models' (e.g. `qwen3`) `<think>` traces, which otherwise fight the JSON-format constraint and bloat latency). Reuses the same prompt builders as the CLI path — including `render_active_skills()` — so promoted skills are injected identically regardless of backend. Any failure (connection refused, timeout, invalid JSON, schema mismatch) returns the same fail-soft `[]`/`None` as the CLI path. |
| `parser.py` | Validates and parses Claude's JSON response into a structured `ClaudeReview` object. On any failure, returns an empty result — the pipeline always continues. Also provides `parse_ollama_review_output` / `parse_ollama_roll_output` / `parse_ollama_journal_output` / `parse_ollama_skill_proposal`, which run the same `ClaudeReview`/`RollReview`/`SkillProposal` validation against Ollama's `format: "json"` response text (no CLI envelope to unwrap). |
| `memory.py` | The learning-loop outcome recorder. Back-fills each `claude_memory` row with what actually happened — `filled` (executor), `user_rejected` (Telegram reject), `risk_rejected` (re-validation), `expired` (TTL) — so later scans inject real outcomes (not just rejections) into the strategist prompt. |
| `prompts/` | Prompt templates: `strategist.py` (candidate review — injects `_UNIVERSE_CONTEXT`, a compact tier/IV/assignment reference for every ticker in the universe, now banner-flagged as **stale Jun-2026 anchors**; injects a **scan-time spot-price block** (N17) marked authoritative so Claude reasons from current levels; also renders a VIX regime line, each candidate's VRP, and any **active reasoning skills**), `roll.py` (roll alerts — also injects active skills), `eod.py` (EOD journal) |

**Important:** Claude is enrichment only. If it is unavailable or returns bad output, the system
sends the Rules-Engine-approved list to Telegram without Claude commentary. Claude never places,
sizes, or gates orders.

---

### `src/claude/eval/` — The verdict learning loop

Turns Claude's reviews into labeled history and scores them. Read-only with respect to trading:
nothing here can place, size, or gate an order — it only observes and measures.

| File | What it does |
|---|---|
| `ledger.py` | The **outcome ledger**. Maps `VerdictLedgerRow` ↔ `VerdictRecord` so the rest of the loop works in schemas, not ORM. At scan time it stores one row per surfaced candidate: the full signal vector Claude saw, its verdict, and the deterministic baseline. Upserts on `candidate_id` and never clobbers a recorded outcome. **Once an order exists for the candidate** (`_candidate_is_committed`), the pre-outcome signal vector is frozen too (N2b), so the row that receives the realized outcome carries the signals of the scan that produced the fill — not a later re-scan's. |
| `baseline.py` | The **deterministic counterfactual** — what the engine would do without Claude. Pure Python over the engine's own slate: every surfaced candidate is a `sell` ranked by `blended_score`; anything not surfaced is `skip`. No LLM, no new tunables. |
| `reconcile.py` | The **close reconciler**. Deterministic, DB-only: joins the ledger against fills/orders/approvals to set the terminal outcome (`expired_worthless` / `closed_early` / `assigned` / `not_filled` / `user_rejected` / `risk_rejected`) and realized P&L. Runs automatically at EOD and via `scripts.reconcile_outcomes`. |
| `assignment.py` | **Assignment auto-detection** (Phase 4): `detect_assignments` is a pure function that diffs the prior day's position snapshot against current positions — a vanished short whose underlying stock moved ~100×contracts in the assignment direction (puts → shares appear, calls → shares called away) is `assigned`, not `expired_worthless`. `assigned_candidate_ids` is the DB-backed orchestration the EOD run feeds into `reconcile(assigned_candidate_ids=…)`, replacing the manual `--assigned` flag. Enrichment-input only — never touches the engine or sizing. |
| `metrics.py` | **Verdict scoring**: calibration (reliability buckets + Brier score) and EV of *following Claude* vs *the baseline*, on a held-out window and per month — so the score reflects skill, not the last trade's luck. |
| `score_metrics.py` | **Score-vs-outcome analysis** (N22): over closed ledger rows, buckets `blended_score` (and each scorecard component) by realized win rate / mean P&L, plus a per-signal Pearson correlation. Read-only evidence for whether the *human-edited* `scoring_weights.yaml` is earning its keep — it never feeds the engine (the fence). Driven by `scripts/evaluate_scores.py`. |

### `src/claude/skills/` — The skill loop

Claude proposes reasoning playbooks from the labeled ledger; a human promotes them; promoted
skills are injected into the strategist/roll prompts. Skills shape **verdict and ranking only** —
never gates, weights, or sizing (see *Key invariants → the fence*).

| File | What it does |
|---|---|
| `registry.py` | Loads/saves/promotes/rejects skill files under `config/skills/{active,proposed,rejected}` and renders the active set for prompt injection. `render_active_skills()` is the **single, auditable path** a skill reaches Claude — imported only by the prompt builders. |
| `proposer.py` | Builds a prompt from the labeled ledger + current evaluation + active skills and drafts one new/refined skill into `proposed/`. Dispatches on `config/settings.yaml → claude.backend` like `runner.py`: `"cli"` shells `claude -p`, **`"ollama"` (active in this deployment) delegates to `ollama_runner.propose_skill`**, `"cli_then_ollama"` tries the CLI then falls back to Ollama. Fail-soft like the runner. Never auto-promotes. |

---

### `src/execution/` — Order placement

Handles everything between your Telegram approval and the order reaching IBKR.

| File | What it does |
|---|---|
| `order_builder.py` | Builds the IBKR order objects (never market orders). `build_limit_order`: a single-leg mid-price SELL, rounded to the penny-pilot tick ($0.01 below $3.00, $0.05 at/above). `build_combo_roll_order`: a two-leg **BAG combo** (BUY-to-close old short + SELL-to-open new short) priced at the net — a credit roll is a *negative* net-debit limit (`lmtPrice = -net_credit`). `reprice_limit`: pure chase-price helper — steps a resting limit a fraction toward the bid (SELL) or ask (BUY), tick-rounded and guarded by a floor/ceiling. |
| `executor.py` | Places single-leg orders via IBKR, monitors for a fill, handles timeouts and cancellations, records the fill (with entry IV) and the `filled` learning-loop outcome. A `ROLL` candidate is delegated to `roll_executor.execute_roll` (never sent down the single-leg/naked-SELL path). When `execution.reprice_enabled` is set, the fill-wait loop chases an unfilled SELL down toward the bid (via `reprice_limit`) up to `max_reprices` times — never below `min_live_premium_ratio × approved premium` — before cancelling on timeout. Each chase step **re-fetches the live bid/ask** (`_refetch_bid_ask`, N11) so it moves toward the current market, not the quote captured at placement. |
| `roll_pipeline.py` | **Wires rolls end-to-end** (N20): `queue_roll_for_approval` takes a triggered short + a fresh chain, calls `generate_roll_candidates`, persists the best as a `CandidateRow`, and raises a PENDING `ApprovalRow` (frozen snapshot, N2a). Approve then creates a QUEUED ROLL `OrderRow` → `process_queued_orders` → `execute_candidate` → `execute_roll`. Called from the monitor's `fire_alerts` only when `monitor.roll_execution_enabled` is set (default OFF, pending live BAG-sign verification); otherwise rolls stay alert-only. `validate_candidates` treats ROLL as exposure-neutral so the queue re-gate doesn't double-count the replaced leg. |
| `roll_executor.py` | Executes a `Strategy.ROLL` candidate as one atomic BAG combo. Resolves the existing short to buy back from live positions (the roll candidate only carries the new leg), fetches fresh quotes + qualified conIds for both legs, re-gates the new leg via `validate_live_quote` (delta + live-greeks-in-LIVE) plus a **net-credit floor** (`min_live_premium_ratio`; rejects debit rolls), requires a LIVE-mode [CONFIRM LIVE] tap, places the combo, cancels on timeout, and records two FillRows — a BUY under the *original short's* `candidate_id` (so the ledger labels it `closed_early` and EOD cashflow sees the debit) and a SELL under the new candidate's id (so the monitor tracks the new short with entry IV). The combo's sign convention is mock-tested only and is on the STATUS.md live-verification list. |
| `approval.py` | Picks up QUEUED orders → re-validates against the Rules Engine (batched, cumulative-aware) → hands off to executor. `_load_candidate` executes the **frozen approved snapshot** on the OrderRow (N2a), never the latest `CandidateRow` payload, so a 15-min re-scan that mutated `contracts`/`premium` between approval and execution can't change the size the human approved (legacy snapshot-less rows fall back to `CandidateRow`). |
| `profit_take.py` | **Profit-take orchestration** (extracted from the notify layer, N23): `check_profit_takes` loads short positions, computes each one's net entry credit (`net_entry_credit_per_share`, qty-weighted SELL fills less commission), polls a live quote for the cost-to-close, and — at the 50% threshold — either auto-buys-to-close (AUTO mode, via `position_manager`) or sends a profit alert. Telegram sends go through the passed `bot`, so the trading logic no longer lives in `notify/`. The intraday loop calls it; `approval_service` re-exports it for back-compat. |
| `position_manager.py` | Buy-to-close execution for short option positions (profit-take auto-closes). Routes the close through the same `OrderRow`/`FillRow` lifecycle and cancel-on-timeout discipline as entries, and is idempotent at the contract level (a deterministic `close:` candidate id + `has_active_order`) so the next intraday cycle can't stack a second buy-to-close. Buy-to-close is risk-reducing, so it deliberately skips the income Rules Engine gate but still records the order/fill. `_auto_close_position` in `notify/` is now just the Telegram-notification wrapper around `close_short_position`. |
| `circuit_breakers.py` | AUTOMATED-mode safety breakers (the risk gate bounds *exposure*; these bound *activity + losses*). `remaining_entry_allowance` enforces `max_auto_trades_per_day`; `daily_loss_breached` auto-engages the kill switch on a daily realized-loss breach. Read-only except for tripping the persisted halt — never feeds the risk engine, scoring, or sizing. Consumed by `process_queued_orders`. |
| `reconciliation.py` | Broker ↔ DB recovery, extracted from the notify layer. `recover_orphan_orders` resets SUBMITTED rows with no `ib_order_id` (crash before `placeOrder`) back to QUEUED; `reconcile_orphan_fills` back-fills FillRows for orders whose fill event was lost, matching `reqExecutions` by broker order id then contract — covering SUBMITTED rows **and** REJECTED/CANCELLED rows that still carry an `ib_order_id` (N8: the executor's except path marks an order REJECTED when its monitor loop throws, but the SELL may already have filled; pre-placement cancels have no `ib_order_id` and are ignored); `reconcile_external_closes` records *manual* buy-to-closes done in TWS as BUY FillRows attributed to the original short's `candidate_id` (idempotent on IBKR `execId`), so the verdict ledger labels the position `closed_early` rather than `expired_worthless` and EOD cashflow includes the debit (SYSTEM_REVIEW F7). All three are strictly additive (record only proven broker state; never cancel/resubmit) and run at startup **and** periodically from the intraday loop, so fills/closes landing mid-session are recovered on the next cycle, not only on the next restart. |

---

### `src/notify/` — Telegram messaging

| File | What it does |
|---|---|
| `sender.py` | Stateless message sender: sends text and formatted messages to your Telegram (used by the scan pipeline and EOD report). **Per-thread routing:** each send function takes a caller-provided `thread_id` int (or None) so CC candidates, CSP candidates, buy-to-own, and account snapshots each land in their own Telegram forum topic. `thread_id(raw: str) -> int | None` parses config strings. **Always-send-something rule:** an empty candidate list sends a `format_screen_empty` diagnostic rather than being silently dropped (troubleshooting signal). **Output-frequency suppression (S6):** `send_candidates` takes required kwargs `thread_id`, `label`, `icon`, `hash_key`, `time_key` plus optional `empty_reason`/`noun`/`suppress_unchanged`. When `suppress_unchanged=True` it first checks the screen-level content hash (`_screen_hash` over `(candidate_id, score-band)` tuples, stored in `system_settings` under `hash_key`/`time_key`); if the hash matches and every candidate already has a live same-band PENDING approval, a single `format_screen_unchanged` message is sent (one compact digest for the whole screen). A full send stores the new hash and timestamp. `send_buy_list` routes to `telegram_thread_buy` and uses `_screen_hash` over `(symbol, score-band)`, stored in `last_buy_list_hash`/`last_buy_list_time`. **`send_account_snapshot(account, positions)`** sends an account snapshot to `telegram_thread_account`: on the first call each ET calendar day it sends a new message and stores the `message_id` in `account_snapshot_message_id` and the date in `account_snapshot_date`; on subsequent same-day calls it edits that message in place (updating the "last updated HH:MM" footer), so the thread stays tidy. If the stored message can't be edited (deleted, >48h) it falls back to a fresh send. Best-effort: never raises. |
| `approval_service.py` | The long-running daemon: runs the Telegram polling loop, handles Approve/Reject callbacks, drives order execution, serves all interactive commands, and runs the 15-minute intraday scan + profit-take loop during RTH. The profit-take *trading logic* now lives in `execution/profit_take.py` (N23) — the daemon just drives the loop and re-exports it. **Overrun observability (S9):** when an intraday cycle is lost to an overrun (the prior scan still running) or scan-lease contention, `_note_intraday_skip` increments a per-session skipped counter and sends a throttled (≤ once/30 min) Telegram warning (routed to `telegram_thread_scan`); successful cycles increment a run counter. Both counters live in `bot_data` and are surfaced in `/status`. The scan-started ping (`🔄 Scan started · HH:MM ET`) and startup notification also route to `telegram_thread_scan`. **Premarket snapshot loop:** `_premarket_snapshot_loop` is a background task (started alongside the intraday loop when `ib_scan` is available) that sleeps until 09:00 ET each trading day, then calls `send_account_snapshot` to post the day's first account snapshot to `telegram_thread_account` (topic 58) before market open; subsequent same-day intraday-loop calls edit that message in place. |
| `formatters.py` | Converts all data types into MarkdownV2 messages. Covers: trade candidates (with VRP displayed), positions, account, health, status, startup, EOD report, fill confirmations (`format_fill_confirm`), roll combo fill confirmations (`format_roll_fill_confirm`), live-order confirmation requests (`format_live_confirm_request`), roll alerts (`format_roll_alert`), pending approvals list (`format_pending_approvals`), fills history (`format_fills_history`), trading mode status (`format_mode_status`), auto-trade summary (`format_auto_trade_notification`), profit alerts (`format_profit_alert`), auto-close results (`format_auto_close_result`), buy-to-own screen (`format_buy_list` — a per-name card with price, IV-rank/IV-vs-HV/VRP premium richness, trend + RSI, estimated monthly CC yield, earnings/dividend notes, and a deterministic rationale), and the S6 suppression digests (`format_unchanged_cards_digest` — a compact list of still-pending unchanged CC/CSP candidates with "since HH:MM"; `format_quiet_cycle` — the intraday quiet-cycle heartbeat: a compact "🟰 Quiet cycle · HH:MM ET" message sent when a 15-min cycle surfaces nothing at all, stating how many names moved below the materiality threshold and that the chain re-fetch + Claude were skipped, so silence ≠ dead daemon). `format_status` takes optional `scans_run`/`scans_skipped` counters (S9) and renders a 🔁 run · ⚠️ skipped line when provided. `format_data_provenance` — the end-of-scan "📊 Data sources this scan" summary sent after a full sweep (`/scan`): option-chain fetch counts (IBKR ok/failed/skipped), spot-price source split (IBKR chain parity vs. yfinance vs. unavailable), VIX availability, and the IBKR-vs-Black-Scholes split of option Greeks. **Telegram multi-thread routing formatters:** `format_screen_unchanged(icon, label, count, since, noun)` — generic "N {noun}(s) unchanged since HH:MM" digest, used by the buy-to-own, CC, and CSP per-thread screens (replaces the old `format_buy_list_digest`); `format_screen_empty(icon, label, reason)` — "no candidates this cycle" diagnostic with a reason line, the "always send something" troubleshooting signal for empty screens; `format_account_snapshot(account, positions, updated_at)` — the per-thread account snapshot: net liq + total unrealized P&L $/%, a *Stocks* section (each holding with any covered calls sold against it nested below via `└ `), and a *Cash-Secured Puts* section for standalone short puts (omitted if none); each position shows its unrealized P&L % (`unrealized_pnl / abs(avg_cost * position * multiplier)`, multiplier=100 for options, "N/A" if cost basis is zero), with a "Source: IBKR · last updated HH:MM" footer. **Per-message data-source footers:** every trading-data message now ends with a `_Sources: …_` line identifying which systems contributed: CC/CSP candidate cards use `_candidate_sources(c)` (derives "IBKR option chain" always, plus "yfinance spot/Greeks (fallback)" when `c.price_source == "yfinance"` or `c.greeks_source != "ibkr"`); buy-to-own always shows "yfinance (prices · IV · technicals · fundamentals) · IBKR (IV rank history)"; account snapshot shows "Source: IBKR"; auto-trade notifications aggregate sources across all queued candidates; roll alerts and EOD summaries show "Source: IBKR"; quiet-cycle heartbeats show "IBKR (price moves)" plus "yfinance (VIX)" when VIX was available. |

**Telegram commands served by `approval_service.py`:**

| Command | What it does |
|---|---|
| `/scan` | Run a full on-demand pipeline scan (CC/CSP/buy opportunities) |
| `/mode` | Show current trading mode (👤 MANUAL / 🤖 AUTOMATED) and toggle. Confirmation prompt appears before enabling AUTOMATED. Mode persists across restarts in SQLite. |
| `/halt` | 🛑 Master kill switch: immediately stop queuing/transmitting all orders. Profit-take *closes* still run (risk-reducing). Persisted in SQLite, so it survives a restart and must be lifted with `/resume`. Optional free-text reason. |
| `/resume` | Release the kill switch; QUEUED orders resume on the next poll cycle. |
| `/status` | Compact overview: account + active short options + pending approvals, plus the per-session intraday-scan tally (🔁 N run · ⚠️ M skipped) so intended (~26/session) vs actual scan count is visible (S9). Shows a 🛑 HALTED banner when the kill switch is engaged. |
| `/positions` | Show live portfolio positions (stocks + options) with P&L |
| `/account` | Show account balances: net liquidation, buying power, margin, excess liquidity |
| `/pending` | List all pending approvals with score and time-to-expiry |
| `/fills` | Recent fills from the last 7 days with quantity, price, and credit received |
| `/expire` | Expire all pending approvals (clears the queue without acting on them) |
| `/health` | System health check: IBKR connection status, DB, last scan time, open orders |
| `/help` | List all available commands |
| `✅ Approve` / `❌ Reject` inline buttons | Tap to approve or reject each trade candidate (MANUAL mode only; AUTOMATED mode skips these) |
| `[CONFIRM LIVE]` inline button | Second-confirmation tap required for each order when `LIVE_TRADING=true`. Appears as an inline keyboard button on the pre-execution message; times out after `fill_timeout_minutes` if not tapped. |

---

### `src/monitor/` — Intraday position watching

Watches your open positions during market hours and fires alerts when action may be needed.

| File | What it does |
|---|---|
| `intraday.py` | Subscribes to live IBKR price feeds for each open position; runs checks every tick. On subscribe it loads each position's **entry IV** (from the originating fill's `FillRow.entry_iv`, matched by contract) as the IV-spike baseline, and caches the underlying's **fundamentals** (ex-dividend date) — so all four triggers can actually fire. `fire_alerts` sends the roll alert; when `monitor.roll_execution_enabled` is set it first fetches the chain and queues an **approvable** roll candidate (N20, via `execution.roll_pipeline`) so the message carries Approve/Reject buttons instead of being alert-only. |
| `triggers.py` | Defines stateless trigger-check functions: delta drift, DTE threshold, IV spike, ex-dividend risk. These are pure functions — they do **not** call Claude or Telegram. Claude review and Telegram delivery are handled by `intraday.py::fire_alerts` after triggers fire. |

---

### `src/backtest/` — Offline income backtest

A standalone, deterministic simulator for the CC/CSP income strategies. It is **fully isolated
from the live path** — it imports nothing from `engine/` or `execution/` and is never imported by
them — so it can never influence a real order. **v1** synthesises premiums with Black-Scholes from
trailing realised vol (a fair-value IV proxy → expected edge ≈ 0 by construction). **v2 (N21)**
prices the entry premium from the symbol's *stored* daily IV (`iv_history`), so the result actually
measures the variance-risk premium (IV−HV); it also simulates the 50% profit-take and IV-rank
gating. Use it to compare parameter choices, not as tick-accurate truth.

| File | What it does |
|---|---|
| `engine.py` | The pure core. `simulate(symbol, prices, params, *, iv_series=None)` walks a daily-close series, writes non-overlapping short-premium cycles, settles each cash-style at expiry, and returns a `BacktestResult`. With `iv_series` it prices entries at the stored IV (measuring VRP) and reports `mean_vrp_pct` + `iv_source`; `params.profit_take_pct` closes a cycle early when its daily mark decays to the take level (`profit_take_rate`); `params.min_iv_rank` only opens cycles whose backtest IV rank clears the bar. Takes in-memory series → unit-testable offline. |
| `data.py` | yfinance loader (`load_price_series`) plus `load_iv_series` — the forward-filled `iv_history` IV aligned to the price dates (the v2 entry-IV source). Kept out of `engine.py` so the core needs no network/DB. |
| `report.py` | `format_report` — plain-text rendering of a `BacktestResult` for the CLI (now incl. pricing-IV source, mean VRP, and profit-take rate). |

Driven by `scripts/backtest.py` (`--use-stored-iv`, `--profit-take`, `--min-iv-rank` enable v2). The
Black-Scholes price (`analytics.black_scholes.bs_price`) was added for this harness;
`analytics.black_scholes.bs_delta` is reused to delta-target strikes.

---

### `src/orchestrator/` — Daily workflows

Ties everything together into the daily automated routines.

| File | What it does |
|---|---|
| `eod_report.py` | Run by cron at 4:15 PM ET. Pulls the day's **option premium cashflow** (SELL credits − BUY debits — surfaced as "premium cashflow", not a paired realized P&L; assignment stock-leg P&L is excluded, N13), generates a journal entry via Claude, sends an end-of-day summary to the **account snapshot thread** (thread 58). Also appends today's ATM IV observation per universe symbol (N4, `_append_daily_iv`) so the IV-rank window stays current, and reconciles the verdict ledger + saves the position snapshot. |
| `scan.py` | The canonical scan pipeline shared by the 15-min daemon loop and the on-demand `/scan` Telegram command. Claude-memory injection is bounded (N9): `_load_memory` keeps at most `_MEMORY_ROWS_PER_SYMBOL` (3) rows per symbol, outcomes first; `_persist_memory` upserts one `claude_memory` row per (symbol, strategy, day) instead of inserting one per surfaced candidate per 15-min cycle. Interactive `/scan` progress is driven by `_Tracker`, which edits **two** Telegram messages in place: a *checklist* (one line per stage — account, market data, scoring, Claude, notify) and a *dashboard* (a progress bar + ETA, a current-activity line, and a running log of per-symbol errors flagged 🔴). The dashboard's per-symbol updates are throttled (`_DASHBOARD_MIN_INTERVAL`) to stay under Telegram's edit-rate limits; stage changes, errors, and completion always flush. The 15-min daemon loop runs the scan with both callbacks `None` (silent) and `intraday=True`, which enables the **S1 materiality gate**: `_compute_material_symbols` restricts the per-symbol option-chain fetch to held positions, `would_own` names whose live spot moved past `intraday_rescan_move_pct`, and names that cleared the score floor last cycle (plus a `force_full_scan_minutes` safety sweep); immaterial names are skipped this cycle (analytics still run, so the buy-to-own list stays complete). Fetched chains are persisted via `persist_chain_quotes` (S10) and each fetched symbol's `scan_state` baseline is upserted after scoring. In `intraday` mode it also enables the **S5 LLM-skip**: `_candidates_review_hash` hashes the top candidates' `candidate_id` + signal vectors, and when that matches the prior cycle's hash (stored in the `last_review_hash` system setting) the `claude -p` review is skipped and the persisted `ClaudeReview`s are reused via `_load_prior_reviews` — enrichment-only, the risk gate already ran, so this never affects gating (the fence). Manual `/scan` leaves `intraday=False` and always sweeps the full universe, reviews fresh, and sends in full. A full sweep also tallies `ScanResult.provenance` (a `ProvenanceCounts`) — per-symbol option-chain success/failure/skip, which source produced each symbol's spot price (IBKR chain parity vs. yfinance), VIX availability, and the IBKR-vs-Black-Scholes split of option Greeks — and sends it as a final `format_data_provenance` Telegram message once the scan completes, so an operator can see at a glance which data sources were live this run. |

---

### `src/storage/` — The database

All data is stored in a SQLite database at `data/income_system.db`.

| File | What it does |
|---|---|
| `db.py` | Database connection and session management via SQLAlchemy. For SQLite it enables WAL mode + a 30 s busy-timeout (so the concurrent processes don't hit "database is locked"), applies a lightweight ALTER-in for columns added after the original schema, and creates partial indexes that the model metadata can't express portably (e.g. `uq_orders_active_candidate` — one working order per candidate). |
| `models.py` | Defines the database tables: `candidates`, `risk_verdicts`, `claude_reviews`, `approvals`, `orders`, `fills`, `iv_history`, `price_history`, `option_quotes`, `scan_state`, `position_snapshots`, `roll_alerts`, `claude_memory`, `verdict_ledger`, `journal`, `system_settings`. `scan_state` (unique per `symbol`) is the S1 intraday-materiality store: one row per symbol holding `last_spot` + `last_scanned_at` (at its last option-chain fetch) and a `cleared_floor` flag, upserted for every fetched symbol so the 15-min loop can decide which chains to re-fetch and which to skip. `price_history` (unique per `symbol`+`obs_date`) stores settled daily OHLCV bars backing the technical indicators and HV30, so scans read history from SQLite and only fetch the missing tail from yfinance. `position_snapshots` (unique per `snapshot_date`) holds the daily portfolio JSON the EOD run writes for assignment auto-detection (position diffing). The `fills` row records `action` (SELL credit / BUY debit) and `entry_iv`. `approvals` and `orders` each carry a `snapshot` JSON column — the frozen `TradeCandidate` payload at approval time (N2a) — so execution runs exactly the size/premium that was approved, immune to re-scan payload drift. `verdict_ledger` (the **outcome ledger**) stores, per Claude-reviewed candidate, the signal vector Claude saw + its verdict + the deterministic baseline, with the realized trade outcome back-filled on close (unique on `candidate_id`, upserted per scan). `system_settings` is a key-value table for runtime toggles and state (`automated_mode`, the `execution_halted` kill switch + its reason, the `scan_lease_expiry` cross-process scan lease, the S1/S6 intraday-suppression keys `last_buy_list_hash`/`last_buy_list_time`/`last_cc_hash`/`last_cc_time`/`last_csp_hash`/`last_csp_time`/`last_candidates_hash`/`last_candidates_time`/`last_review_hash`, and the account-snapshot edit-in-place state `account_snapshot_message_id`/`account_snapshot_date`). `candidates`, `orders`, and `journal` carry unique constraints to prevent duplicate rows. |
| `system_settings.py` | Helper functions for the `system_settings` table: `is_automated_mode()`/`set_automated_mode()`, the kill switch (`is_halted()`/`set_halted()`/`get_halt_reason()`), the cross-process scan lease (`acquire_scan_lease()`/`renew_scan_lease()`/`release_scan_lease()` — serialises full scans so concurrent `/scan` commands can't compete for the market-data line cap, F5), and `get_setting()`/`set_setting()`. The lease is **owner-token + heartbeat** (N7): `acquire` returns a stable token; the scan loop calls `renew` each symbol to extend the TTL so a long ~60-symbol scan can't expire mid-run; and `renew`/`release` are compare-and-swap, so a scan that overran and was re-claimed can't clobber the new holder. All persist across restarts. |
| `orders.py` | Order-creation idempotency: `has_active_order(session, candidate_id)`. Because `candidate_id` is a deterministic hash, a re-scan (especially the 15-min automated loop) regenerates the same candidate; both order-creation paths (`sender._auto_queue_candidates`, `approval_service._process_button`) consult this guard so a candidate with an order already QUEUED/SUBMITTED/FILLED/PARTIAL is not re-queued — preventing stacked duplicate positions (naked short calls for CCs, which bypass the cumulative exposure gates). A partial unique index `uq_orders_active_candidate` (created in `db.py`) is the DB-level backstop: at most one order in a *working* state (queued/submitted) per candidate. |
| `maintenance.py` | Periodic DB upkeep, both called from the EOD run. `purge_old_option_quotes(retention_days=14)` deletes stale rows from the write-only `option_quotes` audit table so SQLite stays bounded under the 15-min loop's write volume. `backup_database(keep=7)` takes a consistent online snapshot (SQLite backup API) into `data/backups/` and rotates to the last 7 — the system of record (orders, fills, learning history) is no longer a single point of failure. |
| `positions.py` | Daily position-snapshot persistence for assignment auto-detection. `save_position_snapshot(date, positions)` upserts one JSON row per ET day (written by the EOD run); `load_latest_position_snapshot(before=…)` returns the most recent prior snapshot to diff against. |
| `scan_state.py` | Per-symbol intraday-scan materiality state (S1/S10). `get_scan_state(symbols)` returns each symbol's `last_spot`/`last_scanned_at`/`cleared_floor`; `upsert_scan_state(symbol, …)` writes the baseline for a fetched symbol. The 15-min loop reads this to gate the (expensive) option-chain fetch; the first intraday cycle sweeps all symbols and writes baselines for every one. All failures are swallowed — it is an optimisation, never a correctness dependency (a read miss degrades to "treat as material"). |
| `iv_history.py` | Accessors for the `iv_history` table (N4): `latest_iv` (most recent IV, used by the IV-scaled strike band), `append_observation` (idempotent daily insert, called from the EOD run so the IV-rank window stays current), and `latest_obs_dates`/`stale_symbols` (powering the `/health` staleness warning). All swallow storage errors — derived data must never take the pipeline down. |
| `price_history.py` | Accessors for the `price_history` table: `load_bars` (settled OHLCV, ascending), `latest_bar_date`, and `append_bars` (idempotent — skips dates already stored). Source for `analytics/price_data.get_ohlcv`; same error-swallowing discipline as `iv_history.py`. |

Every stage of the pipeline writes its results here. This means:
- If a scan crashes halfway through, the next run can pick up where it left off.
- The dashboard reads from this database — no IBKR connection needed.
- You can inspect any trade decision by querying the database.

---

### `src/common/` — Shared building blocks

| File | What it does |
|---|---|
| `schemas.py` | Pydantic data models that all modules use to pass data between each other (`TradeCandidate`, `PositionSnapshot`, `ScoreCard`, `RiskVerdict`, `ClaudeReview`, etc.). The enrichment-evaluation shapes also live here: `VerdictOutcome`, `BaselineDecision`, `VerdictRecord` (one ledger entry), `CalibrationBucket`/`PolicyStats`/`VerdictEvaluation` (verdict scoring), `ScoreBucket`/`SignalCorrelation`/`ScoreOutcomeReport` (score-vs-outcome analysis, N22), and `SkillProposal`. |
| `config.py` | Loads and validates `config/*.yaml` and `.env` |
| `logging.py` | Structured logging setup — colourised console output (green INFO, yellow WARNING, red ERROR) and a plain rotating file log; `setup_logging()` is the single call-site used by all entry points. A `_NoiseFilter` on both handlers truncates oversized `ib_async.wrapper` error strings and collapses runs of near-identical messages (e.g. repeated "Can't find EId with tickerId:..." per option contract during `/scan`) to the first few occurrences plus a "(suppressed N further repeats)" summary, so a chain scan doesn't produce multi-MB logs. |
| `market_hours.py` | Self-contained US equity-market calendar + RTH gate (`is_rth`, `is_new_entry_window`, `session_close`, `is_market_holiday`, `is_early_close`, `seconds_until_next_aligned_mark`, `seconds_until_time`, `now_et_hhmm`). Computes NYSE full-day holidays and the 13:00 ET early-close sessions for any year — no external calendar dependency. The single source of truth for "is the market open"; both the execution bridge and the intraday loop call it instead of keeping their own weekday-only check. `is_new_entry_window` additionally enforces the configurable `entry_cutoff` time (default 15:00 ET) so no new positions are surfaced in the last hour. `seconds_until_next_aligned_mark(interval_minutes)` returns the ET wall-clock delay until the next `:00`/`:15`/`:30`/`:45`-style mark, used by the intraday loop so its cycles land on 9:30, 9:45, 10:00, ... instead of drifting with process restarts. `seconds_until_time(hh, mm)` returns the ET wall-clock delay until the next occurrence of a specific HH:MM (today if still ahead, else tomorrow) — used by the premarket snapshot loop to fire at 09:00 ET daily. `now_et_hhmm()` returns the current time as `"HH:MM ET"`, shared by the scan-started message and the quiet-cycle heartbeat. |
| `cache.py` | `@daily_cached` — a thread-safe, process-local memoizer keyed by `(args, today)`. Wraps the yfinance hot paths (`get_fundamental_stats`, `_compute_hv30`, `price_data.get_ohlcv`, and `sentiment.fetch_sentiment`) so the 15-min intraday loop fetches each symbol at most once per calendar day. `clear_all()` is called by the test harness between cases. |

**Rule:** Modules never pass raw IBKR objects to each other — they always convert to these shared
schemas first. This keeps modules independent and testable.

---

### `Archive/dashboard/` — The Streamlit web dashboard (archived)

The Streamlit dashboard has been moved to `Archive/dashboard/`. To reinstate it, move the
folder back to `dashboard/` at the project root and run `streamlit run dashboard/app.py`.

| Page | What it shows |
|---|---|
| `01_portfolio.py` | Current positions, Greeks, P&L |
| `02_candidates.py` | Today's top trade candidates and their scores |
| `03_orders.py` | Order history, pending orders, fill records |
| `04_journal.py` | Claude-written daily journal entries |
| `05_iv_conditions.py` | IV rank/percentile charts for your universe |

The dashboard never connects to IBKR directly — it reads entirely from the SQLite database.

---

### `scripts/` — Command-line entrypoints

These are the scripts you run directly:

| Script | How to run | What it does |
|---|---|---|
| `healthcheck.py` | `python -m scripts.healthcheck` | Verifies IBKR connection and prints account summary |
| `start.py` | `python -m scripts.start` | **Single-command launcher**: starts both always-on daemons (approval service + monitor) as supervised subprocesses with auto-restart on crash. Accepts `--no-monitor` / `--no-approval` flags. Does NOT start the cron jobs. |
| `run_eod.py` | `python -m scripts.run_eod` | Runs the EOD report (also called by cron) |
| `run_approval_service.py` | `python -m scripts.run_approval_service` | Starts the long-running approval + execution daemon |
| `run_monitor.py` | `python -m scripts.run_monitor` | Starts the intraday position monitor |
| `backfill_iv.py` | `python -m scripts.backfill_iv` | One-time: seeds one year of IV history for the universe |
| `backfill_prices.py` | `python -m scripts.backfill_prices` | One-time: seeds ~1y of daily OHLCV into `price_history` so the first scan reads from SQLite instead of pulling full histories from yfinance. Safe to re-run (only the missing tail is fetched). |
| `reconcile_outcomes.py` | `python -m scripts.reconcile_outcomes` | Reconcile the outcome ledger (deterministic, DB-only). `--assigned <id…>` flags past-expiry shorts that were assigned. Also runs automatically at EOD. |
| `evaluate_verdicts.py` | `python -m scripts.evaluate_verdicts` | Score Claude's verdicts: calibration + EV vs the baseline, held-out + per month. Read-only. `--since`, `--until`, `--json`. |
| `evaluate_scores.py` | `python -m scripts.evaluate_scores` | Score-vs-outcome report (N22): `blended_score` + per-component bands vs realized win rate / mean P&L, plus per-signal correlation, over closed ledger rows. Read-only; informs hand-tuning of `scoring_weights.yaml`. `--since`, `--until`, `--json`. |
| `propose_skill.py` | `python -m scripts.propose_skill` | Draft a reasoning skill from the labeled ledger via `claude -p` into `config/skills/proposed/`. Not promoted. |
| `skills.py` | `python -m scripts.skills <list\|show\|promote\|reject\|retire> [name]` | The human gate: review proposed skills and promote them into `active/`. |

---

### `tests/` — The test suite

Unit tests for every module. IBKR is mocked, so tests run without a live TWS connection.

Run with: `python -m pytest`

---

## Process architecture (what runs where)

The system splits into separate processes, each with its own IBKR client ID, to avoid conflicts.
The full registry lives in `config/settings.yaml → ibkr.client_ids`; **never reuse an id across two
processes that run at the same time.**

| Process | When it runs | Client ID | What it owns |
|---|---|---|---|
| `eod_report` | One-shot at 4:15 PM (cron) | 16 (`eod`) | P&L + journal → Telegram (account snapshot thread) |
| `intraday_monitor` | Always-on during market hours | 12 (`monitor`) | Live position watching + roll alerts |
| `backfill_iv` | One-time manual | 13 (`backfill`) | Historical IV data seeding |
| `backfill_prices` | One-time manual | — (no IBKR; yfinance) | Historical OHLCV seeding into `price_history` |
| `approval_service` | Always-on daemon | **14 (`exec`) + 15 (`scan`)** | Telegram callbacks + order execution (14) and a second connection for `/scan`, `/positions`, `/account`, `/status` (15) |
| `healthcheck` | Manual | 19 | Connection check / account print |
| `trading_skills` MCP | Inside `claude -p` (opt-in) | 20 | Ad-hoc Claude lookups (see `STATUS.md`) |
| dashboard | Optional Streamlit (archived to `Archive/dashboard/`) | 21 | Read-only views (reads SQLite; rarely hits TWS) |

One-shots connect, work, and disconnect; the daemons run continuously and self-heal on a dropped socket via `AutoReconnect`.

---

## Data flow between modules

All modules exchange data through the Pydantic schemas in `src/common/schemas.py`. The key objects:

| Schema | What it represents |
|---|---|
| `PositionSnapshot` | A current open position (symbol, quantity, cost basis, and `delta` when enriched) |
| `AccountSnapshot` | Account totals: net liquidation, cash, buying power, margin, excess liquidity |
| `OptionQuote` | A single option contract's live snapshot (bid/ask/last, Greeks, IV). Computed fields: `mid` (bid+ask)/2, falling back to `last`; `spread_pct` as a percentage of mid; `dte` as days-to-expiry in ET timezone. |
| `IVStats` / `TechnicalStats` / `FundamentalStats` | Per-symbol analytics outputs. `IVStats` now includes `vrp` (IV% − HV30%) computed in `iv.py`. `TechnicalStats.price_source` records whether `price` came from `"ibkr"` (chain-inferred spot) or `"yfinance"` (fast_info fallback) this scan cycle — used to build the end-of-scan data-provenance summary. |
| `MarketConditions` | Market-level signals fetched once per scan: `vix` (CBOE VIX from yfinance). Attached to `ScanResult`. |
| `ScoreCard` | All analytics scores for a symbol (IV rank, technicals, fundamentals, liquidity, assignment safety) |
| `TradeCandidate` | A specific trade proposal (symbol, strategy, strike, expiry, premium, scores, and `next_earnings` for the earnings-blackout gate). Carries `price_source` ("ibkr" \| "yfinance") and `greeks_source` ("ibkr" \| "black_scholes") propagated from the generating `TechnicalStats` and `OptionQuote` — used to render per-card data-source footers in Telegram. |
| `BuyCandidate` | A buy-to-own stock recommendation, enriched from the per-symbol analytics: `score` + sub-scores (`iv_score`/`fundamental_score`/`technical_score`), `price`, `current_iv`/`hv_30`/`vrp`, `rsi_14`/`sma_50`/`sma_200`, `next_earnings`, `dividend_yield`, and a heuristic `est_monthly_cc_yield`. The `rationale` is a deterministic one-liner built in `buy_candidates.py` (Claude does not review buy candidates — only option candidates). The screen applies a score floor + count cap (`scoring_weights.yaml → buy_to_own`), so it surfaces only the best few names rather than the whole non-held universe. |
| `RiskVerdict` | The Rules Engine's decision: PASS or REJECT, with reasons |
| `ClaudeReview` / `RollReview` | Claude's structured review of a candidate / a live position roll |
| `RollAlert` | A fired intraday trigger (delta drift, DTE, IV spike, ex-div) |
| `EODSummary` | End-of-day metrics handed to Claude and stored in the journal |
| `VerdictRecord` | One outcome-ledger entry: the signals Claude saw + its verdict + the deterministic `BaselineDecision` + the back-filled realized `VerdictOutcome`/P&L |
| `VerdictEvaluation` | Held-out scoring of verdicts: Brier calibration + `PolicyStats` for follow-Claude vs baseline |
| `ScoreBucket` / `SignalCorrelation` / `ScoreOutcomeReport` | Score-vs-outcome evidence (N22): per-band realized win rate / mean P&L and per-signal correlation against realized P&L, over closed ledger rows |
| `SkillProposal` | A Claude-drafted reasoning skill awaiting human promotion |

(The complete, authoritative list is the set of classes in `src/common/schemas.py`.)

---

## Key invariants (things that must never change)

1. **The Rules Engine is the only path to execution.** Nothing bypasses it.
2. **Claude never places, sizes, or blocks orders.** It enriches; it does not control.
3. **One IBKR client ID per process.** Sharing IDs causes connection conflicts.
4. **Secrets live only in `.env`.** Never in code, logs, or YAML.
5. **All option orders use LimitOrder at mid-price.** Never market orders.
6. **`qualifyContracts` runs before every order submission.**
7. **The fence: skills influence verdict + ranking only.** Promoted reasoning skills reach Claude
   solely through the strategist/roll prompt builders (`render_active_skills`). The risk engine,
   scoring, and sizing never import or see them — gates/weights/limits stay human-edited config.
   Enforced by `tests/test_eval_skills.py::test_skills_never_reach_the_engine`.

---

## Operational risks & how they're handled

The hard parts of this system are operational, not algorithmic. The main failure modes and their
mitigations:

| Risk | Mitigation |
|---|---|
| **TWS/Gateway disconnects mid-session** | `AutoReconnect` on the daemons (backoff + re-subscribe); the monitor self-heals on the next poll; one-shots simply abort and retry next cron. |
| **Market-data line limit (~100)** | Option chains are requested in batches and cancelled between batches; only one symbol's chain is fetched at a time. |
| **clientId conflicts** | Central registry in `settings.yaml`; one id per concurrent process (see the process table above). |
| **Claude unavailable / unparseable** | Strict JSON validation + graceful fallback — the Rules-Engine-approved list still ships to Telegram. Claude never blocks the pipeline. |
| **Approval→execution timing gap** | Orders queue in the DB; the executor re-validates against a fresh live quote + the Rules Engine at send time; off-hours orders wait for RTH; stale approvals expire (TTL). |
| **Order rejects / partial fills / wrong contract** | `qualifyContracts` before every order; LimitOrder at mid (never market); fill monitoring with timeout/cancel; rejects alert back to Telegram. |
| **Early assignment (dividends/ITM)** | The monitor flags ITM-ish short calls near ex-dividend and short options breaching delta/DTE, prompting a roll alert. |
| **Risk-limit bypass / runaway** | The deterministic Rules Engine runs twice (decision time + send time); a buying-power buffer is always reserved; live trading is triple-gated. |
| **Secrets leakage** | `.env` is gitignored and never logged; a Telegram chat-id allowlist means only you can approve. |
| **Paper↔live confusion** | Live execution requires `LIVE_TRADING=true` **and** the live port; a loud startup banner states the active mode and account; each live order needs a second `[CONFIRM LIVE]` tap. |

Database concurrency (multiple processes on one SQLite file) is handled with WAL mode + a 30 s busy
timeout, and no process holds a write transaction open across network I/O.
