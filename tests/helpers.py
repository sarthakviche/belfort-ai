"""Synthetic inputs for tests. All figures here are made up and exist only to exercise the rules."""
import numpy as np
import pandas as pd

CR = 1e7
YEARS = pd.to_datetime(["2023-03-31", "2024-03-31", "2025-03-31", "2026-03-31"])


def statements(rev=(1000, 1150, 1300, 1500), op_margin=0.18, ni=None, debt=(200, 200, 200, 200),
               eq=(1000, 1150, 1320, 1500), recv=None, cfo=None, interest=(20, 20, 20, 20), unusual=(0, 0, 0, 0),
               shares=(10, 10, 10, 10)) -> dict:
    rev = np.array(rev, float)
    op = rev * op_margin
    ni = np.array(ni, float) if ni is not None else rev * 0.12
    recv = np.array(recv, float) if recv is not None else rev * 0.10
    cfo = np.array(cfo, float) if cfo is not None else ni * 1.0
    pretax = ni * 1.3

    def frame(rows):
        return pd.DataFrame({k: np.array(v, float) * CR for k, v in rows.items()}, index=YEARS).T

    return {
        "income": frame({"Total Revenue": rev, "Operating Income": op, "EBIT": op, "Net Income": ni,
                         "Pretax Income": pretax, "Interest Expense": interest, "Total Unusual Items": unusual}),
        "balance": frame({"Total Debt": debt, "Stockholders Equity": eq, "Accounts Receivable": recv,
                          "Ordinary Shares Number": shares}),
        "cashflow": frame({"Operating Cash Flow": cfo}),
        "q_income": None,
        "info": {"longName": "Test Company Ltd", "trailingPE": 20.0, "marketCap": 5000 * CR, "sector": "Industrials"},
    }


def price_frame(n=400, drift=0.0015, seed=1, noise=0.008) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, noise, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    idx = pd.bdate_range(end="2026-11-13", periods=n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close,
                         "volume": rng.lognormal(13, 0.3, n)}, index=idx)
