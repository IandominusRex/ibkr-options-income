"""Intraday monitor entrypoint.

Usage:
    python -m scripts.run_monitor

Connects to TWS/Gateway with clientId 12, subscribes to live position ticks,
fires roll alerts via Telegram when trigger conditions are met.
Runs until SIGINT/SIGTERM.
"""

import asyncio

from src.common.logging import setup_logging
from src.monitor.intraday import run


def main() -> None:
    setup_logging()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
