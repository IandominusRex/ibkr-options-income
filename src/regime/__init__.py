"""The market regime at run time: refreshing it, and handing it to the sizer and the gate.

Deterministic tier (it feeds `src/engine/` and `src/strategies/`): nothing here imports
`src.claude`, `src.news`, `src.spreads_ai` or the enrichment analytics (macro, sentiment,
sector context). The pure classifier lives in `src/analytics/regime.py`; the persisted state in
`src/storage/regime_state.py`; the limits in `src/engine/regime_limits.py`.
"""
