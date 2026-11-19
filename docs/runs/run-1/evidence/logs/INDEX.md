# Run 1 log excerpts

Curated, scrubbed excerpts of `logs/` for the run record `../../README.md`. Each file starts with a header naming its source file, line ranges, why it matters and the record section it supports. They hold every log line the record cites, with context. Everything else in `logs/` (241 MB, mostly scan noise) is Tier 2: gzip copies of every file on the operator's machine at `data/runs/run-1/logs/` (see `../README.md`). Line numbers in these files are line numbers in the raw files at capture; the raw files are append-only, so they stay valid in the gzip copies.

**Scrubbing.** ANSI colour removed; the paper account number replaced by `DU-PAPER`; Telegram tokens, chat and thread ids, API keys, the IBC user and password arguments (the file `launchd-gateway.log` prints the IBC start command line) and addresses removed; lines over 420 characters cut with a marker. Several raw log files hold the account number (`approval.log`, `monitor.log`, `eod.log`, `eod_rerun.log`, `spreads.log`, `system.log.4`, `system.log.5`, `value.log`, `test.log*`); they are not committed.

**Clock.** Log timestamps are the machine's local clock, UTC+8. Subtract 8 hours for UTC; ET is UTC-5 in November. The record's "Z" times are already converted.

| File | Source | What it shows | Record |
|---|---|---|---|
| `01-breaker-trips-oct12-nov17.log` | approval.log | all 17 `Circuit breaker tripped` lines (15 trips, 14 sessions) with the account read and the kill-switch release before and after, including the Oct 12 SGD/USD phantom trip | §3.3, §8 L2, N3 |
| `02-oct12-phantom-drawdown.log` | approval.log | the Oct 12 phantom trip in full: `NetLiq=786836.87 USD (from SGD at 1.28051 SGD/USD)` against a stored SGD high-water mark; released by `/resume`, tripped again | §9, §2 |
| `03-hims-error-103-oct23.log` | approval.log, monitor.log | roll order 159, `Error 103, reqId 1020: Duplicate order id`, order 160 filled, the first order's legs booked by the live feed at 23:18-23:34 local, the reconciler's `recovered fill for order_id=159 qty=3`; the Oct 30 `assign:roll_limit_reached` decision | §9, §8 L10 |
| `04-nov10-spreads-phantom-close.log` | spreads.log | the unfilled profit-take close, `cancel_unconfirmed`, late fills, entries blocked, the Nov 11-12 "expired but spreads.db still holds it open" warnings | §9, §4.5 |
| `05-usage-limit-refusals.log` | news.log, monitor.log, approval.log, eod.log | all 45 `usage limit reached - not retrying` lines: Oct 30, Nov 5, Nov 17-18 | §7, §9 |
| `06-nov18-competing-session-10197-and-gateway-restart.log` | approval.log, monitor.log, launchd-gateway.log | Error 10197 at 18:35:38Z and 18:46:40Z, both scans BLOCKED, the watchdog's Gateway restart at 18:35:44Z, reconnects at 18:36:00Z; monitor.log's first 10197 at 18:30:31Z | §9, §2 |
| `07-liquidation-window-nov18.log` | approval.log, monitor.log, launchd-supervisor.log | `/halt` 18:52:03Z, daemons stopped 18:53:15Z, restarted 19:01:24Z on `4121b2d`, the reconciler's 7 manual put closes, the ledger sweep, the first flat account reads | §6.2, §6.3, §2 |
| `08-nov18-envelope-merge-and-restarts.log` | launchd-supervisor.log, approval.log | the 12:30Z restart onto the envelope, an unlisted 14:20Z restart, the first envelope snapshot lines | §2, §10 |
| `09-stale-daemons.log` | launchd-supervisor.log | the Oct 14 21:22-21:23 restart; the Nov 16 stale process (SIGTERM, then SIGKILL) | §9 |
| `10-dormant-gap-jun-aug.log` | approval.log | lines 390912 and 390913 are consecutive: Jun 26 01:25:37 then Aug 12 23:55:41 | §1, §2, N1 |
| `11-autonomy-full-first-orders.log` | approval.log | Jun 24 order 42 after `Button approve for approval_id=9` in MANUAL mode; the first `autonomy=full` scan (Sep 30 21:36:26) and the first autonomous orders | §1, §2, N5 |
| `12-gateway-outage-oct24-26.log` | watchdog.log, approval.log | `gateway_port ok=False` from Oct 24 10:00:06 to Oct 26 13:58:31, healthy again 14:03:50 | §2, §12 |
| `13-value-book-gross-cap-refusals.log` | value.log | the value book's `refused at send time: halted, gross_notional_cap` lines | §4.7, L1 |
| `14-error-10197-by-date.md` | approval.log, monitor.log, spreads.log | line counts of Error 10197 per local date since Oct 8 | §9 |
| `20-git-commits-cited.md` | git | subject, date and body of the 24 commits the record cites by hash | §2, §8, front matter |
| `21-config-and-prompt-at-boundary.md` | private config, git | the config keys and the prompt rubric the record quotes | §7, §8 L5 L12, §10 |

## Cited by the record but not backed by an excerpt here

These are in the record but have no log line or extract in this folder. Each is either a database fact already in `../data/` or something these files cannot show.

- The liquidation orders and how they were sent (TWS, order type): the wheel logs nothing for orders typed into TWS; the booked rows are `../data/broker_executions.csv` ids 316-354.
- Who closed the 18 `campaigns` rows at 19:17:21Z: no log line; `../data/campaigns.csv` `updated_at` shows when.
- The Oct 14 stale feature branch and the 10-year-yield error (record §9 "Stale daemons" (1), (2)): the checkout's branch at the time is not in the logs; the yield text was prompt content, not a logged line. Only the fix `353cdd8` is in `20-git-commits-cited.md`.
- The implausible-IV flag "has flagged nothing" (`cd59708`): no log line says so (`grep -c implausible logs/approval.log` is 0); the commit text is in `20-git-commits-cited.md`.
- The IBC credentials visible in `ps` (record §9): by design no value was read or recorded; nothing to excerpt.
- Benchmark total returns for JEPI, JEPQ, XYLD, QYLD and SVOL, and the 5-minute SPY/QQQ/SMH bars on Nov 18: yfinance [W], not in any database or log here (`../data/benchmark_closes.csv` holds the stored SPY, QQQ, SMH and SOXX price-return closes only).
- The realised-beta and attribution computations (§3.3, §5): the inputs are all here (`nlv_portfolio_snapshots.csv`, `benchmark_closes.csv`, `broker_executions.csv`, `position_snapshots_daily.csv`); the short scripts the record ran over them were not saved.
