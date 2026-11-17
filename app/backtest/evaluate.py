"""Measure the pattern detectors: detection quality on synthetic charts, outcome on real history."""
import numpy as np
import pandas as pd

from ..analysis.indicators import atr as atr_series
from ..analysis.patterns import Ctx, detect_all
from ..analysis.pivots import confirmed_pivots, find_pivots, raw_pivots
from .synthetic import KINDS, make_negative, make_positive


def _ctx(d: dict, k: int) -> Ctx:
    df = pd.DataFrame(d)
    a = float(atr_series(df).iloc[-1])
    return Ctx(d["high"], d["low"], d["close"], d["volume"], find_pivots(d["high"], d["low"], k), k, a)


def synthetic_report(n_pos: int = 120, n_neg: int = 400, k: int = 5, seed: int = 7) -> dict:
    rng = np.random.default_rng(seed)
    out = {}
    neg_hits = {name: 0 for name in KINDS}
    for _ in range(n_neg):
        names = {p.name for p in detect_all(_ctx(make_negative(rng), k), lines=False)}
        for name in names:
            if name in neg_hits:
                neg_hits[name] += 1
    for kind in KINDS:
        hit = 0
        for _ in range(n_pos):
            names = {p.name for p in detect_all(_ctx(make_positive(kind, rng), k), lines=False)}
            hit += kind in names
        out[kind] = {"labelled_examples": n_pos, "hit_rate": round(hit / n_pos, 3),
                     "no_pattern_charts": n_neg, "false_positive_rate": round(neg_hits[kind] / n_neg, 3)}
    return out


def _outcome(high, low, close, t, direction, target, inval, horizon):
    """What happened first after bar t: target, invalidation, or neither within the horizon."""
    end = min(len(close) - 1, t + horizon)
    for i in range(t + 1, end + 1):
        if direction == "bullish":
            if low[i] <= inval:
                return "stopped", i
            if high[i] >= target:
                return "target", i
        else:
            if high[i] >= inval:
                return "stopped", i
            if low[i] <= target:
                return "target", i
    return "neither", end


def historical_report(frames: dict[str, pd.DataFrame], k: int, horizon: int, step: int = 3,
                      warmup: int = 250, seed: int = 11) -> dict:
    """Walk each stock forward. Record every newly confirmed pattern and what price did next.

    Baseline: random entry bars in the same stock, using the same target and stop distances in
    percent, so the comparison is 'this pattern' versus 'any day with the same bet shape'.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for sym, df in frames.items():
        if len(df) < warmup + horizon + 20:
            continue
        hi, lo, cl, vo = (df[c].values.astype(float) for c in ("high", "low", "close", "volume"))
        atr_all = atr_series(df).values
        raw = raw_pivots(hi, lo, k)
        seen = set()
        for t in range(warmup, len(df) - horizon, step):
            s0 = max(0, t + 1 - 400)
            piv = [type(p)(p.idx - s0, p.price, p.kind) for p in confirmed_pivots(raw, k, t) if p.idx >= s0]
            ctx = Ctx(hi[s0:t + 1], lo[s0:t + 1], cl[s0:t + 1], vo[s0:t + 1], piv, k, float(atr_all[t]))
            for p in detect_all(ctx, lines=False):
                if p.status != "confirmed" or p.direction not in ("bullish", "bearish"):
                    continue
                key = (p.name, tuple(q["idx"] + s0 for q in p.points))
                if key in seen:
                    continue
                seen.add(key)
                entry = cl[t]
                tp, sl = p.target / entry - 1, p.invalidation / entry - 1
                ok = (tp > 0.005 and sl < -0.005) if p.direction == "bullish" else (tp < -0.005 and sl > 0.005)
                if not ok:
                    continue  # price already beyond target or stop at detection
                res, _ = _outcome(hi, lo, cl, t, p.direction, p.target, p.invalidation, horizon)
                sign = 1 if p.direction == "bullish" else -1
                fwd = sign * (cl[min(len(cl) - 1, t + horizon)] / entry - 1)
                base = []
                for t2 in rng.integers(warmup, len(df) - horizon, 8):
                    e2 = cl[t2]
                    r2, _ = _outcome(hi, lo, cl, int(t2), p.direction, e2 * (1 + tp), e2 * (1 + sl), horizon)
                    base.append(r2 == "target")
                rows.append({"pattern": p.name, "direction": p.direction, "result": res, "fwd": fwd,
                             "baseline": float(np.mean(base)), "rr": abs(tp / sl)})
    out = {}
    if not rows:
        return out
    r = pd.DataFrame(rows)
    for name, g in r.groupby("pattern"):
        n = len(g)
        out[name] = {
            "signals": n,
            "reached_target_first": round(float((g.result == "target").mean()), 3),
            "hit_invalidation_first": round(float((g.result == "stopped").mean()), 3),
            "neither": round(float((g.result == "neither").mean()), 3),
            "baseline_target_first": round(float(g.baseline.mean()), 3),
            "avg_move_in_pattern_direction_pct": round(float(g.fwd.mean() * 100), 2),
            "median_reward_to_risk": round(float(g.rr.median()), 2),
            "horizon_bars": horizon,
            "small_sample": bool(n < 30),
        }
    return out
