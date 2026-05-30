"""Candidates page — top-scored CC/CSP candidates from the latest scan."""

import pandas as pd
import streamlit as st

import dashboard.data as _data

st.set_page_config(page_title="Candidates | IBKR", layout="wide")


@st.cache_data(ttl=60)
def _load() -> list[dict]:
    return _data.get_candidates()


@st.cache_data(ttl=60)
def _run_id() -> str | None:
    return _data.get_latest_run_id()


st.title("Candidates")

run_id = _run_id()
if run_id:
    st.caption(f"Run ID: `{run_id}`")
else:
    st.info("No candidate data found. Run the morning scan to populate this page.")

rows = _load()

if not rows:
    st.write("No candidates for this run.")
else:
    df = pd.DataFrame(rows)
    display_cols = ["Symbol", "Strategy", "Right", "Strike", "Expiry", "Score", "Risk", "Claude"]
    df_display = df[display_cols].copy()

    def _color_risk(val: object) -> str:
        if val == "pass":
            return "background-color: #1a472a; color: #b7e1c5"
        if val == "reject":
            return "background-color: #5c1a1a; color: #f5b7b1"
        return ""

    def _color_claude(val: object) -> str:
        if val in ("sell", "approved"):
            return "color: #27ae60"
        if val in ("skip", "wait"):
            return "color: #e67e22"
        return ""

    styled = df_display.style.map(_color_risk, subset=["Risk"]).map(
        _color_claude, subset=["Claude"]
    )

    st.dataframe(styled, use_container_width=True, hide_index=True)
    st.caption(f"{len(df)} candidates shown.")
