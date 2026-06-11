# ARCHIVED — original location: dashboard/pages/01_portfolio.py
# Streamlit portfolio page. To reinstate: move back to dashboard/pages/01_portfolio.py.
"""Portfolio page — account snapshot from the latest EOD journal entry."""

import streamlit as st

import dashboard.data as _data

st.set_page_config(page_title="Portfolio | IBKR", layout="wide")


@st.cache_data(ttl=60)
def _load() -> dict:
    return _data.get_portfolio_summary()


p = _load()

st.title("Portfolio")
if p["entry_date"]:
    st.caption(f"Last EOD report: {p['entry_date']}")
else:
    st.warning("No journal entries found. Run the EOD report to populate this page.")

# KPI row
c1, c2, c3, c4 = st.columns(4)
c1.metric("Net Liquidation", f"${p['nlv']:,.2f}" if p["nlv"] is not None else "—")
c2.metric("Buying Power", f"${p['buying_power']:,.2f}" if p["buying_power"] is not None else "—")
c3.metric("Realized P&L", f"${p['realized_pnl']:+,.2f}")
c4.metric("Unrealized P&L", f"${p['unrealized_pnl']:+,.2f}")

c5, c6 = st.columns(2)
c5.metric("Open Positions", str(p["open_positions"]))
net_delta = p["net_delta"]
c6.metric(
    "Net Delta Exposure",
    f"{net_delta:+.2f}" if isinstance(net_delta, float) else "—",
    help="Sum of (delta × position × 100) across all short options.",
)

st.divider()

col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Top Movers")
    if p["top_movers"]:
        for sym in p["top_movers"]:
            st.write(f"- {sym}")
    else:
        st.write("—")

with col_b:
    st.subheader("Tomorrow's Watchlist")
    if p["tomorrow_watchlist"]:
        for sym in p["tomorrow_watchlist"]:
            st.write(f"- {sym}")
    else:
        st.write("—")

st.divider()
st.subheader("EOD Narrative")
if p["narrative"]:
    st.write(p["narrative"])
else:
    st.write("No narrative available.")
