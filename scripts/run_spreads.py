"""Daily credit-spread service entrypoint.

Usage:
    python -m scripts.run_spreads

Connects with clientId 30 (config/settings.yaml → ibkr.client_ids.spreads). Idles when
config/spreads.yaml → enabled is false; refuses to trade when LIVE_TRADING=true. Runs until
SIGINT/SIGTERM. Supervised by scripts.start like the other daemons.
"""

import asyncio
import signal

from src.common.logging import setup_logging
from src.spreads.service import run


async def _main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await run(stop)


def main() -> None:
    setup_logging()
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
