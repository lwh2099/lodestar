"""Granny Shots cross-section engine.

Seven investment themes (config/themes.yaml) map to ticker lists — three of
them computed from live data. A stock enters the portfolio when it is hit by
at least two themes; holdings are equal-weighted and rebalanced on the first
weekday of January, April, July and October.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from core import fred, market

THEMES_PATH = Path(__file__).resolve().parents[1] / "config" / "themes.yaml"

MIN_HITS = 2
RS_WINDOW_DAYS = 63  # ~3 months of trading days


def load_themes_config() -> dict:
    # Re-read on every run so edits to themes.yaml apply on refresh.
    with open(THEMES_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass
class Theme:
    key: str
    label: str
    kind: str                    # static | dynamic | conditional
    active: bool
    members: list[str]
    note: str = ""
    description: str = ""


@dataclass
class EngineResult:
    themes: list[Theme]
    universe: list[str]
    hit_matrix: pd.DataFrame          # bool, index=ticker, columns=theme label
    selection: pd.DataFrame           # selected names with hits/weight/sector
    overlap: pd.DataFrame             # theme x theme shared-member counts
    next_rebalance: date
    days_to_rebalance: int
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# Sector lookup
# --------------------------------------------------------------------------

def sector_lookup(cfg: dict) -> dict[str, str]:
    names = cfg.get("sector_names", {})
    lookup: dict[str, str] = {}
    for etf, tickers in cfg.get("sector_pools", {}).items():
        for ticker in tickers:
            lookup[ticker] = names.get(etf, etf)
    lookup.update(cfg.get("extra_sectors", {}))
    return lookup


# --------------------------------------------------------------------------
# Dynamic theme builders
# --------------------------------------------------------------------------

def _trailing_return(series: pd.Series, days: int) -> Optional[float]:
    series = series.dropna()
    if len(series) <= days:
        return None
    return float(series.iloc[-1] / series.iloc[-1 - days] - 1) * 100


def _style_tilt(theme_cfg: dict, force: bool,
                warnings: list[str]) -> tuple[list[str], str]:
    pools = theme_cfg.get("pools", {})
    result = market.history(["IWD", "IWF", "IWM"], period="6mo", force=force)
    if not result.ok:
        warnings.append("Style Tilt: ETF data unavailable, theme skipped.")
        return [], "style ETFs unavailable"

    close = result.data
    r_value = _trailing_return(close.get("IWD", pd.Series(dtype=float)), RS_WINDOW_DAYS)
    r_growth = _trailing_return(close.get("IWF", pd.Series(dtype=float)), RS_WINDOW_DAYS)
    r_small = _trailing_return(close.get("IWM", pd.Series(dtype=float)), RS_WINDOW_DAYS)
    if r_value is None or r_growth is None:
        warnings.append("Style Tilt: not enough ETF history, theme skipped.")
        return [], "insufficient history"

    members: list[str] = []
    notes: list[str] = []
    if r_value > r_growth:
        members += pools.get("value", [])
        notes.append(f"Value leads Growth by {r_value - r_growth:+.1f}pp (3M)")
    else:
        members += pools.get("growth", [])
        notes.append(f"Growth leads Value by {r_growth - r_value:+.1f}pp (3M)")
    if r_small is not None and r_small > r_growth:
        members += pools.get("smallcap", [])
        notes.append(f"small caps lead large by {r_small - r_growth:+.1f}pp")
    return list(dict.fromkeys(members)), "; ".join(notes)


def _seasonality_theme(cfg: dict, theme_cfg: dict, force: bool,
                       warnings: list[str]) -> tuple[list[str], str]:
    pools = cfg.get("sector_pools", {})
    names = cfg.get("sector_names", {})
    etfs = list(pools.keys())
    result = market.history(etfs, period="max", force=force)
    if not result.ok:
        warnings.append("Seasonality theme: sector ETF history unavailable, theme skipped.")
        return [], "sector history unavailable"

    close = result.data
    month = date.today().month
    scores: dict[str, float] = {}
    for etf in etfs:
        if etf not in close.columns:
            continue
        monthly = close[etf].dropna().resample("ME").last().pct_change().dropna()
        in_month = monthly[monthly.index.month == month]
        if len(in_month) >= 5:  # require a few years of history
            scores[etf] = float(in_month.mean()) * 100

    if not scores:
        warnings.append("Seasonality theme: not enough monthly history.")
        return [], "insufficient history"

    top_n = int(theme_cfg.get("top_sectors", 3))
    top = sorted(scores, key=scores.get, reverse=True)[:top_n]
    members: list[str] = []
    for etf in top:
        members += pools.get(etf, [])
    label = date(2000, month, 1).strftime("%B")
    note = (f"best {label} sectors historically: "
            + ", ".join(f"{names.get(e, e)} ({scores[e]:+.1f}%)" for e in top))
    return list(dict.fromkeys(members)), note


def _easing_conditions(theme_cfg: dict, force: bool,
                       warnings: list[str]) -> tuple[bool, list[str], str]:
    try:
        nfci = fred.snapshot("NFCI", force=force)
    except Exception:  # noqa: BLE001
        nfci = None
    if nfci is None or not nfci.ok:
        warnings.append("Easing Fin. Conditions: NFCI unavailable, theme inactive.")
        return False, [], "NFCI unavailable"
    if nfci.latest < 0:
        return True, theme_cfg.get("members", []), f"active — NFCI {nfci.latest:+.2f} (< 0)"
    return False, [], f"inactive — NFCI {nfci.latest:+.2f} (>= 0)"


# --------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------

def build_themes(force: bool = False) -> tuple[list[Theme], list[str], dict]:
    cfg = load_themes_config()
    warnings: list[str] = []
    themes: list[Theme] = []

    for key, tc in cfg.get("themes", {}).items():
        kind = tc.get("kind", "static")
        label = tc.get("label", key)
        description = tc.get("description", "")
        if key == "style_tilt":
            members, note = _style_tilt(tc, force, warnings)
            themes.append(Theme(key, label, kind, bool(members), members,
                                note, description))
        elif key == "seasonality":
            members, note = _seasonality_theme(cfg, tc, force, warnings)
            themes.append(Theme(key, label, kind, bool(members), members,
                                note, description))
        elif kind == "conditional":
            active, members, note = _easing_conditions(tc, force, warnings)
            themes.append(Theme(key, label, kind, active, members, note,
                                description))
        else:
            members = tc.get("members", [])
            themes.append(Theme(key, label, kind, True, members,
                                f"{len(members)} fixed constituents", description))
    return themes, warnings, cfg


def next_rebalance(today: Optional[date] = None,
                   months: Optional[list[int]] = None) -> date:
    """First weekday of the next rebalance month (Jan/Apr/Jul/Oct)."""
    today = today or date.today()
    months = months or [1, 4, 7, 10]
    candidates = []
    for year in (today.year, today.year + 1):
        for month in months:
            day = date(year, month, 1)
            while day.weekday() >= 5:
                day += timedelta(days=1)
            candidates.append(day)
    return min(d for d in candidates if d >= today)


def run(force: bool = False) -> EngineResult:
    themes, warnings, cfg = build_themes(force=force)
    lookup = sector_lookup(cfg)

    # Candidate universe = union of all sector pools and theme members.
    universe: list[str] = []
    for tickers in cfg.get("sector_pools", {}).values():
        universe += tickers
    for theme in themes:
        universe += theme.members
    for tc in cfg.get("themes", {}).values():
        universe += tc.get("members", [])
        for pool in tc.get("pools", {}).values():
            universe += pool
    universe = sorted(dict.fromkeys(universe))

    active = [t for t in themes if t.active]
    hit_matrix = pd.DataFrame(False, index=universe,
                              columns=[t.label for t in active])
    for theme in active:
        for ticker in theme.members:
            if ticker in hit_matrix.index:
                hit_matrix.loc[ticker, theme.label] = True

    hits = hit_matrix.sum(axis=1)
    selected = hits[hits >= MIN_HITS].sort_values(ascending=False)

    rows = []
    weight = 1 / len(selected) if len(selected) else 0.0
    for ticker, hit_count in selected.items():
        theme_labels = [c for c in hit_matrix.columns if hit_matrix.loc[ticker, c]]
        rows.append({"ticker": ticker,
                     "sector": lookup.get(ticker, "Other"),
                     "hits": int(hit_count),
                     "themes": " + ".join(theme_labels),
                     "weight": weight})
    selection = pd.DataFrame(rows)
    if not selection.empty:
        selection = selection.set_index("ticker")

    # Theme overlap: shared members between each pair of active themes.
    labels = [t.label for t in active]
    overlap = pd.DataFrame(0, index=labels, columns=labels)
    for a in active:
        for b in active:
            shared = set(a.members) & set(b.members)
            overlap.loc[a.label, b.label] = len(shared)

    reb_date = next_rebalance(months=cfg.get("rebalance_months"))
    return EngineResult(
        themes=themes, universe=universe, hit_matrix=hit_matrix,
        selection=selection, overlap=overlap, next_rebalance=reb_date,
        days_to_rebalance=(reb_date - date.today()).days, warnings=warnings)


def attach_market_data(selection: pd.DataFrame,
                       force: bool = False) -> pd.DataFrame:
    """Add last price, 1-day and 3-month return columns to the selection."""
    if selection.empty:
        return selection
    tickers = list(selection.index)
    out = selection.copy()

    quote_res = market.quotes(tickers, force=force)
    if quote_res.ok:
        quotes = quote_res.data
        out["price"] = [float(quotes.loc[t, "last"]) if t in quotes.index else None
                        for t in tickers]
        out["1d_pct"] = [float(quotes.loc[t, "chg_pct"]) if t in quotes.index else None
                         for t in tickers]

    hist_res = market.history(tickers, period="6mo", force=force)
    if hist_res.ok:
        close = hist_res.data
        out["3m_pct"] = [
            _trailing_return(close[t], RS_WINDOW_DAYS)
            if t in close.columns else None
            for t in tickers]
    return out
