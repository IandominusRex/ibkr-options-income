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
| **`README.md`** | Anyone | One-page overview: what the system does, quick start, layout table, safety summary |
| **`SETUP.md`** | New users | Complete step-by-step guide from fresh machine to first live trade |
| **`ARCHITECTURE.md`** | Non-technical users and new contributors | Plain-English walkthrough of every folder, how modules interact, the pipeline, the process/clientId model, data-flow schemas, key invariants, and operational risk handling |
| **`STATUS.md`** | Claude and developers | What's built vs. deliberately not built, tech stack, unenforced config, items needing live verification, the live-cutover gate |
| **`UNIVERSE_RESEARCH.md`** | Claude Code + headless `claude -p` | Deep-research reference for every ticker: tier, verified prices/IV ranks (Jun 2026), CC vs CSP appropriateness, leveraged-ETF assignment rules, IV rank methodology, data-quality warnings. A compact version is injected into every trade-review prompt via `src/claude/prompts/strategist.py`. |
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
| New file or module added | `README.md` layout table · `ARCHITECTURE.md` folder guide |
| Existing module renamed, moved, or deleted | Both above |
| New config key added to any YAML | `ARCHITECTURE.md` config/ section · `SETUP.md` if it affects setup |
| New script entrypoint added | `SETUP.md` scripts table · `README.md` layout table |
| **New Telegram command registered** in `approval_service.py` | `ARCHITECTURE.md` commands table (src/notify/ section) · `SETUP.md` "Using the Telegram bot" commands table · `README.md` Telegram commands table |
| **New formatter function added** to `formatters.py` | `ARCHITECTURE.md` src/notify/ table description |
| **New Pydantic schema** added to `schemas.py` | `ARCHITECTURE.md` src/common/ + data-flow sections |
| **New storage model** (ORM class) added to `models.py` | `ARCHITECTURE.md` src/storage/ section |
| Feature built / deferred, or a limitation changes | `STATUS.md` (what's built / not built / known limitations) |
| Bug fix that changes behaviour users would notice | `SETUP.md` troubleshooting table if relevant |
| **Ticker added/removed from `universe.yaml`** | `UNIVERSE_RESEARCH.md` — add/remove ticker section · `src/claude/prompts/strategist.py` `_UNIVERSE_CONTEXT` table |

The goal: a user reading `README.md` or `ARCHITECTURE.md` should always get an accurate picture
of the current codebase, not a stale one.

## Core invariant — never violate

**The Rules Engine (`src/engine/risk_engine.py`) is the only path to order execution, and it is
deterministic Python with NO LLM involvement.** Claude reviews and prioritizes; it must never
place, size, or gate an order. A hallucinated or malformed Claude response must be unable to reach
the broker. The risk gate runs twice: once at decision time, once again at order-send time against
a fresh quote.

## The fence — the enrichment learning loop may not touch the deterministic layer

The verdict learning loop (`src/claude/eval/` + `src/claude/skills/`) closes the feedback cycle
around Claude's reviews: an **outcome ledger** (`verdict_ledger`) logs every verdict alongside the
signals it saw and the deterministic baseline; a **reconciler** back-fills the realized outcome on
close; **verdict scoring** measures calibration + EV against held-out periods; and a **skill loop**
lets Claude draft reasoning playbooks from that labeled history.

**The fence is absolute:** promoted skills influence **verdict and ranking only**. They reach Claude
solely through the strategist/roll prompt builders via `render_active_skills()`. The risk engine,
`scoring_weights.yaml`, `risk_limits.yaml`, and all position sizing remain **human-edited config** —
nothing in `eval/` or `skills/` is importable from, or reachable by, the engine/execution/sizing
path. When extending this area: never let a skill, the ledger, or the metrics feed a gate, weight,
or contract count. The guarantee is enforced by `tests/test_eval_skills.py::test_skills_never_reach_the_engine`
— keep it green. Skill **promotion is always human-gated** (a `scripts.skills promote` file move);
the proposer drafts, it never activates.

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
  commit them.
- All tunables (deltas, DTE, IV thresholds, weights, concentration limits) live in
  `config/risk_limits.yaml` and `config/scoring_weights.yaml`. Change behavior there, not in code.
- One **clientId per process** (`config/settings.yaml → ibkr.client_ids`). The trading_skills MCP
  (20) and dashboard (21) use their own. Never reuse an id across concurrent processes.
- Money/quantities are explicit; option premiums are **per share** (×100 for contract value).
- Type-hint everything; keep modules small and single-purpose matching the `src/` layout.

## Safety

- **Paper first.** Live trading is gated behind `LIVE_TRADING=true` in `.env` AND the live port.
  The connection manager prints a loud mode banner — keep it.
- Use `LimitOrder` at mid, never `MarketOrder`, for option entries.
- `qualifyContracts` every option contract before sending an order.
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

## How Claude is invoked in production (not the API)

`src/claude/runner.py` shells out to `claude -p "<prompt>" --output-format json`, passing context
(top candidates + portfolio summary + a specific question) and parsing a structured `ClaudeReview`
back. If the CLI is unavailable or output is unparseable, the pipeline **falls back** to shipping
the deterministic Rules-Engine-approved list — Claude is enrichment, never a dependency.
