"""Scan progress reporting — the two Telegram messages a scan edits in place.

Split out of ``scan.py`` so that progress *presentation* lives apart from the scan's data
production (``scan_pipeline.py``). Nothing here decides anything: the tracker only renders
MarkdownV2 and pushes it through the two async callbacks it was handed, either of which may be
``None`` (the 15-min daemon loop runs a scan silently).

The callbacks are supplied by the caller — this module never imports ``src.notify`` or the
telegram SDK itself, so a non-Telegram front-end (the dashboard, a future HTTP API) can reuse
the same tracker by passing its own sinks.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

_ProgressCB = Callable[[str], Awaitable[None]]

_STAGE_ORDER = ["account", "market_data", "scoring", "claude", "notify"]
_STAGE_LABELS = {
    "account": "Account & positions",
    "market_data": "Market data",
    "scoring": "Scoring & risk gate",
    "claude": "Claude review",
    "notify": "Sending results",
}

# Fraction of total wall-clock each stage occupies — used to drive the dashboard progress
# bar + ETA. Market data (per-symbol option chains) dominates a scan, hence the wide span.
_STAGE_SPAN: dict[str, tuple[float, float]] = {
    "account": (0.00, 0.05),
    "market_data": (0.05, 0.85),
    "scoring": (0.85, 0.89),
    "claude": (0.89, 0.98),
    "notify": (0.98, 1.00),
}

# Minimum seconds between throttled dashboard pushes (per-symbol updates). Stage changes,
# errors, and completion always flush immediately regardless of this guard.
_DASHBOARD_MIN_INTERVAL = 2.0
_BAR_CELLS = 10


def _md2(s: str) -> str:
    """Escape a string for Telegram MarkdownV2."""
    for c in r"\_*[]()~`>#+-=|{}.!":
        s = s.replace(c, f"\\{c}")
    return s


def _fmt_eta(seconds: float) -> str:
    s = max(0, int(seconds))
    if s < 60:
        return f"~{s}s left"
    return f"~{s // 60}m {s % 60}s left"


class _Tracker:
    """Drives two Telegram messages for a scan:

    1. the *checklist* (one line per pipeline stage with a status icon), and
    2. the *dashboard* (a progress bar + ETA, a current-activity line, and a running log of
       errors flagged in red).

    Each is edited in place through its own async callback. Either callback may be ``None``
    (e.g. the 15-min daemon loop runs the scan silently).
    """

    def __init__(
        self,
        checklist_cb: _ProgressCB | None,
        dashboard_cb: _ProgressCB | None = None,
    ) -> None:
        self._checklist_cb = checklist_cb
        self._dashboard_cb = dashboard_cb
        self._failed = False
        self._done = False
        # (icon, detail) — detail is already md2-escaped
        self._states: dict[str, tuple[str, str]] = {k: ("⬜", "") for k in _STAGE_ORDER}
        # Dashboard state
        self._pct = 0.0
        self._status = "Starting scan…"
        self._errors: list[str] = []
        self._t0 = time.monotonic()
        self._last_push = 0.0

    # -- checklist (message 1) -------------------------------------------------
    def _render_checklist(self, header: str | None = None) -> str:
        if header is None:
            header = "🔍 *Scan failed*" if self._failed else "🔍 *Scan in progress\\.\\.\\.*"
        lines = [header, ""]
        for key in _STAGE_ORDER:
            icon, detail = self._states[key]
            label = _md2(_STAGE_LABELS[key])
            lines.append(f"{icon} {label}" + (f" — {detail}" if detail else ""))
        return "\n".join(lines)

    # -- dashboard (message 2) -------------------------------------------------
    def _render_dashboard(self) -> str:
        pct = max(0.0, min(1.0, self._pct))
        filled = round(pct * _BAR_CELLS)
        bar = "▰" * filled + "▱" * (_BAR_CELLS - filled)

        if self._done:
            title, pct_txt, eta = "Scan complete", "100%", ""
        elif self._failed:
            title, pct_txt = "Scan failed", f"{int(pct * 100)}%"
            eta = ""
        else:
            title, pct_txt = "Scanning…", f"{int(pct * 100)}%"
            elapsed = time.monotonic() - self._t0
            eta = _fmt_eta(elapsed * (1 - pct) / pct) if 0.02 < pct < 1.0 else ""

        lines = [f"🔍 *{title}* {pct_txt}", f"{bar}" + (f"  {_md2(eta)}" if eta else ""), ""]
        lines.append(f"⚙️ {_md2(self._status)}")
        if self._errors:
            lines.append("")
            lines.append(f"🔴 *Errors \\({len(self._errors)}\\)*")
            for e in self._errors:
                lines.append(f"🔴 {_md2(e)}")
        return "\n".join(lines)

    # -- push mechanics --------------------------------------------------------
    async def _push(self, *, force: bool = False, checklist: bool = True) -> None:
        now = time.monotonic()
        if not force and (now - self._last_push) < _DASHBOARD_MIN_INTERVAL:
            return
        self._last_push = now
        if checklist and self._checklist_cb is not None:
            try:
                header = "🔍 *Scan complete*" if self._done else None
                await self._checklist_cb(self._render_checklist(header))
            except Exception:
                log.debug("Checklist callback failed", exc_info=True)
        if self._dashboard_cb is not None:
            try:
                await self._dashboard_cb(self._render_dashboard())
            except Exception:
                log.debug("Dashboard callback failed", exc_info=True)

    def _stage_pct(self, stage: str, frac: float) -> float:
        lo, hi = _STAGE_SPAN[stage]
        return lo + (hi - lo) * max(0.0, min(1.0, frac))

    # -- public API ------------------------------------------------------------
    async def tick(self, stage: str, icon: str, detail: str = "") -> None:
        self._states[stage] = (icon, _md2(detail) if detail else "")
        # Position the bar: ⏳ → stage start, ✅ → stage end.
        self._pct = self._stage_pct(stage, 1.0 if icon == "✅" else 0.0)
        self._status = f"{_STAGE_LABELS[stage]}…"
        await self._push(force=True)

    async def mark_symbol(self, i: int, n: int, symbol: str) -> None:
        """Per-symbol market-data progress (throttled)."""
        frac = (i / n) if n else 0.0
        self._pct = self._stage_pct("market_data", frac)
        self._states["market_data"] = ("⏳", _md2(f"{i}/{n} — {symbol}"))
        self._status = f"Option chain — {symbol} ({i}/{n})"
        await self._push()

    async def add_error(self, message: str) -> None:
        self._errors.append(message)
        await self._push(force=True, checklist=False)

    async def error(self, stage: str, detail: str = "") -> None:
        """Mark a stage as failed and flip both messages to the failed state."""
        self._failed = True
        self._states[stage] = ("❌", _md2(detail) if detail else "")
        if detail:
            self._errors.append(f"{_STAGE_LABELS.get(stage, stage)}: {detail}")
        await self._push(force=True)

    async def complete(self, cc: int, csp: int, buy: int, vix: float | None = None) -> None:
        vix_str = f" · VIX {vix:.1f}" if vix is not None else ""
        self._states["notify"] = ("✅", _md2(f"{cc} CC · {csp} CSP · {buy} buy{vix_str}"))
        self._done = True
        self._pct = 1.0
        self._status = f"Done — {cc} CC · {csp} CSP · {buy} buy{vix_str}"
        await self._push(force=True)
