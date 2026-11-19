# Commits the record cites (subject, date, body)

Source: `git log -1 --format=... <sha>` in the repository. Author names and addresses are not copied. Dates are the commit date, local (UTC+8).
Supports: README front matter `rule_set`, section 2 timeline, section 8 fixes. Range 959b7a1..4121b2d is 878 commits (`git rev-list --count 959b7a1..4121b2d`); no commit dated July 2026 (`git log --since=2026-07-01 --until=2026-08-01` prints nothing).

### 959b7a1  2026-06-22 15:57:07 +0800
Add Ollama backend probe to startup and healthcheck

The system never starts Ollama itself — it only POSTs to localhost:11434.
Previously a down/unpulled local model failed silently: the circuit breaker
just degraded to the deterministic-only path with a WARNING buried in logs.

Add ollama_runner.probe_ollama() — a cheap GET /api/tags reachability +
configured-model check (returns (ok, message), never raises). Wire it into:
- scripts.start: logs a loud WARNING on launch if the model is unreachable/
  unpulled. Fail-soft — daemons still start, enrichment is skipped.
- scripts.healthcheck: prints an "Ollama backend : OK/WARN" line (never fatal).

Only runs when claude.backend uses Ollama. Docs updated (ARCHITECTURE, SETUP,
STATUS); 4 new tests (859 pass).

Co-Authored-By: Claude Opus 4.8 <[email]>

### 0d3e702  2026-09-09 21:59:18 +0800
feat(monitor): write portfolio snapshots on the refresh cadence, RTH-only, never blocking alerts

### 94415ec  2026-09-23 21:42:59 +0800
feat(risk): widen CSP delta band, split ideal-zone put/call multipliers, raise large-position slots to 2

- cash_secured_put.delta_min/delta_max: 0.15/0.30 -> 0.20/0.35, matching the covered-call
  band, for more premium at the cost of a higher assignment rate (deliberate, since CSPs
  only screen the would_own allowlist already).
- ideal_zone.em_lo_mult split into em_lo_mult_call (0.30) and em_lo_mult_put (0.18): puts
  and calls don't map to the same sigma distance at equal delta, so a single shared inner-
  edge floor couldn't admit the widened put range without also letting a ~0.46-delta
  covered call register as "in zone" (test_ideal_call_band_never_endorses_an_at_the_money_
  write). Display/ranking-only (zone_fit ships at 0.0); doesn't touch the real gate.
- portfolio.max_large_positions: 1 -> 2, so two names may be a deliberate oversized bet at
  once (each still capped at max_pct_per_ticker_large individually).

Updated the reject-reason text for large_position_slot_full to be count-agnostic, and
brought README/ARCHITECTURE/SETUP/STATUS and the web GatePanel explainer in line with all
three changes. Full suite (2267 tests), ruff, mypy, and web vitest all green.

Co-Authored-By: Claude Sonnet 5 <[email]>

### 920dd7e  2026-09-30 04:38:40 +0800
feat(autonomy): paper-only promotion-gate override and ./ibkr autonomy; run paper on FULL

Co-Authored-By: Claude Opus 5.5 <[email]>

### 099fd0a  2026-10-09 23:31:02 +0800
fix(portfolio): report the account snapshot in USD, not the base currency

accountSummary reports NetLiquidation/AvailableFunds/ExcessLiquidity in the
account's base currency. On this SGD-base paper account the wheel read them as
USD, so every %-of-net-liq limit and the circuit breaker's mark-loss % were
measured against S$1.02M as if it were US$1.02M (~28% looser than configured).

_build_account_snapshot now divides by the account stream's USD rate
(ExchangeRate or $LEDGER-ExchangeRate), reuses the last rate seen if the stream
briefly has none, and raises AccountCurrencyError rather than pass a base figure
off as USD. Live: NetLiq US$795,856 vs IBKR's own USD figure US$795,820.

Co-Authored-By: Claude Opus 5.5 <[email]>

### 14cbf9a  2026-10-13 14:26:30 +0800
fix(wheel): USD high-water mark; a breaker halt can no longer hide

The drawdown breaker compared US$786,836 net liq against the S$1,044,124
high-water mark stored before 099fd0a made net liq USD: a 24.6% phantom
drawdown halted every new-entry scan on 2026-10-12. The mark now lives under
nlv_high_water_mark_usd and re-seeds from USD; the old row is never read.

The halt was also invisible: each cycle posted 'Scan started' before the
halt check skipped the scan, the alert went to the main chat only, and the
watchdog's scan_loop check is quiet while halted. A halted cycle now posts
'Scan skipped — execution halted: <reason>', the breaker alerts the scan
thread too, set_halted records its source (operator | breaker), and a new
watchdog 'halt' check re-alerts in RTH while a breaker halt stands.

Co-Authored-By: Claude Opus 5.5 <[email]>
Claude-Session: https://claude.ai/code/session_018VBnCVdA5ojoDiryoZjkaM

### e136547  2026-10-12 11:46:49 +0800
test(spreads): pin --day to the requested main mode (Opus re-review)

Co-Authored-By: Claude Opus 5.5 <[email]>
Claude-Session: https://claude.ai/code/session_018VBnCVdA5ojoDiryoZjkaM

### 4be3078  2026-10-15 00:47:09 +0800
fix(execution): /resume acknowledges a breaker halt; rolls run through it; roll-mode setting

The daily-loss breaker re-measured the same loss against the same baseline 30s after
/resume and halted again. /resume on a breaker halt now records the loss/drawdown level
the operator resumed through (system_settings.breaker_ack, one ET day); the breaker needs a
further full threshold to trip again. The mark-to-market measure now counts what today's
close: fills realized instead of dropping a closed position's unrealized from the sum.

A circuit-breaker halt no longer blocks rolls: process_queued_orders runs a rolls-only pass
and may_auto_roll ignores a breaker halt (an operator /halt still blocks them).

New set_roll_mode command (auto | propose) with a RollModeControl beside AutonomyControl
in the web controls strip and Bot sheet; GET /options/controls returns roll_mode.

Co-Authored-By: Claude Sonnet 5.5 <[email]>
Claude-Session: https://claude.ai/code/session_01UgAibG86qMyDmtDwkHKhGp

### 35052ef  2026-10-15 23:44:21 +0800
perf(claude): slim headless claude -p calls (~40K -> ~1K tokens), fewer calls, usage report

Run from the repo with everything loaded, every claude -p call carried ~40K tokens of
Claude Code ambient context (skills, CLAUDE.md, MCP tools, hooks, tool definitions) around a
0.5K-10K prompt: 3.27M context tokens in a week, the 5-hour session limit hit three times.

- cli.build_cmd is the one headless command builder (runner + spreads picker): -p, strict MCP,
  no skills, --setting-sources project, no tools, short system prompt, no transcript.
  claude.slim_context=false restores the old command (kill switch). Calls run from
  claude.workdir (~/.cache/ibkr-claude), validated absolute and outside the repo.
  Measured on CLI 2.1.295: trivial call 37.7K -> 0.6K; real roll 40K -> 1.2K, news 41K -> 2.2K,
  AVGO scan review 48K -> 6.1K, all parsed with the same recommendation.
- Model per call kind (claude.review_model/roll_model/eod_model, "" = claude.model). Haiku was
  audited (blinded, 8 scan + 18 news) and NOT adopted: it understated risk in 8/8 scan reviews
  and once quoted collateral 5x too low. Defaults stay on Sonnet; the audit is in STATUS.md.
- Roll/assignment-risk info alerts no longer call Claude (claude.review_info_alerts=false); a
  strike breach used to fire that alert and the decision card, two calls in a minute.
- Scan prompt history is limited to the reviewed tickers (was 48% of an AVGO prompt, 0 AVGO rows).
- Review reuse: coarse fingerprint + bounded log of recent fresh reviews with a TTL
  (claude.review_reuse_minutes=120), replacing a full-precision single-cycle hash that any tick
  defeated (10 contracts reviewed 2-4 times in a week).
- A usage-limit reply is detected from its envelope (api_error usage_limit_reached / 429) and
  not retried.
- Per-call "claude usage:" log line and scripts/claude_usage.py (totals by call kind, deduped
  across system.log and per-process logs).

Full suite 3836 passed, 1 skipped; ruff and mypy clean.

Co-Authored-By: Claude Sonnet 5.5 <[email]>

### cf379c6  2026-10-14 15:05:34 +0800
feat(roll): leveraged ETFs roll; the loss line rolls before it closes; rolls run on FULL autonomy

Operator rulings 2026-10-14:
- Leveraged ETFs follow the normal roll tree (roll for a credit, else assign) instead of
  'never roll'. The monitor no longer short-circuits them to hold.
- Prefer rolling over closing in a loss: the leveraged 2x loss line asks evaluate_roll
  (on_no_roll='close') for a roll first and buys back only when none qualifies, the Rules
  Engine refuses it, it was rejected/expired, or a roll order for the short failed today.
  A put on a name we would not own also rolls when it can, closing only when it cannot.
- On FULL autonomy a gated roll is written APPROVED + QUEUED (same shape as the entry
  auto-queue); process_queued_orders and execute_roll still re-gate it. The card says
  so and carries no buttons.
- Rolls are exempt from the daily new-entry cap (same size, no new exposure).

Co-Authored-By: Claude Opus 5.5 <[email]>
Claude-Session: https://claude.ai/code/session_018VBnCVdA5ojoDiryoZjkaM

### ee87286  2026-10-22 21:16:53 +0800
Merge branch 'feat/market-picture': market regime sizing, scale-in ladder, news expert (triage, picture, noise check), Claude's reduce-only size cut, CC breakout rule, ticker dossiers, What Claude knows page

Built 2026-10-21/22 from docs/superpowers/plans/2026-10-20-market-picture.md (31 commits, Sections A-G, the open-items passes and the whole-branch review fixes). Offline-tested only: nothing has run against real IBKR, Telegram, claude -p or the operator's databases. Restart order: trading service, news, API.

Co-Authored-By: Claude Sonnet 5.5 <[email]>
Claude-Session: https://claude.ai/code/session_01LVHqY8R1KcRxqr7uK2U49d

### 353cdd8  2026-10-27 23:48:36 +0800
feat(web,news): sizing record on the Claude page, market card; fix 10y yield quote scale

- /claude/sizing endpoint and the web MarketCard, NameNotes and HeldBack views
- ^TNX is now quoted directly (4.98), no longer x10: the market picture told Claude the
  10-year was 0.50% (tnx_divisor); picture and market_conditions share the scale check
- web overhaul part 3 (portfolio + activity) plan; docs and OpenAPI regenerated

Co-Authored-By: Claude Sonnet 5.5 <[email]>

### f79efbd  2026-11-04 17:36:15 +0800
feat(engine): the Rules Engine counts the value book; the capital-release gate

E1-E3 of the plan's rulings (operator-approved 2026-11-04): resolve_caps takes the value claim off excess liquidity, seed_budgets counts value stock per name, the gate refuses book_attribution_mismatch, value_book_unreadable, gross_notional_cap and combined_name_cap (all only with value.book.enabled), the sizer and the regime fit pass the same numbers; pure ReleaseCandidate, release_reasons, select_releases and risk_ [... +64 chars cut]

Co-Authored-By: Claude Opus 5.5 <[email]>
Claude-Session: https://claude.ai/code/session_014u3WhSjv7z3JyxyiPUfAYB

### 544e32e  2026-11-05 21:09:29 +0800
fix: rolling 3-session drawdown breaker, range-aware hero change, spreads card health

- Drawdown breaker measured from an all-time peak, so a standing drawdown re-halted new
  entries every ET morning (the /resume ack lapsed at midnight). It now uses the highest
  net liquidation of the last automation.drawdown_window_days (3) sessions, drawdown_halt_pct
  ships at 6.0, and a drawdown /resume holds for the window. The 3% daily-loss line still
  covers one bad day.
- AccountValueSeries gains change/change_pct/change_since so the Home hero's change follows
  the range chip and no longer reads n/a on weekends; change_today* keep their meaning.
- Spreads day card shows updated-at, GEX map health and trades-assessed lines, re-stamped
  every 5 minutes; the separate map outage/recovery posts are folded into the card.

Co-Authored-By: Claude Sonnet 5.5 <[email]>

### 9da9e8a  2026-11-12 16:04:45 +0800
fix: spreads late fills, regime flapping and notice bursts, roll noise and the ITM roll-down rule

- spreads: keep watching an order whose cancel went unconfirmed and book its late fills
  (Nov 10: a 2-lot phantom blocked entries for two sessions); URGENT/time-stop alerts count only
  today's expiry and fire only before the bell
- regime: the bottoming signal holds for the session; queued notices are netted into one
  message per batch; easing may go up to ease_max_notches (3) toward the day's reading
- rolls: one decision card per short per action per day; an assign/hold answer stands for the
  day; no breach/delta/loss info alerts on a short under a decision; no-roll answer after
  roll.exec.max_attempts_per_day unfilled roll orders
- ITM put rolls must roll down for a credit and cut the assignment cost by
  roll.csp.itm_min_basis_drop_pct (operator ruling 2026-11-12), checked by the constructor and
  the Rules Engine

Co-Authored-By: Claude Opus 5.5 <[email]>

### cb55ddd  2026-11-15 00:26:56 +0800
fix(engine): no reason erased by a floor lot; U_ew replaces the nominal gross check

Risk-envelope plan Task 18 (P4, Q3, C1, spec 3.4.2, 3.5). The value
book's combined_name_cap and the envelope reasons are appended after the
regime rewrite and the guaranteed-floor clear. validate_candidates takes
envelope=(room, inputs) and tests every opening CSP with envelope.admits
(on refuses, record writes sizing_actions envelope_record, off nothing);
the wheel no longer reads max_gross_notional_pct. A leveraged ETF's
exposure counts at leverage in the per-ticker and CSP budgets.

Co-Authored-By: Claude Opus 5.5 <[email]>

### f449267  2026-11-14 18:43:15 +0800
feat(spreads): shadow until the backtest bar passes; the harness on the cost standard

Risk-envelope Task 7 (spec 3.2 g, h; rulings E1, P8). mode: paper trades paper only while
the data-gated switch spreads_paper is on; otherwise the service trades the shadow book,
says so on the day card, and winds down any paper spread still open with a closes-only
executor. The backtest sizes at the live shares of --nlv, fills on the cost standard,
and --report writes the P8 paper bar to data/envelope_reports/spreads_paper.json.

Co-Authored-By: Claude Opus 5.5 <[email]>

### 465ff29  2026-11-14 19:05:17 +0800
feat(regime): no leveraged CSP outside the drawdown sleeve

leveraged_sizing.csp_mode ships drawdown_only: per_trade_cap is 0 for a leveraged ETF unless
regime_limits.sleeve_lot (a stub until Task 23) holds; vrp_waiver is False for a leveraged
name. csp_mode: normal restores decision 32. Existing leveraged-floor tests now run under
normal mode.

Co-Authored-By: Claude Sonnet 5.5 <[email]>

### 75af220  2026-11-14 23:09:54 +0800
feat(envelope): the daily line, the manual-buy line and GET /envelope

Risk-envelope plan Task 14. The EOD report ends with a Risk envelope block
(S10 gross/net beside L(t), S20, G10, P20, T20, S-SMH, U_ew, cash after every
ITM put is assigned, stored IV labelled) and the two LES lines. A manual TWS
stock buy posts S10 and U_ew before and after with tomorrow's headroom, once
per execution, from a loop on the ledger sweep's cadence in approval_service.
GET /envelope (owner, read-only) serves the latest snapshots, limits, glide,
switches and LES. openapi.json and api-types.ts regenerated.

Co-Authored-By: Claude Opus 5.5 <[email]>

### cd59708  2026-11-14 19:21:32 +0800
feat(data): flag implausible IV observations; every reader skips them

append_observation marks an IV row flagged when an index ETF's ratio to its vol index (SPY vs
^VIX, QQQ and TQQQ vs ^VXN) or a single name's IV leaves its band against its own median; the row is
kept, a data alert goes out once per symbol per day, and every iv_history reader (IV rank, strike
band, staleness, the API, the backtest) skips flagged rows. A structural test scans src/ for a
reader that does not. The EOD run appends the reference closes just before the IV capture.

Co-Authored-By: Claude Sonnet 5.5 <[email]>

### 488c315  2026-11-18 20:04:43 +0800
fix(reporting): the capacity report uses the slow breaker's CSP fraction

scripts/capacity_report.py resolved the caps unscaled, so it showed the full
budget while the breaker was tripped. (The bridge roll's cost multiplier, the
other review minor, landed with fix 1's commit.)

Co-Authored-By: Claude Sonnet 5.5 <[email]>

### 2f40cd0  2026-11-18 20:11:59 +0800
docs(plan): review fixes logged

Co-Authored-By: Claude Sonnet 5.5 <[email]>

### b9d8243  2026-11-18 22:04:24 +0800
config: the Nasdaq-100 constituent list for the breadth count

101 tickers from Nasdaq's NDX weightings export (2026-11-17), cross-checked against Invesco's QQQ holdings: no differences. Operator to-do 12.

Co-Authored-By: Claude Sonnet 5.5 <[email]>

### 4121b2d  2026-11-19 02:43:12 +0800
fix(envelope): betas cover the put universe, so a put on a name not held is measured

build_inputs read betas only for the names in the book, so a candidate put on any other
name (AVGO, META, QQQ, SMH ...) measured as unmeasured and envelope_enforce on would have
refused it envelope_unmeasured (69 of the first 96 record-mode rows).

Co-Authored-By: Claude Sonnet 5.5 <[email]>
Claude-Session: https://claude.ai/code/session_014u3WhTPut4NEKkyVzMz1Ap
