"""Tests for _NoiseFilter — collapses the IBKR error-callback flood (see scan logs)."""

from __future__ import annotations

import logging

from src.common.logging import _NoiseFilter


def _record(name: str, msg: str, levelno: int = logging.ERROR) -> logging.LogRecord:
    return logging.LogRecord(
        name=name, level=levelno, pathname="x.py", lineno=1, msg=msg, args=(), exc_info=None
    )


def test_truncates_overly_long_messages():
    f = _NoiseFilter()
    rec = _record("ib_async.wrapper", "Error 354" + "&BEST/OPT/Top" * 100)
    assert f.filter(rec) is True
    assert len(rec.getMessage()) <= _NoiseFilter._MAX_LEN + 40
    assert "truncated" in rec.getMessage()


def test_suppresses_runs_of_near_identical_messages():
    f = _NoiseFilter()

    decisions = []
    for i in range(6):
        rec = _record(
            "ib_async.wrapper", f"Error 300, reqId 1792{i}: Can't find EId with tickerId:1792{i}"
        )
        decisions.append(f.filter(rec))

    # First _SUPPRESS_AFTER+1 pass through (identical 120-char prefix), rest suppressed.
    assert decisions[:3] == [True, True, True]
    assert all(d is False for d in decisions[3:])


def test_repeat_count_resets_on_distinct_message(caplog):
    f = _NoiseFilter()
    logger_name = "ib_async.wrapper"

    for i in range(5):
        f.filter(_record(logger_name, f"Error 300, reqId {i}: Can't find EId with tickerId:{i}"))

    with caplog.at_level(logging.ERROR, logger=logger_name):
        rec = _record(logger_name, "scan: processing SOFI")
        assert f.filter(rec) is True

    assert any("suppressed" in r.message for r in caplog.records)


def test_suppresses_runs_that_alternate_option_right():
    """A chain probe fires 'Unknown contract' once per (strike, right) combo, alternating
    right='C'/'P' every other line. Since that token used to survive normalisation, it
    defeated the consecutive-repeat check and let a single symbol emit hundreds of
    un-suppressed lines (2026-08-27 incident)."""
    f = _NoiseFilter()

    decisions = []
    for i in range(6):
        strike = 485.0 + i * 2.5
        right = "C" if i % 2 == 0 else "P"
        rec = _record(
            "ib_async.ib",
            f"Unknown contract: Option(symbol='SMH', "
            f"lastTradeDateOrContractMonth='20261009', strike={strike}, right='{right}', "
            f"exchange='SMART')",
            levelno=logging.WARNING,
        )
        decisions.append(f.filter(rec))

    assert decisions[:3] == [True, True, True]
    assert all(d is False for d in decisions[3:])


def test_same_record_processed_by_multiple_handlers_is_idempotent():
    f = _NoiseFilter()
    rec = _record("ib_async.wrapper", "Error 300, reqId 1: Can't find EId with tickerId:1")
    first = f.filter(rec)
    second = f.filter(rec)
    assert first == second is True


def test_httpx_loggers_are_pinned_to_warning_even_at_debug(monkeypatch):
    """M8: httpx's INFO request line embeds the Flex token, so DEBUG must not unmute it."""
    import src.common.logging as lg
    from src.common.config import get_config

    saved = {n: logging.getLogger(n).level for n in ("httpx", "httpcore")}
    monkeypatch.setattr(lg, "_CONFIGURED", False)
    monkeypatch.setattr(get_config().logging, "level", "DEBUG")
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    try:
        lg.setup_logging()
        assert logging.getLogger("httpx").level == logging.WARNING
        assert logging.getLogger("httpcore").level == logging.WARNING
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)
        for n, lv in saved.items():
            logging.getLogger(n).setLevel(lv)
