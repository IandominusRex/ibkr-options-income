"""Run the web API.

    python -m scripts.run_api

Holds no IBKR connection and no clientId. Bound to config/research.yaml -> api.host,
which is loopback by default.
"""

from __future__ import annotations

import uvicorn

from src.common.config import get_config
from src.common.logging import setup_logging
from src.research.store.session import init_research_db


def main() -> None:
    setup_logging()
    init_research_db()
    cfg = get_config()
    uvicorn.run(
        "src.api.main:create_app",
        factory=True,
        host=cfg.research.api.host,
        port=cfg.research.api.port,
        log_level=cfg.logging.level.lower(),
    )


if __name__ == "__main__":
    main()
