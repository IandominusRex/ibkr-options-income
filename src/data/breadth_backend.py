"""The Nasdaq-100 advance/decline history from thetrading.tools (risk-envelope Task 10a, ruling L2).

``https://www.thetrading.tools/data/market_breadth/ad_line.json``: a free JSON series with
``ndx_advancing`` / ``ndx_declining`` per day from 2016-11, computed by that provider from its own
stock universe, not from official counts. Personal-use licence: attribution is in ARCHITECTURE.md
(the `src/data/` section) and the operator's use is the system's own research record only.

Reached only through ``src/data/factory.py::get_breadth_provider`` (asserted by
``tests/test_regime_fence.py``). Never raises: any error is an empty list and a warning, and the
nightly run then falls back to its own count.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx

from src.common.schemas import BreadthCount

log = logging.getLogger(__name__)

AD_LINE_URL = "https://www.thetrading.tools/data/market_breadth/ad_line.json"
_TIMEOUT_SECONDS = 30


def _rows(payload: object) -> list[object]:
    """The list of day objects, from a bare list or a ``{"data": [...]}`` wrapper."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "rows", "values"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return inner
    raise ValueError(f"unexpected breadth payload: {type(payload).__name__}")


class TheTradingToolsBreadth:
    """``BreadthProvider`` backed by thetrading.tools' ``ad_line.json``."""

    def history(self) -> list[BreadthCount]:
        """Every day with a usable Nasdaq-100 advancing and declining count, ascending.

        A row missing a field, with a non-integer count or an unparseable date is skipped.
        """
        try:
            response = httpx.get(AD_LINE_URL, timeout=_TIMEOUT_SECONDS)
            response.raise_for_status()
            rows = _rows(response.json())
        except Exception as exc:  # noqa: BLE001 - a feed error is "no history", never a crash
            log.warning("breadth feed (thetrading.tools) unavailable: %s", exc)
            return []
        out: list[BreadthCount] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                day = date.fromisoformat(str(row["date"])[:10])
                adv, dec = row["ndx_advancing"], row["ndx_declining"]
                if adv is None or dec is None:
                    continue
                out.append(BreadthCount(day=day, adv=int(adv), dec=int(dec), source="tt"))
            except (KeyError, ValueError, TypeError):
                continue
        out.sort(key=lambda c: c.day)
        if not out:
            log.warning("breadth feed (thetrading.tools) returned no usable rows")
        return out
