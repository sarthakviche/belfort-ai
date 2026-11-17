"""Stop suggestion and position size. Risk is never allowed to exceed the stated limit."""
import math

from ..config import TICK, Style


def _tick_down(x: float) -> float:
    return round(math.floor(x / TICK + 1e-9) * TICK, 2)


def suggest_stop(close: float, atr: float, supports: list[dict], st: Style) -> dict:
    """Stop just under the nearest usable support, else a fixed ATR distance."""
    min_gap = 0.75 * atr if st.key == "swing" else 1.5 * atr
    for s in supports:
        stop = s["price"] - 0.5 * atr
        gap = close - stop
        if gap >= min_gap and gap / close <= st.max_stop_pct:
            return {"stop": _tick_down(stop), "basis": f"half an ATR below support at ₹{s['price']:.2f} "
                    f"({s['touches']} touch{'es' if s['touches'] != 1 else ''})", "kind": "support"}
    stop = close - st.atr_stop * atr
    return {"stop": _tick_down(stop), "basis": f"{st.atr_stop:g} x ATR (₹{atr:.2f}) below the last close; "
            "no usable support nearby", "kind": "atr"}


def position_size(capital: float, risk_pct: float, entry: float, stop: float) -> dict:
    out = {"capital": capital, "risk_pct": risk_pct, "entry": entry, "stop": stop,
           "quantity": 0, "risk_per_share": None, "risk_amount": 0.0, "risk_budget": None,
           "position_value": 0.0, "position_pct": 0.0, "stop_pct": None,
           "capped_by_capital": False, "error": None}
    if capital <= 0 or risk_pct <= 0:
        out["error"] = "Capital and risk per trade must be above zero."
        return out
    if risk_pct > 100:
        out["error"] = "Risk per trade cannot exceed 100% of capital."
        return out
    if stop <= 0 or stop >= entry:
        out["error"] = "The stop must be below the entry price (this app sizes long positions only)."
        return out
    budget = capital * risk_pct / 100.0
    per_share = entry - stop
    by_risk = math.floor(budget / per_share + 1e-9)
    by_cap = math.floor(capital / entry + 1e-9)
    qty = max(0, min(by_risk, by_cap))
    out.update({
        "quantity": qty, "risk_per_share": round(per_share, 2), "risk_budget": round(budget, 2),
        "risk_amount": round(qty * per_share, 2), "position_value": round(qty * entry, 2),
        "position_pct": round(qty * entry / capital * 100, 2),
        "stop_pct": round(per_share / entry * 100, 2), "capped_by_capital": by_cap < by_risk,
    })
    if qty == 0:
        out["error"] = ("One share already risks more than your limit, or costs more than your capital. "
                        "The sized position is zero.")
    return out
