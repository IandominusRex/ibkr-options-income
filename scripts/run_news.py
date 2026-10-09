"""News service entrypoint (docs/superpowers/specs/2026-10-09-news-thread-design.md).

Usage:
    python -m scripts.run_news

No IBKR connection, no clientId. Idles when config/news.yaml → enabled is false. Runs until
SIGINT/SIGTERM. Supervised by scripts.start like the other daemons.
"""

import asyncio
import signal

from src.common.logging import setup_logging
from src.news.service import run


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
