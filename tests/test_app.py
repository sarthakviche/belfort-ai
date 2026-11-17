"""End-to-end tests of the report and API with the network replaced by synthetic data."""
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.analysis import explain, pipeline
from app.data.providers import DataError, NseArchiveProvider
from app.main import app
from tests.helpers import price_frame, statements


class FakePrices:
    def __init__(self, drift=0.0015, stm=None, n=400):
        self.drift, self.stm, self.n = drift, stm, n

    def history(self, symbol, years=5):
        if symbol == "NOSUCH":
            raise DataError("No price history found for NOSUCH on NSE. Check the symbol.")
        return price_frame(n=self.n, drift=self.drift)

    def fundamentals(self, symbol):
        if self.stm == "fail":
            raise RuntimeError("source down")
        return self.stm or statements()

    def info(self, symbol):
        return {"trailingPE": 18.0, "returnOnEquity": 0.15, "debtToEquity": 40.0}

    def earnings_date(self, symbol):
        return None


class FakeNse:
    def delivery(self, symbol, days=5):
        return {"available": False, "missing_reason": "test: archive offline", "source": "NSE archives"}

    def bulk_deals(self, symbol):
        return {"available": False, "missing_reason": "test: archive offline", "source": "NSE archives"}

    def recent_bars(self, symbol, after):
        return pd.DataFrame()

    def listed(self):
        return [("TCS", "Tata Consultancy Services Limited"), ("RELIANCE", "Reliance Industries Limited"),
                ("HDFCBANK", "HDFC Bank Limited"), ("NOSUCH", "No Such Company Limited")]

    def search(self, query, limit=8):
        return NseArchiveProvider.search(self, query, limit)


@pytest.fixture
def fake(monkeypatch):
    def install(**kw):
        monkeypatch.setattr(pipeline, "prices", FakePrices(**kw))
        monkeypatch.setattr(pipeline, "nse", FakeNse())
    install()
    return install


def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)


@pytest.mark.parametrize("style", ["swing", "positional"])
@pytest.mark.parametrize("drift", [0.0015, -0.0015, 0.0])
def test_report_is_complete_sourced_and_free_of_promises(fake, style, drift):
    fake(drift=drift)
    r = pipeline.analyze("RELIANCE", style, 200000, 1)
    json.dumps(r)  # JSON-safe, no NaN objects
    assert r["verdict"]["label"] in {"Setup valid", "Watch", "Avoid", "Insufficient data"}
    assert r["verdict"]["main_risk"] and r["verdict"]["invalidation"]["price"] > 0
    # acceptance 1: every source row names a source and a date, or says why it is missing
    for s in r["sources"]:
        assert s["source"]
        assert s["as_of"] or s["note"], s
    for key in ("order_book", "pledge", "announcements"):
        assert r["extras"][key]["available"] is False and r["extras"][key]["missing_reason"]
    # acceptance 5: the sized position never risks more than the limit
    sz = r["sizing"]
    assert sz["risk_amount"] <= sz["risk_budget"] + 1e-6
    assert sz["quantity"] * (sz["entry"] - sz["stop"]) <= 2000 + 1e-6
    # acceptance 6: no promise wording anywhere in the output
    for text in _strings({k: v for k, v in r.items() if k != "chart"}):
        assert not explain.find_banned(text), text
    # every pattern lists the exact bars it used
    for p in r["technical"]["patterns"]:
        assert p["points"] and all("date" in q and "price" in q for q in p["points"])
        assert 0 <= p["score"] <= 1


def test_downtrend_is_never_labelled_valid(fake):
    fake(drift=-0.003)
    for style in ("swing", "positional"):
        assert pipeline.analyze("TCS", style)["verdict"]["label"] != "Setup valid"


def test_serious_concern_blocks_valid_label_and_shows_as_main_risk(fake):
    fake(stm=statements(cfo=(100, 60, 10, -50)))
    r = pipeline.analyze("TCS", "swing")
    assert r["verdict"]["label"] == "Avoid"
    assert "cash" in r["verdict"]["main_risk"].lower()


def test_fundamentals_failure_caps_label_and_is_reported(fake):
    fake(stm="fail")
    r = pipeline.analyze("TCS", "swing")
    assert r["fundamental"]["available"] is False and r["fundamental"]["missing_reason"]
    assert r["verdict"]["label"] in {"Watch", "Avoid"}


def test_short_history_gives_insufficient_data(fake):
    fake(n=90)
    assert pipeline.analyze("TCS", "positional")["verdict"]["label"] == "Insufficient data"


def test_user_stop_is_respected(fake):
    r = pipeline.analyze("TCS", "swing", 100000, 2, stop=50.0)
    assert r["sizing"]["stop"] == 50.0 and r["sizing"]["stop_basis"] == "your own stop"
    assert r["sizing"]["risk_amount"] <= 2000 + 1e-6


def test_api_and_access_codes(fake, monkeypatch):
    c = TestClient(app)
    assert c.get("/").status_code == 200
    assert c.get("/api/analyze", params={"symbol": "TCS"}).status_code == 200
    assert c.get("/api/analyze", params={"symbol": "bad symbol!"}).status_code == 400
    assert c.get("/api/analyze", params={"symbol": "hdfc bank"}).json()["symbol"] == "HDFCBANK"   # company name works
    assert c.get("/api/analyze", params={"symbol": "relia"}).json()["symbol"] == "RELIANCE"       # partial name works
    assert c.get("/api/analyze", params={"symbol": "NOSUCH"}).status_code == 400
    assert c.get("/api/analyze", params={"symbol": "TCS", "risk_pct": 0}).status_code == 422
    monkeypatch.setenv("ACCESS_CODES", "alpha, beta")
    assert c.get("/api/analyze", params={"symbol": "TCS"}).status_code == 401
    assert c.get("/api/analyze", params={"symbol": "TCS"}, headers={"X-Access-Code": "beta"}).status_code == 200
    assert c.get("/api/config").json()["requires_code"] is True


def test_static_pages_contain_no_promise_wording():
    static = Path(__file__).resolve().parent.parent / "app" / "static"
    for f in static.iterdir():
        if f.suffix not in {".html", ".js", ".css"}:   # skip img/ and other non-text assets
            continue
        assert not explain.find_banned(f.read_text(encoding="utf-8")), f.name


def test_search_ranks_symbol_then_name(fake):
    hits = pipeline.nse.search("tata")
    assert hits and hits[0]["symbol"] == "TCS"
    assert pipeline.nse.search("HDFCBANK")[0]["symbol"] == "HDFCBANK"
    assert pipeline.nse.search("zzzz") == []


def test_report_has_quote_block(fake):
    q = pipeline.analyze("TCS", "swing")["quote"]
    assert q["low_52w"] <= q["high_52w"] and q["volume"] > 0


def test_chat_without_key_says_how_to_set_up(fake, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    c = TestClient(app)
    r = c.post("/api/chat", json={"question": "What is support?"})
    assert r.status_code == 503 and "GEMINI_API_KEY" in r.json()["detail"]
    assert c.get("/api/config").json()["chat_ready"] is False


def test_chat_blocks_promise_wording(fake, monkeypatch):
    from app import chat

    class R:
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "This is a sure shot, buy now."}]}}]}

    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(chat.httpx, "post", lambda *a, **k: R())
    assert "sure shot" not in chat.ask("Should I buy?").lower()


def test_dictionary_covers_terms_and_is_plain():
    from app.glossary import GLOSSARY
    terms = {g["term"] for g in GLOSSARY}
    for must in ("Support", "Resistance", "Stop-loss", "Lower highs and lower lows", "P/E", "ATR", "Promoter pledge"):
        assert must in terms
    for g in GLOSSARY:
        assert g["meaning"] and g["match"] and not explain.find_banned(g["meaning"])
