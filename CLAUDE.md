# CLAUDE.md — IBKR Options Income System

Guidance for Claude Code when working in this repository.

## What this project is

A **semi-autonomous options-income trading system** for an Interactive Brokers account,
focused on selling **covered calls (CCs)** and **cash-secured puts (CSPs)**. Python does all
deterministic work (scanning, option-chain analysis, IV/Greeks, technicals, fundamentals,
scoring, monitoring, execution). Claude is the **reasoning/strategy layer**, invoked **without the
API** via the Claude Code CLI in headless mode (`claude -p`, JSON in/out) under the user's
subscription.

The build is feature-complete (paper-trading v1). **`ARCHITECTURE.md`** (how it's built) and
**`STATUS.md`** (what's built, what's deferred, known limitations) are the authoritative references —
read both before making structural changes.

## Documentation files — what they are and when to update them

| File | Audience | Purpose |
|---|---|---|
| **`README.md`** | Anyone, including public/portfolio viewers | Short pitch: what it does, Telegram commands, safety summary, fork/quickstart, and a top-level-only layout table. **Deliberately does not** carry the detailed pipeline walkthrough or a per-file layout — those live in `ARCHITECTURE.md` (moved out 2026-09-30 so a first-time reader isn't met with a wall of implementation detail) |
| **`SETUP.md`** | New users | Complete step-by-step guide from fresh machine to first live trade |
| **`ARCHITECTURE.md`** | Non-technical users and new contributors | The full technical deep dive: "The pipeline, stage by stage" (the detailed How-it-works/In-plain-English walkthrough — moved here from `README.md`), the folder-by-folder guide (every folder including `web/` and the root `ibkr` script), the process/clientId model, data-flow schemas, key invariants, and operational risk handling |
| **`STATUS.md`** | Claude and developers | What's built vs. deliberately not built, tech stack, unenforced config, items needing live verification, the live-cutover gate |
| **`UNIVERSE_RESEARCH.md`** | Claude Code + headless `claude -p` | Deep-research reference for every ticker: tier, verified prices/IV ranks (Jun 2026), CC vs CSP appropriateness, leveraged-ETF assignment rules, IV rank methodology, data-quality warnings. A compact version is injected into every trade-review prompt via `src/claude/prompts/strategist.py`. |
| **`How the scan works.md`** | Anyone | Operator-facing explanation of scan scheduling and the materiality gate: what `indexes`/`watchlist`/`would_own`/`actively_wheeling` each mean to the scan loop, the 15-min / 120-min clocks, the 0.5% / 2% / 3% thresholds and their directions, and a worked scenario. Update it whenever `market_data.*_pct`, `force_full_scan_minutes`, `intraday_loop_minutes`, or `_compute_material_symbols` changes |
| **`CLAUDE.md`** | Claude Code | Invariants, conventions, safety rules, change workflow — read before any structural change |
| **`ib_async_documentation.md`** | Claude and developers | Authoritative IBKR API reference — consult before guessing any ib_async signature |

### Mandatory doc-update rule

> **This rule is enforced by a project hook.** A reminder fires after every Python file edit.
> Do not declare a task complete until docs are consistent with the code.

**After every prompt that results in a code change, review and update the relevant documentation
files before declaring the task complete.** Map the change to the table below and act on every
row that matches:

| What changed | Files to update |
|---|---|
| New file or module added | `ARCHITECTURE.md` folder guide (always) · `README.md` layout table only if it's a new top-level directory |
| Existing module renamed, moved, or deleted | Both above |
| New config key added to any YAML | Add it to the committed `config/<name>.example.yaml` (the private copy is git-ignored) · `ARCHITECTURE.md` config/ section · `SETUP.md` if it affects setup |
| New script entrypoint added | `SETUP.md` scripts table · `ARCHITECTURE.md` `scripts/` folder-guide entry |
| **New Telegram command registered** in `approval_service.py` | `ARCHITECTURE.md` commands table (src/notify/ section) · `SETUP.md` "Using the Telegram bot" commands table · `README.md` Telegram commands table |
| **New formatter function added** to `formatters.py` | `ARCHITECTURE.md` src/notify/ table description |
| **New Pydantic schema** added to `schemas.py` | `ARCHITECTURE.md` src/common/ + data-flow sections |
| **New storage model** (ORM class) added to `models.py` | `ARCHITECTURE.md` src/storage/ section |
| Feature built / deferred, or a limitation changes | `STATUS.md` (what's built / not built / known limitations) |
| Bug fix that changes behaviour users would notice | `SETUP.md` troubleshooting table if relevant |
| **Ticker added/removed from `universe.yaml`** | `UNIVERSE_RESEARCH.md` — add/remove ticker section · `src/claude/prompts/strategist.py` `_UNIVERSE_CONTEXT` table |
| **New command kind registered** in `command_drain.py` | `docs/web/commands.md` |
| **New module under `src/reporting/`** | `ARCHITECTURE.md` folder guide · root `CLAUDE.md` analytics-tier section |
| **New module under `src/news/`** or a new key in `config/news.example.yaml` | `ARCHITECTURE.md` `src/news/` section · `SETUP.md` §17 News thread if operator-facing · root `CLAUDE.md` news-fence section if it changes what the package may import |
| **New module under `src/spreads/`** or a new key in `config/spreads.example.yaml` | `ARCHITECTURE.md` `src/spreads/` section · `SETUP.md` §16 if operator-facing · root `CLAUDE.md` spreads-fence section if it changes what the package may import |

The goal: a user reading `README.md` or `ARCHITECTURE.md` should always get an accurate picture
of the current codebase, not a stale one.

## Running this repo in opencode

Sessions run in either **Claude Code** or **opencode** (the fallback when Claude usage limits are
hit, against Ollama Cloud models). opencode's instruction loader looks for `AGENTS.md`, then
`CLAUDE.md`, then `CONTEXT.md` at each directory level and stops at the first match it finds — so
this file is first-class there, not a workaround. **Never add an `AGENTS.md` anywhere in this
repo** — one anywhere in the walk-up chain would silently blank this file (and every invariant
above) for any opencode session started at or below it. **Do not run opencode's `/init` here** — it
writes an `AGENTS.md`, which at the root would do exactly that.

| File | Role |
|---|---|
| `opencode.json` | Ollama Cloud provider config (`:cloud`-tagged models, routed to Ollama's datacenter), the `instructions` list, `git push` / `reset --hard` / `clean` gated behind a confirmation prompt |
| `.opencode/ibkr-flow.md` | The operating-protocol delta for opencode — loaded into every session via `instructions`; this file (`CLAUDE.md`) remains authoritative on what the invariants *are* |
| `.opencode/agent/ibkr.md` | Primary agent (`temperature: 0.1`) restating the core invariant, the fence, and the analytics-tier split so a fresh opencode session can't drift from them |
| `.opencode/plugin/session-checks.js` | Mirrors the `PostToolUse` hook below via `tool.execute.after` — same reminder, same non-test-`.py` file match, still advisory only |

**Don't confuse this with the production Ollama backend.** `src/claude/ollama_runner.py`
(`config/settings.yaml → claude.backend: "ollama"`, see `SETUP.md` §14) runs a small **local** model
(`qwen3.5:4b` — Task 10, see `SETUP.md` §14 "Model choice" for the evaluated alternatives; no
`:cloud` tag) as the trading pipeline's own strategist reviewer at runtime —
an entirely different concern from opencode's Ollama Cloud models. Both talk to the same
`ollama serve` daemon on `localhost:11434`, but the local pulled models serve production review
calls; the `:cloud` models in `opencode.json` exist only for interactive coding sessions and require
`ollama signin` separately from anything the trading pipeline uses.

**What does not carry over is enforcement, though there is little to lose.** The `PostToolUse` hook
in `.claude/settings.json` fires after every Write/Edit of a non-test `.py` file and injects a
reminder to check the doc-update trigger table above — it only ever adds context, it cannot block
task completion, in Claude Code either. So opencode's lack of a hook mechanism here costs less than
it would in a repo whose enforcement is a blocking `Stop` hook: `.opencode/plugin/
session-checks.js` reproduces the same reminder, but either way, nothing in either harness can force
the update — run the pytest/ruff/mypy commands in `## Change workflow` and re-check the trigger
table yourself before calling a task done.

opencode loads config once at startup and does not hot-reload it; restart the session after editing
`opencode.json` or any file under `.opencode/`.

## Core invariant — never violate

**The Rules Engine (`src/engine/risk_engine.py`) is the only path to order execution, and it is
deterministic Python with NO LLM involvement.** Claude reviews and prioritizes; it must never
place, size, or gate an order. A hallucinated or malformed Claude response must be unable to reach
the broker. The risk gate runs twice: once at decision time, once again at order-send time against
a fresh quote.

## The fence — the enrichment learning loop may not touch the deterministic layer

`src/claude/eval/` closes a read-only feedback loop around Claude's reviews: an **outcome ledger**
(`ledger.py`, `verdict_ledger`) logs every reviewed candidate's signals, verdict, and the
deterministic baseline; a **reconciler** (`reconcile.py`) back-fills the realized outcome on close;
**assignment auto-detection** (`assignment.py`) catches assignments the reconciler alone would miss;
and **score-vs-outcome analysis** (`score_metrics.py`, N22) buckets `blended_score` (and its
components) against realized win rate/P&L — evidence a human reads to decide, by hand, whether
`scoring_weights.yaml` should change.

**The fence is absolute:** none of this reaches the risk engine, `scoring_weights.yaml`,
`risk_limits.yaml`, or position sizing, all of which remain **human-edited config** — nothing in
`eval/` or `skills/` is importable from, or reachable by, the engine/execution/sizing path. When
extending this area: never let the ledger, the reconciler, or a score-vs-outcome finding feed a
gate, weight, or contract count directly. The guarantee is enforced by
`tests/test_eval_skills.py::test_skills_never_reach_the_engine` (checks for `src.claude.eval`/
`src.claude.skills` imports reaching the engine/execution/strategies path; carries a documented
one-way exception for `src.claude.memory`'s outcome-recording, which execution writes to but never
reads a decision from) — keep it green.

**Removed 2026-08-10** (see `STATUS.md` "Removed 2026-08-10"): the skill-proposal loop that used to
draft reasoning playbooks from this labeled history (`src/claude/skills/`, `scripts/propose_skill.py`,
`scripts/skills.py`) and verdict-EV scoring (`src/claude/eval/metrics.py`, `scripts/evaluate_verdicts.py`)
were both deleted — the verdict they measured is deliberately inert in auto mode and needed years of
closed trades to produce a meaningful held-out score. The outcome ledger and reconciler above were
kept; they are cheap and still useful. There is no promotion mechanism to gate anymore — everything
`eval/` produces is read by a human, never auto-applied.

## Analytics tiers — which signals may influence ranking

`src/analytics/` is split into two tiers, and the split is load-bearing:

- **Deterministic tier** — `iv.py`, `technicals.py`, `fundamentals.py`, `liquidity.py`,
  `realized_vol.py`, `black_scholes.py`, `price_data.py`, `fair_value.py`. These may feed
  `engine/`, the strategy screens, and position sizing.
- **Enrichment tier** — `sentiment.py`, `sector_context.py`, `market_conditions.py` (the macro
  backdrop). These reach the Telegram cards and the reasoning prompt **only**. They must never be
  imported by `engine/`, `execution/`, or `strategies/`.

The same enrichment-tier rule extends outside `src/analytics/`: `src/claude/news_context.py`
(builds the strategist prompt's `=== NEWS ===` block) and `src/claude/ollama_tools.py` (the
bounded tool-calling research turn the local Ollama reviewer may run before judging — Task 11),
plus their keyless data-layer backend `src/data/google_news_backend.py`, reach the prompt and the
local reviewer only — never `engine/`, `execution/`, or `strategies/`. Enforced by
`tests/test_eval_skills.py::test_news_and_tool_research_never_reach_the_deterministic_layer`.

The trap: `analytics/fair_value.py` produces the ideal-price zone, and its output reaches the
deterministic layer through **two different fields of the same `IdealZone`, doing two different
jobs** — keep them straight:

- **`min_credit` gates.** Since D2 (remediation Task 5), `risk_engine.validate_candidates` rejects
  any candidate whose `premium` falls below `cand.ideal.min_credit` — Black-Scholes fair value at
  *realised* vol (HV30) plus `ideal_zone.min_credit_edge_pct` — with the reason
  `premium_below_fair_value`, under `income.require_vrp_edge` (ships `true`). The CSP and CC
  generators run the same check themselves so the operator sees the reason on the card. **Rolls
  are scoped out of this gate** (with the ROC and annualized-yield floors): a defensive roll books
  `roc_pct = 0.0` and deliberately pays under the new strike's fair value, so the gate rejected
  every one of them at the approval-queue re-gate — `strategies/rolling.py`'s own `max_debit` /
  `min_delta_reduction` bounds are a roll's real economic control, and its `ideal` stays populated
  for the card but no longer rejects. A missing zone is data-unavailable and never rejects.
- **`zone_fit` only ranks, and still ships at `0.0`.** The separate `fair_value.zone_fit_score`
  hook blends into `technical_score` under the `zone_fit` weight in `scoring_weights.yaml`, which
  is `0.0` for both strategies — strike placement changes no ranking until a human raises it.

Both put `fair_value.py` firmly on the deterministic side — so it may read technicals, IV,
fundamentals, and Black-Scholes and nothing else. **That constraint matters more now than it did
when the zone was display-only:** a sentiment or macro term added to `fair_value.py` would no longer
merely reorder candidates, it would move `min_credit` and let news tone and crowd sentiment
**reject a trade outright**. Enforced by
`tests/test_eval_skills.py::test_fair_value_stays_in_the_deterministic_tier` and
`::test_macro_never_reaches_the_engine` — keep both green.

`fair_value.py` still has no reject path of its own: it computes and returns numbers, and the Rules
Engine is what refuses the order. The Rules Engine remains the sole path to an order.

### The third, read-only tier — `src/reporting/`

`src/reporting/` is downstream of everything and upstream of nothing. It holds the **paired
realised-P&L accounting rule** (`legs.py` — `fill_economics` and `classify_outcome`, **moved
verbatim** out of `src/claude/eval/reconcile.py` in P3-P4 M4 Task 4.1 so the reconciler and the
reporting layer share one implementation; `reconcile.py` imports them from there) plus the
read-only P&L builders over the trading DB (`pnl.py` — legs, campaigns, summary, equity curve).
It also holds `trade_ledger.py` — the whole-account trade-ledger builder (orders → FIFO trades →
outcomes/rolls/orphans, stock lots and wheel-adjusted cost basis, ticker roll-ups, FX, and the
USD portfolio summary; docs/superpowers/plans/2026-10-05-trade-ledger.md, Tasks 1-12). It is
read-only, like `pnl.py` — same no-writes rule, same tier. It reads the whole book, including
enrichment-side tables, which is why it stays on the read side of the tier line exactly as
`src/api/` and `src/research/` do:

- `src/reporting/` imports nothing from `src.claude`;
- `src/engine/`, `src/execution/` and `src/strategies/` may never import `src.reporting`.

Both asserted in `tests/test_web_fence.py` — `test_reporting_never_writes_anything` already
covers `trade_ledger.py` (it globs every file under `src/reporting/`), since the builder has no
`session.add`/`session.merge`/`session.delete`/`session.commit` call of its own. The one
inversion the fence allows: `src/claude/eval/reconcile.py` imports the neutral read-only
accounting module — the fence stops `eval/` reaching the **engine**, not `eval/` importing a
read-only module.

### The `src/ledger/` fence — the only writer of the broker-truth ledger tables

`src/ledger/` (`contracts.py`, `activity_csv.py`, `flex.py`, `live.py`, `ingest.py`,
`annotations.py`, `sheets_mirror.py`, `state.py`) is the **only** writer of the six
`broker_*`/ledger tables (`BrokerExecutionRow`, `BrokerCashEventRow`, `BrokerCorporateActionRow`,
`FxRateRow`, `LedgerImportRunRow`, `TradeAnnotationRow`) — every execution/CSV/Flex/live feed
normalises to a `ParsedStatement` and lands through `src/ledger/ingest.py::ingest`, never through
a second writer. The same fence applies here as everywhere else in the reporting tier: nothing
in `src/ledger/` is imported by `engine/`, `execution/`, or `strategies/`, and `src/ledger/`
imports nothing from `src.claude`, directly or at import time: `live.py` imports `src.execution.reconciliation`'s `_req_executions_bounded` lazily, inside its own wrapper, because a module-level import loaded `src.execution` and, through it, `src.claude.memory` into every process that attaches the ledger's commission hook, the spreads service included. Only the RTH sweep, which runs only inside `approval_service`, reaches it. `src/ledger/live.py` is the one place `ib_async` objects
(`Fill`/`Execution`/`CommissionReport`) are converted to the ledger's own `ParsedExecution`
schema — never passed across a module boundary raw, and never elsewhere in the ledger code.
Enforced by `tests/test_web_fence.py::test_the_trading_path_never_imports_the_ledger` (grepping
engine/execution/strategies for `src.ledger`/`trade_ledger`), `::test_the_ledger_never_imports_the_enrichment_layer`
and `::test_only_the_ledger_package_writes_the_ledger_tables` (only `src/ledger/` constructs the
six writer rows) — keep them green. The web `/ledger/*` pages are read-only over `GET /ledger/*`;
their two edits (annotations, corporate-action reviewed) and the CSV upload are intents drained by
`approval_service`, like every other web write.

### The spreads fence — `src/spreads/` is a second system, not a wheel module

`src/spreads/` (docs/superpowers/plans/2026-10-07-daily-credit-spreads.md) trades daily SPY
credit spreads in the **same IBKR account and Gateway** as the wheel, with its own process
(`scripts/run_spreads.py`, clientId 30), its own SQLite file (`data/spreads.db`, its own
`SpreadsBase`), its own config (the operator's private `config/spreads.yaml`; the repo commits
`config/spreads.example.yaml`) and its own Telegram thread. The rules:

- **Book = underlying.** `config/spreads.yaml → book_underlyings` (SPY, SPX, XSP) must never appear in
  `config/universe.yaml` — `Config._spreads_isolated` refuses the overlap at load. Positions
  carry no order tag and IBKR nets same-contract positions across clientIds, so the underlying
  is the only sound separator; order ids are unique per clientId only and are never used.
- **The wheel learns about the spreads book only through `src/common/books.py`.** Three places:
  `get_positions()` drops spreads contracts by default (only `scripts/healthcheck.py` passes
  `include_spreads=True`), the rules engine rejects `reserved_for_spreads_book`, and ledger
  ingest tags `book="spreads"`. The web universe override refuses those underlyings too (`422`
  at both routes, refused in the drain, dropped by the composer), and the wheel's fill recovery
  requires the underlying to match even on an order-id match. No module outside `src/spreads/`
  imports `src.spreads`.
- **`src/spreads/risk.py::validate` is the spreads system's only gate** — deterministic, no LLM,
  run at decision time and again at send time on fresh quotes. The core invariant holds
  unchanged: nothing an LLM produces reaches a spreads order (the package imports nothing from
  `src.claude`). The entry trigger (`src/spreads/tape.py`) is deterministic too; it only decides
  *when* the chain is fetched and *which side* is offered to the gate, never a size.
- `src/spreads/` imports nothing from `src.claude`, `src.engine`, `src.execution`,
  `src.strategies`, `src.orchestrator`, `src.monitor`, `src.notify`, `src.reporting`, `src.api`,
  `src.research`; only `src/spreads/service.py` may import `src.ledger` / `src.storage`.
- At most `max_market_data_lines` (30) open lines; with spreads enabled,
  `market_data.chain_batch_size + max_market_data_lines + reserved_monitor_lines ≤
  market_data.max_concurrent_lines` is enforced at load. `req_fresh_mkt_data` only;
  `LimitOrder` only.
- In paper mode the broker is the truth for what a close may send: never close more than the
  broker holds, never send a second close while one is working (see `service.py`).
- `run()` idles when `LIVE_TRADING=true` — shadow/paper only until a separate live plan exists.

Enforced by `tests/test_spreads_fence.py` (imports parsed with `ast`, so `from src import
engine`, relative imports and `importlib` count, plus a `sys.modules` check that the spreads
process loads no wheel layer even transitively), `tests/test_wheel_spreads_isolation.py` and
`tests/test_spreads_config.py` — keep them green.

### The news fence — `src/news/` is enrichment with its own database

`src/news/` (docs/superpowers/specs/2026-10-09-news-thread-design.md §10) runs as its own process
(`scripts/run_news.py`, **no IBKR connection, no clientId**), with its own SQLite file
(`data/news.db`, its own `NewsBase`), its own config (private `config/news.yaml`; the repo commits
`config/news.example.yaml` and the reference playbook `config/news_playbook.yaml`) and its own
Telegram thread (`TELEGRAM_THREAD_NEWS`). It explains news; it never trades. The rules:

1. `src/engine/`, `src/execution/`, `src/strategies/` and `src/spreads/` never import `src.news`.
2. `src/news/` imports nothing from `src.engine`, `src.execution`, `src.strategies`, `src.spreads`,
   `src.orchestrator` or `src.notify.approval_service`. Reading the deterministic analytics tier
   (technicals, IV, realized vol, price data, sector context, market conditions) is allowed —
   enrichment may read deterministic, never the reverse.
3. Only `src/news/` constructs `NewsBase` rows: `data/news.db` has one writer package.
4. `src/analytics/sentiment.py` reads only the deterministic `news_items` columns
   (`det_sentiment`, `published_at`, `fetched_at`, `tickers`, `cluster_id`, `title`) through
   `src.news.store.readonly` — never `news_posts`, never an `Explanation`. **No LLM output reaches
   `ScoreCard.sentiment_score`, the risk engine or sizing** (spec D3, permanent). FinBERT is
   allowed because it is deterministic classification, not generation.
5. `src.news` is on `tests/test_eval_skills.py`'s enrichment list.
6. `src/api/` reaches `news.db` only through `src/api/news_db.py`'s read-only engine and the
   Session-parameterised `src/news/store/queries.py`; it never imports `src.news.store.session`.
   The API still writes exactly one table (`app_commands`).
7. The only `src.news` module `src/notify/` may import is `src.news.briefs` (the `/news` command
   and the `news_brief` drain handler) — import it as `import src.news.briefs as briefs`, since an
   `ast` walk records `from src.news import briefs` as `src.news`. No LLM, ingest or publish code
   loads into `approval_service`.

Every number on a news card comes from deterministic code (the fact sheet, the playbook, the
measured reaction); the LLM only writes the explanation, which `src/news/grounding.py` checks
against those numbers before it posts. Enforced by `tests/test_news_fence.py`
(`test_trading_path_never_imports_news`, `test_news_never_imports_the_trading_path`,
`test_only_src_news_constructs_news_rows`, `test_notify_imports_only_the_brief_queue`,
`test_api_never_imports_the_rw_engine`, `test_api_process_never_loads_the_rw_engine`,
`test_sentiment_reads_only_deterministic_news_columns`, `test_brief_queue_stays_light`),
`tests/test_eval_skills.py::test_news_and_tool_research_never_reach_the_deterministic_layer` and
`tests/test_web_fence.py` — keep them green.

## Reference documentation

- **`ib_async_documentation.md`** (root) is the **official ib_async documentation** for this
  project. Treat it as the source of truth for the IBKR API surface — connection patterns,
  `reqMktData`/`reqHistoricalData`/`reqSecDefOptParams`, contract objects (`Stock`, `Option`),
  order types, and event handling. Consult it before guessing IBKR API signatures.
- The library is `ib_async` (the maintained successor to `ib_insync`). Import as
  `from ib_async import ...`. Do **not** add the legacy `ib_insync` package.

## Architecture (see ARCHITECTURE.md for the full walkthrough)

```
orchestrator → market data (ibkr/) → analytics → strategies → decision engine
            → RULES ENGINE (gate) → Claude review (enrich) → Telegram approval
            → execution (re-validate vs rules + live quote) → IBKR
```

- Modules communicate **only** through the Pydantic schemas in `src/common/schemas.py`. Do not
  pass raw `ib_async` objects across module boundaries — convert to schemas first.
- **SQLite (via SQLAlchemy) is the integration backbone**: every pipeline stage persists, so runs
  are resumable/inspectable and Telegram/dashboard read one source of truth.
- Intraday monitoring is **event-driven** (ib_async events), not the batch pipeline.

## Conventions

- Python ≥ 3.12. Config in `config/*.yaml`; **secrets only in `.env`** (gitignored) — never log or
  commit them. `settings.yaml`, `risk_limits.yaml`, `scoring_weights.yaml`, `universe.yaml`,
  `spreads.yaml` and `news.yaml` are the operator's **private, git-ignored** copies; the repo commits
  `config/<name>.example.yaml` (`news_playbook.yaml` is committed reference data, not private).
  Never `git add` a private config file or anything holding an account number; tests read the
  examples (`IBKR_CONFIG_USE_EXAMPLES=1` in `tests/conftest.py`).
- All tunables (deltas, DTE, IV thresholds, weights, concentration limits) live in
  `config/risk_limits.yaml` and `config/scoring_weights.yaml`. Change behavior there, not in code.
- One **clientId per process** (`config/settings.yaml → ibkr.client_ids`). The trading_skills MCP
  (20) and dashboard (21) use their own. Never reuse an id across concurrent processes.
- Money/quantities are explicit; option premiums are **per share** (×100 for contract value).
- Type-hint everything; keep modules small and single-purpose matching the `src/` layout.
- **analytics/strategies/engine never call `yfinance.*` directly; they go through `src/data/`**
  (Phase 2 provider abstraction). The factories in `src/data/factory.py` read
  `config/settings.yaml → data.*` to pick the active backend and cache it process-wide. A
  future FMP/Polygon swap is a config change, not a rewrite of every analytics module. IBKR is
  *not* a provider — it's the broker + execution path (`src/ibkr/`) and stays untouched (the
  IBKR greeks fallback in `src/ibkr/market_data.py` still calls `yfinance` directly, by design).
  The `src/backtest/` harness is also out of scope — it's an offline tool, not the live
  pipeline.

## Safety

- **Paper first.** Live trading is gated behind `LIVE_TRADING=true` in `.env` AND the live port.
  The connection manager prints a loud mode banner — keep it.
- Use `LimitOrder` at mid, never `MarketOrder`, for option entries.
- `qualifyContracts` every option contract before sending an order.
- **Never call `ib.reqMktData` directly — use `src.ibkr.market_data.req_fresh_mkt_data`.** ib_async
  keeps one `Ticker` per contract per connection and `cancelMktData` doesn't clear it, so a plain
  re-subscription hands back the previous subscription's bid/ask/greeks and every "quote ready?"
  poll passes instantly on stale data (2026-09-30: every approved order failed the send-time re-gate).
- Respect the market-data line limit (~100): batch option-chain requests and cancel between
  batches (`config/settings.yaml → market_data`).

## Commands

```bash
python -m scripts.healthcheck        # connect + read account/positions
python -m pytest                     # tests (IBKR is mocked; no TWS needed)
ruff check . && ruff format .        # lint + format
mypy src                             # type check
```

Requires TWS or IB Gateway running with the API enabled (paper port 7497 by default) for anything
that touches IBKR. Tests do not require it.

## Change workflow

The build is feature-complete; there are no remaining phases. For any change:

1. **Verify** — run the full quality gate before declaring completion:
   ```bash
   python -m pytest -q    # all tests must pass
   ruff check .           # no lint issues
   mypy src               # no type errors
   ```
2. **Add/adjust tests** for the behaviour you changed — the suite is the safety net, since the system
   is paper-only and IBKR is mocked.
3. **Update docs** per the mandatory doc-update table above. If you build, defer, or change the status
   of a feature/limitation, reflect it in **`STATUS.md`**.
4. **Executing a plan** under `docs/superpowers/plans/`: keep the plan's **Progress log** current
   without being asked. After each task, tick its step checkboxes and update its row: status,
   commits, gate result, date, and every ruling (any deviation from the task text, and why). Commit
   that with the task. A plan with no Progress log gets one under its title. A new session resumes
   from that log and `git log`, never from memory. The `.superpowers/sdd/` ledger is git-ignored
   scratch, not the record.

## The web layer and the trading database

The API reads the trading database read-only and writes exactly one table, `app_commands`,
through `src/api/commands.py`. No other module may import `get_command_engine`. Enforced by
`tests/test_web_fence.py`.

Every web action is an intent drained by `approval_service`, never a direct mutation from the API
process: the drain's approve/reject handlers call `_process_button` unchanged, never reimplement
it, and the Rules Engine remains the only path to an order — the web layer can propose (approve,
promote, roll_request, universe edits) but cannot gate or size anything itself.

Universe overrides (P2 M7, `src/common/universe.py::effective_universe()`) cover `would_own` and
`watchlist` only. `sectors` stays file-only — `config/universe.yaml` — precisely so the risk
engine's concentration limits stay unreachable from the web, at every layer (API `422`, the
schema's `Literal` type, and the composer's byte-identical passthrough for every other key).

P3 and P4 (portfolio, P&L, and `GET /pnl/system`'s read behind the `src/claude/eval/` fence)
added no write beyond the `refresh` command (Task 1.4) — the API still writes exactly one table
(`tests/test_web_fence.py::test_the_api_still_writes_exactly_one_table`, P3-P4 M6 Task 6.3).

## How Claude is invoked in production (not the API)

`src/claude/runner.py` shells out to `claude -p "<prompt>" --output-format json`, passing context
(top candidates + portfolio summary + a specific question) and parsing a structured `ClaudeReview`
back. If the CLI is unavailable or output is unparseable, the pipeline **falls back** to shipping
the deterministic Rules-Engine-approved list — Claude is enrichment, never a dependency.
