"""Reusable HTML components: metric tiles, pills, cards, sparklines."""

from __future__ import annotations

import html
from typing import Iterable, Optional

import streamlit as st

from core.cache import CacheResult
from ui.theme import COLORS


# --------------------------------------------------------------------------
# Sparkline (inline SVG so it can live inside a metric tile)
# --------------------------------------------------------------------------

def sparkline_svg(values: Iterable[float], width: int = 132, height: int = 30,
                  color: Optional[str] = None) -> str:
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return ""
    color = color or COLORS["accent"]
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    pad = 2
    step = (width - 2 * pad) / (len(values) - 1)
    points = []
    for i, v in enumerate(values):
        x = pad + i * step
        y = pad + (height - 2 * pad) * (1 - (v - lo) / span)
        points.append(f"{x:.1f},{y:.1f}")
    last_x, last_y = points[-1].split(",")
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" '
        f'stroke-width="1.5" stroke-linejoin="round" stroke-linecap="round"/>'
        f'<circle cx="{last_x}" cy="{last_y}" r="2.4" fill="{color}"/></svg>'
    )


# --------------------------------------------------------------------------
# Metric tiles
# --------------------------------------------------------------------------

def metric_tile(label: str, value: str, delta: str = "", direction: int = 0,
                spark: Optional[Iterable[float]] = None,
                spark_color: Optional[str] = None,
                note: str = "", stale: bool = False, small: bool = False) -> str:
    """One tile as an HTML string; render a batch with render_tiles().

    ``small`` renders the value at a smaller size that wraps instead of
    overflowing — use it for long text values like dates.
    """
    tone = "up" if direction > 0 else ("down" if direction < 0 else "flat")
    delta_html = (f'<div class="delta {tone}">{html.escape(delta)}</div>'
                  if delta else "")
    spark_html = sparkline_svg(spark, color=spark_color) if spark else ""
    note_parts = []
    if note:
        note_parts.append(html.escape(note))
    if stale:
        note_parts.append('<span class="stale">cached</span>')
    note_html = (f'<div class="note">{" · ".join(note_parts)}</div>'
                 if note_parts else "")
    value_class = "value small" if small else "value"
    return (f'<div class="mc-tile"><div class="label">{html.escape(label)}</div>'
            f'<div class="{value_class}">{html.escape(value)}</div>'
            f'{delta_html}{spark_html}{note_html}</div>')


def render_tiles(tiles: list[str]) -> None:
    st.markdown(f'<div class="mc-grid">{"".join(tiles)}</div>',
                unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Pills, cards, captions
# --------------------------------------------------------------------------

def pill(text: str, tone: str = "muted", label: str = "") -> str:
    """tone: up | down | neutral | muted | accent"""
    label_html = (f'<span class="pill-label">{html.escape(label)}</span>'
                  if label else "")
    return f'<span class="mc-pill {tone}">{label_html}{html.escape(text)}</span>'


def render_pills(pills: list[str]) -> None:
    st.markdown(f'<div style="margin:6px 0 10px 0">{"".join(pills)}</div>',
                unsafe_allow_html=True)


def headline_card(text: str) -> None:
    st.markdown(f'<div class="mc-card"><div class="mc-headline">'
                f'{html.escape(text)}</div></div>', unsafe_allow_html=True)


def caption(text: str) -> None:
    st.markdown(f'<div class="mc-caption">{html.escape(text)}</div>',
                unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Page scaffolding
# --------------------------------------------------------------------------

def page_header(title: str, subtitle: str = "") -> bool:
    """Title + subtitle + refresh button. Returns True when a forced
    refresh was requested this run."""
    col_title, col_btn = st.columns([5, 1])
    with col_title:
        st.title(title)
        if subtitle:
            caption(subtitle)
    with col_btn:
        st.write("")
        force = st.button("↻ Refresh", key=f"refresh_{title}",
                          help="Bypass the cache and pull fresh data now")
    return force


def source_status(*results: CacheResult, source_names: Optional[list[str]] = None) -> None:
    """One-line data freshness footer: 'FRED · updated 2026-07-08 08:31 · live'."""
    parts = []
    for i, res in enumerate(results):
        name = (source_names[i] if source_names and i < len(source_names)
                else f"source {i + 1}")
        if res is None or res.fetched_at is None:
            parts.append(f"{name}: no data")
        elif res.is_stale:
            parts.append(f"{name}: last update {res.age_text} (cached, source down)")
        else:
            state = "cached" if res.from_cache else "live"
            parts.append(f"{name}: {res.age_text} ({state})")
    caption(" · ".join(parts))
