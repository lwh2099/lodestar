"""Macro — full-history official FRED series, organised by category.

Within a category, series that share the same unit and transform (so the same
y-axis scale) are drawn together on one chart — e.g. all Treasury yields on a
single axis, each a different colour. Series that stand alone keep their own
chart.
"""

import html
from collections import OrderedDict

import pandas as pd
import streamlit as st

from core import fred
from ui import charts
from ui import components as ui
from ui.theme import COLORS

force = ui.page_header("Macro")

categories = fred.categories()
labels = [label for _, label in categories]
keys = {label: key for key, label in categories}

chosen = st.radio("Category", labels, horizontal=True,
                  label_visibility="collapsed")

sids = fred.series_for_category(keys[chosen])
if not sids:
    st.info("No series configured for this category.")
    st.stop()


def _latest_line(snap: fred.Snapshot) -> str:
    """One 'Name  value  ▲delta' HTML row for a single series.

    Delta colour tracks the direction of the move itself — up is green, down
    is red, unchanged is grey — so it reads consistently across every series
    in a subsection (independent of whether a rise is "good" for that series).
    """
    if snap.delta is None or snap.delta == 0:
        color = COLORS["text2"]
    elif snap.delta > 0:
        color = COLORS["up"]
    else:
        color = COLORS["down"]
    delta_html = ""
    if snap.delta is not None:
        delta_html = (f'<span style="font-family:monospace;font-size:12px;'
                      f'color:{color};margin-left:8px;">'
                      f'{html.escape(snap.delta_text())}</span>')
    return (f'<div style="margin-bottom:-6px;"><span style="font-weight:600;">'
            f'{html.escape(snap.name)}</span>'
            f'<span style="font-family:monospace;font-size:15px;margin-left:10px;">'
            f'{html.escape(snap.value_text())}</span>{delta_html}</div>')


def _footer(snaps: list[fred.Snapshot]) -> None:
    stale = any(s.is_stale for s in snaps)
    ids = " · ".join(s.sid for s in snaps)
    asof = max(s.latest_date for s in snaps)
    updated = max(s.fetched_at for s in snaps)
    note = " · cached (source down)" if stale else ""
    ui.caption(f"{ids} · as of {asof:%Y-%m-%d}"
               f" · updated {updated.astimezone():%Y-%m-%d %H:%M}{note}")


def _single_block(snap: fred.Snapshot) -> None:
    st.markdown(_latest_line(snap), unsafe_allow_html=True)
    units = snap.units if snap.units in ("%", "pp") else ""
    charts.show(
        charts.line(snap.display, snap.name, units=units,
                    initial_years=10, height=300),
        key=f"chart_{snap.sid}")
    _footer([snap])


def _group_block(snaps: list[fred.Snapshot]) -> None:
    """Several like-scaled series on one chart, one colour each."""
    for snap in snaps:
        st.markdown(_latest_line(snap), unsafe_allow_html=True)
    frame = pd.DataFrame({s.name: s.display for s in snaps})
    units = snaps[0].units if snaps[0].units in ("%", "pp") else ""
    key = "chart_" + "_".join(s.sid for s in snaps)
    charts.show(
        charts.multi_line(frame, units=units, range_buttons=True,
                          initial_years=10, height=340),
        key=key)
    _footer(snaps)


# Group series by (units, transform): same suffix + same transform means the
# same y-axis scale, so they belong on one chart.
groups: "OrderedDict[tuple, list[fred.Snapshot]]" = OrderedDict()
for sid in sids:
    snap = fred.snapshot(sid, force=force)
    if not snap.ok:
        st.warning(f"{sid}: no data ({snap.error or 'source unavailable'})")
        continue
    meta = fred.series_meta(sid)
    gkey = (meta.get("units", ""), meta.get("transform", "level"))
    groups.setdefault(gkey, []).append(snap)

multi = [snaps for snaps in groups.values() if len(snaps) > 1]
singles = [snaps[0] for snaps in groups.values() if len(snaps) == 1]

# Combined charts first (full width), then any singletons in a 2-column grid.
for snaps in multi:
    _group_block(snaps)

for i in range(0, len(singles), 2):
    cols = st.columns(2)
    for col, snap in zip(cols, singles[i:i + 2]):
        with col:
            _single_block(snap)
