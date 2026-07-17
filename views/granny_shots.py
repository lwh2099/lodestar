"""Granny Shots — 7-theme cross-section engine, equal-weight portfolio."""

import pandas as pd
import streamlit as st

from core import granny
from ui import charts
from ui import components as ui

force = ui.page_header(
    "Granny Shots",
    "Seven themes vote on a curated universe; names hit by ≥2 themes enter an "
    "equal-weight portfolio, rebalanced quarterly. Edit constituents in "
    "config/themes.yaml.")

with st.spinner("Running the cross-section engine..."):
    result = granny.run(force=force)

for warning in result.warnings:
    st.info(warning)

# --------------------------------------------------------------------------
# Headline tiles
# --------------------------------------------------------------------------

n_selected = len(result.selection)
tiles = [
    ui.metric_tile("next rebalance", result.next_rebalance.strftime("%b %d, %Y"),
                   note="first weekday of Jan / Apr / Jul / Oct", small=True),
    ui.metric_tile("days to rebalance", str(result.days_to_rebalance)),
    ui.metric_tile("candidate universe", str(len(result.universe)),
                   note="union of all theme pools"),
    ui.metric_tile("selected (≥2 hits)", str(n_selected),
                   note=f"{1 / n_selected:.1%} each, equal weight"
                        if n_selected else "no hits yet"),
]
ui.render_tiles(tiles)

# --------------------------------------------------------------------------
# Theme status
# --------------------------------------------------------------------------

st.header("Themes")

theme_rows = []
for theme in result.themes:
    theme_rows.append({
        "Theme": theme.label,
        "Type": theme.kind,
        "Status": "active" if theme.active else "inactive",
        "Members": len(theme.members),
        "Current read": theme.note,
    })
st.dataframe(pd.DataFrame(theme_rows), hide_index=True, width="stretch")

# --------------------------------------------------------------------------
# Portfolio
# --------------------------------------------------------------------------

st.header("Portfolio")

if result.selection.empty:
    st.warning("No name is currently hit by two or more themes. Loosen the "
               "theme lists in config/themes.yaml or wait for dynamic themes "
               "to activate.")
else:
    portfolio = granny.attach_market_data(result.selection, force=force)

    col_table, col_pie = st.columns([3, 2])
    with col_table:
        display = portfolio.copy()
        display["weight"] = display["weight"].map(lambda w: f"{w:.1%}")
        for col in ("1d_pct", "3m_pct"):
            if col in display.columns:
                display[col] = display[col].map(
                    lambda v: f"{v:+.1f}%" if pd.notna(v) else "—")
        if "price" in display.columns:
            display["price"] = display["price"].map(
                lambda v: f"{v:,.2f}" if pd.notna(v) else "—")
        st.dataframe(display, width="stretch", height=430)
        st.download_button(
            "Download portfolio CSV",
            portfolio.to_csv().encode("utf-8"),
            file_name=f"granny_shots_{result.next_rebalance:%Y%m%d}.csv",
            mime="text/csv")
    with col_pie:
        ui.caption("Sector distribution (equal-weight names per sector)")
        sector_counts = result.selection["sector"].value_counts()
        charts.show(charts.donut(sector_counts, height=380), key="sector_donut")

# --------------------------------------------------------------------------
# Hit matrix
# --------------------------------------------------------------------------

st.header("Hit matrix")

show_all = st.toggle("Show names with fewer than 2 hits", value=False)
hits = result.hit_matrix.sum(axis=1)
matrix = result.hit_matrix.copy()
matrix.insert(0, "hits", hits)
matrix = matrix[matrix["hits"] >= (1 if show_all else granny.MIN_HITS)]
matrix = matrix.sort_values("hits", ascending=False)
pretty = matrix.replace({True: "✓", False: ""})
st.dataframe(pretty, width="stretch", height=420)
ui.caption(f"{len(matrix)} names shown · a ✓ means the theme currently "
           "includes the ticker.")

# --------------------------------------------------------------------------
# Theme overlap
# --------------------------------------------------------------------------

st.header("Theme overlap")
ui.caption("Shared constituents between each pair of active themes — which "
           "combinations drive the portfolio.")
charts.show(charts.heatmap(result.overlap.astype(float), units="",
                           diverging=False, fmt=".0f", height=380),
            key="overlap_heatmap")
