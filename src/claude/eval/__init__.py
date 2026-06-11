"""Enrichment-layer evaluation: the outcome ledger, the close reconciler, and verdict
scoring (calibration + EV vs the deterministic baseline).

This package is the *labeled history* engine behind Claude's reviews. It reads from the
SQLite backbone and produces metrics + evidence consumed by the skill loop. None of it can
gate, size, or place an order — it is observe-only by construction (see CLAUDE.md "the
fence"). The risk engine never imports anything here.
"""
