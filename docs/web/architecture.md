# Web architecture

## Overview

The web layer is a Next.js frontend (`web/`) talking to a FastAPI backend (`src/api/`).
The backend runs as a separate process (`scripts/run_api.py`, port 8787) with no IBKR
connection and no clientId — it cannot reach the broker, by construction.

## The two-engine model (P2)

The API uses two SQLAlchemy engines on the same trading database
(`data/income_system.db`):

1. **The read-only engine** (`get_trading_engine`) opens the database via SQLite's
   `mode=ro` URI. Every route reads through this engine. An accidental INSERT raises
   `OperationalError` at the database layer — the guarantee is structural, not
   conventional.

2. **The write-scoped command engine** (`get_command_engine`) opens the same file
   read-write, but is imported from `src/api/commands.py` only. A `before_flush`
   listener (`WriteFenceViolation`) rejects any flush targeting a table other than
   `app_commands`, naming the offending table. `tests/test_web_fence.py` asserts no
   other module imports `get_command_engine`.

The asymmetry is deliberate: **reads go through the read-only engine even for
commands** (`get_status` reads through `trading_session`, not `command_session`). The
write handle is used for inserts and nothing else.

```
console ──POST /commands──▶ API ──write-scoped engine──▶ app_commands (status=pending)
                             │
                             └────mode=ro engine───────▶ approvals · orders · fills
                                                         risk_verdicts · position_snapshots
                                                         system_settings · universe_overrides

approval_service._command_drain_loop        (every execution.poll_interval_seconds)
   approve / reject      → _process_button(approval_id, action)        [existing, unchanged]
   promote               → re-run single-ticker → gate → raise approval
   roll_request          → chain → generate_roll_candidates → queue_roll_for_approval
   halt / resume         → set_halted(True/False, reason)
   set_autonomy          → set_autonomy_level
    universe_add / remove → universe_overrides
    refresh               → get_positions + account → portfolio_snapshots (P3-P4 M1)
```

The drain runs inside `approval_service` (the process that holds the exec connection),
so applying a command — mutating `ApprovalRow`, inserting `OrderRow`, marking the
command `applied` — is one transaction with no partially-applied state to reason
about (spec §4.2). The drain writes `command_drain_heartbeat` to `system_settings`
at the end of every cycle (after the work, never before), so M2's `/options/controls`
can tell an operator their click is queued and nothing is picking it up.

## The API proxy

`web/lib/api.ts` fetches from `/api`, not from the upstream API directly. The proxy at
`web/app/api/[...path]/route.ts` injects `Authorization: Bearer ${API_TOKEN}` server-side.
`API_TOKEN` has no `NEXT_PUBLIC_` prefix, so Next.js cannot inline it into the client
bundle. This works under `next start` behind Tailscale; it does not survive a
Vercel-hosted frontend (a route handler in Vercel's cloud cannot reach a private API).

## Databases

| Database | Owner | API access |
|---|---|---|
| `data/income_system.db` | the trading system | read-only (`mode=ro` URI) for every route; write-scoped for `app_commands` only |
| `data/research.db` | the research worker | read-write (the API's research routes read through a separate session) |

The two are separate `Base`/engine pairs so `create_all()` can never cross-build.

## Import fence

The web layer knows about the trading system. The trading system does not know the web
layer exists. `tests/test_web_fence.py` enforces this by grepping `engine/`,
`execution/`, and `strategies/` for `src.api` or `src.research` imports. `src/notify/`
is the exception — the drain loop lives there precisely because it is allowed to know
about both sides.