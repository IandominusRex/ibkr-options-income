"""Claude as the value book's analyst (docs/superpowers/specs/2026-10-28-value-swing-book-design.md §8).

Enrichment only. It gathers news context, prompts ``claude -p`` through ``src.claude.cli`` (slim,
from a workdir outside the repo) and returns plain data: a verdict and valuation drivers per
list, prose, kill-trigger picks, a review state and proposed facts. It never imports
``src.value``, the trading path, ``src.notify``, ``src.ledger`` or ``src.storage``, and it writes
nothing: ``src/value/`` bounds, computes, clamps, verifies and stores every number.
``scripts/run_value.py`` is the only module that imports this package (tests/test_value_fence.py).
"""
