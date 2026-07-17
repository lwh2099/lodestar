"""FRED data layer.

Series are downloaded through FRED's keyless ``fredgraph.csv`` endpoint, so
no API key or registration is required. Display metadata (labels, categories,
transforms) lives in ``config/series.yaml`` — add a row there and the series
shows up across the app automatically.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yaml

from core import cache

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "series.yaml"
FRED_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
HEADERS = {"User-Agent": "Lodestar/1.0 (personal research dashboard)"}

DEFAULT_TTL_HOURS = {"D": 12, "W": 24, "M": 24, "Q": 24}
# Periods per year, used by the yoy transform.
YOY_PERIODS = {"M": 12, "Q": 4, "W": 52, "D": 252}


@lru_cache(maxsize=1)
def load_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def all_series() -> dict[str, dict]:
    return load_config()["series"]


def categories() -> list[tuple[str, str]]:
    """Ordered [(key, label), ...] of display categories."""
    cats = load_config()["categories"]
    return [(k, v["label"]) for k, v in
            sorted(cats.items(), key=lambda kv: kv[1].get("order", 99))]


def series_meta(sid: str) -> dict:
    return all_series().get(sid, {"name": sid, "category": "other", "freq": "D"})


def series_for_category(cat_key: str) -> list[str]:
    return [sid for sid, meta in all_series().items()
            if meta.get("category") == cat_key and not meta.get("hidden")]


# --------------------------------------------------------------------------
# Download + cache
# --------------------------------------------------------------------------

def _download(sid: str) -> pd.DataFrame:
    resp = requests.get(FRED_CSV_URL.format(sid=sid), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    raw = pd.read_csv(io.StringIO(resp.text))
    if raw.shape[1] < 2:
        raise ValueError(f"unexpected FRED response for {sid}")
    date_col, value_col = raw.columns[0], raw.columns[1]
    out = (raw.assign(**{date_col: pd.to_datetime(raw[date_col]),
                         value_col: pd.to_numeric(raw[value_col], errors="coerce")})
              .rename(columns={date_col: "date", value_col: "value"})
              .dropna(subset=["value"])
              .set_index("date"))
    return out[["value"]]


def fetch(sid: str, force: bool = False) -> cache.CacheResult:
    meta = series_meta(sid)
    ttl_hours = meta.get("ttl_hours",
                         DEFAULT_TTL_HOURS.get(meta.get("freq", "D"), 12))
    return cache.fetch_with_cache(
        "fred", sid, ttl_hours * 3600,
        lambda: cache.retry(lambda: _download(sid)),
        force_refresh=force)


# --------------------------------------------------------------------------
# Snapshot: one series, ready for display
# --------------------------------------------------------------------------

@dataclass
class Snapshot:
    sid: str
    name: str
    units: str
    decimals: int
    good_when: str            # up | down | none
    category: str
    freq: str
    display: Optional[pd.Series]   # transformed, scaled series for charts
    raw: Optional[pd.Series]       # untransformed (scaled) series
    latest: Optional[float]
    latest_date: Optional[datetime]
    delta: Optional[float]         # change vs previous observation of `display`
    fetched_at: Optional[datetime]
    is_stale: bool
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.display is not None and len(self.display) > 0

    @property
    def delta_direction(self) -> int:
        """+1 favourable move, -1 unfavourable, 0 neutral/unknown."""
        if self.delta is None or self.good_when not in ("up", "down"):
            return 0
        sign = 1 if self.delta > 0 else (-1 if self.delta < 0 else 0)
        return sign if self.good_when == "up" else -sign

    def spark(self, points: int = 60) -> list[float]:
        if not self.ok:
            return []
        return list(self.display.tail(points).values)

    def value_text(self) -> str:
        return format_value(self.latest, self.units, self.decimals)

    def delta_text(self) -> str:
        if self.delta is None:
            return ""
        if self.delta == 0:
            return "unchanged"
        arrow = "▲" if self.delta > 0 else "▼"
        return f"{arrow} {format_value(abs(self.delta), self.units, self.decimals)}"


def format_value(value: Optional[float], units: str = "", decimals: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    if units in ("$tn", "$bn", "$mn"):        # e.g. $1.23tn (leading $, drop it from suffix)
        return f"${value:,.{decimals}f}{units[1:]}"
    return f"{value:,.{decimals}f}{units}"    # units="" collapses to the bare number


def _transform(values: pd.Series, meta: dict) -> pd.Series:
    transform = meta.get("transform", "level")
    if transform == "yoy":
        periods = YOY_PERIODS.get(meta.get("freq", "M"), 12)
        return (values.pct_change(periods) * 100).dropna()
    if transform == "mom_diff":
        return values.diff().dropna()
    return values


def snapshot(sid: str, force: bool = False) -> Snapshot:
    meta = series_meta(sid)
    base = Snapshot(
        sid=sid, name=meta.get("name", sid), units=meta.get("units", ""),
        decimals=int(meta.get("decimals", 2)),
        good_when=meta.get("good_when", "none"),
        category=meta.get("category", "other"), freq=meta.get("freq", "D"),
        display=None, raw=None, latest=None, latest_date=None, delta=None,
        fetched_at=None, is_stale=True)

    result = fetch(sid, force=force)
    base.fetched_at = result.fetched_at
    base.is_stale = result.is_stale
    base.error = result.error
    if not result.ok:
        return base

    df: pd.DataFrame = result.data
    scaled = df["value"] * float(meta.get("scale", 1))
    display = _transform(scaled, meta)
    if display.empty:
        return base

    base.raw = scaled
    base.display = display
    base.latest = float(display.iloc[-1])
    base.latest_date = display.index[-1].to_pydatetime()
    if len(display) > 1:
        base.delta = float(display.iloc[-1] - display.iloc[-2])
    return base


def value_asof(snap: Snapshot, days_back: int) -> Optional[float]:
    """Display-series value as of `days_back` calendar days before the latest print."""
    if not snap.ok or snap.latest_date is None:
        return None
    target = snap.display.index[-1] - pd.Timedelta(days=days_back)
    val = snap.display.asof(target)
    return None if pd.isna(val) else float(val)


def recession_spans(force: bool = False) -> list[tuple[datetime, datetime]]:
    """NBER recession (start, end) spans for chart shading."""
    result = fetch("USREC", force=force)
    if not result.ok:
        return []
    flag = result.data["value"]
    spans: list[tuple[datetime, datetime]] = []
    start = None
    for date, val in flag.items():
        if val >= 1 and start is None:
            start = date
        elif val < 1 and start is not None:
            spans.append((start.to_pydatetime(), date.to_pydatetime()))
            start = None
    if start is not None:
        spans.append((start.to_pydatetime(), flag.index[-1].to_pydatetime()))
    return spans
