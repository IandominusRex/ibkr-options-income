"""The skill loop — Claude proposes reasoning skills from labeled history, a human promotes
them, and promoted skills are injected into the strategist/roll prompts.

A "skill" is a small markdown playbook (frontmatter + body) that sharpens how Claude reasons
and ranks — e.g. "on CSPs, demand IVR ≥ 40 unless VRP is strongly positive." It is NOT code,
NOT a gate, NOT a weight. The promotion gate is human by design: Claude may draft and refine
skills into `config/skills/proposed/`, but only a person moves one to `config/skills/active/`,
and only active skills reach a prompt.

The fence (CLAUDE.md): skills influence verdict + ranking only. Nothing in this package is
importable from, or reachable by, the risk engine, scoring, or sizing.
"""
