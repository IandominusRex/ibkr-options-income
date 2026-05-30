"""Structured logging setup. Writes to both console and a rotating file.

Secrets must never be passed to the logger. Format keeps lines greppable.
"""

from __future__ import annotations

import logging
import logging.handlers

from src.common.config import ROOT, get_config

_CONFIGURED = False


def setup_logging() -> None:
    """Idempotent root-logger configuration driven by settings.yaml."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    cfg = get_config()
    level = getattr(logging, cfg.logging.level.upper(), logging.INFO)

    log_path = ROOT / cfg.logging.file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # ib_async is chatty at INFO; keep it at WARNING unless we're debugging.
    if level > logging.DEBUG:
        logging.getLogger("ib_async").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
