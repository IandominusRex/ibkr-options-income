# Runs: one record per account run

A **run** is a period of the paper or live account under one rule set, bounded by two
**run-boundary dates**. A run ends when the operator closes it (for example by liquidating the book
and restarting from cash), or when the rule set changes so much that the old statistics no longer
describe the new system. Each run gets one record here, written at the boundary and kept.

These records are for Claude Code sessions, the plan writer and, later, the Mastermind's
track-record block (`docs/superpowers/specs/2026-11-12-mastermind-design.md` §8.5). They exist so that
the next run does not rediscover what the last one cost.

## How to use a run record

1. **Lessons are evidence for a human or for the plan. They are never auto-applied.** Nothing in a
   run record may feed a gate, a weight, a size or a limit. The same fence as `src/claude/eval/`
   (root `CLAUDE.md`, "The fence"): a person reads the record and edits config by hand. No module
   under `src/engine/`, `src/execution/` or `src/strategies/` may read these files.
2. **A run's per-trade statistics were made under the rules of that run.** Run 1's closed trades ran
   with no enforced envelope, leveraged puts on, no stacking rule and a nominal gross check that
   never fired. Do not use Run 1's win rates, averages or per-name results as a prior for Run 2.
   The Mastermind shows Run 1 only as one labelled summary line, never as per-name cells (spec §8.5,
   ruling R13).
3. **Read the tags.** Every figure carries one of:
   - **[V]** verified here from the database, the logs or git, with the query or file named;
   - **[M]** a model or an approximation, with its method stated;
   - **[W]** from the web (yfinance adjusted closes), not from the account;
   - **[S]** taken from a spec and not re-derived here;
   - **[U]** could not be verified.
4. **Where a record and a spec disagree, the record says so** (run-1/README.md §12) and says which figure is
   right.
5. **No account number, credential or token goes into a record or its Tier 1 evidence.** These files are
   meant to be committable (root `CLAUDE.md`, "Conventions"). The raw logs and database copies are Tier 2,
   local only (see "Evidence" below).

## Index

| Run | Account | Starts | Ends (boundary) | Rule set | NLV start, end (USD) | Return | Record |
|---|---|---|---|---|---|---|---|
| 1 | IBKR paper | 2026-06-22 | 2026-11-18, the operator liquidated every position at 18:53 UTC | git `959b7a1..4121b2d`; the envelope merged but unenforced | 787,576; 588,867 | −25.2% (50/50 SPY/QQQ: −6.5%) | [run-1/README.md](run-1/README.md), closed; evidence in [run-1/evidence/](run-1/evidence/) |
| 2 | IBKR paper | 2026-11-18, from cash (the first flat snapshot is 19:01 UTC) | open | starts on `4121b2d`; execution halted by the operator until the halt is lifted | 588,867; open | n/a | not yet written |

Run 2 has no `run_boundary` row yet. The Mastermind spec (§6A P9) plans one, written by an operator
command that does not exist at the boundary. Until it does, the boundary is the date and time above.

## The front matter every record carries

Each `run-N/README.md` starts with a YAML block. Keep the keys stable: the Mastermind renders Run 1 as one
labelled line from it. Units are in the key names or the comments. Percentages are percent (−25.2
means −25.2%), money is USD, dates are ISO.

| Key | Meaning |
|---|---|
| `run`, `status` | the run number; `closed` or `open` |
| `start_date`, `end_date` | the boundary dates |
| `nlv_usd.start / peak / trough_close / trough_intraday / end` | net liquidation, with the date or time beside each |
| `return_pct.*` | from the start and from the peak, to the end and to the last full close |
| `max_drawdown_pct.*` | from the peak: close basis and intraday |
| `benchmarks_pct.<window>.<name>` | SPY, QQQ, a monthly-rebalanced 50/50 SPY/QQQ, SMH, JEPI, JEPQ, XYLD, QYLD (and SVOL) over the same windows, total return [W] |
| `realised_beta.*` | beta and R² of daily NLV returns to the benchmarks, with the window |
| `attribution_usd.*` | the change from the peak split by source (manual stock, wheel-assigned stock, options, spreads, residual) and the manual and system shares |
| `premium_usd.*`, `realised_put_pnl_usd.*` | premium sold and bought back, and the realised put P&L |
| `trades.*`, `assignments.*`, `exits.*` | counts, with their definitions |
| `claude.*` | what Claude's levers did, as counts and money |
| `rule_set.*` | the git commit range, the commit running at the boundary and the switch states |

An example of the one-line render, from the keys: `Run 1 (2026-06-22 to 2026-11-18), pre-envelope
rules, closed: −25.2% vs 50/50 SPY/QQQ −6.5%, max drawdown −30.1%; see docs/runs/run-1/README.md`. Build it
from the keys at render time. Do not store the string.

## Evidence: two tiers, and a run boundary always produces both

A record is only as good as what it can be checked against, and the databases prune themselves
(Run 1 lost its 15-minute snapshots before Oct 20, its risk verdicts before Nov 5 and kept 41 journal
rows in five months), so the evidence is captured at the boundary, in two tiers:

| Tier | Where | Committed? | Holds |
|---|---|---|---|
| 1 | `docs/runs/run-N/evidence/logs/` and `evidence/data/` | yes, scrubbed | small log excerpts (one `.log` or `.md` per incident or theme, each with a header naming the source file, line range or time, and why it matters; every log line the record cites, with context) and CSV extracts read with `sqlite3 "file:<db>?mode=ro"`, each with an entry in `evidence/data/INDEX.md` (file, source table, query, row count, columns). Keep the folder under about 20 MB: summarise anything larger |
| 2 | `data/runs/run-N/` | **no**, git-ignored (`data/runs/` is in `.gitignore`) | `logs/`: a gzip copy of every file in `logs/`, raw and unscrubbed. `db/`: a consistent copy of every database (`sqlite3 <src> ".backup <dest>"`, safe while the daemons run, then gzip). `MANIFEST.md`: every file with its size and sha256, and when it was captured |

Rules for both tiers:

- **Scrub everything committed.** Replace the account number (`DU[A-Z]?\d{5,}`) with `DU-PAPER`; remove
  Telegram bot tokens, chat and thread ids, API keys, the IBC user and password arguments, email
  addresses and anything that looks like a secret; drop prompt text and `account`, `raw` and
  `snapshot` columns that carry the account block. After writing, a grep of `docs/runs` for the account-number pattern, a
  `-{2}pw` credential flag, a Telegram `bot<digits>:` token and a gmail address must print nothing
  (spell the patterns so the grep does not match its own line: `grep -rE 'DU[A-Z]?[0-9]{5,}|-{2}pw|bot[0-9]+:|@gm[a]il' docs/runs`). The raw logs hold the account number and, in `launchd-gateway.log`,
  the IBC start command: they are Tier 2 only.
- **Extracts matter more than raw logs.** `portfolio_snapshots`, `risk_verdicts` and
  `envelope_snapshots` are pruned over time; take the extracts, the NLV series (journal plus
  snapshots, a converted column marked [M]), the executions, orders, fills, campaigns, sizing actions,
  approvals, the verdict ledger, the spreads metadata, the FX rates and the benchmark closes, at the
  boundary, before the next prune.
- **Never write to a live database** and never import or run a `scripts.run_*` module to capture.
  The trading services may be running (halted); read from the `.backup` copies.
- **Say what is not backed.** Each record's last section lists any claim for which there is no
  excerpt or extract, and the evidence `INDEX.md` files list it too.

## Template for the next record

Create the folder `docs/runs/run-N/` at the boundary, with its record in `run-N/README.md` (the
skeleton below) and its evidence beside it (the two tiers above). Fill the front matter from the
databases, then the sections. A section with nothing to say says so in one line. It is not deleted.
The record ends with an "Evidence" section that says what Tier 1 holds and where Tier 2 lives (copy
Run 1's).

```markdown
---
run: N
status: closed
start_date: YYYY-MM-DD
end_date: YYYY-MM-DD
nlv_usd: {start: 0, peak: 0, trough_close: 0, trough_intraday: 0, end: 0}
return_pct: {from_start: 0.0, from_peak: 0.0}
max_drawdown_pct: {from_peak_close_basis: 0.0, from_peak_intraday: 0.0}
benchmarks_pct: {start_to_end: {spy: 0.0, qqq: 0.0, spy_qqq_50_50: 0.0, smh: 0.0, jepi: 0.0, jepq: 0.0, xyld: 0.0, qyld: 0.0}}
realised_beta: {window: "...", to_qqq: 0.0, to_spy: 0.0}
attribution_usd: {total_change: 0, manual: 0, system: 0}
premium_usd: {sold_gross: 0, bought_back: 0}
realised_put_pnl_usd: {ibkr_column: 0}
trades: {...}
assignments: {...}
rule_set: {git_first: "", git_last: "", switches: {...}}
---

# Run N: <one line>

1. Summary: half a page, the verdict stated plainly
2. Timeline: account events and system changes on one dated table
3. Account curve: weekly NLV in USD beside the benchmarks, the windows, the risk measures
4. What the system traded: by underlying and book; exits; the manual book kept separate
5. Attribution of the loss (or the gain): by source, with the method stated
6. Positions at the end and the boundary: the last snapshot, the closing executions, the final NLV
7. What Claude did: facts only
8. Lessons: each with its evidence, its fix and its status at the boundary; new lessons marked NEW
9. Operational incidents
10. What the next run changes: the rules in force at the boundary
11. Open questions the next run must answer
12. Figures that differ from the specs, and what could not be verified; the queries to reproduce
```

Rules for writing one:

- State the verdict plainly and do not flatter. A record is not a narrative of blame: it names
  causes, mechanisms and fixes, not people.
- Re-verify any figure restated from a spec against the database, and say where it came from.
- Open every database read-only (`sqlite3 "file:data/income_system.db?mode=ro"`). Never import or run a
  `scripts.run_*` module to gather data: it starts a service that fights the live daemons.
- Update the index above and add the row to the root `CLAUDE.md` documentation table only the first
  time (it already points here).
- A run boundary is not complete until both evidence tiers exist, the scrub grep prints nothing and `data/runs/run-N/MANIFEST.md` is written.
