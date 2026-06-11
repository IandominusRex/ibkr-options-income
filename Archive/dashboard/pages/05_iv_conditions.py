# ARCHIVED — original location: dashboard/pages/05_iv_conditions.py
# Streamlit IV conditions page. To reinstate: move back to dashboard/pages/05_iv_conditions.py.
"""IV Conditions page — IV Rank/Percentile table and historical IV charts per symbol."""

import pandas as pd
import streamlit as st

import dashboard.data as _data

st.set_page_config(page_title="IV Conditions | IBKR", layout="wide")


@st.cache_data(ttl=60)
def _load_iv(lookback: int) -> dict:
    by_sym = _data.get_iv_history_by_symbol(lookback_days=lookback)
    rank_table = _data.compute_iv_rank_table(by_sym)
    return {"by_sym": by_sym, "rank_table": rank_table}


st.title("IV Conditions")

lookback = st.sidebar.slider("Lookback days", min_value=21, max_value=365, value=252, step=21)

data = _load_iv(lookback)
rank_table = data["rank_table"]
by_sym = data["by_sym"]

if not rank_table:
    st.info(
        "No IV history found. Run the backfill script (`python -m scripts.backfill_iv`) to seed data."
    )
else:
    # --- IV Rank/Percentile table ---
    st.subheader("IV Summary")
    df_rank = pd.DataFrame(rank_table)

    def _color_rank(val: object) -> str:
        if isinstance(val, (int, float)) and val >= 50:
            return "color: #27ae60; font-weight: bold"
        if isinstance(val, (int, float)) and val >= 30:
            return "color: #d4ac0d"
        return "color: #e74c3c"

    styled = df_rank.style.map(_color_rank, subset=["IV Rank", "IV Pct"]).format(
        {
            "Current IV %": "{:.1f}",
            "IV Rank": "{:.1f}",
            "IV Pct": "{:.1f}",
            "52w Low %": "{:.1f}",
            "52w High %": "{:.1f}",
        }
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # --- IV Rank bar chart ---
    st.subheader("IV Rank by Symbol")
    bar_df = pd.DataFrame(rank_table).set_index("Symbol")[["IV Rank"]]
    st.bar_chart(bar_df)

    st.divider()

    # --- Historical IV line charts per symbol ---
    st.subheader("IV History")
    symbols = sorted(by_sym.keys())
    selected = st.multiselect(
        "Symbols", options=symbols, default=symbols[:5] if len(symbols) > 5 else symbols
    )

    if selected:
        chart_data: dict[str, list] = {}
        index_dates: list = []
        for sym in selected:
            pts = by_sym.get(sym, [])
            if pts:
                dates = [str(d) for d, _ in pts]
                ivs = [round(iv * 100, 2) for _, iv in pts]
                chart_data[sym] = ivs
                if not index_dates:
                    index_dates = dates

        if chart_data and index_dates:
            iv_df = pd.DataFrame(chart_data, index=index_dates)
            st.line_chart(iv_df)
