---
name: value
description: Interactive value-book analysis of one stock in this repo - a deep dive into its 10-K, the bear case, the thesis and kill triggers, a review of a held name (INTACT/WEAKENED/BROKEN), a postmortem, or a plain-English reading of its scorecard. Use when the operator types /value SYMBOL or asks what the value book thinks of a company. Interactive only; the headless value reads use src/value_ai/ instead.
---

# The value skill (value book spec §8.6)

You are helping the operator read one company the way the value book does. The numbers are
**Python's**: never compute a fair value, a margin of safety or a DCF yourself, and never
re-implement a calculator. Two valuations that disagree are worse than none.

## First, always

1. Run `python -m scripts.value_report --symbol SYMBOL --json` and read it. It holds Part 1 of the
   ticker file (the scorecard: every gate with its number and bar, each valuation method, the
   baseline verdict per list), the effective verdict per list (`decided_by` claude or python),
   and Claude's latest verdicts, notes and kill triggers, each labelled with its source.
   `"error": "no ticker file"` means the value process has not scored the name: say so, and
   suggest `python -m scripts.value_claude --read SYMBOL` once it is in a universe or looked up.
2. Read `config/value.yaml` (`rules`, `claude`) for the bars and the driver bounds. Do not ask the
   operator for anything that file answers.

## Modes

| Mode | What you do | Reference |
|---|---|---|
| `explain` (default) | A plain-English reading of the scorecard: is the business healthy (the gates), what is it worth (Python's methods and median, Claude's drivers and the 1.5x cap), how much and when (timing, the regime's margin) | `reference/reverse-dcf-reading.md`, `reference/sector-rules.md` |
| `deep-dive` | Read the newest 10-K/10-Q the operator points you at and propose facts in `reference/output-schema.json`'s `facts` shape: each with the accession and a verbatim quote containing its number | `reference/forensic-checklist.md` |
| `bear` | The strongest case against, in a short seller's voice, from the numbers in the ticker file | |
| `thesis` | What has to be true for the price to reach fair value, and up to five kill triggers from the menu, with thresholds inside their ranges | `reference/trigger-vocabulary.md` |
| `review` | For a held name after a re-evaluation: INTACT, WEAKENED or BROKEN with one line why. A headline alone changes nothing about what the company is worth | |
| `postmortem` | For a closed position: `python -m scripts.value_report --postmortems`, then which gate was closest to wrong | |

## Rules

- Health and earnings-quality gates are final: never argue a name over one.
- Anything you would save (a fact, a request for a read) goes through
  `python -m scripts.value_claude` or the value process; never open a database.
- Label everything you write as Claude's. Unknown is `n/a`, never zero.
