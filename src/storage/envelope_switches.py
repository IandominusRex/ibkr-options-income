"""The risk envelope's data-gated switches (risk-envelope plan, Task 1).

Each switch is one ``system_settings`` row, ``envelope_switch:<name>``, holding JSON
``{value, source, report, set_at}``. A behaviour the plan builds now but that must wait on data
(the envelope's enforcement, the slow breaker, the hedge instrument ...) reads its switch here.

* **Defaults.** A missing, unparseable or out-of-set stored value reads the switch's default. In
  live every switch reads its default regardless of what is stored (``Config.is_live``), except
  ``spxw_ready``, which only records the E3 verdict and gates nothing by itself.
* **Who sets one.** ``set_switch`` (the ``scripts.envelope`` CLI, ``source="cli"``) or a PASSed
  result file (``apply_reports``, ``source="report:<id>"``). A report never overwrites a value the
  CLI set (ruling P11), and a FAIL never turns anything off: only the CLI does.

Deterministic tier: reads and writes ``system_settings`` only; imports nothing from enrichment.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.common.config import ROOT, get_config
from src.common.schemas import EnvelopeReportResult
from src.storage.system_settings import get_setting, set_setting

log = logging.getLogger(__name__)

KEY_PREFIX = "envelope_switch:"
REPORTS_DIR = ROOT / "data" / "envelope_reports"

_OFF_ON = frozenset({"off", "on"})

# name -> (default, allowed values)
SWITCHES: dict[str, tuple[str, frozenset[str]]] = {
    "envelope_enforce": ("record", frozenset({"off", "record", "on"})),
    "spreads_paper": ("off", _OFF_ON),
    "spxw_ready": ("off", frozenset({"off", "spxw", "xsp", "stay"})),
    "hedge_instrument": ("none", frozenset({"none", "XND", "QQQ"})),
    "bridge": ("off", frozenset({"off", "on", "ended"})),
    "tech_cap": ("off", _OFF_ON),
    "stacking_rule": ("off", _OFF_ON),
    "index_1x": ("off", _OFF_ON),
    "leveraged_sleeve": ("off", _OFF_ON),
    "leveraged_cc_auto": ("off", _OFF_ON),
    "t20_limit": ("off", _OFF_ON),
    "slow_breaker": ("off", frozenset({"off", "8", "10", "12", "15"})),
    "cc_basis_floor": ("1.00", frozenset({"1.00", "0.95", "0.90"})),
    "hedge_monetisation": ("none", frozenset({"none", "2x"})),
    "leveraged_entry": ("record", frozenset({"off", "record", "on"})),  # L7
}

# The one switch that reads its stored value in live (it records the E3 verdict, nothing more).
LIVE_EXEMPT = frozenset({"spxw_ready"})


def _key(name: str) -> str:
    return f"{KEY_PREFIX}{name}"


def _check(name: str, value: str | None = None) -> tuple[str, frozenset[str]]:
    if name not in SWITCHES:
        raise ValueError(f"unknown envelope switch {name!r}")
    default, allowed = SWITCHES[name]
    if value is not None and value not in allowed:
        raise ValueError(f"{name}: {value!r} is not one of {sorted(allowed)}")
    return default, allowed


def switch_record(name: str) -> dict[str, Any] | None:
    """The stored ``{value, source, report, set_at}`` for a switch, or None (never set, or the
    row is unreadable)."""
    raw = get_setting(_key(name), "")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        log.warning("envelope switch %s: unparseable record %r", name, raw)
        return None
    return data if isinstance(data, dict) else None


def parse_record(raw: str | None) -> dict[str, Any] | None:
    """A stored switch row's JSON as a dict, or None (empty, unparseable or not an object)."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def resolve_switch(name: str, record: dict[str, Any] | None, *, live: bool) -> str:
    """The pure rule behind ``get_switch`` (shared with the read-only API): the default in live
    (``spxw_ready`` excepted) and whenever *record*'s value is missing or outside the set."""
    default, allowed = _check(name)
    if live and name not in LIVE_EXEMPT:
        return default
    value = record.get("value") if record else None
    if isinstance(value, str) and value in allowed:
        return value
    return default


def get_switch(name: str) -> str:
    """The switch's value: its default in live (``spxw_ready`` excepted) and whenever the stored
    value is missing, unparseable or outside the allowed set. Raises only on an unknown name."""
    default, _allowed = _check(name)
    live = False
    if name not in LIVE_EXEMPT:
        try:
            live = get_config().is_live
        except Exception:
            log.warning("envelope switch %s: config unreadable, reading the default", name)
            return default
        if live:
            return default
    return resolve_switch(name, switch_record(name), live=live)


def set_switch(name: str, value: str, *, source: str, report: str | None = None) -> None:
    """Store a switch. Raises ``ValueError`` on an unknown name or a value outside its set."""
    _check(name, value)
    rec = {
        "value": value,
        "source": source,
        "report": report,
        "set_at": datetime.now(UTC).isoformat(),
    }
    set_setting(_key(name), json.dumps(rec))


def _load_report(path: Path) -> EnvelopeReportResult | None:
    try:
        return EnvelopeReportResult.model_validate_json(path.read_text())
    except Exception:
        log.warning("envelope report %s is unreadable, skipped", path.name, exc_info=True)
        return None


def apply_reports(directory: Path | None = None) -> list[str]:
    """Turn on every switch a PASSed result file names; return one notice per change.

    A file with ``passed is True`` sets ``switch`` to ``value_on_pass`` when the switch has no
    record, or its record came from a report (``source`` starts ``report:``) with a different
    value. A record set by the CLI is never overwritten (P11). A FAIL, an insufficient-data
    result, an unreadable file or an unknown switch/value changes nothing (the last two log).
    """
    directory = directory if directory is not None else REPORTS_DIR
    if not directory.is_dir():
        return []
    notices: list[str] = []
    for path in sorted(directory.glob("*.json")):
        result = _load_report(path)
        if result is None or result.passed is not True:
            continue
        try:
            default, _allowed = _check(result.switch, result.value_on_pass)
        except ValueError:
            log.warning("envelope report %s names a bad switch/value, skipped", path.name)
            continue
        rec = switch_record(result.switch)
        if rec is not None:
            source = str(rec.get("source", ""))
            if not source.startswith("report:") or rec.get("value") == result.value_on_pass:
                continue
        set_switch(
            result.switch,
            result.value_on_pass,
            source=f"report:{result.id}",
            report=result.id,
        )
        if result.switch == "spxw_ready":
            # E3 only notifies: this records the verdict and gates nothing (Task 17, ruling E3).
            notices.append(
                f"{result.id} PASS: {result.switch} -> {result.value_on_pass}. Run Task 39 of "
                f"the risk-envelope plan at a flat-book cutover. Nothing else changes. Reverse: "
                f"python -m scripts.envelope switch {result.switch} {default}"
            )
            continue
        notices.append(
            f"{result.id} PASS: {result.switch} -> {result.value_on_pass} "
            f"(paper; record-only in live). Reverse: "
            f"python -m scripts.envelope switch {result.switch} {default}"
        )
    return notices
