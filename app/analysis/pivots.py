"""Swing highs and lows. A pivot at bar i is only usable from bar i + k (no look-ahead)."""
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Pivot:
    idx: int
    price: float
    kind: str  # "H" or "L"


def raw_pivots(high: np.ndarray, low: np.ndarray, k: int) -> list[Pivot]:
    out = []
    n = len(high)
    for i in range(k, n - k):
        wh = high[i - k:i + k + 1]
        if high[i] == wh.max() and (wh[:k] < high[i]).all():
            out.append(Pivot(i, float(high[i]), "H"))
        wl = low[i - k:i + k + 1]
        if low[i] == wl.min() and (wl[:k] > low[i]).all():
            out.append(Pivot(i, float(low[i]), "L"))
    return out


def alternate(pivots: list[Pivot]) -> list[Pivot]:
    """Force high/low alternation, keeping the more extreme of consecutive same-kind pivots."""
    out: list[Pivot] = []
    for p in pivots:
        if out and out[-1].kind == p.kind:
            last = out[-1]
            if (p.kind == "H" and p.price >= last.price) or (p.kind == "L" and p.price <= last.price):
                out[-1] = p
        else:
            out.append(p)
    return out


def confirmed_pivots(raw: list[Pivot], k: int, t: int) -> list[Pivot]:
    """Pivots knowable at bar t (inclusive)."""
    return alternate([p for p in raw if p.idx + k <= t])


def find_pivots(high: np.ndarray, low: np.ndarray, k: int) -> list[Pivot]:
    return alternate(raw_pivots(high, low, k))
