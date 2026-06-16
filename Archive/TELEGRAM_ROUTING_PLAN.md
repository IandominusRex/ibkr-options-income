# Telegram Multi-Thread Routing — Implementation Plan

**Status:** ✅ Complete — all 9 phases shipped.
**Owner context:** Restructure how `src/notify/` sends messages so the user's Telegram
group's forum *topics* (threads) are used purposefully, instead of everything landing
in one topic.
**Format note:** follows the phase-tracking convention used by
[`Archive/SCAN_EFFICIENCY_PLAN.md`](Archive/SCAN_EFFICIENCY_PLAN.md) and
[`Archive/IMPROVEMENT_PLAN.md`](Archive/IMPROVEMENT_PLAN.md) — each phase is marked ✅ on
completion with a "Result" note (what shipped, test count, gate status) directly below it.

## Background / current state

Today, **one** topic ID (`TELEGRAM_THREAD_ID`, `src/common/config.py:39`, read via
`cfg.secrets.telegram_thread_id`) is used everywhere a `message_thread_id` is passed:

- `src/notify/sender.py::send_candidates` — CC + CSP approval cards (combined list).
- `src/notify/sender.py::send_buy_list` — buy-to-own screen.
- `src/notify/approval_service.py` — startup notification, the "🔄 Scan started · HH:MM
  ET" ping (line ~880, currently sent **without** a thread at all — goes to the chat's
  General topic), and overrun warnings.
- `src/orchestrator/scan.py::_send_quiet_heartbeat` — quiet-cycle heartbeat (also no
  thread today — same as scan-started).
- `src/orchestrator/scan.py` — end-of-scan data-provenance summary (also no thread).

The 15-min intraday loop (`_intraday_scan_loop` in `approval_service.py`, aligned to ET
clock marks via `seconds_until_next_aligned_mark`) drives one `run_scan(..., intraday=True)`
per cycle during RTH. `run_scan` → `_run_scan_body` (src/orchestrator/scan.py) does the
work and, in step 10 ("Send to Telegram"), calls `send_candidates` once (CC+CSP combined)
and `send_buy_list` once.

## Target routing

| Topic (thread ID) | Content | Cadence |
|---|---|---|
| **2** | "🔄 Scan started · HH:MM ET", startup notification, overrun warnings, quiet-cycle heartbeat — general ops/system pings | every 15-min cycle (scan-started), ad hoc otherwise |
| **52** | Cash-secured put (CSP) trade candidates | every 15-min cycle, always sends *something* |
| **54** | Covered-call (CC) trade candidates on currently-held underlyings | every 15-min cycle, always sends *something* |
| **56** | Buy-to-own recommendations (stocks worth owning to sell CCs against) | every 15-min cycle, always sends *something* |
| **58** | Account snapshot: net liq, holdings (stocks + nested CCs sold against them + standalone CSP/short-put positions), per-position unrealized P&L % | sent once at 09:00 ET (30 min pre-open), then the **same message is edited** on every subsequent 15-min cycle with an updated "(last updated HH:MM)" |

### "Always send something" rule (threads 52/54/56)

Each cycle, each of these threads gets exactly one of:

1. **Full screen** — new/changed candidate cards (or buy-list cards), same as today.
2. **Unchanged digest** — `"🟢 *Buy-to-Own* — 8 name(s) unchanged since 12:33 (no new
   screens)"` (exact pattern from the user's spec; icon/label/noun vary per thread).
3. **Empty/diagnostic** — `"no candidates this cycle — <reason>"`, e.g. *"0/12 option
   chains fetched — check market-data subscription"* or *"0/4 candidates passed the
   risk gate"*. This is the troubleshooting signal the user explicitly asked for.

### Gain/loss definition (thread 58)

Per the user's confirmed choice: **per-position unrealized P&L %** (market value vs.
cost basis: `unrealized_pnl / abs(avg_cost * position * multiplier)`, multiplier=100
for options, 1 for stock), plus an account-level total unrealized P&L $ and % summed
across all positions. No new daily-baseline tracking needed — derived entirely from the
existing `AccountSnapshot`/`PositionSnapshot` returned by
`src/ibkr/portfolio.py::get_account_snapshot_async` / `get_positions`.

---

## Phase 1 — Config: typed per-purpose thread IDs ✅

**Files:** `src/common/config.py`, `.env.example`, `SETUP.md`, `README.md`

1. In `Secrets` (`src/common/config.py:27-43`), **remove** `telegram_thread_id` and add:
   ```python
   telegram_thread_scan: str = Field(default="2", alias="TELEGRAM_THREAD_SCAN")
   telegram_thread_csp: str = Field(default="52", alias="TELEGRAM_THREAD_CSP")
   telegram_thread_cc: str = Field(default="54", alias="TELEGRAM_THREAD_CC")
   telegram_thread_buy: str = Field(default="56", alias="TELEGRAM_THREAD_BUY")
   telegram_thread_account: str = Field(default="58", alias="TELEGRAM_THREAD_ACCOUNT")
   ```
   Defaults match the user's numbers so an unconfigured `.env` still "just works" if
   their group happens to use these IDs; real IDs are per-group and overridable.

2. Add a small helper — `thread_id(raw: str) -> int | None` — in `src/notify/sender.py`
   (top of file, near other module-level helpers) replacing the
   `int(cfg.secrets.telegram_thread_id) if cfg.secrets.telegram_thread_id else None`
   pattern that's currently duplicated at `sender.py:109`, `sender.py:366`, and
   `approval_service.py:1111-1113`.

3. Docs (mandatory doc-update rule):
   - `.env.example`: replace the single `TELEGRAM_THREAD_ID=` line with the five new
     vars, each commented with its purpose and default.
   - `SETUP.md`: update the env-var table (~line 61) and the "Using the Telegram bot"
     / `getUpdates` instructions (~lines 73, 805-806) to explain finding each topic's
     thread ID and setting the five vars (or relying on defaults).
   - `README.md` (~line 87): update the secrets bullet to list the five thread vars;
     add the topic-routing table from this plan's "Target routing" section.

**Result:** `Secrets` now has `telegram_thread_scan/csp/cc/buy/account` (defaults
`2/52/54/56/58`), `telegram_thread_id` removed. Added `thread_id()` helper in
`src/notify/sender.py` and used it at the three former call sites (`send_candidates`,
`send_buy_list`, `approval_service` startup notification), all routed to
`telegram_thread_scan` for now — preserves current single-thread behaviour until Phase
3/5/6 split the routing. Updated `.env.example`, `SETUP.md`, `README.md`. The
topic-routing table (full "Target routing" doc) is deferred to Phase 8, once routing
actually exists.
**Gate after Phase 1:** ✅ tests pass (707, incl. 2 new `thread_id()` unit tests) · ✅
ruff check · ✅ mypy · ✅ no remaining `telegram_thread_id`/`TELEGRAM_THREAD_ID` references
(`grep` clean across `src/`, `tests/`, `.env.example`, `SETUP.md`, `README.md`).

---

## Phase 2 — Formatters: generic digest/empty + account snapshot ✅

**File:** `src/notify/formatters.py`

1. **Generalize the unchanged-digest formatter.** Replace `format_buy_list_digest`
   (lines 231-236) with:
   ```python
   def format_screen_unchanged(icon: str, label: str, count: int, since: str, noun: str = "name") -> str:
       plural = "" if count == 1 else "s"
       return (
           f"{icon} *{_md(label)}* — {count} {noun}{plural} unchanged since {_md(since)} "
           f"\\(no new screens\\)"
       )
   ```
   Used as:
   - Buy: `format_screen_unchanged("🟢", "Buy-to-Own", count, since, "name")`
   - CC: `format_screen_unchanged("🔵", "Covered Calls", count, since, "candidate")`
   - CSP: `format_screen_unchanged("🟣", "Cash-Secured Puts", count, since, "candidate")`

   Check `tests/test_notify.py` for any test asserting `format_buy_list_digest`'s exact
   string and update it to call/expect `format_screen_unchanged` instead.

2. **New `format_screen_empty(icon: str, label: str, reason: str) -> str`** — for the
   "no candidates this cycle" diagnostic:
   ```python
   def format_screen_empty(icon: str, label: str, reason: str) -> str:
       return f"{icon} *{_md(label)}* — no candidates this cycle\n_{_md(reason)}_"
   ```

3. **New `format_account_snapshot(account: AccountSnapshot, positions: list[PositionSnapshot], updated_at: str) -> str`**:
   - Header: `📊 *Account Snapshot*`
   - Account line: net liq (reuse `_md(f'{account.net_liquidation:,.0f}')` pattern from
     `format_account`), plus total unrealized P&L $ and % across all `positions`
     (sum `unrealized_pnl`; % = `sum(unrealized_pnl) / sum(abs(cost_basis))`, guard
     `sum(abs(cost_basis)) == 0` → omit the % and show "N/A").
   - `*Stocks*` section: for each `STK` position with `position > 0`, one line: symbol,
     share count, market value, P&L $ (`_pnl`) and % (1 decimal). Immediately below,
     nested (indented, prefixed `└ `), any `OPT`/`CALL`/short (`position < 0`) positions
     where `p.underlying == stock.symbol` — strike, expiry, DTE (`(expiry - date.today()).days`,
     same pattern as `format_positions` line ~463), P&L $/%.
   - `*Cash-Secured Puts*` section: `OPT`/`PUT`/short positions — strike, expiry, DTE,
     P&L $/%. If none, omit the section entirely (don't print an empty header).
   - Per-position P&L %: `unrealized_pnl / abs(avg_cost * position * multiplier) * 100`
     (multiplier = 100 for `sec_type == "OPT"`, else 1). Guard division by zero
     (`avg_cost == 0` or `position == 0`) → render `N/A` instead of a %.
   - Footer: `_(last updated {updated_at})_` where `updated_at` is `HH:MM ET` (reuse
     `now_et_hhmm()` from `src.common.market_hours`, already imported in `scan.py`).
   - Apply the same `_MAX_MESSAGE_LEN` truncation pattern used by every other formatter
     in this file.

4. Leave `format_quiet_cycle`, `format_unchanged_cards_digest`, `format_buy_list`,
   `format_positions`, etc. unchanged — they're reused as-is.

**Result:** Added `format_screen_unchanged`, `format_screen_empty`,
`_position_pnl_pct`, `_format_option_snapshot_line`, and `format_account_snapshot` to
`src/notify/formatters.py`. Removed `format_buy_list_digest`; its one call site
(`send_buy_list`'s unchanged-digest branch in `sender.py`) now calls
`format_screen_unchanged("🟢", "Buy-to-Own", len(candidates), since, "name")` — this is
the minimal sender.py touch needed to keep the codebase compiling/passing; the full
per-thread routing split is still Phase 3. `format_quiet_cycle`,
`format_unchanged_cards_digest`, `format_buy_list`, `format_positions` untouched.
**Gate after Phase 2:** ✅ tests pass (715, incl. 9 new formatter tests covering
`format_screen_unchanged` pluralization/escaping, `format_screen_empty`, and
`format_account_snapshot` — stocks-only, nested CC, standalone CSP, zero-cost-basis
"N/A", footer timestamp, message-length truncation) · ✅ ruff check + format · ✅ mypy.

---

## Phase 3 — Sender: per-thread routing + account-snapshot send/edit ✅

**File:** `src/notify/sender.py`

1. **Generalize the screen-hash helper.** Replace `_buy_list_hash` (lines 64-68) with:
   ```python
   def _screen_hash(keys: list[tuple]) -> str:
       return hashlib.sha256(json.dumps(sorted(keys)).encode()).hexdigest()
   ```
   - Buy list: `_screen_hash([(c.symbol, _score_band(c.score)) for c in candidates])`
   - CC/CSP: `_screen_hash([(c.candidate_id, _score_band(c.blended_score)) for c in candidates])`
     (candidate_id is deterministic per cycle — see the existing comment at
     `sender.py:155-158`).

2. **`send_candidates` signature change** — add required kwargs:
   ```python
   async def send_candidates(
       candidates: list[TradeCandidate],
       reviews: list[ClaudeReview],
       *,
       thread_id: int | None,
       label: str,
       icon: str,
       hash_key: str,
       time_key: str,
       empty_reason: str | None = None,
       session: Session | None = None,
       suppress_unchanged: bool = False,
   ) -> bool:
   ```
   New logic, evaluated **before** the `is_automated_mode()` branch (so both MANUAL and
   AUTOMATED get empty/unchanged handling) and before the early `if not candidates`
   return:
   - `candidates` empty → `bot.send_message(text=format_screen_empty(icon, label,
     empty_reason or "no candidates this cycle"), message_thread_id=thread_id)`,
     return `True`.
   - else if `suppress_unchanged` and `_screen_hash(...) == get_setting(hash_key)`:
     compute `to_send`/`suppressed` via the existing `_live_pending_approval` loop
     (lines 260-267) as today; if `to_send` is **also** empty (every candidate is an
     unchanged live pending approval), send
     `format_screen_unchanged(icon, label, len(candidates), get_setting(time_key) or
     "earlier", noun)` instead of the per-card `format_unchanged_cards_digest`, return
     `True`. (`noun` derived from `label`: "candidate" for CC/CSP screens — pass it
     through as an extra kwarg, default `"candidate"`.)
   - else: existing full-card flow (`_send_with_session` / `_auto_queue_candidates`),
     then `set_setting(hash_key, current_hash)` and `set_setting(time_key, _et_hhmm())`
     on success.
   - All `thread_id` usages inside `_auto_queue_candidates` / `_send_with_session`
     come from the new param instead of `cfg.secrets.telegram_thread_id`.

3. **`send_buy_list`**:
   - Route via `thread_id(cfg.secrets.telegram_thread_buy)` instead of
     `cfg.secrets.telegram_thread_id`.
   - Add an empty-state branch (currently `if not candidates: return False` at line
     357-358 silently drops it): send `format_screen_empty("🟢", "Buy-to-Own",
     "0 would_own names cleared the buy screen this cycle")`, return `True`.
   - Switch `format_buy_list_digest(...)` call (line 379) to
     `format_screen_unchanged("🟢", "Buy-to-Own", len(candidates), since, "name")`.

4. **New `send_account_snapshot(account: AccountSnapshot, positions: list[PositionSnapshot]) -> bool`**:
   - Mirrors `send_buy_list`'s structure: reads config/token/chat_id, builds its own
     `Bot(token=token)`.
   - `thread_id = thread_id(cfg.secrets.telegram_thread_account)`.
   - `text = format_account_snapshot(account, positions, now_et_hhmm())`.
   - New `system_settings` keys: `account_snapshot_message_id`, `account_snapshot_date`
     (ET date string `YYYY-MM-DD`, via `_et_hhmm`-style helper using
     `datetime.now(_ET).date().isoformat()`).
   - If `get_setting("account_snapshot_date") != today`:
     `send_message(...)` → store `message_id` (as str) and `today` via `set_setting`.
   - Else: `try: edit_message_text(chat_id=..., message_id=int(stored_id),
     text=text, parse_mode="MarkdownV2")`. On `Exception` (message deleted, >48h old,
     etc.) fall back to `send_message` and overwrite both stored keys.
   - Best-effort: log + return `False` on any failure, never raises.

**Result:** `_buy_list_hash` replaced by generic `_screen_hash(keys: list[tuple]) -> str`. `send_candidates` signature changed to required keyword kwargs `thread_id`, `label`, `icon`, `hash_key`, `time_key` (+ optional `empty_reason`, `noun`, `session`, `suppress_unchanged`): empty candidates → `format_screen_empty` diagnostic; hash-unchanged + all per-card suppressed → screen-level `format_screen_unchanged`; full send stores hash/time in the provided system-settings keys. `send_buy_list` routes to `telegram_thread_buy` and sends `format_screen_empty` on empty list. `send_account_snapshot(account, positions)` added: sends/edits the account snapshot on `telegram_thread_account`, using `account_snapshot_message_id`/`account_snapshot_date` system-settings keys. `scan.py` updated to pass new required kwargs (combined CC+CSP → `telegram_thread_scan`; Phase 5 will split). Tests updated: `_mock_cfg` extended with all five thread fields; `_cc_kwargs()` helper added; 16 existing `send_candidates` calls migrated; `test_send_candidates_empty_list_no_bot_calls` renamed/rewritten; 11 new tests added (per-thread routing, empty/unchanged screen, `send_account_snapshot` ×4, buy-list empty + routing).
**Gate after Phase 3:** ✅ tests pass · ✅ ruff check + format · ✅ mypy.

---

## Phase 4 — Market hours: daily-time helper ✅

**File:** `src/common/market_hours.py`

Add, near `seconds_until_next_aligned_mark` (line 194):
```python
def seconds_until_time(hh: int, mm: int, now: datetime | None = None) -> float:
    """Seconds (ET wall-clock) until the next occurrence of HH:MM — today if still
    ahead, else tomorrow. Mirrors seconds_until_next_aligned_mark's tz handling."""
    if now is None:
        now = datetime.now(_ET)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=_ET)
    else:
        now = now.astimezone(_ET)

    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()
```

**Result:** `seconds_until_time(hh, mm, now)` added to `src/common/market_hours.py` immediately
before `seconds_until_next_aligned_mark`. `ARCHITECTURE.md` `market_hours.py` entry updated to
list the new function. 5 new tests added to `tests/test_market_hours.py` covering: target ahead
today, already-passed rolls to tomorrow, exactly-on-target rolls to tomorrow, tz-naive treated as
ET, tz-aware non-ET converted.
**Gate after Phase 4:** ✅ tests pass (729, incl. 5 new `seconds_until_time` tests) · ✅ ruff
check + format · ✅ mypy.

---

## Phase 5 — Scan orchestrator: split CC/CSP sends + account snapshot ✅

**File:** `src/orchestrator/scan.py`

1. New small helper near `_send_quiet_heartbeat` (~line 705):
   ```python
   def _no_candidates_reason(result: ScanResult, all_count: int, passed_count: int) -> str:
       prov = result.provenance
       if result.total_symbols == 0:
           return "no symbols in universe"
       if prov.chain_ibkr == 0 and prov.chain_failed > 0:
           return f"{prov.chain_failed}/{result.total_symbols} option chains failed — check market-data subscription"
       if all_count == 0:
           return "0 candidates generated this cycle"
       return f"0/{all_count} candidates passed the risk gate"
   ```

2. Step 10 (~lines 1187-1217): replace the single `send_candidates(cc+csp, ...)` call
   with two calls, each using `thread_id(...)` from Phase 1/3:
   ```python
   cfg_secrets = cfg.secrets
   cc_sent = await send_candidates(
       result.cc_candidates, result.reviews,
       thread_id=thread_id(cfg_secrets.telegram_thread_cc),
       label="Covered Calls", icon="🔵",
       hash_key="last_cc_hash", time_key="last_cc_time",
       empty_reason=_no_candidates_reason(result, len(all_option_candidates_cc), len(result.cc_candidates)),
       suppress_unchanged=intraday,
   )
   csp_sent = await send_candidates(
       result.csp_candidates, result.reviews,
       thread_id=thread_id(cfg_secrets.telegram_thread_csp),
       label="Cash-Secured Puts", icon="🟣",
       hash_key="last_csp_hash", time_key="last_csp_time",
       empty_reason=_no_candidates_reason(result, len(all_option_candidates_csp), len(result.csp_candidates)),
       suppress_unchanged=intraday,
   )
   buy_sent = await send_buy_list(result.buy_candidates, bot, chat_id, suppress_unchanged=intraday)
   ```
   (`all_option_candidates_cc`/`_csp` — split `all_option_candidates` (line 1088) by
   `strategy.value`, or just pass `len(cc_candidates_pre_gate)`/`len(csp_candidates_pre_gate)`
   computed earlier in the function — whichever is simplest given what's already in
   scope at that point.)

3. After the notify step, best-effort:
   ```python
   try:
       await send_account_snapshot(account, positions)
   except Exception:
       log.warning("scan: failed to send account snapshot", exc_info=True)
   ```
   for **both** intraday and full-sweep runs (`account`/`positions` already fetched in
   step 1).

4. `_send_quiet_heartbeat` (lines 705-738): change `bot.send_message(...)` to include
   `message_thread_id=thread_id(get_config().secrets.telegram_thread_scan)`. Trigger
   condition stays `intraday and not cand_sent and not buy_sent` where
   `cand_sent = cc_sent or csp_sent` (declared near line 1192).

5. The end-of-scan data-provenance summary (lines 1219-1242, full-sweep only) — also
   add `message_thread_id=thread_id(get_config().secrets.telegram_thread_scan)` since
   it's a system/ops message, same bucket as scan-started/quiet-heartbeat.

**Result:** `_no_candidates_reason(result, all_count)` helper added. Single combined
`send_candidates(cc+csp)` call replaced by two calls: CC → `telegram_thread_cc`
(`last_cc_hash`/`last_cc_time`) and CSP → `telegram_thread_csp`
(`last_csp_hash`/`last_csp_time`), each with per-strategy empty-reason diagnostics.
`cand_sent = cc_sent or csp_sent`. `send_account_snapshot(account, positions)` called
best-effort after every cycle. `_send_quiet_heartbeat` now passes
`message_thread_id=thread_id(cfg_s.telegram_thread_scan)`. Data-provenance summary
also passes `message_thread_id=thread_id(cfg_s.telegram_thread_scan)`.
`send_account_snapshot` imported at the top of `scan.py`. `STATUS.md` updated.
**Gate after Phase 5:** ✅ tests pass · ✅ ruff check · ✅ mypy.

---

## Phase 6 — Approval service: thread routing + 09:00 ET premarket snapshot job ✅

**File:** `src/notify/approval_service.py`

1. Scan-started ping (~line 880): add `message_thread_id=thread_id(cfg.secrets.telegram_thread_scan)`.

2. Startup notification (~lines 1111-1125): replace
   `int(cfg.secrets.telegram_thread_id) if cfg.secrets.telegram_thread_id else None`
   with `thread_id(cfg.secrets.telegram_thread_scan)` (import `thread_id` from
   `src.notify.sender`).

3. Overrun warning (`_note_intraday_skip`, ~lines 836-845): add
   `message_thread_id=thread_id(cfg.secrets.telegram_thread_scan)` to its
   `bot.send_message(...)` call.

4. **New `_premarket_snapshot_loop`** (placed near `_intraday_scan_loop`, ~line 850):
   ```python
   async def _premarket_snapshot_loop(ib_scan: IB, chat_id: str) -> None:
       """Background task: send the day's first account-snapshot to thread 58 at
       09:00 ET (30 min pre-open). Subsequent updates come from the intraday loop's
       calls to send_account_snapshot (which edits this same message)."""
       cfg = get_config()
       while True:
           await asyncio.sleep(seconds_until_time(9, 0))
           try:
               if is_trading_day(datetime.now(_ET).date()) and ib_scan.isConnected():
                   from src.ibkr.portfolio import get_account_snapshot_async, get_positions
                   from src.notify.sender import send_account_snapshot

                   account = await get_account_snapshot_async(ib_scan, cfg.secrets.ibkr_account)
                   positions = get_positions(ib_scan)
                   await send_account_snapshot(account, positions)
           except Exception:
               logger.exception("Premarket snapshot loop: failed")
   ```
   (`_ET` — reuse the existing `ZoneInfo("America/New_York")` constant if one exists in
   this module, else import from `src.common.market_hours` or define locally;
   `is_trading_day`, `seconds_until_time` imported from `src.common.market_hours`.)

5. Start/cancel this task in `_run_service` alongside `intraday_task` (~lines 1152-1172):
   ```python
   premarket_task: asyncio.Task | None = None
   if ib_scan is not None:
       premarket_task = asyncio.create_task(_premarket_snapshot_loop(ib_scan, chat_id))
       logger.info("Premarket snapshot loop started (09:00 ET daily)")
   ```
   and cancel it in the `finally` block the same way as `intraday_task`.

**Result:** `_premarket_snapshot_loop(ib_scan, chat_id)` added to `approval_service.py` — sleeps
until 09:00 ET, then on trading days fetches the account snapshot and calls `send_account_snapshot`
(which seeds the edit-in-place message_id for subsequent intraday edits). Task is started/cancelled
alongside `intraday_task` in `_run_service`. Scan-started ping, overrun warning
(`_note_intraday_skip`), and startup notification all pass `message_thread_id=telegram_thread_scan`.
`seconds_until_time` imported from `src.common.market_hours`.
**Gate after Phase 6:** ✅ tests pass · ✅ ruff check + format · ✅ mypy.

---

## Phase 7 — system_settings keys ✅

No schema change — `system_settings` (`src/storage/system_settings.py`,
`get_setting`/`set_setting`) is a generic key/value table. New keys used (document in
`ARCHITECTURE.md` storage section if that table is documented there):

- `account_snapshot_message_id`
- `account_snapshot_date`
- `last_cc_hash`, `last_cc_time`
- `last_csp_hash`, `last_csp_time`

(mirrors the existing `last_buy_list_hash`/`last_buy_list_time` pattern at
`sender.py:45-46`)

**Result:** All six keys documented in the `system_settings` row of the `models.py` table in
`ARCHITECTURE.md` (alongside the existing `last_buy_list_hash`/`last_buy_list_time` entries). No
code change needed — `get_setting`/`set_setting` already handle arbitrary keys.
**Gate after Phase 7:** ✅ (documentation only).

---

## Phase 8 — Documentation (mandatory per CLAUDE.md) ✅

| File | Update |
|---|---|
| `README.md` | Telegram secrets bullet (5 thread vars) + new topic-routing table |
| `ARCHITECTURE.md` | `src/notify/` section: document `format_account_snapshot`, `format_screen_unchanged`, `format_screen_empty`, `send_account_snapshot`, the 5 new config keys, the new premarket job, new system_settings keys |
| `SETUP.md` | `.env` table (5 new vars), "Using the Telegram bot" topic-ID instructions, troubleshooting table |
| `STATUS.md` | Note the new account-snapshot feature + per-thread "always send something" guarantee as a built feature |
| `.env.example` | Replace `TELEGRAM_THREAD_ID=` with the 5 new vars (commented with purpose/defaults) |

**Result:** `README.md` updated with topic-routing table (5 topics × purpose/env-var/content);
`ARCHITECTURE.md` `src/notify/` section documents `format_account_snapshot`,
`format_screen_unchanged`, `format_screen_empty`, `send_account_snapshot`, the 5 config keys,
and the premarket snapshot task; `system_settings` key list updated with all 6 new keys;
`SETUP.md` has per-thread env-var block and troubleshooting rows for wrong-topic and missing-thread
errors; `STATUS.md` reflects all 9 phases complete; `.env.example` already done in Phase 1.
**Gate after Phase 8:** ✅ (documentation only).

---

## Phase 9 — Tests ✅

**Files:** `tests/test_notify.py`, `tests/test_scan_materiality.py`,
`tests/test_scan_review_reuse.py`, `tests/test_claude.py` (grep for
`telegram_thread_id`), new/extended market-hours test.

1. `tests/test_notify.py`:
   - Replace any `cfg.secrets.telegram_thread_id = None` setup (lines ~1067, ~1205)
     with the new per-purpose fields.
   - New tests: `format_screen_unchanged` (exact string match against the user's
     example), `format_screen_empty`, `format_account_snapshot` — stocks-only, stock
     with nested CC, standalone CSP, P&L % math (including div-by-zero → "N/A"), footer
     timestamp, message-length truncation.
   - `send_account_snapshot`: (a) no stored message → `send_message` + stores id/date;
     (b) stored message from today → `edit_message_text`; (c) edit raises → falls back
     to `send_message` + overwrites stored id/date; (d) stored date ≠ today → fresh
     `send_message`.
   - `send_candidates`/`send_buy_list`: per-thread routing (`message_thread_id` ==
     expected per-purpose thread), empty-candidates → `format_screen_empty`, unchanged
     hash → `format_screen_unchanged`.

2. `tests/test_scan_materiality.py` / `test_scan_review_reuse.py`: update mocks —
   `send_candidates` is now called twice (CC, CSP) with different kwargs; mock
   `send_account_snapshot` so scans don't hit IBKR via the new account/positions
   formatting path. Re-verify `quiet_cycle` true/false expectations still hold under
   the new `cand_sent = cc_sent or csp_sent` definition.

3. New test in `tests/test_market_hours.py` (create if it doesn't exist, else extend)
   for `seconds_until_time` — today-still-ahead vs. already-passed-rolls-to-tomorrow,
   tz-naive/aware inputs.

**Result:** `send_account_snapshot` mock (`AsyncMock()`) added to `_stub_common` in
`test_scan_materiality.py` and `_stub_pipeline` in `test_scan_review_reuse.py` — scans no longer
rely on best-effort exception swallowing for this call. `test_notify.py` formatter and sender tests
(format_screen_unchanged ×2, format_screen_empty, format_account_snapshot ×5,
send_account_snapshot ×4, per-thread routing, empty/unchanged screen, buy-list empty+routing) were
already added in Phases 2–3. `seconds_until_time` tests (×5) were added in Phase 4. No remaining
`telegram_thread_id` references in tests (grep clean).
**Gate after Phase 9:** ✅ tests pass (729) · ✅ ruff check + format · ✅ mypy.

---

## Verification checklist

- [x] `python -m pytest -q` — full suite green (729 tests)
- [x] `ruff check . && ruff format .`
- [x] `mypy src`
- [ ] Manual (optional, needs `.env` + TWS): run `python -m scripts.run_approval_service`,
      confirm startup + scan-started pings land in topic 2; trigger `/scan`, confirm
      CC/CSP/Buy land in 54/52/56 (full screen first run, unchanged/empty digest on a
      repeat run with no changes); confirm an account snapshot appears in 58 and is
      *edited in place* (not re-sent) on the next cycle.
- [x] Updated `STATUS.md` / `ARCHITECTURE.md` / `README.md` / `SETUP.md` / `.env.example`
      per Phase 8.
