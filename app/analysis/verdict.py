"""The single label. A fixed rule over computed inputs, so the same data always gives the same label.

Chart patterns are deliberately not part of this rule: their measured value on history is weak
(see the pattern reliability table), so they are shown as context only.
"""
from .explain import trend_sentence
from ..config import (LABEL_AVOID, LABEL_NODATA, LABEL_VALID, LABEL_WATCH, MIN_REWARD_TO_RISK, Style)


def _check(name, passed, detail):
    return {"name": name, "passed": bool(passed), "detail": detail}


def decide(st: Style, n_bars: int, trend: dict, levels: dict, vol: dict, atr: float,
           entry: float, stop: float, fund: dict, earnings_in_days: int | None) -> dict:
    close = trend["close"]
    checks, reasons = [], []
    real = [c for c in fund.get("concerns", []) if c["severity"] != "info"]
    highs = [c for c in real if c["severity"] == "high"]
    meds = [c for c in real if c["severity"] == "medium"]

    if n_bars < st.min_bars:
        return {"label": LABEL_NODATA, "checks": [], "reasons": [
            f"Only {n_bars} daily bars of history are available; the {st.name.lower()} rule needs {st.min_bars}."],
            "summary": "There is not enough price history to judge this stock under the rule.",
            "main_risk": "Too little history: any reading would be a guess.", "unmet": []}

    d = trend["direction"]
    trend_detail = trend_sentence(trend)
    checks.append(_check("Trend is up", d == "up", trend_detail))

    # Location: near support, pulled back to the fast average, or a fresh breakout on volume.
    sup = levels["supports"][0] if levels["supports"] else None
    bo = vol.get("breakout")
    fast = trend.get("fast")
    if bo and bo["still_above"] and bo["confirmed"]:
        loc_ok, loc = True, (f"Closed above the {st.breakout_n}-day high of ₹{bo['level']:.2f} "
                             f"on {bo['rel_volume']} times average volume.")
    elif bo and bo["still_above"]:
        loc_ok, loc = False, (f"Broke the {st.breakout_n}-day high of ₹{bo['level']:.2f} but on thin volume "
                              f"({bo['rel_volume']} times average; the rule wants 1.5).")
    elif sup and close - sup["price"] <= 1.5 * atr:
        loc_ok, loc = True, f"Price is within 1.5 ATR of support at ₹{sup['price']:.2f} ({sup['touches']} touches)."
    elif fast and 0 <= close - fast <= atr:
        loc_ok, loc = True, f"Price has pulled back to its {st.fast}-day average (₹{fast:.2f})."
    else:
        where = f"{(close / sup['price'] - 1) * 100:.1f}% above the nearest support (₹{sup['price']:.2f})" if sup else "with no support level below"
        loc_ok, loc = False, f"Price is between levels, {where}. Entries far from support need wide stops."
    checks.append(_check("Price is at a sensible entry area", loc_ok, loc))

    ext = (close - fast) / atr if fast and atr else 0
    checks.append(_check("Price is not stretched", ext <= 3,
                         (f"Price is {ext:.1f} ATR above its {st.fast}-day average (limit 3)."
                          + (" After a fast run like this, a pullback is common and a sensible stop sits far away."
                             if ext > 3 else "")) if fast else "Average not available."))

    stop_pct = (entry - stop) / entry if stop and entry > stop else None
    checks.append(_check("Stop distance is acceptable", stop_pct is not None and stop_pct <= st.max_stop_pct,
                         f"Stop at ₹{stop:.2f} is {stop_pct * 100:.1f}% below entry (limit {st.max_stop_pct * 100:.0f}% for {st.name.lower()})."
                         if stop_pct is not None else "The stop is not below the entry price."))

    res = levels["resistances"][0] if levels["resistances"] else None
    if stop_pct is None:
        rr_ok, rr_txt, rr = False, "Cannot be computed without a valid stop.", None
    elif res is None:
        rr_ok, rr, rr_txt = True, None, "No resistance level overhead in the last year of swing highs."
    else:
        rr = (res["price"] - entry) / (entry - stop)
        rr_ok = rr >= MIN_REWARD_TO_RISK
        rr_txt = (f"Next resistance ₹{res['price']:.2f} is {rr:.1f} times the stop distance away "
                  f"(the rule wants at least {MIN_REWARD_TO_RISK}).")
    checks.append(_check("Room to the next resistance", rr_ok, rr_txt))

    if st.earnings_blackout:
        soon = earnings_in_days is not None and 0 <= earnings_in_days <= st.earnings_blackout
        checks.append(_check("No results due inside the holding window", not soon,
                             f"Results are expected in about {earnings_in_days} trading days; prices can gap past a stop."
                             if soon else ("No results date inside the next "
                                           f"{st.earnings_blackout} trading days." if earnings_in_days is not None
                                           else "Results date not available from the source; check the exchange calendar.")))

    gate_ran = bool(fund.get("available"))
    checks.append(_check("Business concerns check ran", gate_ran,
                         f"{len(highs)} serious, {len(meds)} moderate concerns found." if gate_ran
                         else "Fundamentals were not available, so the concerns check did not run. The label is capped at Watch."))

    unmet = [c for c in checks if not c["passed"]]
    if d == "down":
        label = LABEL_AVOID
        reasons.append(trend_detail)
        if highs:
            reasons.append(f"Serious business concern: {highs[0]['title'].lower()}.")
        summary = f"The trend is down for a {st.name.lower()} trade. The rule does not look for entries against the trend."
    elif highs:
        label = LABEL_AVOID
        reasons.append(f"Serious business concern: {highs[0]['title']}. {highs[0]['detail']}")
        summary = "The business has a serious concern. The rule does not label a setup valid while it stands."
    elif not unmet:
        label = LABEL_VALID
        reasons = [c["detail"] for c in checks[:2]]
        summary = (f"The chart conditions for a {st.name.lower()} setup are met and no serious business concern was found. "
                   "This describes the setup. Whether to trade it is your decision.")
    else:
        label = LABEL_WATCH
        reasons = [c["detail"] for c in unmet[:2]]
        summary = f"Not a valid setup yet: {len(unmet)} of {len(checks)} conditions are unmet."

    if highs:
        main_risk = f"{highs[0]['title']}. {highs[0]['detail']}"
    elif label == LABEL_AVOID:
        main_risk = "Buying into a falling trend: most such entries keep falling before they recover."
    elif unmet:
        main_risk = unmet[0]["detail"]
    elif meds:
        main_risk = f"{meds[0]['title']}. {meds[0]['detail']}"
    else:
        main_risk = (f"A close below ₹{stop:.2f} means the setup has failed. Prices can also gap below a stop on news, "
                     "so the loss can be larger than planned.")
    return {"label": label, "summary": summary, "reasons": reasons, "checks": checks,
            "unmet": [c["name"] for c in unmet], "main_risk": main_risk,
            "reward_to_risk": round(rr, 2) if rr is not None else None}


def agreement(trend_dir: str, fund: dict, st: Style) -> dict:
    """State plainly whether the chart and the business point the same way."""
    if not fund.get("available"):
        return {"state": "unknown", "text": "The business side could not be assessed, so chart and business cannot be compared."}
    fv = fund["verdict"]
    if trend_dir == "up" and fv == "constructive":
        return {"state": "agree", "text": "Chart and business agree: the trend is up and the business looks sound on the figures available."}
    if trend_dir == "down" and fv == "cautious":
        return {"state": "agree", "text": "Chart and business agree, and both are negative: the trend is down and the business has concerns."}
    if trend_dir == "up" and fv == "cautious":
        return {"state": "conflict", "text": "Conflict: the chart is rising but the business has concerns. "
                                             "A rising price does not fix a weak balance sheet; treat the concerns as a warning flag."}
    if trend_dir == "down" and fv == "constructive":
        return {"state": "conflict", "text": f"Conflict: the business looks sound but the price trend is down. "
                                             f"For a {st.name.lower()} trade that is a stock to watch, not a setup."}
    return {"state": "mixed", "text": f"No strong agreement or conflict: the trend is {trend_dir} and the business read is {fv}."}
