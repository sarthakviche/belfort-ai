"""Run the whole analysis for one symbol and style and return a JSON-ready report."""
import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import numpy as np
import pandas as pd

from ..config import DISCLAIMER, FUND_SOURCE, PRICE_SOURCE, STATS_FILE, STYLES
from ..data.providers import DataError, NseArchiveProvider, YahooProvider, clean_symbol
from ..data.universe import LENDER_SECTORS, SECTOR_OF, peers_of
from . import explain, fundamentals, sizing, verdict
from .indicators import atr as atr_series
from .indicators import macd, rsi, sma
from .patterns import Ctx, detect_all
from .pivots import find_pivots
from .structure import fibonacci, find_levels, trend_state, volume_read

prices = YahooProvider()
nse = NseArchiveProvider()
_pool = ThreadPoolExecutor(max_workers=8)


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:  # a failed side-fetch must never break the report
        return e


def _clean(o):
    """Make the report JSON-safe: numpy types to Python, NaN to None."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if math.isnan(float(o)) or math.isinf(float(o)) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, (pd.Timestamp, date)):
        return o.isoformat()[:10]
    return o


def pattern_stats() -> dict:
    if STATS_FILE.exists():
        return json.loads(STATS_FILE.read_text(encoding="utf-8"))
    return {"available": False, "missing_reason": "The backtest has not been run. Run: python scripts/run_backtest.py"}


def _quote(df: pd.DataFrame) -> dict:
    last, c = df.iloc[-1], df["close"]
    yr = df.iloc[-250:]
    ret = lambda n: round((float(c.iloc[-1]) / float(c.iloc[-1 - n]) - 1) * 100, 1) if len(c) > n else None  # noqa: E731
    return {"open": float(last["open"]), "high": float(last["high"]), "low": float(last["low"]),
            "prev_close": float(c.iloc[-2]), "volume": float(last["volume"]),
            "high_52w": float(yr["high"].max()), "low_52w": float(yr["low"].min()),
            "ret_1w": ret(5), "ret_1m": ret(21), "ret_3m": ret(63), "ret_1y": ret(249)}


def technical(df: pd.DataFrame, st) -> dict:
    hi, lo, cl, vo = (df[c].values.astype(float) for c in ("high", "low", "close", "volume"))
    a = float(atr_series(df).iloc[-1])
    piv = find_pivots(hi, lo, st.k)
    trend = trend_state(df, piv, st)
    levels = find_levels(piv, float(cl[-1]), a, len(df))
    vol = volume_read(df, st)
    line, sig, hist = macd(df["close"])
    mom = {"rsi": float(rsi(df["close"]).iloc[-1]), "macd": float(line.iloc[-1]),
           "macd_signal": float(sig.iloc[-1]), "macd_hist": float(hist.iloc[-1])}
    fib = fibonacci(df, st.fib_lookback)
    pats = [p.to_dict() for p in detect_all(Ctx(hi, lo, cl, vo, piv, st.k, a))]
    return {"atr": a, "trend": trend, "levels": levels, "volume": vol, "momentum": mom, "fib": fib,
            "patterns": pats, "pivots": [{"idx": p.idx, "price": p.price, "kind": p.kind} for p in piv[-12:]]}


def _add_dates(tech: dict, df: pd.DataFrame):
    d = lambda i: df.index[int(i)].strftime("%Y-%m-%d")  # noqa: E731
    for p in tech["patterns"]:
        for pt in p["points"]:
            pt["date"] = d(pt["idx"])
        p["confirm_date"] = d(p["confirm_idx"]) if p.get("confirm_idx") is not None else None
    for side in ("supports", "resistances"):
        for l in tech["levels"][side]:
            l["dates"] = [d(i) for i in l.pop("bars")]
            l["last_touch"] = d(l.pop("last_touch_idx"))
    for key in ("swing_highs", "swing_lows"):
        for s in tech["trend"][key]:
            s["date"] = d(s["idx"])
    for p in tech["pivots"]:
        p["date"] = d(p["idx"])
    if tech["fib"]:
        tech["fib"]["high_date"], tech["fib"]["low_date"] = d(tech["fib"]["high_idx"]), d(tech["fib"]["low_idx"])
    bo = tech["volume"].get("breakout")
    if bo:
        bo["date"] = d(bo["idx"])


def resolve(query: str) -> str:
    """Accept an NSE symbol or a company name and return the symbol."""
    try:
        sym = clean_symbol(query)
    except DataError:
        sym = None
    listed = _safe(nse.listed)
    known = {s for s, _ in listed} if isinstance(listed, list) else set()
    if sym and (sym in known or not known):
        return sym  # an exact symbol, or the company list is unavailable so trust the input
    hits = _safe(nse.search, query, 1)
    if isinstance(hits, list) and hits:
        return hits[0]["symbol"]
    if sym is None:
        raise DataError("No NSE company matches that name. Try the symbol, for example RELIANCE or HDFCBANK.")
    return sym


def analyze(symbol: str, style: str = "swing", capital: float = 100000, risk_pct: float = 1.0,
            stop: float | None = None, entry: float | None = None) -> dict:
    symbol = resolve(symbol)
    if style not in STYLES:
        raise DataError("Style must be 'swing' or 'positional'.")
    st = STYLES[style]

    f_hist = _pool.submit(prices.history, symbol)
    f_fund = _pool.submit(_safe, prices.fundamentals, symbol)
    f_earn = _pool.submit(_safe, prices.earnings_date, symbol)
    f_deliv = _pool.submit(_safe, nse.delivery, symbol)
    f_bulk = _pool.submit(_safe, nse.bulk_deals, symbol)
    sector, peer_syms = peers_of(symbol)
    f_peers = {s: _pool.submit(_safe, prices.info, s) for s in peer_syms}

    df = f_hist.result()
    deliv = f_deliv.result()  # also warms the NSE file cache used just below
    price_note = ""
    extra = _safe(nse.recent_bars, symbol, df.index[-1].date())
    if isinstance(extra, pd.DataFrame) and len(extra):
        # Guard against an unadjusted corporate action between the two sources.
        if abs(float(extra["close"].iloc[0]) / float(df["close"].iloc[-1]) - 1) < 0.25:
            df = pd.concat([df, extra])
            price_note = f" Last {len(extra)} session(s) taken from the NSE end-of-day file."
    if len(df) < 40:
        raise DataError(f"{symbol} has only {len(df)} days of price history, too little to analyse.")
    as_of = df.index[-1].strftime("%Y-%m-%d")
    close = float(df["close"].iloc[-1])
    prev = float(df["close"].iloc[-2])

    tech = technical(df, st)
    _add_dates(tech, df)

    # Sizing comes before the signal.
    entry_px = float(entry) if entry else close
    sug = sizing.suggest_stop(close, tech["atr"], tech["levels"]["supports"], st)
    stop_px = float(stop) if stop else sug["stop"]
    sz = sizing.position_size(float(capital), float(risk_pct), entry_px, stop_px)
    sz.update({"stop_basis": "your own stop" if stop else sug["basis"], "suggested_stop": sug["stop"],
               "suggested_basis": sug["basis"], "entry_basis": "your own entry" if entry else "last close",
               "text": explain.sizing_text(sz)})

    raw = f_fund.result()
    info = {} if isinstance(raw, Exception) or not raw else (raw.get("info") or {})
    is_lender = SECTOR_OF.get(symbol) in LENDER_SECTORS or info.get("sector") == "Financial Services"
    if isinstance(raw, Exception) or not raw:
        fund = {"available": False, "concerns": [], "pros": [], "cons": [], "verdict": None,
                "missing_reason": "Company statements could not be fetched from the data source.",
                "source": FUND_SOURCE, "as_of": None}
    else:
        infos = {s: (None if isinstance(f.result(), Exception) else f.result()) for s, f in f_peers.items()}
        fund = fundamentals.analyse(raw, is_lender, fundamentals.peer_block(sector, infos))
    fund["text"] = explain.fundamental_text(fund)

    ed = f_earn.result()
    earnings = {"available": False, "missing_reason": "Results date not returned by the source.", "source": "Yahoo Finance calendar"}
    earn_days = None
    if isinstance(ed, date):
        earn_days = int(np.busday_count(date.today(), ed)) if ed >= date.today() else None
        if earn_days is not None:
            earnings = {"available": True, "date": ed.isoformat(), "trading_days_away": earn_days,
                        "source": "Yahoo Finance calendar (estimate; confirm on the exchange)", "as_of": date.today().isoformat()}
        else:
            earnings["missing_reason"] = "The source only has a past results date; the next date is not announced there."

    v = verdict.decide(st, len(df), tech["trend"], tech["levels"], tech["volume"], tech["atr"],
                       entry_px, stop_px, fund, earn_days)
    v["agreement"] = verdict.agreement(tech["trend"]["direction"], fund, st)
    v["invalidation"] = {"price": stop_px, "text": f"A daily close below ₹{stop_px:.2f} ({sz['stop_basis']})."}
    tech["text"] = explain.technical_text(st, tech["trend"], tech["levels"], tech["volume"], tech["momentum"],
                                          tech["fib"], tech["patterns"])
    tech["style_text"] = explain.style_text(st, tech["trend"], stop_px, v)

    bulk = f_bulk.result()
    na = lambda why: {"available": False, "missing_reason": why}  # noqa: E731
    extras = {
        "delivery": deliv if isinstance(deliv, dict) else na("NSE archive request failed."),
        "bulk_deals": bulk if isinstance(bulk, dict) else na("NSE archive request failed."),
        "earnings": earnings,
        "order_book": na("Live buy and sell quantities need a broker or exchange feed, which is not connected."),
        "pledge": na("Promoter pledge data needs exchange shareholding filings or a licensed provider, which is not connected."),
        "announcements": na("Corporate announcements need an exchange feed, which is not connected. Check the NSE website."),
    }

    tail = df.iloc[-(320 if st.key == "swing" else 560):]
    fast_s, slow_s = sma(df["close"], st.fast).loc[tail.index], sma(df["close"], st.slow).loc[tail.index]
    ts = [d.strftime("%Y-%m-%d") for d in tail.index]
    chart = {
        "candles": [{"time": t, "open": o, "high": h, "low": l, "close": c}
                    for t, o, h, l, c in zip(ts, tail["open"], tail["high"], tail["low"], tail["close"])],
        "volume": [{"time": t, "value": float(x)} for t, x in zip(ts, tail["volume"])],
        "fast": [{"time": t, "value": float(x)} for t, x in zip(ts, fast_s) if not math.isnan(x)],
        "slow": [{"time": t, "value": float(x)} for t, x in zip(ts, slow_s) if not math.isnan(x)],
        "first_date": ts[0],
    }

    sources = [
        {"item": "Price, volume, averages, levels, patterns, RSI, MACD, ATR, Fibonacci", "source": PRICE_SOURCE,
         "as_of": as_of, "note": f"{len(df)} daily bars from {df.index[0].strftime('%Y-%m-%d')}. Split-adjusted, not dividend-adjusted." + price_note},
        {"item": "Annual statements and ratios", "source": fund.get("source"), "as_of": fund.get("as_of"),
         "note": fund.get("missing_reason") or fund.get("history_note")},
        {"item": "Valuation (P/E, market value) and peers", "source": "Yahoo Finance key ratios (trailing)",
         "as_of": "latest available", "note": (fund.get("peers") or {}).get("missing_reason")},
    ]
    for label, key in (("Delivery percentage", "delivery"), ("Bulk deals", "bulk_deals"), ("Next results date", "earnings"),
                       ("Order book depth", "order_book"), ("Promoter pledge", "pledge"), ("Corporate announcements", "announcements")):
        e = extras[key]
        sources.append({"item": label, "source": e.get("source") or "not available", "as_of": e.get("as_of"),
                        "note": e.get("missing_reason")})

    report = {
        "symbol": symbol, "name": info.get("longName") or info.get("shortName") or symbol,
        "sector": sector or info.get("sector"), "style": {"key": st.key, "name": st.name, "holds": st.holds},
        "as_of": as_of, "bars": len(df),
        "price": {"close": close, "change_pct": round((close / prev - 1) * 100, 2), "source": PRICE_SOURCE, "as_of": as_of},
        "quote": _quote(df),
        "verdict": v, "sizing": sz, "technical": tech, "fundamental": fund, "extras": extras,
        "chart": chart, "pattern_stats": pattern_stats(), "sources": sources, "disclaimer": DISCLAIMER,
    }
    return _clean(report)
