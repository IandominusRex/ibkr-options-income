"""Show and change the risk envelope's data-gated switches.

A switch is a behaviour the envelope plan builds now but turns on only when data says so (a
replay or capture report PASSes, or you set it here). A report never overwrites a value set by
this CLI, and a FAIL never turns anything off: only this CLI does.

Usage:
    python -m scripts.envelope show                  # every switch, the latest snapshot, the glide
    python -m scripts.envelope stabilisation         # the three conditions for raising a limit (spec §3.8)
    python -m scripts.envelope switch NAME VALUE     # set one (source "cli"), with a Telegram notice
    python -m scripts.envelope apply-reports         # apply the PASSed files in data/envelope_reports/
    python -m scripts.envelope reset-slow-breaker    # the human reset of the 20-session drawdown breaker

In live every switch reads its default whatever is stored (``spxw_ready`` excepted), so a value
set here takes effect in paper only.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from src.common.envelope_types import EnvelopeSnapshot
from src.common.logging import setup_logging
from src.common.market_hours import today_et
from src.common.schemas import EnvelopeReportResult
from src.notify.notices import send_notice
from src.storage import slow_breaker
from src.storage.db import init_db
from src.storage.envelope_state import glide_span, latest_snapshot, limits_on, load_glide
from src.storage.envelope_switches import (
    REPORTS_DIR,
    SWITCHES,
    apply_reports,
    get_switch,
    set_switch,
    switch_record,
)


def _show() -> int:
    width = max(len(n) for n in SWITCHES)
    print(f"{'switch'.ljust(width)}  {'value':<8} {'source':<24} set_at")
    for name, (default, _allowed) in SWITCHES.items():
        rec = switch_record(name)
        source = str(rec.get("source")) if rec else "(default)"
        set_at = str(rec.get("set_at")) if rec else ""
        print(
            f"{name.ljust(width)}  {get_switch(name):<8} {source:<24} {set_at}  [default {default}]"
        )
    print()
    for source in ("live", "stored"):
        print(_snapshot_text(latest_snapshot(source), source))
    print(_glide_text())
    print(_slow_breaker_text())
    return 0


def _slow_breaker_text() -> str:
    try:
        state = slow_breaker.read_state()
    except Exception as exc:
        return f"slow breaker: UNREADABLE ({exc})"
    if not state or not state.get("tripped"):
        return "slow breaker: not tripped"
    return (
        f"slow breaker: TRIPPED {state.get('at')} at {state.get('drawdown_pct')}% (threshold "
        f"{state.get('threshold_pct')}%, high ${state.get('high'):,.0f}); reset it with "
        "python -m scripts.envelope reset-slow-breaker"
    )


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f}%"


def _snapshot_text(snap: EnvelopeSnapshot | None, source: str) -> str:
    if snap is None:
        return f"latest {source}-IV snapshot: none yet"
    r = snap.result
    uew_limit = "n/a" if snap.uew_limit is None else f"{snap.uew_limit:.2f}"
    lines = [
        f"latest {source}-IV snapshot ({snap.captured_at:%Y-%m-%d %H:%M} UTC, enforce {snap.enforce}"
        f"{'' if snap.measured else ', UNMEASURED'}):",
        f"  S10 {_pct(r.s10)} gross / {_pct(r.s10_net)} net  (limit {_pct(snap.s10_limit)});"
        f" +10 vol {_pct(r.s10_vol10)}",
        f"  S20 {_pct(r.s20)} / {_pct(r.s20_net)}   G10 {_pct(r.g10)} / {_pct(r.g10_net)}"
        f"   P20 {_pct(r.p20)} / {_pct(r.p20_net)}",
        f"  T20 {_pct(r.t20)} / {_pct(r.t20_net)}   S-SMH {_pct(r.s_smh)} / {_pct(r.s_smh_net)}",
        f"  U_ew {r.uew:.2f} (limit {uew_limit})",
    ]
    if snap.cash_after_itm is not None:
        lines.append(f"  cash after every ITM put is assigned: ${snap.cash_after_itm:,.0f}")
    if snap.reasons:
        lines.append(f"  unmeasured because: {', '.join(snap.reasons)}")
    return "\n".join(lines)


def _glide_text() -> str:
    try:
        rec = load_glide()
    except Exception as exc:
        return f"glide: UNREADABLE ({exc})"
    if rec is None:
        return "glide: not started (it starts on the first session envelope_enforce reads on)"
    today = today_et()
    span = glide_span(rec, today)
    s10, uew = limits_on(rec, today)
    return (
        f"glide: started {rec.start_date} at S10 {rec.s10_start:.1f}% / U_ew {rec.uew_start:.2f};"
        f" week {span.week} of {span.weeks}, ends {span.end}; today's L(t) S10 {s10:.2f}%,"
        f" U_ew {uew:.3f}; targets {rec.s10_target:.1f}% / {rec.uew_target:.2f}"
    )


def _latest_harness(directory: Path) -> EnvelopeReportResult | None:
    found: list[EnvelopeReportResult] = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            result = EnvelopeReportResult.model_validate_json(path.read_text())
        except Exception:
            continue
        if "harness" in result.id:
            found.append(result)
    return max(found, key=lambda r: r.written_at) if found else None


def stabilisation_text(directory: Path | None = None) -> str:
    """Spec §3.8: after the glide reaches its target, a limit rises only on all three of the
    market-level bottoming signal, the survivability harness passing at the new level, and an
    operator ruling. This says where each stands and changes nothing."""
    from src.storage.regime_state import load_regime_state

    state = load_regime_state()
    if state is None:
        bottom = "unknown (no regime state recorded)"
    else:
        flags = {"SPY": state.spy.eased_by_bottoming, "QQQ": state.qqq.eased_by_bottoming}
        bottom = ", ".join(f"{k} {'yes' if v else 'no'}" for k, v in flags.items())
    harness = _latest_harness(directory if directory is not None else REPORTS_DIR)
    if harness is None:
        h = "no harness result file yet"
    else:
        verdict = {True: "PASS", False: "FAIL", None: "insufficient data"}[harness.passed]
        h = f"{verdict} ({harness.id}, written {harness.written_at:%Y-%m-%d})"
    return "\n".join(
        [
            "Stabilisation (spec §3.8): a limit rises only when all three hold.",
            f"  1. market-level bottoming signal: {bottom}",
            f"  2. survivability harness at the new level: {h}",
            "  3. operator ruling required: this script never raises a limit.",
        ]
    )


def _stabilisation() -> int:
    print(stabilisation_text())
    return 0


def _switch(name: str, value: str) -> int:
    old = get_switch(name) if name in SWITCHES else None
    try:
        set_switch(name, value, source="cli")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{name}: {old} -> {get_switch(name)}")
    asyncio.run(send_notice(f"envelope switch {name}: {old} -> {value} (set by CLI)"))
    return 0


def _reset_slow_breaker() -> int:
    """The human reset (spec §3.4.5): clears the trip and restarts the drawdown window."""
    try:
        cleared = slow_breaker.reset()
    except Exception as exc:
        print(f"error: the slow breaker state could not be read ({exc})", file=sys.stderr)
        return 1
    if cleared is None:
        print("the slow breaker is not tripped: nothing to reset")
        return 0
    text = (
        f"Slow breaker reset by hand (it tripped {cleared.get('at')} at {cleared.get('drawdown_pct')}%). "
        "The CSP budget is back to normal and the spreads book may enter again; the drawdown window "
        "restarts from today's high."
    )
    print(text)
    asyncio.run(send_notice(text))
    return 0


def _apply_reports() -> int:
    messages = apply_reports()
    if not messages:
        print("no report changes a switch")
    for message in messages:
        print(message)
        asyncio.run(send_notice(message))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Risk-envelope switches")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show", help="every switch, the latest envelope snapshot and the glide")
    sub.add_parser("stabilisation", help="the three conditions for raising a limit (reads only)")
    s = sub.add_parser("switch", help="set a switch by hand")
    s.add_argument("name")
    s.add_argument("value")
    sub.add_parser("apply-reports", help="apply the PASSed result files now")
    sub.add_parser(
        "reset-slow-breaker", help="clear a tripped slow drawdown breaker (a human reset)"
    )
    a = p.parse_args(argv)

    init_db()
    if a.cmd == "show":
        return _show()
    if a.cmd == "stabilisation":
        return _stabilisation()
    if a.cmd == "switch":
        return _switch(a.name, a.value)
    if a.cmd == "reset-slow-breaker":
        return _reset_slow_breaker()
    return _apply_reports()


if __name__ == "__main__":
    setup_logging()
    raise SystemExit(main())
