"""Measure the pattern detectors and write data/pattern_stats.json (shown in the app).

Usage:  python scripts/run_backtest.py
"""
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.backtest.evaluate import historical_report, synthetic_report  # noqa: E402
from app.config import STATS_FILE, STYLES  # noqa: E402
from app.data.providers import YahooProvider  # noqa: E402
from app.data.universe import ALL_SYMBOLS  # noqa: E402


def main():
    print("Synthetic labelled charts...")
    syn = synthetic_report(n_pos=200, n_neg=600)
    for k, v in syn.items():
        print(f"  {k:28s} hit {v['hit_rate']:.2f}  false positive {v['false_positive_rate']:.3f}")

    print("Fetching 5 years of daily prices for the built-in universe...")
    yp, frames = YahooProvider(), {}
    for s in ALL_SYMBOLS:
        try:
            frames[s] = yp.history(s, years=5)
        except Exception as e:
            print(f"  skipped {s}: {e}")
    hist = {}
    for key, st in STYLES.items():
        print(f"Walking forward with {key} settings...")
        hist[key] = historical_report(frames, st.k, st.horizon)
        for k, v in hist[key].items():
            print(f"  {k:28s} n={v['signals']:4d} target-first {v['reached_target_first']:.2f} "
                  f"baseline {v['baseline_target_first']:.2f} stop-first {v['hit_invalidation_first']:.2f}")

    first = min(f.index[0] for f in frames.values()).strftime("%Y-%m-%d")
    last = max(f.index[-1] for f in frames.values()).strftime("%Y-%m-%d")
    out = {
        "available": True, "generated": date.today().isoformat(),
        "source": f"Yahoo Finance daily prices, {len(frames)} large NSE stocks, {first} to {last}",
        "headline": ("Classic chart patterns have weak and disputed predictive power on liquid stocks. This table shows what the "
                     "detectors in this app actually did, so a pattern name is never taken as an edge by itself. "
                     "Patterns are not used in the label."),
        "synthetic_note": ("computer-drawn textbook shapes with noise (200 per pattern) and 600 random charts with no intended "
                           "pattern. This shows whether the code finds the shape and how often it sees one in noise. "
                           "They are not human-labelled real charts."),
        "historical_note": ("every newly confirmed pattern over the period, tracked until price reached the measured target, "
                            "hit the invalidation price, or the holding window ended. The baseline uses random entry days in "
                            "the same stock with the same target and stop distances. A pattern only adds something if it "
                            "beats the baseline by a clear margin on a large sample. Past results do not predict future ones; "
                            "costs and slippage are not included; the stocks are today's large companies, which flatters results."),
        "synthetic": syn, "historical": hist, "universe": sorted(frames),
    }
    STATS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATS_FILE.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("Wrote", STATS_FILE)


if __name__ == "__main__":
    main()
