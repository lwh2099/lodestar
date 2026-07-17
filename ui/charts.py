"""Plotly chart builders on the warm template.

Rules applied throughout (from the dataviz method):
  - one y-axis per chart, never dual axes
  - 2px lines, thin bars, recessive grid
  - legend shown whenever there are >= 2 series; single series charts are
    named by their title instead
  - hover tooltips on everything by default
"""

from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.theme import (CHART_COLORWAY, COLORS, DIVERGING, FONT_DISPLAY,
                      FONT_MONO, MONTH_COLORWAY)

# Range buttons live top-left, clear of the hover modebar (which sits top-right).
RANGE_SELECTOR = dict(
    buttons=[
        dict(count=1, label="1Y", step="year", stepmode="backward"),
        dict(count=5, label="5Y", step="year", stepmode="backward"),
        dict(count=10, label="10Y", step="year", stepmode="backward"),
        dict(step="all", label="Max"),
    ],
    bgcolor=COLORS["surface2"],
    activecolor=COLORS["accent"],
    font=dict(size=11),
    x=0, xanchor="left", y=1.06, yanchor="bottom",
)

# ── One place that controls chart interaction ────────────────────────────────
# Continuous time-series charts (line / multi_line / year_lines) are pan/zoom
# interactive, TradingView-style: the wheel and drag act on the TIME axis only,
# and the value axis auto-fits to whatever window is visible. Everything
# categorical (bar / hbar / heatmap / donut / gauge) is static — hover still
# works, but no drag or scroll. A builder marks itself static with
# layout.meta = "static"; show() reads that flag, so the interactive-vs-static
# rule lives in one place.
#
# Why the custom component: plotly has no native "autoscale y to visible x"
# (plotly.js #6995, backlogged for years) and st.plotly_chart surfaces only
# selection events, so the standard TradingView-style workaround is a small JS
# handler on plotly_relayout that refits y from the visible points. The y-axis
# stays fixedrange for the USER (no 2-D wheel zoom compounding into a distorted,
# unresettable state) while the handler adjusts it programmatically.
PAN_ZOOM = {"scrollZoom": True, "displaylogo": False,
            "modeBarButtonsToRemove": ["select2d", "lasso2d"]}
_STATIC_CONFIG = {"displayModeBar": False}

_APP_ROOT = Path(__file__).resolve().parent.parent
# CDN fallback if static file serving is off; version matches the plotly.js
# bundled with the installed plotly.py (6.8 ships plotly.js 3.6.0).
_PLOTLY_CDN = "https://cdn.plot.ly/plotly-3.6.0.min.js"


@lru_cache(maxsize=1)
def _plotlyjs_src() -> str:
    """Write the bundled plotly.js into ./static once and return its URL.

    Streamlit serves ./static at /app/static (server.enableStaticServing in
    .streamlit/config.toml), so every chart iframe shares one browser-cached
    copy and works offline — no CDN round-trip per chart.
    """
    import plotly
    from plotly.offline import get_plotlyjs

    name = f"plotly-{plotly.__version__}.min.js"
    path = _APP_ROOT / "static" / name
    if not path.exists():
        path.parent.mkdir(exist_ok=True)
        path.write_text(get_plotlyjs(), encoding="utf-8")
    return f"/app/static/{name}"


# Rendered inside an st.iframe. The fitY handler reads plotted
# points from gd.calcdata (already numeric, dates in ms, matching axis.r2l
# units) and refits the y-axis to the visible x-window with 6% headroom —
# live while panning (plotly_relayouting), after wheel zoom / range buttons /
# double-click reset (plotly_relayout), and on legend toggles (plotly_restyle).
# Our own relayout writes only yaxis keys, which touchesX() ignores, so the
# handler never re-triggers itself.
_AUTOFIT_TEMPLATE = """
<meta charset="utf-8">
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap');
html, body { margin: 0; padding: 0; background: transparent; overflow: hidden; }
#gd { width: 100%; height: __HEIGHT__px; }
</style>
<script src="__JS_SRC__"></script>
<script>
  if (!window.Plotly) document.write('<script src="__CDN__"><\\/script>');
</script>
<div id="gd"></div>
<script>
(function () {
  var gd = document.getElementById("gd");
  var spec = __SPEC__;
  var config = __CONFIG__;

  function fitY() {
    var xa = gd._fullLayout && gd._fullLayout.xaxis;
    if (!xa || !xa.range) return;
    var lo = xa.r2l(xa.range[0]), hi = xa.r2l(xa.range[1]);
    if (lo > hi) { var t = lo; lo = hi; hi = t; }
    var min = Infinity, max = -Infinity;
    var cd = gd.calcdata || [];
    for (var i = 0; i < cd.length; i++) {
      var tr = gd._fullData[i];
      if (!tr || tr.visible !== true) continue;
      for (var j = 0; j < cd[i].length; j++) {
        var xv = cd[i][j].x, yv = cd[i][j].y;
        if (!isFinite(xv) || !isFinite(yv) || xv < lo || xv > hi) continue;
        if (yv < min) min = yv;
        if (yv > max) max = yv;
      }
    }
    if (!isFinite(min)) return;
    var pad = (max - min) * 0.06 || Math.abs(max) * 0.06 || 1;
    Plotly.relayout(gd, {"yaxis.range": [min - pad, max + pad]});
  }

  var raf = null;
  function queueFit() {
    if (raf !== null) return;
    raf = requestAnimationFrame(function () { raf = null; fitY(); });
  }
  function touchesX(e) {
    if (!e) return false;
    for (var k in e) { if (k.indexOf("xaxis") === 0) return true; }
    return false;
  }

  Plotly.newPlot(gd, spec.data, spec.layout, config).then(function () {
    gd.on("plotly_relayout", function (e) { if (touchesX(e)) queueFit(); });
    gd.on("plotly_relayouting", function (e) { if (touchesX(e)) queueFit(); });
    gd.on("plotly_restyle", queueFit);
    fitY();
  });
})();
</script>
"""


def _show_autofit_y(fig: go.Figure, *, config: dict) -> None:
    """Embed an interactive figure with the y-follows-x autofit handler."""
    height = int(fig.layout.height or 360)
    # "</" would close the surrounding <script> tag if a label ever contained
    # it; escaping is a no-op for JSON semantics.
    spec = fig.to_json().replace("</", "<\\/")
    html = (_AUTOFIT_TEMPLATE
            .replace("__JS_SRC__", _plotlyjs_src())
            .replace("__CDN__", _PLOTLY_CDN)
            .replace("__HEIGHT__", str(height))
            .replace("__SPEC__", spec)
            .replace("__CONFIG__", json.dumps({**config, "responsive": True})))
    # st.iframe treats a raw HTML string as inline content and runs its
    # scripts — the supported replacement for the deprecated
    # st.components.v1.html (removed after 2026-06-01).
    st.iframe(html, height=height)


def show(fig: go.Figure, key: Optional[str] = None, *,
         config: Optional[dict] = None) -> None:
    """Render a Plotly figure with the app's standard interaction settings.

    Interactivity is decided by the figure itself: a chart built as static
    (layout.meta == "static") renders with no pan/zoom; anything else gets
    drag-to-pan + wheel-zoom on the time axis with the value axis auto-fitted
    to the visible window. Every view renders through this one function.
    (`key` only applies to the static path; the iframe embed needs none.)
    """
    static = getattr(fig.layout, "meta", None) == "static"
    if static:
        fig.update_layout(dragmode=False)
        st.plotly_chart(fig, width="stretch",
                        config=config or _STATIC_CONFIG, key=key)
        return
    fig.update_layout(dragmode="pan")
    # Locked for the user (wheel/drag act on time only); the embedded fitY
    # handler still adjusts it programmatically to track the visible window.
    fig.update_yaxes(fixedrange=True)
    _show_autofit_y(fig, config=config or PAN_ZOOM)


# Tooltip + tick date formatting for continuous time axes. With hovermode
# "x unified" the axis hoverformat drives the tooltip header, so setting it here
# makes every tooltip name an explicit date no matter the zoom; tickformatstops
# keep month ticks labelled with their year, so a month is never ambiguous.
DATE_TICKFORMATSTOPS = [
    # Zoomed in far enough that day-level ticks show — carry the year so a tick
    # is never ambiguous (m/d/yyyy, e.g. 4/5/2026).
    dict(dtickrange=[None, "M1"], value="%-m/%-d/%Y"),
    dict(dtickrange=["M1", "M12"], value="%b %Y"),   # months: month + year
    dict(dtickrange=["M12", None], value="%Y"),      # a year or more: year
]


def _hover_date_format(index: pd.Index) -> str:
    """Explicit-date tooltip format, finer for higher-frequency data.

    Daily/weekly series get a numeric m/d/yyyy date (e.g. 4/5/2026); monthly or
    coarser series keep the month-name form (e.g. Jun 2026).
    """
    if len(index) >= 2:
        span_days = (index[-1] - index[0]).days
        if span_days / (len(index) - 1) <= 20:       # roughly daily/weekly
            return "%-m/%-d/%Y"
    return "%b %Y"                                    # monthly or coarser


def _frame_time_axis(fig: go.Figure, index: pd.Index) -> None:
    """Frame a continuous time axis: clamp pan/zoom to the data span and label
    dates explicitly.

    One place for the rule so it holds across every time-series builder:
      - minallowed/maxallowed stop the user dragging past the first or last
        observation into empty space;
      - hoverformat makes the "x unified" tooltip always show a concrete date;
      - tickformatstops keep month ticks carrying their year.
    """
    if index is None or len(index) == 0:
        return
    fig.update_xaxes(minallowed=index[0], maxallowed=index[-1])
    if isinstance(index, pd.DatetimeIndex):
        fig.update_xaxes(hoverformat=_hover_date_format(index),
                         tickformatstops=DATE_TICKFORMATSTOPS)


def _recession_shapes(spans: list[tuple[datetime, datetime]],
                      x_min: Optional[datetime]) -> list[dict]:
    shapes = []
    for start, end in spans:
        if x_min is not None and end < x_min:
            continue
        shapes.append(dict(type="rect", xref="x", yref="paper",
                           x0=start, x1=end, y0=0, y1=1,
                           fillcolor="rgba(116, 112, 106, 0.10)",
                           line=dict(width=0), layer="below"))
    return shapes


def line(series: pd.Series, name: str, units: str = "",
         color: Optional[str] = None, height: int = 320,
         range_buttons: bool = True,
         recessions: Optional[list[tuple[datetime, datetime]]] = None,
         hlines: Optional[list[tuple[float, str]]] = None,
         initial_years: Optional[int] = None) -> go.Figure:
    """Single time series with optional recession shading and marker lines."""
    color = color or CHART_COLORWAY[0]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=series.index, y=series.values, mode="lines", name=name,
        line=dict(color=color, width=2),
        hovertemplate=f"%{{y:.2f}}{units}<extra></extra>"))

    if hlines:
        for y_val, label in hlines:
            fig.add_hline(y=y_val, line=dict(color=COLORS["text2"], width=1,
                                             dash="dot"),
                          annotation_text=label,
                          annotation_font=dict(size=10, color=COLORS["text2"]))
    if recessions:
        fig.update_layout(shapes=_recession_shapes(
            recessions, series.index[0] if len(series) else None))

    fig.update_layout(height=height, showlegend=False)
    if range_buttons:
        fig.update_xaxes(rangeselector=RANGE_SELECTOR)
    if initial_years and len(series):
        start = series.index[-1] - pd.DateOffset(years=initial_years)
        fig.update_xaxes(range=[max(start, series.index[0]), series.index[-1]])
    if units:
        fig.update_yaxes(ticksuffix=units if units in ("%", "pp") else None)
    _frame_time_axis(fig, series.index)
    return fig


def multi_line(frame: pd.DataFrame, units: str = "", height: int = 360,
               range_buttons: bool = False,
               recessions: Optional[list[tuple[datetime, datetime]]] = None,
               hlines: Optional[list[tuple[float, str]]] = None,
               initial_years: Optional[int] = None) -> go.Figure:
    """Several series, one axis, direct hover; legend always on."""
    fig = go.Figure()
    for i, col in enumerate(frame.columns):
        series = frame[col].dropna()
        fig.add_trace(go.Scatter(
            x=series.index, y=series.values, mode="lines", name=str(col),
            line=dict(color=CHART_COLORWAY[i % len(CHART_COLORWAY)], width=2),
            hovertemplate=f"%{{y:.2f}}{units}<extra>{col}</extra>"))
    if hlines:
        for y_val, label in hlines:
            fig.add_hline(y=y_val, line=dict(color=COLORS["text2"], width=1,
                                             dash="dot"),
                          annotation_text=label,
                          annotation_font=dict(size=10, color=COLORS["text2"]))
    if recessions and len(frame.index):
        fig.update_layout(shapes=_recession_shapes(recessions, frame.index[0]))
    fig.update_layout(height=height, showlegend=True)
    if range_buttons:
        fig.update_xaxes(rangeselector=RANGE_SELECTOR)
        # Range buttons occupy the top-right; drop the legend below the plot
        # so the two never overlap.
        fig.update_layout(
            legend=dict(orientation="h", yanchor="top", y=-0.16, x=0),
            margin=dict(b=70))
    if units in ("%", "pp"):
        fig.update_yaxes(ticksuffix=units)
    if initial_years and len(frame.index):
        end = frame.index.max()
        start = end - pd.DateOffset(years=initial_years)
        fig.update_xaxes(range=[max(start, frame.index.min()), end])
    _frame_time_axis(fig, frame.index)
    return fig


def year_lines(frame: pd.DataFrame, units: str = "%", height: int = 400,
               initial_tail: Optional[int] = None,
               colorway: Optional[list[str]] = None) -> go.Figure:
    """Many series over an integer (year) x-axis — e.g. one line per month.

    Every line is SOLID. Colours are drawn from ``colorway`` (default the
    12-hue :data:`MONTH_COLORWAY`) in the order the columns arrive, so the style
    is decided by the current selection rather than pre-pinned per column: pass a
    single column and it gets the first hue, not whatever slot it would occupy in
    the full twelve. Legend below, zero reference line, no date range-selector
    (the axis is years, not dates — pan/zoom still work).
    """
    fig = go.Figure()
    colorway = colorway or MONTH_COLORWAY
    for i, col in enumerate(frame.columns):
        series = frame[col].dropna()
        fig.add_trace(go.Scatter(
            x=series.index, y=series.values, mode="lines", name=str(col),
            line=dict(color=colorway[i % len(colorway)], width=1.6),
            hovertemplate=f"%{{y:.2f}}{units}<extra>{col}</extra>"))
    fig.add_hline(y=0, line=dict(color=COLORS["text2"], width=1, dash="dot"))
    fig.update_layout(height=height, showlegend=True,
                      legend=dict(orientation="h", yanchor="top", y=-0.14, x=0),
                      margin=dict(b=80))
    if units in ("%", "pp"):
        fig.update_yaxes(ticksuffix=units)
    if initial_tail and len(frame.index) > initial_tail:
        fig.update_xaxes(range=[frame.index[-initial_tail], frame.index[-1]])
    _frame_time_axis(fig, frame.index)
    return fig


def bar(series: pd.Series, units: str = "%", height: int = 330,
        highlight: Optional[str] = None, signed_colors: bool = True,
        show_values: bool = False) -> go.Figure:
    """Category bar chart. Positive/negative colouring by default; a
    highlighted category gets the coral accent."""
    colors = []
    for idx, val in series.items():
        if highlight is not None and str(idx) == highlight:
            colors.append(COLORS["highlight"])
        elif signed_colors:
            colors.append(COLORS["up"] if val >= 0 else COLORS["down"])
        else:
            colors.append(CHART_COLORWAY[0])
    series = series.round(2)
    fig = go.Figure(go.Bar(
        x=list(series.index.astype(str)), y=series.values,
        marker=dict(color=colors, cornerradius=4),
        text=[f"{v:+.2f}{units}" for v in series.values] if show_values else None,
        textposition="outside" if show_values else None,
        textfont=dict(family=FONT_MONO, size=10),
        hovertemplate=f"%{{x}}: %{{y:+.2f}}{units}<extra></extra>"))
    fig.update_layout(height=height, showlegend=False, bargap=0.35,
                      hovermode="closest", meta="static")
    fig.update_yaxes(ticksuffix=units if units in ("%", "pp") else None,
                     hoverformat=".2f")
    return fig


def hbar(series: pd.Series, units: str = "%", height: int = 360,
         show_values: bool = True) -> go.Figure:
    """Horizontal signed bar chart (e.g. sector 1-day moves), sorted.

    Each bar is labelled with its value by default so magnitudes are readable
    straight off the chart. Labels sit outside the bar tip (``cliponaxis=False``
    keeps them from being clipped), and the value axis is padded so the outermost
    label still fits inside the frame.
    """
    data = series.dropna().round(2).sort_values()
    colors = [COLORS["up"] if v >= 0 else COLORS["down"] for v in data.values]
    fig = go.Figure(go.Bar(
        y=list(data.index.astype(str)), x=data.values, orientation="h",
        marker=dict(color=colors, cornerradius=4),
        text=[f"{v:+.2f}{units}" for v in data.values] if show_values else None,
        textposition="outside" if show_values else None,
        textfont=dict(family=FONT_MONO, size=10),
        cliponaxis=False,
        hovertemplate=f"%{{y}}: %{{x:+.2f}}{units}<extra></extra>"))
    fig.update_layout(height=height, showlegend=False, bargap=0.3,
                      hovermode="closest", meta="static")
    fig.update_xaxes(ticksuffix=units if units in ("%", "pp") else None,
                     hoverformat=".2f")
    if show_values and len(data):
        # Widen the value axis a touch so outside labels on the longest bars
        # (both signs) clear the plot edge instead of being cut off.
        lo, hi = min(0.0, float(data.min())), max(0.0, float(data.max()))
        pad = (hi - lo) * 0.18 or 1.0
        fig.update_xaxes(range=[lo - pad, hi + pad])
    return fig


def heatmap(matrix: pd.DataFrame, units: str = "%", height: int = 420,
            diverging: bool = True, fmt: str = "+.1f") -> go.Figure:
    """Signed heatmap with in-cell values (returns tables, overlap counts)."""
    values = matrix.values
    if diverging:
        finite = pd.DataFrame(values).abs().max().max()
        bound = float(finite) if pd.notna(finite) and finite > 0 else 1.0
        zmin, zmax, scale = -bound, bound, DIVERGING
    else:
        zmin, zmax, scale = None, None, [[0, "#F7F3EC"], [1, COLORS["accent"]]]
    suffix = units if units in ("%", "pp") else ""
    fig = go.Figure(go.Heatmap(
        z=values, x=list(matrix.columns.astype(str)),
        y=list(matrix.index.astype(str)),
        zmin=zmin, zmax=zmax, colorscale=scale, xgap=2, ygap=2,
        texttemplate="%{text}",
        text=[[("" if pd.isna(v) else f"{v:{fmt}}{suffix}") for v in row]
              for row in values],
        textfont=dict(family=FONT_MONO, size=11),
        hovertemplate=f"%{{y}} · %{{x}}: %{{z:{fmt}}}{units}<extra></extra>",
        showscale=False))
    fig.update_layout(height=height, hovermode="closest", meta="static")
    fig.update_yaxes(autorange="reversed")
    return fig


def donut(series: pd.Series, height: int = 340) -> go.Figure:
    """Sector distribution donut with direct labels.

    ``automargin`` lets Plotly shrink the pie so outside labels (e.g. long
    sector names like "Communication Services") stay inside the frame instead
    of being clipped at the edges.
    """
    fig = go.Figure(go.Pie(
        labels=list(series.index.astype(str)), values=series.values,
        hole=0.55, marker=dict(colors=[CHART_COLORWAY[i % len(CHART_COLORWAY)]
                                       for i in range(len(series))],
                               line=dict(color=COLORS["bg"], width=2)),
        textinfo="label+percent", textposition="outside",
        textfont=dict(size=11), automargin=True,
        hovertemplate="%{label}: %{value} names (%{percent})<extra></extra>"))
    fig.update_layout(height=height, showlegend=False, meta="static",
                      margin=dict(l=90, r=90, t=30, b=30))
    return fig


def gauge(score: float, verdict: str, height: int = 300) -> go.Figure:
    """0-100 contrarian thermometer. Higher = more fear = more bullish."""
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=score,
        number=dict(font=dict(family=FONT_MONO, size=44,
                              color=COLORS["text"]), suffix=""),
        title=dict(text=verdict, font=dict(family=FONT_DISPLAY, size=16,
                                           color=COLORS["text"])),
        gauge=dict(
            axis=dict(range=[0, 100], tickwidth=1,
                      tickcolor=COLORS["border"],
                      tickfont=dict(size=10, color=COLORS["text2"])),
            bar=dict(color=COLORS["accent"], thickness=0.28),
            bgcolor=COLORS["surface2"],
            borderwidth=0,
            steps=[
                dict(range=[0, 25], color="rgba(193, 95, 60, 0.18)"),
                dict(range=[25, 45], color="rgba(193, 95, 60, 0.08)"),
                dict(range=[45, 55], color="rgba(116, 112, 106, 0.08)"),
                dict(range=[55, 75], color="rgba(91, 140, 90, 0.10)"),
                dict(range=[75, 100], color="rgba(91, 140, 90, 0.20)"),
            ],
        )))
    fig.update_layout(height=height,
                      margin=dict(l=30, r=30, t=60, b=10), meta="static")
    return fig
