"""Static price charts for ticker/earnings/close-recap cards (spec §7.1). Headless (Agg)."""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

_BG, _FG, _MUTED = "#111418", "#e6e8eb", "#8a9099"


def build_figure(
    daily: pd.DataFrame,
    *,
    title: str,
    support: list[float],
    resistance: list[float],
    strikes: list[tuple[float, str]],
    event_day: date | None,
) -> Figure | None:
    if daily is None or daily.empty or "Close" not in daily:
        return None
    close = daily["Close"].dropna().iloc[-130:]
    full = daily["Close"].dropna()
    fig, ax = plt.subplots(figsize=(8, 4), dpi=120)
    fig.patch.set_facecolor(_BG)
    ax.set_facecolor(_BG)
    ax.plot(close.index, close.values, color=_FG, lw=1.4, label="Close")
    ax.plot(
        close.index,
        full.rolling(50).mean().reindex(close.index).values,
        color="#5b9bd5",
        lw=1,
        label="SMA50",
    )
    ax.plot(
        close.index,
        full.rolling(200).mean().reindex(close.index).values,
        color="#c9a227",
        lw=1,
        label="SMA200",
    )
    for s in support:
        ax.axhline(s, color="#3fa34d", lw=0.8, ls=":")
    for r in resistance:
        ax.axhline(r, color="#d9534f", lw=0.8, ls=":")
    for k, label in strikes:
        ax.axhline(k, color="#e07b39", lw=1.2, ls="--")
        ax.text(close.index[0], k, f" {label}", color="#e07b39", va="bottom", fontsize=8)
    if event_day is not None:
        ax.axvline(pd.Timestamp(event_day), color=_MUTED, lw=0.8)
    ax.set_title(title, color=_FG, fontsize=11, loc="left")
    ax.tick_params(colors=_MUTED, labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#2a2f36")
    ax.legend(loc="upper left", fontsize=7, facecolor=_BG, edgecolor="#2a2f36", labelcolor=_FG)
    fig.tight_layout()
    return fig


def to_png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    plt.close(fig)
    return buf.getvalue()


def price_chart(
    daily: pd.DataFrame,
    *,
    title: str,
    support: list[float],
    resistance: list[float],
    strikes: list[tuple[float, str]],
    event_day: date | None,
) -> bytes | None:
    fig = build_figure(
        daily,
        title=title,
        support=support,
        resistance=resistance,
        strikes=strikes,
        event_day=event_day,
    )
    return None if fig is None else to_png(fig)


def save_chart(png: bytes, charts_dir: Path, post_id: int) -> str:
    charts_dir.mkdir(parents=True, exist_ok=True)
    path = charts_dir / f"{post_id}.png"
    path.write_bytes(png)
    return str(path)
