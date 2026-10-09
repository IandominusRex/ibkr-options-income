"""Deterministic tags computed before any LLM sees an item (spec §5.4)."""

from __future__ import annotations

import re
from collections.abc import Iterable

from src.common.config import NewsTaggingCfg

AliasIndex = dict[str, re.Pattern[str]]

_QUANT = re.compile(
    r"(\d+(?:\.\d+)?\s?%|[$€£]\s?\d|\d+(?:\.\d+)?\s?(?:bp|bps|basis points)\b|\b\d[\d,.]*\s?(?:billion|million|trillion|bn|mn)\b)",
    re.I,
)


def build_alias_index(symbols: Iterable[str], aliases: dict[str, list[str]]) -> AliasIndex:
    """One compiled regex per symbol: ``$SYM`` always; bare ``SYM`` only when ≥ 2 chars and
    upper-case in the title (case-sensitive); company aliases case-insensitive whole words.
    A trailing hyphen is excluded so "V-shaped" / "Nvidia-adjacent" never match."""
    out: AliasIndex = {}
    for sym in sorted({s.upper() for s in symbols}):
        esc = re.escape(sym)
        parts = [rf"\${esc}\b"]
        if len(sym) >= 2:
            parts.append(rf"(?<![A-Za-z$]){esc}(?![A-Za-z0-9-])")
        for alias in aliases.get(sym, []):
            parts.append(rf"(?i:(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z-]))")
        out[sym] = re.compile("|".join(parts))
    return out


def tag_tickers(title: str, index: AliasIndex) -> list[str]:
    return sorted(sym for sym, pat in index.items() if pat.search(title))


def _has_any(text_lower: str, terms: Iterable[str]) -> bool:
    return any(re.search(rf"(?<![a-z]){re.escape(t.lower())}(?![a-z])", text_lower) for t in terms)


def tag_events(title: str, *, scheduled: bool, cfg: NewsTaggingCfg) -> list[str]:
    low = title.lower()
    tags: list[str] = []
    if scheduled:
        tags.append("scheduled")
    if _has_any(low, cfg.rumor_terms):
        tags.append("rumor")
    if _QUANT.search(title):
        tags.append("quantified")
    if _has_any(low, cfg.forward_terms):
        tags.append("forward_looking")
    return tags


def topic_class(title: str, cfg: NewsTaggingCfg) -> str:
    low = title.lower()
    for topic, terms in cfg.topic_terms.items():
        if _has_any(low, terms):
            return topic
    return "other"


def det_sentiment(text: str) -> float:
    """−1..+1 polarity. VADER (+ the existing keyword bias) — reuses src.analytics.sentiment's
    helpers so the news store and the scan score with one lexicon."""
    if not text:
        return 0.0
    from src.analytics.sentiment import _keyword_bias, _vader_compound

    kb = _keyword_bias(text)
    return kb if kb != 0.0 else _vader_compound(text)
