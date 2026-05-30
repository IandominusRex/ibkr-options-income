"""IBKR Options Income System — Streamlit dashboard home.

Run with:  streamlit run dashboard/app.py
"""

import streamlit as st

st.set_page_config(
    page_title="IBKR Income System",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

import dashboard.data as _data  # noqa: E402  (after set_page_config)


@st.cache_data(ttl=60)
def _load_portfolio() -> dict:
    return _data.get_portfolio_summary()


# --- Sidebar ---
with st.sidebar:
    st.title("IBKR Income System")
    if st.button("Refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption("Data auto-refreshes every 60 s.")

# --- KPI row ---
p = _load_portfolio()

st.header("Overview")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric(
    "NLV",
    f"${p['nlv']:,.0f}" if p["nlv"] is not None else "—",
)
c2.metric(
    "Buying Power",
    f"${p['buying_power']:,.0f}" if p["buying_power"] is not None else "—",
)
c3.metric(
    "Realized P&L",
    f"${p['realized_pnl']:+,.2f}",
)
c4.metric(
    "Unrealized P&L",
    f"${p['unrealized_pnl']:+,.2f}",
)
c5.metric(
    "Open Positions",
    str(p["open_positions"]),
)

if p["entry_date"]:
    st.caption(f"Last EOD report: {p['entry_date']}")

# --- Watchlists ---
col_a, col_b = st.columns(2)
with col_a:
    if p["top_movers"]:
        st.subheader("Top Movers")
        for sym in p["top_movers"]:
            st.write(f"- {sym}")

with col_b:
    if p["tomorrow_watchlist"]:
        st.subheader("Tomorrow's Watchlist")
        for sym in p["tomorrow_watchlist"]:
            st.write(f"- {sym}")

# --- Latest narrative ---
if p["narrative"]:
    with st.expander("Latest EOD Narrative"):
        st.write(p["narrative"])

if not p["entry_date"]:
    st.info("No journal entries yet. Run the morning scan and EOD report to populate data.")
