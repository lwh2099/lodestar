"""Sentiment — contrarian thermometer from VIX and CNN Fear & Greed."""

import pandas as pd
import streamlit as st

from core import market, sentiment
from ui import charts
from ui import components as ui

force = ui.page_header("Sentiment")

# The concluded score is the CNN Fear & Greed contrarian reading (CNN already
# embeds VIX; see core.sentiment.compute). VIX is shown as context / fallback.
thermo = sentiment.compute(force=force)

col_gauge, col_parts = st.columns([2, 3])

with col_gauge:
    if thermo.score is not None:
        charts.show(charts.gauge(thermo.score, thermo.verdict),
                    key="thermo_gauge")
    else:
        st.error("All sentiment sources are down and no cache exists yet.")

with col_parts:
    st.subheader("Components")
    tiles = []
    for comp in thermo.components:
        if comp.score is None:
            tiles.append(ui.metric_tile(
                label=comp.label, value="—",
                note="source unavailable", stale=True))
        else:
            tiles.append(ui.metric_tile(
                label=comp.label,
                value=comp.value_text,
                delta=comp.raw_text,
                direction=0,
                stale=comp.is_stale))
    ui.render_tiles(tiles)

# --------------------------------------------------------------------------
# VIX vs Fear & Greed over time (context, not its own section)
# --------------------------------------------------------------------------

vix_hist = market.history(["^VIX"], period="max", ttl=market.EOD_TTL,
                          force=force)
fng = sentiment.fear_greed(force=force)

series_map: dict[str, pd.Series] = {}
source_names: list[str] = []
if vix_hist.ok and "^VIX" in vix_hist.data.columns:
    series_map["VIX"] = vix_hist.data["^VIX"].dropna()
    source_names.append("Yahoo Finance (VIX)")

fng_hist = fng.data.get("history") if fng.ok else None
if fng_hist is not None and len(fng_hist):
    series_map["CNN Fear & Greed"] = fng_hist["score"]
    source_names.append("CNN (Fear & Greed)")

if series_map:
    # Auto-aligned on date (outer join); each series keeps its own values, so a
    # shorter history just leaves gaps rather than distorting the shared axis.
    combined = pd.DataFrame(series_map).sort_index()
    charts.show(charts.multi_line(combined, height=360, range_buttons=True,
                                  initial_years=5),
                key="vix_fng_chart")
    if vix_hist.ok:
        ui.source_status(vix_hist, source_names=source_names)
    if "CNN Fear & Greed" not in series_map:
        st.info("CNN Fear & Greed history unavailable"
                + (f" — {fng.error}" if fng.error else "") + ".")
else:
    st.info("Neither VIX nor CNN Fear & Greed history is available right now.")
