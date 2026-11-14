"""Breadth counts and Leveraged Entry Signal rows (deterministic tier; risk-envelope Task 10a).

Two tables in the trading database:

* ``breadth_counts`` (`BreadthCountRow`): one row per (day, source), source ``tt`` (the
  thetrading.tools history) or ``own`` (our nightly count from the constituent list's closes), the
  advancing / declining / unchanged counts, the oscillator of the merged series on the row that the
  merge picked, and ``flagged`` where the two sources disagreed (`analytics.breadth.merge_counts`).
* ``les_signals`` (`LesSignalRow`): one row per (asof, index), the `LesSignal` the EOD run computed.

Record only: nothing on the trading path reads these (the sleeve and the LES share buys will, in
Tasks 23 and 32a, behind the ``leveraged_entry`` switch). Every function swallows storage errors,
like `iv_history.py`: this is derived data and must not take the EOD run down.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import yaml
from sqlalchemy import select

from src.common.config import ROOT
from src.common.schemas import BreadthCount, LesSignal
from src.storage.db import session_scope
from src.storage.models import BreadthCountRow, LesSignalRow

log = logging.getLogger(__name__)


CONSTITUENTS_PATH = ROOT / "config" / "breadth_constituents.yaml"


def load_constituents(path: Path | None = None) -> list[str]:
    """The Nasdaq-100 tickers of the committed list, or ``[]`` when the file is missing or unreadable.

    No list means no own count (the thetrading.tools history alone feeds the oscillator); it never
    means a guess. ``python -m scripts.breadth refresh-constituents`` writes the file.
    """
    target = path if path is not None else CONSTITUENTS_PATH
    try:
        raw = yaml.safe_load(target.read_text()) or {}
        tickers = raw.get("ndx") if isinstance(raw, dict) else None
        if not isinstance(tickers, list):
            return []
        return [str(t).upper() for t in tickers if str(t).strip()]
    except FileNotFoundError:
        return []
    except Exception:
        log.warning("breadth constituents unreadable: %s", target, exc_info=True)
        return []


def record_counts(counts: list[BreadthCount]) -> int:
    """Insert the counts whose (day, source) is not stored yet. Returns the number inserted."""
    if not counts:
        return 0
    try:
        with session_scope() as sess:
            have = {
                (d, s)
                for d, s in sess.execute(select(BreadthCountRow.day, BreadthCountRow.source)).all()
            }
            fresh = [c for c in counts if (c.day, c.source) not in have]
            for c in fresh:
                sess.add(
                    BreadthCountRow(
                        day=c.day, source=c.source, adv=c.adv, dec=c.dec, unch=c.unch, flagged=False
                    )
                )
            return len(fresh)
    except Exception:
        log.warning("record_counts failed", exc_info=True)
        return 0


def load_counts(source: str | None = None) -> list[BreadthCount]:
    """Every stored count (or one source's), ascending by day."""
    try:
        with session_scope() as sess:
            stmt = select(BreadthCountRow).order_by(BreadthCountRow.day)
            if source is not None:
                stmt = stmt.where(BreadthCountRow.source == source)
            return [
                BreadthCount(day=r.day, adv=r.adv, dec=r.dec, unch=r.unch, source=r.source)  # type: ignore[arg-type]
                for r in sess.execute(stmt).scalars()
            ]
    except Exception:
        log.warning("load_counts failed", exc_info=True)
        return []


def record_oscillator(
    merged: list[BreadthCount], osc: list[float | None], flagged: set[date] | None = None
) -> None:
    """Write the merged series' oscillator onto the row the merge picked (None elsewhere).

    *merged* and *osc* are aligned (`oscillator` returns values in date order, and `merge_counts`
    returns ascending days). Rows of the other source for the same day get no oscillator. The days
    in *flagged* (the sources disagreed) mark both of their rows.
    """
    flagged = flagged or set()
    picked: dict[tuple[date, str], float | None] = {
        (c.day, c.source): v for c, v in zip(merged, osc, strict=True)
    }
    try:
        with session_scope() as sess:
            for row in sess.execute(select(BreadthCountRow)).scalars():
                row.osc = picked.get((row.day, row.source))
                row.flagged = row.day in flagged
    except Exception:
        log.warning("record_oscillator failed", exc_info=True)


def latest_osc(n: int = 10) -> list[tuple[date, float]]:
    """The newest *n* oscillator readings, ascending by day (rows without one are skipped)."""
    try:
        with session_scope() as sess:
            rows = sess.execute(
                select(BreadthCountRow.day, BreadthCountRow.osc)
                .where(BreadthCountRow.osc.is_not(None))
                .order_by(BreadthCountRow.day.desc())
                .limit(n)
            ).all()
            return sorted((d, float(v)) for d, v in rows)
    except Exception:
        log.warning("latest_osc failed", exc_info=True)
        return []


def flagged_days() -> set[date]:
    """The days on which the two sources disagreed by more than the configured gap."""
    try:
        with session_scope() as sess:
            return set(
                sess.execute(
                    select(BreadthCountRow.day).where(BreadthCountRow.flagged.is_(True))
                ).scalars()
            )
    except Exception:
        log.warning("flagged_days failed", exc_info=True)
        return set()


def record_signal(sig: LesSignal) -> bool:
    """Store one signal; a re-run for the same (asof, index) updates that row, not a second one.

    A later run the same evening may carry a fresher breadth count, so the newest computation wins.
    Returns False for a signal with no date (nothing to key it by) or on a storage error.
    """
    if sig.asof is None:
        return False
    try:
        with session_scope() as sess:
            row = sess.execute(
                select(LesSignalRow).where(
                    LesSignalRow.asof == sig.asof, LesSignalRow.index_symbol == sig.index
                )
            ).scalar_one_or_none()
            if row is not None:
                row.trend_up = sig.trend_up
                row.pullback = sig.pullback
                row.washout = sig.washout
                row.trend_break = sig.trend_break
                row.tier_pct = sig.tier_pct
                row.reasons = list(sig.reasons)
                return True
            sess.add(
                LesSignalRow(
                    asof=sig.asof,
                    index_symbol=sig.index,
                    trend_up=sig.trend_up,
                    pullback=sig.pullback,
                    washout=sig.washout,
                    trend_break=sig.trend_break,
                    tier_pct=sig.tier_pct,
                    reasons=list(sig.reasons),
                )
            )
            return True
    except Exception:
        log.warning("record_signal failed", exc_info=True)
        return False


def latest_signal(index: str) -> LesSignal | None:
    """The newest stored signal for *index*, or None."""
    try:
        with session_scope() as sess:
            row = sess.execute(
                select(LesSignalRow)
                .where(LesSignalRow.index_symbol == index)
                .order_by(LesSignalRow.asof.desc())
                .limit(1)
            ).scalar_one_or_none()
            if row is None:
                return None
            return LesSignal(
                asof=row.asof,
                index=row.index_symbol,
                trend_up=row.trend_up,
                pullback=row.pullback,
                washout=row.washout,
                trend_break=row.trend_break,
                tier_pct=row.tier_pct,
                reasons=list(row.reasons or []),
            )
    except Exception:
        log.warning("latest_signal failed", exc_info=True)
        return None
