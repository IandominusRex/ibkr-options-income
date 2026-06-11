# ARCHIVED — original location: dashboard/pages/03_orders.py
# Streamlit orders page. To reinstate: move back to dashboard/pages/03_orders.py.
"""Orders page — approval pipeline: pending → approved → queued → submitted → filled."""

import pandas as pd
import streamlit as st

import dashboard.data as _data

st.set_page_config(page_title="Orders | IBKR", layout="wide")

_STATE_COLORS = {
    "queued": "#d4ac0d",
    "submitted": "#2980b9",
    "filled": "#27ae60",
    "partial": "#8e44ad",
    "cancelled": "#7f8c8d",
    "rejected": "#c0392b",
}

_APPROVAL_COLORS = {
    "pending": "#d4ac0d",
    "approved": "#27ae60",
    "rejected": "#c0392b",
    "expired": "#7f8c8d",
}


@st.cache_data(ttl=60)
def _load() -> list[dict]:
    return _data.get_orders_pipeline()


st.title("Orders")

rows = _load()

if not rows:
    st.info("No orders or approvals yet.")
else:
    df = pd.DataFrame(rows)

    def _color_approval(val: object) -> str:
        color = _APPROVAL_COLORS.get(str(val), "")
        return f"color: {color}" if color else ""

    def _color_state(val: object) -> str:
        color = _STATE_COLORS.get(str(val), "")
        return f"color: {color}" if color else ""

    styled = (
        df.style.map(_color_approval, subset=["Approval"])
        .map(_color_state, subset=["Order State"])
        .format(
            {
                "Limit Price": lambda v: f"${v:.2f}" if v is not None else "—",
                "Avg Fill": lambda v: f"${v:.2f}" if v is not None else "—",
                "Filled Qty": lambda v: f"{v:.0f}" if v is not None else "—",
                "Commission": lambda v: f"${v:.2f}" if v is not None else "—",
            }
        )
    )

    st.dataframe(styled, use_container_width=True, hide_index=True)
    st.caption(f"{len(df)} approval records shown.")

    # Summary counts
    if len(df):
        counts = df["Approval"].value_counts()
        cols = st.columns(len(counts))
        for col, (status, count) in zip(cols, counts.items(), strict=False):
            col.metric(str(status).capitalize(), count)
