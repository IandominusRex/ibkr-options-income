"""Structured logging setup. Writes to both console (colourised) and a rotating file (plain).

Secrets must never be passed to the logger. Format keeps lines greppable.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import re
import sys

from src.common.config import ROOT, get_config

_CONFIGURED = False

# ── ANSI colour codes ────────────────────────────────────────────────────────
_RESET = "\033[0m"
_DIM = "\033[2m"

_LEVEL_STYLES: dict[int, str] = {
    logging.DEBUG: "\033[36m",  # cyan
    logging.INFO: "\033[32m",  # green
    logging.WARNING: "\033[33m",  # yellow
    logging.ERROR: "\033[31m",  # red
    logging.CRITICAL: "\033[1;31m",  # bold red
}


class _NoiseFilter(logging.Filter):
    """Tames the IBKR error-callback flood so a /scan doesn't produce multi-MB logs.

    Two patterns from ``ib_async.wrapper`` make raw logs nearly useless during a scan:
      - some error strings grow with every duplicate callback for the same reqId
        (e.g. "...Error&BEST/OPT/Top" repeated dozens of times), producing multi-KB lines;
      - benign cleanup errors (300 "Can't find EId", 354/10091 "not subscribed") fire once
        per contract in a chain, dozens of times back-to-back.

    Long messages are truncated; runs of consecutive near-identical messages (same logger +
    first 120 chars, with reqId/tickerId digits normalised out so e.g. "Can't find EId with
    tickerId:17920" and "...tickerId:17921" compare equal) are collapsed to the first few
    occurrences plus a "(suppressed N repeats)" summary once the run ends.
    """

    _MAX_LEN = 500
    _PREFIX_LEN = 120
    _SUPPRESS_AFTER = 2
    _DIGITS = re.compile(r"\d+")
    # "Unknown contract"/"No security definition" callbacks fire once per (strike, right)
    # combo in a chain probe, alternating right='C'/'P' every other line — since that token
    # sits inside the 120-char prefix and digit-normalisation doesn't touch it, consecutive
    # call/put lines never share a key and the run-length suppression above never engages,
    # letting a single symbol's chain fetch emit hundreds of un-suppressed lines. Normalise
    # it out too so calls and puts for the same contract-shape collapse into one run.
    _OPTION_RIGHT = re.compile(r"right='[CP]'")

    def __init__(self) -> None:
        super().__init__()
        self._last_key: tuple[str, str] | None = None
        self._repeat_count = 0

    def filter(self, record: logging.LogRecord) -> bool:
        # The same filter instance is attached to multiple handlers (console + file); each
        # handler calls filter() on every record. Cache the decision on the record itself
        # so cross-record dedup state only advances once per record, not once per handler.
        cached = getattr(record, "_noise_decision", None)
        if cached is not None:
            return bool(cached)

        msg = record.getMessage()
        normalised = self._DIGITS.sub("#", msg)
        normalised = self._OPTION_RIGHT.sub("right='#'", normalised)
        key = (record.name, normalised[: self._PREFIX_LEN])

        if key == self._last_key:
            self._repeat_count += 1
            if self._repeat_count > self._SUPPRESS_AFTER:
                record._noise_decision = False
                return False
        else:
            prev_key, prev_count = self._last_key, self._repeat_count
            # Reset state before emitting the summary — the summary log re-enters this
            # filter, and it must see a fresh (non-suppressing) state or it recurses forever.
            self._last_key = key
            self._repeat_count = 0
            if prev_count > self._SUPPRESS_AFTER and prev_key is not None:
                logging.getLogger(prev_key[0]).log(
                    record.levelno,
                    "(suppressed %d further repeats of the previous message)",
                    prev_count - self._SUPPRESS_AFTER,
                )

        if len(msg) > self._MAX_LEN:
            record.msg = msg[: self._MAX_LEN] + f"... [truncated, {len(msg)} chars total]"
            record.args = ()

        record._noise_decision = True
        return True


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

    # pytest imports the `pytest` package before collecting any test module, so this is set
    # before any src module (and its module-level get_logger() call) is imported — reliably
    # routing test runs to their own file. Without this, mocked failure-injection in the test
    # suite (RuntimeError("boom") etc.) interleaves with real production incidents in
    # logs/system.log, which made a past incident investigation briefly mistake a burst of
    # synthetic test errors for a live crash loop.
    log_file = "logs/test.log" if "pytest" in sys.modules else cfg.logging.file
    log_path = ROOT / log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    noise_filter = _NoiseFilter()

    # Console — colourised
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(_ColourFormatter())
    console.addFilter(noise_filter)
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
    file_handler.addFilter(noise_filter)
    root.addHandler(file_handler)

    # Quiet noisy third-party loggers unless we are in DEBUG
    if level > logging.DEBUG:
        for noisy in ("ib_async", "telegram", "apscheduler"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
    # Always, even at DEBUG: httpx's INFO request line embeds the Flex token (?t=...)
    for secret_bearing in ("httpx", "httpcore"):
        logging.getLogger(secret_bearing).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
