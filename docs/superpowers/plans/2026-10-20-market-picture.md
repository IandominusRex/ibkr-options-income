# Market Picture, Regime Sizing and the News Expert — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The plan is split into seven sections. Every section opens with **entry checks** that must all pass before its first task starts, and carries a **model label** so an orchestrator that delegates a section knows which model to spawn. The operator's standing pattern (memory: token-light plan execution): a git worktree, **one Sonnet subagent per section** (not per task), **stop and ask the operator between sections**, one Opus whole-branch review at the end, no per-task reviews. **Task 22 (the web page) starts by invoking the `da-vinci` skill**, and so does any subagent given it (say so in its prompt). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every `claude -p` call a shared, persistent, deterministic-first picture of the market;
make the wheel trade less (and only at technically chosen lower prices) when the market or a single
name is falling, while still taking a guarded lot when a bottom is forming; turn the news thread into
an expert that sorts stories into three piles against that picture; keep a dossier on every name the
book cares about and have every trade and roll review read it; push covered-call strikes out after a
breakout; size leveraged ETFs smaller in every regime; let Claude cut (never raise) an auto-opened
CSP's size, applied in paper and recorded on every override; and show the operator what each Claude
call knows on one web page.

**Architecture:** Deterministic first. A pure classifier (`src/analytics/regime.py`) turns SPY and
QQQ data into a `MarketRegime`; the trading process persists it with its intraday escalation and
bottoming state (`src/storage/regime_state.py`, `src/regime/refresh.py`). A `SizingContext`
(`src/regime/context.py`) carries the regimes, the suspension switch, today's CSP count and each
name's scale-in zone into the sizer (`strategies/cash_secured_put.py`) and the gate
(`engine/risk_engine.py`), which apply them through pure functions in `src/engine/regime_limits.py`
— the generator and the gate call the same functions, so they agree. The news process
(`src/news/`) triages clusters (Python floor first, one batched LLM call), keeps multi-week stories
alive only by Python matching, and writes a grounded `MarketPicture` to `data/news.db`. Readers
render it with one neutral function (`src/common/picture_text.py`). Claude's size cut is one clamped
integer applied in `notify/sender.py`'s auto branch; every regime trim, ladder block and cut is
written to a counterfactual table that a human reads. Per name, the news process keeps a
`TickerDossier` in `news.db` (Python facts and health, Claude's cited story and profile, and
upcoming events whose dates Python finds in the cited news), rendered by
`src/common/dossier_text.py`. A deterministic breakout rule (`src/analytics/breakout.py`) pushes
covered-call strikes out through the same `SizingContext`. (The covered-call event hold of the
2026-10-20 draft was withdrawn on 2026-10-21 — spec decision 34; Task 20 is a removed stub.)

**Tech Stack:** Python 3.12, pandas/numpy, Pydantic v2, SQLAlchemy 2 (SQLite), python-telegram-bot,
FastAPI; Next.js 15 / React 19 / Tailwind v4 / react-query / Vitest for the page; pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-10-20-market-picture-design.md` (operator decisions 1–39,
§1–§19; decisions 25–30 and §16–§18 are the dossier and covered-call timing, added 2026-10-20;
decisions 31–39 and §19 are the second review and the replay of the real book, 2026-10-21, and win
over anything earlier they amend). Executors read the spec and this plan together; where they differ, the spec's operator
decisions win and the difference is a ruling in the Progress log.

## Execution model

| Section | Tasks | Model | Why this model |
|---|---|---|---|
| **A — The regime and regime sizing** | 1–4 | **sonnet** (opus if the operator wants extra care: it edits the gate) | Pure classifier, persisted state, the sizer/gate integration and the send-time trim. Every interface and test is pinned here; the gate edits are additive and guarded by the existing risk-engine suite. |
| **B — The ladder and the bottoming signal** | 5–7 | **sonnet** | New deterministic analytics modules with exact rules, plus one more pure check in the gate and the live re-gate. |
| **C — The news expert** | 8–11 | **sonnet** | New tables, triage, stories, the picture and the noise check inside the existing news service. |
| **D — Readers and Claude's cut** | 12–15 | **sonnet** | Prompt changes, the clamped cut, the counterfactual record, and the two written-rule amendments with their fence tests. |
| **E — Covered-call timing and the ticker dossier** | 16–19 (20 removed) | **sonnet** | A deterministic CC rule mirroring the ladder, a news-side dossier built like the picture, and its readers. |
| **F — The page** | 21–22 | **sonnet** (Task 22 invokes `da-vinci`) | One read-only route and one read-only page. |
| **G — Docs and finish** | 23 | **sonnet**, then an **opus** whole-branch review | Doc sweep and full gate; the review runs on the most capable model. |

**How a section runs:**

1. Run that section's **entry checks** in order (the orchestrator runs them, not the subagent).
2. **Any check fails → stop** and report what failed with its output. A failure belonging to the
   previous section is fixed there (reopen its last task, record the ruling).
3. **All pass →** add a Progress-log row ("Section X entry", result, date), spawn one Sonnet subagent
   for the whole section with this plan and the spec, and tell it: follow each task's steps in order,
   TDD (run each new test red before the code), one commit per task, update the Progress log row of
   each task in the same commit, and stop at the section exit.
4. After the subagent reports, **verify it yourself** (git log, `git status`, the gate counts, the
   section exit) before relaying it, then **ask the operator whether to continue**.

**Commit counts.** Each task is one commit (Task 1's also adds this plan and the spec). A review fix
pass adds one commit; record it in the Progress log.

## Progress log

| Section / task | Status | Commits | Gate | Date | Rulings |
|---|---|---|---|---|---|
| **Plan verified** (Opus review) | done | (plan file only) | n/a | 2026-10-20 | Opus verified the plan against the spec and `main`; 22 fixes applied: zone supports detected relative to the anchor; loss exits found through the opening order (close orders have no snapshot); send-time context built before the write session; counterfactual rows de-duplicated per day; `max_contracts` validator; collateral caps not scaled; reason-label parity; text-grep fence warning; split daily/live regime fetch with a pinned "stale" rule; triage `rank` column and re-eligibility; per-purpose LLM counting; correct grounding functions; `render_picture` moved to Task 8; the tiles' header map; beta helper; picture into the writer/digest prompts; news-storage fence test; `.opencode` amendment; lot spots read from the DB. Rulings 15–22 added; the operator confirmed 15 (VIX for both indices) and 16 (per-index daily limits) the same day. |
| **Plan extended** (dossier + CC timing) | done | (plan and spec only) | n/a | 2026-10-20 | Operator asked for a per-name memory read before every CSP/CC/roll review and a "wait to sell the CC" behaviour (the META/MUSE example). Research (spec §18) did not support holding CCs after a past jump; operator chose the evidence-shaped design: a deterministic breakout rule that only pushes strikes out, plus a Claude hold limited to a Python-verified dated event ahead. Section E (Tasks 16–20) added; page/docs renumbered 21–23; rulings 23–33. |
| **Plan revised** (second Opus review + replay of the real book) | done | (plan and spec only) | n/a | 2026-10-21 | Review found: the book at 101% of deployable makes any regime budget multiplier a full CSP stop; the 0.20 bottoming/breakout delta guards meet `delta_min: 0.20` (empty band); `recovered()` counted closes from before the anchor and the strict ITM trigger missed TQQQ 75P by $0.12, so the ladder missed its own must-catch lots; intraday escalation carried over days; the 80th-percentile rule fired at VIX 20; hourly dossier versions churned review reuse; counterfactual rows double-counted and marked to expiry only; tokens ~1.7–2.5× a day, not +20–40%. Operator (same day): floor under the scaled budget; Claude's cut applied in paper, record-only in live, every override recorded; cut the CC event hold, keep the breakout rule; smaller per-trade size for 2× and 3× leveraged ETFs. Spec decisions 31–39 and §19; rulings 34–48; Task 20 removed (stub); Tasks 1–4, 6, 7, 10, 14–19, 21–23 amended. Replay with the revised rules (spec §19): 41 CSP opens → 10 blocked, 4 trimmed; contracts 178 → 120; CSP P&L −$5,253 → −$1,268. |
| **Plan revised** (leveraged-ETF middle ground) | done | (plan and spec only) | n/a | 2026-10-21 | Operator: the flat 3× 0.3 / 2× 0.5 ceiling barely moved P&L in the replay (TQQQ winners and losers nearly cancel) while cutting leveraged-ETF premium ~46% — find a middle ground. Replayed five variants (spec §19 table). Decided: a **tiered** ceiling — calm (name regime `normal`, no ladder trigger) 3× 0.6 / 2× 0.8; stressed (otherwise) 3× 0.3 / 2× 0.5. Keeps 71% of leveraged-ETF premium (flat: 54%); largest lot $46.8k collateral (flat $26k, none $78k). Replay: 10 blocked, 4 trimmed; contracts 178 → 129; CSP P&L −$5,253 → −$1,298. Ruling 35 rewritten; Tasks 3, 4, 6, 7, 21, 22 amended. |
| **A entry checks** (baseline) | done | (none; plan and spec copied into the worktree, committed by Task 1) | pytest **3869 passed, 1 skipped**; ruff clean; mypy clean (266 source files) | 2026-10-21 | A1–A4 all pass. `MAIN=/Users/ianlim/Desktop/IBKR Investments` (Tasks 5 and 7 read `$MAIN/data/income_system.db` read-only). Worktree: `$MAIN/.claude/worktrees/market-picture` on `feat/market-picture` cut from local `main` at 4872a77 (the repo's existing `.claude/worktrees/` convention; `.venv` and `web/node_modules` symlinked; `init_db()` run). Orchestrator: Sonnet. |
| 1 Regime config, schemas, classifier | done | `feat(regime): market regime config, schemas and classifier` | pytest **3909 passed, 1 skipped**; ruff clean; mypy clean (267 source files) | 2026-10-21 | (1) **Typed regime blocks refuse an unknown key** (`_KeyedCfg` with a `KEYS` tuple per block; `RegimeCfg`, `RegimeCspCfg`, `RegimeThresholdsCfg`, `RegimeIntradayCfg`, `RegimeIndexIntradayCfg`). Why: the existing guard `tests/test_config_keys.py` requires every leaf key of `risk_limits.yaml` to appear quoted in `src/`, and a typed pydantic model reads them as attributes, so the plan's typed block failed it (13 keys). The honest fix is a typo guard, not an allowlist entry or a weakened test: a mistyped tunable now fails at first use instead of leaving a default in force. Cost if wrong: a later task that adds a key under `regime:` must also add it to that block's `KEYS` (`test_regime_cfg_key_lists_match_the_model_fields` says so). (2) `fetch_live_inputs` takes one extra keyword, `prior_vol_close`, so ruling 39's equal-to-the-prior-close rule applies to the live VIX as well as the index (the plan's signature had no prior VIX close); it makes no provider call outside RTH. (3) `fetch_daily_inputs` takes `today=` and marks a daily frame whose last bar is older than the last completed session by more than 4 days as stale (index fields, or `vol`/`vol_pct_1y`/`term_ratio`): the DB bar store serves old closes while yfinance is down, which is Review Focus 2 (must not read as calm). Extra tests: stale bars, missing VIX frames, never raises. (4) `get_bars` reaches the network only through `_load_raw`; an autouse fixture in `tests/conftest.py` stubs `_load_raw` and `_default_last_price` to "no data" so the scan, order-poll and `/regime` tests of Tasks 2-4 stay offline (a refresh with no data is the fail-soft path). (5) Reason strings: intraday `"QQQ -2.9% today"` (one decimal, the notice example), `"live VIX 41.0"`, `"stale:<field>"`; classify_base: `"VIX 23.0"`, `"VIX/VIX3M 1.02 (backwardation)"`, `"slow: ..."`. Drawdown is measured on closes over the last 252 sessions. Slow rule exactly as pinned; the vol percentile and term rules need non-stale fields. (6) Added `test_regime_module_stays_in_the_deterministic_tier` (AST over `src/analytics/regime.py`). |
| 2 Regime state, refresh, `/regime`, notices | done | `feat(regime): persisted regime state, /regime, change notices` | pytest **3951 passed, 1 skipped**; ruff clean; mypy clean (271 source files) | 2026-10-21 | (1) A first-ever refresh appends a `RegimeChange` per index **only when the effective regime is not normal** (a calm first run announces nothing; the plan's test name says "one change per index" and is tested on a stressed market). (2) No data and no previous state: NORMAL with `escalated_by=["no_data"]` and `base_date` set to *yesterday*, so the daily fetch is retried on every call instead of the day being treated as classified (`/regime` says "no market data yet" rather than claiming calm). (3) Only a trading day (or the very first run) fetches or recomputes the daily base; a weekend or holiday refresh rolls the ET day over, keeps the base, and drops the last session's intraday escalation (the change is recorded). Fetchers run outside the state lock; the rules run inside `update_regime_state` against the latest persisted state. (4) `mark_changes_sent(sent=None)` takes the list that actually went out, so a change appended by the order poll while a notice was in flight is not lost; `send_regime_changes` returns 0 and leaves changes queued with no bot token or on a Telegram error. (5) `refresh_regime_cached` returns the persisted state when the refresh raises (None only when nothing is stored). `tests/conftest.py`'s autouse regime fixture also clears the 60 s cache around every test (a cached state must not leak between tests that each have their own tmp DB). (6) The scan refreshes and announces right after the market-conditions block (step 0b), not just before `send_scan_results`, so an early abort (account fetch failure) still announces; a failed refresh falls back to the persisted state. `refresh_regime(..., fetch_bars=)` is accepted and unused until Task 7. (7) `/regime` is plain text; the status calls `refresh_regime_cached` first; `/regime` was also added to `format_help` and the BotCommand menu. Docs for the new command (ARCHITECTURE commands table, SETUP, README) are Task 23's sweep. |
| 3 Regime sizing in the sizer and the gate | done | `feat(regime): regime budgets with a guaranteed floor, per-trade and leveraged-ETF limits, daily limit` | pytest **4013 passed, 1 skipped**; ruff clean; mypy clean (273 source files) | 2026-10-21 | (1) The plan's `test_generator_trims_to_the_per_trade_cap_and_records_the_note` named TQQQ and expected 3; TQQQ is a leveraged ETF, so under ruling 35 it is 1 in a stressed QQQ. The test uses NVDA (tech-linked, not leveraged) for the 3, and TQQQ has its own tests for 6 (calm), 3 (a ladder trigger) and 1. (2) The `leveraged_sizing.leverage` ticker map has its defaults in code (`_DEFAULT_LEVERAGE`, used when the block or the `leverage:` key is absent): `tests/test_config_keys.py` requires every YAML leaf key (here the tickers UPRO, DPST, LABU) to appear quoted in `src/`, and that guard was neither weakened nor allowlisted. The factor keys 2/3 are validated against `"2"`/`"3"`. The YAML shape is the plan's. (3) The gate tags `sizing.floor_lot` **in place** on the accepted candidate (creating the `SizingNote` if the candidate had none) and overrides the generator's advisory flag: the gate is what decides a lot took the floor; it returns verdicts only. In the deep-dive (`dedupe_same_symbol=False`) the daily count and the floor are tracked per underlying, so the strikes of one name share one slot. (4) `name_regime` on a tie reports QQQ; the daily-count/floor bucket (`governing_index`) is QQQ for any tech-linked name even when SPY is the stricter regime (ruling 16), documented in the module. `SizingNote.regime` reads NORMAL when the regime limits are off, and a note is attached to every CSP candidate whenever a context exists (the card prints a size line only when the lot was cut or is a floor lot). `pre_regime_contracts` is the unscaled capital fit. (5) The send-time context (`approval._send_context`: cached regime refresh + `for_send=True` context, built before the write session) is introduced here, not in Task 4, so `sizing=` is real at send time the moment the keyword exists; a failed build skips the poll (orders stay QUEUED) instead of sending without the limits. Task 4 extends it. A scan's `_build_sizing` runs in the executor and a database failure propagates (fail closed). `_price_and_gate_ticker` refreshes the regime through the cache before building its context (`/scan TICKER` and promote can run before the day's first scan). (6) Seven mocks of `validate_candidates` in `tests/test_execution.py` gained `sizing=None` in their lambda signature (the gate now always receives the keyword); no assertion changed. `generate_csp_candidates` and `roll_pipeline` pass `sizing=None` explicitly. `/regime off` now says the leveraged-ETF limit stays on. (7) Extra tests beyond the plan list: `tests/test_regime_scan_wiring.py` (the value that reaches the sizer, the gate, a one-name scan and the send-time re-gate is the persisted regime), the tie rule, the context's day window/state/close-prefix filters, the card lines, label parity for the four new codes. |
| 4 Send-time regime re-check, trim, counterfactual table | done | `feat(regime): send-time regime re-check, trim, counterfactual table` | pytest **4036 passed, 1 skipped**; ruff clean; mypy clean (274 source files) | 2026-10-21 | (1) The plan's trim tests used TQQQ for the plain regime trim (10 -> 3); under ruling 35 a stressed TQQQ is 1, so the plain trim uses NVDA and TQQQ has its own two tests (a calm 6-lot cut to 1 and recorded as `leveraged_ceiling`; a stressed-tier card never loosened). (2) `link_order` ties the day's rows for a card to its order **at send time** (when the order poll accepts it), not at queue time in `_auto_queue_candidates` / the approve handler: one place covers auto, Telegram and web approvals, and the id only matters once an order is sent. `record_action(order_id=)` still sets it directly for a send-time trim. (3) `scaled_budget_fit` (in `engine/regime_limits.py`, with `hard_max_contracts`) returns None unless the regime is active and the name's budgets are scaled (or it was a floor lot): the trim is a regime behaviour only, so a card that no longer fits the plain book is refused by the gate exactly as before (tested). The functions live there because they read the real config; `approval.get_config` is patched to a MagicMock in many existing tests. (4) The trim kind is `leveraged_ceiling` when the leveraged factor is the binding one, else `escalation_trim`; a trim bound by the scaled budget says ": budget" in the order detail. The order detail keeps the trim note after the order is marked SUBMITTED, and the operator also gets a Telegram line (`notify_msgs`). A trimmed order the gate then cancels keeps its trimmed snapshot and its row (the resolver reads the order state). (5) `record_action(session=)` writes inside a savepoint so a failed row cannot poison the poll's write session (tested with a NULL strike). `record_scan_actions(top, scored, verdicts)` is called from the scan after `select_top_candidates_detailed`: surfaced CSPs cut below their capital-fitted size are recorded under their ceiling kind (or `regime_budget`), a floor lot as `regime_floor_lot` (a floor lot that was also cut gets both rows), and a name none of whose strikes passed, whose best-ranked candidate failed only for regime reasons, once per name/kind/day with `key=csp:<SYM>:<kind>:<ET day>`. (6) `_send_context` also marks every queued CSP whose snapshot tier was stressed (`name_triggers[symbol] = ["snapshot_stressed"]`) and reads the live spot for names whose snapshot carries a ladder zone (stub-tested; the zone itself arrives in Task 6, as does `loss_exit_today`). `tests/test_regime_scan_wiring.py`'s send-time stub account became a real `AccountSnapshot` because the trim now re-fits the budget. **Section A exit met:** four commits; the regime limits apply in the scan and at send time; no ladder yet. |
| **B entry checks** | done | (none) | pytest **4036 passed, 1 skipped**; ruff clean; mypy clean (274 source files) | 2026-10-21 | B1–B4 all pass on HEAD 335183a (4 commits, rows 1–4 done, tree clean; `build_sizing_context`, `ScaleInZone` and `SizingContext.scale_in` present; `price_history` for SPY/QQQ/TQQQ/SOXL 2025-09-01..2026-10-19 = 1140 rows in `$MAIN/data/income_system.db`). Operator said "continue" after Section A. |
| 5 Support detector | done | `feat(analytics): support detector on daily lows; week-of-Oct-13 fixture` | pytest **4046 passed, 1 skipped**; ruff clean; mypy clean (275 source files) | 2026-10-21 | (1) `support_levels` takes one extra optional keyword, `broken_atr: float = 1.0` (the plan's signature has none, but step 3 of the algorithm needs it and says it comes from `ladder.broken_atr`); Task 6 callers pass the configured value. (2) The pinned order is kept: swing lows are merged first (the lower of a close pair is kept, with its own bar), then the broken test runs on the kept levels using closes *after that bar*. Cost if wrong: a merged cluster whose lower member is broken but whose higher member is not loses both; this only makes the zone lower, never looser. (3) With no `atr` given and fewer than 15 bars, the detector claims no level (`[]`); a ties-on-flat-lows bar counts as a swing low (`Low[i] == min(window)`), as pinned. (4) The fixture holds 285 bars per symbol, 2025-09-02..2026-10-19 (2025-09-01 was a holiday); `^VIX`/`^VIX3M` came from the provider on the first try (network available), 287/285 bars. `tests/conftest.py::week_bars(symbol)` accepts `VIX`/`^VIX`. (5) Extra tests beyond the plan list: `tests/test_export_week_fixture.py` (the exporter's database half is read-only, ascending, round-trips to CSV; a missing database is an error and is not created). (6) TQQQ's levels on 2026-10-13 from the fixture: `[75.47, 67.93, 66.55, 57.59, 37.23]` at spot 78.81 (ATR-14 2.76). `scripts/export_week_fixture.py` is a new entrypoint: its `SETUP.md` scripts-table and `ARCHITECTURE.md` `scripts/` entries are Task 23's sweep. |
| 6 Scale-in ladder: anchors, name triggers, zones, gate | done | `feat(regime): scale-in ladder with name-level triggers and a same-day loss-exit block` | pytest **4103 passed, 1 skipped**; ruff clean; mypy clean (277 source files) | 2026-10-21 | (1) `regime.ladder` is a typed, key-checked block like Section A's (`RegimeLadderCfg` with a `KEYS` tuple, added to `RegimeCfg.KEYS`; the shipped YAML block is in `config/examples/risk_limits.yaml` only). (2) **The send-time input the plan relied on did not exist:** `executor._fetch_quote` never filled `OptionQuote.underlying_price`, so the ladder re-check would always have fallen back to `ctx.spot_at_send`. `_fetch_quote` now reads `modelGreeks.undPrice` (positive only); `spot_at_send` (ruling 48) remains the fallback and, when neither exists, "ladder not re-checked: no underlying price" is appended to the order `detail` at the SUBMITTED update (`regime_limits.live_ladder_note`). (3) The send path passes the context explicitly: `execute_candidate(..., *, sizing=)` (new keyword), `approval.process_queued_orders` passes `sizing=sizing`, `roll_executor` passes `sizing=None` (a fence test asserts that exact call); `test_every_send_path_caller_passes_sizing` is an AST walk over `validate_live_quote` and `execute_candidate` callers in `src/`. Ten test mocks of `execute_candidate`/`validate_live_quote` gained `sizing=None` in their signature (no assertion changed). (4) `latest_anchor` takes one extra optional keyword, `spot`, for the plan's `max(strike, spot)` fallback; anchors that have no fill date (held shares, a short put with no system fill) carry `date.min`, so `recovered` counts every close for them and the price level is the discipline. A lot's fill date is the ET date of its latest SELL fill; a closed lot (buy-to-close fills cover its quantity, or its expiry has passed) survives `anchor_survival_days` **calendar** days. (5) "The support that last broke" (recovery level) needed the detector's broken levels: `support_levels.broken_supports()` returns `(level, break date)` and `scale_in.last_broken_support` takes the latest break dated after the anchor lot, else the recovery level is the anchor. (6) `build_sizing_context` gains `spots=` (live price for the near-the-money trigger); by default a live price is fetched (`regime.last_price`, stubbed offline in tests) only for names with a short put, else the last close is used. With no bars the zone falls back to the percentage gap alone (a data gap never lifts the ladder; recovery needs bars). A recovered name drops its `name_triggers` too (the ladder is lifted, so the leveraged tier reads calm); a name with a trigger but no anchor keeps its triggers (tier stressed) and has no zone. `for_send=True` fetches no bars and fills only `loss_exit_today`. (7) `/regime off` (or `regime.enabled: false`) lifts the **zone** (`scale_in_reason` is None when inactive, per the plan) but not the same-day loss-exit block or the name triggers (which still stress the leveraged tier); tested. (8) Spec section 10 requires ladder rejections and loss-exit blocks in the counterfactual record, and the plan's Task 6 text did not do it. The sizer refuses them before the gate, so `record_scan_actions(generator_rejects=)` takes the generator's rejects and writes one `scale_in_zone` / `loss_exit_cooldown` row per name, kind and ET day, only when ladder codes are the **only** reasons (a reject that also failed ROC/yield is not the ladder's doing). (9) Gate pass 1 reads the zone from `ctx.scale_in` and the spot from `cand.ideal.spot` (no `ideal`: skipped, a data gap never rejects); the accepted candidate carries the name's zone into its snapshot (`sizing.scale_in`), which is what `validate_live_quote` re-checks against the live price. The send-time context has no zone of its own. (10) Extra tests beyond the plan list: ladder config values and key list, zone cap/crisis gap, last-broken-support, recovery needs both sma20 and level, the anchor falls back to the fill-date close, an expired lot survives `survival_days`, a short put with no fill, a cancelled order is not a lot, ET-day boundary of a loss exit, the loss-exit block can be switched off, `_send_context` carries today's loss exits, the five new ladder modules stay in the deterministic tier (AST), the executor test with a real `validate_live_quote`, label parity and card line, ladder-block recording. |
| 7 Bottoming signal and the week-of-Oct-13 replay | done | `feat(regime): bottoming signal; week-of-Oct-13 replay` | pytest **4139 passed, 1 skipped**; ruff clean; mypy clean (278 source files) | 2026-10-21 | **HARD GATE MET (ruling 38): SOXL 100P (10-13), TQQQ 75P (10-13), TQQQ 70P (10-13) and TQQQ 68P (10-14) are all blocked** by the rules as built, in a replay whose state is built only from the lots it lets through. Evidence: SOXL 100P `loss_exit_cooldown` (the 130P stopped 13:34 UTC; also zone 99.9-112.1 vs spot 122.93); TQQQ 75P and 70P `near_money_put` on the 78P (spot 78.12 <= 78 + 0.5 x ATR 2.79 = 79.4), anchor 81.79, zone 74.07-76.87, spots 78.12 / 78.41 above its top, recovery not met (the closes of 10-09 and 10-12 are under the 81.79 anchor); TQQQ 68P `loss_exit_cooldown` (the 78P stopped 15:15 UTC the same day). The tests have teeth: switching the cooldown off lets TQQQ 68P through, and `near_money_atr: 0` (a strict in-the-money test) lets TQQQ 75P and 70P through. **Replay (`scripts/replay_week.py --db $MAIN/data/income_system.db`, read-only; 2026-09-30..10-20; spec 19 in brackets):** 40 CSP opens judged [41; a partial fill is counted at its filled size and the roll successor is not an open here]; **9 blocked [10], 4 trimmed [4]**; contracts **168 -> 122** (-27%) [178 -> 129, -28%]; loss exits **-$7,824 -> -$3,274** [-$7,840 -> -$3,280]; the four must-catch entries avoided -$3,915 [-$3,925]. Week of Oct 13: 24 entries, 8 blocked. The four trims are TQQQ 74P / 77P / 78P (10 -> 6, calm 3x) and TQQQ 60P on 10-16 (3 -> 1: QQQ escalated to stressed, -2.85% at the low). **Finding, not tuned away:** total CSP P&L is **+$4,671 -> +$6,368** [-$5,253 -> -$1,298]. The levels are not comparable: no option marks are stored, so open legs here are intrinsic-only (every unexpired out-of-the-money put keeps its whole premium); the $9.9k level gap is consistent with the time value the spec's 10-20 marks carry on the open GOOGL / TQQQ legs, but that was not measured. The gain is +$1,697 [+$3,955]: it blocks five losers (-$4,246: SOXL 100P, TQQQ 75P / 70P / 68P, SOXL 90P 10-19) and four winners it cannot see coming (-$2,363: GOOGL 335P 10-02 +$195, TQQQ 65P x5 +$1,280, TQQQ 67P +$158 and TQQQ 65P x5 +$730, all 10-19) and trims four (-$187). **The three TQQQ blocks on 10-19 (+$2,168 of winners) are the ladder doing its job slowly:** after the 10-16 lot (anchor 68.0) the zone is 55.95-59.23 against TQQQ at 70-72, and recovery needs two closes above the 20-day average (78.4 on 10-19) and the anchor, so a 3x ETF that has dropped 20% stays blocked unless it falls another 15% or climbs back above its 20-day average. **VRP gate (spec 6b), the week of 10-13..19:** of 12,242 SOXL/TQQQ CSP candidate evaluations 2,831 (23%) were rejected `premium_below_fair_value` (199 distinct contracts, 140 scan/name pairs): a bottoming lot meets this gate like any other and the signal does not change it (an operator decision, not part of this build). **What an ease stressed -> cautious unlocks:** guaranteed floor 1 -> 2 lots a day per index, per-trade ceiling 3 -> 6 contracts, daily limit 3 -> 6, budget multiplier 0.4 -> 0.7. Rulings: (1) `regime.bottoming` is a typed key-checked block (`RegimeBottomingCfg`, in `RegimeCfg.KEYS`); `get_regime_cfg()` raises `ValueError` when `signal_delta_max <= cash_secured_put.delta_min` (ruling 42, tested both directions; `get_cc_timing_cfg` is Task 16). (2) `market_bottoming` is order-aware: the peak must come after the lowest close before it (the plan's window-low arithmetic would also read a decay from an old peak as a spike), and every missing input (live VIX, live index, VIX3M history, frames) is no signal, never a guess; it returns reasons for the notice. (3) `refresh_regime` eases ONE notch only when the effective regime is stressed or crisis, is **not above its base** (a regime the tape raised earlier today is not eased away), no escalation threshold is breached now, and the signal was not cancelled today; any breach today sets `bottoming_cancelled_on = today` and restores the escalated regime; the next trading day starts clean. Bars (`^VIX`, `^VIX3M`, the index) are fetched outside the lock and only when the index could ease. Changes read "bottoming: ..." / "bottoming signal ended"; `/regime` says "eased one notch by a bottoming signal" (it would otherwise have said "raised today"). (4) The name signal is evaluated per name under a zone in `build_sizing_context` (completed bars; the live spot, fetched through `regime.last_price` for those few names unless `spots=` is given); a **signal lot** is a lot above the zone that the signal lets in (`regime_limits.signal_lot`), and only it meets the guards (`bottoming_guard`: delta cap, one per name per N sessions, counted in trading days). A lot inside or under the zone is an ordinary ladder lot. (5) **Interpretation to confirm with the operator:** the market-level signal only eases the regime; lots sized under an eased regime are tagged `sizing.bottoming = "market"` (informational) and carry no extra guards and no `bottoming_lot` row. Spec 6b's "guards on any lot opened on either signal" is read as the name signal's guards: a delta cap and one lot per three sessions on every lot of an eased regime would make "ease one notch" a near-stop. (6) A signal lot is recorded `kind="bottoming_lot"` when the order poll **sends** it (not at scan), so a card nobody approves does not use up the name's turn; `signal_lot_recent` reads those rows. The frozen zone of a signal lot carries `bottoming_signal=True` and `live_ladder_reason` / `live_ladder_note` skip the zone re-check for it (its spot is above the zone by definition; the same-day loss-exit block still applies at send); and the gate no longer erases a `bottoming` tag already on the card (the send-time context has no signals) - found by `test_a_name_signal_lot_is_recorded_when_it_is_sent`. (7) The replay engine is `scripts/replay_week.py` (importable): it drives the real `refresh_regime` day by day (an intraday escalation uses the day's low: a look-ahead within the day), `build_sizing_context` per entry from bars strictly before the entry's day, `loss_exit_reason`, `scale_in_reason`, the bottoming guards, `daily_limit` and `per_trade_cap`, against a scratch database (the CLI points storage at a temp file; the tests use their tmp database). Not replayed (first order, as in spec 19): the budget multiplier and floor, premium/VRP/IV gates, Claude's cut. (8) Extra tests beyond the plan list: config values and key list, the delta guard in both directions, the crisis ease, signal ending, an earlier escalation is not eased away, calm regime unaffected, the sizer's guards and a real far strike (delta 0.23) passing, the gate's tag, the floor with a full book and with the floor used up, the live re-gate for a signal lot, `signal_lot_recent` by sessions, `/regime` wording, the replay's hypothetical second lot (each later lot needs a lower price) and its state-only-from-allowed-lots check. |
| **C entry checks** | done | (none) | pytest **4139 passed, 1 skipped**; ruff clean; mypy clean (278 source files) | 2026-10-22 | C1-C4 all pass on HEAD 5522517 (7 commits, rows 1-7 done, tree clean; `edit_digest` and `digest_reads` in `src/news/explain.py`, `editor = await asyncio.to_thread(edit_digest` in `src/news/service.py`, `call_llm(prompt: str, *, schema: dict, prefix: str, now: datetime)` in `src/news/llm.py`; `tests/test_news_fence.py` 8 passed). Operator said "continue" after Section B. |
| 8 News tables, config, reserved LLM budget | done | `feat(news): triage and picture tables, config, reserved LLM budget` | pytest **4159 passed, 1 skipped**; ruff clean; mypy clean (279 source files) | 2026-10-22 | (1) **The general share is `min(cap, max(1, cap - reserved))`, not the plan's `cap - reserved`.** With the shipped reserve of 10 and a cap at or below 10 the plan's formula gives zero general calls: the existing `test_cap_stops_calls` / `test_cap_applies_between_backends` (they patch `max_calls_per_day=1`) would fail, and so would an operator's small private cap. At the shipped 40/10 it is identical (30). Cost if wrong: with a reserve at or above the cap one general call a day still gets through. (2) `incr_llm_calls(day, purpose="general")` bumps the day's total (`llm_calls:<day>`, still what `GET /news/status` reads) and `llm_calls:<day>:<purpose>` in one transaction, so the picture count is stored too; `llm_calls(day, purpose=None)`. `cap_reached(now, purpose="general")`. (3) `MarketPicture` gains `stale: bool = False` (the plan's interface has none, but `latest_picture` has to hand the row's `stale` flag to readers; the row's flag wins over the JSON's). (4) `triage_since(s, since)` filters on the cluster's `last_seen >= since` (a story still current), joined to `news_clusters` for the headline; a triage row whose cluster was pruned is skipped. `latest_picture` returns None when the stored payload no longer validates; all three readers return empty on `OperationalError` (an old news.db opened read-only). (5) `NewsTriageCfg` / `NewsPictureCfg` are plain typed blocks with bounds validators (HH:MM times, `batch_size >= 1`, `story_match_jaccard` in (0, 1]), like the other `news:` blocks; they do not use Section A's `_KeyedCfg` because `tests/test_config_keys.py` covers only `risk_limits.yaml` and `settings.yaml`, not `news.yaml`. (6) `render_picture`: a regime line reads `QQQ: stressed (base cautious; eased by a bottoming signal)` with only the notes that apply (`base X` when it differs, the ease, `limits suspended today`); `regime_source == "news"` adds one line saying the news service estimated it; the 300-word target is met by the builder bounding stories (5) and facts (12), not by truncating in the renderer. (7) `tests/test_news_fence.py::_ROW_CLASSES` gained the three row names, as the plan says. Extra tests: stale JSON/row flag, a payload that no longer validates, `triage_since` join, the one-general-call floor, a failed attempt counted under its purpose. **Note:** the Section C prompt names `tests/test_regime_fence.py`; no such file exists in this branch (the fence tests are `test_eval_skills.py`, `test_news_fence.py`, `test_web_fence.py`, `test_spreads_fence.py` plus the AST tier tests in `test_regime_classifier.py` and `test_scale_in.py`); all of them are green. **Docs owed to Task 23:** `ARCHITECTURE.md` `src/news/` section (three tables, `llm.reserved_for_picture`, `triage:` and `picture:` keys) and `src/common/` entry for `picture_text.py` plus the `MarketPicture` family in the data-flow section; `SETUP.md` §17 (the three new `news.yaml` blocks; the operator's private `config/news.yaml` needs no edit, every key has a code default); `STATUS.md`. |
| 9 Triage: floor, batch call, digest integration | done | `feat(news): three-pile triage with a deterministic floor; digest uses it` | pytest **4187 passed, 1 skipped**; ruff clean; mypy clean (280 source files) | 2026-10-22 | (1) `explain._validated` became the public `explain.validated_call(..., purpose=)` (both the call and its one validation retry count against that purpose); `explain_card` and `digest_reads` gained `picture_text=`; `explain.latest_picture_text(now)` reads the newest stored picture and renders it (None before the first one: the prompt then has no picture block). `followup.complete_post` passes it. The picture block follows RULES in the writer and digest prompts with one framing line ("Context for framing only: do not quote its numbers, do not cite it"), so the card's grounding refs stay its own facts. (2) `EditorOutput`, `EditorThread`, `editor_prompt`, `EDITOR_SCHEMA` and `edit_digest` are deleted. Two existing tests exercised the editor and were **replaced in place, none deleted or loosened** (their premise is gone by the plan's own instruction): `test_news_explain.py::test_editor_drops_unknown_cluster_ids` -> `test_digest_reads_drop_unknown_cluster_ids` (the same invented-cluster property on the surviving function; the triage twin is `test_triage_ignores_cluster_ids_the_model_made_up`), and `test_news_service.py::test_digest_uses_editor_order_and_reads_or_falls_back` -> `test_digest_uses_triage_order_and_reads_or_falls_back` (the same `[[2],[1]]` / `[2,1]` ordering and explained/fallback stage assertions, now driven by stored piles; the second half asserts the deterministic fallback). (3) `TriageView` gained `rank` (the digest orders each pile by it; the plan's field list had none). (4) **Beyond the plan, a digest fallback:** `triage_last_ok` (news_state) records the last usable model answer; `_order_by_triage` only replaces the digest's order when the model judged something since the digest window opened (`triage_ok_since`). Without it a model outage (cap reached, CLI down) leaves only floors and not-reviewed rows in the store and the digest would go empty; with it the digest keeps its old deterministic order and no reads. A triage exception inside a digest is logged and the digest still posts. (5) A floored cluster with no model verdict is stored at **pile 2** with reason `floor: alert rule` / `floor: held name`, both when the call fails and for a floored cluster outside the batch (batch overflow), so the floor holds without a call. A model answer that the floor lifts keeps its words: `floor: alert rule (model: <reason>)`. (6) **Beyond the plan:** a judged-noise row (pile 3) that later gains a floor (an alert fires, a name becomes held) is lifted to pile 2 on the next run with no model call, alongside the plan's re-triage of pile-None rows; `alerted_ids` reads posts of the last 48 h (not just "the triage window") so a later alert reaches a cluster stored earlier, and counts every non-digest post (alert cards, briefs, late-promotion posts). (7) Clock: the first run ever (or after an outage) looks back 16 h, later runs from the start of the previous run, never more than 48 h; `triage_last_run` stores the run's start so a cluster created during the call is picked up next time; `triage_due` is a configured ET slot passed since the last run, trading days only; the digest's own run needs no slot. A cluster the model omitted from a batch it answered stays not reviewed (and is not retried), like any cluster outside the batch. (8) Digest: `DigestInputs.since` (set by `gather_inputs`, None means 16 h) bounds the story window; `_order_by_triage` replaces `inp.clusters` with the pile 1/2 clusters (pile 1 first, then 2, each by rank desc; a floored story always eligible), loading any the digest's own 30-cluster query missed, and sets `thread_order=[[id], ...]`; `digests.regime_line` renders `SPY normal · QQQ stressed` from `load_regime_state()` and `_rank_digest` sets `inp.regime` (the service imports `load_regime_state` at module level). (9) `TriageItem.reason` keeps the pinned 120-char limit: a longer reason fails validation, retries once (the retry counts), then the batch has no verdict. The triage prompt drops the writer rules' "cite the ids" line (as the old editor prompt did) and does not tell the model about floors. (10) `prompts.py` imports `TriageCandidate` only under `TYPE_CHECKING` (triage imports prompts). **Docs owed to Task 23:** `ARCHITECTURE.md` `src/news/` table (`schemas.py` row names `EditorOutput`; `prompts.py` "Editor, writer and digest prompts"; `explain.py` "Writer and editor passes"; a new `triage.py` row; the digest description), `SETUP.md` §17 (the triage loop and its three RTH slots), `STATUS.md`. |
| 10 Stories and the market picture | done | `feat(news): multi-week stories kept alive in Python; grounded market picture` | pytest **4231 passed, 1 skipped**; ruff clean; mypy clean (283 source files) | 2026-10-22 | (1) **A cluster's signature leaves out the tagger's four style tags** (`scheduled`, `rumor`, `quantified`, `forward_looking`) **and the unclassified topic `other`.** Those describe how a headline is written, not what it is about: any two clusters tagged `quantified` would share a token, and two such strangers can keep a story alive, which is the loose match spec section 8 forbids. Since the tagger emits only those four, the "tags" part of ruling 21 contributes nothing today; a future topical tag would count. Cost if wrong: matching is only stricter (a story ends sooner), never looser. (2) `story_alive(story, new_ids, ...)` reads `new_ids` as "this story's clusters, old or newly attached, that the caller found inside the window" (the row stores ids, not attach times, so the caller selects by the cluster's `last_seen`); a young story is one started within `window_days` **ET days**. (3) `match_clusters` takes in `clusters` both the candidates and the clusters the stories already hold (a story's signature is the union of the held ones); a cluster no story holds attaches to the highest-Jaccard story at or above the threshold, ties to the older story. (4) `PictureDraft.stories` keeps the pinned `max_length=5`, so `news.picture.max_stories` gained `le=5` (Task 8's block tightened) rather than letting a larger config value fail every answer. (5) `picture_prompt` gained keyword-only `piles` and `max_stories` (the plan's signature has neither): `piles` marks each cluster's triage pile so the model knows only pile 1 may start a story; previous stories appear as `S<id> <title> (since <date>)`, never with their prose. (6) **Validation (`picture.validate_drafts`):** evidence is filtered to ids that exist (`C<id>` of a pile 1/2 cluster the model was shown, `F<n>` of the sheet); none left drops the story, a continued one included; a story id the model made up **or that Python has ended** is treated as a new story (needs a pile 1 cluster), so a dead story cannot be revived; the **title** gets the same grounding/advice/meta checks as the description (and a `C<id>` in prose drops the story: grounding's `_ID` knows only `N#`/`F#`); a continued story keeps its stored title and start date (the model's title is ignored); numbers are grounded against the fact sheet only, as the plan says. A dropped continuation stays alive in Python and is offered again at the next rebuild. (7) **Facts:** one numbered fact per index (close, vs 50/200-day, drawdown from the 52-week high, 1m/3m return, from the trading record's `RegimeInputs`), then `build_market_facts({}, backdrop)` (VIX, VIX/VIX3M, 10-year, 10-year 5 days; the record's VIX/term ratio when the backdrop is unavailable) and one `10y 1m change` from `^TNX` (quoted x10): about seven facts, so the picture stays near 300 words. `facts.py` has no dollar, oil or gold, so none were added. The `news` regime fallback is a base classification only (no hysteresis, no intraday). (8) `upcoming_events`: High-impact releases in the next seven days and **held-name** earnings, soonest first, at most 8. (9) `picture_due`: the first picture is due at once; a pre-market or close digest time (ET trading days) has passed since the last build; or a pile 1 row was judged since it; at most `max_rebuilds_per_day` rows per ET day (a stale build is a row and counts). (10) Build: no model call when there is nothing to say (no live story and no pile 1/2 cluster); the model sees at most 40 pile 1/2 clusters (pile, rank, recency); all reads happen first, the call runs with no database session open, then one write session saves story attachments, ended stories (`active=False`, `ended_on`), new stories, `story_triage.story_id` for attached and cited clusters, and the picture row. (11) `seasonality.py` sits in the **deterministic tier** as the plan's Global Constraints list it (a pure computation over `src/data`; its docstring says nothing in the engine reads it). The provider's 5-year cap means a 5-year fetch usually yields four completed Octobers (the first partial year has no prior month-end); `years` reports what was found. The month still forming is excluded; only consecutive months count. (12) The tests have teeth: seven mutations (style tags counted, young-story clause removed, pile 1 rule removed, advice check removed, grounding removed, evidence check removed, dead story revivable) each failed a test; the evidence one exposed a gap (a *continued* story citing nothing) that now has its own test. **Docs owed to Task 23:** `ARCHITECTURE.md` `src/news/` (`stories.py`, `picture.py`) and `src/analytics/` (`seasonality.py`), `SETUP.md` §17 (the picture loop, its rebuild rule), `STATUS.md`, root `CLAUDE.md` is Task 15's. |
| 11 Noise check (safeguard 2) | todo | | | | |
| **D entry checks** | todo | | | | |
| 12 Picture text and the trade reviewer (book, size fields, no history) | todo | | | | |
| 13 Roll, EOD and spreads readers | todo | | | | |
| 14 Claude's cut, the manual card, the review fingerprint | todo | | | | |
| 15 Counterfactual resolver, report, rule amendments, fences | todo | | | | |
| **E entry checks** | todo | | | | |
| 16 CC breakout rule: resistance detector, floor in the generator and the gate | todo | | | | |
| 17 Dossier store, deterministic facts, health, verified events | todo | | | | |
| 18 Dossier builds: batched prose, grounding, cadence, budget | todo | | | | |
| 19 Dossier readers: trade review, roll review, `/scan` | todo | | | | |
| 20 ~~Claude's CC event hold~~ — removed 2026-10-21 (spec decision 34) | removed | none | n/a | 2026-10-21 | Nothing to build; see the Task 20 stub. |
| **F entry checks** | todo | | | | |
| 21 `GET /claude/context` | todo | | | | |
| 22 "What Claude knows" page | todo | | | | |
| **G entry checks** | todo | | | | |
| 23 Docs and full gate | todo | | | | |

## Rulings made up front (the operator may overturn any of them)

1. **Name collision.** `src/common/schemas.py` already has `Regime` (a per-ticker technical label)
   and `Phase`. The new market regime is `MarketRegime` (`normal`, `cautious`, `stressed`, `crisis`)
   — never reuse or rename `Regime`.
2. **Regime config lives in `config/risk_limits.yaml → regime:`** (the risk dict is untyped), parsed
   into a typed `RegimeCfg` by `get_regime_cfg()` in `src/common/config.py`. Invalid config fails at
   first use with a `ValueError`, like the other typed blocks.
3. **Regime state is JSON in `system_settings`** (key `market_regime_state`, plus
   `regime_suspended_on`), written only by the trading process through `src/storage/regime_state.py`
   — no new table. The news process and the API read it read-only.
4. **The sizer and the gate take an explicit `sizing: SizingContext | None` keyword.** `None` means
   no regime behaviour (tests and back-compat). Every production call passes it explicitly
   (`sizing=None` only in `roll_pipeline.py`, with a comment); a fence test enforces the keyword.
5. **Budgets:** the total CSP allocation scales by the **SPY** regime's multiplier; the per-ticker
   and per-sector risk/collateral caps scale by the **name's** regime multiplier (SPY's, or the
   stricter of SPY's and QQQ's for a tech-linked name). Only CSPs reach pass 2 of the gate, so CCs and
   rolls are untouched by construction; the roll exemption is still asserted by a test.
6. **Distinct reasons.** A candidate stopped only because of a regime-scaled cap gets `regime_budget`
   (the gate re-checks against the unscaled caps to tell); over the per-trade ceiling gets
   `regime_ceiling`; over the day's count gets `regime_daily_limit`; the ladder gets
   `scale_in_zone_not_reached`; a bottoming lot that breaks its guards gets `bottoming_delta_too_high`
   or `bottoming_lot_recent`.
7. **Regime-change notices** are sent by the scan (it already imports `src.notify.sender`), not by the
   send-time refresh in `src/execution/approval.py`; a change found at send time is persisted as
   unsent and the next scan (≤ 15 min) sends it.
8. **The ladder at send time** is re-checked in `validate_live_quote` from the snapshot's
   `sizing.scale_in` zone and the fresh quote's `underlying_price`; the regime limits and the daily
   count are re-checked in `approval.process_queued_orders`' batched `validate_candidates` with a
   fresh `SizingContext(for_send=True)`.
9. **Anchors:** the most recent CSP lot on the name (open, or closed within
   `ladder.anchor_survival_days`), its spot from the order snapshot's `ideal.spot`, else the
   `price_history` close on the fill date; else held shares' `avg_cost` (assignment); else a short put
   in `positions` with no system fill: `max(strike, spot)`. Rolls never move the anchor.
10. **Shadow marks are to expiry** (intrinsic at the expiry close from `price_history`), not to the
    exit rules — deterministic and cheap; the report says so.
11. **Spreads read the picture's embedded regime, labelled "as of <built_at>"** — no extra fetch in
    the spreads process.
12. **The digest's editor pass is replaced by the triage output** (piles 1 and 2 ordered by rank),
    which also removes `EditorOutput.regime`. `digest_reads` (the writer call) stays.
13. **`/regime`** is the Telegram command: no argument shows both regimes and limits; `off` suspends
    every regime limit until the next trading day's base; `on` resumes.
14. **My earlier estimate** (the operator conversation, 2026-10-20) that the name-level rules would
    have blocked ~$3.9k of the week's loss exits assumed blocking; under the agreed zone rule some of
    those re-entries may have been allowed at the next zone at a smaller size. Task 7's replay
    measures it and records the result in the Progress log; no test asserts a dollar figure.
15. **Vol index for QQQ — VIX for both indices (operator, 2026-10-20).** **VIX for both
    indices**, so the spec's VIX thresholds (daily and the intraday 30/40) mean the same thing for
    SPY and QQQ; QQQ's own stress comes from QQQ's intraday move and its trend. (^VXN with the same
    thresholds would hold QQQ and every tech-linked name at `cautious` on ordinary days: VXN closed
    20.6–22.9 through early October 2026.) `RegimeInputs.vol` is VIX for both.
16. **Daily-limit scope — per governing index (operator, 2026-10-20).** The count is **per governing
    index** — a name governed by QQQ's regime (tech-linked) counts against QQQ's daily limit with
    other tech-linked opens; every other name counts against SPY's. So BAC opens never use up TQQQ's
    stressed limit.
17. **Partial cuts are valued at the traded contract's realised P&L** (spec §10): once the traded
    leg has closed, `withheld × its realised P&L per contract`; until then, and for lots not sent at
    all, a shadow mark to expiry (ruling 10).
18. **A confirmed recovery lifts the ladder for that name** whatever its triggers (spec §6), until a
    trigger fires again.
19. **A budget that shrank between card and send is trimmed** (spec §5): the send-time size is
    `min(per-trade cap, the budget-fitted size from capital.max_contracts with the scaled caps)`;
    zero → reject with the regime reason.
20. **Every scan-time trim or block is recorded, once per (candidate, kind, ET day)** (spec §10 says
    every trim); `summarize` reports "sent smaller" and "never sent" separately.
21. **Story matching uses tickers, tags and topic only** (spec §8), not title tokens.
22. **Token use is measured by the operator after restart** (`python -m scripts.claude_usage`); a
    builder cannot run real `claude -p` calls in tests. Task 23 records the prompt sizes it can
    measure offline (rendered picture, book and dossier blocks, in words) in the Progress log.
23. **Dossier coverage** is `would_own ∪ actively_wheeling` from the effective universe (web
    overrides count) ∪ every held underlying from `collectors.held_underlyings()` — about 33 names.
24. **A dossier carries no book.** `build_ticker_facts` is called with `positions=[]`; the trade
    reviewer's book block (Task 12) already shows positions and stop-outs, so they are never
    rendered twice.
25. **Dossier budget** (numbers revised by ruling 43): deterministic facts are refreshed hourly with
    no LLM call; prose is batched 6 names per call under its own `dossier.max_calls_per_day: 4`. The
    example `llm.max_calls_per_day` rises 40 → 44 so general news calls keep their 30. The operator's
    private `news.yaml` needs the same change by hand.
26. **A dossier answer that fails validation for one name** drops that name's story (never the
    previous story) and keeps its previous profile; only a failed call (no answer) keeps the previous
    prose, marked stale. This refines the spec §16 sentence "a failed or ungrounded build keeps the
    previous prose".
27. **Verified events persist until their date.** Python verified them against the news, so they are
    data, not prose; carrying them forward does not re-feed Claude's words (decision 26 holds).
28. **The breakout is recomputed from daily bars on every scan** (no table). It is a decision-time
    rule: the send-time gate re-checks only from the snapshot's `cc_breakout` and fetches no bars.
29. **The breakout rule has its own switch** (`cc_timing.breakout.enabled`) and is not a regime
    limit: `/regime off` and `regime.enabled: false` leave it on. `build_sizing_context` therefore
    returns a context whenever either the regime or any `cc_timing` switch is on; `active()` is
    unchanged.
30. ~~One Claude hold per name.~~ **Withdrawn 2026-10-21** with the CC event hold (spec decision 34).
31. ~~A hold applies only while the name may auto-open.~~ **Withdrawn 2026-10-21** (decision 34).
32. ~~The `far_only` floor is the breakout floor formula.~~ **Withdrawn 2026-10-21** (decision 34);
    `breakout.cc_floor` stays for the breakout rule itself.
33. **Covered-call timing rows are keyed per name and day** (`cctiming:<SYM>:<ET day>`) through
    `record_action(key=...)`, so a different near strike rejected on each scan still counts once; the
    day's first contract is the counterfactual.

**Added 2026-10-21 (second review and replay; spec decisions 31–39). Where one of these and an
earlier ruling differ, this one wins.**

34. **The guaranteed floor** (decision 31). `regime.csp.floor_new_per_day: {normal: 0, cautious: 2,
    stressed: 1, crisis: 1}`, per governing index per ET day. In the sizer and in gate pass 2, a CSP
    whose **only** budget reason is `regime_budget` (it fits every unscaled cap) is accepted while
    `floor_lots_counted[index] + floor_accepted_so_far[index] < floor_new_per_day[regime]`, sized
    `min(unscaled fit, per_trade_cap(...))`, with `sizing.floor_lot = True`. It still counts against
    the daily limit (`regime_daily_limit` applies first). Floor lots already sent today are counted
    from today's `OrderRow`s whose snapshot has `sizing.floor_lot` true. Each floor lot is recorded
    `kind="regime_floor_lot"`. When the floor is used up the reason stays `regime_budget`.
35. **Leveraged-ETF ceiling, tiered** (decision 32 as revised 2026-10-21). Top-level
    `config/examples/risk_limits.yaml → leveraged_sizing: {enabled: true, per_trade_fraction:
    {calm: {2: 0.8, 3: 0.6}, stressed: {2: 0.5, 3: 0.3}}, leverage: {TQQQ: 3, UPRO: 3, SOXL: 3,
    DPST: 3, LABU: 3, TSLL: 2}}` — not under `regime:`, so `/regime off` and `regime.enabled: false`
    leave it on (like ruling 29). A name in `universe.leveraged_etfs` missing from `leverage` is
    treated as 3× and logged once as a warning; TSLL's factor is the operator's to confirm.
    **Tier (pinned):** `leverage_tier(ctx, symbol) -> Literal["calm","stressed"]` → `"stressed"`
    when the name's regime (`name_regime`, the stricter of SPY/QQQ for a tech-linked name) is not
    `NORMAL` **or** `ctx.name_triggers.get(symbol)` is non-empty (any ladder trigger — Task 6 fills
    it, before Task 6 it is always empty); else `"calm"`. When the regime is suspended or disabled,
    the regime part reads as `NORMAL` but name triggers still count. `per_trade_cap(ctx, symbol,
    hard_max)` becomes: `rf = fraction[regime] if active(ctx) else 1.0`; `base = floor(hard_max ×
    rf)`; when `base == 0` return 0; when the name is leveraged and `leveraged_sizing.enabled`,
    `lf = per_trade_fraction[leverage_tier(...)][factor]` and return `max(1, floor(hard_max × rf ×
    lf))`; else `base`. A
    candidate trimmed where the leveraged factor is the binding one gets the note/record kind
    `leveraged_ceiling` (gate reason `leveraged_ceiling` when a stale snapshot is over it);
    otherwise `regime_ceiling`. `build_sizing_context` returns a context when the regime, any
    `cc_timing` switch **or** `leveraged_sizing.enabled` is on. Rolls pass `sizing=None` and are
    exempt.
36. **Claude's cut modes** (decision 33). Top-level `config/examples/risk_limits.yaml → claude_cut:
    {apply_in_paper: true, apply_live: false, breaker_min: 4, breaker_pct: 50}`. Paper or live is
    `get_config().is_live` (`LIVE_TRADING`, `src/common/config.py:1332`), the same flag the
    connection banner reads. **Only overrides are recorded:** a valid `claude_cut(...)` result below the
    deterministic size writes `kind="claude_cut"` when applied, `kind="claude_cut_unapplied"` when
    not (live mode, or the breaker tripped); equal sizes write nothing.
37. **Ladder fixes** (decision 35). `ladder.near_money_atr: 0.5` — the trigger `near_money_put`
    (replacing `itm_put`) fires when a short put on the name has `spot ≤ strike + near_money_atr ×
    ATR-14`. `recovered(..., after: date)` counts only closes dated after the anchor lot's fill
    date (and needs `closes` of them). `ladder.loss_exit_same_day_block: true` — a `loss_exit` BUY
    fill on the name earlier in the same ET day rejects a new CSP with `loss_exit_cooldown` in the
    sizer, gate pass 1 and at send time (`SizingContext.loss_exit_today: list[str]`, filled for
    `for_send=True` too — a cheap DB query, no bars).
38. **The week replay is a pass/fail gate** (decision 35). `tests/test_week_replay.py` asserts that
    SOXL 100P (10-13), TQQQ 75P and 70P (10-13) and TQQQ 68P (10-14) are blocked. If the rules as
    built do not block them, **stop and report** — never loosen the test to make it pass.
39. **Classifier corrections** (decision 36). `thresholds.vol_pct_cautious: 90.0` and
    `thresholds.vol_pct_min_vol: 20.0` (the percentile rule fires only with both). `get_bars` drops
    any row dated today (ET) for every symbol. `fetch_live_inputs` marks a live value stale when it
    equals the prior close to 4 decimals.
40. **Intraday escalation expires at the close** (decision 36). `IndexRegime` gains `base_since:
    date` (the date the base last changed). The new day starts from **yesterday's base**, eased by
    the hysteresis rule against `base_since`; the effective regime is `stricter(base,
    today's intraday escalation)` only. Supersedes Task 2 rule 1 as first written.
41. **Regime state writes are serialised.** `src/storage/regime_state.py` wraps every
    load-modify-save in one module-level `threading.Lock` (`update_regime_state(fn)`), because the
    scan thread and the order poll's `to_thread` both write it.
42. **No empty delta band** (decision 39). `regime.bottoming.signal_delta_max: 0.25` and
    `cc_timing.breakout.delta_max: 0.25`. `get_regime_cfg()` / `get_cc_timing_cfg()` raise
    `ValueError` when either is ≤ the matching strategy's `delta_min` in `risk_limits.yaml`.
43. **Dossier cadence** (decision 37). `dossier_due` has no `age` reason; `dossier.prose_min_interval_hours:
    6` (a name with `prose_at` newer than that is not due unless the reason is `new`, `alert` or
    `earnings`); `dossier.max_calls_per_day: 4`; `llm.max_calls_per_day: 44`. `prose_max_age_hours`
    is removed. The review fingerprint keys the dossier by `prose_key` (`prose_at` ISO plus the
    sorted event ids and dates), not by `version`.
44. **Counterfactual values** (decision 38; supersedes ruling 10). `SizingActionRow` stores
    `shadow_pnl_expiry` and `shadow_pnl_rules`: the first as ruling 10 described; the second walks
    daily closes from the action day to expiry, prices the put with Black-Scholes at the snapshot's
    `current_iv` and the risk-free rate the analytics already use, and applies the system's own
    profit-take and loss-exit thresholds (`config/settings.yaml → profit_take_pct` /
    `profit_take_schedule` and `max_loss_multiple`, read through the same accessors
    `src/execution/position_manager.py` uses — `grep -n "profit_take_pct\|max_loss_multiple" src -r`),
    else expiry. Never-sent
    CSP rows are keyed `csp:<SYM>:<kind>:<ET day>` through `record_action(key=...)`.
45. **Breakout rows that only pushed the strike out.** `summarize` reports a `cc_breakout_floor` row
    as `pushed_out` (count only, no P&L) when an `OrderRow` for a covered call on the same
    underlying was created the same ET day; only the others count as "never sent".
46. **Seasonality is 5 years**, not 20: the price provider caps lookbacks at `"5y"`
    (`yfinance_backend.py:43-45`). `month_seasonality(month, *, years=5)`; the picture says "5-year".
47. **Profiles may name an index or a leverage multiple.** Before `grounding.extract_numbers` checks a
    profile, the text has `-?\d(\.\d)?x\b`, `S&P 500`, `Nasdaq-100`, `Nasdaq 100`, `Russell 2000`
    and `Dow 30` removed (case-insensitive), so "a 3x daily Nasdaq-100 fund" is not rejected.
48. **Send-time ladder spot.** When `quote.underlying_price` is None (paper fallback greeks), the
    ladder re-check uses `ctx.spot_at_send[symbol]`, fetched by `_send_context` through the price
    provider's `get_last_price` outside the write session; if that is None too, the re-check is
    skipped and the order `detail` says "ladder not re-checked: no underlying price".

## Global Constraints

- **Core invariant (amended in Task 15, operator decisions 3, 15 and 33):** the Rules Engine is the
  only path to an order. Claude may lower — never raise — the contract count of an auto-opened
  opening CSP (`claude_cut`), applied in paper and record-only in live until the operator switches
  it on; nothing else an LLM produces reaches a gate, a size, a strike, a price, an exit or a roll.
  There is **no** covered-call exception (decision 34).
- Deterministic tier (may feed the engine): `src/analytics/{regime,support_levels,scale_in,bottoming,seasonality,breakout}.py`,
  `src/regime/`, `src/storage/regime_state.py`, `src/engine/regime_limits.py`. None of them imports
  `src.claude`, `src.news`, `src.spreads_ai`, `src.analytics.market_conditions`,
  `src.analytics.sentiment` or `src.analytics.sector_context`.
- Enrichment tier: `src/news/{triage,stories,picture,noise_check,dossier}.py`, `src/claude/picture_context.py`,
  `src/claude/book_context.py`, `src/claude/dossier_context.py`. Never imported by `src/engine/`, `src/execution/`, `src/strategies/`,
  `src/spreads/`.
- `src/common/picture_text.py` and `src/common/dossier_text.py` are neutral (import only `src.common.schemas`).
- No regime check, leveraged-ETF ceiling, ladder rule, breakout rule or Claude cut ever touches
  closes, profit-takes, loss exits or rolls.
- Only `src/news/` constructs `NewsBase` rows; the API still writes exactly one table
  (`app_commands`); the API reads `news.db` only through `src/api/news_db.py` + `src/news/store/queries.py`.
- Every new config key goes into `config/examples/*.yaml` (tests run on the examples,
  `IBKR_CONFIG_USE_EXAMPLES=1`); never `git add` a private `config/*.yaml`.
- Starting values (spec, operator-approved; config-tunable):
  - CSP budget multiplier `{normal: 1.0, cautious: 0.7, stressed: 0.4, crisis: 0.1}`
  - CSP per-trade fraction of `hard_max` `{normal: 1.0, cautious: 0.6, stressed: 0.3, crisis: 0.1}`
  - New CSPs per day `{normal: null, cautious: 6, stressed: 3, crisis: 1}`
  - Guaranteed floor lots per governing index per day `{normal: 0, cautious: 2, stressed: 1, crisis: 1}` (ruling 34)
  - Leveraged-ETF per-trade fraction, tiered: calm `{2×: 0.8, 3×: 0.6}`, stressed (regime not normal or a ladder trigger) `{2×: 0.5, 3×: 0.3}`; multiplied by the regime's, ≥ 1 lot (ruling 35)
  - VIX percentile rule: ≥ 90th percentile **and** VIX ≥ 20 (ruling 39)
  - Intraday escalation: SPY −2% → stressed, −3.5% → crisis; QQQ −2.5% → stressed, −4% → crisis;
    live VIX 30 → stressed, 40 → crisis; expires at the close (ruling 40).
  - Ladder: near-the-money put = spot ≤ strike + 0.5 × ATR-14; same-day block after a loss exit;
    recovery counts only closes after the anchor (ruling 37).
  - Bottoming: VIX ≥ 15% below its spike peak; signal-lot delta ≤ 0.25 (ruling 42).
  - CC breakout: a close-to-close rise ≥ 1.5 × ATR on ≥ 1.5× average volume above resistance (or a
    60-session high), for 5 sessions unless it fades by 1 ATR; strike floor max(next resistance,
    price + 1 ATR); delta ≤ 0.25 (ruling 42).
  - Claude's cut: applied in paper, record-only in live; breaker at ≥ 4 zeroed and > 50% of the day's
    reviewed auto CSPs (ruling 36).
  - Dossiers: 6 names per call, 4 calls/day, prose on change at most every 6 hours per name, facts
    hourly, compact notes for at most 8 names (ruling 43).
- **Text-grep fences.** `tests/test_eval_skills.py::test_macro_never_reaches_the_engine` and
  `::test_news_and_tool_research_never_reach_the_deterministic_layer` grep the raw text of every file
  in `src/engine`, `src/execution` and `src/strategies`, comments and docstrings included. In those
  packages never write the strings `market_conditions`, `src.news`, `src.spreads_ai` or
  `src.claude.eval` — not even in a comment.
- **Reason-label parity.** `tests/test_reason_label_parity.py` requires every code in
  `src/notify/formatters.py::_REJECT_REASON_LABELS` to appear, with the identical phrase, in
  `src/api/routers/options.py::_REASON_LABELS`. Every new reason code (`regime_budget`,
  `regime_ceiling`, `leveraged_ceiling`, `regime_daily_limit`, `scale_in_zone_not_reached`,
  `loss_exit_cooldown`, `bottoming_delta_too_high`, `bottoming_lot_recent`,
  `cc_breakout_strike_floor`, `cc_breakout_delta`) is added to both, in the task that introduces it.
- Quality gate after every task (repo root): `python -m pytest -q && ruff check . && mypy src`;
  Task 22 also `cd web && npx vitest run && npx tsc --noEmit && npm run lint`.
- Never run `next build` inside `web/` (the operator's `next dev` shares `web/.next`).
- Daemons do not hot-reload: nothing here is live until the operator restarts `./ibkr` (trading
  service first, then the news service, then the API).

## Review Focus

1. **A production caller that forgets `sizing=`** silently drops every regime limit. → Task 3 test
   `test_every_production_caller_passes_sizing` (AST over `src/`).
2. **Stale or missing regime inputs** (yfinance down, a last close served as live): the regime must
   not read as calm and must never block a close. → Task 1 `test_stale_live_input_cannot_escalate_or_calm`,
   Task 2 `test_missing_inputs_keep_the_last_known_regime`, Task 3 `test_rolls_are_never_regime_limited`.
3. **A restart mid-day** must not relax an escalated regime. → Task 2
   `test_restart_keeps_the_intraday_escalation`.
4. **Claude's integer is malformed, above the deterministic size, negative, or from Ollama** → the
   deterministic size. → Task 14 `test_claude_cut_is_clamped_and_ignored_when_untrusted` (parametrised).
5. **The news floor** — an alert-rule story or a held-name story judged noise is never dropped; one
   index move promotes at most the capped number of dismissed stories. → Task 9
   `test_floor_never_lets_an_alert_or_held_story_fall_to_noise`, Task 11
   `test_one_index_move_promotes_at_most_the_cap`.
6. **The same contract trimmed every 15 minutes** must count once per day in the counterfactual
   record, or the report multiplies the P&L. → Task 4 `test_record_action_is_idempotent_per_day`.
7. **The page with no news.db, an old news.db without the new tables, or no regime state** answers
   `available: false` / empty sections, never a 500. → Task 21 `test_context_without_news_db`,
   `test_context_with_old_news_db`, `test_context_without_regime_state`.
8. **A full book turns a non-normal regime into a weeks-long stop** (spec decision 31). → Task 3
   `test_floor_lets_lots_through_a_full_book_in_crisis`, `test_floor_never_exceeds_the_unscaled_caps`.
9. **A dossier that re-feeds Claude's old prose or keeps an event whose date is not in its news**
   hardens opinion into fact. → Task 18 `test_previous_prose_is_never_in_the_prompt`,
   `test_event_without_the_date_in_its_cluster_is_dropped`.
10. **The breakout rule stopping covered calls for long, touching rolls, or switched off by
    `/regime off`.** → Task 16 `test_breakout_expires_after_lookback_sessions`,
    `test_breakout_ends_on_a_fade`, `test_breakout_never_touches_rolls_or_csps`,
    `test_breakout_not_switched_off_by_regime_off`.
11. **An empty delta band** — a guard at or below the strategy's `delta_min` lets nothing through. →
    Task 7 `test_bottoming_delta_guard_must_exceed_delta_min`, Task 16
    `test_breakout_delta_guard_must_exceed_delta_min` and
    `test_generator_rejects_near_strikes_and_keeps_far_ones` (a real far strike passes).
12. **The ladder missing its own must-catch lots.** → Task 7 `test_week_replay.py` (ruling 38: a hard
    gate, never loosened).
13. **Claude's cut silently zeroing the book.** → Task 14 `test_breaker_ignores_further_cuts_and_alerts_once`,
    `test_live_mode_records_but_sends_the_deterministic_size`.

---

## File structure

```
config/examples/risk_limits.yaml        MODIFY  regime: block (Task 1; ladder/bottoming keys Tasks 6-7)
config/examples/news.yaml               MODIFY  triage:, picture:, llm.reserved_for_picture (Task 8)
src/common/config.py                    MODIFY  RegimeCfg (+ sub-models), get_regime_cfg(); NewsTriageCfg, NewsPictureCfg, NewsLlmCfg.reserved_for_picture
src/common/schemas.py                   MODIFY  MarketRegime, RegimeInputs, IndexRegime, RegimeChange, RegimeState,
                                                ScaleInZone, SizingNote, SizingContext, TradeCandidate.sizing,
                                                ClaudeReview.max_contracts/size_reason/backend,
                                                MarketPicture (+ PictureFact, PictureStory, SeasonalityView, NoiseSummary)
src/common/picture_text.py              CREATE  render_picture()
src/analytics/regime.py                 CREATE  get_bars(), fetch_daily_inputs(), fetch_live_inputs(), classify_base(), intraday_escalation(), ease_one(), stricter()
src/analytics/support_levels.py         CREATE  support_levels(), broken()
src/analytics/scale_in.py               CREATE  name_drawdown_triggered(), compute_zone(), recovered()
src/analytics/bottoming.py              CREATE  market_bottoming(), name_bottoming()
src/analytics/seasonality.py            CREATE  month_seasonality()
src/analytics/technicals.py             MODIFY  rsi14_series() (and _rsi14 uses it)
src/storage/regime_state.py             CREATE  load/save state, suspend/resume, unsent changes
src/storage/models.py                   MODIFY  SizingActionRow ("sizing_actions")
src/regime/__init__.py                  CREATE
src/regime/refresh.py                   CREATE  refresh_regime(), refresh_regime_cached()
src/regime/context.py                   CREATE  build_sizing_context(), csp_opens_counted()
src/regime/anchors.py                   CREATE  latest_anchor(), recent_loss_exit()
src/regime/actions.py                   CREATE  record_action()
src/engine/capital.py                   MODIFY  scale_caps()
src/engine/regime_limits.py             CREATE  pure regime/ladder/cut functions
src/engine/risk_engine.py               MODIFY  validate_candidates(sizing=), validate_live_quote ladder re-check
src/strategies/cash_secured_put.py      MODIFY  screen_csp_candidates(sizing=)
src/orchestrator/scan_pipeline.py       MODIFY  pass sizing through SymbolDeps call
src/orchestrator/scan.py                MODIFY  refresh regime, build context, notices, book/picture to the review
src/execution/approval.py               MODIFY  fresh context at send time, trim, record
src/execution/roll_pipeline.py          MODIFY  sizing=None (explicit)
src/notify/regime_notice.py             CREATE  format/send regime changes
src/notify/approval_service.py          MODIFY  /regime command
src/notify/sender.py                    MODIFY  Claude's cut in the auto branch; record
src/notify/formatters.py                MODIFY  new reasons; "Claude suggests N of M"; regime line on the card
src/news/store/models.py                MODIFY  StoryTriageRow, MarketPictureRow, PictureStoryRow
src/news/store/queries.py               MODIFY  latest_picture(), triage_since(), active_stories()
src/news/schemas.py                     MODIFY  TriageItem, TriageOutput, PictureDraft, PictureStoryDraft
src/news/prompts.py                     MODIFY  triage_prompt(), picture_prompt()
src/news/llm.py                         MODIFY  purpose= and the reserved budget
src/news/triage.py                      CREATE  presort(), apply_floor(), run_triage()
src/news/stories.py                     CREATE  match_clusters(), story_alive()
src/news/picture.py                     CREATE  picture_facts(), build_picture(), picture_due()
src/news/noise_check.py                 CREATE  find_promotions(), beta_vs_spy()
src/news/render.py                      MODIFY  the late-post line
src/news/explain.py, followup.py        MODIFY  picture text into writer/digest prompts; edit_digest removed
src/news/service.py                     MODIFY  triage/picture/noise loops; digest uses triage
src/news/digests.py                     MODIFY  regime line from the deterministic regime
src/claude/picture_context.py           CREATE  load_picture_block()
src/claude/book_context.py              CREATE  render_book()
src/claude/prompts/strategist.py        MODIFY  picture + book + size fields; history removed
src/claude/prompts/roll.py, eod.py      MODIFY  picture block
src/claude/runner.py, ollama_runner.py  MODIFY  history removed; backend stamped; schema fields
src/claude/eval/sizing_counterfactual.py CREATE resolve_actions(), summarize()
src/spreads_ai/context.py, prompts.py   MODIFY  picture block
src/api/routers/claude_context.py       CREATE  GET /claude/context
src/api/models/claude_context.py        CREATE  response models
src/api/main.py                         MODIFY  include router
scripts/sizing_report.py                CREATE  counterfactual report
scripts/export_week_fixture.py          CREATE  week-of-Oct-13 fixture export (Task 5)
scripts/replay_week.py                  CREATE  the week replay (Task 7)
scripts/review_eval.py                  MODIFY  history= removed (Task 12)
src/api/claude_calls.py                 CREATE  the tiles' static map (Task 21)
src/api/routers/options.py              MODIFY  _REASON_LABELS (Tasks 3, 6, 7)
.opencode/agent/ibkr.md                 MODIFY  core-invariant amendment (Task 15)
web/app/more/claude/page.tsx            CREATE
web/features/claude-context/*           CREATE  page, types, tests
web/app/more/page.tsx                   MODIFY  link
tests/fixtures/week_2026_10_13/*.csv    CREATE  real bars for the replay tests
CLAUDE.md, ARCHITECTURE.md, STATUS.md, SETUP.md, README.md, docs/web/*   MODIFY (Tasks 15, 23)
```

Added by the 2026-10-21 revision (rulings 34–48):

```
config/examples/risk_limits.yaml        MODIFY  regime.csp.floor_new_per_day, thresholds.vol_pct_min_vol (Tasks 1, 3);
                                                leveraged_sizing:, claude_cut: (Tasks 3, 14); ladder.near_money_atr,
                                                ladder.loss_exit_same_day_block (Task 6)
src/common/config.py                    MODIFY  LeveragedSizingCfg/get_leveraged_sizing_cfg() (3); ClaudeCutCfg/get_claude_cut_cfg() (14);
                                                delta-guard validation (7, 16)
src/engine/regime_limits.py             MODIFY  per_trade_cap with the leveraged factor; floor_ok(); loss_exit_reason() (3, 6)
src/regime/context.py                   MODIFY  floor_lots_counted, loss_exit_today, spot_at_send (3, 6, 4)
src/storage/regime_state.py             MODIFY  update_regime_state() under a lock (2)
src/claude/eval/sizing_counterfactual.py MODIFY shadow_pnl_rules (exit-rule mark), pushed_out (15)
```

Added by Section E (Tasks 16–19; Task 20 removed 2026-10-21):

```
config/examples/risk_limits.yaml        MODIFY  cc_timing: breakout (Task 16)
config/examples/news.yaml               MODIFY  dossier:; llm.max_calls_per_day 40 -> 44 (Task 17)
src/common/config.py                    MODIFY  CcTimingCfg (+ CcBreakoutCfg), get_cc_timing_cfg() (16); NewsDossierCfg (17)
src/common/schemas.py                   MODIFY  CcBreakout, SizingContext.cc_breakout, TradeCandidate.cc_breakout (16);
                                                DossierFact, DossierEvent, TickerDossier (17)
src/common/dossier_text.py              CREATE  render_dossier(), render_dossiers() (17)
src/analytics/support_levels.py         MODIFY  resistance_levels() (16)
src/analytics/breakout.py               CREATE  breakout(), cc_floor() (16)
src/analytics/technicals.py             MODIFY  atr14_series() (and _atr14 uses it) (16)
src/regime/context.py                   MODIFY  cc_breakout (16); a context whenever regime, cc_timing or leveraged_sizing is on
src/regime/actions.py                   MODIFY  record_action(key=) (16)
src/engine/regime_limits.py             MODIFY  cc_timing_reasons() (16)
src/engine/risk_engine.py               MODIFY  CC timing reasons in pass 1 (16)
src/strategies/covered_call.py          MODIFY  screen_cc_candidates(sizing=) (16)
src/orchestrator/scan_pipeline.py       MODIFY  sizing= to deps.screen_cc (16)
src/orchestrator/scan.py                MODIFY  CC context + record (16); dossier blocks + fingerprint (19)
src/notify/formatters.py                MODIFY  breakout card line (16); two reason labels
src/api/routers/options.py              MODIFY  _REASON_LABELS (16)
src/news/store/models.py                MODIFY  TickerDossierRow (17)
src/news/store/queries.py               MODIFY  latest_dossier(), latest_dossiers() (17)
src/news/llm.py                         MODIFY  purpose "dossier" with its own cap (17)
src/news/dossier.py                     CREATE  dossier_symbols(), kind_of(), health_label(), build_facts(), verify_event_date(),
                                                refresh_facts() (17); dossier_due(), build_dossier_prose() (18)
src/news/schemas.py                     MODIFY  DossierDraft, DossierNameDraft, DossierEventDraft (18)
src/news/prompts.py                     MODIFY  dossier_prompt() (18)
src/news/service.py                     MODIFY  dossier_facts and dossier loops (18)
src/claude/dossier_context.py           CREATE  load_dossiers(), dossier_block(), prose_key() (19)
src/claude/prompts/strategist.py        MODIFY  dossier block + RULES text (19)
src/claude/prompts/roll.py              MODIFY  dossier block (19)
src/claude/runner.py, ollama_runner.py  MODIFY  dossier pass-through (19)
tests/test_cc_breakout.py, test_dossier_store.py, test_dossier_facts.py, test_dossier_text.py,
tests/test_dossier_build.py, test_dossier_readers.py   CREATE
```

---

## Section A — The regime and regime sizing (Tasks 1–4) · model: sonnet

**Entry checks (baseline; repo root, on `main`):**

- [x] **A1. Clean start.** `git status --short` shows only this plan and the spec (untracked or
  modified); `git branch --show-current` prints `main`.
- [x] **A2. Worktree.** Create it (superpowers:using-git-worktrees) on branch `feat/market-picture`;
  symlink the main `.venv` and `web/node_modules`; **copy this plan and the spec from the main
  checkout into the worktree** (they are untracked, so a new worktree does not have them); run
  `python -c "from src.storage.db import init_db; init_db()"` (else four monitor tests fail "no such
  table: fills"). Record the main checkout's absolute path as `MAIN=` in the Progress log row:
  Tasks 5 and 7 read `$MAIN/data/income_system.db`, which the worktree does not have.
- [x] **A3. Baseline green** in the worktree; record the pytest count:
  `python -m pytest -q && ruff check . && mypy src`. A red baseline is not this plan's: stop.
- [x] **A4. The code is where this plan says.** Each prints at least one line:

  ```bash
  grep -n "^def resolve_caps(account: AccountSnapshot, risk: dict) -> Caps" src/engine/capital.py
  grep -n "^def validate_candidates(" src/engine/risk_engine.py
  grep -n "^def screen_csp_candidates(" src/strategies/cash_secured_put.py
  grep -n "csp_screen = deps.screen_csp(" src/orchestrator/scan_pipeline.py
  grep -n "verdicts = validate_candidates(\[c for _, c in ordered\], account_snap, positions)" src/execution/approval.py
  grep -n "verdict = validate_candidates(\[cand\], account, positions)\[0\]" src/execution/roll_pipeline.py
  grep -n "^class Regime(StrEnum)" src/common/schemas.py
  grep -n "def entry_orders_today" src/execution/circuit_breakers.py
  grep -rn "MarketRegime\|regime_limits\|market_regime_state" src tests | head   # prints nothing
  ```

**Section exit:** four commits on `feat/market-picture`; Tasks 1–4 ticked; the regime limits apply
in the scan and at send time; no ladder yet.

---

### Task 1: Regime config, schemas and the pure classifier

**Files:**
- Modify: `config/examples/risk_limits.yaml`, `src/common/config.py`, `src/common/schemas.py`
- Create: `src/analytics/regime.py`, `tests/test_regime_classifier.py`
- Add: this plan and the spec (first commit of the branch)

**Interfaces:**
- Produces (`src/common/schemas.py`):
  - `class MarketRegime(StrEnum)`: `NORMAL="normal"`, `CAUTIOUS="cautious"`, `STRESSED="stressed"`, `CRISIS="crisis"`
  - `class RegimeInputs(BaseModel)`: `vol: float | None` (the VIX close for both indices — ruling 15),
    `vol_pct_1y: float | None` (0–100), `term_ratio: float | None` (VIX/VIX3M),
    `contango_streak: int = 0` (consecutive daily closes with term_ratio < 1, most recent first),
    `index_close: float | None`, `index_live: float | None`, `day_change_pct: float | None`,
    `sma50: float | None`, `sma200: float | None`, `drawdown_52w_pct: float | None` (positive number),
    `ret_1m_pct: float | None`, `ret_3m_pct: float | None`, `rv20: float | None`,
    `rv_1y_avg: float | None`, `live_vol: float | None`, `stale: list[str] = []`
  - `class IndexRegime(BaseModel)`: `index: Literal["SPY","QQQ"]`, `base: MarketRegime`,
    `base_date: date`, `since: date` (the ET date the **effective** regime last changed),
    `base_since: date` (the ET date the **base** last changed — the hysteresis clock, ruling 40),
    `effective: MarketRegime`, `escalated_by: list[str] = []`,
    `eased_by_bottoming: bool = False`, `bottoming_cancelled_on: date | None = None`, `inputs: RegimeInputs`
  - `class RegimeChange(BaseModel)`: `index`, `before: MarketRegime`, `after: MarketRegime`,
    `why: list[str]`, `at: datetime`, `sent: bool = False`
  - `class RegimeState(BaseModel)`: `as_of: datetime`, `spy: IndexRegime`, `qqq: IndexRegime`,
    `changes: list[RegimeChange] = []`
- Produces (`src/common/config.py`): `RegimeCfg` with sub-models `RegimeCspCfg`
  (`budget_multiplier`, `per_trade_fraction`: `dict[MarketRegime, float]`; `max_new_per_day:
  dict[MarketRegime, int | None]`), `RegimeThresholdsCfg` (fields below), `enabled: bool`,
  `tech_linked: list[str]`; `get_regime_cfg() -> RegimeCfg` (parses `get_config().risk.get("regime", {})`,
  defaults when absent).
- Produces (`src/analytics/regime.py`):
  - `ORDER: tuple[MarketRegime, ...]` (normal → crisis)
  - `stricter(a: MarketRegime, b: MarketRegime) -> MarketRegime`
  - `escalate_one(r) -> MarketRegime`, `ease_one(r) -> MarketRegime` (clamped at the ends)
  - `get_bars(symbol: str, *, today: date | None = None) -> pd.DataFrame` — daily OHLCV:
    `src.analytics.price_data.get_ohlcv` for stocks/ETFs, `get_price_provider().get_ohlcv(symbol,
    lookback_days=400)` for `^`-prefixed indices; **any row dated `today` (ET, default the current
    ET date) is dropped for every symbol** (ruling 39: the index provider includes today's forming
    bar, `yfinance_backend.py:54-56`); empty frame on failure.
  - `fetch_daily_inputs(index: Literal["SPY","QQQ"], *, bars=get_bars) -> RegimeInputs` — every
    daily field (closes, SMAs, drawdown, returns, rv, VIX close, its 1-year percentile, the term
    ratio, `contango_streak`), live fields left None. Never raises.
  - `fetch_live_inputs(index, prior_close: float | None, *, now: datetime, last_price=<provider.get_last_price>) -> dict[str, Any]`
    — returns `index_live`, `day_change_pct`, `live_vol` and a `stale` list. **Stale (pinned):** a
    live value is stale when `get_last_price` returned None, or `now` is outside RTH
    (`src.common.market_hours.is_rth`), **or it equals the prior close rounded to 4 decimals**
    (ruling 39: yfinance's `lastPrice` carries no timestamp, so an unchanged value is a last close
    served as live). `day_change_pct = (index_live / prior_close − 1) × 100`,
    computed only in RTH; outside RTH `day_change_pct` and `live_vol` are None and listed in `stale`.
  - `classify_base(inp: RegimeInputs, th: RegimeThresholdsCfg) -> tuple[MarketRegime, list[str]]`
  - `intraday_escalation(index, inp, th) -> tuple[MarketRegime, list[str]]` (NORMAL when nothing breached)

- [x] **Step 1: Branch, plan and spec** — in the worktree (A2), `git add` this plan and the spec.

- [x] **Step 2: Config** — add to `config/examples/risk_limits.yaml`:

```yaml
regime:
  enabled: true
  tech_linked: [QQQ, TQQQ, SMH, SOXL, NVDA, AMD, AVGO, AAPL, MSFT, GOOGL, AMZN, META, PLTR, MAGS,
                HACK, IGV, CRWD, NBIS, IONQ, RGTI, BABA, TSLL, MARA]
  csp:
    budget_multiplier:  {normal: 1.0, cautious: 0.7, stressed: 0.4, crisis: 0.1}
    per_trade_fraction: {normal: 1.0, cautious: 0.6, stressed: 0.3, crisis: 0.1}
    max_new_per_day:    {normal: null, cautious: 6, stressed: 3, crisis: 1}
  thresholds:
    vol_cautious: 22.0        # VIX close (both indices, ruling 15)
    vol_stressed: 28.0
    vol_crisis: 36.0
    vol_pct_cautious: 90.0    # 1-year percentile of the vol index (ruling 39; 80 fired at VIX 20.0 after a calm year)
    vol_pct_min_vol: 20.0     # ...and only when the vol close is at least this
    term_stressed: 1.00       # VIX/VIX3M at or above -> at least stressed (backwardation)
    term_crisis: 1.10
    slow_drawdown_pct: 10.0   # slow signals may add at most one notch
    slow_ret_1m_pct: -5.0
    ease_contango_days: 3     # contango closes needed before easing one notch
    min_days_in_regime: 2
    intraday:
      SPY: {stressed: -2.0, crisis: -3.5}
      QQQ: {stressed: -2.5, crisis: -4.0}
      vix_stressed: 30.0
      vix_crisis: 40.0
```

(`tech_linked` is a starting list from `universe.yaml`'s tech/semis tags plus QQQ, TQQQ, TSLL and
MARA; the operator edits it.)

- [x] **Step 3: Write the failing tests** — `tests/test_regime_classifier.py`

```python
def test_calm_market_is_normal():
    inp = RegimeInputs(vol=15.3, vol_pct_1y=30, term_ratio=0.85, index_close=778.0,
                       sma50=770.0, sma200=720.0, drawdown_52w_pct=1.0, ret_1m_pct=1.5)
    assert classify_base(inp, th())[0] == MarketRegime.NORMAL

def test_vol_level_sets_the_fast_regime():            # 23 -> cautious, 30 -> stressed, 37 -> crisis
def test_backwardation_is_at_least_stressed():        # term_ratio 1.02 with vol 20 -> STRESSED
def test_slow_signals_add_at_most_one_notch():
    # vol 15 (normal) + drawdown 12% + below sma200 -> CAUTIOUS, never STRESSED
def test_below_sma50_and_falling_is_cautious():      # synthetic: close 728.95, sma50 745,
    # sma200 690, drawdown 4.4%, ret_1m -5.5%, vol 17, term 0.90 -> CAUTIOUS (slow rule, one notch)
    # NOTE: synthetic numbers pin the rule. QQQ's REAL Oct 14 numbers (sma50 726.6, ret_1m +3.6%,
    # close above sma50) do NOT fire the slow rule; Task 7 asserts the real outcome.
def test_fetch_live_inputs_outside_rth_is_stale()      # day_change_pct None, "day_change_pct" in stale
def test_live_value_equal_to_the_prior_close_is_stale() # ruling 39
def test_get_bars_drops_todays_forming_bar()           # a frame ending today -> last row is yesterday
def test_percentile_rule_needs_the_90th_and_vix_20():  # ruling 39
    # vol 20.0 at pct 82 -> NORMAL (the 2026-10-16 close); vol 19.5 at pct 95 -> NORMAL;
    # vol 21.0 at pct 92 -> CAUTIOUS
def test_spy_week_of_oct_13_stays_normal():           # SPY close 769.6, vol 16.9, term 0.90 -> NORMAL
def test_intraday_qqq_minus_2_85_is_stressed():
    inp = RegimeInputs(day_change_pct=-2.85, live_vol=21.0)
    assert intraday_escalation("QQQ", inp, th())[0] == MarketRegime.STRESSED
def test_intraday_spy_minus_1_1_does_nothing():
def test_live_vix_40_is_crisis():
def test_stale_live_input_cannot_escalate_or_calm():
    # day_change_pct=-5 but "day_change_pct" in inp.stale -> intraday returns NORMAL with why ["stale:day_change_pct"]
    # and classify_base with vol stale uses only the non-stale signals, never returns a calmer
    # regime than the slow signals alone imply
def test_stricter_and_ease_and_escalate_clamp():
def test_regime_cfg_defaults_when_block_absent(monkeypatch):
def test_regime_cfg_rejects_a_fraction_above_one():
```

Slow-signal rule (pinned): the slow bump fires when **any** of: `drawdown_52w_pct ≥ slow_drawdown_pct`;
`index_close < sma200`; (`index_close < sma50` **and** `ret_1m_pct ≤ slow_ret_1m_pct`). For the QQQ
Oct 14 case the test uses `ret_1m_pct=-5.5` (the fixture's real 1-month return is computed in
Task 7; here the test pins the rule, not the history).

- [x] **Step 4: Run** `python -m pytest tests/test_regime_classifier.py -q` → FAIL (import errors).

- [x] **Step 5: Implement** the schemas, `RegimeCfg`/`get_regime_cfg`, and `src/analytics/regime.py`.

  `classify_base`: fast regime = the strictest of (vol thresholds; `vol_pct_1y ≥ vol_pct_cautious`
  **and** `vol ≥ vol_pct_min_vol` → cautious; `term_ratio ≥ term_stressed` → stressed, `≥ term_crisis` → crisis); then
  `escalate_one` once if the slow rule fires. A stale field is skipped (named in `why`), never
  treated as calm. The fetchers use `get_bars` (`^VIX`, `^VIX3M` for the vol inputs) and the
  provider's `get_last_price`. The module must not import `src.analytics.market_conditions`.

- [x] **Step 6: Run** the new tests → PASS; then the full gate.

- [x] **Step 7: Commit** — `feat(regime): market regime config, schemas and classifier` (+ plan, spec).

---

### Task 2: Regime state, refresh, `/regime` and change notices

**Files:**
- Create: `src/storage/regime_state.py`, `src/regime/__init__.py`, `src/regime/refresh.py`,
  `src/notify/regime_notice.py`, `tests/test_regime_state.py`, `tests/test_regime_command.py`
- Modify: `src/notify/approval_service.py` (register `/regime`), `src/orchestrator/scan.py`
  (refresh at scan start, send unsent changes)

**Interfaces:**
- Consumes: Task 1's schemas and `src/analytics/regime.py`.
- Produces:
  - `src/storage/regime_state.py`: `load_regime_state() -> RegimeState | None`,
    `save_regime_state(state: RegimeState) -> None`, `update_regime_state(fn) -> RegimeState`
    (ruling 41), `suspend_regime(day: date) -> None`,
    `resume_regime() -> None`, `regime_suspended(day: date) -> bool`,
    `unsent_changes() -> list[RegimeChange]`, `mark_changes_sent() -> None`
  - `src/regime/refresh.py`: `refresh_regime(now: datetime, *, fetch_daily=fetch_daily_inputs,
    fetch_live=fetch_live_inputs, fetch_bars=get_bars) -> RegimeState` (daily inputs fetched only when
    `base_date != today`; live inputs every call; `fetch_bars` is used by Task 7) and
    `refresh_regime_cached(now: datetime, max_age_s: float = 60.0) -> RegimeState | None`
  - `src/notify/regime_notice.py`: `format_regime_change(c: RegimeChange, cfg: RegimeCfg, *,
    working_opens: int) -> str`, `async send_regime_changes() -> int`
  - Telegram: `/regime`, `/regime off`, `/regime on`; plus `BotCommand("regime", "Market regime and
    its limits")` in the command menu list in `approval_service.py` (beside the `halt` entry)

`refresh_regime` rules (pinned):
1. Daily base (ruling 40): recomputed once per ET trading day (when `state.<idx>.base_date != today`)
   from `classify_base`. The new day starts from **yesterday's base** — never yesterday's effective
   regime, so an intraday escalation expires at the close. A stricter classification takes effect
   at once (`base_since = today`). **Easing** below yesterday's base is allowed only if
   `inputs.contango_streak ≥ ease_contango_days` **and** `(today − base_since).days ≥
   min_days_in_regime`, and then by one notch only (`base_since = today`); otherwise yesterday's
   base stands.
2. Intraday: `effective = stricter(base, intraday_escalation(...), previous effective if same day)`
   — one-way within the day, and only within the day.
3. Missing inputs: when `fetch` returns all-None for an index, keep the previous `IndexRegime`
   unchanged (log a warning); with no previous state, `NORMAL` with `escalated_by=["no_data"]`.
4. Any change of `effective` appends a `RegimeChange` (sent=False) and sets `since = today`; the base
   moving sets `base_since = today`.
5. Every write goes through `update_regime_state(fn: Callable[[RegimeState | None], RegimeState]) ->
   RegimeState`, which holds one module-level `threading.Lock` across load, `fn` and save (ruling
   41); `suspend_regime`, `resume_regime` and `mark_changes_sent` use it too.

- [x] **Step 1: Write the failing tests** — `tests/test_regime_state.py` (system_settings on the
  test DB; inject `fetch`):

```python
def test_first_refresh_writes_state_and_one_change_per_index()
def test_base_recomputed_once_per_day()               # second refresh same day does not refetch daily bars
def test_intraday_escalation_is_sticky_within_the_day()
def test_restart_keeps_the_intraday_escalation()       # save, new process (reload), calm live input -> still STRESSED
def test_next_day_base_eases_only_after_contango_streak_and_min_days()
def test_easing_is_one_notch_at_a_time()               # CRISIS -> STRESSED, never NORMAL
def test_intraday_escalation_expires_at_the_next_day():  # ruling 40
    # day 1: base NORMAL, QQQ -2.85% -> effective STRESSED; day 2: daily inputs calm, live calm
    # -> effective NORMAL (not STRESSED held by min_days_in_regime)
def test_concurrent_updates_do_not_lose_a_write():    # ruling 41: two threads, each appends a change -> both kept
def test_missing_inputs_keep_the_last_known_regime()
def test_suspension_lasts_until_the_next_trading_day()
def test_refresh_cached_reuses_within_max_age()
def test_unsent_changes_round_trip()
```

`tests/test_regime_command.py`:

```python
async def test_regime_shows_both_indices_and_limits()   # reply contains "SPY", "QQQ", "cautious", "CSP budget 70%"
async def test_regime_off_suspends_today_and_says_until_when()
async def test_regime_on_resumes()
async def test_regime_ignores_unauthorized_users()
def test_format_regime_change_text():
    # "QQQ regime -> stressed (QQQ -2.9% today): CSP budget 40%, per-trade 30%, at most 3 new CSPs today."
def test_format_regime_change_names_working_opening_orders():
    # working_opens=2 -> adds "2 opening orders already working at the broker are unchanged; cancel them in IBKR if you want them smaller."
```

`send_regime_changes` counts `working_opens` as OrderRows in states submitted/partial whose snapshot
strategy is `cash_secured_put` (spec §5: the operator is told).

- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement.** `/regime` follows `handle_halt_command`'s shape (`_is_authorized`,
  `update.message.reply_text`), registered beside `/halt`. `send_regime_changes` sends to the same
  chat and thread `send_order_notification` uses, then `mark_changes_sent()`. In `scan.py`
  `_run_scan_body`, call `refresh_regime(now)` in the executor right after `get_market_conditions`,
  store it on `ScanResult.regime` (new optional field), and `await send_regime_changes()` before
  `send_scan_results`. A failure in either is logged and never aborts the scan.
- [x] **Step 4: Run** → PASS; full gate.
- [x] **Step 5: Commit** — `feat(regime): persisted regime state, /regime, change notices`.

---

### Task 3: Regime sizing in the sizer and the gate

**Files:**
- Create: `src/engine/regime_limits.py`, `src/regime/context.py`, `tests/test_regime_limits.py`,
  `tests/test_regime_sizing_integration.py`
- Modify: `src/common/schemas.py` (`SizingContext`, `SizingNote`, `TradeCandidate.sizing`),
  `src/engine/capital.py` (`scale_caps`), `src/strategies/cash_secured_put.py`,
  `src/engine/risk_engine.py`, `src/orchestrator/scan_pipeline.py`, `src/orchestrator/scan.py`,
  `src/execution/roll_pipeline.py`, `src/notify/formatters.py` (reason texts),
  `src/api/routers/options.py` (labels), `config/examples/risk_limits.yaml` (`regime.csp.floor_new_per_day`,
  top-level `leveraged_sizing:`), `src/common/config.py` (`LeveragedSizingCfg`, `get_leveraged_sizing_cfg()`)

**Config** (rulings 34–35; `floor_new_per_day` goes under the existing `regime.csp:` block from Task 1,
`leveraged_sizing:` at the top level of `risk_limits.yaml`):

```yaml
regime:
  csp:
    floor_new_per_day: {normal: 0, cautious: 2, stressed: 1, crisis: 1}   # lots per governing index per ET day
                                                                          # past a full scaled budget (spec decision 31)
leveraged_sizing:                    # spec decision 32; not a regime limit: /regime off leaves it on
  enabled: true
  per_trade_fraction:                # of hard_max, multiplied by the regime's per-trade fraction
    calm:     {2: 0.8, 3: 0.6}       # name regime normal and no ladder trigger on the name
    stressed: {2: 0.5, 3: 0.3}       # otherwise
  leverage: {TQQQ: 3, UPRO: 3, SOXL: 3, DPST: 3, LABU: 3, TSLL: 2}   # operator-edited; TSLL to confirm
```

**Interfaces:**
- Produces (`src/common/schemas.py`):
  - `class ScaleInZone(BaseModel)` — defined here so `SizingContext` and `SizingNote` need no forward
    reference; Task 6 fills it: `anchor: float`, `anchor_source:
    Literal["order_snapshot","price_history","shares","position"]`, `zone_low: float`,
    `zone_high: float`, `support: float | None`, `min_gap_pct: float`, `triggers: list[str]`,
    `bottoming_signal: bool = False`
  - `class SizingNote(BaseModel)`: `pre_regime_contracts: int`, `regime: MarketRegime`,
    `regime_index: Literal["SPY","QQQ"]`, `per_trade_cap: int`, `budget_multiplier: float`,
    `leverage: int | None = None`, `leverage_tier: Literal["calm","stressed"] | None = None` and
    `ceiling_kind: Literal["regime_ceiling","leveraged_ceiling"] | None = None`
    (ruling 35), `floor_lot: bool = False` (ruling 34),
    `scale_in: ScaleInZone | None = None` (Task 6), `bottoming: Literal["market","name"] | None = None`
    (Task 7), `claude_suggested: int | None = None`, `claude_reason: str | None = None` (Task 14)
  - `class SizingContext(BaseModel)`: `regimes: dict[str, MarketRegime]` (keys `"SPY"`,`"QQQ"`,
    effective), `tech_linked: list[str]`, `suspended: bool = False`,
    `csp_opens_counted: dict[str, int] = {}` (per governing index),
    `floor_lots_counted: dict[str, int] = {}` (per governing index, ruling 34),
    `leverage: dict[str, int] = {}` (leveraged names → factor, ruling 35),
    `name_triggers: dict[str, list[str]] = {}` (every symbol's ladder triggers, anchor or not —
    Task 6 fills it; read by `leverage_tier`),
    `for_send: bool = False`, `scale_in: dict[str, ScaleInZone] = {}` (Task 6),
    `loss_exit_today: list[str] = []` (Task 6), `spot_at_send: dict[str, float] = {}` (Task 4),
    `name_bottoming: list[str] = []`, `market_bottoming: dict[str, bool] = {}`,
    `signal_lot_recent: list[str] = []` (Task 7)
  - `TradeCandidate.sizing: SizingNote | None = None`
- Produces (`src/engine/capital.py`): `scale_caps(caps: Caps, *, ticker: float, book: float) -> Caps`
  (`max_csp_collateral × book`; `max_ticker_risk` and `max_sector_risk` × ticker; **the collateral
  caps — `max_ticker_collateral`, `large_ticker_collateral` — and every other field unchanged**, so
  the large-position slot threshold never moves with the regime). Both the sizer and the gate call
  `seed_budgets` with the **unscaled** caps and use the scaled caps only for the checks.
- Produces (`src/engine/regime_limits.py`, pure, reads only `get_regime_cfg()`):
  - `active(ctx: SizingContext | None) -> bool` (ctx present, not suspended, `cfg.enabled`)
  - `name_regime(ctx, symbol) -> tuple[MarketRegime, Literal["SPY","QQQ"]]`
  - `multipliers(ctx, symbol) -> tuple[float, float]` → `(ticker, book)`; `(1.0, 1.0)` when inactive
  - `leverage_tier(ctx, symbol) -> Literal["calm","stressed"]` (ruling 35).
  - `per_trade_cap(ctx, symbol, hard_max: int) -> int` — ruling 35: `rf` = the regime fraction when
    `active(ctx)`, else 1.0; `base = floor(hard_max × rf)`; 0 when `base == 0`; for a name in
    `ctx.leverage` with `leveraged_sizing.enabled`, `max(1, floor(hard_max × rf × lf))` with `lf`
    from the name's tier; else `base`. `hard_max` when `ctx` is None.
  - `ceiling_kind(ctx, symbol, hard_max: int, pre: int) -> str | None` → `"leveraged_ceiling"` when
    the leveraged factor is what brings `per_trade_cap` below `min(pre, base)`, `"regime_ceiling"`
    when the regime fraction does, None when neither binds.
  - `floor_left(ctx, symbol, accepted_so_far: dict[str, int]) -> int` — ruling 34:
    `floor_new_per_day[name regime] − ctx.floor_lots_counted[index] − accepted_so_far[index]`,
    at least 0; 0 when inactive.
  - `daily_limit(ctx, symbol) -> int | None` — the limit of the name's **governing index** regime
    (ruling 16); `SizingContext.csp_opens_counted` becomes `dict[str, int]` keyed `"SPY"`/`"QQQ"`
    (opens on names governed by that index)
  - `sizing_note(ctx, symbol, pre: int, hard_max: int) -> SizingNote | None`
- Produces (`src/regime/context.py`): `build_sizing_context(*, now: datetime, session: Session,
  for_send: bool = False, symbols: list[str] | None = None, positions: list[PositionSnapshot] | None = None,
  bars: dict[str, pd.DataFrame] | None = None) -> SizingContext | None` (None only when
  `regime.enabled`, every `cc_timing` switch and `leveraged_sizing.enabled` are all off — ruling 35;
  `leverage` is filled from `universe.leveraged_etfs` and the `leveraged_sizing.leverage` map, a
  missing name defaulting to 3 with one warning); `csp_opens_counted(session, today: date, *, for_send: bool, tech_linked: list[str]) -> dict[str, int]`
  (OrderRows created today ET whose snapshot strategy is `cash_secured_put`; states
  submitted/partial/filled, plus queued when `for_send` is False; keyed by governing index of the
  snapshot's underlying) and `floor_lots_counted(...)` with the same signature, counting only rows
  whose snapshot has `sizing.floor_lot` true
- Changes signatures: `screen_csp_candidates(..., *, positions=None, sizing: SizingContext | None = None)`;
  `validate_candidates(..., *, dedupe_same_symbol=True, sizing: SizingContext | None = None)`.

- [x] **Step 1: Write the failing unit tests** — `tests/test_regime_limits.py`

```python
def test_inactive_context_changes_nothing()           # None, suspended, cfg.enabled False -> (1.0,1.0), cap = hard_max
def test_per_trade_cap_stressed_turns_10_into_3()
def test_per_trade_cap_crisis_keeps_one_lot()          # floor(10*0.1) == 1
def test_tech_linked_name_uses_the_stricter_regime()   # SPY normal, QQQ stressed: TQQQ -> stressed/QQQ, BAC -> normal/SPY
def test_book_multiplier_follows_spy_ticker_multiplier_follows_the_name()
def test_daily_limit_by_regime()                       # normal None, cautious 6, stressed 3, crisis 1
def test_scale_caps_scales_only_the_csp_budgets()
@pytest.mark.parametrize("sym,regime,triggers,expected", [      # ruling 35, hard_max 10
    ("TQQQ", "normal", [], 6),                       # calm 0.6
    ("TQQQ", "normal", ["recent_loss_exit"], 3),     # stressed 0.3 via a name trigger
    ("TQQQ", "cautious", [], 1),                     # stressed: floor(10 x 0.6 x 0.3) = 1
    ("TQQQ", "stressed", [], 1), ("TQQQ", "crisis", [], 1),
    ("TSLL", "normal", [], 8), ("TSLL", "normal", ["name_drawdown"], 5), ("TSLL", "cautious", [], 3),
    ("BAC", "normal", [], 10), ("BAC", "stressed", [], 3)])
def test_per_trade_cap_with_the_leveraged_tier(sym, regime, triggers, expected)
def test_leverage_tier_uses_the_stricter_index_for_tech_linked():   # SPY normal, QQQ cautious -> TQQQ stressed
def test_leveraged_cap_applies_when_the_regime_is_suspended_or_disabled()   # TQQQ normal, no trigger -> 6 either way;
    # with a name trigger -> 3 either way
def test_leveraged_cap_is_zero_when_the_regime_ceiling_is_zero()             # crisis fraction 0.0 in the test cfg
def test_unmapped_leveraged_etf_is_treated_as_3x()
def test_ceiling_kind_names_the_binding_factor()       # TQQQ 10 normal -> leveraged_ceiling; BAC 10 stressed -> regime_ceiling
def test_floor_left_counts_sent_and_batch_lots()       # stressed floor 1, counted {"QQQ": 1} -> 0
```

- [x] **Step 2: Write the failing integration tests** — `tests/test_regime_sizing_integration.py`

```python
def test_generator_trims_to_the_per_trade_cap_and_records_the_note():
    # hard_max 10, capital fits 10, ctx QQQ stressed -> TQQQ candidate contracts == 3,
    # c.sizing.pre_regime_contracts == 10, c.sizing.regime == STRESSED
def test_generator_says_regime_budget_when_only_the_scaled_cap_binds():
    # caps fit 2 lots unscaled, 0 after x0.4 -> reasons contain "regime_budget", not "no_headroom"
def test_gate_rejects_over_the_per_trade_cap_with_regime_ceiling()
def test_gate_says_regime_budget_when_unscaled_caps_would_pass()
def test_gate_enforces_the_daily_csp_limit_across_the_batch():
    # QQQ stressed, csp_opens_counted={"QQQ": 2}, three passing tech-linked CSP representatives
    # -> first passes, next two "regime_daily_limit"
def test_daily_limit_is_per_governing_index():
    # QQQ stressed with {"QQQ": 3, "SPY": 9}: a BAC CSP (SPY normal, no limit) passes; a TQQQ CSP is limited
def test_large_position_threshold_never_moves_with_the_regime()
def test_covered_calls_are_never_regime_limited()
def test_rolls_are_never_regime_limited()              # a 10-lot ROLL in crisis passes contracts/regime checks
def test_suspended_context_applies_no_limit()          # ...except the leveraged ceiling (ruling 35)
def test_generator_trims_a_leveraged_etf_in_a_normal_regime():
    # ctx all NORMAL, no triggers, capital fits 10 -> TQQQ contracts 6, c.sizing.leverage_tier == "calm",
    # c.sizing.ceiling_kind == "leveraged_ceiling"
def test_floor_lets_lots_through_a_full_book_in_crisis():
    # book at 101% of deployable (the 2026-10-20 shape), SPY CRISIS, two passing BAC CSPs that fit
    # every unscaled cap -> the first is accepted at 1 contract with sizing.floor_lot True, the
    # second gets "regime_budget"
def test_floor_never_exceeds_the_unscaled_caps():      # a candidate over an unscaled cap is rejected as today
def test_floor_counts_against_the_daily_limit():
def test_floor_is_per_governing_index():               # a QQQ floor lot does not use SPY's
def test_every_production_caller_passes_sizing():
    # AST over src/: every Call to validate_candidates / screen_csp_candidates /
    # deps.screen_csp has a keyword named "sizing"
```

- [x] **Step 3: Run** both files → FAIL.
- [x] **Step 4: Implement.**
  - **Sizer:** in `screen_csp_candidates`, when `active(sizing)`: compute `ticker, book =
    multipliers(sizing, symbol)`; `scaled = scale_caps(caps, ticker=ticker, book=book)`; size with
    `max_contracts(..., caps=scaled, hard_max=hard_max)`; when that gives `< 1` but the unscaled call
    gives `≥ 1`: if `floor_left(sizing, symbol, {}) > 0` (ruling 34) size with the **unscaled** caps
    and set the note's `floor_lot = True`, else append `REASON_REGIME_BUDGET = "regime_budget"`; then
    `cap = per_trade_cap(...)` (with the leveraged factor, ruling 35): if `cap == 0` append
    `"regime_ceiling"`, else `contracts = min(contracts, cap)`; set
    `candidate.sizing = sizing_note(sizing, symbol, pre=<unscaled size>, hard_max=hard_max)`, with
    `ceiling_kind` from `ceiling_kind(...)`. The generator's floor check is advisory (it lets the
    candidate reach the gate); the gate decides which candidates actually take the floor.
    **The leveraged ceiling applies whenever `sizing` is not None and `leveraged_sizing.enabled`,
    even when `active(sizing)` is false.**
  - **Gate pass 1:** for a CSP with a `sizing` context, `cand.contracts > per_trade_cap(...)` →
    `ceiling_kind(...)` (`"leveraged_ceiling"` or `"regime_ceiling"`). **Pass 2:** per
    representative, use `scale_caps(caps, ...)` for that candidate's checks; if any budget reason
    fires, re-run the same checks against the unscaled caps and, if they pass, replace those reasons
    with `"regime_budget"`; then the daily limit: `sizing.csp_opens_counted.get(index, 0) +
    accepted_csp_so_far[index] >= daily_limit` → `"regime_daily_limit"`; then, **when the only
    remaining reason is `regime_budget` and `floor_left(sizing, symbol, floor_accepted_so_far) > 0`,
    drop the reason**, accept the candidate, increment `floor_accepted_so_far[index]`, and charge
    the budgets with its (unscaled-fitted) collateral. Budgets are charged exactly as today.
  - **Callers:** `scan_symbol` (scan_pipeline.py) gains `sizing: SizingContext | None = None` and
    passes `sizing=sizing` to `deps.screen_csp`; `scan.py` builds the context once per scan
    (`build_sizing_context(now=..., session=..., symbols=would_own, positions=positions)`) after the
    regime refresh and passes it to `scan_symbol` and the full-scan gate; `run_ticker_scan` /
    `_price_and_gate_ticker` build their own context the same way for the one ticker;
    `generate_csp_candidates` (used only by tests) passes `sizing=None`; `roll_pipeline.py` passes
    `sizing=None` with the comment `# rolls are exempt from regime limits (spec §5)`.
  - **Labels** (both `formatters._REJECT_REASON_LABELS` and `api/routers/options._REASON_LABELS`,
    identical): `regime_budget`: "the market regime has shrunk the CSP budget"; `regime_ceiling`:
    "over the market regime's size limit"; `leveraged_ceiling`: "over the size limit for a leveraged
    ETF"; `regime_daily_limit`: "the market regime's new-CSP limit for today is used up".
  - **Card line** (formatter, CSPs with `sizing`): "Size 6 of 10 (leveraged ETF, 3×, calm)", "Size 3
    of 10 (leveraged ETF, 3×, stressed: loss exit on TQQQ)" or "Size 1 of 10 (QQQ crisis; today's
    guaranteed lot)" — the binding reason in words.
- [x] **Step 5: Run** → PASS; full gate (existing risk-engine and CSP tests must pass unchanged —
  they call without `sizing`).
- [x] **Step 6: Commit** — `feat(regime): regime budgets with a guaranteed floor, per-trade and leveraged-ETF limits, daily limit`.

---

### Task 4: Send-time re-check, trim, and the counterfactual table

**Files:**
- Modify: `src/storage/models.py` (`SizingActionRow`), `src/execution/approval.py`,
  `src/engine/regime_limits.py` (`trim_for_send`), `src/orchestrator/scan.py` (record
  decision-time trims), `src/notify/formatters.py`
- Create: `src/regime/actions.py`, `tests/test_regime_send_time.py`

**Interfaces:**
- Produces: `SizingActionRow` (`__tablename__ = "sizing_actions"`): `id`, `created_at`,
  `candidate_id` (index), `underlying`, `strategy`, `right`, `strike`, `expiry`, `premium`,
  `kind` (String(24): `regime_budget|regime_ceiling|leveraged_ceiling|regime_daily_limit|regime_floor_lot|escalation_trim|scale_in_zone|loss_exit_cooldown|bottoming_lot|claude_cut|claude_cut_unapplied|cc_breakout_floor`),
  `regime`, `picture_version` (nullable), `deterministic_contracts`, `sent_contracts`, `reason`
  (Text), `action_day` (Date, ET), `order_id` (nullable — set once an order exists),
  `realized_pnl_per_contract` (Float, nullable), `shadow_pnl_expiry` and `shadow_pnl_rules`
  (Float, nullable — ruling 44), `entry_iv` (Float, nullable — the snapshot's `current_iv`, for
  the exit-rule mark), `resolved_at` (nullable), `record_key` (String(64)) — the key it was
  upserted on; `UniqueConstraint("record_key", "kind", "action_day")`. New table: `create_all`
  builds it.
- Produces: `src/regime/actions.py::record_action(*, cand: TradeCandidate, kind: str,
  deterministic: int, sent: int, reason: str, picture_version: str | None = None,
  order_id: int | None = None, key: str | None = None, session: Session | None = None) -> None` —
  an **upsert** on (`key or cand.candidate_id`, kind, ET day): the first row is kept,
  `sent_contracts` / `order_id` / `reason` are updated (ruling 20); `entry_iv` is taken from
  `cand.current_iv` on the first write. **Never-sent CSP rows pass
  `key=f"csp:{underlying}:{kind}:{et_day}"`** (ruling 44), so one blocked name is one row a day
  however many strikes, expiries or scan cycles were rejected; trims of a sent candidate keep the
  candidate id. Never raises.
- Produces: `src/engine/regime_limits.py::trim_for_send(cand: TradeCandidate, ctx: SizingContext | None,
  hard_max: int, budget_fit: int | None) -> int` → for CSPs
  `min(cand.contracts, per_trade_cap(ctx, cand.underlying, hard_max), budget_fit if not None)`,
  else `cand.contracts` (ruling 19; `per_trade_cap` carries the leveraged factor, ruling 35). The
  send-time context computes no bars, so `_send_context` sets `name_triggers[symbol] =
  ["snapshot_stressed"]` for every pending candidate whose snapshot has `sizing.leverage_tier ==
  "stressed"`, and adds `"recent_loss_exit"` for names in `loss_exit_today`; the send-time regime
  does the rest. The tier can tighten between card and send, never loosen.
  `budget_fit` is `capital.max_contracts(...)` run with the scaled caps and budgets seeded
  (unscaled) from `positions` — **except for a candidate whose snapshot has `sizing.floor_lot`**:
  it is re-checked against the unscaled caps and kept while `floor_left(ctx, symbol, sent_floor)`
  allows it (the send-time context counts only sent floor lots), else it gets `regime_budget`.
- Produces: `_send_context` also fills `ctx.spot_at_send` for each pending CSP's underlying whose
  snapshot has `sizing.scale_in`, via the price provider's `get_last_price`, outside the write
  session (ruling 48), and `ctx.loss_exit_today` (Task 6).

- [x] **Step 1: Failing tests** — `tests/test_regime_send_time.py`

```python
def test_escalation_after_approval_trims_down_and_notes_it():
    # queued 10-lot TQQQ CSP; fresh context QQQ stressed -> order contracts 3, detail says
    # "trimmed 10 -> 3 by the market regime (QQQ stressed)", a SizingActionRow kind "escalation_trim"
def test_escalation_to_a_zero_limit_rejects_with_the_regime_reason():
    # per_trade_fraction crisis set to 0.0 in the test cfg -> CANCELLED, detail contains "regime_ceiling"
def test_trim_never_raises_a_size()
def test_a_budget_that_shrank_since_the_card_trims_to_the_fitted_size()
def test_send_time_daily_limit_counts_only_sent_orders()
def test_scan_records_a_decision_time_trim()           # a trimmed candidate writes kind "regime_ceiling", deterministic 10, sent 3
def test_record_action_is_idempotent_per_day():
    # the same candidate trimmed on 4 scan cycles in one day -> one row; a new day -> a second row
def test_never_sent_csp_rows_are_one_per_name_kind_and_day():   # ruling 44
    # 3 cycles x 4 TQQQ strikes rejected regime_budget -> one row keyed "csp:TQQQ:regime_budget:<day>"
def test_leveraged_trim_at_send_time_is_recorded_as_leveraged_ceiling()
    # a calm 6-lot TQQQ card; QQQ escalates to stressed before send -> trimmed to 1
def test_leveraged_tier_never_loosens_at_send_time()   # a stressed 3-lot card stays 3 even if calm at send
def test_a_floor_lot_survives_send_time_while_the_floor_allows()
def test_a_second_floor_lot_at_send_time_is_rejected_regime_budget()
def test_record_action_never_raises_on_a_db_error()
def test_send_context_is_built_outside_the_write_session()
    # monkeypatch session_scope to fail if the context helper runs inside it
```

- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement.** In `process_queued_orders`, **after `positions = get_positions(ib)` and
  before `with session_scope() as session:`** (the function deliberately fetches slow data before
  taking the SQLite write lock), run `ctx = await asyncio.to_thread(_send_context, now, positions)`;
  `_send_context` calls `refresh_regime_cached(now)` and `build_sizing_context(..., for_send=True)`
  in its own read session. **`for_send=True` computes no `scale_in` zones and fetches no bars** — the
  ladder is re-checked only from the snapshot zone in `validate_live_quote` (ruling 8). Inside the
  session, for each pending CSP compute `n = trim_for_send(...)`; when
  `0 < n < candidate.contracts`, `candidate = candidate.model_copy(update={"contracts": n,
  "collateral": candidate.strike * n * 100})`, write the trimmed snapshot back to the `OrderRow`,
  set `order_row.detail`, and `record_action(kind="escalation_trim", ...)`; then call
  `validate_candidates(..., sizing=ctx)`. In `scan.py`, after the gate, record one action per passing
  candidate whose `sizing.pre_regime_contracts > contracts` (kind = `sizing.ceiling_kind`, i.e.
  `regime_ceiling` or `leveraged_ceiling`), one per floor lot (kind `regime_floor_lot`, sent =
  its size, deterministic = its size — the counterfactual is "what the floor lot earned"), and per
  name rejected only for a regime reason (kind = that reason, sent 0, the name's highest-ranked
  candidate as the representative, `key=` as above). When an order is later queued for a
  recorded candidate, `_auto_queue_candidates` / the approval path set `order_id` on the day's rows
  (an upsert through `record_action`).
- [x] **Step 4: Run** → PASS; full gate.
- [x] **Step 5: Commit** — `feat(regime): send-time regime re-check, trim, counterfactual table`.

---

## Section B — The ladder and the bottoming signal (Tasks 5–7) · model: sonnet

**Entry checks:**

- [x] **B1.** Section A's four commits are on `feat/market-picture`; Progress log rows 1–4 done.
- [x] **B2.** Gate green; pytest count ≥ the A3 baseline + Section A's new tests.
- [x] **B3.** `grep -n "def build_sizing_context" src/regime/context.py`,
  `grep -n "^class ScaleInZone" src/common/schemas.py` and
  `grep -n "scale_in: dict\[str, ScaleInZone\]" src/common/schemas.py` each print one line.
- [x] **B4. Fixture source exists:**
  `sqlite3 data/income_system.db "select count(*) from price_history where symbol in ('SPY','QQQ','TQQQ','SOXL') and obs_date between '2025-09-01' and '2026-10-19'"`
  prints a number > 1000 (run against the main checkout's `data/`).

**Section exit:** three commits; the ladder and the bottoming signal are enforced; the replay result
is in the Progress log.

---

### Task 5: Support detector

**Files:**
- Create: `src/analytics/support_levels.py`, `tests/test_support_levels.py`,
  `tests/fixtures/week_2026_10_13/{SPY,QQQ,TQQQ,SOXL,VIX,VIX3M}.csv`,
  `scripts/export_week_fixture.py`
- Modify: `src/analytics/technicals.py` (`rsi14_series`)

**Interfaces:**
- Produces: `support_levels(bars: pd.DataFrame, *, spot: float, windows: tuple[int, ...] = (3, 5, 10),
  merge_atr: float = 0.5, atr: float | None = None, max_levels: int = 5) -> list[float]` — levels
  strictly below `spot`, nearest first, broken levels excluded.
- Produces: `broken(level: float, closes_after: pd.Series, atr: float, broken_atr: float) -> bool`.
- Produces: `rsi14_series(close: pd.Series) -> pd.Series` in `technicals.py`; `_rsi14` returns its
  last value (no behaviour change; existing technicals tests pass unmodified).

Algorithm (pinned): for each window `w`, a bar `i` (with `w ≤ i ≤ len−1−w`) is a swing low when
`Low[i] == min(Low[i−w : i+w+1])`. Collect all, merge levels closer than `merge_atr × atr` (keep the
lower), drop any level with a later daily close `< level − broken_atr × atr` (`broken_atr` from
`ladder.broken_atr`, default 1.0), keep those `< spot`, sort descending, cap at `max_levels`.

- [x] **Step 1: Export the fixture.** `scripts/export_week_fixture.py --db PATH --out DIR` writes
  `Date,Open,High,Low,Close,Volume` CSVs from the `price_history` table of `--db` (SPY, QQQ, TQQQ,
  SOXL, 2025-09-01..2026-10-19) and from `get_price_provider().get_ohlcv` for `^VIX` and `^VIX3M`
  (same range). Run it with `--db $MAIN/data/income_system.db --out tests/fixtures/week_2026_10_13`
  (A2's `MAIN`); commit the CSVs (small). Tests load them with a `week_bars(symbol)` helper in
  `tests/conftest.py`; no test reads `data/`.
- [x] **Step 2: Failing tests** — `tests/test_support_levels.py`

```python
def test_swing_low_found_and_below_spot()
def test_levels_are_nearest_first_and_capped()
def test_close_levels_merge_to_the_lower()
def test_broken_level_is_dropped()
def test_no_history_gives_no_levels()
def test_tqqq_levels_on_oct_13_are_all_below_spot():   # from the fixture, spot 78.81
def test_rsi14_series_last_value_matches_rsi14()
```

- [x] **Step 3: Run** → FAIL. **Step 4: Implement.** **Step 5: Run** → PASS; full gate.
- [x] **Step 6: Commit** — `feat(analytics): support detector on daily lows; week-of-Oct-13 fixture`.

---

### Task 6: Scale-in ladder — anchors, name triggers, zones, the gate

**Files:**
- Create: `src/analytics/scale_in.py`, `src/regime/anchors.py`, `tests/test_scale_in.py`,
  `tests/test_scale_in_gate.py`
- Modify: `config/examples/risk_limits.yaml` (`regime.ladder`), `src/common/config.py`
  (`RegimeLadderCfg`), `src/regime/context.py`,
  `src/engine/regime_limits.py`, `src/engine/risk_engine.py` (pass 1 + `validate_live_quote`),
  the `validate_live_quote` callers on the send path (`grep -rn "validate_live_quote(" src` — pass
  `sizing=ctx`), `src/strategies/cash_secured_put.py`, `src/notify/formatters.py`,
  `src/api/routers/options.py` (labels)

**Config** (append under `regime:`):

```yaml
  ladder:
    regimes: [stressed, crisis]          # market regimes where the ladder applies to every held name
    min_gap_pct: {normal: 5.0, cautious: 5.0, stressed: 5.0, crisis: 7.0}
    min_gap_atr: 1.5
    band_atr: 0.5
    broken_atr: 1.0
    anchor_survival_days: 5
    name_drawdown_atr: 2.5               # drawdown from the 10-session high, in ATRs
    name_drawdown_sessions: 10
    recovery_closes: 2                   # counted only after the anchor lot's fill date (ruling 37)
    near_money_atr: 0.5                  # a short put with spot <= strike + this x ATR fires the ladder
    loss_exit_same_day_block: true       # no new CSP on a name for the rest of the ET day of its loss exit
```

**Interfaces:**
- Consumes: `ScaleInZone` (Task 3); its `triggers` values are
  `regime_stressed|regime_crisis|name_drawdown|near_money_put|recent_loss_exit` (`near_money_put`
  replaces the first draft's `itm_put` — ruling 37).
- Produces (`src/analytics/scale_in.py`, pure):
  - `name_drawdown_triggered(bars: pd.DataFrame, atr: float, *, sessions: int, k_atr: float) -> bool`
    → `1 − last_close / max(High[-sessions:]) ≥ k_atr × atr / last_close`
  - `near_money_short_put(positions: list[PositionSnapshot], symbol: str, spot: float, atr: float,
    *, k_atr: float) -> bool` → any short put on `symbol` with `spot ≤ strike + k_atr × atr`
    (TQQQ 75P on 2026-10-13: the 78P was out of the money by $0.12 — a strict ITM test missed it)
  - `compute_zone(*, anchor: float, anchor_source: str, atr: float, supports: list[float],
    regime: MarketRegime, triggers: list[str], cfg: RegimeLadderCfg) -> ScaleInZone`:
    `gap = max(cfg.min_gap_pct[regime] / 100, cfg.min_gap_atr × atr / anchor)`;
    `ceiling = anchor × (1 − gap)`; `support` = first level `≤ ceiling` (else None);
    zone = `support ± band_atr × atr` capped at `ceiling` on top; with no support, zone =
    `[ceiling − band_atr × atr, ceiling]`.
  - `recovered(bars: pd.DataFrame, *, sma20: float | None, level: float, closes: int, after: date) -> bool`
    → among the daily closes **dated after `after`** (the anchor lot's fill date, ET — ruling 37),
    there are at least `closes`, and the last `closes` of them are all above both `sma20` and
    `level`, where `level` is **the most recently broken support, else the anchor**. (Without
    `after`, the closes from before the anchor lifted the ladder on 2026-10-13 and 10-14 for TQQQ
    70P and 68P.)
  - **Supports for the zone are detected relative to the anchor, not the spot:**
    `supports = support_levels(bars, spot=anchor, atr=atr, ...)`. (Detected relative to spot, a
    support between spot and the gap ceiling would be dropped and a price already past the target
    would be blocked.)
- Produces (`src/regime/anchors.py`): `latest_anchor(session, symbol, positions, *, survival_days: int,
  today: date) -> tuple[float, str, date] | None` (ruling 9; the third item is the anchor lot's fill
  date, ET, for `recovered(after=)`), `recent_loss_exit(session, symbol, *, days: int, today: date)
  -> bool` and `loss_exits_today(session, *, today: date) -> list[str]` (underlyings with a
  `loss_exit` BUY fill dated today ET — ruling 37). **How a loss exit is found (pinned):** close orders
  (`execution/position_manager.py`) carry **no snapshot**, and `OrderRow` has no `underlying` column.
  A loss-exit `FillRow` (`action == "BUY"`, `close_reason == "loss_exit"`) is matched by joining its
  `candidate_id` to the **opening** `OrderRow` with the same `candidate_id` and a non-null
  `snapshot`, and reading `snapshot["underlying"]`; when no opening row exists, fall back to parsing
  a `close:<SYM>:…` candidate id. Test fixtures build the real shape: an opening order with a
  snapshot, a close order without one.
- **Where bars come from:** `build_sizing_context(..., bars=None)` defaults to
  `src.analytics.regime.get_bars(symbol)` (daily-cached); ATR from `technicals._atr14(high, low, close)`.
- Produces (`src/engine/regime_limits.py`): `scale_in_reason(ctx: SizingContext | None, symbol: str,
  spot: float | None) -> str | None` → `"scale_in_zone_not_reached"` when the name has a zone and
  `spot > zone_high`; None otherwise (also None when inactive or no zone); and
  `loss_exit_reason(ctx, symbol) -> str | None` → `"loss_exit_cooldown"` when
  `ladder.loss_exit_same_day_block` and `symbol in ctx.loss_exit_today` (checked before the zone;
  applies whenever the context is present, like the ladder's name triggers).
- `build_sizing_context` now fills `scale_in` for each symbol in `symbols` where **any** trigger
  holds: the name's regime is in `ladder.regimes`; `name_drawdown_triggered`;
  `near_money_short_put`; `recent_loss_exit`. A name with a trigger but no anchor gets no zone
  (first lot is free). A name whose `recovered(..., after=<anchor fill date>)` is true drops the
  zone **whatever its triggers** (ruling 18, spec §6) until a trigger fires again on a later day.
  It fills `loss_exit_today` from `loss_exits_today(...)` for both `for_send` values, and
  `name_triggers[symbol]` with the triggers that hold for **every** symbol in `symbols`, whether or
  not it has an anchor (the leveraged tier reads it — ruling 35; a first lot on a falling 3× ETF is
  sized at the stressed tier even though the ladder lets it through).

- [x] **Step 1: Failing tests** — `tests/test_scale_in.py`

```python
def test_zone_sits_at_the_next_support_below_the_min_gap()
def test_zone_found_when_spot_already_below_the_support():
    # anchor 100, gap ceiling 95, support 94, spot 93.5 -> zone around 94 (allowed), not the next level down
def test_zone_falls_back_to_the_gap_without_support()
def test_atr_gap_wins_for_a_volatile_name()            # SOXL-like atr 12 on anchor 145 -> gap 12.4% > 5%
def test_name_drawdown_soxl_triggers_by_oct_13()       # fixture
def test_name_drawdown_tqqq_triggers_by_oct_14_not_oct_13()   # fixture; Oct 13 alone is covered by near_money_put
def test_near_money_short_put_triggers_just_out_of_the_money():
    # 78P held, spot 78.12, ATR 3.4 -> True (78.12 <= 78 + 1.7); spot 80.0 -> False
def test_recovery_ignores_closes_before_the_anchor():
    # TQQQ fixture: anchor 78.12 filled 2026-10-13; closes 10-09 81.28 and 10-12 79.61 are above
    # sma20 and the anchor -> recovered(..., after=date(2026, 10, 13)) is False
def test_loss_exit_blocks_the_name_for_the_rest_of_the_day():
    # SOXL loss exit at 13:34 UTC -> a SOXL CSP at 13:52 gets "loss_exit_cooldown"; next day it does not
def test_name_triggers_filled_even_without_an_anchor()     # SOXL drawdown, no lot held -> ["name_drawdown"]; tier stressed
def test_recent_loss_exit_triggers_within_survival_days_only()
    # opening OrderRow with snapshot (underlying SOXL) + close OrderRow with NO snapshot + BUY FillRow loss_exit
def test_recent_loss_exit_falls_back_to_the_close_candidate_id()
def test_anchor_prefers_the_order_snapshot_spot()
def test_anchor_survives_a_loss_exit_for_survival_days()
def test_assigned_shares_are_a_lot()
def test_roll_fills_never_move_the_anchor()
def test_recovery_lifts_a_name_trigger()
```

`tests/test_scale_in_gate.py`:

```python
def test_gate_blocks_a_lot_above_the_zone()            # reason "scale_in_zone_not_reached"
def test_gate_allows_a_lot_inside_the_zone()
def test_near_money_put_fires_the_ladder_not_a_block():   # operator decisions 21 and 35
    # a near-the-money 78P is held; a candidate whose spot is inside the next zone passes
def test_live_regate_blocks_when_the_underlying_bounced_above_the_zone()
    # validate_live_quote with quote.underlying_price > snapshot zone_high -> REJECT
def test_live_regate_uses_spot_at_send_without_an_underlying_price()   # ruling 48
def test_live_regate_rejects_after_a_loss_exit_since_the_card()        # ctx.loss_exit_today -> "loss_exit_cooldown"
def test_ladder_never_applies_to_rolls_or_ccs()
```

- [x] **Step 2: Run** → FAIL.
- [x] **Step 3: Implement.** Labels in both label maps: `scale_in_zone_not_reached` ("the price
  has not reached the next lower entry zone"), `loss_exit_cooldown` ("a loss exit on this name
  earlier today"). Sizer: append `loss_exit_reason(...)` when not None; when
  `scale_in_reason(sizing, symbol, tech_stats.price)` is not None, append it; copy the zone into
  `candidate.sizing.scale_in`. Gate pass 1: the same two checks with `cand.ideal.spot` for the zone
  (skip the zone check when `ideal` is None). `validate_live_quote` gains `sizing:
  SizingContext | None = None` (the send path passes the send-time context): `loss_exit_reason`;
  then, when `candidate.sizing and candidate.sizing.scale_in`, `spot = quote.underlying_price` or
  `sizing.spot_at_send.get(symbol)` (ruling 48); `spot > zone_high` → the reason; no spot → skip
  and note it in the order `detail`. Card line (formatter): "Next lot zone $47.10–$49.20 (support
  $48.15, 5.0% below the last lot)".
- [x] **Step 4: Run** → PASS; full gate.
- [x] **Step 5: Commit** — `feat(regime): scale-in ladder with name-level triggers and a same-day loss-exit block`.

---

### Task 7: Bottoming signal and the week-of-Oct-13 replay

**Files:**
- Create: `src/analytics/bottoming.py`, `tests/test_bottoming.py`, `tests/test_week_replay.py`,
  `scripts/replay_week.py`
- Modify: `config/examples/risk_limits.yaml` (`regime.bottoming`), `src/common/config.py`
  (`RegimeBottomingCfg`), `src/regime/refresh.py`, `src/regime/context.py`,
  `src/engine/regime_limits.py`, `src/engine/risk_engine.py`, `src/strategies/cash_secured_put.py`

**Config:**

```yaml
  bottoming:
    vix_spike_pct: 25.0          # VIX rose at least this much from its window low to its peak
    spike_sessions: 10
    off_peak_pct: 15.0           # live VIX at least this far below the spike peak
    rsi_oversold: 30.0
    rsi_lookback: 5
    signal_delta_max: 0.25       # must exceed cash_secured_put.delta_min (0.20), checked at load (ruling 42)
    signal_lot_every_sessions: 3
```

**Interfaces:**
- Produces (`src/analytics/bottoming.py`, pure):
  - `market_bottoming(*, vix: pd.DataFrame, vix3m: pd.DataFrame, index: pd.DataFrame,
    live_vix: float | None, live_index: float | None, cfg: RegimeBottomingCfg) -> tuple[bool, list[str]]`
    — all of: a spike in the last `spike_sessions` (peak close ≥ window-low close × (1 + vix_spike_pct/100));
    `live_vix ≤ peak × (1 − off_peak_pct/100)`; if any day in the window had VIX/VIX3M ≥ 1, today's
    live ratio < 1; `live_index > min(Low)` of the window's lowest-close day.
  - `name_bottoming(*, bars: pd.DataFrame, zone: ScaleInZone, supports: list[float], spot: float,
    atr: float, band_atr: float, cfg: RegimeBottomingCfg) -> tuple[bool, list[str]]` — all of:
    **spot is within `band_atr × atr` of a support (from `support_levels(bars, spot=zone.anchor, ...)`)
    that lies above `zone_high`** — i.e. a level the ladder would otherwise make it wait past; RSI-14
    (via `rsi14_series`) was `< rsi_oversold` within `rsi_lookback` sessions and today's RSI >
    yesterday's; the last close > the prior day's high.
- `refresh_regime`: when `market_bottoming` holds for an index whose effective regime is STRESSED or
  CRISIS, and no escalation threshold is breached now, set `effective = ease_one(effective)`,
  `eased_by_bottoming = True`, append a `RegimeChange` with `why=["bottoming: ..."]`. A later
  escalation breach the same day sets `bottoming_cancelled_on = today` and restores the escalated
  regime.
- `build_sizing_context`: `name_bottoming` list; `signal_lot_recent` = names with a
  `SizingActionRow(kind="bottoming_lot")` within `signal_lot_every_sessions` sessions.
- `regime_limits.scale_in_reason` returns None for a name in `ctx.name_bottoming` (the lot is
  allowed at that support without waiting for the next zone down), but
  `bottoming_reason(ctx, cand) -> str | None` then applies the guards: `abs(cand.delta) >
  signal_delta_max` → `"bottoming_delta_too_high"`; name in `signal_lot_recent` →
  `"bottoming_lot_recent"`. A lot that passes on a signal sets `sizing.bottoming` and is recorded
  `kind="bottoming_lot"`. **When the scaled budget is full, a signal lot uses the guaranteed floor
  (ruling 34) like any other CSP** — the signal changes where the lot may open, never the budget.
- `get_regime_cfg()` raises `ValueError` when `bottoming.signal_delta_max ≤
  risk_limits.cash_secured_put.delta_min` (ruling 42: at 0.20 against `delta_min` 0.20 only an exact
  0.200 delta could ever pass).
- **The market-level ease and the floor:** with the book full, an ease from `stressed` to `cautious`
  changes the floor from 1 to 2 lots a day and the per-trade ceiling from 3 to 6; the replay
  (Step 5) prints both so the operator sees what an ease actually unlocks.

- [x] **Step 1: Failing tests** — `tests/test_bottoming.py`

```python
def test_market_signal_needs_a_spike_and_a_retreat_and_a_higher_low()
def test_market_signal_off_without_a_spike()
def test_inverted_curve_must_normalise()
def test_name_signal_needs_support_rsi_turn_and_close_above_prior_high()
def test_refresh_eases_one_notch_on_the_market_signal()
def test_escalation_cancels_the_easing_for_the_day()
def test_name_signal_off_when_the_support_is_inside_the_zone_already()
def test_signal_lot_guards():                          # delta 0.30 -> bottoming_delta_too_high; 0.23 passes; recent lot -> bottoming_lot_recent
    # both codes added to both label maps
def test_signal_lot_is_recorded_and_tagged()
def test_bottoming_delta_guard_must_exceed_delta_min()  # signal_delta_max 0.20 with delta_min 0.20 -> ValueError
def test_signal_lot_uses_the_floor_when_the_book_is_full()
```

`tests/test_week_replay.py` (fixture; the must-catch case, spec §14). Lot spots are written inline in
the test (no `data/` access). These are the order snapshots' `ideal.spot` values, read from
`data/income_system.db` on 2026-10-20: SOXL 130P opened 2026-10-08 at spot 140.19, stopped 10-13
13:34 UTC; SOXL 100P opened 10-13 at 122.93; TQQQ 78P opened 10-07 at 81.79, stopped 10-14; TQQQ 75P
opened 10-13 at 78.12, stopped 10-14 16:18 UTC; TQQQ 70P opened 10-13 at 78.41; TQQQ 68P opened 10-14
at 74.72, stopped 10-16.

```python
def test_spy_regime_normal_oct_13_to_15()
def test_qqq_base_regime_on_oct_14_is_what_the_rules_say():
    # with VIX for both (ruling 15): NORMAL — VIX 16.9, term < 1, slow rule does not fire
    # (sma50 726.6 < close 728.95, ret_1m +3.6%).
def test_qqq_escalates_to_stressed_intraday_oct_16():
    # day change at the low = Low / prior close - 1 = 707.23 / 728.00 - 1 = -2.85% -> STRESSED
def test_soxl_and_tqqq_get_a_zone_after_their_loss_exits():
    # zone_high below the previous anchor by >= the min gap
def test_each_later_lot_needs_a_lower_price_than_the_last():
# THE HARD GATE (ruling 38; spec decision 35). Replay the week's actual CSP entries in time order
# through loss_exit_reason, the triggers, compute_zone and scale_in_reason, with the anchor and
# loss-exit state built only from lots the replay itself let through. Each must be blocked:
def test_replay_blocks_soxl_100p_on_oct_13():          # loss_exit_cooldown (SOXL 130P stopped 13:34 UTC)
def test_replay_blocks_tqqq_75p_on_oct_13():           # near_money_put on the 78P; spot 78.12 > zone_high
def test_replay_blocks_tqqq_70p_on_oct_13():           # same trigger; recovery ignores pre-anchor closes
def test_replay_blocks_tqqq_68p_on_oct_14():           # loss_exit_cooldown (the 78P stop the same day)
# If any of the four is not blocked by the rules as written: STOP, report which and why — never
# loosen or delete these tests to get green.
```

- [x] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; full gate.
- [x] **Step 5: Replay.** `scripts/replay_week.py --db $MAIN/data/income_system.db` replays the
  actual CSP entries of 2026-10-13..19 (from `orders`/`fills`, opened read-only) through `classify_base`,
  `intraday_escalation`, the loss-exit block, the ladder and `per_trade_cap` (with the leveraged
  factor), and prints per entry: regime, triggers, zone, allowed or blocked and why, size
  before/after, and the leg's realised (or marked) P&L before and after. Also print, for the same
  week, how many CSPs the VRP gate (`premium_below_fair_value`) rejected on SOXL/TQQQ (spec §6b known
  interaction). Compare with spec §19's replay (41 opens Sep 30–Oct 20 → 10 blocked, 4 trimmed;
  contracts 178 → 129; CSP P&L −$5,253 → −$1,298); a large difference is a finding to report, not to
  tune away. Paste the
  summary (not the full output) into this task's Progress-log Rulings cell.
- [x] **Step 6: Commit** — `feat(regime): bottoming signal; week-of-Oct-13 replay`.

---

## Section C — The news expert (Tasks 8–11) · model: sonnet

**Entry checks:**

- [x] **C1.** Sections A–B committed (seven commits); Progress log rows 1–7 done; gate green.
- [x] **C2.** `grep -n "def edit_digest\|def digest_reads" src/news/explain.py` prints two lines;
  `grep -n "editor = await asyncio.to_thread(edit_digest" src/news/service.py` prints one.
- [x] **C3.** `grep -n "def call_llm(prompt: str, \*, schema: dict, prefix: str, now: datetime)" src/news/llm.py` prints one line.
- [x] **C4.** `python -m pytest tests/test_news_fence.py -q` passes.

**Section exit:** four commits; the news service triages, keeps stories, writes a picture and runs
the noise check; the digest uses triage and shows the deterministic regime.

---

### Task 8: News tables, config and the reserved LLM budget

**Files:**
- Modify: `src/news/store/models.py`, `src/news/store/queries.py`, `src/common/config.py`,
  `config/examples/news.yaml`, `src/news/llm.py`, `src/common/schemas.py` (`MarketPicture` family)
- Create: `src/common/picture_text.py`, `tests/test_news_picture_store.py`, `tests/test_picture_text.py`
  (moved here from Task 12 because Task 9 already renders the picture)

**Config** (`config/examples/news.yaml`):

```yaml
llm: {backend: cli_then_ollama, model: "claude-sonnet-5-5", ollama_model: "", timeout_seconds: 120,
      max_calls_per_day: 40, reserved_for_picture: 10}
triage:
  enabled: true
  batch_size: 40
  rth_batch_times: ["10:30", "12:30", "14:30"]   # ET, plus one inside each digest
  promote_index_move_pct: 1.0
  promote_ticker_residual_pct: 3.0               # ticker move net of beta x index move
  promote_window_min: 60
  max_promotions_per_hour: 2
picture:
  enabled: true
  max_rebuilds_per_day: 4
  max_stories: 5
  story_window_days: 7
  story_min_new_clusters: 2
  story_match_jaccard: 0.3
  staleness_hours: 26
```

**Interfaces:**
- Produces (`src/news/store/models.py`): `StoryTriageRow` (`story_triage`: `id`, `cluster_id`
  unique, `pile` Integer nullable (None = not reviewed), `floor` String(8) nullable
  (`alert|held`), `rank` Float (the presort rank), `reason` String(160), `judged_at`,
  `promoted_at`, `promoted_move_pct`, `story_id` nullable), `MarketPictureRow` (`market_pictures`: `id`, `built_at`, `version` unique,
  `payload` JSON, `stale` bool), `PictureStoryRow` (`picture_stories`: `id`, `title`,
  `started_on` date, `last_supported_at`, `cluster_ids` JSON, `active` bool, `ended_on`).
- Produces (`src/common/schemas.py`): `PictureFact(label: str, value: str)`,
  `SeasonalityView(month: int, avg_return_pct: float, up_share: float, years: int)`,
  `PictureStory(id: int, title: str, started_on: date, description: str, evidence: list[str])`,
  `NoiseSummary(judged: int, not_reviewed: int, promotions: int)`,
  `PictureRegime(index: Literal["SPY","QQQ"], effective: MarketRegime, base: MarketRegime,
  eased_by_bottoming: bool, suspended: bool, as_of: datetime)`,
  `MarketPicture(version: str, built_at: datetime, regimes: list[PictureRegime],
  regime_source: Literal["trading","news"], facts: list[PictureFact],
  seasonality: SeasonalityView | None, events: list[str], stories: list[PictureStory],
  noise: NoiseSummary)`.
- Produces (`queries.py`, Session-parameterised): `latest_picture(s) -> MarketPicture | None`,
  `triage_since(s, since: datetime) -> list[TriageView]` (`TriageView` in `src/news/schemas.py`:
  `cluster_id, headline, pile, floor, reason, judged_at, promoted_at, promoted_move_pct`),
  `active_stories(s) -> list[PictureStoryRow]`. Each returns empty/None when its table is missing
  (an old `news.db`), never raises.
- Changes: `call_llm(prompt, *, schema, prefix, now, purpose: Literal["general","picture"] = "general")`
  with calls **counted per purpose** (`news_state` keys `llm_calls:<day>` total, as today, plus
  `llm_calls:<day>:general`): a `general` call is allowed while
  `general_calls < max_calls_per_day − reserved_for_picture` **and** `total < max_calls_per_day`; a
  `picture` call (triage and picture builds) while `total < max_calls_per_day`. So general calls can
  never eat the picture reserve (on a heavy picture day the picture may take part of the general
  share; the total cap still holds).
  `cap_reached(now, purpose=...)` likewise; every existing caller keeps `purpose="general"`.
- Produces: `render_picture(p: MarketPicture | None, *, now: datetime, staleness_hours: float) -> str`
  in `src/common/picture_text.py` (imports only `src.common.schemas`) —
  `"=== MARKET PICTURE ==="` then: one line per index (`QQQ: stressed (base cautious; eased by a
  bottoming signal)`), the facts, `Seasonality (weak signal): ...`, events, `S<id> <title> (since
  <date>): <description>` per story; prefixed `PICTURE IS STALE (built <time>)` when older than
  `staleness_hours` or `stale=True`; `"=== MARKET PICTURE ===\n(unavailable)"` when None. Target
  **≤ 300 words** (spec §13: ~400 tokens).

- [x] **Step 1: Failing tests** — `tests/test_news_picture_store.py`

```python
def test_tables_created_by_init_news_db()
def test_latest_picture_round_trips_the_schema()
def test_queries_return_empty_on_an_old_news_db()      # a db file without the three tables
def test_general_calls_stop_at_the_reserve_picture_calls_do_not()
def test_general_is_counted_separately_from_picture()
    # 25 picture calls then general calls: general allowed until general == 30 or total == 40
```

`tests/test_picture_text.py`:

```python
def test_render_picture_lines_and_stale_prefix()
def test_render_picture_unavailable()
def test_render_picture_stays_short()                  # 5 stories, 12 facts -> <= 300 words
def test_picture_text_imports_only_common()
```

- [x] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; full gate (incl.
  `tests/test_news_fence.py::test_only_src_news_constructs_news_rows` — add the three row names to
  its tuple).
- [x] **Step 5: Commit** — `feat(news): triage and picture tables, config, reserved LLM budget`.

---

### Task 9: Triage — the floor, the batch call, the digest

**Files:**
- Create: `src/news/triage.py`, `tests/test_news_triage.py`
- Modify: `src/news/schemas.py` (`TriageItem`, `TriageOutput`), `src/news/prompts.py`
  (`triage_prompt`; `writer_prompt` and `digest_prompt` gain `picture_text: str | None = None`,
  rendered with `render_picture` after the RULES block), `src/news/explain.py` and
  `src/news/followup.py` (pass the latest picture text), `src/news/service.py` (triage loop;
  `_rank_digest` uses triage),
  `src/news/digests.py` (regime line), `src/news/explain.py` (remove `edit_digest`)

**Interfaces:**
- Produces: `TriageItem(cluster_id: int, pile: Literal[1,2,3], reason: str = Field(max_length=120))`,
  `TriageOutput(items: list[TriageItem])`.
- Produces (`src/news/triage.py`):
  - `@dataclass TriageCandidate(cluster: ClusterView, floor: Literal["alert","held"] | None, rank: float)`
  - `presort(clusters: list[ClusterView], *, held: set[str], alerted_ids: set[int], limit: int) -> list[TriageCandidate]`
    — rank (pinned) = `3·[floor=="alert"] + 2·[floor=="held"] + min(source_count, 5)/5 +
    [category in ("macro","government","geopolitics")] + [topic_class != "other"]`; ties by
    `last_seen` desc; top `limit`.
  - `apply_floor(pile: int, floor: str | None) -> int` → `min(pile, 2)` when a floor is set (pile 1
    is highest; Claude may only move a story up from its floor).
  - `run_triage(now: datetime, *, picture: MarketPicture | None) -> int` — clusters from
    `queries.clusters_since(s, last_run, limit=5000)` (explicit: the default limit is 50) not yet in
    `story_triage`, **plus** rows with `pile is None` that have since gained a floor (re-eligible);
    writes every presorted cluster (pile from the LLM, floored, with its `rank`) and every other
    cluster as not reviewed (`pile=None`, `rank` stored); one `call_llm(..., purpose="picture")` per
    batch; on LLM failure, floored clusters get `pile=2`, `reason="floor: alert rule"` /
    `"floor: held name"`, the rest stay not reviewed. Returns the number judged.
  - `alerted_ids` = the union of `NewsPostRow.cluster_ids` for non-digest posts (`kind` not starting
    with `digest`) posted in the triage window; `held` = `collectors.held_underlyings()`.
- `triage_prompt(cands: list[TriageCandidate], picture_text: str | None) -> str` — RULES (existing)
  + the task: "Sort each cluster: 1 = shapes the market picture (market-wide, persisting); 2 = worth
  telling an options seller but does not change the picture; 3 = noise. One-line reason each.
  Cite nothing else." + the picture text + the numbered clusters (`C<id> [category/topic, N sources,
  tickers] headline`) + the JSON schema.
- Digest: `_rank_digest` orders threads from `story_triage` (pile 1 then 2, by `rank` desc) for the
  digest window — **floored clusters are always included** — keeps the `digest_reads` writer call
  (now given the picture text, spec §9), and drops the `edit_digest` call;
  `DigestInputs.regime` becomes the deterministic text from `load_regime_state()` (`"SPY normal ·
  QQQ stressed"`), read through `src.storage.regime_state` (news fence: allowed, like
  `collectors.py:36`).
- Triage loop in `NewsService.loops()`: `("triage", 60, self._triage)`, which runs `run_triage` when
  an `rth_batch_times` slot (ET) has passed since the last run, and inside each digest before ranking.

- [x] **Step 1: Failing tests** — `tests/test_news_triage.py`

```python
def test_presort_ranks_alert_then_held_then_macro()
def test_floor_never_lets_an_alert_or_held_story_fall_to_noise():
    # LLM says pile 3 for an alerted cluster and a held-name cluster -> stored pile 2, floor set
def test_claude_may_promote_a_universe_only_story()     # no floor, LLM pile 1 -> 1
def test_unreviewed_clusters_are_stored_as_not_reviewed()
def test_a_not_reviewed_cluster_that_gains_an_alert_is_triaged_again()
def test_writer_and_digest_prompts_carry_the_picture()   # writer_prompt / digest_prompt gain picture_text: str | None
def test_llm_failure_keeps_the_floor()
def test_triage_uses_the_picture_budget()               # call_llm called with purpose="picture"
def test_digest_orders_threads_by_pile_and_shows_the_deterministic_regime()
def test_digest_no_longer_calls_the_editor()
```

- [x] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; full gate (update the
  existing digest/explain tests that asserted the editor call: replace, do not delete, their
  ordering assertions).
- [x] **Step 5: Commit** — `feat(news): three-pile triage with a deterministic floor; digest uses it`.

---

### Task 10: Stories and the market picture

**Files:**
- Create: `src/news/stories.py`, `src/news/picture.py`, `src/analytics/seasonality.py`,
  `tests/test_news_stories.py`, `tests/test_news_picture.py`
- Modify: `src/news/schemas.py` (`PictureDraft`, `PictureStoryDraft`), `src/news/prompts.py`
  (`picture_prompt`), `src/news/service.py` (picture loop)

**Interfaces:**
- Produces (`src/news/stories.py`, pure):
  - `cluster_signature(c: ClusterView) -> set[str]` = tickers ∪ tags ∪ `topic:<topic_class>` (no title tokens — ruling 21)
  - `match_clusters(stories: list[PictureStoryRow], clusters: list[ClusterView], *, jaccard: float) -> dict[int, list[int]]`
    — a pile-1 or pile-2 cluster attaches to the story whose signature (union of its clusters'
    signatures) has the highest Jaccard ≥ `jaccard`.
  - `story_alive(story: PictureStoryRow, new_ids: list[int], *, now: datetime, window_days: int, min_new: int) -> bool`
    — `len(new ids within window) ≥ min_new`, or the story started within the window.
- Produces (`src/analytics/seasonality.py`): `month_seasonality(month: int, *, years: int = 5) -> SeasonalityView | None`
  (SPY monthly returns via `get_price_provider().get_ohlcv("SPY", lookback_days=365*6)`; daily-cached).
  Ruling 46: the provider caps lookbacks at `"5y"` (`yfinance_backend.py:43-45`), so the view says
  how many years it actually covers (`SeasonalityView.years`) and the picture renders "5-year",
  never "20-year".
- Produces (`src/news/picture.py`):
  - `picture_facts(now: datetime) -> tuple[FactSheet, list[PictureRegime], str]` — the regime from
    `load_regime_state()` (`regime_source="trading"`) or, if absent, `classify_base(fetch_daily_inputs(...))`
    (`"news"`); facts F1.. for each index (close, vs 50/200-day %, drawdown, 1m/3m return, VIX, term
    ratio), 10-year yield and 1-month change, and what `src/news/facts.py::build_market_facts`
    already provides.
  - `picture_due(now: datetime) -> bool` — pre-market or close digest slot passed since the last
    build, or a pile-1 cluster judged since the last build; never more than `max_rebuilds_per_day`.
  - `build_picture(now: datetime) -> MarketPicture | None` — loads active stories, attaches new
    clusters (`match_clusters`), ends stories that fail `story_alive`, calls the LLM once
    (`purpose="picture"`) with `picture_prompt`, validates: every draft story cites ≥ 1 id that
    exists (`C<id>` of a pile-1/2 cluster or `F<n>`); a new story must cite a pile-1 cluster; each
    description passes `grounding.strip_ungrounded(text, refs, rel_tol)` (refs = the fact sheet's
    numbers, `rel_tol = news.grounding.rel_tol`) and `grounding.strip_meta_and_advice(text)` — **a
    story whose description either function trims is dropped** (spec §3: no ungrounded numbers, no
    advice). (`grounding.ground()` takes an `Explanation`, so it is not used here.) Saves a `MarketPictureRow` (version = `built_at` ISO) and the story rows.
    On LLM failure: saves the deterministic part (regimes, facts, seasonality, events, previous
    story titles without descriptions) with `stale=True`.
- `PictureStoryDraft(story_id: int | None, title: str = Field(max_length=80), description: str =
  Field(max_length=280), evidence: list[str])`, `PictureDraft(stories: list[PictureStoryDraft] = Field(max_length=5))`.
- `picture_prompt(facts: FactSheet, stories: list[tuple[int, str, date]], clusters: list[ClusterView], events: list[str]) -> str`
  — RULES + "Name the stories moving the market for an options premium seller (at most 5). Continue
  a listed story by its id or start a new one. Each description ties the story to the numbered facts;
  every number must appear in FACTS. Cite clusters (C#) and facts (F#) in evidence. Seasonality is
  a weak signal: never use it as a reason." + facts, the previous stories as `S<id> <title>
  (since <date>)` (titles only, never prose), the clusters, events, schema.

- [x] **Step 1: Failing tests** — `tests/test_news_stories.py`, `tests/test_news_picture.py`

```python
def test_clusters_attach_by_signature_overlap()
def test_a_story_without_new_supporting_clusters_ends()
def test_a_young_story_survives_its_first_window()
def test_previous_prose_is_never_in_the_prompt()        # build_picture prompt contains titles, not descriptions
def test_uncited_story_is_dropped()
def test_new_story_needs_a_pile_one_cluster()
def test_ungrounded_number_drops_the_story()
def test_advice_in_a_description_drops_the_story()     # "consider reducing exposure" -> dropped
def test_llm_failure_saves_a_stale_deterministic_picture()
def test_regime_comes_from_the_trading_record_when_present()
def test_picture_due_respects_the_daily_cap()
def test_seasonality_is_none_without_history()
def test_seasonality_reports_the_years_it_actually_covers()   # 5 years of bars -> years == 5
```

- [x] **Step 2: Run** → FAIL. **Step 3: Implement** (loop `("picture", 120, self._picture)`).
  **Step 4: Run** → PASS; full gate.
- [x] **Step 5: Commit** — `feat(news): multi-week stories kept alive in Python; grounded market picture`.

---

### Task 11: Noise check (safeguard 2)

**Files:**
- Create: `src/news/noise_check.py`, `tests/test_news_noise_check.py`
- Modify: `src/news/service.py` (loop + posting), `src/news/render.py` (the late-post line)

**Interfaces:**
- Produces: `@dataclass Promotion(cluster_id: int, move_pct: float, basis: Literal["index","ticker"], symbol: str)`;
  `find_promotions(now: datetime, *, bars_for: Callable[[str], pd.DataFrame], beta_for: Callable[[str], float | None]) -> list[Promotion]`
  — judged-noise rows (`pile == 3`) first seen between `now − promote_window_min − 30 min` and
  `now − promote_window_min`, not yet promoted: a ticker cluster uses the ticker's move over the
  window net of `beta × SPY move` (`≥ promote_ticker_residual_pct`, absolute); a macro cluster uses
  `max(|SPY|, |QQQ|)` (`≥ promote_index_move_pct`). Sorted by move desc, capped at
  `max_promotions_per_hour` minus promotions in the last hour. Each promoted row gets `pile=2`,
  `promoted_at`, `promoted_move_pct`.
- Produces: `beta_vs_spy(symbol: str, *, sessions: int = 60) -> float | None` in
  `src/news/noise_check.py` — OLS slope of the symbol's daily returns on SPY's over the last
  `sessions` sessions from `get_ohlcv`; None with fewer than 30 overlapping sessions. The service
  passes `lambda s: beta_vs_spy(s) or 1.0` as `beta_for`.
- The post (render.py), exact copy: `Dismissed earlier; the market moved {move:+.1f}% after it. Cause not confirmed.`

- [ ] **Step 1: Failing tests**

```python
def test_a_dismissed_macro_story_is_promoted_on_an_index_move()
def test_ticker_story_uses_the_beta_adjusted_move()
def test_one_index_move_promotes_at_most_the_cap()
def test_already_promoted_is_not_promoted_again()
def test_late_post_copy_is_exact()
def test_beta_vs_spy_is_none_on_short_history()
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (loop `("noise_check", 300, self._noise_check)`,
  RTH only; posts through the existing alert path, counted against `alerts.max_per_hour`).
  **Step 4: Run** → PASS; full gate.
- [ ] **Step 5: Commit** — `feat(news): market-reaction check promotes dismissed stories`.

---

## Section D — Readers and Claude's cut (Tasks 12–15) · model: sonnet

**Entry checks:**

- [ ] **D1.** Sections A–C committed (eleven commits); Progress log rows 1–11 done; gate green.
- [ ] **D2.** `grep -n "def _format_history" src/claude/prompts/strategist.py` prints one line;
  `grep -n "history=memory" src/orchestrator/scan.py` prints two lines (the full scan and
  `run_ticker_scan`).
- [ ] **D3.** `grep -n "auto_candidates: list\[TradeCandidate\] = \[\]" src/notify/sender.py` and
  `grep -n "def _review_fingerprint" src/orchestrator/scan.py` each print one line.

**Section exit:** four commits; every Claude call reads the picture; the reviewer sees the book;
Claude's cut is applied in paper and record-only in live, with every override recorded;
`CLAUDE.md`'s two rules are amended and fenced.

---

### Task 12: Picture text and the trade reviewer

**Files:**
- Create: `src/claude/picture_context.py`, `src/claude/book_context.py`,
  `tests/test_strategist_picture.py`
- Modify: `src/common/schemas.py` (`ClaudeReview` fields), `src/claude/prompts/strategist.py`,
  `src/claude/runner.py`, `src/claude/ollama_runner.py` (`_REVIEW_ITEM`), `src/orchestrator/scan.py`
  (full scan **and** `run_ticker_scan`: both pass `picture_block` and `book_block`),
  `scripts/review_eval.py` (passes `history=` today; mypy does not cover `scripts/`)
- Delete or rewrite: `tests/test_prompt_history_filter.py` (it tests the removed block)

**Interfaces:**
- Consumes: `render_picture` (Task 8).
- Produces: `load_picture_block(now: datetime) -> str` (news.db read-only via
  `src.news.store.readonly.read_only_session` + `queries.latest_picture`; never raises).
- Produces: `render_book(candidates: list[TradeCandidate], positions: list[PositionSnapshot], *,
  stopouts: dict[str, list[str]], tech_linked: list[str], net_delta: float | None) -> str` —
  `"=== YOUR BOOK ==="`; for each reviewed underlying and its related names (same `sectors` tag or
  both tech-linked): open short options (strike, expiry, ITM/OTM), shares and cost basis; stop-outs
  in the last 5 days; the book's net delta.
- Changes: `ClaudeReview` gains `max_contracts: int | None = None`,
  `size_reason: str = ""`, `backend: Literal["cli","ollama"] | None = None`.
  **`max_contracts` has a `field_validator(mode="before")` that returns None for anything that is
  not a non-bool `int`** (Pydantic's lax mode would turn `true` into 1, and `3.5`/`"three"` would
  raise and make `parser._parse_reviews` drop the whole review). **`backend` is never taken from the
  model's output:** the parser sets it to None on input and the runners always overwrite it — `"cli"`
  on parsed CLI reviews, `"ollama"` in `ollama_runner`.
- Changes: `build_prompt(..., picture_block: str | None = None, book_block: str | None = None)`;
  **`history` removed** from `build_prompt`, `review_candidates` (both runners) and
  `_review_candidates_cli_outcome`; `scan.py` stops calling `_load_memory` for the review (keep
  `_persist_memory`). Each candidate block shows `Size: N contracts (deterministic, after market-regime
  limits; regime <r> on <index>)` and the ladder zone when set. The task text adds: "max_contracts:
  an integer from 0 to N. The market-regime limits above already price the regime: cut only for
  something specific to this name or trade inside its window (a dated event, a thesis-breaking
  story, an existing position on the same bet). Return N to keep the size. size_reason: one
  sentence citing F#/N#/S# ids."

- [ ] **Step 1: Failing tests**

```python
def test_prompt_has_picture_and_book_and_no_prior_recommendations()
def test_malformed_max_contracts_keeps_the_review_and_is_none():
    # parse_claude_output with max_contracts true / 3.5 / "three" -> review kept, max_contracts None
def test_backend_in_the_model_output_is_ignored()      # {"backend": "cli"} from an Ollama answer -> "ollama"
def test_ticker_scan_prompt_has_the_picture()
def test_prompt_states_the_size_and_the_cut_rule()
def test_book_lists_related_names_and_stopouts()
def test_runner_stamps_the_backend()                  # cli -> "cli"; fallback -> "ollama"
def test_review_schema_accepts_the_new_fields()       # ollama _REVIEW_ITEM has max_contracts, size_reason
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**; update the tests that passed `history=` (grep
  `history=` under `tests/`). **Step 4: Run** → PASS; full gate.
- [ ] **Step 5: Commit** — `feat(claude): trade reviewer reads the market picture and the book; prior recommendations removed`.

---

### Task 13: Roll, EOD and spreads readers

**Files:**
- Modify: `src/claude/prompts/roll.py`, `src/claude/runner.py` (`review_roll` passes the block),
  `src/claude/ollama_runner.py` (its `review_roll` and EOD journal calls build the same prompts —
  pass the block there too), `src/claude/prompts/eod.py`, the EOD caller
  (`grep -rn "build_eod_prompt(" src`),
  `src/spreads_ai/context.py`, `src/spreads_ai/prompts.py`, `src/common/schemas.py`
  (`SpreadMarketSnapshot.picture_text: str | None = None`)
- Create: `tests/test_picture_readers.py`

**Interfaces:**
- `build_roll_prompt(alert, pos, quote, *, proposal=None, picture_block: str | None = None)`;
  `build_eod_prompt(summary, *, picture_block: str | None = None)`.
- `spreads_ai/context.py::market_snapshot` fills `picture_text` via `src.news.store.readonly` +
  `queries.latest_picture` + `render_picture`, with the regime lines suffixed `(as of <built_at>)`
  (ruling 11). `spreads_ai` must not import `src.claude` or `src.storage` (fence).

- [ ] **Step 1: Failing tests**

```python
def test_roll_prompt_includes_the_picture_and_still_only_agrees_or_disagrees()
def test_eod_prompt_includes_the_picture()
def test_spreads_prompt_includes_the_picture_labelled_as_of()
def test_spreads_ai_still_imports_neither_claude_nor_storage()   # tests/test_spreads_fence.py stays green
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; full gate.
- [ ] **Step 5: Commit** — `feat(claude): roll, EOD and spreads calls read the market picture`.

---

### Task 14: Claude's cut, the manual card, the review fingerprint

**Files:**
- Modify: `src/engine/regime_limits.py` (`claude_cut`, `cut_applies`), `src/notify/sender.py`,
  `src/notify/formatters.py` (`format_candidate`, the auto-summary cut lines), `src/orchestrator/scan.py`
  (`_review_fingerprint`, `_candidates_review_hash` callers), `config/examples/risk_limits.yaml`
  (top-level `claude_cut:`), `src/common/config.py` (`ClaudeCutCfg`, `get_claude_cut_cfg()`)
- Create: `tests/test_claude_cut.py`

**Config** (ruling 36; spec decision 33):

```yaml
claude_cut:                  # Claude's reduce-only CSP size cut (spec §9)
  apply_in_paper: true       # paper: the cut is applied and every override recorded
  apply_live: false          # live: record-only until the operator has reviewed scripts/sizing_report.py
  breaker_min: 4             # circuit breaker: at least this many auto CSPs cut to 0 today...
  breaker_pct: 50            # ...and more than this % of the day's reviewed auto CSPs -> ignore further cuts
```

**Interfaces:**
- Produces: `claude_cut(deterministic: int, suggested: int | None, backend: str | None) -> int`
  — returns `suggested` only when `backend == "cli"`, `suggested` is an `int` (not bool), and
  `0 ≤ suggested ≤ deterministic`; otherwise `deterministic`.
- Produces: `cut_applies(*, is_live: bool, zeroed_today: int, reviewed_today: int, cfg: ClaudeCutCfg)
  -> tuple[bool, str | None]` (pure) → `(False, "live_record_only")` when `is_live and not
  cfg.apply_live`; `(False, "paper_record_only")` when not live and not `cfg.apply_in_paper`;
  `(False, "breaker")` when `zeroed_today ≥ breaker_min` and `zeroed_today / reviewed_today × 100 >
  breaker_pct`; else `(True, None)`. `is_live` comes from `get_config().is_live`.
- `sender.send_candidates` auto branch: before `_auto_queue_candidates`, for each CSP auto candidate
  with a review, `n = claude_cut(c.contracts, r.max_contracts, r.backend)`. **When `n ==
  c.contracts` nothing happens and nothing is recorded** (ruling 36: only overrides are recorded).
  When `n < c.contracts`: `applies, why = cut_applies(...)` with today's counts (from today's
  `claude_cut` rows with `sent_contracts == 0`, and today's reviewed auto CSPs counted by the
  sender in a `system_settings` counter keyed by ET day).
  - `applies`: `n == 0` → not queued; `n > 0` → `c = c.model_copy(update={"contracts": n,
    "collateral": c.strike * n * 100, "sizing": <note with claude_suggested=n,
    claude_reason=r.size_reason>})`; recorded `kind="claude_cut"`, deterministic = the size before
    the cut, sent = `n`. The auto summary gains one line per cut: "Claude cut TQQQ 65P 3 → 1:
    <reason>" or "Claude: not sending TQQQ 65P (3 lots): <reason>".
  - not `applies`: the candidate is queued at the deterministic size; recorded
    `kind="claude_cut_unapplied"`, deterministic = sent = the deterministic size, and the `reason`
    column holds `"<why>: Claude suggested <n>: <size_reason>"` (the resolver values the
    `deterministic − n` contracts Claude wanted withheld, Task 15). When `why == "breaker"` and it
    is the first breaker trip of the ET day, one Telegram alert in the orders thread: "Claude cut
    <k> of today's <m> auto CSPs to zero; further cuts today are recorded but not applied."
  - CCs and rolls untouched.
- Manual/OBSERVE card: `format_candidate` adds `Claude suggests {n} of {N}: {size_reason}` when
  `review.max_contracts` is a valid cut below `N` (labelled as Claude's; approval still sends N).
- `_review_fingerprint(c, vix, *, regime: str, picture_version: str | None)` adds `"contracts"`,
  `"per_trade_cap"`, `"regime"`, `"picture"`; the scan passes them.

- [ ] **Step 1: Failing tests** — `tests/test_claude_cut.py`

```python
@pytest.mark.parametrize("suggested,backend,expected", [
    (3, "cli", 3), (0, "cli", 0), (12, "cli", 10), (-1, "cli", 10), (None, "cli", 10),
    (True, "cli", 10), (3, "ollama", 10), (3, None, 10)])
def test_claude_cut_is_clamped_and_ignored_when_untrusted(suggested, backend, expected):
    assert claude_cut(10, suggested, backend) == expected
async def test_auto_branch_applies_the_cut_and_records_it()   # paper: 10 -> 3 sent, one claude_cut row
async def test_cut_to_zero_queues_nothing()
async def test_keeping_the_size_records_nothing()               # max_contracts == N -> no row
async def test_live_mode_records_but_sends_the_deterministic_size():
    # is_live True, apply_live False: queued at 10, row kind "claude_cut_unapplied", reason starts "live_record_only"
async def test_breaker_ignores_further_cuts_and_alerts_once():
    # 4 of 6 reviewed auto CSPs already zeroed today -> the 7th cut is unapplied ("breaker"), one alert;
    # an 8th cut -> unapplied, no second alert
async def test_auto_summary_lists_each_applied_cut()
@pytest.mark.parametrize(...) def test_cut_applies(is_live, zeroed, reviewed, cfg, expected)
async def test_ccs_and_rolls_are_never_cut()
def test_manual_card_shows_claudes_suggestion_and_keeps_the_size()
def test_fingerprint_changes_with_regime_or_picture()
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; full gate.
- [ ] **Step 5: Commit** — `feat(claude): reduce-only size cut on auto-opened CSPs — applied in paper, record-only live, every override recorded`.

---

### Task 15: Counterfactual resolver, report, the two rule amendments, fences

**Files:**
- Create: `src/claude/eval/sizing_counterfactual.py`, `scripts/sizing_report.py`,
  `tests/test_sizing_counterfactual.py`, `tests/test_regime_fence.py`
- Modify: the EOD job (`grep -rn "reconcile" scripts/run_eod.py src/orchestrator/eod_report.py`) to
  call `resolve_actions`, `CLAUDE.md`, `src/common/schemas.py` (`ClaudeReview` docstring),
  `STATUS.md` (live-cutover gate line)

**Interfaces:**
- **Withheld contracts per kind:** `deterministic − sent` for every kind, except
  `claude_cut_unapplied` (the contracts Claude wanted withheld, parsed from the row's
  `"Claude suggested <n>"` reason, i.e. `deterministic − n`) and `regime_floor_lot` (`sent` — the
  floor lot itself is what is valued: what letting it through earned).
- `resolve_actions(now: datetime) -> int` — for each unresolved `SizingActionRow` (ruling 17):
  when `order_id` is set and that position's lot has closed (its opening order's candidate has a BUY
  fill, or it expired), `realized_pnl_per_contract` = the traded contract's realised P&L per
  contract (`src.reporting.legs.fill_economics`, the shared accounting rule) and the row's value =
  `realized_pnl_per_contract × withheld` (exact — written to both shadow columns); otherwise, once
  `expiry` is past (ruling 44):
  - `shadow_pnl_expiry = (premium − max(strike − expiry_close, 0)) × 100 × withheld` for puts;
  - `shadow_pnl_rules` — walk the daily closes from `action_day` to expiry (`price_history`, else
    the price provider), price the put each day with `src.analytics.black_scholes` at `entry_iv`
    and the remaining DTE; the first day the put's value is ≤ `(1 − profit_take_pct/100) ×
    premium` closes it there, the first day it is ≥ `max_loss_multiple × premium` closes it there
    (the same thresholds `position_manager` applies); else the expiry value. `× 100 × withheld`.
    With no `entry_iv`, `shadow_pnl_rules` stays None and the report says so.
  Writes `resolved_at`. Returns the count.
- `summarize(since: date) -> dict[str, dict[str, float]]` — per `kind`, split into "sent smaller"
  (`sent > 0`), "never sent" (`sent == 0`) and, for `cc_breakout_floor`, "pushed out" (ruling 45:
  a CC `OrderRow` on the same underlying was created the same ET day — counted, not valued): count,
  contracts withheld, P&L of the withheld contracts under each mark (positive = the trim, block or
  cut cost money). `claude_cut` and `claude_cut_unapplied` are summarised together as "Claude's
  overrides" with applied/unapplied counts, the question being whether not following the system
  paid.
- `scripts/sizing_report.py [--since YYYY-MM-DD]` prints the summary table with both marks side by
  side and says which rows are exact (valued at the traded leg's realised P&L) and which are shadow
  values.

**`CLAUDE.md` amendments (exact copy):**
- In "Core invariant — never violate", after the first paragraph add:
  > **One narrow exception (operator decisions, 2026-10-20/21 — `docs/superpowers/specs/2026-10-20-market-picture-design.md` §9, decisions 3, 15 and 33):**
  > Claude may **lower, never raise,** the contract count of an **auto-opened opening CSP**, through
  > one clamped integer function (`src/engine/regime_limits.py::claude_cut`). It is applied in paper
  > and **record-only in live** (`claude_cut.apply_live: false`) until the operator has reviewed the
  > record; a daily circuit breaker stops applying cuts when Claude zeroes most of the day's auto
  > CSPs. A missing, malformed, out-of-range or Ollama-produced value means the deterministic size.
  > Claude still never places, prices, gates any other field, or touches a close, a roll or a
  > covered call. Every override is recorded in `sizing_actions` (`scripts/sizing_report.py`) and
  > reviewed by a human before the live cutover.
- In the news fence, rule 4, append: "Exception: the same narrow reduce-only cut above, since the
  market picture (news-derived) informs it."
- Add a short "Regime sizing" subsection under "Analytics tiers" listing the deterministic modules
  (Global Constraints line 2) and that they may never import enrichment; and that the news process
  reads the regime record only through `src.storage.regime_state.load_regime_state` (never writes it).
- Make the same core-invariant amendment in `.opencode/agent/ibkr.md` (it restates the invariant,
  around lines 13–15) so opencode sessions do not contradict `CLAUDE.md`.

**Fence tests** — `tests/test_regime_fence.py`:

```python
def test_regime_modules_never_import_enrichment()      # ast over the deterministic list
def test_engine_still_imports_nothing_from_claude_or_news()
def test_claude_cut_is_the_only_llm_value_reaching_contracts():
    # ast over src/notify/sender.py: the only assignment to a candidate's contracts that reads a
    # ClaudeReview attribute goes through claude_cut
def test_spreads_sizing_cannot_reach_regime_limits()   # src/spreads imports no src.engine.regime_limits / src.regime
def test_news_reads_only_regime_state_and_portfolio_snapshots_from_storage():
    # ast over src/news: src.storage imports are only src.storage.regime_state and
    # src.storage.portfolio_snapshots; no call to save_regime_state / suspend_regime / resume_regime
```

Add `"src.regime"`-free assertions to `tests/test_eval_skills.py` only if needed: the existing
`_engine_path_modules()` checks still pass unchanged.

- [ ] **Step 1: Failing tests** (`test_sizing_counterfactual.py`: partial cut valued at the traded
  leg's realised P&L, cut to zero valued both to expiry and under the exit rules, expired OTM,
  expired ITM, **an exit-rule mark that stops out before expiry differs from the expiry mark** (a put
  that went 2.5× the premium then recovered OTM: rules mark negative, expiry mark positive),
  no `entry_iv` leaves `shadow_pnl_rules` None, unresolved before expiry, the sent-smaller /
  never-sent / pushed-out split, `claude_cut_unapplied` valued on Claude's suggested withholding,
  `regime_floor_lot` valued on the lot itself; plus the fence file).
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement + amend `CLAUDE.md`, the `ClaudeReview` docstring
  ("never gating" → "never gating, except the reduce-only `max_contracts` cut"), and `STATUS.md`'s
  live-cutover gate ("review `scripts/sizing_report.py` output before going live — including the
  leveraged-ETF ceiling, floor lots and Claude's overrides — and decide `claude_cut.apply_live`").
- [ ] **Step 4: Run** → PASS; full gate.
- [ ] **Step 5: Commit** — `feat(eval): sizing counterfactual record and report; amend the core invariant`.

---

## Section E — Covered-call timing and the ticker dossier (Tasks 16–19; Task 20 removed) · model: sonnet

**Entry checks:**

- [ ] **E1.** Sections A–D committed (fifteen commits); Progress log rows 1–15 done; gate green.
- [ ] **E2.** Each prints at least one line:

  ```bash
  grep -n "def claude_cut" src/engine/regime_limits.py
  grep -n "^class SizingActionRow" src/storage/models.py
  grep -n "def render_picture" src/common/picture_text.py
  grep -n "^class StoryTriageRow" src/news/store/models.py
  grep -n "^def build_ticker_facts" src/news/facts.py
  grep -n "^def screen_cc_candidates(" src/strategies/covered_call.py
  grep -n "cc_screen = deps.screen_cc(" src/orchestrator/scan_pipeline.py
  grep -n 'CommandHandler("halt"' src/notify/approval_service.py
  grep -rn "TickerDossier\|cc_breakout\|cc_event_hold" src tests | head   # prints nothing
  ```
- [ ] **E3.** `python -m pytest tests/test_news_fence.py tests/test_regime_fence.py tests/test_eval_skills.py -q` passes.

**Section exit:** four commits (Task 20 was removed on 2026-10-21 and has none); the CC breakout
rule applies in the scan and the gate; every `would_own`, `actively_wheeling` and held name has a
dossier in `news.db`; the trade review, the roll review and `/scan` read them. `CLAUDE.md` keeps
exactly one exception (Task 15's).

---

### Task 16: CC breakout rule — resistance detector, floor in the generator and the gate

**Files:**
- Create: `src/analytics/breakout.py`, `tests/test_cc_breakout.py`
- Modify: `src/analytics/support_levels.py` (`resistance_levels`), `src/analytics/technicals.py`
  (`atr14_series`), `config/examples/risk_limits.yaml` (`cc_timing:`), `src/common/config.py`
  (`CcTimingCfg`, `CcBreakoutCfg`, `get_cc_timing_cfg()`), `src/common/schemas.py`
  (`CcBreakout`, `SizingContext.cc_breakout`, `TradeCandidate.cc_breakout`),
  `src/regime/context.py`, `src/engine/regime_limits.py` (`cc_timing_reasons`),
  `src/strategies/covered_call.py`, `src/engine/risk_engine.py` (pass 1),
  `src/orchestrator/scan_pipeline.py`, `src/orchestrator/scan.py` (CC callers; record),
  `src/regime/actions.py` (`key=`), `src/notify/formatters.py`, `src/api/routers/options.py`,
  `tests/test_regime_sizing_integration.py` (the caller test)

**Config** (`config/examples/risk_limits.yaml`, top level — not under `regime:`, ruling 29):

```yaml
cc_timing:
  breakout:
    enabled: true
    lookback_sessions: 5      # a breakout governs CC strikes for this many sessions
    jump_atr: 1.5             # close-to-close rise, in ATR-14 of the day before
    volume_mult: 1.5          # the day's volume vs its 20-session average
    high_sessions: 60         # with no resistance found, a close at this many sessions' high counts
    fade_atr: 1.0             # a later close this many ATRs below the breakout close ends it
    floor_atr: 1.0            # strike floor = max(next resistance above price, price + floor_atr x ATR)
    delta_max: 0.25           # must exceed covered_call.delta_min (0.20), checked at load (ruling 42)
```

(The first draft's `event_hold:` block is gone with Task 20 — spec decision 34.)

**Interfaces:**
- Produces (`src/common/schemas.py`):
  - `class CcBreakout(BaseModel)`: `trigger_day: date`, `trigger_close: float`, `jump_pct: float`,
    `volume_ratio: float`, `broke_level: float | None` (None = a `high_sessions` high),
    `floor_strike: float`, `delta_max: float`, `sessions_left: int`
  - `SizingContext.cc_breakout: dict[str, CcBreakout] = {}`
  - `TradeCandidate.cc_breakout: CcBreakout | None = None`
  - `get_cc_timing_cfg()` raises `ValueError` when `breakout.delta_max ≤
    risk_limits.covered_call.delta_min` (ruling 42).
- Produces: `atr14_series(high, low, close) -> pd.Series` in `technicals.py`; `_atr14` returns its
  last value (no behaviour change; existing technicals tests pass unmodified).
- Produces (`src/analytics/support_levels.py`): `resistance_levels(bars: pd.DataFrame, *, spot: float,
  windows: tuple[int, ...] = (3, 5, 10), merge_atr: float = 0.5, atr: float | None = None,
  broken_atr: float = 1.0, max_levels: int = 5) -> list[float]` — the mirror of Task 5's
  algorithm on daily **highs**: a bar is a swing high when `High[i] == max(High[i−w : i+w+1])`;
  merge levels closer than `merge_atr × atr` (keep the **higher**); drop a level with a later daily
  close `> level + broken_atr × atr`; keep those `> spot`; sort **ascending** (nearest first); cap.
- Produces (`src/analytics/breakout.py`, pure, deterministic tier):
  - `breakout(bars: pd.DataFrame, *, cfg: CcBreakoutCfg) -> CcBreakout | None` (pinned): ATR from
    `atr14_series`. For each of the last `lookback_sessions` sessions `d`, most recent first, `d` is a
    breakout day when **all** of: `Close[d] − Close[d−1] ≥ jump_atr × ATR[d−1]`;
    `Volume[d] ≥ volume_mult × mean(Volume[d−20 : d])`; and either
    `Close[d] > resistance_levels(bars[:d], spot=Close[d−1], atr=ATR[d−1])[0]` (when that list is
    non-empty) or `Close[d] ≥ max(Close[d−high_sessions : d])`. The first match is the trigger. It has
    **ended** when any later close `< Close[d] − fade_atr × ATR[d]` → None. `sessions_left =
    lookback_sessions − (sessions since d)`. Fewer than 30 bars, or no `Volume` column → None.
  - `cc_floor(bars: pd.DataFrame, *, cfg: CcBreakoutCfg) -> float | None` →
    `max(resistance_levels(bars, spot=last_close, atr=ATR_last)[0] if any, last_close + floor_atr × ATR_last)`;
    None without ATR. `breakout(...)` sets `floor_strike` with it.
- Produces (`src/engine/regime_limits.py`): `cc_timing_reasons(ctx: SizingContext | None,
  cand: TradeCandidate) -> list[str]` — for `Strategy.COVERED_CALL` only (never a ROLL, never a
  CSP): `b = (ctx.cc_breakout.get(cand.underlying) if ctx else None) or cand.cc_breakout`; when `b`
  and `cc_timing.breakout.enabled`: `cand.strike < b.floor_strike` → `"cc_breakout_strike_floor"`;
  `cand.delta is not None and abs(cand.delta) > b.delta_max` → `"cc_breakout_delta"`. **Not gated by
  `active(ctx)`** — `/regime off` and `regime.enabled: false` never switch it off (ruling 29).
- Changes: `build_sizing_context` returns a context when `regime.enabled`, any `cc_timing`
  switch **or** `leveraged_sizing.enabled` is on (ruling 35; `active()` is unchanged, so every regime
  limit stays off when the regime is disabled); with `for_send=False` it fills `cc_breakout` for every underlying with ≥ 100 long
  shares in `positions`, from the same daily bars Task 6 fetches. `for_send=True` fetches no bars
  (ruling 28): the send-time gate re-checks from the snapshot's `cand.cc_breakout`.
- Changes: `screen_cc_candidates(..., existing_short_calls=0, *, sizing: SizingContext | None = None)`;
  `ScanDeps.screen_cc` callers pass `sizing=sizing`; `run_ticker_scan`'s direct call (scan.py,
  `cc_screen = screen_cc_candidates(`) passes the ticker's context.
- Changes: `record_action(..., key: str | None = None)` — when given, the upsert key uses `key` in
  place of `cand.candidate_id` (ruling 33).

- [ ] **Step 1: Failing tests** — `tests/test_cc_breakout.py` (synthetic bars; a `make_bars(closes,
  highs=None, lows=None, volumes=None)` helper in the file)

```python
def test_resistance_levels_above_spot_nearest_first()
def test_close_resistance_levels_merge_to_the_higher()
def test_resistance_broken_by_a_later_close_is_dropped()
def test_breakout_needs_a_jump_volume_and_a_level():
    # parametrised: drop each condition in turn -> None; all three -> a CcBreakout
def test_breakout_at_a_60_session_high_without_resistance()
def test_breakout_expires_after_lookback_sessions()     # 6 sessions after the jump -> None
def test_breakout_ends_on_a_fade()                       # a later close 1.1 ATR below -> None
def test_floor_is_the_higher_of_resistance_and_atr()
def test_atr14_series_last_value_matches_atr14()
def test_generator_rejects_near_strikes_and_keeps_far_ones():
    # held 200 shares, breakout floor 760, delta_max 0.25, covered_call.delta_min 0.20: a 745C
    # (delta 0.35) carries "cc_breakout_strike_floor" and "cc_breakout_delta"; a 765C (delta 0.22)
    # passes every gate (the strategy's delta band too — ruling 42); candidate.cc_breakout is set on both
def test_breakout_delta_guard_must_exceed_delta_min()   # delta_max 0.20 with delta_min 0.20 -> ValueError
def test_gate_rejects_a_near_cc_during_a_breakout()
def test_breakout_never_touches_rolls_or_csps()
def test_breakout_not_switched_off_by_regime_off()       # ctx.suspended True -> still rejects the 745C
def test_context_built_when_regime_disabled_but_breakout_enabled()
def test_scan_records_one_breakout_row_per_name_per_day():
    # two scans, different near strikes rejected only for cc_breakout_* -> one SizingActionRow,
    # kind "cc_breakout_floor", key "cctiming:META:<ET date>", the first contract kept
```

  Extend `test_every_production_caller_passes_sizing` (Task 3) to calls of `screen_cc_candidates`
  and `deps.screen_cc`.

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
  - **Generator:** after the existing gates in `screen_cc_candidates`, `reasons.extend(
    cc_timing_reasons(sizing, candidate))` and set `candidate.cc_breakout`; the full reason list
    is kept, as for every other gate.
  - **Gate pass 1:** for a CC that is not a roll, `reasons.extend(cc_timing_reasons(sizing, cand))`.
  - **Record (scan.py, after the gate):** per underlying, the highest-premium CC rejected **only**
    for `cc_breakout_*` reasons is recorded with `record_action(kind="cc_breakout_floor",
    deterministic=cand.contracts, sent=0, key=f"cctiming:{sym}:{et_day}")`. When a farther CC on the
    same name is sold that day, Task 15's `summarize` reports the row as "pushed out" (ruling 45).
  - **Labels** (both maps, identical): `cc_breakout_strike_floor`: "below the strike floor after
    a breakout"; `cc_breakout_delta`: "too close to the money after a breakout".
  - **Card line** (`format_candidate`, CCs with `cc_breakout`): "Breakout Oct 14 (+6.1%, 2.3×
    volume, above $742.00): CC strikes at or above $760.00, delta ≤ 0.25, for 3 more sessions".
- [ ] **Step 4: Run** → PASS; full gate (existing CC and risk-engine tests pass unchanged — they
  call without `sizing`).
- [ ] **Step 5: Commit** — `feat(cc): breakout rule pushes covered-call strikes out; resistance detector`.

---

### Task 17: Dossier store, deterministic facts, health, verified events

**Files:**
- Create: `src/news/dossier.py`, `src/common/dossier_text.py`, `tests/test_dossier_store.py`,
  `tests/test_dossier_facts.py`, `tests/test_dossier_text.py`
- Modify: `src/news/store/models.py` (`TickerDossierRow`), `src/news/store/queries.py`,
  `src/common/schemas.py` (`DossierFact`, `DossierEvent`, `TickerDossier`), `src/common/config.py`
  (`NewsDossierCfg`), `config/examples/news.yaml`, `src/news/llm.py` (`purpose="dossier"`),
  `tests/test_news_fence.py` (row tuple)

**Config** (`config/examples/news.yaml`; `llm.max_calls_per_day` rises 40 → 44, rulings 25 and 43):

```yaml
llm: {backend: cli_then_ollama, model: "claude-sonnet-5-5", ollama_model: "", timeout_seconds: 120,
      max_calls_per_day: 44, reserved_for_picture: 10}
dossier:
  enabled: true
  batch_size: 6                # names per LLM call
  max_calls_per_day: 4         # its own cap; general news calls keep 44 - 10 - 4 = 30 (ruling 43)
  facts_refresh_min: 60        # deterministic refresh, no LLM
  prose_min_interval_hours: 6  # prose is rebuilt on change, at most this often per name (ruling 43)
  profile_days: 7
  story_window_days: 7
  max_event_days: 45
  staleness_hours: 26
  max_names_in_review: 8
  keep_days: 30
  health: {de_strong: 100.0, de_weak: 200.0}   # debt/equity in yfinance's unit (percent: 150 = 1.5x)
```

**Interfaces:**
- Produces (`src/common/schemas.py`, neutral — readers import them):
  - `DossierFact(id: str, label: str, display: str)` — `id` is `<SYM>:F<n>`
  - `DossierEvent(id: str, title: str = Field(max_length=80), on: date, evidence: str, quote: str = Field(max_length=200))`
    — `id` is `<SYM>:E<n>`, `evidence` a `C<id>`, `quote` the cluster text that contains the date
  - `TickerDossier(symbol: str, version: str, facts_at: datetime, prose_at: datetime | None = None,
    profile_at: datetime | None = None, kind: Literal["stock","etf","leveraged_etf"],
    health: Literal["strong","ok","weak","n/a","unknown"], health_why: list[str] = [],
    facts: list[DossierFact] = [], sentiment_7d: float | None = None, sentiment_items_7d: int = 0,
    profile: str = "", story: str = "", story_evidence: list[str] = [],
    events: list[DossierEvent] = [], stale: bool = False)`
- Produces (`src/news/store/models.py`): `TickerDossierRow` (`ticker_dossiers`: `id`, `symbol`
  String(16) index, `version` unique, `built_at` index, `payload` JSON). One row per build; the
  latest per symbol wins.
- Produces (`queries.py`, Session-parameterised): `latest_dossier(s, symbol) -> TickerDossier | None`,
  `latest_dossiers(s, symbols: list[str]) -> dict[str, TickerDossier]`. Empty/None when the table is
  missing (an old `news.db`), never raises.
- Changes (`src/news/llm.py`): `purpose: Literal["general","picture","dossier"]`, counted per
  purpose (`llm_calls:<day>:dossier`). A `dossier` call is allowed while `dossier_calls <
  dossier.max_calls_per_day` **and** `total < max_calls_per_day`; a `general` call while
  `general_calls < max_calls_per_day − reserved_for_picture − dossier.max_calls_per_day` and
  `total < max_calls_per_day` (this replaces Task 8's general formula; `picture` is unchanged).
- Produces (`src/news/dossier.py`, deterministic part — enrichment-tier package, no LLM here):
  - `dossier_symbols() -> list[str]` — sorted `would_own ∪ actively_wheeling` from
    `effective_universe()` ∪ `collectors.held_underlyings()` (ruling 23).
  - `kind_of(symbol: str, fund: FundamentalStats | None) -> Literal["stock","etf","leveraged_etf"]`
    — `leveraged_etf` when in `universe.leveraged_etfs`; `etf` when in `universe.indexes` or
    `fund.total_assets is not None`; else `stock`.
  - `health_label(fund: FundamentalStats | None, kind: str, cfg: NewsDossierCfg) -> tuple[str, list[str]]`
    (pinned): ETF kinds → `("n/a", [])`; no fund, or `quality_flag`, `free_cash_flow` and
    `debt_to_equity` all None → `("unknown", ["no fundamentals"])`; `free_cash_flow < 0` or
    `debt_to_equity > de_weak` → `weak`; `quality_flag` and `free_cash_flow > 0` and
    (`debt_to_equity` None or `≤ de_strong`) → `strong`; else `ok`. Each reason is a short phrase
    ("free cash flow negative", "debt/equity 2.4x", "passes the quality screen").
  - `build_facts(symbol: str, *, an: Analytics, today: date, cfg: NewsCfg, session: Session) -> tuple[list[DossierFact], float | None, int]`
    — `build_ticker_facts(symbol, an=an, positions=[], lists=universe_lists(symbol), earnings=<from
    queries.earnings_between, as _alert_ctx does>, cluster_tags=set(), today=today, cfg=cfg)`
    (**`positions=[]`: no book in a dossier**, ruling 24) plus 1- and 3-month returns from
    `an.daily`, the governing regime index (`QQQ` when tech-linked, else `SPY`) and the 7-day mean
    `det_sentiment` with its item count from `queries.ticker_sentiment_rows`; ids re-prefixed
    `<SYM>:F<n>`.
  - `verify_event_date(text: str, on: date) -> str | None` (pinned) — returns the ≤ 200-character
    snippet around the first match, or None. Accepted, case-insensitive, at word boundaries:
    `October 22`, `Oct 22`, `Oct. 22`, `Oct 22nd`, `22 October`, `10/22`, `2026-10-22`, each with an
    optional year that must equal `on.year` when present. `Oct 2` never matches `Oct 22`; relative
    dates ("next Tuesday", "later this month") never match.
  - `refresh_facts(now: datetime) -> int` — for each dossier symbol whose latest `facts_at` is older
    than `facts_refresh_min`: a new row with fresh facts, health and sentiment, copying the previous
    profile, story, story evidence, `prose_at`, `profile_at` and `stale`; events dated before today
    are dropped. Once a day it deletes rows older than `keep_days`. Never raises.
- Produces (`src/common/dossier_text.py`, imports only `src.common.schemas`):
  `render_dossier(d: TickerDossier | None, *, symbol: str, now: datetime, staleness_hours: float, compact: bool) -> str`
  and `render_dossiers(ds: list[tuple[str, TickerDossier | None]], *, now, staleness_hours, compact) -> str`
  (`"=== NAME NOTES ==="` + one block per name). A block opens `--- META (stock · health strong) ---`.
  **Compact** (≤ 80 words): the first health reason, the story with its evidence ids, the events
  (`META:E1 MUSE launch event on 2026-10-22 (C8123)`), and three facts chosen by label in this order
  of preference — `Price vs SMA200`, `RSI14`, `IV rank`, `Nearest resistance`, `Nearest support`.
  **Full** (≤ 220 words) adds `Profile (Claude's summary, general knowledge): …`, every fact and the
  7-day sentiment. `PROSE IS STALE (built <time>)` when `stale` or `prose_at` is older than
  `staleness_hours`; `--- META --- (no notes yet)` for None.

- [ ] **Step 1: Failing tests**

```python
# tests/test_dossier_store.py
def test_table_created_and_latest_dossier_round_trips()
def test_latest_wins_per_symbol()
def test_queries_return_empty_on_an_old_news_db()
def test_dossier_budget_has_its_own_cap_and_general_keeps_thirty():
    # 4 dossier calls allowed, the 5th refused; general refused at 30; total never above 44
# tests/test_dossier_facts.py
def test_dossier_symbols_are_universe_plus_held()        # a held AMD outside would_own is included
def test_kind_of_leveraged_etf_etf_and_stock()
@pytest.mark.parametrize(...) def test_health_label_rules(fund, kind, expected)
def test_facts_have_prefixed_ids_and_no_book()          # no "Shares" fact even with a held position
@pytest.mark.parametrize("text,on,ok", [
    ("Meta to unveil MUSE at Connect on Oct 22", date(2026, 10, 22), True),
    ("event set for October 22, 2026", date(2026, 10, 22), True),
    ("on 10/22 the company", date(2026, 10, 22), True),
    ("scheduled 2026-10-22", date(2026, 10, 22), True),
    ("on Oct 2 the company", date(2026, 10, 22), False),
    ("event next Tuesday", date(2026, 10, 22), False),
    ("October 22, 2025", date(2026, 10, 22), False)])
def test_verify_event_date(text, on, ok)
def test_facts_refresh_keeps_prose_and_drops_past_events()
# tests/test_dossier_text.py
def test_render_compact_within_80_words_and_full_within_220()
def test_render_labels_the_profile_and_the_stale_prefix()
def test_render_without_a_dossier()
def test_dossier_text_imports_only_common()
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (add `TickerDossierRow` to
  `tests/test_news_fence.py::test_only_src_news_constructs_news_rows`' tuple). **Step 4: Run** →
  PASS; full gate.
- [ ] **Step 5: Commit** — `feat(news): ticker dossier store, deterministic facts and health, verified event dates`.

---

### Task 18: Dossier builds — batched prose, grounding, cadence, budget

**Files:**
- Create: `tests/test_dossier_build.py`
- Modify: `src/news/schemas.py` (`DossierDraft`, `DossierNameDraft`, `DossierEventDraft`),
  `src/news/prompts.py` (`dossier_prompt`), `src/news/dossier.py` (`dossier_due`,
  `build_dossier_prose`), `src/news/service.py` (two loops)

**Interfaces:**
- Produces: `DossierEventDraft(title: str = Field(max_length=80), on: date, evidence: str)`,
  `DossierNameDraft(symbol: str, profile: str | None = Field(None, max_length=400), story: str =
  Field("", max_length=280), story_evidence: list[str] = [], events: list[DossierEventDraft] =
  Field([], max_length=3))`, `DossierDraft(names: list[DossierNameDraft])`.
- Produces: `dossier_due(symbol: str, last: TickerDossier | None, *, now: datetime, s: Session) -> list[str]`
  — the reasons, empty when not due: `new` (no dossier or no `prose_at`); `news` (a `story_triage`
  row with pile 1 or 2, judged after `prose_at`, whose cluster names the symbol); `alert` (a
  non-digest `NewsPostRow` about the symbol posted after `prose_at`); `earnings` (a report date
  between `prose_at` and `now`); `profile` (`profile_at` None or older than `profile_days` — the
  profile is then requested too). **There is no `age` reason** (ruling 43, spec decision 37): old
  prose is shown labelled with its age, never rebuilt for being old. A `news` or `profile` reason
  is dropped while `prose_at` is newer than `prose_min_interval_hours`; `new`, `alert` and
  `earnings` are never held back. A name already in a batch for another reason also gets its
  profile requested when `profile_at` is older than `profile_days`.
- Produces: `build_dossier_prose(now: datetime) -> int` — due names ordered held first, then by
  number of reasons, then symbol; batches of `batch_size`; one `call_llm(prompt, schema=<DossierDraft
  schema>, prefix="dossier", now=now, purpose="dossier")` per batch while the cap allows (the rest
  wait for the next loop); validates (below); writes one new row per name. Returns names built.
- `dossier_prompt(entries: list[DossierPromptEntry], picture_text: str | None) -> str` —
  `DossierPromptEntry(symbol, kind, facts: list[DossierFact], clusters: list[ClusterView],
  want_profile: bool)`. RULES (existing) + the task: "For each name: PROFILE (only when requested):
  what the company or fund is and what moves its price, at most 3 sentences, no numbers. STORY: what
  is happening to the name now, from its listed clusters only, citing C# ids; leave it empty if none
  of them is about the name. EVENTS: dated upcoming catalysts other than earnings that a listed
  cluster states with a calendar date, citing that cluster; never infer or estimate a date." + the
  picture text + per name its facts (ids), its clusters (pile 1 or 2, within `story_window_days`,
  naming the symbol, at most 8: `C<id> headline` plus up to two item titles or summaries of ≤ 200
  characters), and `PROFILE requested: yes|no` + the schema. **No previous profile, story or event
  text is ever included** (decision 26).
- Validation per name (pinned; ruling 26):
  - an unknown symbol is ignored;
  - **profile:** after removing leverage multiples and index names (ruling 47: `-?\d(\.\d)?x\b`,
    `S&P 500`, `Nasdaq-100`, `Nasdaq 100`, `Russell 2000`, `Dow 30`, case-insensitive), rejected
    when `grounding.extract_numbers(profile)` is non-empty or
    `grounding.strip_meta_and_advice` trims it → the previous profile and `profile_at` stay;
  - **story:** kept only when it cites at least one `C<id>` of that name's listed clusters (in
    `story_evidence` or inline) and neither `grounding.strip_ungrounded(story, refs=<the name's fact
    numbers>, rel_tol=news.grounding.rel_tol)` nor `strip_meta_and_advice` trims it; otherwise the
    story is empty (never the previous one);
  - **events:** each must cite a `C<id>` of that name's listed clusters whose text passes
    `verify_event_date(text, on)`, with `today < on ≤ today + max_event_days`; a title matching
    `earnings|results|quarter` (case-insensitive) is dropped; ETFs and leveraged ETFs keep none.
    Verified events from the previous dossier that are still in the future are kept (ruling 27);
    duplicates by (`on`, `evidence`) collapse; ids `<SYM>:E<n>` in date order.
  - **LLM failure** (no answer, timeout, cap reached mid-batch): the batch's names keep their previous
    prose, marked `stale=True`.
- Loops in `NewsService.loops()`: `("dossier_facts", 300, self._dossier_facts)` (runs
  `refresh_facts`) and `("dossier", 600, self._dossier)` (runs `build_dossier_prose`), from the
  pre-market digest slot to the close; both no-ops when `dossier.enabled` is false.

- [ ] **Step 1: Failing tests** — `tests/test_dossier_build.py`

```python
def test_due_reasons_new_news_alert_earnings_profile()
def test_old_prose_alone_is_not_due()                    # prose_at 30 hours old, no news -> []
def test_news_reason_waits_for_the_min_interval()        # prose 2 hours old + new pile-2 cluster -> []; alert -> ["alert"]
def test_a_leveraged_etf_profile_may_say_3x_and_nasdaq_100()   # ruling 47
def test_batches_respect_size_and_the_dossier_cap()      # 30 due names, cap 4 calls -> 24 built, 6 wait
def test_held_names_are_built_first()
def test_previous_prose_is_never_in_the_prompt()        # the previous story text is absent from the prompt
def test_profile_with_a_number_or_advice_keeps_the_previous_profile()
def test_uncited_or_ungrounded_story_is_dropped()
def test_event_without_the_date_in_its_cluster_is_dropped()
def test_earnings_events_and_etf_events_are_dropped()
def test_verified_events_persist_until_their_date()
def test_llm_failure_keeps_previous_prose_marked_stale()
def test_dossier_calls_use_the_dossier_purpose()
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; full gate.
- [ ] **Step 5: Commit** — `feat(news): batched dossier prose with grounding and verified events`.

---

### Task 19: Dossier readers — trade review, roll review, `/scan`

**Files:**
- Create: `src/claude/dossier_context.py`, `tests/test_dossier_readers.py`; add
  `test_no_llm_value_reaches_a_covered_call` to `tests/test_regime_fence.py` (Task 20 stub)
- Modify: `src/claude/prompts/strategist.py` (`build_prompt(..., dossier_block=None)` and the RULES
  text), `src/claude/prompts/roll.py` (`dossier_block=None`), `src/claude/runner.py` and
  `src/claude/ollama_runner.py` (pass-through), `src/orchestrator/scan.py` (full scan,
  `run_ticker_scan`, `_review_fingerprint`), the roll-review caller (`grep -rn "review_roll(" src`)

**Interfaces:**
- Produces (`src/claude/dossier_context.py`, enrichment):
  - `load_dossiers(symbols: list[str]) -> dict[str, TickerDossier]` — `news.db` read-only via
    `src.news.store.readonly.read_only_session` + `queries.latest_dossiers`; `{}` when the file or
    the table is missing; never raises.
  - `dossier_block(symbols: list[str], dossiers: dict[str, TickerDossier], *, now: datetime,
    compact: bool, max_names: int) -> str` — `render_dossiers` over the first `max_names` symbols,
    then `(N more names without notes in this prompt)` when any were cut.
  - `prose_key(d: TickerDossier | None) -> str | None` — `prose_at` ISO plus the sorted
    `(event id, date)` pairs; None for no dossier (ruling 43).
- Changes: the full-scan review gets the **compact** block for the reviewed underlyings in candidate
  priority order, capped at `dossier.max_names_in_review`, placed after the market picture and
  before the candidates; `/scan TICKER` and the roll review get the **full** block for their one
  name. The RULES text adds: "NAME NOTES give each name's situation. Cite their ids (META:F3,
  META:E1, C#) like other facts. A profile is general knowledge, never the only reason for a
  verdict."
- Changes: `_review_fingerprint(c, vix, *, regime, picture_version, dossier_key: str | None)`
  adds `"dossier"` = `prose_key(...)` of the name's latest dossier — **not** its `version`, which
  changes on every hourly fact refresh and would defeat review reuse (ruling 43). A reused review is
  never older than the prose and events it read; the facts it read are at most an hour old.

- [ ] **Step 1: Failing tests** — `tests/test_dossier_readers.py`

```python
def test_trade_review_prompt_has_compact_notes_for_reviewed_names_only()
def test_notes_capped_at_max_names_in_priority_order()
def test_ticker_scan_and_roll_prompts_have_full_notes()
def test_missing_news_db_gives_no_block_and_no_error()
def test_fingerprint_changes_with_new_prose_or_events()
def test_fingerprint_ignores_the_hourly_fact_refresh()  # a refresh_facts row with the same prose_at -> same fingerprint
# and in tests/test_regime_fence.py: test_no_llm_value_reaches_a_covered_call (see the Task 20 stub)
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; full gate.
- [ ] **Step 5: Commit** — `feat(claude): trade, roll and /scan reviews read each name's dossier`.

---

### Task 20: ~~Claude's CC event hold, `/ccholds`, the record, the amendment~~ — removed

**Removed 2026-10-21 by the operator** (spec decision 34, §17). Build nothing here and make no commit;
the Progress-log row says "removed". Nothing else in this plan may add `ClaudeReview.cc_action`,
`cc_event`, `cc_reason`, `CcHold`, `claude_cc_hold`, `src/storage/cc_holds.py`, the
`cc_event_holds` setting, the `cc_event_hold` / `cc_event_floor` reasons or a `/ccholds` command.
The dossiers' verified events (Tasks 17–18) stay: they are information in the reviewers' prompts and
on the page, and nothing acts on them. `CLAUDE.md` keeps exactly one exception to the core
invariant (Task 15's).

**One guard test, added in Task 19's commit** (`tests/test_regime_fence.py`):

```python
def test_no_llm_value_reaches_a_covered_call():
    # ast over src/notify/sender.py and src/engine/: no ClaudeReview attribute other than
    # max_contracts (through claude_cut) is read on the order path; no name "cc_hold" exists in src/
```

---

## Section F — The page (Tasks 21–22) · model: sonnet

**Entry checks:**

- [ ] **F1.** Sections A–E committed (nineteen commits — Task 20 has none); gate green.
- [ ] **F2.** `cd web && npx vitest run && npx tsc --noEmit && npm run lint` green; record the count.
- [ ] **F3.** `grep -n "def read_only_session\|def news_read_session" src/api/news_db.py` and
  `ls src/api/settings_read.py` print lines.
- [ ] **F4.** `python -m pytest tests/test_web_fence.py tests/test_openapi_current.py -q` passes.

**Section exit:** two commits; `/more/claude` renders with real data and degrades cleanly.

---

### Task 21: `GET /claude/context`

**Files:**
- Create: `src/api/routers/claude_context.py`, `src/api/models/claude_context.py`,
  `src/api/claude_calls.py`, `tests/test_api_claude_context.py`
- Modify: `src/api/main.py`, `docs/web/openapi.json`, `web/lib/api-types.ts` (regenerated),
  `docs/web/api.md`

**Interfaces:**
- `GET /claude/context` → `ClaudeContextResponse`: `as_of: datetime`, `available: bool` (news.db
  present), `picture: MarketPicture | None`, `regime: RegimeState | None` (trading DB read-only via
  the existing `src/api/settings_read.py::read_setting(db: TradingDb, key)` — it already takes the
  db handle; do not add a second reader), `suspended_today: bool`, `limits: list[RegimeLimitOut]`
  (`index, regime, budget_pct, per_trade_pct, max_new_per_day, floor_new_per_day`),
  `leveraged: list[LeveragedLimitOut]` (`symbol, leverage, calm_fraction, stressed_fraction` —
  ruling 35),
  `claude_cut_mode: Literal["applied","record_only"]` (ruling 36, for the account the API runs
  against), `calls: list[CallContextOut]`
  (`kind, label, blocks: list[str]`), `dropped: list[DroppedOut]` (`cluster_id, headline, reason,
  judged_at, promoted: bool, promoted_move_pct`), `not_reviewed_7d: int`,
  `dossiers: list[DossierOut]` (`symbol, kind, health, health_why, story, story_evidence, events:
  list[DossierEvent], profile, facts_at, prose_at, stale` — every dossier symbol, from
  `queries.latest_dossiers`; empty on an old `news.db`).
- `src/api/claude_calls.py::CALLS` (static, the tiles): a list of
  `(kind, label, [(block_label, header_substring, builder_file)])`. The map (header substrings are
  the `=== … ===` headers the builders emit; Tasks 8–13 and 19 add the new ones):

  | Call | Block label → header substring (file) |
  |---|---|
  | Trade review | Market picture → `MARKET PICTURE` (common/picture_text.py); Your book → `YOUR BOOK` (claude/book_context.py); Name notes → `NAME NOTES` (common/dossier_text.py); News → `=== NEWS` (claude/news_context.py); Candidates → `TRADE CANDIDATES` (claude/prompts/strategist.py) |
  | Roll review | Market picture → `MARKET PICTURE`; Name notes → `NAME NOTES`; Position → `POSITION`; Live quote → `LIVE QUOTE`; System proposal → `SYSTEM PROPOSAL` (claude/prompts/roll.py) |
  | Spreads picker | Market picture (as of build) → `MARKET PICTURE`; Tape → `TAPE (ET)`; Events → `=== EVENTS`; Headlines → `HEADLINES (untrusted`; Menu → `=== MENU` (spreads_ai/prompts.py) |
  | News expert | Facts → `=== FACTS`; Clusters → `=== CLUSTERS`; Market picture → `MARKET PICTURE` (news/prompts.py) |
  | EOD journal | Market picture → `MARKET PICTURE`; Today's trades → `TODAY'S TRADES` (claude/prompts/eod.py) |
  | `/scan` | Market picture → `MARKET PICTURE`; Name notes → `NAME NOTES`; Sector → `SECTOR` (the sector-context block); News → `=== NEWS`; Candidates → `TRADE CANDIDATES` |
  | Dossier builder | Facts → `FACTS`; Clusters → `CLUSTERS`; Market picture → `MARKET PICTURE` (news/prompts.py, `dossier_prompt`) |

  A test asserts each `header_substring` occurs in its `builder_file`'s source text.

- [ ] **Step 1: Failing tests**

```python
def test_context_with_everything()
def test_context_without_news_db()                    # available False, regime still shown
def test_context_with_old_news_db()                    # tables missing -> picture None, dropped []
def test_context_without_regime_state()
def test_dropped_lists_judged_noise_and_promotions_last_7_days()
def test_context_lists_dossiers_leveraged_limits_and_the_cut_mode()
def test_api_still_writes_exactly_one_table()          # existing web-fence test stays green
```

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement**, then regenerate:

```bash
python -c "import json; from src.api.main import create_app; print(json.dumps(create_app().openapi(), indent=2))" > docs/web/openapi.json
cd web && npx openapi-typescript ../docs/web/openapi.json -o lib/api-types.ts && cd ..
python -m pytest tests/test_openapi_current.py -q
```

- [ ] **Step 4: Run** → PASS; full gate.
- [ ] **Step 5: Commit** — `feat(api): GET /claude/context`.

---

### Task 22: The "What Claude knows" page

**Start by invoking the `da-vinci` skill** (it reads `web/DESIGN.md`); add the surface's contract to
`web/DESIGN.md` (§ Surfaces) before any page code, and run its critique/audit at the end.

**Files:**
- Create: `web/app/more/claude/page.tsx`, `web/features/claude-context/ClaudeContextPage.tsx`,
  `web/features/claude-context/types.ts`, `web/features/claude-context/ClaudeContextPage.test.tsx`
- Modify: `web/app/more/page.tsx` (LINKS: `{ href: "/more/claude", label: "What Claude knows", sub:
  "The market picture and what each Claude call reads" }`), `web/DESIGN.md`

**Content (mockup option A, spec §11):**
- Top card: SPY and QQQ regimes in words ("QQQ: stressed, eased one step by a bottoming signal"),
  "Regime limits suspended today" when suspended, the CSP limits per index, the facts, stories with
  "since <date>", seasonality labelled "weak signal", events, "Rebuilt <time>" / "Stale since <time>".
- Tiles: one per `calls[]` entry with its blocks as chips.
- "Dropped as noise (7 days)": rows with headline and reason; promoted rows say "Promoted: the market
  moved +1.2% after it"; a line "N stories were not reviewed".
- In the top card, under the limits: the leveraged-ETF ceilings ("TQQQ, SOXL, UPRO … 3×: 60% of
  the regime's size when calm, 30% when the name or its market is under stress; TSLL 2×: 80% / 50%")
  and Claude's cut mode ("Claude's size cuts: applied (paper)" or
  "recorded only (live)").
- "Names" (spec §16): one row per dossier symbol — kind and health (with its first reason), Claude's
  story with its evidence ids, upcoming events with dates, "Notes rebuilt <time>" / "Stale since
  <time>"; the row expands to the profile, labelled "Claude's summary, general knowledge", and the
  facts. Held names first, then alphabetical.
- Unknown values follow DESIGN.md's unknown rule; Claude's text is labelled as Claude's.

- [ ] **Step 1: Failing tests** — `ClaudeContextPage.test.tsx`

```tsx
it("shows both regimes and the CSP limits")
it("says the limits are suspended today")
it("labels seasonality as a weak signal")
it("shows a stale picture as stale")
it("lists a tile per Claude call with its blocks")
it("shows dropped stories with reasons and promotions")
it("says the news service has no picture yet when unavailable")
it("lists each name's notes with Claude's text and the profile labelled")
it("shows the leveraged-ETF ceilings and Claude's cut mode")
```

- [ ] **Step 2: Run** `cd web && npx vitest run features/claude-context` → FAIL.
- [ ] **Step 3: Implement** (react-query + `apiFetch`, like `features/position/PositionPage.tsx`).
- [ ] **Step 4: Run** → PASS; `npx tsc --noEmit && npm run lint`; da-vinci lint and
  `python3 ~/.claude/skills/da-vinci/scripts/design_md_check.py web/DESIGN.md` exit 0.
- [ ] **Step 5: Commit** — `feat(web): What Claude knows page`.

---

## Section G — Docs and finish (Task 23) · model: sonnet, then an opus whole-branch review

**Entry checks:**

- [ ] **G1.** Twenty-one commits; Progress log rows 1–22 done (row 20 "removed"); Python and web gates green.

---

### Task 23: Docs and the full gate

- [ ] **Step 1: Docs** per `CLAUDE.md`'s update table:
  - `ARCHITECTURE.md`: folder guide entries for every new module (both File structure blocks
    above), the `src/regime/` package, the four news tables (incl. `ticker_dossiers`),
    `sizing_actions`, the `/regime` command, the `leveraged_sizing:` and `claude_cut:` blocks, the
    `/claude/context` route, the data-flow addition (regime and CC timing → SizingContext →
    sizer/generator/gate; dossiers → every review prompt), and the pipeline diagram's new step.
  - `STATUS.md`: built (regime sizing with the guaranteed floor, the leveraged-ETF ceiling, ladder
    with the same-day loss-exit block, bottoming, triage, picture, Claude's cut — applied in paper,
    record-only live — CC breakout rule, dossiers, page); deliberately not built (the CC event hold,
    withdrawn 2026-10-21); known limitations (shadow marks are Black-Scholes at the entry IV on daily
    closes, not real fills; the VRP-gate interaction from Task 7's replay; the event-date matcher
    accepts only explicit calendar dates; the dossier profile is unchecked general knowledge; first
    lots opened before any signal are not protected beyond the per-trade ceilings; the
    `close:delta_missing` forced-close bug is separate and still open; held-stock risk out of scope);
    the live-cutover gate line (Task 15), including deciding `claude_cut.apply_live`.
  - `SETUP.md`: `/regime` in the commands table; the scripts table gains
    `scripts/sizing_report.py`, `scripts/export_week_fixture.py` and `scripts/replay_week.py`; restart
    order (trading service, news, API); the new config blocks (`regime:`, `leveraged_sizing:`,
    `claude_cut:`, `cc_timing:`, `dossier:`, and the operator's private `news.yaml` raising
    `llm.max_calls_per_day` to 44 — rulings 25 and 43; the operator's private `risk_limits.yaml` needs
    the `regime:`, `leveraged_sizing:`, `claude_cut:` and `cc_timing:` blocks by hand). Record
    the measured prompt-block sizes (ruling 22) in this task's Progress-log row.
  - `README.md`: `/regime` in the Telegram commands table.
  - `How the scan works.md`: one paragraph on regime limits, the guaranteed floor and the
    leveraged-ETF ceiling; one on the ladder and the same-day loss-exit block; one on the CC breakout
    rule.
  - `docs/web/api.md`: `/claude/context`.
- [ ] **Step 2: Full gate** — `python -m pytest -q && ruff check . && mypy src`, the web gate, and
  `git diff main -- config/*.yaml` shows no private config.
- [ ] **Step 3: Commit** — `docs: market picture, regime sizing, news expert`.
- [ ] **Step 4: Whole-branch review** (orchestrator): one Opus subagent reviews `main..feat/market-picture`
  against the spec and this plan; Critical/Important findings are fixed in one Sonnet pass (one
  commit, logged); then superpowers:finishing-a-development-branch. Ask the operator before merging
  or pushing, and remind them to restart `./ibkr` (trading service first).

---

## Self-review (plan author, 2026-10-20; revised 2026-10-21)

- **Spec coverage:** §4 → Tasks 1–2 (decision 36 → rulings 39–41); §5 → 3–4 (decision 31 → ruling
  34, decision 32 → ruling 35); §6 → 5–6 (decision 35 → ruling 37); §6b → 7 (decision 39 → ruling
  42); §7 → 8–9, 11; §8 → 10 (ruling 46); §9 readers → 12–13, cut → 14 (decision 33 → ruling 36);
  §10 → 4, 15 (decision 38 → rulings 44–45); §11 → 21–22; §12 constraints → Global Constraints +
  Task 15 fences; §13 token budget → measured by the operator after restart
  (`scripts.claude_usage`), noted in Task 23's STATUS entry; §14 evidence → Task 7 replay (ruling
  38: a hard gate); §16 dossier → 17–19, 21–22 (decision 37 → ruling 43, ruling 47); §17 breakout →
  16 (decision 39 → ruling 42), event hold → withdrawn (decision 34, Task 20 stub); §18 research →
  the spec only (no code); §19 → the Progress-log "Plan revised" row and Task 7's comparison;
  decisions 1–39 each map to a task or a withdrawal.
- **Deliberately not in this plan:** the `close:delta_missing` fix (spec §14: separate); held-stock
  risk; per-call "last ran" on tiles (decision 19); any Claude power over covered calls (decisions
  30, 34); dossiers for the spreads book's underlyings; a cap on first lots opened before any signal
  beyond the per-trade and leveraged ceilings (spec §19: SOXL 130P).
- **Type consistency:** `MarketRegime`, `SizingContext`, `SizingNote`, `ScaleInZone`,
  `RegimeState`, `MarketPicture`, `claude_cut`, `cut_applies`, `per_trade_cap`, `leverage_tier`,
  `name_triggers`, `ceiling_kind`,
  `floor_left`, `scale_in_reason`, `loss_exit_reason`, `near_money_short_put`, `recovered(after=)`,
  `build_sizing_context`, `record_action(key=)`, `CcBreakout`, `cc_timing_reasons`,
  `TickerDossier`, `DossierEvent`, `prose_key` are named identically in every task that uses them.
- **Revision check (2026-10-21):** no task still references `CcHold`, `claude_cc_hold`,
  `cc_holds`, `/ccholds`, `itm_put`, `prose_max_age_hours` or a 0.20 delta guard except the
  withdrawn rulings and the Task 20 stub that names them as forbidden.
