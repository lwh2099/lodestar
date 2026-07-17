"""Claude warm-minimal design system: tokens, plotly template, injected CSS.

Colour tokens follow the project spec. The chart colorway is a validated
variant of the spec palette: same hues, reordered and slightly darkened so
every adjacent pair stays distinguishable under red-green colour blindness
(deltaE >= 33 simulated) and every line colour clears 3:1 contrast on the
warm ivory surface.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

COLORS = {
    "bg": "#FAF9F5",
    "surface": "#FFFFFF",
    "surface2": "#F0EEE6",
    "border": "#E5E1D6",
    "text": "#1F1E1D",
    "text2": "#74706A",
    "accent": "#D97757",     # coral — UI accent, fills, highlights
    "accent2": "#E0A93C",    # amber — highlight bands / soft fills only
    "up": "#5B8C5A",
    "down": "#C15F3C",
    "neutral": "#B9924A",
    # Blue for a highlighted category bar (e.g. the current month) — kept clearly
    # apart from the red down / green up bars so "this is today" never reads as a
    # negative return.
    "highlight": "#2478B8",
}

# CVD-validated categorical line colorway (coral, blue, amber, teal, magenta,
# violet). Ordered so every prefix stays separable: any chart using the first N
# colours (N up to 6, the largest group in the app) keeps its worst colour-blind
# (protan/deutan) pairwise ΔE >= 12.9, above the 12 target. Passes the dataviz
# validator's lightness-band and chroma-floor checks; amber/teal fall just under
# 3:1 contrast on the ivory surface — mitigated by the always-on legend + hover.
CHART_COLORWAY = ["#C15F3C", "#2478B8", "#E0A93C", "#2AA597", "#A83E66", "#5B4590"]

# 12 solid, high-separation hues for the twelve-month line chart (Seasonality's
# "each month, year by year"). One distinct colour per month so every line can be
# a SOLID line — no dashes — even with all twelve on screen. Interleaved so
# adjacent months contrast strongly; validated with the dataviz method for the
# ivory surface (all checks pass, worst adjacent protan/deutan ΔE 8.6, above the
# 8 target). Colours are assigned in selection order, so a single-month pick
# starts from the first hue rather than a pre-pinned per-month style.
MONTH_COLORWAY = [
    "#C1443C",  # red
    "#2478B8",  # blue
    "#E0A93C",  # amber
    "#2AA597",  # teal
    "#A83E66",  # magenta
    "#2E9E5B",  # green
    "#7A45A8",  # violet
    "#D97A2B",  # orange
    "#3B4F9E",  # indigo
    "#C23E6B",  # rose
    "#6E8C1F",  # olive
    "#159AC0",  # cyan
]

# Diverging scale for signed heatmaps (down -> neutral surface -> up).
DIVERGING = [[0.0, COLORS["down"]], [0.5, "#F1EFE8"], [1.0, COLORS["up"]]]
# Sequential single-hue scale for unsigned magnitude.
SEQUENTIAL = [[0.0, "#F7EDE7"], [1.0, "#C15F3C"]]

FONT_BODY = "Inter, 'IBM Plex Sans', sans-serif"
FONT_MONO = "'JetBrains Mono', 'IBM Plex Mono', monospace"
FONT_DISPLAY = "Fraunces, Newsreader, Georgia, serif"


def register_plotly_template() -> None:
    pio.templates["claude"] = go.layout.Template(
        layout=go.Layout(
            paper_bgcolor=COLORS["bg"],
            plot_bgcolor=COLORS["bg"],
            font=dict(family=FONT_BODY, color=COLORS["text"], size=13),
            title=dict(font=dict(family=FONT_DISPLAY, size=17)),
            colorway=CHART_COLORWAY,
            xaxis=dict(gridcolor=COLORS["border"], zerolinecolor=COLORS["border"],
                       linecolor=COLORS["border"], ticks="outside",
                       tickcolor=COLORS["border"]),
            yaxis=dict(gridcolor=COLORS["border"], zerolinecolor=COLORS["border"],
                       linecolor=COLORS["border"], ticks="outside",
                       tickcolor=COLORS["border"]),
            margin=dict(l=48, r=16, t=40, b=40),
            legend=dict(borderwidth=0, bgcolor="rgba(0,0,0,0)",
                        orientation="h", yanchor="bottom", y=1.02, x=0),
            hoverlabel=dict(bgcolor=COLORS["surface"],
                            bordercolor=COLORS["border"],
                            font=dict(family=FONT_MONO, size=12,
                                      color=COLORS["text"])),
            hovermode="x unified",
        )
    )
    pio.templates.default = "claude"


_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap');

:root {{
    --bg: {COLORS['bg']};
    --surface: {COLORS['surface']};
    --surface-2: {COLORS['surface2']};
    --border: {COLORS['border']};
    --text: {COLORS['text']};
    --text-2: {COLORS['text2']};
    --accent: {COLORS['accent']};
    --accent-2: {COLORS['accent2']};
    --up: {COLORS['up']};
    --down: {COLORS['down']};
    --neutral: {COLORS['neutral']};
}}

.stApp {{ background: var(--bg); }}
.block-container {{ padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1280px; }}

h1, h2, h3 {{
    font-family: {FONT_DISPLAY} !important;
    font-weight: 600 !important;
    letter-spacing: -0.01em;
    color: var(--text) !important;
}}
h1 {{ font-size: 2.1rem !important; }}
h2 {{ margin-top: 2.2rem !important; }}

p, li, label, .stMarkdown {{ font-family: {FONT_BODY}; }}

/* Sidebar */
section[data-testid="stSidebar"] {{
    background: var(--surface-2);
    border-right: 1px solid var(--border);
}}
[data-testid="stSidebarNav"] a {{
    border-radius: 8px;
    color: var(--text-2);
}}
[data-testid="stSidebarNav"] a span {{ color: var(--text-2); font-family: {FONT_BODY}; }}
/* Keep the Material Symbols ligature font on nav icons — the body-font rule
   above would otherwise render the icon name as literal text. */
[data-testid="stSidebarNav"] a span[data-testid="stIconMaterial"],
[data-testid="stSidebarNav"] a span.material-symbols-rounded {{
    font-family: 'Material Symbols Rounded', 'Material Symbols Outlined' !important;
    font-weight: normal !important;
    letter-spacing: normal !important;
}}
[data-testid="stSidebarNav"] a[aria-current="page"] {{
    background: rgba(217, 119, 87, 0.14);
}}
[data-testid="stSidebarNav"] a[aria-current="page"] span {{
    color: var(--accent);
    font-weight: 600;
}}

/* Buttons */
.stButton > button, .stDownloadButton > button {{
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--surface);
    color: var(--text);
    font-family: {FONT_BODY};
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
    border-color: var(--accent);
    color: var(--accent);
}}

/* Popover trigger styled as an inline text link, not a button.
   The popover body renders in a separate portal, so a descendant selector
   here only ever matches the trigger. */
[data-testid="stPopover"] button {{
    background: transparent !important;
    border: none !important;
    box-shadow: none !important;
    padding: 0 !important;
    min-height: 0 !important;
    height: auto !important;
    color: var(--accent) !important;
    font-family: {FONT_BODY} !important;
    font-size: 12px !important;
    font-weight: 500 !important;
    text-decoration: underline;
    text-decoration-style: dotted;
    text-underline-offset: 3px;
}}
[data-testid="stPopover"] button:hover {{
    color: var(--down) !important;
    text-decoration-style: solid;
}}
[data-testid="stPopover"] button p {{
    font-size: 12px !important;
    font-weight: 500 !important;
    text-decoration: underline;
    text-decoration-style: dotted;
    text-underline-offset: 3px;
}}
/* Drop the default caret so it reads as text, not a dropdown */
[data-testid="stPopover"] button svg {{ display: none; }}

/* Metric tile grid */
.mc-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(176px, 1fr));
    gap: 12px;
    margin: 4px 0 8px 0;
}}
.mc-tile {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px 12px 16px;
}}
.mc-tile .label {{
    font-size: 11px;
    text-transform: lowercase;
    letter-spacing: 0.08em;
    color: var(--text-2);
    margin-bottom: 4px;
    font-family: {FONT_BODY};
}}
.mc-tile .value {{
    font-family: {FONT_MONO};
    font-size: 26px;
    font-weight: 600;
    color: var(--text);
    line-height: 1.15;
    white-space: nowrap;
}}
.mc-tile .value.small {{
    font-size: 18px;
    white-space: normal;
    word-break: break-word;
}}
.mc-tile .delta {{
    font-family: {FONT_MONO};
    font-size: 12px;
    margin-top: 2px;
}}
.mc-tile .delta.up {{ color: var(--up); }}
.mc-tile .delta.down {{ color: var(--down); }}
.mc-tile .delta.flat {{ color: var(--text-2); }}
.mc-tile .note {{
    font-size: 10px;
    color: var(--text-2);
    margin-top: 6px;
    font-family: {FONT_BODY};
}}
.mc-tile .note .stale {{ color: var(--down); font-weight: 600; }}
.mc-tile svg {{ margin-top: 6px; display: block; }}

/* Status pills */
.mc-pill {{
    display: inline-block;
    padding: 5px 16px;
    border-radius: 999px;
    font-size: 13px;
    font-weight: 600;
    font-family: {FONT_BODY};
    margin-right: 8px;
}}
.mc-pill.up      {{ background: rgba(91, 140, 90, 0.14);  color: #3F6B3E; }}
.mc-pill.down    {{ background: rgba(193, 95, 60, 0.14);  color: #9A4526; }}
.mc-pill.neutral {{ background: rgba(185, 146, 74, 0.16); color: #82652F; }}
.mc-pill.muted   {{ background: rgba(116, 112, 106, 0.12); color: var(--text-2); }}
.mc-pill.accent  {{ background: rgba(217, 119, 87, 0.14); color: var(--accent); }}
.mc-pill .pill-label {{
    font-weight: 400;
    font-size: 11px;
    opacity: 0.75;
    margin-right: 6px;
    text-transform: lowercase;
    letter-spacing: 0.06em;
}}

/* Cards */
.mc-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 20px 24px;
    margin: 8px 0;
}}
.mc-headline {{
    font-family: {FONT_DISPLAY};
    font-size: 19px;
    line-height: 1.45;
    color: var(--text);
}}

/* Section subtitles / captions */
.mc-caption {{
    font-size: 12px;
    color: var(--text-2);
    font-family: {FONT_BODY};
    margin: 2px 0 10px 0;
}}

/* Streamlit chrome */
#MainMenu, footer {{ visibility: hidden; }}
[data-testid="stMetric"] {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 14px 16px;
}}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
.stTabs [data-baseweb="tab"] {{
    font-family: {FONT_BODY};
    border-radius: 8px 8px 0 0;
}}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


def apply() -> None:
    """One-call setup used by app.py on every rerun."""
    register_plotly_template()
    inject_css()
