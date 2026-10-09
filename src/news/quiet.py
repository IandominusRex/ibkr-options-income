"""Quiet hours (spec §7.2, D8): non-critical posts go out silently, nothing is held."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from src.common.config import NewsQuietCfg


def _t(hhmm: str) -> time:
    h, m = hhmm.split(":")
    return time(int(h), int(m))


def is_quiet(now: datetime, cfg: NewsQuietCfg) -> bool:
    local = now.astimezone(ZoneInfo(cfg.tz)).time()
    start, end = _t(cfg.start), _t(cfg.end)
    if start <= end:
        return start <= local < end
    return local >= start or local < end


def silent_for(now: datetime, *, critical: bool, cfg: NewsQuietCfg) -> bool:
    if not is_quiet(now, cfg):
        return False
    return not (critical and cfg.critical_breaks_quiet)
