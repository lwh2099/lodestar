"""Lodestar — entry point and navigation.

Run with:  streamlit run app.py   (or double-click "Start Lodestar.bat")
"""

import streamlit as st

from ui import theme

st.set_page_config(
    page_title="Lodestar",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)

theme.apply()

# Material Symbols (outlined line icons) for a clean, uniform sidebar.
pages = [
    st.Page("views/cockpit.py", title="Regime Compass",
            icon=":material/explore:", default=True),
    st.Page("views/macro.py", title="Macro", icon=":material/account_balance:"),
    st.Page("views/market.py", title="Market", icon=":material/show_chart:"),
    st.Page("views/sentiment.py", title="Sentiment", icon=":material/thermostat:"),
    st.Page("views/granny_shots.py", title="Granny Shots",
            icon=":material/track_changes:"),
    st.Page("views/seasonality.py", title="Seasonality",
            icon=":material/calendar_month:"),
]

navigation = st.navigation(pages)

with st.sidebar:
    st.markdown("")
    if st.button("⟳ Update all data", width="stretch",
                 help="Force-refresh every source: FRED, market history, "
                      "sentiment. Takes ~1 minute."):
        from core import refresh

        all_jobs = refresh.jobs()
        bar = st.progress(0.0, text="Starting update...")
        ok_count, cached_count, failed = 0, 0, []
        for i, job in enumerate(all_jobs):
            bar.progress((i + 1) / len(all_jobs), text=job.name)
            outcome = refresh.run_job(job)
            if outcome.ok and not outcome.stale:
                ok_count += 1
            elif outcome.ok:
                cached_count += 1
            else:
                failed.append(outcome.name)
        bar.empty()
        message = f"Updated {ok_count}/{len(all_jobs)} sources."
        if cached_count:
            message += f" {cached_count} kept cached data (source down)."
        st.success(message)
        for name in failed:
            st.warning(f"No data: {name}")

    st.markdown(
        '<div style="font-size:11px;color:#74706A;margin-top:24px;">'
        "Free data: FRED · Yahoo Finance · CNN<br>"
        "Quotes delayed 15–20 min. Personal research, not investment advice."
        "</div>",
        unsafe_allow_html=True,
    )

navigation.run()
