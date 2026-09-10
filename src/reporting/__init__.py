"""The reporting package: paired realised P&L and campaign rollups, read-only.

The third analytics tier — downstream of everything, upstream of nothing. It reads the whole
book (including enrichment-side tables) and may never be imported by `src/engine/`,
`src/execution/` or `src/strategies/`. Enforced by `tests/test_web_fence.py`.
"""
