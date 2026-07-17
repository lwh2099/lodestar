"""Market — indices, volatility, sector rotation, style/factor RS, commodities, bonds."""

import pandas as pd
import streamlit as st

from core import market
from ui import charts
from ui import components as ui

force = ui.page_header(
    "Market",
    "Real-time (15–20 min delayed) market internals via Yahoo Finance, "
    "with cache fallback when the source is down.")

RETURN_WINDOWS = {"1D": 1, "1W": 5, "1M": 21, "3M": 63, "YTD": 0}

# One batched quotes call warms every tile on the page (and shares the cache
# entry the "Update all data" job pre-fetches), instead of one download per
# group.
all_quotes = market.quotes(market.all_tickers(), force=force)


def _quote_tiles(tickers: list[str], lower_better: set[str] = frozenset(),
                 decimals: int = 2) -> None:
    if not all_quotes.ok:
        st.warning("Quotes unavailable (no cache yet).")
        return
    tiles = []
    for ticker in tickers:
        if ticker not in all_quotes.data.index:
            continue
        row = all_quotes.data.loc[ticker]
        chg = float(row["chg_pct"])
        direction = -1 if chg < 0 else (1 if chg > 0 else 0)
        if ticker in lower_better:
            direction = -direction
        tiles.append(ui.metric_tile(
            label=str(row["label"]),
            value=f"{float(row['last']):,.{decimals}f}",
            delta=f"{chg:+.2f}% today",
            direction=direction,
            stale=all_quotes.is_stale))
    ui.render_tiles(tiles)


# --------------------------------------------------------------------------
# Indices & volatility
# --------------------------------------------------------------------------

st.header("Indices & volatility")
_quote_tiles(list(market.GROUPS["indices"].keys()))
_quote_tiles(list(market.GROUPS["volatility"].keys()),
             lower_better=set(market.GROUPS["volatility"].keys()))

st.header("Rates & dollar")
_quote_tiles(list(market.GROUPS["rates"].keys())
             + list(market.GROUPS["dollar"].keys()))

# --------------------------------------------------------------------------
# Sector rotation
# --------------------------------------------------------------------------

st.header("Sector rotation")

sector_tickers = list(market.GROUPS["sectors"].keys())
sector_hist = market.history(sector_tickers, period="1y", force=force)
if sector_hist.ok:
    returns = market.trailing_returns(sector_hist.data, RETURN_WINDOWS)
    returns.index = [market.label(t) for t in returns.index]

    col_heat, col_bar = st.columns([3, 2])
    with col_heat:
        ui.caption("Trailing returns by sector ETF (%)")
        charts.show(charts.heatmap(returns, height=430), key="sector_heatmap")
    with col_bar:
        ui.caption("Today's sector moves (%)")
        charts.show(charts.hbar(returns["1D"], height=430), key="sector_1d")
    ui.source_status(sector_hist, source_names=["Yahoo Finance"])
else:
    st.warning("Sector data unavailable (no cache yet).")

# --------------------------------------------------------------------------
# Style & factor relative strength
# --------------------------------------------------------------------------

st.header("Style & factor relative strength")

style_tickers = list(market.GROUPS["styles"].keys()) + ["SPY"]
style_hist = market.history(style_tickers, period="1y", force=force)
if style_hist.ok:
    close = style_hist.data
    ratios = {}
    value_growth = market.relative_strength(close, "IWD", "IWF")
    small_large = market.relative_strength(close, "IWM", "IWF")
    if value_growth is not None:
        ratios["Value / Growth (IWD/IWF)"] = value_growth
    if small_large is not None:
        ratios["Small / Large (IWM/IWF)"] = small_large

    col_rs, col_factor = st.columns(2)
    with col_rs:
        ui.caption("Ratio rebased to 100 · rising line = numerator leading")
        if ratios:
            charts.show(charts.multi_line(pd.DataFrame(ratios), height=360),
                        key="style_rs")
    with col_factor:
        ui.caption("Factor ETF 3-month returns (%)")
        factor_returns = market.trailing_returns(
            close[list(market.GROUPS["styles"].keys())], {"3M": 63})["3M"]
        factor_returns.index = [market.label(t) for t in factor_returns.index]
        charts.show(charts.hbar(factor_returns.dropna(), height=360),
                    key="factor_3m")
else:
    st.warning("Style/factor data unavailable (no cache yet).")

# --------------------------------------------------------------------------
# Commodities & bonds
# --------------------------------------------------------------------------

st.header("Commodities")
_quote_tiles(list(market.GROUPS["commodities"].keys()))

commodity_hist = market.history(list(market.GROUPS["commodities"].keys()),
                                period="max", ttl=market.EOD_TTL, force=force)
if commodity_hist.ok:
    close = commodity_hist.data
    rebased = {}
    for ticker in market.GROUPS["commodities"]:
        if ticker in close.columns:
            series = close[ticker].dropna()
            if not series.empty:
                rebased[market.label(ticker)] = series / series.iloc[0] * 100
    if rebased:
        ui.caption("All four commodities on one axis, indexed so their relative "
                   "performance is comparable across very different price levels. "
                   "Full available history — use the range buttons to zoom.")
        with st.popover("ⓘ How “rebased to 100” is computed"):
            st.markdown(
                "Each commodity is **rebased to 100** at the start of the "
                "available history, then every later point is scaled the same "
                "way:")
            st.markdown("`rebased = price ÷ price_at_window_start × 100`")
            st.markdown(
                "- Every line starts at **100**, so they share one axis despite "
                "very different dollar prices (gold ≈ \\$2,000, natural gas ≈ "
                "\\$3/MMBtu, copper ≈ \\$4/lb, WTI ≈ \\$80).\n"
                "- A reading of **120 means +20%** since the window start; "
                "**90 means −10%**.\n"
                "- The **highest line is the best performer** over the window, "
                "and crossings mark shifts in leadership.\n\n"
                "This shows *relative performance*, not price — use the quote "
                "tiles above for current dollar levels.")
        charts.show(
            charts.multi_line(pd.DataFrame(rebased), range_buttons=True,
                              height=380),
            key="commodities")
    ui.source_status(commodity_hist, source_names=["Yahoo Finance"])

st.header("Bonds & credit")
_quote_tiles(list(market.GROUPS["bonds"].keys()))
bond_hist = market.history(list(market.GROUPS["bonds"].keys()),
                           period="1y", force=force)
if bond_hist.ok:
    bond_returns = market.trailing_returns(bond_hist.data,
                                           {"3M": 63})["3M"].dropna()
    bond_returns.index = [market.label(t) for t in bond_returns.index]
    ui.caption("Bond ETF 3-month total returns (%)")
    charts.show(charts.hbar(bond_returns, height=300), key="bond_3m")
