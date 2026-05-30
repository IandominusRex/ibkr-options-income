# CLAUDE.md — IBKR Options Income System

Guidance for Claude Code when working in this repository.

## What this project is

A **semi-autonomous options-income trading system** for an Interactive Brokers account,
focused on selling **covered calls (CCs)** and **cash-secured puts (CSPs)**. Python does all
deterministic work (scanning, option-chain analysis, IV/Greeks, technicals, fundamentals,
scoring, monitoring, execution). Claude is the **reasoning/strategy layer**, invoked **without the
API** via the Claude Code CLI in headless mode (`claude -p`, JSON in/out) under the user's
subscription.

The authoritative build plan is **`PLAN.md`** (root). Read it before making structural changes.

## Documentation files — what they are and when to update them

| File | Audience | Purpose |
|---|---|---|
| **`README.md`** | Anyone | One-page overview: what the system does, quick start, layout table, safety summary |
| **`SETUP.md`** | New users | Complete step-by-step guide from fresh machine to first live trade |
| **`ARCHITECTURE.md`** | Non-technical users and new contributors | Plain-English walkthrough of every folder, how modules interact, the pipeline, and key invariants |
| **`PLAN.md`** | Claude and developers | Full technical build plan, phase history, architecture diagram, risk register |
| **`CLAUDE.md`** | Claude Code | Invariants, conventions, safety rules, phase workflow — read before any structural change |
| **`Improvements.md`** | Claude and developers | Known bugs, code audit findings, and improvement notes |
| **`ib_async_documentation.md`** | Claude and developers | Authoritative IBKR API reference — consult before guessing any ib_async signature |

### Mandatory doc-update rule

> **This rule is enforced by a project hook.** A reminder fires after every Python file edit.
> Do not declare a task complete until docs are consistent with the code.

**After every prompt that results in a code change, review and update the relevant documentation
files before declaring the task complete.** Map the change to the table below and act on every
row that matches:

| What changed | Files to update |
|---|---|
| New file or module added | `README.md` layout table · `ARCHITECTURE.md` folder guide · relevant section of `PLAN.md` |
| Existing module renamed, moved, or deleted | All three above |
| New config key added to any YAML | `ARCHITECTURE.md` config/ section · `SETUP.md` if it affects setup |
| New script entrypoint added | `SETUP.md` scripts table · `README.md` layout table |
| **New Telegram command registered** in `approval_service.py` | `ARCHITECTURE.md` commands table (src/notify/ section) · `SETUP.md` "Using the Telegram bot" commands table · `README.md` Telegram commands table |
| **New formatter function added** to `formatters.py` | `ARCHITECTURE.md` src/notify/ table description |
| **New Pydantic schema** added to `schemas.py` | `ARCHITECTURE.md` src/common/ section |
| **New storage model** (ORM class) added to `models.py` | `ARCHITECTURE.md` src/storage/ section |
| Phase completed | Phase completion workflow below (mark `PLAN.md`, write handoff) |
| Bug fix that changes behaviour users would notice | `SETUP.md` troubleshooting table if relevant · note in `Improvements.md` |

The goal: a user reading `README.md` or `ARCHITECTURE.md` should always get an accurate picture
of the current codebase, not a stale one.

## Core invariant — never violate

**The Rules Engine (`src/engine/risk_engine.py`) is the only path to order execution, and it is
deterministic Python with NO LLM involvement.** Claude reviews and prioritizes; it must never
place, size, or gate an order. A hallucinated or malformed Claude response must be unable to reach
the broker. The risk gate runs twice: once at decision time, once again at order-send time against
a fresh quote.

## Reference documentation

- **`ib_async_documentation.md`** (root) is the **official ib_async documentation** for this
  project. Treat it as the source of truth for the IBKR API surface — connection patterns,
  `reqMktData`/`reqHistoricalData`/`reqSecDefOptParams`, contract objects (`Stock`, `Option`),
  order types, and event handling. Consult it before guessing IBKR API signatures.
- The library is `ib_async` (the maintained successor to `ib_insync`). Import as
  `from ib_async import ...`. Do **not** add the legacy `ib_insync` package.

## Architecture (see PLAN.md for the full diagram)

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
python -m scripts.healthcheck        # Phase 0 acceptance: connect + read account/positions
python -m pytest                     # tests (IBKR is mocked; no TWS needed)
ruff check . && ruff format .        # lint + format
mypy src                             # type check
```

Requires TWS or IB Gateway running with the API enabled (paper port 7497 by default) for anything
that touches IBKR. Tests do not require it.

## Phase completion workflow

**This workflow is mandatory after every phase.** Do not mark a phase done without completing
all three steps.

1. **Verify** — run the full quality gate before declaring completion:
   ```bash
   python -m pytest -q    # all tests must pass
   ruff check .           # no lint issues
   mypy src               # no type errors
   ```

2. **Mark PLAN.md** — prefix the completed phase bullet with `✅`.

3. **Write `docs/PHASE<N+1>_HANDOFF.md`** — this file MUST be created for every completed phase.
   It is the primary context document for the next implementation session. Model it on
   `docs/PHASE1_HANDOFF.md` and include all of these sections:
   - *Where things stand* — what files/functions/tables now exist that Phase N+1 can reuse
   - *Phase N+1 goal + acceptance criterion* — one concrete, testable "done when" statement
   - *Files to create* — exact paths
   - *Implementation notes* — the parts that bite: gotchas, API quirks, ordering constraints,
     async/sync boundaries, config keys to read, schema fields to populate
   - *Testing approach* — how to unit-test without live TWS/network
   - *Open decisions* — choices that must be made before or during implementation

   Be specific: name exact functions, config keys, schema fields, and known failure modes so
   the next session can start coding immediately without re-deriving context.

## How Claude is invoked in production (not the API)

`src/claude/runner.py` shells out to `claude -p "<prompt>" --output-format json`, passing context
(top candidates + portfolio summary + a specific question) and parsing a structured `ClaudeReview`
back. If the CLI is unavailable or output is unparseable, the pipeline **falls back** to shipping
the deterministic Rules-Engine-approved list — Claude is enrichment, never a dependency.
