"""Tests for the scan progress _Tracker: the checklist message + the progress-bar dashboard.

The dashboard is the second Telegram message a /scan edits in place — a progress bar with an
ETA, a current-activity line, and a running log of errors flagged in red. These tests drive
the tracker directly (no IBKR / Telegram needed) and assert on the rendered MarkdownV2.
"""

from __future__ import annotations

from src.orchestrator.scan import _Tracker


def _collector():
    sent: list[str] = []

    async def cb(text: str) -> None:
        sent.append(text)

    return sent, cb


async def test_both_callbacks_fire_on_stage_tick():
    checklist, ccb = _collector()
    dash, dcb = _collector()
    t = _Tracker(ccb, dcb)

    await t.tick("account", "✅")

    assert checklist and dash
    assert "Account & positions" in checklist[-1]
    assert "▰" in dash[-1] or "▱" in dash[-1]  # progress bar present


async def test_dashboard_progress_advances_with_symbols():
    _, ccb = _collector()
    dash, dcb = _collector()
    t = _Tracker(ccb, dcb)

    await t.mark_symbol(1, 10, "AAPL")
    early = t._pct
    # force-flush the next one past the throttle by simulating elapsed time
    t._last_push = 0.0
    await t.mark_symbol(10, 10, "ZM")
    late = t._pct

    assert 0.0 < early < late <= 0.85
    assert "ZM" in dash[-1]


async def test_error_log_rendered_in_red():
    _, ccb = _collector()
    dash, dcb = _collector()
    t = _Tracker(ccb, dcb)

    await t.add_error("NVDA — option chain timed out, skipped")
    await t.add_error("TSLA — analytics failed, skipped")

    text = dash[-1]
    assert "🔴" in text
    assert "Errors" in text
    assert "NVDA" in text and "TSLA" in text


async def test_complete_shows_100_percent_and_summary():
    checklist, ccb = _collector()
    dash, dcb = _collector()
    t = _Tracker(ccb, dcb)

    await t.complete(cc=2, csp=1, buy=3, vix=17.7)

    assert "100%" in dash[-1]
    assert "Scan complete" in dash[-1]
    assert "Scan complete" in checklist[-1]
    assert "2 CC" in checklist[-1]


async def test_error_stage_flips_to_failed():
    _, ccb = _collector()
    dash, dcb = _collector()
    t = _Tracker(ccb, dcb)

    await t.error("account", "fetch failed — aborting")

    assert "Scan failed" in dash[-1]
    assert "🔴" in dash[-1]


async def test_per_symbol_updates_are_throttled():
    _, ccb = _collector()
    dash, dcb = _collector()
    t = _Tracker(ccb, dcb)

    # Two rapid symbol marks: the second is inside the min-interval window, so it must not
    # produce a second dashboard edit (avoids Telegram rate limits).
    await t.mark_symbol(1, 50, "A")
    n_after_first = len(dash)
    await t.mark_symbol(2, 50, "B")
    assert len(dash) == n_after_first


async def test_none_callbacks_are_safe():
    t = _Tracker(None, None)
    await t.tick("account", "✅")
    await t.mark_symbol(1, 2, "AAPL")
    await t.add_error("x")
    await t.complete(0, 0, 0)  # must not raise
