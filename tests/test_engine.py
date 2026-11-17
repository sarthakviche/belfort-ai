import math

import numpy as np
import pytest

from app.analysis import explain, fundamentals, sizing, verdict
from app.analysis.indicators import atr, rsi, sma
from app.analysis.pivots import confirmed_pivots, find_pivots, raw_pivots
from app.backtest.evaluate import synthetic_report
from app.config import LABEL_AVOID, LABEL_NODATA, LABEL_VALID, LABEL_WATCH, STYLES
from tests.helpers import price_frame, statements

SWING = STYLES["swing"]


# ---------- position sizing (acceptance 5) ----------
def test_sizing_exact_example():
    s = sizing.position_size(200000, 1, 500, 480)
    assert s["quantity"] == 100 and s["risk_amount"] == 2000 and s["risk_budget"] == 2000


def test_sizing_never_exceeds_limit():
    rng = np.random.default_rng(0)
    for _ in range(3000):
        cap, risk = rng.uniform(5e3, 5e7), rng.uniform(0.1, 5)
        entry = rng.uniform(5, 50000)
        stop = entry * (1 - rng.uniform(0.002, 0.3))
        s = sizing.position_size(cap, risk, entry, stop)
        budget, per = cap * risk / 100, entry - stop
        assert s["quantity"] * per <= budget + 1e-6          # never over the limit
        assert s["quantity"] * entry <= cap + 1e-6           # never over capital
        if not s["capped_by_capital"]:
            assert (s["quantity"] + 1) * per > budget - 1e-6  # and one more share would break it


def test_sizing_rejects_bad_inputs():
    assert sizing.position_size(100000, 1, 100, 100)["error"]
    assert sizing.position_size(100000, 1, 100, 120)["error"]
    assert sizing.position_size(0, 1, 100, 90)["error"]
    assert sizing.position_size(1000, 1, 5000, 4000)["quantity"] == 0


def test_stop_is_below_price_and_within_limit():
    df = price_frame()
    a = float(atr(df).iloc[-1])
    close = float(df["close"].iloc[-1])
    s = sizing.suggest_stop(close, a, [{"price": close - a, "touches": 2}], SWING)
    assert s["stop"] < close and (close - s["stop"]) / close <= SWING.max_stop_pct


# ---------- indicators and pivots ----------
def test_indicators_basic():
    df = price_frame()
    r = rsi(df["close"])
    assert r.dropna().between(0, 100).all()
    assert math.isclose(sma(df["close"], 20).iloc[-1], df["close"].iloc[-20:].mean())
    assert (atr(df).iloc[20:] > 0).all()


def test_pivots_have_no_lookahead():
    df = price_frame(seed=3)
    hi, lo = df["high"].values, df["low"].values
    raw = raw_pivots(hi, lo, 5)
    for t in (150, 250, 399):
        known = confirmed_pivots(raw, 5, t)
        assert all(p.idx + 5 <= t for p in known)
        # the same pivots come out when the future bars are cut off entirely
        cut = find_pivots(hi[:t + 1], lo[:t + 1], 5)
        assert [(p.idx, p.kind) for p in cut] == [(p.idx, p.kind) for p in known]


# ---------- pattern detectors (acceptance 2) ----------
def test_detectors_find_textbook_shapes_and_rarely_fire_on_noise():
    rep = synthetic_report(n_pos=40, n_neg=150, seed=3)
    for name, r in rep.items():
        assert r["hit_rate"] >= 0.7, (name, r)
        assert r["false_positive_rate"] <= 0.2, (name, r)


# ---------- concerns list (acceptance 3, synthetic archetypes only) ----------
def _titles(f, sev=None):
    return [c["title"] for c in f["concerns"] if sev is None or c["severity"] == sev]


def test_healthy_company_is_not_flagged():
    f = fundamentals.analyse(statements(), is_lender=False)
    assert f["available"] and f["verdict"] == "constructive"
    assert not _titles(f, "high") and not _titles(f, "medium")
    assert any(c["severity"] == "info" and "pledge" in c["title"].lower() for c in f["concerns"])


@pytest.mark.parametrize("kwargs,expect", [
    (dict(debt=(500, 900, 1600, 2600), eq=(1000, 1050, 1100, 1150), interest=(40, 80, 150, 260)), "Debt is high and rising"),
    (dict(interest=(40, 80, 150, 260)), "Profit barely covers interest"),
    (dict(recv=(200, 260, 420, 700)), "Money owed by customers is growing faster than sales"),
    (dict(cfo=(100, 60, 10, -50)), "Profit is not turning into cash"),
    (dict(ni=(120, 60, -40, -150)), "The company made a net loss"),
])
def test_serious_red_flags_are_caught(kwargs, expect):
    f = fundamentals.analyse(statements(**kwargs), is_lender=False)
    assert expect in _titles(f, "high"), _titles(f)
    assert f["verdict"] == "cautious"
    assert f["concerns"][0]["severity"] == "high"  # ranked most serious first


def test_moderate_flags():
    f = fundamentals.analyse(statements(unusual=(0, 0, 0, 120)), is_lender=False)
    assert "One-time gains lifted profit" in _titles(f, "medium")
    s = statements()
    s["income"].loc["Operating Income"] = np.array([220, 200, 180, 150]) * 1e7
    f = fundamentals.analyse(s, False)
    assert "Operating margin has fallen two years running" in _titles(f, "medium")


def test_every_concern_has_figure_period_and_source():
    f = fundamentals.analyse(statements(debt=(500, 900, 1600, 2600), eq=(1000, 1050, 1100, 1150), recv=(200, 260, 420, 700)), False)
    for c in f["concerns"]:
        assert c["detail"] and c["source"]
        if c["severity"] != "info":
            assert c["period"] and any(ch.isdigit() for ch in c["detail"])


def test_lenders_skip_debt_checks_and_say_so():
    f = fundamentals.analyse(statements(debt=(5000, 6000, 7000, 9000)), is_lender=True)
    assert not any("Debt" in t for t in _titles(f))
    assert f["notes"]


def test_missing_statements_are_reported_not_invented():
    f = fundamentals.analyse({"income": None, "balance": None, "cashflow": None, "info": {}}, False)
    assert f["available"] is False and f["missing_reason"]


# ---------- the label ----------
def _inputs(direction="up", close=100.0):
    trend = {"direction": direction, "structure": direction if direction != "sideways" else "mixed",
             "ma_alignment": "up" if direction == "up" else "mixed", "close": close, "fast": 99.0, "slow": 95.0}
    levels = {"supports": [{"price": 98.0, "touches": 3}], "resistances": [{"price": 112.0, "touches": 2}]}
    vol = {"breakout": None}
    return trend, levels, vol


CLEAN = {"available": True, "verdict": "constructive", "concerns": []}


def test_label_valid_when_everything_is_met():
    t, l, v = _inputs()
    out = verdict.decide(SWING, 300, t, l, v, 2.0, 100.0, 96.0, CLEAN, None)
    assert out["label"] == LABEL_VALID and not out["unmet"]


def test_label_avoid_in_downtrend_or_with_serious_concern():
    t, l, v = _inputs("down")
    assert verdict.decide(SWING, 300, t, l, v, 2.0, 100.0, 96.0, CLEAN, None)["label"] == LABEL_AVOID
    t, l, v = _inputs("up")
    bad = {"available": True, "verdict": "cautious", "concerns": [{"severity": "high", "title": "Debt is high and rising", "detail": "x"}]}
    out = verdict.decide(SWING, 300, t, l, v, 2.0, 100.0, 96.0, bad, None)
    assert out["label"] == LABEL_AVOID and "Debt" in out["main_risk"]


def test_label_watch_cases():
    t, l, v = _inputs("sideways")
    assert verdict.decide(SWING, 300, t, l, v, 2.0, 100.0, 96.0, CLEAN, None)["label"] == LABEL_WATCH
    t, l, v = _inputs("up")
    # fundamentals missing: capped at Watch
    assert verdict.decide(SWING, 300, t, l, v, 2.0, 100.0, 96.0, {"available": False, "concerns": []}, None)["label"] == LABEL_WATCH
    # results due inside a swing holding window
    assert verdict.decide(SWING, 300, t, l, v, 2.0, 100.0, 96.0, CLEAN, 2)["label"] == LABEL_WATCH
    # resistance too close for the stop distance
    l["resistances"] = [{"price": 102.0, "touches": 2}]
    assert verdict.decide(SWING, 300, t, l, v, 2.0, 100.0, 96.0, CLEAN, None)["label"] == LABEL_WATCH


def test_label_insufficient_data():
    t, l, v = _inputs()
    assert verdict.decide(SWING, 60, t, l, v, 2.0, 100.0, 96.0, CLEAN, None)["label"] == LABEL_NODATA


def test_agreement_states():
    assert verdict.agreement("up", {"available": True, "verdict": "constructive"}, SWING)["state"] == "agree"
    assert verdict.agreement("up", {"available": True, "verdict": "cautious"}, SWING)["state"] == "conflict"
    assert verdict.agreement("down", {"available": True, "verdict": "constructive"}, SWING)["state"] == "conflict"
    assert verdict.agreement("up", {"available": False}, SWING)["state"] == "unknown"


def test_banned_phrase_finder():
    assert explain.find_banned("This is a sure shot, buy now!") == ["sure shot", "buy now"]
    assert explain.find_banned("The trend is up and volume agrees.") == []


def test_sharp_recovery_is_read_as_a_new_uptrend_not_as_down():
    """A fall followed by a fast rally past the last swing high must not be called 'no trend' (HDFC Bank, Nov 2026)."""
    import pandas as pd
    from app.analysis.structure import trend_state
    path = np.r_[np.linspace(100, 80, 150), np.linspace(80, 84, 12), np.linspace(84, 78, 12), np.linspace(78, 95, 12)]
    rng = np.random.default_rng(5)
    close = path * (1 + rng.normal(0, 0.002, len(path)))
    df = pd.DataFrame({"open": close, "high": close * 1.004, "low": close * 0.996, "close": close, "volume": 1e6},
                      index=pd.bdate_range(end="2026-11-13", periods=len(path)))
    t = trend_state(df, find_pivots(df["high"].values, df["low"].values, 5), SWING)
    assert t["direction"] == "up" and t["phase"] == "early" and t["broke_above_last_high"]
    assert "turned up" in explain.trend_sentence(t)
