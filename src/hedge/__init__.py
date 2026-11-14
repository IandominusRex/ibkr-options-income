"""The index-hedge package (risk-envelope plan Tasks 16 and 33-37; spec §3.10).

Deterministic tier, its own tables, its own fence (``tests/test_hedge_fence.py``): it imports no
enrichment (``src.claude``, ``src.news``, ``src.spreads_ai``, ``src.value_ai`` and the sentiment,
sector and market-conditions analytics) and is the only package that constructs ``hedge_*`` rows.
Task 16 builds the capture only: the menu (``menu``), its quote capture (``capture``) and the
store (``store``). There is no order path here.
"""
