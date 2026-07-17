"""Real-time market data layer (yfinance).

yfinance is an unofficial, best-effort source: every call here is wrapped in
retry + SQLite cache fallback, so a Yahoo outage degrades to the last cached
quote instead of an empty page.
"""

from __future__ import annotations

import hashlib
from typing import Iterable, Optional

import pandas as pd
import yfinance as yf

from core import cache

# Display ticker groups (mirrors SPEC section 2.2).
GROUPS: dict[str, dict[str, str]] = {
    "indices": {"^GSPC": "S&P 500", "^IXIC": "Nasdaq", "^DJI": "Dow Jones",
                "^RUT": "Russell 2000"},
    "volatility": {"^VIX": "VIX", "^VIX9D": "VIX 9-Day", "^VVIX": "VVIX"},
    "rates": {"^IRX": "13-Week Yield", "^FVX": "5-Year Yield",
              "^TNX": "10-Year Yield", "^TYX": "30-Year Yield"},
    "dollar": {"DX-Y.NYB": "Dollar Index"},
    "commodities": {"GC=F": "Gold", "CL=F": "WTI Crude", "HG=F": "Copper",
                    "NG=F": "Natural Gas"},
    "sectors": {"XLK": "Technology", "XLF": "Financials", "XLV": "Health Care",
                "XLY": "Cons. Discretionary", "XLP": "Cons. Staples",
                "XLI": "Industrials", "XLE": "Energy", "XLU": "Utilities",
                "XLB": "Materials", "XLRE": "Real Estate",
                "XLC": "Communication"},
    "styles": {"IWD": "Value (IWD)", "IWF": "Growth (IWF)",
               "IWM": "Small Cap (IWM)", "MTUM": "Momentum (MTUM)",
               "QUAL": "Quality (QUAL)", "USMV": "Min Vol (USMV)"},
    "bonds": {"TLT": "20+Y Treasury", "IEF": "7-10Y Treasury",
              "SHY": "1-3Y Treasury", "HYG": "High Yield", "LQD": "Inv. Grade",
              "TIP": "TIPS"},
}

INTRADAY_TTL = 15 * 60        # spec: 15-minute cache for intraday quotes
EOD_TTL = 24 * 3600           # long histories refresh nightly


def label(ticker: str) -> str:
    for group in GROUPS.values():
        if ticker in group:
            return group[ticker]
    return ticker


def all_tickers() -> list[str]:
    """Every ticker across all display groups, de-duplicated, order-preserving.

    Used so one batched quotes/history request can cover the whole app and
    share a single cache entry (see the refresh job list and the Market page).
    """
    out: list[str] = []
    for group in GROUPS.values():
        out += group.keys()
    return list(dict.fromkeys(out))


def _key(tickers: Iterable[str], period: str, interval: str) -> str:
    joined = ",".join(sorted(tickers))
    digest = hashlib.md5(joined.encode()).hexdigest()[:10]
    return f"{interval}:{period}:{digest}"


def _download(tickers: list[str], period: str, interval: str) -> pd.DataFrame:
    raw = yf.download(tickers, period=period, interval=interval,
                      auto_adjust=True, progress=False, group_by="column",
                      threads=True)
    if raw is None or raw.empty:
        raise RuntimeError("yfinance returned no data")
    close = raw["Close"]
    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])
    close = close.dropna(how="all")
    if close.empty:
        raise RuntimeError("yfinance returned no close prices")
    close.index = pd.to_datetime(close.index)
    if close.index.tz is not None:
        close.index = close.index.tz_localize(None)
    return close


def history(tickers: Iterable[str], period: str = "1y", interval: str = "1d",
            ttl: Optional[float] = None, force: bool = False) -> cache.CacheResult:
    """Close-price history, one column per ticker."""
    tickers = list(dict.fromkeys(tickers))
    if ttl is None:
        ttl = EOD_TTL if period in ("max", "10y", "20y") else INTRADAY_TTL
    return cache.fetch_with_cache(
        "yfinance", _key(tickers, period, interval), ttl,
        lambda: cache.retry(lambda: _download(tickers, period, interval)),
        force_refresh=force)


def quotes(tickers: Iterable[str], force: bool = False) -> cache.CacheResult:
    """Latest price, previous close and % change per ticker.

    Built from a short daily history so one batched request covers
    everything; falls back to cache when Yahoo is down.
    """
    tickers = list(dict.fromkeys(tickers))
    result = history(tickers, period="10d", interval="1d", force=force)
    if not result.ok:
        return result

    close: pd.DataFrame = result.data
    rows = []
    for ticker in tickers:
        if ticker not in close.columns:
            continue
        series = close[ticker].dropna()
        if series.empty:
            continue
        last = float(series.iloc[-1])
        prev = float(series.iloc[-2]) if len(series) > 1 else last
        rows.append({"ticker": ticker, "label": label(ticker), "last": last,
                     "prev": prev, "chg": last - prev,
                     "chg_pct": (last / prev - 1) * 100 if prev else 0.0})
    table = pd.DataFrame(rows).set_index("ticker") if rows else pd.DataFrame()
    return cache.CacheResult(table, result.fetched_at, result.from_cache,
                             result.is_stale, result.error)


def trailing_returns(close: pd.DataFrame,
                     windows: dict[str, int]) -> pd.DataFrame:
    """% returns over trailing windows given in trading days.

    A window of 0 means year-to-date.
    """
    out = {}
    for name, days in windows.items():
        col = {}
        for ticker in close.columns:
            series = close[ticker].dropna()
            if series.empty:
                col[ticker] = None
                continue
            if days == 0:  # YTD
                year_start = series[series.index.year == series.index[-1].year]
                base = year_start.iloc[0] if len(year_start) else None
            else:
                base = series.iloc[-1 - days] if len(series) > days else None
            col[ticker] = (float(series.iloc[-1] / base - 1) * 100
                           if base else None)
        out[name] = col
    return pd.DataFrame(out)


def relative_strength(close: pd.DataFrame, numer: str, denom: str,
                      rebase: bool = True) -> Optional[pd.Series]:
    """Ratio series numer/denom, optionally rebased to 100."""
    if numer not in close.columns or denom not in close.columns:
        return None
    ratio = (close[numer] / close[denom]).dropna()
    if ratio.empty:
        return None
    return ratio / ratio.iloc[0] * 100 if rebase else ratio
