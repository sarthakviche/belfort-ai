"""Plain-language explanations built from the computed numbers. No language model is required."""
from ..config import BANNED_PHRASES, Style


def find_banned(text: str) -> list[str]:
    low = text.lower()
    return [p for p in BANNED_PHRASES if p in low]


def trend_sentence(t: dict) -> str:
    """One plain sentence on the trend, with the figures behind it."""
    c, d, phase = t["close"], t["direction"], t.get("phase")
    fast, slow = t.get("fast"), t.get("slow")
    r = t.get("recent")
    move = f" Price has moved {r['pct']:+.1f}% in the last {r['bars']} sessions." if r else ""
    avgs = (f"its {t.get('fast_n')}-day average (₹{fast:.2f}) and {t.get('slow_n')}-day average (₹{slow:.2f})"
            if fast and slow else "its averages")
    if d == "up" and phase == "established":
        return (f"The trend is up and established: each rally peak and each dip has been higher than the one before, "
                f"and price ₹{c:.2f} is above {avgs}.{move}")
    if d == "up":
        how = (f"price ₹{c:.2f} has closed above its last swing high (₹{t['last_swing_high']:.2f})"
               if t.get("broke_above_last_high") else f"price ₹{c:.2f} is above {avgs}")
        return (f"The trend has turned up, but only recently: {how} and is above its {t.get('slow_n')}-day average.{move} "
                "It has not yet pulled back and held a higher low, which is what confirms a new uptrend.")
    if d == "down" and phase == "established":
        return (f"The trend is down and established: each rally peak and each dip has been lower than the one before, "
                f"and price ₹{c:.2f} is below {avgs}.{move}")
    if d == "down":
        how = (f"price ₹{c:.2f} has closed below its last swing low (₹{t['last_swing_low']:.2f})"
               if t.get("broke_below_last_low") else f"price ₹{c:.2f} is below {avgs}")
        return f"The trend has turned down recently: {how} and is below its {t.get('slow_n')}-day average.{move}"
    side = ""
    if slow:
        side = f" Price ₹{c:.2f} is {'above' if c > slow else 'below'} its {t.get('slow_n')}-day average (₹{slow:.2f})."
    return f"There is no clear trend: rally peaks and dips are not consistently rising or falling.{side}{move}"


def technical_text(st: Style, trend: dict, levels: dict, vol: dict, mom: dict, fib: dict | None,
                   patterns: list[dict]) -> list[str]:
    out = []
    c = trend["close"]
    out.append(trend_sentence(trend))
    s, r = levels["supports"], levels["resistances"]
    if s:
        out.append(f"Nearest support (a price where buyers stepped in before) is ₹{s[0]['price']:.2f}, "
                   f"{abs(s[0]['distance_pct']):.1f}% below, touched {s[0]['touches']} time(s).")
    else:
        out.append("No support level was found below the current price in the last year of swings.")
    if r:
        out.append(f"Nearest resistance (a price where sellers stepped in before) is ₹{r[0]['price']:.2f}, "
                   f"{r[0]['distance_pct']:.1f}% above, touched {r[0]['touches']} time(s).")
    else:
        out.append("No resistance level sits above the current price in the last year of swings.")
    if vol.get("rel_volume") is not None:
        rv = vol["rel_volume"]
        tone = "well above" if rv >= 1.5 else "above" if rv > 1.1 else "below" if rv < 0.9 else "about equal to"
        line = f"The last session's volume was {rv} times the 20-day average ({tone} normal)."
        if vol.get("up_down_ratio"):
            ud = vol["up_down_ratio"]
            line += (f" Over 20 sessions, up-days averaged {ud} times the volume of down-days, "
                     f"which {'supports' if ud > 1.1 else 'does not support' if ud < 0.9 else 'neither supports nor contradicts'} buying interest.")
        out.append(line)
    bo = vol.get("breakout")
    if bo:
        out.append(f"Price broke above its {vol['breakout_n']}-day high (₹{bo['level']:.2f}) {bo['bars_ago']} session(s) ago on "
                   f"{bo['rel_volume']} times average volume: "
                   + ("volume agrees with the move." if bo["confirmed"] else "thin volume, so the move is less convincing."))
    rsi = mom["rsi"]
    rsi_txt = "stretched to the upside" if rsi >= 70 else "weak" if rsi <= 30 else "in the middle of its range"
    out.append(f"Momentum: RSI(14) is {rsi:.0f} ({rsi_txt}); MACD is {'above' if mom['macd_hist'] > 0 else 'below'} its signal line.")
    if fib:
        mid = next(l for l in fib["levels"] if l["ratio"] == 0.5)
        a, b = (fib["low"], fib["high"]) if fib["direction"] == "up" else (fib["high"], fib["low"])
        out.append(f"The last major swing ran {fib['direction']} from ₹{a:.2f} to ₹{b:.2f}. "
                   f"Its halfway point is ₹{mid['price']:.2f}.")
    shapes = [p for p in patterns if "trend line" not in p["name"]]
    if shapes:
        p = shapes[0]
        out.append(f"Pattern found: {p['name']} ({p['status']}, score {p['score']:.2f}). "
                   "Treat this as context: see the reliability table for how such patterns actually performed.")
    else:
        out.append("No classic chart pattern is present right now.")
    return out


def style_text(st: Style, trend: dict, stop: float, verdict: dict) -> str:
    if st.key == "swing":
        return (f"For a swing trade ({st.holds}) what matters is the nearby levels and the stop distance. "
                f"The setup fails on a close below ₹{stop:.2f}.")
    return (f"For a positional trade ({st.holds}) what matters is the larger trend and whether earnings are moving the right way. "
            f"The trend view fails on a close below ₹{stop:.2f}.")


def fundamental_text(fund: dict) -> str:
    if not fund.get("available"):
        return "The business could not be assessed: " + fund.get("missing_reason", "figures are missing.")
    real = [c for c in fund["concerns"] if c["severity"] != "info"]
    word = {"constructive": "Constructive", "neutral": "Neutral", "cautious": "Cautious"}[fund["verdict"]]
    np_, nc = len(fund["pros"]), len(real)
    why = (f"{np_} strength{'s' if np_ != 1 else ''} and {nc} concern{'s' if nc != 1 else ''} "
           f"{'were' if nc != 1 else 'was'} found in the annual figures")
    worst = f" The most important concern: {real[0]['title'].lower()}." if real else " No concern was flagged by the checks that ran."
    return f"{word}: {why}.{worst}"


def sizing_text(sz: dict) -> str:
    if sz.get("error") and not sz.get("quantity"):
        return sz["error"]
    line = (f"With ₹{sz['capital']:,.0f} and a limit of {sz['risk_pct']:g}% per trade you can lose up to ₹{sz['risk_budget']:,.2f}. "
            f"Entry ₹{sz['entry']:.2f} and stop ₹{sz['stop']:.2f} risk ₹{sz['risk_per_share']:.2f} a share, "
            f"so the size is {sz['quantity']} share(s): ₹{sz['position_value']:,.2f} invested, ₹{sz['risk_amount']:,.2f} at risk.")
    if sz["capped_by_capital"]:
        line += " The size is limited by your capital, not by the risk limit, so less than your limit is at risk."
    return line
