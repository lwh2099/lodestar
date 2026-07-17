"""S&P 500 seasonality, self-computed from price history (zero API cost).

Uses ^GSPC (index history back to 1927) rather than SPY so monthly and
presidential-cycle statistics rest on ~100 years of data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import pandas as pd

from core import cache, market

TICKER = "^GSPC"

MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri"]
CYCLE_LABELS = {1: "Post-election", 2: "Midterm", 3: "Pre-election", 0: "Election"}
CYCLE_ORDER = ["Post-election", "Midterm", "Pre-election", "Election"]


def price_history(force: bool = False) -> cache.CacheResult:
    result = market.history([TICKER], period="max", force=force)
    if result.ok and TICKER in result.data.columns:
        return cache.CacheResult(result.data[TICKER].dropna(),
                                 result.fetched_at, result.from_cache,
                                 result.is_stale, result.error)
    return cache.CacheResult(None, result.fetched_at, False, True, result.error)


def cycle_label(year: int) -> str:
    return CYCLE_LABELS[year % 4]


@dataclass
class CurrentContext:
    month_label: str
    weekday_label: Optional[str]     # None on weekends
    cycle: str
    year: int


def current_context(today: Optional[date] = None) -> CurrentContext:
    today = today or date.today()
    weekday = WEEKDAY_LABELS[today.weekday()] if today.weekday() < 5 else None
    return CurrentContext(MONTH_LABELS[today.month - 1], weekday,
                          cycle_label(today.year), today.year)


# --------------------------------------------------------------------------
# Statistics (all take the price series from ``price_history``)
# --------------------------------------------------------------------------

def monthly_stats(prices: pd.Series) -> pd.DataFrame:
    """Average return, median and win rate per calendar month."""
    monthly = prices.resample("ME").last().pct_change().dropna() * 100
    grouped = monthly.groupby(monthly.index.month)
    stats = pd.DataFrame({
        "avg_return": grouped.mean(),
        "median_return": grouped.median(),
        "win_rate": grouped.apply(lambda x: (x > 0).mean() * 100),
        "years": grouped.count(),
    })
    stats.index = [MONTH_LABELS[m - 1] for m in stats.index]
    return stats.round(2)


def weekday_stats(prices: pd.Series) -> pd.DataFrame:
    """Average daily return and win rate per weekday."""
    daily = prices.pct_change().dropna() * 100
    daily = daily[daily.index.weekday < 5]
    grouped = daily.groupby(daily.index.weekday)
    stats = pd.DataFrame({
        "avg_return": grouped.mean(),
        "win_rate": grouped.apply(lambda x: (x > 0).mean() * 100),
        "obs": grouped.count(),
    })
    stats.index = [WEEKDAY_LABELS[d] for d in stats.index]
    return stats.round(3)


def presidential_stats(prices: pd.Series) -> pd.DataFrame:
    """Average annual return and win rate per presidential-cycle year."""
    annual = prices.resample("YE").last().pct_change().dropna() * 100
    labels = pd.Series([cycle_label(ts.year) for ts in annual.index],
                       index=annual.index)
    grouped = annual.groupby(labels)
    stats = pd.DataFrame({
        "avg_return": grouped.mean(),
        "win_rate": grouped.apply(lambda x: (x > 0).mean() * 100),
        "years": grouped.count(),
    })
    return stats.reindex(CYCLE_ORDER).round(2)


def monthly_returns_by_year(prices: pd.Series) -> pd.DataFrame:
    """Return matrix indexed by year, one column per calendar month (%).

    Row = calendar year, column = Jan..Dec, cell = that month's return that
    year. Feeds the "each line is a month, x-axis is years" trend chart.
    """
    monthly = prices.resample("ME").last().pct_change().dropna() * 100
    frame = pd.DataFrame({
        "ret": monthly.values,
        "year": monthly.index.year,
        "month": [MONTH_LABELS[ts.month - 1] for ts in monthly.index],
    })
    matrix = frame.pivot_table(values="ret", index="year", columns="month",
                               aggfunc="mean")
    return matrix.reindex(columns=MONTH_LABELS).round(2)


def cycle_month_matrix(prices: pd.Series) -> pd.DataFrame:
    """Average monthly return by (cycle year, calendar month)."""
    monthly = prices.resample("ME").last().pct_change().dropna() * 100
    frame = pd.DataFrame({
        "ret": monthly.values,
        "cycle": [cycle_label(ts.year) for ts in monthly.index],
        "month": [MONTH_LABELS[ts.month - 1] for ts in monthly.index],
    })
    matrix = (frame.pivot_table(values="ret", index="cycle", columns="month",
                                aggfunc="mean")
                   .reindex(CYCLE_ORDER)
                   .reindex(columns=MONTH_LABELS))
    return matrix.round(2)
