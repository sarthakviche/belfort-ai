"""Web app: JSON API plus the static front end.

Run:  python -m uvicorn app.main:app --port 8765
Set ACCESS_CODES="code1,code2" to require an access code from every user.
"""
import logging
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from fastapi.staticfiles import StaticFiles

from . import chat, screens
from .analysis.pipeline import analyze, nse, pattern_stats
from .glossary import GLOSSARY
from .config import DISCLAIMER, STYLES
from .data.providers import DataError
from .data.universe import UNIVERSE

log = logging.getLogger("analyst")
app = FastAPI(title="Belfort AI", docs_url=None, redoc_url=None)


def _codes() -> set[str]:
    return {c.strip() for c in os.environ.get("ACCESS_CODES", "").split(",") if c.strip()}


def require_access(x_access_code: str | None = Header(default=None)):
    codes = _codes()
    if codes and x_access_code not in codes:
        raise HTTPException(status_code=401, detail="A valid access code is required.")


@app.get("/api/config")
def config():
    return {"requires_code": bool(_codes()), "disclaimer": DISCLAIMER,
            "styles": [{"key": s.key, "name": s.name, "holds": s.holds} for s in STYLES.values()],
            "universe": UNIVERSE, "glossary": GLOSSARY, "chat_ready": chat.configured()}


@app.get("/api/search", dependencies=[Depends(require_access)])
def api_search(q: str = Query("", max_length=60)):
    try:
        return {"results": nse.search(q)}
    except Exception:
        return {"results": []}


@app.get("/api/screens", dependencies=[Depends(require_access)])
def api_screens():
    return screens.get()


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list, max_length=12)
    context: str = Field(default="", max_length=8000)


@app.post("/api/chat", dependencies=[Depends(require_access)])
def api_chat(body: ChatIn):
    try:
        return {"answer": chat.ask(body.question, body.history, body.context)}
    except chat.ChatError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/api/analyze", dependencies=[Depends(require_access)])
def api_analyze(symbol: str = Query(..., max_length=60), style: str = "swing",
                capital: float = Query(100000, gt=0, le=1e12), risk_pct: float = Query(1.0, gt=0, le=100),
                stop: float | None = Query(None, gt=0), entry: float | None = Query(None, gt=0)):
    try:
        return analyze(symbol, style, capital, risk_pct, stop, entry)
    except DataError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        log.exception("analysis failed for %s", symbol)
        raise HTTPException(status_code=502, detail="The analysis could not be completed. The data source may be "
                                                    "unavailable; try again in a minute.")


@app.get("/api/pattern-stats", dependencies=[Depends(require_access)])
def api_stats():
    return pattern_stats()


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
