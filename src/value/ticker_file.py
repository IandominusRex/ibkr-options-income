"""The ticker file (spec §6.9): every name ever scored keeps Part 1, fresh on search.

``persist`` writes the latest row and, when anything that matters changed, an append-only
history row; names in the ranked universe also get one compact row per session. Nothing is
deleted. ``is_fresh`` compares a stored fingerprint with the current one.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.config import ValueTickerFileCfg
from src.value.schemas import LISTS, Fingerprint, ValueScorecard
from src.value.store import ValueTickerFileRow, ValueTickerHistoryRow


@dataclass(frozen=True, slots=True)
class WriteResult:
    changed: list[str]
    history_reason: str | None  # "changed" | "session" | None


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def summary(
    card: ValueScorecard, ranks: dict[str, float | None], filed: str | None
) -> dict[str, Any]:
    """The compact record history rows keep every session, and the fields a change is read
    from."""
    gates = {c.id: c.state for c in [*card.data_quality_checks, *card.health_checks]}
    lists: dict[str, Any] = {}
    for name in LISTS:
        ev = card.lists.get(name)
        lists[name] = {
            "verdict": card.verdict_for(name),
            "fair_value": ev.fair_value if ev else None,
            "mos": ev.margin_of_safety if ev else None,
            "entry": ev.entry if ev else None,
            "timing": ev.timing if ev else None,
            "rank": ranks.get(name),
        }
    return {
        "as_of": card.as_of.isoformat(),
        "price": card.price,
        "data_quality": card.data_quality,
        "health": card.health,
        "not_applicable": card.not_applicable_reason,
        "gates": gates,
        "lists": lists,
        "filed_list": filed,
    }


def _band(mos: float | None, width: float) -> int | None:
    return None if mos is None else math.floor(mos * 100.0 / width)


def what_changed(
    prev: dict[str, Any] | None, new: dict[str, Any], cfg: ValueTickerFileCfg
) -> list[str]:
    """Spec §6.9: the verdict, fair value (by more than ``fair_value_change_pct``), the margin
    of safety's band, or any gate result."""
    if prev is None:
        return ["new"]
    out: list[str] = []
    for key in ("data_quality", "health", "not_applicable"):
        if prev.get(key) != new.get(key):
            out.append(key)
    old_gates, new_gates = prev.get("gates", {}), new.get("gates", {})
    for gate in sorted(set(old_gates) | set(new_gates)):
        if old_gates.get(gate) != new_gates.get(gate):
            out.append(f"gate:{gate}")
    for name in LISTS:
        a, b = prev.get("lists", {}).get(name, {}), new["lists"].get(name, {})
        for key in ("verdict", "entry", "timing"):
            if a.get(key) != b.get(key):
                out.append(f"{name}.{key}")
        fa, fb = a.get("fair_value"), b.get("fair_value")
        if (fa is None) != (fb is None) or (
            fa and fb and abs(fb - fa) / abs(fa) * 100.0 > cfg.fair_value_change_pct
        ):
            out.append(f"{name}.fair_value")
        if _band(a.get("mos"), cfg.mos_band_pts) != _band(b.get("mos"), cfg.mos_band_pts):
            out.append(f"{name}.mos_band")
    return out


def persist(
    session: Session,
    card: ValueScorecard,
    *,
    universe: str,
    ranks: dict[str, float | None],
    filed: str | None,
    cfg: ValueTickerFileCfg,
    session_row: bool,
) -> WriteResult:
    """Upsert the latest row; append history when something changed, else (when
    *session_row*) one compact row per as-of date."""
    now = _now()
    new = summary(card, ranks, filed)
    row = session.get(ValueTickerFileRow, card.symbol)
    prev = json.loads(row.summary_json) if row is not None else None
    changed = what_changed(prev, new, cfg)
    full = card.model_dump_json()
    deep, growth = card.lists.get("deep_value"), card.lists.get("quality_growth")
    values = dict(
        computed_at=now,
        as_of=card.as_of,
        universe=universe,
        fingerprint_key=card.fingerprint.key(),
        fingerprint_json=card.fingerprint.model_dump_json(),
        ruleset_version=card.ruleset_version,
        ruleset_hash=card.ruleset_hash,
        company_class=card.company_class,
        data_quality=card.data_quality,
        health=card.health,
        verdict_deep=card.verdict_for("deep_value"),
        verdict_growth=card.verdict_for("quality_growth"),
        filed_list=filed,
        fair_value_deep=deep.fair_value if deep else None,
        fair_value_growth=growth.fair_value if growth else None,
        mos_deep=deep.margin_of_safety if deep else None,
        mos_growth=growth.margin_of_safety if growth else None,
        rank_deep=ranks.get("deep_value"),
        rank_growth=ranks.get("quality_growth"),
        price=card.price,
        summary_json=json.dumps(new, sort_keys=True),
        scorecard_json=full,
    )
    if row is None:
        session.add(ValueTickerFileRow(symbol=card.symbol, **values))
    else:
        for key, value in values.items():
            setattr(row, key, value)

    reason: str | None = None
    if changed:
        reason = "changed"
    elif session_row:
        seen = session.execute(
            select(ValueTickerHistoryRow.id).where(
                ValueTickerHistoryRow.symbol == card.symbol,
                ValueTickerHistoryRow.as_of == card.as_of,
            )
        ).first()
        reason = None if seen else "session"
    if reason is not None:
        session.add(
            ValueTickerHistoryRow(
                symbol=card.symbol,
                recorded_at=now,
                as_of=card.as_of,
                reason=reason,
                changed=json.dumps(changed),
                fingerprint_key=card.fingerprint.key(),
                ruleset_version=card.ruleset_version,
                summary_json=json.dumps(new, sort_keys=True),
                scorecard_json=full if reason == "changed" else None,
            )
        )
    return WriteResult(changed=changed, history_reason=reason)


def is_fresh(stored: Fingerprint | None, current: Fingerprint) -> bool:
    """Equal fingerprints mean the stored file stands; anything else recomputes (spec §6.9)."""
    return stored is not None and stored.key() == current.key()


def stored_fingerprint(session: Session, symbol: str) -> Fingerprint | None:
    row = session.get(ValueTickerFileRow, symbol)
    return None if row is None else Fingerprint.model_validate_json(row.fingerprint_json)
