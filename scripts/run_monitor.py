"""Intraday monitor entrypoint.

Usage:
    python -m scripts.run_monitor

Connects to TWS/Gateway with clientId 12, subscribes to live position ticks,
fires roll alerts via Telegram when trigger conditions are met.
Runs until SIGINT/SIGTERM.
"""

import asyncio
import logging

from src.monitor.intraday import run


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("ib_async").setLevel(logging.WARNING)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
