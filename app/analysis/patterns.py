"""Chart pattern detectors. Everything is computed from OHLCV and confirmed pivots.

Each detector returns Pattern objects with a 0..1 score, the exact bars used, a measured-move
target and an invalidation price. Mirror patterns (tops/bottoms) share one implementation by
flipping the sign of prices.
"""
from dataclasses import asdict, dataclass, field

import numpy as np

from .pivots import Pivot


@dataclass
class Ctx:
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    vol: np.ndarray
    piv: list[Pivot]
    k: int
    atr: float

    @property
    def n(self) -> int:
        return len(self.close)


@dataclass
class Pattern:
    name: str
    direction: str            # bullish / bearish / neutral
    status: str               # forming / confirmed / holding / broken
    score: float
    points: list[dict] = field(default_factory=list)   # {idx, price, role}
    key_level: float | None = None
    target: float | None = None
    invalidation: float | None = None
    confirm_idx: int | None = None
    note: str = ""

    @property
    def key(self):
        return (self.name, tuple(p["idx"] for p in self.points))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["score"] = round(float(self.score), 2)
        for f in ("key_level", "target", "invalidation"):
            if d[f] is not None:
                d[f] = round(float(d[f]), 2)
        return d


def _view(c: Ctx, s: int):
    """Arrays and pivots in a space where the pattern is always a 'top'."""
    if s > 0:
        return c.high, c.low, c.close, [(p.idx, p.price, p.kind == "H") for p in c.piv]
    return -c.low, -c.high, -c.close, [(p.idx, -p.price, p.kind == "L") for p in c.piv]


def _pt(idx, price, role):
    return {"idx": int(idx), "price": round(float(price), 2), "role": role}


def _clip(x):
    return float(max(0.0, min(1.0, x)))


def double_patterns(c: Ctx, s: int) -> list[Pattern]:
    HI, LO, CL, P = _view(c, s)
    n, k = c.n, c.k
    min_sep, max_sep, max_age = max(8, 2 * k), 16 * k, 6 * k
    out = []
    for j in range(len(P) - 2):
        (i1, h1, t1), (im, lm, _), (i2, h2, t2) = P[j], P[j + 1], P[j + 2]
        if not (t1 and t2) or n - 1 - i2 > max_sep:
            continue
        sep = i2 - i1
        if not (min_sep <= sep <= max_sep):
            continue
        top = max(h1, h2)
        base = abs(top)
        diff = abs(h1 - h2) / base
        height = min(h1, h2) - lm
        if diff > 0.03 or height / base < 0.04 or height < 1.5 * c.atr:
            continue
        lo0 = max(0, i1 - sep)
        if i1 - lo0 < 5 or LO[lo0:i1].min() > lm - 0.25 * height:
            continue  # no real move into the first peak
        if i2 + 1 < n and HI[i2 + 1:].max() > top + 0.01 * base:
            continue  # price already went past both peaks
        brk = np.nonzero(CL[i2 + 1:] < lm)[0]
        confirm = int(i2 + 1 + brk[0]) if len(brk) else None
        if confirm is not None and n - 1 - confirm > max_age:
            continue
        if confirm is None and n - 1 - i2 > 2 * max_age:
            continue
        target = lm - height
        if confirm is not None and LO[confirm:].min() <= target:
            continue  # measured move already done
        v1, v2 = c.vol[max(0, i1 - 2):i1 + 3].mean(), c.vol[max(0, i2 - 2):i2 + 3].mean()
        score = (0.4 * (1 - diff / 0.03) + 0.3 * _clip(height / base / 0.10)
                 + 0.15 * (v2 < v1) + 0.15 * (confirm is not None))
        top_side = s > 0
        out.append(Pattern(
            name="Double top" if top_side else "Double bottom (W)",
            direction="bearish" if top_side else "bullish",
            status="confirmed" if confirm is not None else "forming", score=_clip(score),
            points=[_pt(i1, s * h1, "first peak" if top_side else "first low"),
                    _pt(im, s * lm, "neckline"),
                    _pt(i2, s * h2, "second peak" if top_side else "second low")],
            key_level=s * lm, target=s * target, invalidation=s * top, confirm_idx=confirm,
            note=("Second peak on lower volume. " if v2 < v1 and top_side else "")
                 + f"Peaks differ by {diff * 100:.1f}%.",
        ))
    return out


def head_shoulders(c: Ctx, s: int) -> list[Pattern]:
    HI, LO, CL, P = _view(c, s)
    n, k = c.n, c.k
    max_age = 6 * k
    out = []
    for j in range(len(P) - 4):
        (i1, ls, a), (ib, t1, _), (ih, hd, d), (ie, t2, _), (i3, rs, f) = P[j:j + 5]
        if not (a and d and f) or n - 1 - i3 > 16 * k or i3 - i1 > 24 * k:
            continue
        base = abs(hd)
        if hd - ls < 0.02 * base or hd - rs < 0.02 * base:
            continue
        sh_diff = abs(ls - rs) / base
        if sh_diff > 0.05:
            continue
        l_span, r_span = ih - i1, i3 - ih
        if not (1 / 3 <= l_span / r_span <= 3):
            continue
        slope = (t2 - t1) / (ie - ib)

        def nl(x, t1=t1, ib=ib, slope=slope):
            return t1 + slope * (x - ib)

        height = hd - nl(ih)
        if height < 0.04 * base or height < 2 * c.atr or abs(t2 - t1) > 0.5 * height:
            continue
        if ls - nl(i1) < 0.25 * height or rs - nl(i3) < 0.25 * height:
            continue
        lo0 = max(0, i1 - (i3 - i1))
        if i1 - lo0 < 5 or LO[lo0:i1].min() > min(t1, t2):
            continue
        if i3 + 1 < n and HI[i3 + 1:].max() > hd:
            continue
        xs = np.arange(i3 + 1, n)
        brk = np.nonzero(CL[i3 + 1:] < nl(xs))[0]
        confirm = int(i3 + 1 + brk[0]) if len(brk) else None
        if confirm is not None and n - 1 - confirm > max_age:
            continue
        if confirm is None and n - 1 - i3 > 2 * max_age:
            continue
        ref = confirm if confirm is not None else n - 1
        target = nl(ref) - height
        if confirm is not None and LO[confirm:].min() <= target:
            continue
        score = (0.35 * (1 - sh_diff / 0.05) + 0.25 * _clip((hd - max(ls, rs)) / base / 0.06)
                 + 0.2 * (1 - abs(t2 - t1) / (0.5 * height)) + 0.2 * (confirm is not None))
        top_side = s > 0
        out.append(Pattern(
            name="Head and shoulders" if top_side else "Inverse head and shoulders",
            direction="bearish" if top_side else "bullish",
            status="confirmed" if confirm is not None else "forming", score=_clip(score),
            points=[_pt(i1, s * ls, "left shoulder"), _pt(ib, s * t1, "neckline"), _pt(ih, s * hd, "head"),
                    _pt(ie, s * t2, "neckline"), _pt(i3, s * rs, "right shoulder")],
            key_level=s * nl(ref), target=s * target, invalidation=s * rs, confirm_idx=confirm,
            note=f"Shoulders differ by {sh_diff * 100:.1f}% of the head price.",
        ))
    return out


def triangles(c: Ctx) -> list[Pattern]:
    n, k, atr = c.n, c.k, c.atr
    highs = [p for p in c.piv if p.kind == "H"][-3:]
    lows = [p for p in c.piv if p.kind == "L"][-3:]
    if len(highs) < 2 or len(lows) < 2 or len(highs) + len(lows) < 5:
        return []
    start, end = min(highs[0].idx, lows[0].idx), max(highs[-1].idx, lows[-1].idx)
    span = end - start
    if span < 4 * k or span > 30 * k or n - 1 - end > 6 * k:
        return []
    fh = np.polyfit([p.idx for p in highs], [p.price for p in highs], 1)
    fl = np.polyfit([p.idx for p in lows], [p.price for p in lows], 1)

    def up(x):
        return fh[0] * x + fh[1]

    def lo(x):
        return fl[0] * x + fl[1]

    res = max(max(abs(p.price - up(p.idx)) for p in highs), max(abs(p.price - lo(p.idx)) for p in lows))
    if res > 0.6 * atr:
        return []
    price = c.close[-1]
    d_h, d_l = fh[0] * span / price, fl[0] * span / price
    gap0, gap1 = up(start) - lo(start), up(end) - lo(end)
    if gap0 < 3 * atr or gap1 <= 0 or gap1 > 0.7 * gap0:
        return []
    if abs(d_h) < 0.02 and d_l > 0.03:
        name, bias = "Ascending triangle", "bullish"
    elif abs(d_l) < 0.02 and d_h < -0.03:
        name, bias = "Descending triangle", "bearish"
    elif d_h < -0.02 and d_l > 0.02:
        name, bias = "Symmetrical triangle", "neutral"
    else:
        return []
    xs = np.arange(start, end + 1)
    cl = c.close[start:end + 1]
    if ((cl > up(xs) + 0.75 * atr) | (cl < lo(xs) - 0.75 * atr)).mean() > 0.05:
        return []
    confirm, direction, status = None, bias, "forming"
    for i in range(end + 1, n):
        if up(i) <= lo(i):
            return []  # ran past the apex without a break
        if c.close[i] > up(i):
            confirm, direction = i, "bullish"
            break
        if c.close[i] < lo(i):
            confirm, direction = i, "bearish"
            break
    if confirm is not None:
        status = "confirmed"
        target = up(confirm) + gap0 if direction == "bullish" else lo(confirm) - gap0
        inval = lo(confirm) if direction == "bullish" else up(confirm)
        key = up(confirm) if direction == "bullish" else lo(confirm)
        done = (c.high[confirm:].max() >= target) if direction == "bullish" else (c.low[confirm:].min() <= target)
        if done:
            return []
    else:
        last = n - 1
        key = up(last) if bias != "bearish" else lo(last)
        target = up(last) + gap0 if bias != "bearish" else lo(last) - gap0
        inval = lo(last) if bias != "bearish" else up(last)
    score = (0.3 * (len(highs) == 3 and len(lows) == 3) + 0.3 * (1 - res / (0.6 * atr))
             + 0.2 * (1 - gap1 / gap0) + 0.2 * (confirm is not None))
    pts = sorted([_pt(p.idx, p.price, "upper line") for p in highs]
                 + [_pt(p.idx, p.price, "lower line") for p in lows], key=lambda p: p["idx"])
    return [Pattern(name=name, direction=direction, status=status, score=_clip(score), points=pts,
                    key_level=key, target=target, invalidation=inval, confirm_idx=confirm,
                    note=f"Upper line now ₹{up(n - 1):.2f}, lower line ₹{lo(n - 1):.2f}.")]


def cup_handle(c: Ctx) -> list[Pattern]:
    n, k = c.n, c.k
    highs = [p for p in c.piv if p.kind == "H"]
    for ci in range(len(highs) - 1, 0, -1):
        C = highs[ci]
        handle_len = n - 1 - C.idx
        if handle_len > 8 * k:
            break
        for ai in range(ci - 1, -1, -1):
            A = highs[ai]
            length = C.idx - A.idx
            if length < 6 * k:
                continue
            if length > 30 * k:
                break
            if abs(C.price - A.price) / A.price > 0.06:
                continue
            seg = c.low[A.idx:C.idx + 1]
            b = A.idx + int(seg.argmin())
            B = float(seg.min())
            depth = (A.price - B) / A.price
            if not (0.12 <= depth <= 0.40):
                continue
            if c.high[A.idx + 1:C.idx].max() > max(A.price, C.price) * 1.01:
                continue
            pos = (b - A.idx) / length
            if not (0.25 <= pos <= 0.75):
                continue
            cl = c.close[A.idx:C.idx + 1]
            low_zone = float((cl < B + 0.4 * (A.price - B)).mean())
            if low_zone < 0.30:
                continue  # V-shaped, not a rounded base
            brk = np.nonzero(c.close[C.idx + 1:] > C.price)[0]
            confirm = int(C.idx + 1 + brk[0]) if len(brk) else None
            h_end = confirm if confirm is not None else n - 1
            h_low = float(c.low[C.idx + 1:h_end + 1].min()) if h_end > C.idx else C.price
            h_idx = C.idx + 1 + int(c.low[C.idx + 1:h_end + 1].argmin()) if h_end > C.idx else C.idx
            h_depth = (C.price - h_low) / (C.price - B)
            if h_depth > 0.5:
                continue
            if confirm is not None and n - 1 - confirm > 6 * k:
                continue
            target = C.price + (C.price - B)
            if confirm is not None and c.high[confirm:].max() >= target:
                continue
            score = (0.3 * (1 - abs(C.price - A.price) / A.price / 0.06) + 0.25 * _clip(low_zone / 0.5)
                     + 0.25 * (1 - h_depth / 0.5) + 0.2 * (confirm is not None))
            return [Pattern(
                name="Cup and handle", direction="bullish",
                status="confirmed" if confirm is not None else "forming", score=_clip(score),
                points=[_pt(A.idx, A.price, "left rim"), _pt(b, B, "cup low"),
                        _pt(C.idx, C.price, "right rim"), _pt(h_idx, h_low, "handle low")],
                key_level=C.price, target=target, invalidation=h_low, confirm_idx=confirm,
                note=f"Cup depth {depth * 100:.0f}% over {length} bars; handle retraced {h_depth * 100:.0f}% of the cup.",
            )]
    return []


def trend_lines(c: Ctx) -> list[Pattern]:
    out = []
    n, atr = c.n, c.atr
    for kind, name, direction in (("L", "Rising trend line", "bullish"), ("H", "Falling trend line", "bearish")):
        pts = [p for p in c.piv if p.kind == kind][-3:]
        if len(pts) < 3:
            continue
        prices = [p.price for p in pts]
        rising = prices[0] < prices[1] < prices[2]
        falling = prices[0] > prices[1] > prices[2]
        if (kind == "L" and not rising) or (kind == "H" and not falling):
            continue
        f = np.polyfit([p.idx for p in pts], prices, 1)
        res = max(abs(p.price - (f[0] * p.idx + f[1])) for p in pts)
        if res > 0.75 * atr:
            continue
        now = f[0] * (n - 1) + f[1]
        if now <= 0:
            continue
        if kind == "L":
            status = "holding" if c.close[-1] >= now - 0.5 * atr else "broken"
        else:
            status = "holding" if c.close[-1] <= now + 0.5 * atr else "broken"
        out.append(Pattern(
            name=name, direction=direction, status=status, score=_clip(0.6 + 0.4 * (1 - res / (0.75 * atr))),
            points=[_pt(p.idx, p.price, "touch") for p in pts], key_level=now, invalidation=now,
            note=f"Line through three swing {'lows' if kind == 'L' else 'highs'}; value today ₹{now:.2f}.",
        ))
    return out


def detect_all(c: Ctx, lines: bool = True) -> list[Pattern]:
    found: list[Pattern] = []
    if len(c.piv) >= 3 and c.atr > 0:
        for s in (1, -1):
            found += double_patterns(c, s)
            found += head_shoulders(c, s)
        found += triangles(c)
        found += cup_handle(c)
        if lines:
            found += trend_lines(c)
    best: dict[str, Pattern] = {}
    for p in found:  # one instance per pattern type: the most recent, then the best score
        cur = best.get(p.name)
        if cur is None or (p.points[-1]["idx"], p.score) > (cur.points[-1]["idx"], cur.score):
            best[p.name] = p
    return sorted(best.values(), key=lambda p: -p.score)
