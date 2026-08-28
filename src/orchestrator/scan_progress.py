"""Scan presentation — everything a scan shows a human, and the only third of the trio that
talks to ``src.notify``.

Two surfaces live here:

* ``_Tracker`` — the two messages a ``/scan`` edits *in place* while it runs: a stage checklist
  and a progress dashboard. It renders MarkdownV2 and pushes it through two async callbacks
  supplied by the caller, either of which may be ``None`` (the 15-min daemon loop runs silently),
  so the tracker itself needs no Telegram SDK and a non-Telegram front-end can reuse it.
* ``send_scan_results`` — the end-of-run send stage: the CC/CSP candidate cards, the buy list,
  the C7 skip-reasons card, the account snapshot, and the full-sweep data-provenance summary,
  together with the ``notify`` stage's tracker transitions.

Split out of ``scan.py`` so that presentation lives apart from the scan's data production
(``scan_pipeline.py``, which imports nothing from ``src.notify`` at all — enforced by a test) and
from orchestration. Nothing here decides anything: it reports what the scan already produced.

``send_candidates`` / ``send_buy_list`` / ``send_account_snapshot`` are *injected* via
:class:`SendDeps` rather than imported here, for the same reason ``scan_pipeline.SymbolDeps``
injects its screens: the scan tests monkeypatch those three names as attributes of
``src.orchestrator.scan``, so that module has to stay the one holding the reference. Everything
else this module needs from ``src.notify`` (``thread_id`` and the three formatters) is imported
directly.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from src.common.config import get_config
from src.common.schemas import AccountSnapshot, PositionSnapshot, TradeCandidate
from src.notify.formatters import (
    format_assessed_contracts,
    format_data_provenance,
    format_skip_reasons,
)
from src.notify.sender import thread_id

if TYPE_CHECKING:  # a presenter renders the orchestrator's result type; runtime import-free
    from src.orchestrator.scan import ScanResult

log = logging.getLogger(__name__)

_ProgressCB = Callable[[str], Awaitable[None]]

# Max assessed-but-not-approved contracts to list per strategy on a *manual* /scan or a full
# sweep. The 15-min intraday loop never renders this block (it keeps the one-line digest
# above), so this bound only shapes the deliberate, human-requested view.
_ASSESSED_LIMIT = 8

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


# ---------------------------------------------------------------------------
# End-of-run send stage
# ---------------------------------------------------------------------------

# Every sender returns True/False (sent / suppressed); none of them raise on a Telegram failure
# they can handle themselves. Typed loosely because each takes a different keyword surface.
AsyncSend = Callable[..., Awaitable[bool]]


@dataclass(frozen=True)
class SendDeps:
    """The three ``src.notify.sender`` coroutines :func:`send_scan_results` calls out to.

    Injected rather than imported because ``tests/test_scan_timeout.py``,
    ``tests/test_scan_materiality.py`` and ``tests/test_scan_review_reuse.py`` monkeypatch these
    names as attributes of ``src.orchestrator.scan``. A module-level import here would resolve
    from *this* module's globals and silently bypass those stubs, sending real Telegram traffic
    from the test suite.
    """

    send_candidates: AsyncSend
    send_buy_list: AsyncSend
    send_account_snapshot: AsyncSend


async def send_scan_results(
    tracker: _Tracker,
    result: ScanResult,
    *,
    bot: object,
    chat_id: str,
    intraday: bool,
    account: AccountSnapshot,
    positions: list[PositionSnapshot],
    cc_empty_reason: str,
    csp_empty_reason: str,
    cc_near_misses: list[tuple[TradeCandidate, list[str]]],
    cc_near_miss_more: int,
    csp_near_misses: list[tuple[TradeCandidate, list[str]]],
    csp_near_miss_more: int,
    per_symbol_skip: dict[str, list[str]],
    sends: SendDeps,
    include_buy_list: bool = True,
) -> None:
    """Send a finished scan's results and drive the ``notify`` stage of the tracker.

    Never raises: the candidate sends are wrapped so a Telegram failure marks the stage failed
    rather than aborting the scan, and the account snapshot + provenance summary are each
    independently best-effort so neither can affect the stage's success status.

    *cc_empty_reason* / *csp_empty_reason* are pre-rendered by the caller (they read
    ``ScanResult`` plus the per-strategy rejection tallies, which is orchestration state).

    *include_buy_list* gates only the Telegram send of the buy-to-own screen — the caller
    (the 15-min intraday loop) sets this ``False`` on every cycle after the first one that
    completes each day, so the buy list fires once daily instead of every 15 minutes. Manual
    ``/scan`` always leaves it ``True``. ``result.buy_candidates`` is scored either way — this
    only suppresses the send.
    """
    # send_candidates manages its own short DB transactions (no session held across the
    # Telegram network sends — that would block other processes writing the same SQLite DB).
    await tracker.tick("notify", "⏳")
    try:
        cfg_s = get_config().secrets
        # The full "assessed but not approved" listing goes out on manual /scan and full
        # sweeps only. The 15-min intraday loop keeps the compact one-line near-miss digest
        # (`near_misses` below) so this can't reintroduce ~26 extra messages a day (S6).
        cc_assessed_text = (
            format_assessed_contracts(
                result.assessed, strategy="covered_call", max_rows=_ASSESSED_LIMIT
            )
            if not intraday
            else None
        )
        csp_assessed_text = (
            format_assessed_contracts(
                result.assessed, strategy="cash_secured_put", max_rows=_ASSESSED_LIMIT
            )
            if not intraday
            else None
        )
        await sends.send_candidates(
            result.cc_candidates,
            result.reviews,
            thread_id=thread_id(cfg_s.telegram_thread_cc),
            label="Covered Calls",
            icon="🔵",
            hash_key="last_cc_hash",
            time_key="last_cc_time",
            empty_reason=cc_empty_reason,
            suppress_unchanged=intraday,
            near_misses=cc_near_misses,
            near_miss_more=cc_near_miss_more,
            assessed_text=cc_assessed_text,
        )
        await sends.send_candidates(
            result.csp_candidates,
            result.reviews,
            thread_id=thread_id(cfg_s.telegram_thread_csp),
            label="Cash-Secured Puts",
            icon="🟣",
            hash_key="last_csp_hash",
            time_key="last_csp_time",
            empty_reason=csp_empty_reason,
            suppress_unchanged=intraday,
            near_misses=csp_near_misses,
            near_miss_more=csp_near_miss_more,
            assessed_text=csp_assessed_text,
        )
        if include_buy_list:
            await sends.send_buy_list(result.buy_candidates, chat_id, suppress_unchanged=intraday)

        # C7: skip-reasons card — send on full sweeps (manual /scan) when any symbols
        # were fully rejected. Omitted for intraday cycles (would fire ~26× per session).
        if not intraday and per_symbol_skip and bot is not None and chat_id:
            skip_text = format_skip_reasons(per_symbol_skip)
            if skip_text:
                try:
                    await bot.send_message(  # type: ignore[attr-defined]
                        chat_id=chat_id,
                        message_thread_id=thread_id(cfg_s.telegram_thread_scan),
                        text=skip_text,
                        parse_mode="MarkdownV2",
                    )
                except Exception:
                    log.warning("scan: failed to send skip-reasons card", exc_info=True)

        # S6 note: an intraday cycle that surfaces nothing is NOT silent. `send_candidates`
        # appends a timestamped `[HH:MM] … no candidates this cycle <reason>` line (plus the
        # closest near-miss) to the persisted per-thread status message, and `_no_candidates_
        # reason` now carries the materiality clause explaining *why* chains weren't re-fetched.
        # A separate heartbeat message used to exist for this but could never fire — both send
        # functions return True on their empty path — and reinstating it would mean two
        # messages per quiet cycle, which is exactly the flood S6 removed.
    except Exception:
        log.exception("scan: failed to send Telegram messages")
        await tracker.error("notify", "send failed")
    else:
        await tracker.complete(
            len(result.cc_candidates),
            len(result.csp_candidates),
            len(result.buy_candidates),
            vix=result.market_conditions.vix,
        )

    # Best-effort account snapshot after every cycle (intraday + full sweep).
    try:
        await sends.send_account_snapshot(account, positions)
    except Exception:
        log.warning("scan: failed to send account snapshot", exc_info=True)

    # Full sweep (manual /scan): close out with a provenance summary so the
    # operator can see at a glance which data sources were live vs. fell back this run.
    # Best-effort — a failure here must not affect the notify stage's success status above.
    if not intraday and bot is not None and chat_id:
        prov = result.provenance
        cfg_s = get_config().secrets
        try:
            await bot.send_message(  # type: ignore[attr-defined]
                chat_id=chat_id,
                message_thread_id=thread_id(cfg_s.telegram_thread_scan),
                text=format_data_provenance(
                    total_symbols=result.total_symbols,
                    chain_ibkr=prov.chain_ibkr,
                    chain_failed=prov.chain_failed,
                    chain_skipped=prov.chain_skipped,
                    spot_ibkr=prov.spot_ibkr,
                    spot_yfinance=prov.spot_yfinance,
                    spot_unavailable=prov.spot_unavailable,
                    greeks_ibkr=prov.greeks_ibkr,
                    greeks_yfinance=prov.greeks_yfinance,
                    vix=result.market_conditions.vix if result.market_conditions else None,
                ),
                parse_mode="MarkdownV2",
            )
        except Exception:
            log.warning("scan: failed to send data-provenance summary", exc_info=True)
