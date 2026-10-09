"""News service — macro, market and ticker news with grounded implications.

Spec: docs/superpowers/specs/2026-10-09-news-thread-design.md.

Fence (CLAUDE.md, spec §10): enrichment tier. Nothing here is importable from src/engine/,
src/execution/, src/strategies/ or src/spreads/; this package imports none of them, nor
src.orchestrator or src.notify.approval_service. data/news.db is written only from here.
"""
