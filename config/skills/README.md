# Reasoning skills

Markdown playbooks that sharpen how Claude forms its **verdict (sell/wait/skip)** and
**ranking** — learned from the outcome ledger. A skill is prose, not code.

## The fence (non-negotiable)

Skills influence **verdict and ranking only**. They never change risk gates, scoring weights,
or position sizing — those live in `config/risk_limits.yaml` and `config/scoring_weights.yaml`
and are **human-edited config**. A skill that tries to set a delta cap, DTE, IV threshold, or
size is out of scope; rewrite it as reasoning guidance or reject it. This is enforced by a test
(`tests/test_eval_skills.py::test_skills_never_reach_the_engine`).

## Loop

1. **Propose** — `python -m scripts.propose_skill` reads the labeled ledger + current
   evaluation and drafts one skill into `proposed/`.
2. **Review** — `python -m scripts.skills show <name>`. Read the rationale and supporting stats.
3. **Promote** — `python -m scripts.skills promote <name>` moves it to `active/`. Only
   `active/` skills are injected into the strategist/roll prompts.
4. **Retire / reject** — `retire` returns an active skill to `proposed/`; `reject` archives a
   draft to `rejected/`.

Promotion is deliberately a human-gated git diff. Nothing here is auto-promoted.

## File format

```markdown
---
name: prefer-positive-vrp-csp
description: On CSPs, lean to wait when VRP is negative even if IVR looks acceptable.
---

When reviewing a cash-secured put whose VRP (IV − HV30) is negative, treat the premium as
"realised-cheap" and bias the recommendation toward `wait` unless IV rank is ≥ 50 ...
```

Drafts carry extra `rationale` and `supporting_stats` frontmatter for the reviewer; the prompt
injects only `name`, `description`, and the body.

## Directories

| Dir | Meaning |
|---|---|
| `active/` | Promoted — injected into every review prompt. |
| `proposed/` | Claude-drafted, awaiting human review. |
| `rejected/` | Declined drafts, kept for provenance. |
