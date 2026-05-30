"""Journal page — EOD feed with cumulative realized P&L sparkline."""

import pandas as pd
import streamlit as st

import dashboard.data as _data

st.set_page_config(page_title="Journal | IBKR", layout="wide")


@st.cache_data(ttl=60)
def _load(limit: int) -> list[dict]:
    return _data.get_journal_feed(limit=limit)


st.title("EOD Journal")

limit = st.sidebar.slider("Entries to show", min_value=5, max_value=90, value=30, step=5)

rows = _load(limit)

if not rows:
    st.info("No journal entries yet. Run the EOD report to populate this page.")
else:
    df = pd.DataFrame(rows)

    # Cumulative realized P&L sparkline (ascending date order)
    pnl_series = df[["Date", "Realized P&L"]].dropna().copy()
    if not pnl_series.empty:
        pnl_series = pnl_series.sort_values("Date")
        pnl_series["Cumulative P&L"] = pnl_series["Realized P&L"].cumsum()
        st.subheader("Cumulative Realized P&L")
        st.line_chart(pnl_series.set_index("Date")["Cumulative P&L"])
        st.divider()

    # Journal table — narratives truncated; expand for full text
    st.subheader("Journal Entries")
    display_cols = ["Date", "Realized P&L", "Unrealized P&L", "Fills", "Positions", "Net Delta"]
    available = [c for c in display_cols if c in df.columns]
    st.dataframe(
        df[available].style.format(
            {
                "Realized P&L": lambda v: f"${v:+,.2f}" if v is not None else "—",
                "Unrealized P&L": lambda v: f"${v:+,.2f}" if v is not None else "—",
                "Net Delta": lambda v: f"{v:+.2f}" if v is not None else "—",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    # Expandable narratives
    st.subheader("Narratives")
    for row in rows:
        narrative = row.get("Narrative", "")
        if narrative:
            with st.expander(f"{row['Date']}"):
                st.write(narrative)
