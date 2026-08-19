"""Data abstraction layer (`src/data/`).

A thin provider abstraction between the analytics layer and the external market-data
backends (yfinance today; FMP/Polygon later). Analytics/strategies/engine never call
``yfinance.*`` directly — they go through the factories in :mod:`src.data.factory`,
which read ``config/settings.yaml → data.*`` to pick the active backend and cache the
instance process-wide.

IBKR is *not* a "provider" here — it is the broker + execution path and stays untouched
(see ``src/ibkr/``). This layer abstracts only the keyless external reads (prices,
fundamentals, news headlines) that the enrichment/deterministic analytics tiers share.

See :mod:`src.data.protocols` for the ``Protocol`` classes every backend must implement,
:mod:`src.data.yfinance_backend` for the active backend (literally the existing yfinance
calls wrapped in a class — no behaviour change), and :mod:`src.data.fmp_backend` for the
documented-but-unwired swap path.
"""
