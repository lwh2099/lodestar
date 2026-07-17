"""Smoke test: exercise every core module end-to-end against live sources.

Run from the project root:  .venv\\Scripts\\python.exe scripts\\smoke_test.py
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FAILURES: list[str] = []


def check(name: str, fn) -> None:
    try:
        detail = fn()
        print(f"[ok]   {name}: {detail}")
    except Exception:
        FAILURES.append(name)
        print(f"[FAIL] {name}")
        traceback.print_exc()


def test_fred():
    from core import fred
    snap = fred.snapshot("DGS10")
    assert snap.ok, snap.error
    assert snap.latest is not None
    cpi = fred.snapshot("CPIAUCSL")
    assert cpi.ok and cpi.latest is not None  # yoy transform
    spans = fred.recession_spans()
    assert len(spans) > 5
    return (f"DGS10={snap.latest:.2f}% ({snap.latest_date:%Y-%m-%d}), "
            f"CPI YoY={cpi.latest:.1f}%, {len(spans)} recessions")


def test_cache_roundtrip():
    from core import cache
    import pandas as pd
    df = pd.DataFrame({"value": [1.0, 2.0]},
                      index=pd.to_datetime(["2024-01-01", "2024-01-02"]))
    cache.write("test", "roundtrip", {"df": df, "n": 3})
    out, _ = cache.read("test", "roundtrip")
    assert isinstance(out["df"].index, pd.DatetimeIndex), type(out["df"].index)
    assert out["n"] == 3
    return "DataFrame + scalar survive SQLite roundtrip"


def test_market():
    from core import market
    q = market.quotes(["^GSPC", "^VIX"])
    assert q.ok, q.error
    assert "^GSPC" in q.data.index
    h = market.history(["XLK", "XLE"], period="1y")
    assert h.ok and h.data.shape[0] > 200, h.error
    r = market.trailing_returns(h.data, {"1M": 21, "YTD": 0})
    assert not r["1M"].isna().all()
    spx = float(q.data.loc["^GSPC", "last"])
    return f"S&P500={spx:,.0f}, sector history {h.data.shape}"


def test_sentiment():
    from core import sentiment
    thermo = sentiment.compute()
    assert thermo.score is not None, "no sentiment source alive"
    alive = [c.key for c in thermo.components if c.score is not None]
    return f"score={thermo.score} from {alive}"


def test_regime():
    from core import regime
    result = regime.evaluate()
    states = [d.state for d in result.dimensions]
    assert all(s != "Unknown" for s in states), states
    return f"{states} | {result.headline[:70]}..."


def test_granny():
    from core import granny
    result = granny.run()
    assert len(result.universe) > 100
    assert not result.hit_matrix.empty
    assert len(result.selection) >= 3, "portfolio suspiciously small"
    top = result.selection.index[:5].tolist()
    return (f"universe={len(result.universe)}, selected={len(result.selection)}, "
            f"top={top}, rebalance {result.next_rebalance} "
            f"({result.days_to_rebalance}d)")


def test_seasonality():
    from core import seasonality
    hist = seasonality.price_history()
    assert hist.ok, hist.error
    monthly = seasonality.monthly_stats(hist.data)
    weekday = seasonality.weekday_stats(hist.data)
    pres = seasonality.presidential_stats(hist.data)
    matrix = seasonality.cycle_month_matrix(hist.data)
    assert monthly.shape[0] == 12 and weekday.shape[0] == 5
    assert pres.shape[0] == 4 and matrix.shape == (4, 12)
    ctx = seasonality.current_context()
    return (f"since {hist.data.index[0].year}, now={ctx.month_label}/"
            f"{ctx.cycle}, Jul avg={monthly.loc['Jul', 'avg_return']:+.2f}%")


def test_ui_imports():
    from ui import theme, components, charts  # noqa: F401
    import pandas as pd
    theme.register_plotly_template()
    fig = charts.line(pd.Series([1.0, 2.0, 1.5],
                                index=pd.date_range("2024-01-01", periods=3)),
                      "test", units="%")
    assert fig.layout.template is not None
    svg = components.sparkline_svg([1, 2, 3])
    assert svg.startswith("<svg")
    return "theme/template/components build"


if __name__ == "__main__":
    check("cache roundtrip", test_cache_roundtrip)
    check("FRED", test_fred)
    check("market (yfinance)", test_market)
    check("sentiment", test_sentiment)
    check("regime", test_regime)
    check("granny shots", test_granny)
    check("seasonality", test_seasonality)
    check("ui imports", test_ui_imports)
    print(f"\n{len(FAILURES)} failure(s): {FAILURES or 'none'}")
    raise SystemExit(1 if FAILURES else 0)
