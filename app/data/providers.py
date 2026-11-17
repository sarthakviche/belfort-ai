"""Data providers. Everything the app shows comes through here, with a source and an as-of date.

To plug in an NSE MCP or a licensed feed later, write a class with the same methods as
YahooProvider / NseArchiveProvider and swap it in app/analysis/pipeline.py.
"""
import io
import re
import warnings
from datetime import date, datetime, timedelta

import httpx
import pandas as pd

from .cache import cached

warnings.filterwarnings("ignore")

SYMBOL_RE = re.compile(r"^[A-Z0-9&\-]{1,20}$")
INFO_KEYS = ["longName", "shortName", "sector", "industry", "trailingPE", "priceToBook", "marketCap",
             "returnOnEquity", "debtToEquity", "heldPercentInsiders", "heldPercentInstitutions",
             "regularMarketTime", "currency", "revenueGrowth", "earningsGrowth"]


class DataError(Exception):
    pass


def clean_symbol(raw: str) -> str:
    s = (raw or "").strip().upper()
    for suffix in (".NS", ".BO"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    if not SYMBOL_RE.match(s):
        raise DataError("Enter an NSE symbol such as RELIANCE, TCS or HDFCBANK.")
    return s


class YahooProvider:
    name = "Yahoo Finance"

    def _ticker(self, symbol: str):
        import yfinance as yf
        return yf.Ticker(symbol + ".NS")

    def history(self, symbol: str, years: int = 5) -> pd.DataFrame:
        def load():
            df = self._ticker(symbol).history(period=f"{years}y", auto_adjust=False)
            if df is None or df.empty:
                return None
            df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna()
            df = df[(df["high"] >= df["low"]) & (df["close"] > 0)]
            df.index = pd.DatetimeIndex(df.index).tz_localize(None).normalize()
            return df[~df.index.duplicated(keep="last")]

        df = cached(f"hist:{symbol}:{years}", 30 * 60, load)
        if df is None or df.empty:
            raise DataError(f"No price history found for {symbol} on NSE. Check the symbol.")
        return df

    def fundamentals(self, symbol: str) -> dict:
        def load():
            t = self._ticker(symbol)
            out = {}
            for key, attr in (("income", "income_stmt"), ("balance", "balance_sheet"),
                              ("cashflow", "cashflow"), ("q_income", "quarterly_income_stmt")):
                try:
                    out[key] = getattr(t, attr)
                except Exception:
                    out[key] = None
            out["info"] = self._info(t)
            return out

        return cached(f"fund:{symbol}", 24 * 3600, load)

    @staticmethod
    def _info(t) -> dict:
        try:
            info = t.info or {}
        except Exception:
            info = {}
        return {k: info.get(k) for k in INFO_KEYS}

    def info(self, symbol: str) -> dict:
        return cached(f"info2:{symbol}", 24 * 3600, lambda: self._info(self._ticker(symbol)))

    def earnings_date(self, symbol: str) -> date | None:
        def load():
            try:
                cal = self._ticker(symbol).calendar or {}
                dates = cal.get("Earnings Date") or []
                return dates[0] if dates else None
            except Exception:
                return None

        return cached(f"cal:{symbol}", 12 * 3600, load)


class NseArchiveProvider:
    """Public end-of-day files from nsearchives.nseindia.com. Best effort; failures are reported."""
    name = "NSE archives"
    BHAV = "https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d}.csv"
    BULK = "https://nsearchives.nseindia.com/content/equities/bulk.csv"
    HEADERS = {"User-Agent": "stock-analyst/0.1"}

    def _get(self, url: str) -> str | None:
        r = httpx.get(url, headers=self.HEADERS, timeout=8.0, follow_redirects=True)
        if r.status_code != 200 or "SYMBOL" not in r.text[:200].upper() and "Symbol" not in r.text[:200]:
            return None
        return r.text

    LISTED = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

    def listed(self) -> list[tuple[str, str]]:
        """(symbol, company name) for every NSE-listed equity. Empty list if the file cannot be fetched."""
        def load():
            try:
                text = self._get(self.LISTED)
            except Exception:
                return []
            if not text:
                return []
            df = pd.read_csv(io.StringIO(text), skipinitialspace=True)
            df.columns = [c.strip() for c in df.columns]
            return [(str(s).strip(), str(n).strip()) for s, n in zip(df["SYMBOL"], df["NAME OF COMPANY"])]

        rows = cached("listed:v1", 7 * 86400, load)
        if not rows:  # an empty result should not be kept for a week
            rows = load()
        return rows

    def search(self, query: str, limit: int = 8) -> list[dict]:
        """Find companies by symbol or by name."""
        q = " ".join((query or "").upper().split())
        if not q:
            return []
        scored = []
        for sym, name in self.listed():
            up = name.upper()
            if sym == q:
                rank = 0
            elif sym.startswith(q):
                rank = 1
            elif up.startswith(q):
                rank = 2
            elif any(w.startswith(q) for w in up.split()) or (" " in q and q in up):
                rank = 3
            elif q in up or q in sym:
                rank = 4
            else:
                continue
            scored.append((rank, len(name), sym, name))
        scored.sort()
        return [{"symbol": s, "name": n} for _, _, s, n in scored[:limit]]

    def _bhav(self, d: date) -> pd.DataFrame | None:
        def load():
            try:
                text = self._get(self.BHAV.format(d=d.strftime("%d%m%Y")))
            except Exception:
                return "error"
            if not text:
                return None
            df = pd.read_csv(io.StringIO(text), skipinitialspace=True)
            df.columns = [c.strip() for c in df.columns]
            return df[["SYMBOL", "SERIES", "DATE1", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE",
                       "TTL_TRD_QNTY", "DELIV_QTY", "DELIV_PER"]]

        ttl = 3600 if d >= date.today() - timedelta(days=1) else 400 * 86400
        return cached(f"bhav2:{d.isoformat()}", ttl, load)

    def recent_bars(self, symbol: str, after: date) -> pd.DataFrame:
        """Daily bars newer than `after`, for sessions the main price source has not published yet."""
        rows, d = [], date.today()
        while d > after and (date.today() - d).days < 7:
            if d.weekday() < 5:
                df = self._bhav(d)
                if isinstance(df, pd.DataFrame):
                    m = df[(df["SYMBOL"].str.strip() == symbol) & (df["SERIES"].str.strip() == "EQ")]
                    if len(m):
                        r = m.iloc[0]
                        rows.append({"date": pd.Timestamp(d), "open": float(r["OPEN_PRICE"]), "high": float(r["HIGH_PRICE"]),
                                     "low": float(r["LOW_PRICE"]), "close": float(r["CLOSE_PRICE"]),
                                     "volume": float(r["TTL_TRD_QNTY"])})
            d -= timedelta(days=1)
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).set_index("date").sort_index()

    def delivery(self, symbol: str, days: int = 5) -> dict:
        """Delivery percentage for the last few sessions."""
        rows, d, tries, errors = [], date.today(), 0, 0
        while len(rows) < days and tries < days + 9:
            tries += 1
            if d.weekday() < 5:
                df = self._bhav(d)
                if isinstance(df, str):
                    errors += 1
                    if errors >= 2:
                        break
                elif df is not None:
                    m = df[(df["SYMBOL"].str.strip() == symbol) & (df["SERIES"].str.strip() == "EQ")]
                    if len(m):
                        pct = pd.to_numeric(m["DELIV_PER"].iloc[0], errors="coerce")
                        if pd.notna(pct):
                            rows.append({"date": d.isoformat(), "delivery_pct": float(pct)})
            d -= timedelta(days=1)
        if not rows:
            reason = ("NSE archive did not respond" if errors else
                      "No delivery figure in the NSE archive for this symbol in the last sessions")
            return {"available": False, "missing_reason": reason, "source": self.name}
        return {"available": True, "latest": rows[0], "rows": rows,
                "average_pct": round(sum(r["delivery_pct"] for r in rows) / len(rows), 2),
                "source": "NSE archives: security-wise delivery file", "as_of": rows[0]["date"]}

    def bulk_deals(self, symbol: str) -> dict:
        def load():
            try:
                text = self._get(self.BULK)
            except Exception:
                return None
            if not text:
                return None
            df = pd.read_csv(io.StringIO(text), skipinitialspace=True)
            df.columns = [c.strip() for c in df.columns]
            return df

        df = cached("bulk:" + date.today().isoformat() + datetime.now().strftime(":%H"), 3600, load)
        if df is None:
            return {"available": False, "missing_reason": "NSE bulk deal file did not respond", "source": self.name}
        try:
            m = df[df["Symbol"].astype(str).str.strip() == symbol]
            deals = [{"date": str(r["Date"]).strip(), "client": str(r["Client Name"]).strip(),
                      "side": str(r["Buy/Sell"]).strip(), "quantity": float(str(r["Quantity Traded"]).replace(",", "")),
                      "price": float(str(r["Trade Price / Wght. Avg. Price"]).replace(",", ""))}
                     for _, r in m.iterrows()]
            as_of = str(df["Date"].iloc[0]).strip() if len(df) else None
        except Exception:
            return {"available": False, "missing_reason": "NSE bulk deal file format changed", "source": self.name}
        return {"available": True, "deals": deals, "source": "NSE archives: latest bulk deals file", "as_of": as_of}
