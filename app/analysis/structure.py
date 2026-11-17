"""Trend, support/resistance, Fibonacci and volume reads."""
import numpy as np
import pandas as pd

from ..config import BREAKOUT_VOLUME, Style
from .indicators import sma
from .pivots import Pivot


def trend_state(df: pd.DataFrame, pivots: list[Pivot], st: Style) -> dict:
    close = float(df["close"].iloc[-1])
    fast_s, slow_s = sma(df["close"], st.fast), sma(df["close"], st.slow)
    fast = float(fast_s.iloc[-1]) if len(df) >= st.fast else None
    slow = float(slow_s.iloc[-1]) if len(df) >= st.slow else None
    highs = [p for p in pivots if p.kind == "H"][-2:]
    lows = [p for p in pivots if p.kind == "L"][-2:]
    structure = "unclear"
    if len(highs) == 2 and len(lows) == 2:
        hh, hl = highs[1].price > highs[0].price, lows[1].price > lows[0].price
        structure = "up" if hh and hl else "down" if (not hh and not hl) else "mixed"
    align = "mixed"
    if fast and slow:
        if close > fast > slow:
            align = "up"
        elif close < fast < slow:
            align = "down"
    # Confirmed swing points lag by k bars, so a sharp turn shows up first as a close beyond the
    # last swing high or low ("break of structure"). Without this a V-shaped recovery reads as down.
    all_h = [p for p in pivots if p.kind == "H"]
    all_l = [p for p in pivots if p.kind == "L"]
    last_h = all_h[-1].price if all_h else None
    last_l = all_l[-1].price if all_l else None
    broke_up = last_h is not None and close > last_h
    broke_down = last_l is not None and close < last_l
    direction, phase = "sideways", None
    if slow:
        if close > slow and not broke_down and (structure == "up" or align == "up" or (broke_up and fast and close > fast)):
            direction = "up"
            phase = "established" if structure == "up" and align == "up" else "early"
        elif close < slow and not broke_up and (structure == "down" or align == "down" or (broke_down and fast and close < fast)):
            direction = "down"
            phase = "established" if structure == "down" and align == "down" else "early"
    nb = max(5, st.fast // 2)
    recent = None
    if len(df) > nb:
        recent = {"bars": nb, "pct": round((close / float(df["close"].iloc[-1 - nb]) - 1) * 100, 1)}
    slow_rising = None
    if slow and len(df) >= st.slow + 10:
        slow_rising = bool(slow > float(slow_s.iloc[-11]))
    return {
        "direction": direction, "phase": phase, "structure": structure, "ma_alignment": align,
        "broke_above_last_high": bool(broke_up), "broke_below_last_low": bool(broke_down),
        "last_swing_high": last_h, "last_swing_low": last_l, "recent": recent,
        "close": close, "fast": fast, "slow": slow, "fast_n": st.fast, "slow_n": st.slow,
        "slow_rising": slow_rising,
        "swing_highs": [{"idx": p.idx, "price": p.price} for p in highs],
        "swing_lows": [{"idx": p.idx, "price": p.price} for p in lows],
    }


def find_levels(pivots: list[Pivot], close: float, atr: float, n_bars: int, lookback: int = 260) -> dict:
    """Cluster pivot prices that sit within 0.75 ATR of each other."""
    recent = sorted([p for p in pivots if p.idx >= n_bars - lookback], key=lambda p: p.price)
    tol = 0.75 * atr
    clusters: list[list[Pivot]] = []
    for p in recent:
        if clusters and p.price - np.mean([q.price for q in clusters[-1]]) <= tol:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    levels = []
    for c in clusters:
        price = float(np.mean([p.price for p in c]))
        levels.append({
            "price": round(price, 2), "touches": len(c), "last_touch_idx": max(p.idx for p in c),
            "bars": [p.idx for p in c], "distance_pct": round((price - close) / close * 100, 2),
        })
    sup = sorted([l for l in levels if l["price"] < close], key=lambda l: -l["price"])
    res = sorted([l for l in levels if l["price"] >= close], key=lambda l: l["price"])
    return {"supports": sup[:5], "resistances": res[:5]}


FIB_RATIOS = [0.236, 0.382, 0.5, 0.618, 0.786]


def fibonacci(df: pd.DataFrame, lookback: int) -> dict | None:
    w = df.iloc[-lookback:]
    if len(w) < 20:
        return None
    hi_i, lo_i = int(np.argmax(w["high"].values)), int(np.argmin(w["low"].values))
    hi, lo = float(w["high"].iloc[hi_i]), float(w["low"].iloc[lo_i])
    if hi <= lo or hi_i == lo_i:
        return None
    up = lo_i < hi_i  # low came first: an up-swing, so retracements sit below the high
    off = len(df) - len(w)
    levels = [{"ratio": r, "price": round(hi - r * (hi - lo) if up else lo + r * (hi - lo), 2)} for r in FIB_RATIOS]
    return {"direction": "up" if up else "down", "high": hi, "low": lo,
            "high_idx": off + hi_i, "low_idx": off + lo_i, "levels": levels}


def volume_read(df: pd.DataFrame, st: Style) -> dict:
    v, c, h = df["volume"], df["close"], df["high"]
    avg20 = float(v.iloc[-21:-1].mean()) if len(df) > 21 else None
    rel = float(v.iloc[-1] / avg20) if avg20 else None
    chg = c.diff().iloc[-20:]
    vv = v.iloc[-20:]
    up_v, dn_v = float(vv[chg > 0].mean() or 0), float(vv[chg < 0].mean() or 0)
    breakout = None
    n = st.breakout_n
    if len(df) > n + 5 and avg20:
        prior_high = h.shift(1).rolling(n).max()
        for back in range(0, 3):  # breakout today or in the last two bars
            i = len(df) - 1 - back
            if c.iloc[i] > prior_high.iloc[i] and c.iloc[i - 1] <= prior_high.iloc[i - 1]:
                base = float(v.iloc[i - 20:i].mean())
                rv = float(v.iloc[i] / base) if base else None
                breakout = {"bars_ago": back, "idx": i, "level": round(float(prior_high.iloc[i]), 2),
                            "rel_volume": round(rv, 2) if rv else None,
                            "confirmed": bool(rv and rv >= BREAKOUT_VOLUME),
                            "still_above": bool(c.iloc[-1] > prior_high.iloc[i])}
                break
    return {
        "last_volume": float(v.iloc[-1]), "avg20": avg20, "rel_volume": round(rel, 2) if rel else None,
        "up_day_avg": up_v, "down_day_avg": dn_v,
        "up_down_ratio": round(up_v / dn_v, 2) if dn_v else None,
        "breakout": breakout, "breakout_n": n,
    }
