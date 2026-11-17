"""Synthetic charts with a known pattern (or none) for measuring detector quality.

These are textbook shapes with noise. They tell us whether the code finds the shape it claims to
find and how often it sees shapes in random data. They say nothing about whether a pattern predicts
price; that is measured on real history in evaluate.py.
"""
import numpy as np

KINDS = ["Double top", "Double bottom (W)", "Head and shoulders", "Inverse head and shoulders",
         "Ascending triangle", "Descending triangle", "Symmetrical triangle", "Cup and handle"]


def _mirror(wp):
    return [(x, 200 - y) for x, y in wp]


def _waypoints(kind: str, rng) -> list[tuple[float, float]]:
    j = lambda lo, hi: rng.uniform(lo, hi)  # noqa: E731
    if kind in ("Double top", "Double bottom (W)"):
        d = j(7, 11)
        wp = [(0, 70), (60, 100), (80, 100 - d), (100, 100 + j(-1.2, 1.2)), (118, 100 - 1.5 * d)]
    elif kind in ("Head and shoulders", "Inverse head and shoulders"):
        nk = 92 + j(-1, 1)
        wp = [(0, 70), (40, 100), (55, nk), (75, 108 + j(0, 4)), (95, nk + j(-1, 1)), (110, 100 + j(-1.5, 1.5)), (130, 82)]
    elif kind in ("Ascending triangle", "Descending triangle"):
        wp = [(0, 70), (30, 100), (45, 87), (60, 100), (73, 91.5), (86, 100), (95, 95), (108, 108)]
    elif kind == "Symmetrical triangle":
        wp = [(0, 70), (30, 100), (45, 82), (60, 96.5), (73, 85.5), (86, 93), (95, 89), (108, 101)]
    else:  # cup and handle
        depth = j(18, 28)
        cup = [(30 + t, 100 - depth * np.sin(np.pi * (t / 80)) ** 0.7) for t in range(4, 80, 4)]
        wp = [(0, 78), (30, 100)] + cup + [(110, 100 + j(-1, 1)), (120, 95), (128, 106)]
    if kind in ("Double bottom (W)", "Inverse head and shoulders", "Descending triangle"):
        wp = _mirror(wp)
    stretch = j(0.9, 1.25)
    return [(x * stretch, y) for x, y in wp]


def _ohlcv(path: np.ndarray, rng, noise: float):
    n = len(path)
    e = np.zeros(n)
    for i in range(1, n):
        e[i] = 0.5 * e[i - 1] + rng.normal(0, noise)
    close = path * np.exp(e)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, noise * 0.7, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, noise * 0.7, n)))
    vol = rng.lognormal(13, 0.35, n)
    return {"open": open_, "high": high, "low": low, "close": close, "volume": vol}


def make_positive(kind: str, rng, noise: float = 0.004) -> dict:
    wp = _waypoints(kind, rng)
    lead = int(rng.integers(40, 80))
    xs = np.array([x for x, _ in wp]) + lead
    ys = np.array([y for _, y in wp])
    n = int(xs[-1]) + 1
    first = ys[0]
    lead_path = first * (1 + np.linspace(rng.uniform(-0.03, 0.03), 0, lead))
    body = np.interp(np.arange(lead, n), xs, ys)
    return _ohlcv(np.r_[lead_path, body], rng, noise)


def make_negative(rng, noise: float = 0.006) -> dict:
    """A drifting random walk with no deliberate shape."""
    n = int(rng.integers(180, 260))
    drift = rng.choice([-0.0012, 0.0, 0.0012])
    steps = rng.normal(drift, 0.011, n)
    path = 100 * np.exp(np.cumsum(steps))
    return _ohlcv(path, rng, noise)
