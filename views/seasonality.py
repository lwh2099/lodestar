"""Seasonality — S&P 500 monthly and presidential-cycle patterns."""

import streamlit as st

from core import seasonality
from ui import charts
from ui import components as ui

force = ui.page_header("Seasonality")

history = seasonality.price_history(force=force)
if not history.ok:
    st.error("Price history unavailable and no cache exists yet. "
             "Check the connection and hit Refresh.")
    st.stop()

prices = history.data
ctx = seasonality.current_context()

pills = [ui.pill(ctx.month_label, "accent", label="month"),
         ui.pill(f"{ctx.cycle} year", "accent", label="cycle")]
if ctx.weekday_label:
    pills.append(ui.pill(ctx.weekday_label, "accent", label="weekday"))
ui.render_pills(pills)
ui.source_status(history, source_names=["Yahoo Finance (^GSPC)"])

# --------------------------------------------------------------------------
# Monthly seasonality
# --------------------------------------------------------------------------

st.header("Monthly pattern")

monthly = seasonality.monthly_stats(prices)
current = monthly.loc[ctx.month_label]
ui.caption(f"Average monthly return since {prices.index[0].year} · current "
           f"month highlighted. {ctx.month_label}: {current['avg_return']:+.2f}% "
           f"average, positive {current['win_rate']:.0f}% of years "
           f"(n={current['years']:.0f}).")
charts.show(
    charts.bar(monthly["avg_return"], highlight=ctx.month_label,
               show_values=True, height=340),
    key="monthly_bar")

by_year = seasonality.monthly_returns_by_year(prices)

# Same "Monthly pattern" section: below the averages, one solid line per month
# across the years. Twelve overlapping lines are hard to read, so let the reader
# isolate a few — colours are assigned in selection order, so picking a single
# month starts from the first hue. The trailing toggle behaves like a
# spreadsheet filter's check-all/uncheck-all: one button that clears everything
# when all are on and selects everything otherwise (its callback seeds the
# pills' state, which runs before the widget is created).
months = list(seasonality.MONTH_LABELS)
st.session_state.setdefault("trend_months", months)


def _toggle_all_months() -> None:
    current = set(st.session_state.get("trend_months", []))
    st.session_state.trend_months = [] if current == set(months) else list(months)


# Horizontal flow so the toggle sits just after the Dec pill (both default to
# width="content"), not pinned to the far right of the page.
with st.container(horizontal=True, vertical_alignment="center", gap="small"):
    selected_months = st.pills(
        "Months shown", months, selection_mode="multi",
        key="trend_months", label_visibility="collapsed")
    all_selected = set(selected_months) == set(months)
    st.button("Clear all" if all_selected else "Select all",
              key="months_toggle", on_click=_toggle_all_months)

if selected_months:
    charts.show(
        charts.year_lines(by_year[selected_months], initial_tail=30,
                          height=420),
        key="monthly_trend")
else:
    st.info("Select at least one month above to draw the chart.")

# --------------------------------------------------------------------------
# Presidential cycle
# --------------------------------------------------------------------------

st.header("Presidential cycle")

cycle = seasonality.presidential_stats(prices)
current_cycle = cycle.loc[f"{ctx.cycle}"]
ui.caption(f"Average annual return by cycle year. {ctx.year} is a "
           f"{ctx.cycle.lower()} year: {current_cycle['avg_return']:+.1f}% "
           f"average, positive {current_cycle['win_rate']:.0f}% of years "
           f"(n={current_cycle['years']:.0f}).")

col_bar, col_heat = st.columns([2, 3])
with col_bar:
    charts.show(
        charts.bar(cycle["avg_return"], highlight=ctx.cycle,
                   show_values=True, height=360),
        key="cycle_bar")
with col_heat:
    ui.caption("Average monthly return by cycle year (%) — find the current "
               f"cell: {ctx.cycle} × {ctx.month_label}.")
    charts.show(
        charts.heatmap(seasonality.cycle_month_matrix(prices), height=360),
        key="cycle_heatmap")
