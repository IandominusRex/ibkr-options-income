"""Structured logging setup. Writes to both console (colourised) and a rotating file (plain).

Secrets must never be passed to the logger. Format keeps lines greppable.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys

from src.common.config import ROOT, get_config

_CONFIGURED = False

# ── ANSI colour codes ────────────────────────────────────────────────────────
_RESET = "\033[0m"
_DIM   = "\033[2m"

_LEVEL_STYLES: dict[int, str] = {
    logging.DEBUG:    "\033[36m",    # cyan
    logging.INFO:     "\033[32m",    # green
    logging.WARNING:  "\033[33m",    # yellow
    logging.ERROR:    "\033[31m",    # red
    logging.CRITICAL: "\033[1;31m",  # bold red
}


class _ColourFormatter(logging.Formatter):
    """Console formatter: coloured level + dim timestamp, plain text for the file handler."""

    def format(self, record: logging.LogRecord) -> str:
        colour = _LEVEL_STYLES.get(record.levelno, "")
        ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        msg = record.getMessage()
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        return (
            f"{_DIM}{ts}{_RESET}"
            f"  {colour}{record.levelname:<8}{_RESET}"
            f"  {_DIM}{record.name}{_RESET}"
            f"  {msg}"
        )


def setup_logging() -> None:
    """Idempotent root-logger configuration driven by settings.yaml."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    # Enable ANSI escape codes on Windows 10+
    if os.name == "nt":
        os.system("")

    cfg = get_config()
    level = getattr(logging, cfg.logging.level.upper(), logging.INFO)

    log_path = ROOT / cfg.logging.file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # Console — colourised
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(_ColourFormatter())
    root.addHandler(console)

    # File — plain text for grep-friendliness
    plain_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(plain_fmt)
    root.addHandler(file_handler)

    # Quiet noisy third-party loggers unless we are in DEBUG
    if level > logging.DEBUG:
        for noisy in ("ib_async", "httpx", "telegram", "apscheduler"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
