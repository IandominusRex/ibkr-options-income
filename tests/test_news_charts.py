from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from src.news import charts


def _daily(n=200):
    idx = pd.bdate_range("2026-01-02", periods=n)
    return pd.DataFrame({"Close": np.linspace(150, 180, n)}, index=idx)


def test_figure_has_close_smas_levels_and_strike() -> None:
    fig = charts.build_figure(
        _daily(),
        title="NVDA",
        support=[170.0],
        resistance=[190.0],
        strikes=[(165.0, "165P 14 DTE")],
        event_day=date(2026, 9, 30),
    )
    ax = fig.axes[0]
    labels = {line.get_label() for line in ax.get_lines()}
    assert {"Close", "SMA50", "SMA200"} <= labels
    assert any("165P" in t.get_text() for t in ax.texts)
    png = charts.to_png(fig)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


def test_empty_data_returns_none(tmp_path) -> None:
    assert (
        charts.price_chart(
            pd.DataFrame(), title="x", support=[], resistance=[], strikes=[], event_day=None
        )
        is None
    )
    path = charts.save_chart(b"\x89PNG", tmp_path, 7)
    assert path.endswith("7.png")
