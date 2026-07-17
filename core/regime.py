"""Rule-based macro regime state machine (Regime Compass core).

Three dimensions, each scored from explainable rules with thresholds in
``config/thresholds.yaml``:

  Monetary  Easing / Neutral / Tightening      (NFCI + Fed funds + 2Y trend)
  Growth    Expansion / Slowing / Contraction  (IPMAN, GDPNow, claims, payrolls)
  Risk      Risk-on / Neutral / Risk-off       (VIX, HY OAS, curve inversion)

Every input is fetched defensively: a missing source turns its rule off and
is listed in the dimension detail instead of crashing the page.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

from core import fred, market

THRESHOLDS_PATH = Path(__file__).resolve().parents[1] / "config" / "thresholds.yaml"


def load_thresholds() -> dict:
    with open(THRESHOLDS_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass
class Dimension:
    key: str
    label: str
    state: str                    # e.g. "Easing", "Unknown"
    tone: str                     # up | down | neutral | muted (pill colour)
    score: Optional[float]
    details: list[str] = field(default_factory=list)


@dataclass
class RegimeResult:
    monetary: Dimension
    growth: Dimension
    risk: Dimension
    curve_inverted: Optional[bool]
    headline: str

    @property
    def dimensions(self) -> list[Dimension]:
        return [self.monetary, self.growth, self.risk]


def _safe_snapshot(sid: str, force: bool) -> Optional[fred.Snapshot]:
    try:
        snap = fred.snapshot(sid, force=force)
        return snap if snap.ok else None
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------
# Dimension rules
# --------------------------------------------------------------------------

def _monetary(th: dict, force: bool) -> Dimension:
    cfg = th["monetary"]
    details: list[str] = []
    score = 0.0
    have_input = False

    nfci = _safe_snapshot("NFCI", force)
    if nfci is not None:
        have_input = True
        val = nfci.latest
        if val < cfg["nfci_easing"]:
            score -= 1.0
            details.append(f"NFCI {val:+.2f} → conditions loose")
        elif val > cfg["nfci_tightening"]:
            score += 1.0
            details.append(f"NFCI {val:+.2f} → conditions tight")
        else:
            details.append(f"NFCI {val:+.2f} → around neutral")
    else:
        details.append("NFCI unavailable")

    dff = _safe_snapshot("DFF", force)
    if dff is not None:
        past = fred.value_asof(dff, 90)
        if past is not None:
            have_input = True
            move = dff.latest - past
            if move < -cfg["dff_confirm_pp"]:
                score -= 0.5
                details.append(f"Fed funds {move:+.2f}pp over 3m (cutting)")
            elif move > cfg["dff_confirm_pp"]:
                score += 0.5
                details.append(f"Fed funds {move:+.2f}pp over 3m (hiking)")
            else:
                details.append(f"Fed funds {move:+.2f}pp over 3m (on hold)")

    dgs2 = _safe_snapshot("DGS2", force)
    if dgs2 is not None:
        past = fred.value_asof(dgs2, 30)
        if past is not None:
            have_input = True
            move = dgs2.latest - past
            if move < -cfg["dgs2_confirm_pp"]:
                score -= 0.25
                details.append(f"2Y yield {move:+.2f}pp over 1m (pricing easing)")
            elif move > cfg["dgs2_confirm_pp"]:
                score += 0.25
                details.append(f"2Y yield {move:+.2f}pp over 1m (pricing tightening)")

    if not have_input:
        return Dimension("monetary", "Monetary", "Unknown", "muted", None, details)
    if score <= cfg["score_easing"]:
        return Dimension("monetary", "Monetary", "Easing", "up", score, details)
    if score >= cfg["score_tightening"]:
        return Dimension("monetary", "Monetary", "Tightening", "down", score, details)
    return Dimension("monetary", "Monetary", "Neutral", "neutral", score, details)


def _growth(th: dict, force: bool) -> Dimension:
    cfg = th["growth"]
    details: list[str] = []
    score = 0.0
    have_input = False

    ipman = _safe_snapshot("IPMAN", force)
    if ipman is not None:
        have_input = True
        yoy = ipman.latest  # IPMAN is configured with the yoy transform
        if yoy > 0:
            score += 1.0
            details.append(f"Manufacturing output {yoy:+.1f}% YoY (growing)")
        else:
            score -= 1.0
            details.append(f"Manufacturing output {yoy:+.1f}% YoY (shrinking)")
    else:
        details.append("IPMAN unavailable")

    gdpnow = _safe_snapshot("GDPNOW", force)
    if gdpnow is not None:
        have_input = True
        val = gdpnow.latest
        if val >= cfg["gdpnow_strong"]:
            score += 1.0
            details.append(f"GDPNow {val:.1f}% (above trend)")
        elif val < cfg["gdpnow_weak"]:
            score -= 1.0
            details.append(f"GDPNow {val:.1f}% (contraction territory)")
        else:
            details.append(f"GDPNow {val:.1f}% (sub-trend)")
    else:
        details.append("GDPNow unavailable")

    icsa = _safe_snapshot("ICSA", force)
    if icsa is not None and len(icsa.display) >= 8:
        have_input = True
        recent = float(icsa.display.iloc[-4:].mean())
        prior = float(icsa.display.iloc[-8:-4].mean())
        change_pct = (recent / prior - 1) * 100 if prior else 0.0
        if change_pct > cfg["icsa_rise_pct"]:
            score -= 1.0
            details.append(f"Jobless claims 4-wk avg {change_pct:+.1f}% (rising)")
        elif change_pct < -cfg["icsa_fall_pct"]:
            score += 0.5
            details.append(f"Jobless claims 4-wk avg {change_pct:+.1f}% (falling)")
        else:
            details.append(f"Jobless claims 4-wk avg {change_pct:+.1f}% (steady)")

    payems = _safe_snapshot("PAYEMS", force)
    if payems is not None and len(payems.display) >= 6:
        have_input = True
        recent = float(payems.display.iloc[-3:].mean())
        prior = float(payems.display.iloc[-6:-3].mean())
        if recent < prior - cfg["payems_slowdown_k"]:
            score -= 0.5
            details.append(f"Payroll gains slowing: {recent:.0f}k vs {prior:.0f}k (3m avg)")
        elif recent > prior + cfg["payems_slowdown_k"]:
            score += 0.25
            details.append(f"Payroll gains accelerating: {recent:.0f}k vs {prior:.0f}k")
        else:
            details.append(f"Payroll gains steady around {recent:.0f}k/month")

    if not have_input:
        return Dimension("growth", "Growth", "Unknown", "muted", None, details)
    if score >= cfg["score_expansion"]:
        return Dimension("growth", "Growth", "Expansion", "up", score, details)
    if score <= cfg["score_contraction"]:
        return Dimension("growth", "Growth", "Contraction", "down", score, details)
    return Dimension("growth", "Growth", "Slowing", "neutral", score, details)


def _risk(th: dict, force: bool) -> tuple[Dimension, Optional[bool]]:
    cfg = th["risk"]
    details: list[str] = []
    score = 0.0
    have_input = False
    inverted: Optional[bool] = None

    vix_val: Optional[float] = None
    try:
        quotes = market.quotes(["^VIX"], force=force)
        if quotes.ok and "^VIX" in quotes.data.index:
            vix_val = float(quotes.data.loc["^VIX", "last"])
    except Exception:  # noqa: BLE001
        pass
    if vix_val is not None:
        have_input = True
        if vix_val < cfg["vix_calm"]:
            score += 1.0
            details.append(f"VIX {vix_val:.1f} (calm)")
        elif vix_val > cfg["vix_stress"]:
            score -= 1.0
            details.append(f"VIX {vix_val:.1f} (stressed)")
        else:
            details.append(f"VIX {vix_val:.1f} (normal)")
    else:
        details.append("VIX unavailable")

    hy = _safe_snapshot("BAMLH0A0HYM2", force)
    if hy is not None:
        have_input = True
        val = hy.latest
        if val < cfg["hy_oas_complacent"]:
            score += 1.0
            details.append(f"HY OAS {val:.2f}% (tight / complacent)")
        elif val > cfg["hy_oas_stress"]:
            score -= 1.0
            details.append(f"HY OAS {val:.2f}% (blowing out)")
        else:
            details.append(f"HY OAS {val:.2f}% (normal)")
    else:
        details.append("HY OAS unavailable")

    curve = _safe_snapshot("T10Y2Y", force)
    if curve is not None:
        inverted = curve.latest < 0
        if inverted:
            score -= 0.5
            details.append(f"10Y-2Y {curve.latest:+.2f}pp → inverted (late-cycle flag)")
        else:
            details.append(f"10Y-2Y {curve.latest:+.2f}pp (positive slope)")

    if not have_input:
        return (Dimension("risk", "Risk Appetite", "Unknown", "muted", None,
                          details), inverted)
    if score >= cfg["score_risk_on"]:
        return (Dimension("risk", "Risk Appetite", "Risk-on", "up", score,
                          details), inverted)
    if score <= cfg["score_risk_off"]:
        return (Dimension("risk", "Risk Appetite", "Risk-off", "down", score,
                          details), inverted)
    return (Dimension("risk", "Risk Appetite", "Neutral", "neutral", score,
                      details), inverted)


# --------------------------------------------------------------------------
# Headline sentence
# --------------------------------------------------------------------------

_MONEY_WORD = {"Easing": "Easy money", "Neutral": "Neutral policy",
               "Tightening": "Tight money", "Unknown": "Policy unclear"}
_GROWTH_WORD = {"Expansion": "growth expanding", "Slowing": "growth slowing",
                "Contraction": "growth contracting", "Unknown": "growth unclear"}
_RISK_WORD = {"Risk-on": "risk-on", "Neutral": "risk appetite neutral",
              "Risk-off": "risk-off", "Unknown": "risk appetite unclear"}

_PLAYBOOK = {
    ("Easing", "Expansion"): "early-cycle tailwinds — cyclicals and small caps historically lead.",
    ("Easing", "Slowing"): "late-cycle easing — favor quality growth, add duration on pullbacks.",
    ("Easing", "Contraction"): "recessionary easing — defensives and duration first, re-risk later.",
    ("Neutral", "Expansion"): "mid-cycle — stay balanced, tilt toward earnings momentum.",
    ("Neutral", "Slowing"): "cautious mid/late cycle — quality and cash-flow resilience preferred.",
    ("Neutral", "Contraction"): "downturn without policy support yet — stay defensive.",
    ("Tightening", "Expansion"): "overheating watch — favor value and energy, keep duration short.",
    ("Tightening", "Slowing"): "classic late cycle — de-risk gradually, quality over beta.",
    ("Tightening", "Contraction"): "policy-induced downturn — capital preservation mode.",
}


def _headline(monetary: Dimension, growth: Dimension, risk: Dimension) -> str:
    parts = (f"{_MONEY_WORD[monetary.state]} · {_GROWTH_WORD[growth.state]} · "
             f"{_RISK_WORD[risk.state]}")
    playbook = _PLAYBOOK.get((monetary.state, growth.state),
                             "insufficient data for a playbook read.")
    tail = " Size down: credit/vol signalling stress." if risk.state == "Risk-off" else ""
    return f"{parts} → {playbook}{tail}"


def evaluate(force: bool = False) -> RegimeResult:
    th = load_thresholds()
    monetary = _monetary(th, force)
    growth = _growth(th, force)
    risk, inverted = _risk(th, force)
    return RegimeResult(monetary, growth, risk, inverted,
                        _headline(monetary, growth, risk))


# --------------------------------------------------------------------------
# Historical regime scores
#
# Re-applies the same rules month by month so the Regime Compass can chart how each
# dimension's composite score has evolved. Scores are oriented so that a
# *higher* line always means "more supportive" (easier money / stronger
# growth / more risk appetite); zero is neutral.
# --------------------------------------------------------------------------

def _snap_display(sid: str, force: bool) -> Optional[pd.Series]:
    snap = _safe_snapshot(sid, force)
    return snap.display if snap is not None else None


def _resample(series: Optional[pd.Series], index: pd.DatetimeIndex,
              how: str = "last") -> pd.Series:
    """Monthly `series` (last or mean per month), forward-filled onto `index`
    (NaN before the series starts)."""
    if series is None or len(series) == 0:
        return pd.Series(index=index, dtype="float64")
    monthly = getattr(series.resample("ME"), how)()
    return monthly.reindex(index, method="ffill")


def _bucket(series: pd.Series, lo: float, hi: float,
            lo_score: float, hi_score: float) -> pd.Series:
    """Threshold scorer: `lo_score` where below `lo`, `hi_score` where above
    `hi`, 0 otherwise. NaN (missing data) contributes 0."""
    out = pd.Series(0.0, index=series.index)
    out[series < lo] = lo_score
    out[series > hi] = hi_score
    return out


def _vix_monthly(index: pd.DatetimeIndex, force: bool) -> pd.Series:
    try:
        res = market.history(["^VIX"], period="max", force=force)
        if res.ok and "^VIX" in res.data.columns:
            return _resample(res.data["^VIX"].dropna(), index)
    except Exception:  # noqa: BLE001
        pass
    return pd.Series(index=index, dtype="float64")


def history(force: bool = False, years: int = 15) -> pd.DataFrame:
    """Monthly composite score per dimension over the last `years` years.

    Columns (all oriented so higher = more supportive):
      "Monetary easing" · "Growth" · "Risk appetite"
    """
    th = load_thresholds()
    index = pd.date_range(end=pd.Timestamp.today().normalize(),
                          periods=years * 12, freq="ME")

    # --- Monetary (raw score is negative when easing; flipped on output) -----
    m = th["monetary"]
    nfci = _resample(_snap_display("NFCI", force), index)
    dff = _resample(_snap_display("DFF", force), index)
    dgs2 = _resample(_snap_display("DGS2", force), index)
    mon = (_bucket(nfci, m["nfci_easing"], m["nfci_tightening"], -1.0, 1.0)
           + _bucket(dff - dff.shift(3), -m["dff_confirm_pp"],
                     m["dff_confirm_pp"], -0.5, 0.5)
           + _bucket(dgs2 - dgs2.shift(1), -m["dgs2_confirm_pp"],
                     m["dgs2_confirm_pp"], -0.25, 0.25))

    # --- Growth --------------------------------------------------------------
    g = th["growth"]
    ipman = _resample(_snap_display("IPMAN", force), index)
    gdpnow = _resample(_snap_display("GDPNOW", force), index)
    icsa = _resample(_snap_display("ICSA", force), index, "mean")
    payems = _resample(_snap_display("PAYEMS", force), index)

    c_ipman = pd.Series(0.0, index=index)
    c_ipman[ipman > 0] = 1.0
    c_ipman[ipman < 0] = -1.0
    icsa_chg = (icsa / icsa.shift(1) - 1) * 100
    pay_diff = payems.rolling(3).mean() - payems.shift(3).rolling(3).mean()
    grow = (c_ipman
            + _bucket(gdpnow, g["gdpnow_weak"], g["gdpnow_strong"], -1.0, 1.0)
            + _bucket(icsa_chg, -g["icsa_fall_pct"], g["icsa_rise_pct"], 0.5, -1.0)
            + _bucket(pay_diff, -g["payems_slowdown_k"],
                      g["payems_slowdown_k"], -0.5, 0.25))

    # --- Risk ----------------------------------------------------------------
    r = th["risk"]
    vix = _vix_monthly(index, force)
    hy = _resample(_snap_display("BAMLH0A0HYM2", force), index)
    curve = _resample(_snap_display("T10Y2Y", force), index)
    c_curve = pd.Series(0.0, index=index)
    c_curve[curve < 0] = -0.5
    risk = (_bucket(vix, r["vix_calm"], r["vix_stress"], 1.0, -1.0)
            + _bucket(hy, r["hy_oas_complacent"], r["hy_oas_stress"], 1.0, -1.0)
            + c_curve)

    frame = pd.DataFrame({
        "Monetary easing": -mon,
        "Growth": grow,
        "Risk appetite": risk,
    })
    # Drop the leading window where no dimension has any data yet.
    return frame.dropna(how="all")
