"""Run the research ingestion worker.

    python -m scripts.run_research_worker

Holds no IBKR connection and no clientId. Writes only to data/research.db.
"""

from __future__ import annotations

import signal
import threading

from src.common.logging import setup_logging
from src.research.ingest.jobs import build_scheduler, run_job
from src.research.ingest.symbols import refresh_symbol_directory
from src.research.store.session import init_research_db


def main() -> None:
    setup_logging()
    init_research_db()

    # Populate the directory on first start so search works immediately.
    run_job("symbols", refresh_symbol_directory)

    sched = build_scheduler()
    sched.start()

    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    stop.wait()
    sched.shutdown(wait=False)


if __name__ == "__main__":
    main()
