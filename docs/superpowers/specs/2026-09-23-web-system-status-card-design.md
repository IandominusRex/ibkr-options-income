# Design — Web System Status Card

**Date:** 2026-09-23
**Status:** Approved design, pending implementation plan
**Supersedes:** nothing. Complements `web/CLAUDE.md` (the web layer's conventions) and
`ARCHITECTURE.md` (folder guide, data-flow schemas).

---

## 1. Context

The web console (`web/`) has no single place that tells an operator whether the underlying
system — the four supervised daemons started by `scripts/start.py`, the two SQLite databases,
the data providers, and the IBKR connection itself — is actually running. Pieces of this exist
today but are scattered and none of them render anywhere:

- `GET /health` (`src/api/routers/meta.py`) checks trading-DB and research-DB connectivity and
  returns the data-provider circuit-breaker states (`src/data/breaker.py:breaker_states()`), plus
  the research worker's heartbeat (`src.research.ingest.jobs.read_heartbeat`). Nothing in `web/`
  fetches `/health`.
- `GET /options/controls` (`src/api/routers/options.py:1097`) computes `drain_healthy` by
  comparing `command_drain_heartbeat` (a `system_settings` key written by `drain_once` in
  `src/notify/command_drain.py` after every drain cycle) against twice the poll interval. This is
  surfaced, but only inside the Options console's `<ControlsStrip/>` — not globally.
- The intraday monitor (`src/monitor/intraday.py::IntradayMonitor`) and the IBKR connection state
  itself (`ib_async`'s `ib.isConnected()`, held separately by `approval_service` and
  `intraday_monitor`, one `clientId` each per the core invariant) have **no** signal that reaches
  the API at all today.
- Each of the four supervised daemons plus the one-shot EOD job writes to its own rotating log
  file under `logs/` (`scripts/start.py`'s `SERVICES` dict: `approval.log`, `monitor.log`,
  `api.log`, `research.log`, plus `eod.log`). Lines are already deduplicated and capped at 500
  chars by `_NoiseFilter` (`src/common/logging.py`) at write time, so tailing these files is cheap.

This design adds a status card pinned to the bottom of the left rail (`web/components/shell/
Rail.tsx`) showing one row per tracked system, red/green (plus a third "unknown" state, never a
fourth color — see §4.2) at a glance, and a click-through log view per system.

## 2. Systems tracked (v1 — 7 rows)

| Row | Signal | New backend work |
|---|---|---|
| Trading DB | `/health.trading_db` | none |
| Research DB | `/health.research_db` | none |
| Data providers | `/health.providers`, rolled up to the worst state across providers | none |
| Command drain (approval_service) | existing `command_drain_heartbeat` setting | none (reused) |
| Intraday monitor | new heartbeat, same pattern as the research worker's | **new** |
| Research worker | `/health.worker_heartbeat` | none |
| IBKR connection | new `ibkr_connected` flag on both daemons above | **new** |

No row for `web_api` itself — if the API is down, the whole `/system/status` fetch fails, and
that failure *is* the signal (§5). No row for `eod_report` — it is a scheduled one-shot batch job,
not a thing that is "up" or "down" at a point in time; excluded from v1, revisit if it ever needs
one.

## 3. Backend design

### 3.1 New heartbeat signals

Two new `system_settings` keys (via `src.storage.system_settings.get_setting`/`set_setting`,
the same generic KV table `command_drain_heartbeat`, `execution_halted`, and the autonomy/lease
keys already use — no new table):

- `monitor_heartbeat` / `monitor_ibkr_connected` — written from
  `IntradayMonitor._refresh_subscriptions` (`src/monitor/intraday.py`), which already runs on a
  fixed cadence and already holds `self._ib`. Written unconditionally each cycle (connected or
  not), mirroring the drain heartbeat's "written after the work, so a hung loop cannot look
  healthy" rule.
- `command_drain_ibkr_connected` — written alongside the existing `command_drain_heartbeat` at
  the end of `drain_once` (`src/notify/command_drain.py`), using the `ib: IB | None` parameter
  the function already receives (`ib is not None and ib.isConnected()`).

The "IBKR connection" row in `/system/status` is `ok` only when every daemon that is supposed to
hold a connection reports `ibkr_connected=true` on a fresh heartbeat; `unknown` if a heartbeat
has never been written this run (see §4.2 — this must not read as `down` on a cold start before
the first cycle completes).

### 3.2 `GET /system/status`

New router `src/api/routers/system.py`, `APIRouter(prefix="/system", tags=["system"])`, mounted
in `main.py` next to the others, owner-only (`OwnerUser`, matching `/options/controls`'s
sensitivity — this is internal operational detail, not a research read). Returns the 7 rows above,
each with:

```
{ key, label, state: "ok" | "degraded" | "unknown" | "down", detail, log_key: str | null }
```

`detail` is a short human sentence ("last heartbeat 8s ago", "breaker open since 14:02Z",
"research DB unreachable"). `log_key` is `null` for the two rows with no log file of their own
(Trading DB, Research DB, Data providers, IBKR connection — these are properties, not processes)
and one of `approval` / `monitor` / `research` for the three that are.

State derivation reuses `/health`'s and `/options/controls`'s existing thresholds rather than
inventing new ones — the drain and monitor rows both apply the same "age <= 2x poll interval"
heartbeat-staleness *rule* `/options/controls` already applies to `drain_healthy`, each against
its own process's cadence: `execution.poll_interval_seconds` for the drain, `scheduler.
intraday_poll_seconds` (`src/monitor/intraday.py::IntradayMonitor.start`) for the monitor.

### 3.3 `GET /system/{name}/log?level=warn|info&lines=100`

Same router, owner-only. `name` is validated against a **fixed allowlist**
(`approval`, `monitor`, `research`) mapped to the real paths already defined in `scripts/
start.py`'s `SERVICES` dict — never built from the raw path param, to foreclose path traversal.
`api` is deliberately not in the allowlist (no status row reads its own log — see §2).

Reads the last `lines` (default 100, hard cap ~150) lines of the file via a tail-from-end seek,
server-side filtered to the requested level (`warn` = WARNING and above, the default; `info`
widens to INFO and above). Each line is already <=500 chars from `_NoiseFilter`'s truncation at
write time, so the response stays small without additional server-side truncation logic.

## 4. Frontend design

### 4.1 Placement

`Rail.tsx` becomes a `flex flex-col` container: the existing `<ul>` of `<RailSection/>` rows keeps
its own `overflow-y-auto` and takes `flex-1`; a new `<SystemStatusCard/>` sits below it, outside
the scrollable region, so it stays pinned to the bottom of the viewport regardless of nav-list
length or scroll position — consistent with the 2026-09-23 "Rail stays pinned in place" layout
note already in `web/CLAUDE.md`.

`components/shell/SystemStatusCard.tsx`: `react-query` on `GET /system/status`, `refetchInterval:
20_000`. Each row renders a state dot + label + one-line `detail`, matching the density of
`<RailSection/>` rows above it. No polling for the rows themselves beyond the 20s interval — this
is background chrome, not a live trading surface.

### 4.2 State → color vocabulary

`web/CLAUDE.md`'s dark-only token system is deliberately **tri-tone** (`text-gain` /
`text-loss` / `text-unknown`, "state is never encoded by colour alone" — `text-unknown` also
carries `.hatch` texture). This design does not add a fourth color for "degraded": `ok` → gain,
`down` → loss, and both `degraded` and `unknown` render in the `unknown` tone (hatch texture),
distinguished only by their `detail` text ("breaker open — degraded" vs. "not yet reporting").
This keeps the card visually consistent with `CheckRibbon`/`StageBadge` rather than inventing new
chrome.

### 4.3 Log slide-over panel

Clicking a row with a non-null `log_key` opens a slide-over panel reusing the focus-trap/
`aria-modal` pattern `ConfirmAction` already implements (Escape/cancel close it, focus trapped
while open, focus returned to the trigger on close). Contents: the row's `detail` line, a WARN/
INFO toggle, a monospace scrollable log box, and a manual "Refresh" button. Fetched on open only
— no auto-poll inside the panel, keeping it the "non-bloating" surface the request asked for. A
row with `log_key: null` (Trading DB, Research DB, Data providers, IBKR connection) is not
clickable — there is no log file to show, and clicking should not spawn an empty panel.

## 5. Error handling

- `/system/status` itself unreachable (proxy 502/504, per `web/CLAUDE.md`'s documented fail-soft
  behavior) → the card renders one degraded line ("Status unavailable") instead of 7 blank/
  stale rows, reusing the same `ApiError`-surfacing `apiFetch` already provides everywhere else.
- A heartbeat key that has never been written this run (fresh deploy, daemon not yet through its
  first cycle) → `unknown`, never `down` — a false alarm on cold start is worse than a few seconds
  of "unknown".
- `/system/{name}/log` on a missing file (fresh install, that daemon has never run) → `200` with
  an explicit "no log file yet" case the panel renders as text, not an error state.
- Path safety: the allowlist in §3.3 is the only thing standing between this endpoint and
  arbitrary file reads — no dynamic path construction from the request anywhere in the handler.

## 6. Testing

- Backend: `tests/` gains coverage for `/system/status` (one state per row, mocked signals —
  ok/degraded/unknown/down), `/system/{name}/log` (allowlist rejection, missing-file case, level
  filtering, line cap), and the two new heartbeat writers (`monitor_ibkr_connected` written on
  each refresh cycle, `command_drain_ibkr_connected` written alongside the existing drain
  heartbeat).
- Frontend: `SystemStatusCard.test.tsx` (one test per state's rendering, the degraded-fetch
  fallback) and a log-panel test (open/empty-file/populated), matching the existing
  one-test-file-per-component convention (`ChecksSection.test.tsx`, `CheckRibbon.test.tsx`,
  `Rail.test.tsx`).

## 7. Docs to update (per `CLAUDE.md`'s mandatory doc-update table)

- `README.md` — layout table (new `system.py` router; no new script entrypoint).
- `ARCHITECTURE.md` — `src/api/` section (new `/system/status` and `/system/{name}/log` routes),
  and a short note in the monitor/approval_service sections about the new heartbeat writes.
- `web/CLAUDE.md` — `components/shell/` entry for `SystemStatusCard`, and the `Rail.tsx` layout
  note extended to describe the pinned footer.
- `STATUS.md` — not required; this closes no tracked limitation and adds no deferred item.

## 8. Out of scope / deferred

- Claude/Ollama review-backend health (declined for v1 in favor of the narrower, already-grounded
  7-row scope — flagged in the brainstorm as the largest of the three scoping options).
- `web_api`'s own row and `eod_report` (see §2 — both deliberately excluded, not deferred by
  oversight).
- Any write path (restart a daemon, clear a breaker, etc.) from this card — it is read-only,
  consistent with the web layer's single-write-table fence (`tests/test_web_fence.py`).
