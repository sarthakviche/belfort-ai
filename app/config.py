"""Style presets, thresholds and wording rules."""
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    """Read KEY=VALUE lines from a .env file in the project folder (existing variables win)."""
    import os
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
STATS_FILE = DATA_DIR / "pattern_stats.json"


@dataclass(frozen=True)
class Style:
    key: str
    name: str
    holds: str
    k: int                 # bars each side of a pivot
    fast: int              # fast moving average
    slow: int              # slow moving average
    min_bars: int
    atr_stop: float        # fallback stop in ATRs
    max_stop_pct: float    # widest acceptable stop distance
    breakout_n: int        # bars for a breakout high
    fib_lookback: int
    earnings_blackout: int  # trading days; 0 = flag only
    horizon: int           # bars used when judging patterns in the backtest


STYLES = {
    "swing": Style("swing", "Swing", "2 to 15 days", 5, 20, 50, 120, 1.5, 0.08, 20, 90, 5, 30),
    "positional": Style("positional", "Positional", "weeks to months", 10, 50, 200, 250, 3.0, 0.15, 55, 250, 0, 60),
}

MIN_REWARD_TO_RISK = 1.5
BREAKOUT_VOLUME = 1.5      # times the 20-day average
TICK = 0.05

LABEL_VALID = "Setup valid"
LABEL_WATCH = "Watch"
LABEL_AVOID = "Avoid"
LABEL_NODATA = "Insufficient data"

PRICE_SOURCE = "Yahoo Finance daily prices (NSE), computed by this app"
FUND_SOURCE = "Yahoo Finance company statements"

BANNED_PHRASES = [
    "guaranteed", "guarantee", "sure shot", "sure-shot", "buy now", "sell now",
    "will definitely", "can't lose", "cannot lose", "risk-free", "risk free", "multibagger",
]

DISCLAIMER = (
    "This is a research summary to support your own decision. It is not investment advice or a "
    "recommendation to buy or sell, and the author is not a SEBI-registered research analyst or "
    "investment adviser. Labels describe the state of a setup under fixed rules; they do not predict "
    "returns. You can lose money. The app never places orders."
)
