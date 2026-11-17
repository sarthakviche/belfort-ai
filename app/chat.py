"""Ask-a-question chat: one plain call to Google's Gemini API. No retrieval, no tools.

Set GEMINI_API_KEY (and optionally GEMINI_MODEL) in the environment or in a .env file.
The page sends the question, the last few turns and a short text summary of the report on screen.
"""
import os

import httpx

from .analysis.explain import find_banned

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-flash-latest"

SYSTEM = """You are the helper inside a stock research app for Indian (NSE) retail traders, many of them beginners.
Explain terms, charts, company figures and the app's own report in short, plain sentences. Define any jargon you use.
Rules you must follow:
- Never tell the user to buy, sell or hold any stock, and never give price targets or predictions of your own.
- Never promise or imply returns. Markets are uncertain; say so when relevant.
- If asked "should I buy", explain what the report's label and checks mean and what the user would need to decide for
  themselves (position size, stop-loss, how much they can afford to lose). The decision is theirs.
- Use only the report summary provided for facts about the stock on screen. If a figure is not there, say you do not
  have it. Do not invent numbers.
- You are not a SEBI-registered adviser. Keep answers under about 150 words unless asked for more detail."""


class ChatError(Exception):
    pass


def configured() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


def ask(question: str, history: list[dict] | None = None, context: str = "") -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ChatError("Chat is not set up. Add GEMINI_API_KEY to the .env file in the project folder and restart the app.")
    contents = []
    for turn in (history or [])[-6:]:
        role = "model" if turn.get("role") == "model" else "user"
        text = str(turn.get("text", ""))[:2000]
        if text:
            contents.append({"role": role, "parts": [{"text": text}]})
    prompt = question.strip()[:2000]
    if context:
        prompt = f"Report currently on the user's screen:\n{context[:6000]}\n\nUser question: {prompt}"
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    body = {"system_instruction": {"parts": [{"text": SYSTEM}]}, "contents": contents,
            "generationConfig": {"temperature": 0.3, "maxOutputTokens": 800}}
    model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL)
    try:
        r = httpx.post(URL.format(model=model), headers={"x-goog-api-key": key}, json=body, timeout=40.0)
    except httpx.HTTPError:
        raise ChatError("Could not reach the Gemini service. Check your internet connection and try again.")
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise ChatError(f"Gemini returned an error ({r.status_code}). {msg[:200]}".strip())
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
        answer = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError):
        raise ChatError("Gemini gave no answer to that question. Try rephrasing it.")
    if not answer:
        raise ChatError("Gemini gave no answer to that question. Try rephrasing it.")
    if find_banned(answer):
        return ("I can't answer that the way it came out, because the reply used promise-style wording this app does not allow. "
                "I can explain what the label, the checks or any term on the screen mean.")
    return answer
