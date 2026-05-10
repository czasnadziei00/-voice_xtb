from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re

app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class VoiceRequest(BaseModel):
    text: str

# ============================
#  PAMIĘĆ 6.5 PRO — MULTI‑TICKER
# ============================
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
        "signal": None,
        "comment": "Czekam na dane…",
    }

memory = {}  # ticker -> state dict


BAD_WORDS = {
    "o","l","h","c",
    "ma","ma20","dema","dema9",
    "rsi","wolumen",
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

def parse_piece(text: str):
    t = text.lower()
    out = {}

    # TICKER
    tick = extract_ticker(text)
    if tick:
        out["ticker"] = tick

    # GODZINA
    m = re.search(r"\b(\d{1,2}:\d{2})\b", t)
    if m:
        out["time"] = m.group(1)

    # OPEN
    m = re.search(r"\b(o|oh|ou|oo|open)\s+([\d\., ]+)", t)
    if m:
        out["open"] = norm(m.group(2))

    # LOW
    m = re.search(r"\b(l|el|al|ł|elle|low)\s+([\d\., ]+)", t)
    if m:
        out["low"] = norm(m.group(2))

    # HIGH
    m = re.search(r"\b(h|ha|he|hi|high)\s+([\d\., ]+)", t)
    if m:
        out["high"] = norm(m.group(2))

    # CLOSE
    m = re.search(r"\b(c|ce|se|si|ci|see|cena)\s+([\d\., ]+)", t)
    if m:
        out["close"] = norm(m.group(2))

    # hi 185 → HIGH
    m = re.search(r"\bhi\s*([\d\., ]+)", t)
    if m:
        out["high"] = norm(m.group(1))

    # MA20
    m = re.search(r"\bma\s*([\d\., ]+)", t)
    if m:
        out["ma20"] = norm(m.group(1))
    m = re.search(r"ma20\s*([\d\., ]+)", t)
    if m:
        out["ma20"] = norm(m.group(1))

    # DEMA9
    m = re.search(r"\bdema\s*([\d\., ]+)", t)
    if m:
        out["dema9"] = norm(m.group(1))
    m = re.search(r"dema9\s*([\d\., ]+)", t)
    if m:
        out["dema9"] = norm(m.group(1))

    # RSI
    m = re.search(r"rsi\s*([\d\., ]+)", t)
    if m:
        out["rsi"] = norm(m.group(1))

    # WOLUMEN
    m = re.search(r"wolumen\s*([\d\., ]+)", t)
    if m:
        out["volume"] = norm(m.group(1))

    # INTERWAŁY
    if "m15" in t or "m 15" in t:
        out["interval"] = "M15"
    elif "m5" in t or "m 5" in t:
        out["interval"] = "M5"
    elif "m1" in t or "m 1" in t:
        out["interval"] = "M1"
    elif "m30" in t or "m 30" in t:
        out["interval"] = "M30"

    # Chrome h1/h5/h15/h30
    if re.search(r"\bh1\b", t) and not out.get("interval"):
        out["interval"] = "M1"
    if re.search(r"\bh5\b", t) and not out.get("interval"):
        out["interval"] = "M5"
    if re.search(r"\bh15\b", t) and not out.get("interval"):
        out["interval"] = "M15"
    if re.search(r"\bh30\b", t) and not out.get("interval"):
        out["interval"] = "M30"

    # słowne
    if "jedna minuta" in t or "minuta" in t:
        out["interval"] = "M1"
    if "pięć minut" in t:
        out["interval"] = "M5"
    if "piętnaście minut" in t:
        out["interval"] = "M15"
    if "trzydzieści minut" in t:
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

def is_complete(d):
    return all([
        d.get("ticker"),
        d.get("interval"),
        d.get("time"),
        d.get("open") is not None,
        d.get("high") is not None,
        d.get("low") is not None,
        d.get("close") is not None,
        d.get("ma20") is not None,
        d.get("dema9") is not None,
        d.get("rsi") is not None,
        d.get("volume") is not None,
    ])

# ============================
#  ENDPOINT 6.5 PRO
# ============================
@app.post("/voice-parse")
def voice_parse(req: VoiceRequest):
    piece = parse_piece(req.text)

    ticker = piece.get("ticker")
    if not ticker:
        # brak tickera → frontend 6.5 to zignoruje
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
            "signal": None,
            "comment": "Brak tickera — podaj nazwę spółki."
        }

    # stan dla danego tickera
    state = memory.get(ticker)
    if state is None:
        state = empty_state()
        state["ticker"] = ticker
        memory[ticker] = state

    # aktualizacja stanu
    if piece.get("interval"):
        state["interval"] = piece["interval"]
    if piece.get("time"):
        state["time"] = piece["time"]

    for key in ["open","high","low","close","ma20","dema9","rsi","volume"]:
        if piece.get(key) is not None:
            state[key] = piece[key]

    # logika 4.5+
    sig, com = system_45_logic(state)
    if sig:
        state["signal"] = sig
        state["comment"] = com
    else:
        state["comment"] = "Czekam na brakujące dane…"

    # niczego nie resetujemy — multi‑ticker trzyma kontekst
    out = {
        "ticker": state["ticker"],
        "interval": state["interval"],
        "time": state["time"],
        "open": state["open"],
        "high": state["high"],
        "low": state["low"],
        "close": state["close"],
        "ma20": state["ma20"],
        "dema9": state["dema9"],
        "rsi": state["rsi"],
        "volume": state["volume"],
        "signal": state["signal"],
        "comment": state["comment"],
    }

    return out
