from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class VoiceRequest(BaseModel):
    text: str

class DeleteRequest(BaseModel):
    ticker: str

def empty_state():
    return {
        "ticker": None,
        "interval": None,
        "time": None,
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "ma20": None,
        "dema9": None,
        "rsi": None,
        "volume": None,
        "entry": None,
        "signal": None,
        "comment": "Czekam na dane…",
    }

memory = {}
last_ticker = None  # 🔥 globalny aktywny ticker

BAD_WORDS = {
    "o","l","h","c",
    "ma","ma20","dema","dema9",
    "rsi","wolumen","entry","usuń","usun",
    "m1","m5","m15","m30","h1","h4","d1","w1"
}

def norm(x):
    if not x:
        return None
    x = x.replace(" ", "").replace(",", ".")
    try:
        return float(x)
    except:
        return None

def extract_ticker(text: str):
    for w in text.split():
        w_clean = w.lower()
        if w_clean in BAD_WORDS:
            continue
        if re.fullmatch(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+", w_clean):
            return w.upper()
    return None

def parse_piece(text: str, existing_ticker=None):
    t = text.lower()
    out = {}

    if "usuń" in t or "usun" in t:
        out["delete"] = True

    if existing_ticker:
        out["ticker"] = existing_ticker
    else:
        tick = extract_ticker(text)
        if tick:
            out["ticker"] = tick

    m = re.search(r"\b(\d{1,2}:\d{2})\b", t)
    if m:
        out["time"] = m.group(1)

    m = re.search(r"entry\s*([\d\., ]+)", t)
    if m:
        out["entry"] = norm(m.group(1))

    m = re.search(r"\b(o|open)\s+([\d\., ]+)", t)
    if m:
        out["open"] = norm(m.group(2))

    m = re.search(r"\b(l|low)\s+([\d\., ]+)", t)
    if m:
        out["low"] = norm(m.group(2))

    m = re.search(r"\b(h|high)\s+([\d\., ]+)", t)
    if m:
        out["high"] = norm(m.group(2))

    m = re.search(r"\b(c|close|cena)\s+([\d\., ]+)", t)
    if m:
        out["close"] = norm(m.group(2))

    m = re.search(r"ma20\s*([\d\., ]+)", t)
    if m:
        out["ma20"] = norm(m.group(1))

    m = re.search(r"dema9\s*([\d\., ]+)", t)
    if m:
        out["dema9"] = norm(m.group(1))

    m = re.search(r"rsi\s*([\d\., ]+)", t)
    if m:
        out["rsi"] = norm(m.group(1))

    m = re.search(r"wolumen\s*([\d\., ]+)", t)
    if m:
        out["volume"] = norm(m.group(1))

    if "m15" in t:
        out["interval"] = "M15"
    elif "m5" in t:
        out["interval"] = "M5"
    elif "m1" in t:
        out["interval"] = "M1"
    elif "m30" in t:
        out["interval"] = "M30"

    return out

def system_45_logic(d):
    o = d.get("open")
    c = d.get("close")
    ma = d.get("ma20")
    de = d.get("dema9")

    if None in (o, c, ma, de):
        return None, "Brak kompletu danych do sygnału."

    if c > ma and c > de:
        return "BUY", "Cena powyżej MA20 i DEMA9 — trend wzrostowy."
    elif c < ma and c < de:
        return "SELL", "Cena poniżej MA20 i DEMA9 — trend spadkowy."
    else:
        return "CZEKAJ", "Brak wyraźnego sygnału (strefa przejściowa)."

@app.post("/voice-parse")
def voice_parse(req: VoiceRequest):
    global last_ticker

    text = req.text
    t_low = text.lower()

    # 1. Spróbuj wyciągnąć nowy ticker z wypowiedzi
    candidate = extract_ticker(text)

    # 2. Jeśli jest kandydat → traktujemy to jako świadome podanie tickera
    if candidate:
        ticker = candidate
        last_ticker = ticker
    else:
        # 3. Brak tickera w tekście → użyj ostatniego aktywnego
        ticker = last_ticker

    piece = parse_piece(text, existing_ticker=ticker)

    # obsługa "usuń" (głosowe)
    if piece.get("delete") and ticker:
        if ticker in memory:
            del memory[ticker]
        if last_ticker == ticker:
            last_ticker = None
        return {"ticker": ticker, "deleted": True, "comment": f"Usunięto {ticker}"}

    if not ticker:
        return {
            "ticker": None,
            "interval": None,
            "time": None,
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "ma20": None,
            "dema9": None,
            "rsi": None,
            "volume": None,
            "entry": None,
            "signal": None,
            "comment": "Brak tickera — podaj nazwę spółki."
        }

    state = memory.get(ticker)
    if state is None:
        state = empty_state()
        state["ticker"] = ticker
        memory[ticker] = state

    for key in ["interval","time","open","high","low","close","ma20","dema9","rsi","volume"]:
        if piece.get(key) is not None:
            state[key] = piece[key]

    if piece.get("entry") is not None:
        if piece["entry"] == 0:
            state["entry"] = None
            state["signal"] = "CZEKAJ"
            state["comment"] = "Pozycja zamknięta (entry = 0)"
        else:
            state["entry"] = piece["entry"]

    sig, com = system_45_logic(state)
    if sig:
        state["signal"] = sig
        if "Pozycja zamknięta" not in state["comment"]:
            state["comment"] = com
    else:
        if "Pozycja zamknięta" not in state["comment"]:
            state["comment"] = "Czekam na brakujące dane…"

    return state

@app.post("/voice-parse/delete")
def delete_ticker(req: DeleteRequest):
    global last_ticker
    t = req.ticker.upper()
    if t in memory:
        del memory[t]
        if last_ticker == t:
            last_ticker = None
        return {"status": "deleted", "ticker": t}
    return {"status": "not_found", "ticker": t}
