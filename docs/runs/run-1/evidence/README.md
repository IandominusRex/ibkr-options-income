# Run 1 evidence

What backs `../README.md` (the Run 1 record). Two tiers:

| Tier | Where | In git? | What |
|---|---|---|---|
| 1 | this folder: [`logs/`](logs/INDEX.md), [`data/`](data/INDEX.md) | yes, scrubbed | small log excerpts, one per incident or theme, each with a source/line-range/why header; CSV extracts of the databases with their queries, row counts and columns |
| 2 | `data/runs/run-1/` on the operator's machine | **no** (git-ignored) | `logs/`: a raw, **unscrubbed** gzip copy of every file in `logs/`; `db/`: consistent `.backup` copies of `income_system.db`, `spreads.db`, `value.db`, `news.db`, `research.db` (gzipped) and `db/older-backups/`: ten older copies of `income_system.db` that hold history the live tables have since pruned; `MANIFEST.md`: every file, its size and sha256, and the capture time |

Captured 2026-11-19 (UTC 05:08), about 14 hours after the liquidation. The Tier 2 files contain the
paper account number; nothing in this folder does (`grep -rE 'DU[A-Z]?[0-9]{5,}' docs/runs` prints nothing).

The extracts' numbers reproduce the record's where the record names a query: for example the
union of the daily backups holds 171,970 distinct `risk_verdicts` rows since 2026-11-04 and 29,147
`strike_below_basis` reason lines (record L1, L8), and the usage extract sums to the record's 919
headless calls and $23.43. Where an extract disagrees with the record, `../README.md` is the record
and the difference is listed in the hand-off note, not edited into it.
