"""The value book (docs/superpowers/specs/2026-10-28-value-swing-book-design.md).

Deterministic tier. Imports nothing from ``src.claude``, ``src.news``, ``src.value_ai``,
``src.spreads*``, ``src.notify``, ``src.api`` or the trading path, and from ``src.research`` only
``src.research.ingest.concepts`` and ``src.research.schemas`` (tests/test_value_fence.py).
``src/value/`` is the only writer of ``data/value.db``.
"""
