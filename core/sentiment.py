"""Sentiment sources and the Fear & Greed thermometer.

Sources (all best-effort, cached, individually skippable):
  - CNN Fear & Greed via CNN's public graphdata endpoint (the headline gauge)
  - VIX             via yfinance (context reading + fallback)

The gauge shows CNN's Fear & Greed index as-is: 0 = extreme fear,
100 = extreme greed. VIX only stands in when the CNN scrape is down.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
import yaml

from core import cache, market

THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / "config" / "thresholds.yaml"

CNN_FNG_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
# The bare endpoint returns only the trailing ~year. Appending a start date
# pulls the full series; CNN's index history begins 2020-07-14 and an earlier
# start 500s, so pin to the first available day for the maximum history.
CNN_FNG_START = "2020-07-14"
CNN_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "application/json",
    "Referer": "https://edition.cnn.com/markets/fear-and-greed",
}

SENTIMENT_TTL = 6 * 3600  # spec: 6h for scraped sentiment sources


def load_sentiment_config() -> dict:
    with open(THRESHOLDS_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)["sentiment"]


# --------------------------------------------------------------------------
# Sources
# --------------------------------------------------------------------------

def vix_quote(force: bool = False) -> cache.CacheResult:
    result = market.quotes(["^VIX"], force=force)
    if result.ok and "^VIX" in result.data.index:
        value = float(result.data.loc["^VIX", "last"])
        return cache.CacheResult(value, result.fetched_at, result.from_cache,
                                 result.is_stale, result.error)
    return cache.CacheResult(None, result.fetched_at, result.from_cache,
                             True, result.error or "VIX unavailable")


def _fetch_fng(url: str) -> dict:
    resp = requests.get(url, headers=CNN_HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _download_fear_greed() -> dict:
    # Pull the full history from CNN's floor; if that dated request ever 500s,
    # fall back to the bare endpoint (trailing ~year) so we degrade to less
    # history instead of failing the fetch entirely.
    try:
        payload = _fetch_fng(f"{CNN_FNG_URL}/{CNN_FNG_START}")
    except requests.RequestException:
        payload = _fetch_fng(CNN_FNG_URL)
    now = payload["fear_and_greed"]
    hist_points = payload.get("fear_and_greed_historical", {}).get("data", [])
    hist = pd.DataFrame(hist_points)
    if not hist.empty:
        hist = (hist.assign(date=pd.to_datetime(hist["x"], unit="ms"))
                    .set_index("date")[["y"]]
                    .rename(columns={"y": "score"}))
    return {"score": float(now["score"]), "rating": str(now["rating"]),
            "history": hist}


def fear_greed(force: bool = False) -> cache.CacheResult:
    return cache.fetch_with_cache(
        "sentiment", "fear_greed", SENTIMENT_TTL,
        lambda: cache.retry(_download_fear_greed),
        force_refresh=force)


# --------------------------------------------------------------------------
# Composite thermometer
# --------------------------------------------------------------------------

@dataclass
class Component:
    key: str
    label: str
    value_text: str               # formatted reading for the tile, e.g. "38"
    raw_text: str                 # short descriptor under the value (rating)
    score: Optional[float]        # numeric reading, None if source unavailable
    fetched_at: Optional[datetime]
    is_stale: bool


@dataclass
class Thermometer:
    score: Optional[float]        # 0-100 Fear & Greed: 0 = fear, 100 = greed
    components: list[Component]
    driver: Optional[str] = None  # key of the component the score is taken from

    @property
    def verdict(self) -> str:
        """The plain Fear & Greed level (CNN's bands), no contrarian spin."""
        if self.score is None:
            return "No data"
        if self.score >= 75:
            return "Extreme greed"
        if self.score >= 55:
            return "Greed"
        if self.score >= 45:
            return "Neutral"
        if self.score >= 25:
            return "Fear"
        return "Extreme fear"


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def compute(force: bool = False) -> Thermometer:
    """Concluded score = the CNN Fear & Greed index, shown as-is (0-100).

    The gauge is CNN's headline reading (0 = extreme fear, 100 = extreme greed),
    not an inverted/contrarian transform — CNN's index is already a 7-factor
    composite that *includes VIX* (alongside momentum, breadth, 52-week
    strength, put/call, safe-haven and junk-bond demand), so VIX isn't blended
    back in. VIX is kept only as a context reading and as a fallback: if the CNN
    scrape is down, the score falls back to a VIX-derived fear/greed proxy (low
    VIX → greed, high VIX → fear) so the gauge still works.
    """
    cfg = load_sentiment_config()

    vix_res = vix_quote(force=force)
    fng_res = fear_greed(force=force)

    fng_val = None
    if fng_res.ok:
        fng_val = float(fng_res.data["score"])
    fng_comp = Component(
        "fear_greed", "CNN Fear & Greed",
        f"{fng_val:.0f}" if fng_val is not None else "—",
        str(fng_res.data["rating"]).lower() if fng_res.ok else "unavailable",
        fng_val, fng_res.fetched_at, fng_res.is_stale)

    vix_val = None
    if vix_res.ok:
        vix_val = float(vix_res.data)
    vix_comp = Component(
        "vix", "VIX",
        f"{vix_val:.1f}" if vix_val is not None else "—",
        "implied volatility" if vix_res.ok else "unavailable",
        vix_val, vix_res.fetched_at, vix_res.is_stale)

    # CNN F&G leads and is listed first (it drives the gauge); VIX is context.
    components = [fng_comp, vix_comp]

    if fng_val is not None:
        return Thermometer(round(fng_val, 1), components, driver="fear_greed")
    if vix_val is not None:
        # Fallback only: map VIX onto the 0-100 fear/greed scale so the gauge
        # still reads when CNN is down. High VIX → fear (low), calm → greed.
        floor, ceil = cfg["vix_floor"], cfg["vix_ceiling"]
        vix_fg = _clip01((ceil - vix_val) / (ceil - floor)) * 100
        return Thermometer(round(vix_fg, 1), components, driver="vix")
    return Thermometer(None, components)
