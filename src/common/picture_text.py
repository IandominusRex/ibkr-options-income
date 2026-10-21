"""The one neutral rendering of the market picture, shared by every reader.

The news writer and digest, the trade and roll reviewers, the EOD journal, ``/scan`` and the
spreads picker all show the model the same block, so a story can never read differently in two
places. Neutral module: it imports only ``src.common.schemas`` (and the standard library), so any
tier may use it and it can reach neither the engine nor a database. Target length is about 300
words (a few hundred tokens): the picture's builder bounds the stories and facts that go in.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from src.common.schemas import MarketPicture, PictureRegime

_ET = ZoneInfo("America/New_York")
_HEADER = "=== MARKET PICTURE ==="
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


def _regime_line(r: PictureRegime) -> str:
    notes: list[str] = []
    if r.base != r.effective:
        notes.append(f"base {r.base.value}")
    if r.eased_by_bottoming:
        notes.append("eased by a bottoming signal")
    if r.suspended:
        notes.append("limits suspended today")
    tail = f" ({'; '.join(notes)})" if notes else ""
    return f"{r.index}: {r.effective.value}{tail}"


def render_picture(p: MarketPicture | None, *, now: datetime, staleness_hours: float) -> str:
    """The picture as prompt text. ``None`` renders as unavailable; a picture older than
    *staleness_hours*, or one whose rebuild failed, is prefixed so the reader knows."""
    if p is None:
        return f"{_HEADER}\n(unavailable)"
    lines = [_HEADER]
    built = _aware(p.built_at)
    if p.stale or _aware(now) - built > timedelta(hours=staleness_hours):
        lines.append(f"PICTURE IS STALE (built {built.astimezone(_ET):%b %d %H:%M} ET)")
    lines += [_regime_line(r) for r in p.regimes]
    if p.regimes and p.regime_source == "news":
        lines.append(
            "(regime estimated by the news service; the trading process has not recorded one)"
        )
    lines += [f"{f.label}: {f.value}" for f in p.facts]
    if p.seasonality is not None:
        sv = p.seasonality
        lines.append(
            f"Seasonality (weak signal): SPY averaged {sv.avg_return_pct:+.1f}% in "
            f"{_MONTHS[sv.month - 1]} ({sv.years}-year average), up in {sv.up_share:.0%} of those years."
        )
    if p.events:
        lines.append("Upcoming: " + "; ".join(p.events))
    for st in p.stories:
        line = f"S{st.id} {st.title} (since {st.started_on:%b %d})"
        lines.append(f"{line}: {st.description}" if st.description else line)
    return "\n".join(lines)
