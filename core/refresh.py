"""Full data refresh, shared by the in-app "Update all data" button
(sidebar) and the optional CLI script."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from core import cache, fred, market, seasonality, sentiment


@dataclass
class Job:
    name: str
    run: Callable[[], cache.CacheResult]


@dataclass
class JobOutcome:
    name: str
    ok: bool
    stale: bool
    error: str | None


def jobs() -> list[Job]:
    """Every cached source, as one forced-refresh job each."""
    out: list[Job] = []

    for sid in fred.all_series():
        out.append(Job(f"FRED · {sid}",
                       lambda sid=sid: fred.fetch(sid, force=True)))

    sectors = list(market.GROUPS["sectors"].keys())
    styles = list(market.GROUPS["styles"].keys()) + ["SPY"]
    bonds = list(market.GROUPS["bonds"].keys())
    commodities = list(market.GROUPS["commodities"].keys())

    # Cache keys are hashed by ticker-set, so pre-fetching one all-ticker blob
    # would miss every page's narrower subset read. Mirror the exact requests
    # the pages make instead — this both warms the real keys and avoids
    # downloading histories nothing reads.
    market_jobs = [
        ("Market · quotes (10d)", market.all_tickers(), "10d"),
        ("Market · sector ETFs (1y)", sectors, "1y"),
        ("Market · style & factor ETFs (1y)", styles, "1y"),
        ("Market · bond ETFs (1y)", bonds, "1y"),
        ("Granny · style ETFs (6mo)", ["IWD", "IWF", "IWM"], "6mo"),
        ("Market · sector ETFs full history", sectors, "max"),
        ("Market · commodities full history", commodities, "max"),
        # Read by both the Regime page and the Sentiment VIX+F&G chart.
        ("Regime & Sentiment · VIX full history", ["^VIX"], "max"),
        ("Seasonality · S&P 500 full history", [seasonality.TICKER], "max"),
    ]
    for name, tickers, period in market_jobs:
        out.append(Job(name, lambda t=tickers, p=period:
                       market.history(t, period=p, force=True)))

    out.append(Job("Sentiment · CNN Fear & Greed",
                   lambda: sentiment.fear_greed(force=True)))
    return out


def run_job(job: Job) -> JobOutcome:
    try:
        result = job.run()
        return JobOutcome(job.name, result.ok, result.is_stale, result.error)
    except Exception as exc:  # noqa: BLE001 - a bad source must not stop the batch
        return JobOutcome(job.name, False, True, str(exc))
