"""Regime Compass — the top-level macro regime read.

Three concluded tags (policy stance, growth pulse, risk appetite) plus the
historical trend of the scores that drive them. Detail lives in the two
expanders; everything else on this page is the conclusion.
"""

import streamlit as st

from core import regime
from ui import charts, components as ui

force = ui.page_header("Regime Compass")

# --------------------------------------------------------------------------
# The three concluded tags
# --------------------------------------------------------------------------

with st.spinner("Scoring the regime (first run downloads FRED history)..."):
    reg = regime.evaluate(force=force)

pills = [ui.pill(dim.state, dim.tone, label=dim.label) for dim in reg.dimensions]
if reg.curve_inverted:
    pills.append(ui.pill("Curve inverted", "down", label="flag"))
ui.render_pills(pills)

with st.expander("How these tags are computed"):
    st.markdown(
        "Each dimension is a rule-based composite score. Inputs are scored "
        "against the thresholds in `config/thresholds.yaml`; a missing source "
        "simply drops out of its dimension.")
    st.markdown(
        "- **Monetary** — Chicago Fed **NFCI** (loose vs tight conditions), the "
        "3-month change in the **effective Fed funds rate**, and the 1-month "
        "change in the **2-year yield**. Net easing → *Easing*; net "
        "tightening → *Tightening*.\n"
        "- **Growth** — manufacturing output **IPMAN** (YoY), **Atlanta Fed "
        "GDPNow**, the trend in **initial jobless claims**, and the momentum "
        "of **nonfarm payroll** gains. Positive net → *Expansion*, negative → "
        "*Contraction*, in between → *Slowing*.\n"
        "- **Risk Appetite** — **VIX**, **high-yield OAS**, and the **10Y-2Y "
        "curve** (an inversion is flagged separately). Calm/tight spreads → "
        "*Risk-on*; stress → *Risk-off*.")

with st.expander("Why these states? Rule-by-rule detail"):
    for dim in reg.dimensions:
        st.markdown(f"**{dim.label} — {dim.state}**"
                    + (f" (score {dim.score:+.2f})" if dim.score is not None else ""))
        for line in dim.details:
            st.markdown(f"- {line}")

# --------------------------------------------------------------------------
# Historical trend of the three scores
# --------------------------------------------------------------------------

st.header("Regime history")
ui.caption("Monthly composite score for each dimension, same rules applied "
           "back through time. Higher = more supportive (easier money, "
           "stronger growth, more risk appetite); zero is neutral.")

with st.spinner("Building regime history..."):
    hist = regime.history(force=force)

if hist.empty:
    st.warning("Not enough history is available yet. Hit Refresh once data "
               "has downloaded.")
else:
    fig = charts.multi_line(hist, height=400, range_buttons=True,
                            hlines=[(0.0, "neutral")])
    fig.update_yaxes(title_text="composite score")
    charts.show(fig, key="regime_history")
    ui.caption("Source: FRED (NFCI, rates, claims, payrolls, spreads) and "
               "Yahoo Finance (VIX).")
