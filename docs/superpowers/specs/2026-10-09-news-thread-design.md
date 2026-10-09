# Design — News Thread (macro, market, and ticker news with grounded implications)

**Date:** 2026-10-09
**Status:** Approved design; amended 2026-10-09 (source probes, `/news TICKER`, web `/news`) — plan: `docs/superpowers/plans/2026-10-09-news-thread.md`
**Telegram:** forum topic `4409` ("News") in the existing group

---

## 1. Context and goal

The system already touches news in four disconnected places, none of which tell the operator
*what happened and what it means*:

| Existing piece | What it does today | Gap |
|---|---|---|
| `src/data/google_news_backend.py` | Keyless Google News RSS search, 15-min cache, breaker | Only queried for the reviewer prompt |
| `src/claude/news_context.py` | `=== NEWS ===` block (`N#` ids) for the Ollama reviewer | Only for names that are already candidates |
| `src/analytics/sentiment.py` | StockTwits + yfinance headlines (VADER) + optional Reddit → 0-100 | Thin headline set; **already feeds ranking** at weight `0.05` via `ScoreCard.sentiment_score` → `engine/scoring.py` |
| `src/analytics/market_conditions.py` | VIX, VIX/VIX3M, 10y, SPY 5d, VADER over SPY/QQQ headlines | Per-scan backdrop only; nothing is pushed to the operator |

**Goal:** a dedicated Telegram News thread that tells the operator, succinctly and with
substantiated numbers:

1. **Macro news** — inflation, jobs (NFP), the Fed, GDP, wars, peace deals, tariffs, sanctions.
2. **Market tone** — SPY/QQQ/DIA/IWM moves, VIX spikes, risk-on/off regime.
3. **Ticker news** — every name in the effective universe and every held position: upcoming
   and released earnings, material moves, and their catalysts.

For every item: **what happened**, **the implication** (for the market and for the operator's
book), **whether further downside is likely or the move looks like an overreaction**, tied to the
system's own technical and volatility analytics.

**Success criteria**

1. A high-impact US macro print (CPI, NFP, FOMC, PCE…) reaches the thread within ~2 minutes
   of its actual value publishing, and is explained within ~20 minutes (bounded by the data
   delay of the reaction instruments — §6.4).
2. Every number in a posted explanation traces to a fact computed by deterministic code; a
   number the model invents is stripped before posting.
3. The same story is never posted twice; follow-up developments edit or thread under the
   original post.
4. A news-service crash, a dead feed, or an LLM outage never affects scanning, approval, or
   execution — and never blocks the other sources from posting.
5. No LLM output can change a ranking, a gate, or a size (CLAUDE.md core invariant).

## 2. Decisions taken during brainstorming

| # | Decision | Rationale |
|---|---|---|
| D1 | **Scheduled digests + event-driven alerts**, not per-headline posts | ~55 tickers × many headlines/day would be noise and LLM-heavy; low-signal items live in digests |
| D2 | **LLM backend configurable, ships as `cli_then_ollama`** | `claude -p` verified working on the operator's machine 2026-10-09 (subscription, `claude-sonnet-5-5`); a handful of calls/day is well inside limits; local `qwen3.5:4b` is the fallback |
| D3 | **Sentiment that feeds ranking stays deterministic** | The news store improves `sentiment.py`'s *input*; LLM verdicts/explanations are display-only (Telegram + reviewer prompt) |
| D4 | **Position-aware implications** | Held names get strike distance in expected-move units, DTE, assignment threat; universe names get "better CSP/CC setup next scan?" |
| D5 | **Separate `news` process** (`scripts/run_news.py`), no IBKR connection | LLM latency and flaky feeds stay out of `approval_service`'s event loop; fence is simple (like spreads) |
| D6 | **Hybrid implications: 📘 playbook rules + 📈 measured reaction + 🧠 LLM read** | Static rules are instant and free but wrong in "bad news is good news" regimes; the measured reaction is ground truth; the LLM explains divergences. `claude -p` has no per-call charge, so accuracy, not cost, decides |
| D7 | **Strict-format, length-budgeted cards** with inline source links, article link preview, and generated charts | Operator asked for extremely readable, succinct, substantiated output with images and links |
| D8 | **Operator is in SGT; quiet hours post silently rather than hold** | The US session (21:30–04:00 SGT) is the operator's night; holding alerts would bury the trading day. `disable_notification=True` keeps the thread a complete timeline |
| D9 | **Borrow designs, not code**, from the surveyed repos | Several are AGPL or Go, and none respect this repo's fences; everything is rebuilt inside `src/data/` + `src/news/` |

## 3. Prior art borrowed

| Source | Idea adopted | Where |
|---|---|---|
| FinThread (samgozman/fin-thread) | Separate fetch → compose (LLM) → publish → archive roles; economic calendar as its own source with *actual*-value tracking | §4, §5.3 |
| MarketBrief (yukipanpan/marketbrief) | Category-tagged feeds with per-category lookback; two-stage LLM (editor: regime + threads + drop noise, then writer); "what happened → reaction → contradiction → view" | §5.1, §6.5 |
| daily_stock_analysis (ZhuLinsen) | Fixed per-stock dashboard schema; market-recap report; trading-calendar gating | §7.1, §7.4 |
| TradingAgents (TauricResearch) | Relevance filter before reading; stance tallies; **alpha vs benchmark, not raw return**; bull/bear both-sides step; grounded figures verified against a data snapshot | §5.4, §6.1, §6.5, §6.6 |
| FinNLP / FinGPT (AI4Finance) | One small class per source; FinBERT-class finance sentiment as an upgrade path | §5.1, §8 |
| MarketGPT (JHenzi) | Feed tracking + HTTP conditional requests (`ETag`/`Last-Modified`) | §5.1 |
| World Monitor (koala73/worldmonitor) | Multi-source confirmation before a geopolitical alert | §5.4, §7.2 |
| "Buy the Rumor, Sell the News" (arXiv 2608.14014) | Event attributes `scheduled` / `rumor` / `quantified` / `forward_looking`; rumor days carry the move | §5.4, §6.3 |

## 4. Architecture

```
                        scripts/run_news.py  (own process, supervised by scripts/start.py)
 ┌───────────────────────────────────────────────────────────────────────────────────────┐
 │  src/data/ (sources, never raise, breakers)                                           │
 │   rss_backend · google_news_backend (exists) · yfinance news (exists)                 │
 │   forexfactory_backend (schedule) · nasdaq_backend (econ actuals, earnings timing)   │
 │   finnhub_backend (company/general news, earnings) · price_data + intraday (tape)    │
 │                      │                                                                │
 │                      ▼                                                                │
 │  src/news/ingest.py ── normalise · dedupe · tag tickers · tag events · cluster        │
 │                      │                                                                │
 │                      ▼                                                                │
 │               data/news.db  (NewsBase — written ONLY by src/news/)                    │
 │                      │                                                                │
 │        ┌─────────────┴──────────────┐                                                 │
 │        ▼                            ▼                                                 │
 │  src/news/triggers.py         src/news/digests.py                                     │
 │  (alert state machines)       (pre-market / close / week-ahead)                       │
 │        └─────────────┬──────────────┘                                                 │
 │                      ▼                                                                │
 │  src/news/facts.py  ── deterministic fact sheet (F#) from analytics + portfolio       │
 │  src/news/playbook.py ── 📘 textbook implications (config/news_playbook.yaml)          │
 │  src/news/reaction.py ── 📈 measured post-event reaction                               │
 │                      │                                                                │
 │                      ▼                                                                │
 │  src/news/explain.py ── 🧠 LLM (editor + writer passes) → grounding check → fallback   │
 │                      │                                                                │
 │                      ▼                                                                │
 │  src/news/render.py + charts.py ── card HTML + PNG  →  src/news/publish.py → thread 4409│
 └───────────────────────────────────────────────────────────────────────────────────────┘
        ▲ reads (read-only)                                   │ reads (read-only)
        │ PortfolioSnapshotRow, effective_universe(),         ▼
        │ technicals/iv/realized_vol/sector_context/   src/analytics/sentiment.py (news input)
        │ market_conditions                            src/claude/news_context.py (=== NEWS ===)
```

- **No IBKR connection and no clientId.** Prices come through `src/data/` (yfinance); positions
  are read from the newest `PortfolioSnapshotRow` (intraday, monitor-written — *not*
  `PositionSnapshotRow`, which is once per EOD); the universe from
  `src.common.universe.effective_universe()`.
- Spreads-book underlyings (`book_underlyings`) are already excluded from
  `PortfolioSnapshotRow` positions by `get_positions()`; SPY still appears as a *market* index
  in the tape, never as "your book".

## 5. Ingest

### 5.1 Sources (`src/data/`)

Every source implements a small protocol in `src/data/protocols.py`, is built by a factory in
`src/data/factory.py` (config-selected, process-cached), **never raises**, and sits behind
`src/data/breaker.get_breaker(<name>)`.

| Source | Module | Content | Poll |
|---|---|---|---|
| RSS feeds | `src/data/rss_backend.py` (new) | Category-tagged feed list from `config/news.yaml` (Fed press releases, BLS, BEA, Treasury, CNBC Markets, MarketWatch, Yahoo Finance, …). Conditional GET with stored `ETag`/`Last-Modified`; stdlib XML parsing (same approach as `google_news_backend.py`, no `feedparser` dependency) | 5 min |
| Google News search | `google_news_backend.py` (exists) | Per-ticker queries (universe ∪ held) + configurable macro topic queries | ticker: 30 min round-robin; macro: 10 min |
| yfinance headlines | existing `NewsProvider` | Per-ticker | 30 min round-robin |
| Economic schedule | `src/data/forexfactory_backend.py` (new) | ForexFactory weekly JSON (`ff_calendar_thisweek.json`), USD, high + medium impact: title, ET time, forecast, previous. **Probed 2026-10-09: the feed has no `actual` field**, so it is the schedule and impact source only | 1 h |
| Economic actuals | `src/data/nasdaq_backend.py` (new) | Nasdaq `api.nasdaq.com/api/calendar/economicevents?date=D`: per-event `actual`, `consensus`, `previous` for every country (filter `United States`). **Probed 2026-10-09: the rows returned for `date=D` are the US releases of ET day D−1, and the column labelled `gmt` is ET** (jobless claims 08:30 appeared under `date=2026-10-09` while ForexFactory lists them on 2026-10-08). The backend therefore requests `ET-day + 1` and matches events to the schedule by playbook key + ET time | 1 h normally; **30 s within −2/+10 min of a scheduled high/medium event** |
| Earnings calendar | `src/data/nasdaq_backend.py` + `src/data/finnhub_backend.py` (new) | Nasdaq `calendar/earnings?date=D`: timing (`time-pre-market`/`time-after-hours`), consensus EPS. Finnhub `calendar/earnings` (symbol-filtered): date, `hour`, EPS/revenue estimate **and actual** once reported. yfinance `next_earnings` (already in `fundamentals.py`) is the fallback date | 6 h; 5 min around a universe/held name's release window |
| Market tape | `price_data` provider + a new `IntradayPriceProvider` (yfinance 1-min bars with pre/post) | SPY QQQ DIA IWM ^VIX ^TNX UUP GLD USO (+ ES=F NQ=F ZN=F DX-Y.NYB GC=F CL=F outside RTH — the §6.4 reaction set) | 2 min during RTH; 5 min pre-market |
| Finnhub | `src/data/finnhub_backend.py` (new) | `company-news` per ticker (headline, **summary, image URL**, source, URL), `news?category=general` (macro/business), `calendar/earnings`, `stock/earnings` (EPS surprise history). **Probed 2026-10-09 with the operator's free key: all four return 200; `calendar/economic` returns 403 (premium) and is not used.** Dormant if `FINNHUB_API_KEY` is unset (Reddit pattern); 60 calls/min budget | company news 30 min round-robin; general 10 min |

Per-category lookback (MarketBrief): `government`/`geopolitics` → 7 d, never truncated by the
per-run cap; `macro` → 7 d; `markets` → 36 h; `ticker` → 72 h. All in `config/news.yaml`.

### 5.2 Store (`data/news.db`, `src/news/store/models.py`, own `NewsBase`)

| Table | Key columns |
|---|---|
| `news_items` | `id`, `url_hash` (unique), `title_norm_hash`, `title`, `url`, `source`, `source_domain`, `category`, `published_at`, `fetched_at`, `tickers` (JSON), `tags` (JSON: scheduled/rumor/quantified/forward_looking), `det_sentiment` (−1..+1, VADER or FinBERT), `cluster_id` |
| `news_clusters` | `id`, `headline` (representative), `category`, `first_seen`, `last_seen`, `source_count` (distinct domains), `tickers` (JSON), `topic_class` (e.g. `war`, `ceasefire`, `tariff`, `fed`, `earnings`, `other`) |
| `econ_events` | `event_key` (title+datetime), `title`, `playbook_key`, `scheduled_at`, `impact`, `forecast`, `previous`, `actual`, `actual_seen_at`, `surprise` (normalised, §6.3) |
| `earnings_events` | `symbol`, `report_date`, `timing` (BMO/AMC/unknown), `eps_est`, `eps_actual`, `rev_est`, `rev_actual`, `status` (scheduled/released), `released_seen_at` |
| `feed_state` | `feed_url`, `etag`, `last_modified`, `last_polled`, `last_ok` |
| `news_posts` | `id`, `kind` (digest/alert type), `telegram_message_id`, `chart_message_id`, `cluster_ids` (JSON), `event_ref`, `posted_at`, `edited_at`, `stage` (`facts`/`explained`/`fallback`), `llm_backend`, `prompt_hash`, `silent` (bool) |
| `alert_state` | `(trigger, subject, trade_date)` unique — "fired once per day" bookkeeping for threshold triggers |

Retention: `news_items` older than `news.retention_days` (default 30) pruned daily; posts kept.

### 5.3 Normalisation and dedupe

- Every item from every source normalises to one `RawNewsItem` schema (in `src/news/schemas.py`).
- Dedupe 1: `url_hash` (URL with tracking params stripped). Dedupe 2: `title_norm_hash`
  (case/whitespace/punctuation-normalised title, reusing `news_context._normalize_title`'s rule).
- **Clustering:** a new item joins an existing cluster in the same category when token-set
  Jaccard similarity of normalised titles ≥ `news.cluster.similarity` (default 0.5) and
  `last_seen` is within 48 h; otherwise it opens a cluster. `source_count` counts distinct
  `source_domain`s.

### 5.4 Deterministic tagging (before any LLM sees an item)

- **Ticker relevance** (TradingAgents' filter-before-reading): an item is tagged with a ticker
  only if its title contains the ticker as a whole word, a `$TICKER` cashtag, or an alias from
  `src/news/aliases.py` (built from yfinance `longName`/`shortName`, cached in `news.db`, with
  manual overrides in `config/news.yaml` — e.g. `GOOGL: [Alphabet, Google]`). Items fetched by a
  ticker query that fail this test are kept as untagged background, not attributed.
- **Event tags** (Buy-the-Rumor paper), keyword/regex lists in `config/news.yaml`:
  `scheduled` (cluster matches an `econ_events`/`earnings_events` row within ±1 day),
  `rumor` ("reportedly", "sources say", "people familiar", "in talks", "considering",
  "weighs"), `quantified` (contains a number/percent/currency figure),
  `forward_looking` ("guidance", "outlook", "forecast", "expects", "raises", "cuts").
- **Topic class** for macro/geopolitics clusters: keyword lists → `war`, `ceasefire`,
  `sanctions`, `tariff`, `fed`, `fiscal`, `energy`, `other`.
- **Deterministic sentiment** per item: `sentiment._vader_compound` + `_keyword_bias` today;
  FinBERT behind `news.sentiment.model: finbert` (optional extra, §8).

## 6. From event to explanation

### 6.1 Fact sheet (`src/news/facts.py`) — deterministic

Builds a numbered list `F1…Fk` (the same citation convention as the strategist prompt's
`F#`/`N#` rubric). Reads only the deterministic analytics tier and storage; never the LLM.

| Group | Facts |
|---|---|
| Move | today's % change; **σ-move** = \|ret\| ÷ (IV30 ÷ √252) (fallback HV30 when IV absent); move ÷ ATR14; **abnormal move** = ret − ret(SPY) and ret − ret(sector ETF via `sector_context`) |
| Technicals (`get_technical_stats`) | RSI14, price vs SMA50/SMA200, `classify_phase` phase/regime, nearest support & resistance and % distance, MACD state |
| Volatility (`iv.py`, `realized_vol.py`) | IV rank, IV30 vs HV30 |
| Earnings | implied move (IV-derived, from the nearest-expiry ATM IV when available, else IV30 scaled to 1 day); realised post-report move; the last *N* (default 4) post-earnings 1-day moves from price history |
| Macro print | actual vs forecast vs previous; normalised surprise (§6.3) |
| Attributes | event tags, `source_count`, topic class, cluster age |
| Book (from newest `PortfolioSnapshotRow`) | per held position on the name: right, strike, DTE, % distance to strike, **distance in expected-move units** (expected move = spot × IV × √(DTE/365)), stock lot if assigned; universe membership (`actively_wheeling` / `would_own` / `watchlist` / `indexes`) |
| Backdrop (`market_conditions`) | VIX, VIX/VIX3M, 10y and 5d change, SPY/QQQ/DIA/IWM day moves |

Each fact is a `Fact(id, label, value, unit, display)` Pydantic model; the rendered fact block is
both the LLM's grounding input and the grounding checker's reference set.

### 6.2 Overreaction / continuation **flags** — deterministic, interpreted by the LLM

Computed in `facts.py` as named boolean flags with the facts that triggered them. They are
evidence, not predictions:

- `large_move_no_hard_news`: σ-move ≥ 2 and no cluster tagged `quantified` for the name.
- `rumor_driven`: the driving cluster is `rumor`-tagged (move likely front-loaded).
- `sector_move`: \|abnormal vs sector\| < ⅓ × \|raw move\| (it's the sector, not the stock).
- `oversold_at_support`: RSI14 < 30 and price within 1 ATR of a support level or SMA200.
- `earnings_move_vs_implied`: realised ÷ implied ≥ 1.5 (outsized) or ≤ 0.5 (muted).
- `trend_break`: close crossed below SMA200 on the event day.

Thresholds live in `config/news.yaml`.

### 6.3 📘 Playbook (`config/news_playbook.yaml`, `src/news/playbook.py`) — deterministic

Maps `playbook_key` × surprise direction → expected direction for **Stocks, Bonds, Dollar,
Gold, Oil, Vol** plus a one-line rationale. Initial keys: `cpi`, `core_cpi`, `ppi`, `pce`,
`core_pce`, `nfp`, `unemployment`, `avg_hourly_earnings`, `fomc_rate`, `gdp`, `retail_sales`,
`ism_manufacturing`, `ism_services`, `jobless_claims`, `jolts`, `umich_sentiment`.
ForexFactory titles map to keys through an alias list in the same file.

- Surprise direction: `hot` if actual > forecast by more than the key's `tolerance` (in the
  event's own units), `cold` if below, `inline` otherwise. For inverse indicators
  (`unemployment`, `jobless_claims`) "hot" means *stronger economy* and the file says so per key.
- Arrows: 🟢 up · 🔴 down · ⚪ flat/ambiguous. Bonds = **price** (yield up ⇒ 🔴), stated in the card legend.
- The playbook is a *prior*; it is never labelled as the outcome.

### 6.4 📈 Measured reaction (`src/news/reaction.py`) — deterministic

For a macro print: the % move (yield change in bp for rates) of each reaction instrument from
the last bar **at or before** `actual_seen_at` to the bar at release + `news.reaction.window_min`
(default 15). Instruments by session (configurable):

| Asset | RTH | Pre-market / after hours |
|---|---|---|
| Stocks | SPY | ES=F |
| Bonds | ^TNX (yield) | ZN=F |
| Dollar | UUP | DX-Y.NYB |
| Gold | GLD | GC=F |
| Oil | USO | CL=F |
| Vol | ^VIX | — (omitted; VIX does not print outside RTH) |

yfinance futures quotes are delayed (~10 min), so the window is measured **on bar
timestamps, not wall clock**: `reaction.py` polls until a bar at or after release + window
exists, up to `news.reaction.max_wait_min` (default 35); past that it renders "reaction
pending (data delayed)" and the 🧠 read proceeds without it. Each reaction is also expressed in
σ (instrument's IV/HV-implied 15-min σ when computable; omitted otherwise).

For ticker events the reaction is the abnormal move from §6.1.

### 6.5 🧠 LLM explanation (`src/news/explain.py`)

**Backend:** `news.llm.backend: cli | ollama | cli_then_ollama` (ships `cli_then_ollama`),
`news.llm.model` (ships `claude-sonnet-5-5`), `news.llm.timeout_seconds`,
`news.llm.max_calls_per_day` (ships 40). Invocation reuses the existing `claude -p`
(`--output-format json`) and Ollama call helpers — factored into a shared
`src/common/llm_cli.py` if the current helpers in `src/claude/runner.py` /
`src/research/summary/claude_cli.py` cannot be imported without dragging their modules' other
imports; never a third copy.

**Pass 1 — editor** (digests only; MarketBrief): input = clusters since the previous digest
(title, sources, tags, tickers) + backdrop facts. Output (`EditorOutput`): `regime`
(`risk_on`/`risk_off`/`rotation`/`mixed`), ranked `threads` (cluster-id groups, max
`news.digest.max_threads`, default 6), `dropped` cluster ids with a one-word reason.

**Pass 2 — writer** (per thread or per alert): input = the thread's headlines (`N#`), the fact
sheet (`F#`), flags (§6.2), playbook prior (§6.3), measured reaction (§6.4). Output
(`Explanation`), each field length-budgeted **in the schema** (Pydantic `max_length`):

| Field | Budget | Content |
|---|---|---|
| `headline` | 80 | Plain-language title |
| `what_happened` | 180 | The fact, with figures |
| `read` | 240 | Why it matters / what the market is pricing; **must address any playbook-vs-actual divergence** |
| `bull` / `bear` | 100 each | One line each side (TradingAgents debate, compressed) |
| `verdict` | enum | `further_downside_likely` · `further_upside_likely` · `overreaction_likely` · `priced_in` · `unclear` |
| `confidence` | enum | `low` · `medium` · `high` |
| `book_impact` | 200 | Held-position consequence (strike distance, DTE, assignment threat) or empty |
| `setup_impact` | 160 | Universe-name CSP/CC setup change or empty |
| `evidence` | list | `F#`/`N#` ids supporting the verdict (≥ 1 required for any verdict other than `unclear`) |

### 6.6 Grounding check (`src/news/grounding.py`) — deterministic

1. Parse against the schema; on failure retry once with the validation error appended.
2. Every `evidence` id must exist in the fact sheet / news index; unknown ids are removed;
   if none remain and `verdict ≠ unclear`, verdict is downgraded to `unclear`.
3. **Numeric grounding** (TradingAgents): every number in the free-text fields is extracted
   (incl. `%`, `bp`, `σ`, `$`) and must match some fact's value within rounding tolerance
   (`news.grounding.rel_tol`, default 2%, or ±1 in the last displayed digit). A sentence
   containing an ungrounded number is dropped and the post carries a small `⚠︎ trimmed`
   marker; if `what_happened` loses its number, it is replaced by the deterministic fact line.
4. Fallback chain: CLI → Ollama → **deterministic card** (facts + playbook + reaction +
   headlines, no 🧠 section). `news_posts.stage` records which one shipped.

## 7. Telegram output

Thread: `TELEGRAM_THREAD_NEWS=4409` (new `.env` key; empty = General topic, matching the
existing thread keys). Bot token and chat id are the existing ones. HTML parse mode;
`src/news/publish.py` splits any text over Telegram's 4096-char limit at section boundaries.

### 7.1 Card format (alerts)

Fixed section order, emoji-anchored, every source name an inline `<a href>` link:

```
🔴 CPI hotter than expected · 20:30 SGT (08:30 ET)
Sep CPI +0.4% m/m vs +0.3% est · core +0.3% — <a>BLS</a> · <a>Reuters</a>

          📘 Textbook   📈 Actual (15m)
Stocks    🔴            🔴 ES −1.2% (1.6σ)
Bonds     🔴            🔴 10y +9bp
Dollar    🟢            🟢 DXY +0.4%
Gold      🔴            ⚪ +0.1%

🧠 Inflation re-accelerating for a 2nd month → Dec cut odds falling. Move is in
   line with surprise size — not an overreaction.
⚖️ Bull: core services cooling · Bear: shelter sticky, 3rd hot print in 4
🎯 Further downside likely · medium
💼 NVDA 165P (14 DTE) 3.1% OTM = 0.9 exp. moves — watch
🛒 IV rank up on SOFI/PLTR → richer CSP premium next scan
```

- The textbook/actual grid is rendered in a `<pre>` block so columns align.
- **Link preview** (python-telegram-bot 22.7 `LinkPreviewOptions`): when the cluster's primary
  item carries an `image_url` (Finnhub supplies one), the preview URL is that image
  (`prefer_large_media=True`, `show_above_text=True`) so the picture renders inline above the
  card; otherwise the primary source article URL (highest-ranked domain in the cluster per
  `news.source_rank`) so Telegram renders the article's own preview image.
- **Chart** (`src/news/charts.py`, `matplotlib` with the `Agg` backend — new dependency): for
  ticker moves, earnings and the close recap, a PNG posted directly beneath the card
  (`reply_to_message_id` = the card) showing ~6 months of daily closes, SMA50/SMA200, nearest
  support/resistance, an event marker, and — for held names — **the short strike as a dashed
  line labelled with DTE**. Intraday 5-min bars are added as an inset when the price provider
  returns them; otherwise daily only.
- Ticker-move and earnings cards use the same skeleton with the 📘 grid replaced by a facts
  line (`−6.2% · 2.4σ · −4.9% vs XLK · RSI 27 · at SMA200`), and earnings show
  `EPS 1.12 vs 1.05 est · Rev 42.1B vs 41.6B · move −9.0% vs ±6.1% implied`.

### 7.2 Alerts (`src/news/triggers.py`)

| Alert | Trigger (all thresholds in `config/news.yaml`) | Critical? |
|---|---|---|
| Macro print | High-impact USD `econ_events` row gains an `actual` | yes |
| Earnings released | `earnings_events` for a universe or held name flips to `released` | held: yes · universe: no |
| Market move | SPY/QQQ/DIA crosses −1 / −2 / −3 % (and +2 / +3 %) intraday; each level once per day (`alert_state`) | ≤ −2 %: yes |
| VIX spike | ^VIX +15 % on the day or crosses 25 / 30 | yes |
| Ticker move | held name \|abnormal move\| ≥ 2σ; universe name ≥ 3σ — card names the matching cluster or states **"no identifiable catalyst"** | held: yes |
| Breaking macro/geo | cluster with `source_count ≥ 2`, `topic_class ∈ {war, ceasefire, sanctions, tariff, fed, fiscal, energy}`, **and** a measurable reaction (\|ES/SPY move\| ≥ 0.5 % within 30 min of `first_seen`) | yes |

**Two-stage post** (FinThread's event tracking): the alert is sent immediately with the
deterministic sections (facts, 📘, reaction-so-far); once the reaction window has closed (§6.4)
and the LLM has run, the **same message is edited** to add 📈 and 🧠, following the
existing `_append_status` edit pattern. A later development on the same cluster edits the
original card's tail (`🔄 Update hh:mm …`) rather than posting anew, up to
`news.alerts.max_edits` (default 3), then posts a threaded reply.

**Throttle:** at most `news.alerts.max_per_hour` (default 6) non-critical alerts; the excess
roll into the next digest.

**Quiet hours** (`news.quiet_hours`, tz `Asia/Singapore`, ships `00:00–07:00`): non-critical
alerts post with `disable_notification=True`; critical alerts notify normally
(`news.quiet_hours.critical_breaks_quiet: true`). Nothing is held.

### 7.3 Digests (`src/news/digests.py`)

US-trading days only (existing market-holiday calendar, as `_market_holiday_loop` uses);
times in `America/New_York`, rendered with the SGT equivalent.

| Digest | Default time | Sections |
|---|---|---|
| Pre-market brief | 08:00 ET | Regime line · overnight macro/geo threads (🧠) · futures ES/NQ/ZN · **today's calendar** (econ events with SGT times + playbook key; BMO/AMC earnings for universe ∪ held with implied moves) · overnight items on held names |
| Close recap | 16:30 ET | Index moves + regime · top universe movers (≤ `news.digest.max_movers`, default 5) with one-line 🧠 each · held-position status table (price, % to strike, DTE) · tonight's AMC earnings · chart of SPY day + the day's biggest held mover |
| Week ahead | Sunday 18:00 ET | Week's high-impact econ calendar · universe earnings with implied moves · **held positions with earnings before expiry** flagged |

Digest sections use the editor pass's thread ranking; each thread renders as a compact
3-line block (headline · 🧠 read · 🎯 verdict) with inline links.

### 7.4 Calendar gating

No digests or market/ticker alerts on US market holidays; macro-print alerts still fire if the
calendar has a release (rare). Weekend: week-ahead only, plus breaking macro/geo alerts.

### 7.5 `/news TICKER` — on-demand ticker brief (added 2026-10-09 at the operator's request)

Telegram long-polling for the bot token lives in `approval_service` (one `getUpdates` poller
per token — a second poller in the news process would steal its updates), so the command is
registered there, but **all work happens in the news process**:

1. `approval_service` registers `CommandHandler("news", handle_news_command)`. `/news NVDA`
   validates the symbol (`^[A-Z][A-Z0-9.\-]{0,9}$`), calls
   `src.news.briefs.enqueue_brief(symbol, origin="telegram")` — a single insert into
   `news_requests` in `news.db` — and replies `📰 Building NVDA brief → News thread`.
   `/news` with no argument replies with the most recent digest's link (the
   `news_posts` row's `telegram_message_id`) or a usage line.
2. The news process polls `news_requests` every `news.briefs.poll_seconds` (default 5), claims
   pending rows, and builds a **ticker brief**: a fresh fetch for that symbol (Google News,
   yfinance, Finnhub company news — bypassing the round-robin), ingest, the §6.1 fact sheet,
   the matching clusters of the last 72 h, the earnings row, and the writer pass (§6.5) on the
   top threads — posted to thread 4409 with a chart, stored in `news_posts` (`kind =
   "brief"`), and the request row marked `done` with the post id.
3. Briefs bypass the hourly alert cap but count toward `news.llm.max_calls_per_day`. The same
   symbol requested again within `news.briefs.dedupe_minutes` (default 10) reuses the pending
   or just-finished request instead of building twice.
4. Works for any ticker, not only universe names (a non-universe name gets no "book" or
   "setup" section and is marked `not in universe`).

### 7.6 Web `/news` page (added 2026-10-09 at the operator's request)

**API** (`src/api/routers/news.py`, owner-only like the other book-exposing routes). Reads
`data/news.db` through a new read-only engine `src/api/news_db.py` (`mode=ro` URI, the
`trading_db.read_only_url` pattern) — the API still writes exactly one table (`app_commands`):

| Route | Returns |
|---|---|
| `GET /news/feed?kind=&symbol=&limit=&before=` | Posted digests/alerts/briefs, newest first, with their structured payload (headline, facts, 📘/📈 grid, 🧠 explanation, verdict, links, image URL) — rendered by the web from structure, never from Telegram HTML |
| `GET /news/posts/{id}` | One post + its chart as a `data:image/png;base64,…` string (the web proxy reads upstream bodies as text, so binary routes are avoided) |
| `GET /news/calendar?days=7` | Upcoming high/medium US econ events (schedule + forecast + actual if released) and earnings for universe ∪ held names |
| `GET /news/ticker/{symbol}` | Latest brief for the symbol (if any), its recent clusters, next earnings, and any open request's status |
| `GET /news/status` | News service heartbeat age, last ingest per source, breaker states, LLM calls used today vs cap |

**Request a brief from the web:** `POST /commands` with a new kind `news_brief`
(`{"symbol": "NVDA"}`), repeatable (no dedupe key — the news process dedupes, §7.5.3). The
drain handler in `approval_service` calls the same `enqueue_brief(symbol, origin="web")` and
returns `{"request_id": …}`; the page polls `GET /news/ticker/{symbol}` until the brief lands.

**Pages** (`web/app/news/`): `/news` — a feed (filter chips: All · Macro · Market · Tickers ·
Earnings · Briefs; a symbol search), each post a card mirroring the Telegram layout
(📘/📈 grid as a small table, 🎯 verdict pill, 💼 book line, inline source links, image) plus a
right-hand **calendar** column (today and the week: econ events with SGT/ET times, earnings
with BMO/AMC). `/news/[symbol]` — the latest brief, the chart, the recent clusters, and a
**Request fresh brief** button (`submitCommand("news_brief", …)` with a `<CommandReceipt/>`).
The rail gains a `News` section. Follows `web/CLAUDE.md`: dark tokens only, IBM Plex Mono +
`.tabular` for numbers, verdict state never colour-only (pill text + icon), no em dashes in
UI copy.

## 8. Integration with existing sentiment and the reviewer

- **`sentiment.py`**: `_fetch_news` reads recent (`news.sentiment.lookback_hours`, default 72)
  ticker-tagged, deduped items from `news.db` and computes a **recency-weighted** mean of
  their `det_sentiment` (half-life `news.sentiment.half_life_hours`, default 24), replacing the
  yfinance-only headline set; `count` is the number of distinct clusters, not raw items. If
  `news.db` is absent or empty for the name, it falls back to today's yfinance path unchanged.
  The blend weights and the `0.05` scoring weight are **not** changed by this spec.
- **FinBERT (optional)**: `news.sentiment.model: vader | finbert` (ships `vader`). `finbert`
  requires the optional `transformers`/`torch` extra, runs inside the news process at ingest
  (scores stored in `det_sentiment`), and degrades to VADER if unavailable. Deterministic
  inference — no generation — so it stays on the allowed side of D3.
- **`news_context.py`**: `build_news_block` prefers `news.db` clusters for the candidate
  underlyings (already deduped, source-counted), falling back to the live Google News +
  yfinance fetch when the store has nothing — cutting the review's NEWS fetch latency.
- **LLM fields are unreachable from ranking**: `sentiment.py` may read only `news_items`
  columns `det_sentiment`, `published_at`, `fetched_at`, `tickers`, `cluster_id`, `title` (the
  source headline, for `top_headline`); it never reads
  `news_posts` or any `Explanation` content. Asserted by test (§10).

## 9. Process, config, operations

- **`scripts/run_news.py`**: one asyncio service; loops for source polling, the RTH tape, the
  econ-release fast-poll, triggers, digests, and pruning. Registered in `scripts/start.py`'s
  process table (like `scripts.run_spreads`) behind `news.enabled` (ships `true`).
- **Config:** committed `config/news.example.yaml` + private git-ignored `config/news.yaml`
  (feeds, macro queries, aliases, tag keyword lists, thresholds, digest times, quiet hours,
  LLM backend/model/cap, sentiment model, retention). Committed
  `config/news_playbook.yaml` (not private — it is reference data, not operator tuning).
  Loaded through `src/common/config.py` with validation at load (unknown playbook keys, bad
  times, quiet-hours tz).
- **`.env`:** `TELEGRAM_THREAD_NEWS=4409`, `FINNHUB_API_KEY` (set on the operator's machine 2026-10-09; empty = Finnhub dormant).
- **Watchdog:** `scripts/watchdog.py` gains a "news service stale" check (no successful
  ingest cycle in 30 min during US hours), reported to the ops (scan) thread.
- **Startup message:** the news process posts a one-line "📰 News service online (backend:
  cli_then_ollama)" to thread 4409 on start, mirroring other services' banners.

## 10. Fences (new `tests/test_news_fence.py`, `ast`-parsed like `test_spreads_fence.py`)

1. `src/engine/`, `src/execution/`, `src/strategies/`, `src/spreads/` never import `src.news`.
2. `src/news/` imports nothing from `src.engine`, `src.execution`, `src.strategies`,
   `src.spreads`, `src.orchestrator`, `src.notify.approval_service`.
3. Only `src/news/` constructs `NewsBase` rows (writer fence, like the ledger fence).
4. `src/analytics/sentiment.py` reads only the whitelisted `news_items` columns (§8) — never
   `news_posts`/`Explanation`.
5. `src.news` is added to `tests/test_eval_skills.py::test_news_and_tool_research_never_reach_the_deterministic_layer`'s
   enrichment list.
6. `src/api/` reaches `news.db` only through `src/api/news_db.py`'s read-only engine; the
   existing `test_the_api_still_writes_exactly_one_table` stays green, and a new test asserts
   no `src/api/` module imports `src.news.store.session` (the read-write engine).
7. The only `src.news` symbol `src/notify/` may import is `src.news.briefs.enqueue_brief`
   (the `/news` command and the `news_brief` drain handler) — no LLM, ingest, or publish code
   is loaded into `approval_service`.

Reading the deterministic tier (`technicals`, `iv`, `realized_vol`, `price_data`,
`sector_context`, `market_conditions`) from `src/news/` is allowed — enrichment may read
deterministic, never the reverse.

## 11. Error handling

- Every source never raises; breaker-opened sources are skipped and logged once per state change.
- Each loop iteration is wrapped; an exception logs and the loop continues (no crash-loop).
- LLM: per-call timeout, daily cap, fallback chain (§6.6); cap exhaustion is logged and shown
  as a small `🧠 off (daily cap)` marker on cards.
- Telegram: send failures retried with backoff (3×); an edit that fails because the message is
  gone posts a fresh card.
- `news.db` corruption/missing → recreated empty on start; `sentiment.py` falls back (§8).

## 12. Testing (all offline; no network)

| Area | Tests |
|---|---|
| Sources | Parsers on saved fixtures (ForexFactory JSON, an RSS sample incl. `ETag` 304 path, Nasdaq earnings JSON, Finnhub JSON); never-raises on garbage |
| Ingest | URL/title dedupe; clustering thresholds; source_count by domain; ticker tagging incl. aliases and incidental-mention rejection; event tags; topic class |
| Facts | σ-move, abnormal move vs SPY and sector, expected-move distance to strike, implied vs realised earnings move, each flag's boundary |
| Playbook | hot/cold/inline per key incl. inverse indicators; alias mapping from FF titles; config validation |
| Reaction | bar-timestamp windowing with delayed data; `max_wait` → "pending"; RTH vs futures instrument selection |
| Explain/grounding | schema retry; unknown evidence ids removed; ungrounded numbers stripped; verdict downgrade; fallback chain with mocked CLI/Ollama; daily cap |
| Triggers | each threshold fires once/day; critical vs non-critical; hourly cap; quiet hours → `disable_notification`; two-stage post then edit; update-edit vs threaded reply after `max_edits` |
| Digests | holiday gating; section assembly; editor-pass ranking used |
| Render | golden-output cards (alert, earnings, ticker move, digests); 4096 split; HTML escaping of titles |
| Charts | PNG produced headless; strike line present for held names (assert on the plotted artists, not pixels) |
| Sentiment integration | store-backed `_fetch_news` recency weighting; fallback when store empty; fence (§10.4) |
| Fences | §10 |

## 13. Milestones

| M | Delivers | Operator-visible |
|---|---|---|
| M1 | `src/news/` skeleton, `news.db` + models, sources (RSS, Google News, yfinance, econ + earnings calendars, optional Finnhub), ingest (dedupe, cluster, tag), `run_news.py` polling loop | Store fills; nothing posted |
| M2 | Facts, flags, playbook, reaction, render + charts, publish, triggers, digests — **deterministic cards only** | Working News thread with numbers, 📘 and 📈 |
| M3 | Explain (editor + writer), grounding, fallback chain, two-stage edit flow | 🧠 explanations, verdicts, book impact |
| M4 | `sentiment.py` + `news_context.py` read the store; optional FinBERT | Better ranking input and reviewer context |
| M5 | `/news TICKER` (§7.5), `news_brief` command kind, read-only `/news/*` API, web `/news` + `/news/[symbol]` pages (§7.6) | On-demand briefs in Telegram and on the web |
| M6 | `start.py` registration polish, watchdog check, docs (ARCHITECTURE, SETUP, STATUS, README Telegram section, CLAUDE.md fence entry, `docs/web/commands.md`, `docs/web/api.md`), `config/*.example.yaml` | Operable, documented |

## 14. Out of scope (deferred)

- Spreads-book (SPY 0DTE) position impact in "your book".
- Real-time (non-delayed) reaction data via IBKR — the news process deliberately holds no
  IBKR connection.
- Any LLM-derived signal entering ranking, gating, or sizing (permanently out, D3).

## 15. Risks and live-verification items

| Risk | Mitigation |
|---|---|
| ForexFactory JSON feed is unofficial and may change or vanish | Breaker + fixture tests; Nasdaq's economic calendar carries the same schedule (without an impact rating) and is the fallback schedule source behind the same protocol; STATUS.md notes it |
| Nasdaq endpoints undocumented, need browser-like headers, and use a D+1 date key | Live-probed fixtures pin the shape and the D+1 rule; a probe script (`scripts/news_probe.py`) re-checks both before go-live; breaker; Finnhub/yfinance are the earnings fallbacks |
| Finnhub free tier is personal-use only and 60 calls/min | Single-operator personal use; client-side token bucket at 50/min |
| yfinance futures/intraday quotes delayed ~10 min | Bar-timestamp windowing (§6.4); "pending" render; documented |
| Google News query volume (~55 tickers + macro topics) | 30-min round-robin + existing 15-min cache + breaker |
| `claude -p` subscription rate limits | Daily cap 40; Ollama fallback; deterministic floor |
| Alert fatigue | Thresholds, once-per-day levels, hourly cap, multi-source + reaction gate for geo news, quiet-hours silent posts |
| Telegram caption/length limits | Text in messages (4096) not captions (1024); charts as separate replies |

Live verification after M2/M3: first CPI/NFP release end-to-end timing; FF `actual` latency;
yfinance futures bar delay measured; link-preview image renders in the forum topic.
