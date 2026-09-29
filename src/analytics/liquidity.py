"""Liquidity scoring and gate checks for option quotes.

Pure math on OptionQuote objects — no external calls, no DB access (beyond reading config).
Thresholds are read from config/risk_limits.yaml via get_config().
"""

from __future__ import annotations

import math
from datetime import datetime, time
from zoneinfo import ZoneInfo

from src.common.config import get_config
from src.common.schemas import OptionQuote

_ET = ZoneInfo("America/New_York")


def volume_gate_active(now_et: time | None = None) -> bool:
    """True when the day-volume liquidity gate should be enforced (N19).

    Option volume often hasn't printed at a 9:45 ET scan, so before the configured
    `liquidity.morning_volume_cutoff_et` the gate is skipped (OI + spread carry the check). Pass
    `now_et` for deterministic tests; defaults to the current ET wall-clock. A missing/blank
    cutoff means "always enforce".
    """
    raw = get_config().risk["liquidity"].get("morning_volume_cutoff_et")
    if not raw:
        return True
    try:
        hh, mm = (int(x) for x in str(raw).split(":", 1))
        cutoff = time(hh, mm)
    except (ValueError, TypeError):
        return True
    current = now_et if now_et is not None else datetime.now(_ET).time()
    return current >= cutoff


def liquidity_failures(quote: OptionQuote, *, enforce_volume: bool = True) -> list[str]:
    """Every liquidity gate *quote* fails, as precise reason codes (empty = passes).

    Replaces a bare bool that collapsed five distinct failure modes into one ``illiquid``
    code, which made "SOXL failed liquidity 684 times" impossible to act on (2026-09 post-
    mortem). Missing data fails its gate (conservative default), but gets its own *_missing
    code so an IBKR data gap is distinguishable from a genuinely thin contract. When
    `enforce_volume` is False the day-volume codes are skipped (N19 — early-session, before
    volume has printed); OI and spread still apply. Morning-scan callers pass
    `enforce_volume=volume_gate_active()`.
    """
    cfg = get_config().risk["liquidity"]
    out: list[str] = []
    if quote.bid is None or quote.ask is None or quote.ask <= 0:
        out.append("illiquid_no_quote")
    else:
        if quote.bid == 0:
            out.append("illiquid_zero_bid")
        spread = quote.spread_pct
        if spread is None or spread > cfg["max_bid_ask_spread_pct"]:
            out.append("illiquid_spread_wide")
    if quote.open_interest is None:
        out.append("illiquid_oi_missing")
    elif quote.open_interest < cfg["min_open_interest"]:
        out.append("illiquid_oi_low")
    if enforce_volume:
        if quote.volume is None:
            out.append("illiquid_volume_missing")
        elif quote.volume < cfg["min_option_volume"]:
            out.append("illiquid_volume_low")
    return out


def passes_liquidity_gates(quote: OptionQuote, *, enforce_volume: bool = True) -> bool:
    """True iff the quote clears every liquidity gate. See :func:`liquidity_failures`."""
    return not liquidity_failures(quote, enforce_volume=enforce_volume)


def score_liquidity(quote: OptionQuote) -> float:
    """Return a 0–100 liquidity score (higher is better).

    Averages three sub-scores: spread, open interest, and volume.
    None values are treated as 0 (penalise missing data).
    """
    cfg = get_config().risk["liquidity"]
    max_spread: float = cfg["max_bid_ask_spread_pct"]

    spread = quote.spread_pct
    spread_score = max(0.0, 100.0 - (spread / max_spread) * 100.0) if spread is not None else 0.0

    oi = quote.open_interest
    # Log-scale so high-liquidity options (OI 50k+) score distinctly better than barely-passing ones.
    # log10(1 + oi/10) normalized so OI=1000 ≈ 70, OI=10000 ≈ 85, OI=100000 ≈ 100.
    oi_score = (
        min(100.0, math.log10(1 + (oi or 0) / 10) / math.log10(1001) * 100.0)
        if oi is not None
        else 0.0
    )

    vol = quote.volume
    vol_score = (
        min(100.0, math.log10(1 + (vol or 0)) / math.log10(101) * 100.0) if vol is not None else 0.0
    )

    return round((spread_score + oi_score + vol_score) / 3.0, 2)
