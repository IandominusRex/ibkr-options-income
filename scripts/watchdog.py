"""One-shot health check — run by launchd/cron every ``watchdog.interval_seconds``
(config/settings.yaml), never by the trading stack's own supervisor (scripts/start.py):
the whole point is to keep working when everything else has stopped. See
``src/ops/watchdog.py`` for the checks and the alert state machine.

Usage:
    python -m scripts.watchdog
"""

from __future__ import annotations

from src.common.logging import setup_logging
from src.ops.watchdog import main

if __name__ == "__main__":
    setup_logging()
    raise SystemExit(main())
