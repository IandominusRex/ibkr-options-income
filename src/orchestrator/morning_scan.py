"""ONE-SHOT morning scan orchestrator — runs the full pipeline and sends results to Telegram.

Connects to IBKR, fetches live data, generates CC/CSP/buy candidates, runs Claude review,
and sends everything to Telegram with Approve/Reject buttons.

Usage:
    python -m scripts.run_morning [--dry-run]
    # or: python -m src.orchestrator.morning_scan
"""

from __future__ import annotations

import asyncio
import logging

from ib_async import IB

from src.common.config import Config, get_config
from src.orchestrator.scan import run_scan
from src.storage.db import init_db

logger = logging.getLogger(__name__)


def _log_startup_banner(cfg: Config) -> None:
    """Emit a loud mode banner so log tails make live vs paper status unambiguous."""
    mode = "*** LIVE TRADING ***" if cfg.is_live else "paper"
    logger.warning("=" * 60)
    logger.warning("  MODE: %s", mode)
    logger.warning(
        "  Account: %s  Port: %d", cfg.secrets.ibkr_account or "(not set)", cfg.ibkr_port
    )
    logger.warning("=" * 60)


async def _run(dry_run: bool = False) -> None:
    init_db()
    cfg = get_config()
    _log_startup_banner(cfg)
    logger.info(
        "Morning scan starting — account=%s live=%s dry_run=%s",
        cfg.secrets.ibkr_account or "(not set)",
        cfg.is_live,
        dry_run,
    )

    if dry_run:
        logger.info("DRY RUN — pipeline skipped; no IBKR connection or Telegram messages")
        return

    ib = IB()
    try:
        await ib.connectAsync(
            cfg.ibkr.host,
            cfg.ibkr_port,
            clientId=cfg.ibkr.client_ids.get("engine", 11),
            timeout=cfg.ibkr.connect_timeout_seconds,
        )
    except Exception:
        logger.exception("Could not connect to IBKR — morning scan aborted")
        return

    try:
        result = await run_scan(ib, bot=None, chat_id=cfg.secrets.telegram_chat_id or "")
        logger.info(
            "Morning scan complete — CC=%d CSP=%d buy=%d reviews=%d",
            len(result.cc_candidates),
            len(result.csp_candidates),
            len(result.buy_candidates),
            len(result.reviews),
        )
    finally:
        ib.disconnect()


def main(dry_run: bool = False) -> None:
    from src.common.logging import setup_logging
    setup_logging()
    asyncio.run(_run(dry_run=dry_run))


if __name__ == "__main__":
    main()
