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

memory = {}  # ticker → state dict

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

# ============================
#  PARSER Z BLOKADĄ TICKERA
# ============================
def parse_piece(text: str, existing_ticker=None):
    t = text.lower()
    out = {}

    # 🔥 BLOKADA TICKERA — jeśli już istnieje, nie szukamy nowego
    if existing_ticker:
        out["ticker"] = existing_ticker
    else:
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

# ============================
#  LOGIKA 4.5+
# ============================
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

# ============================
#  ENDPOINT 6.5 PRO
# ============================
@app.post("/voice-parse")
def voice_parse(req: VoiceRequest):

    # najpierw próbujemy znaleźć ticker w tekście
    temp_ticker = extract_ticker(req.text)

    # jeśli ticker istnieje w pamięci → używamy jego kontekstu
    state = memory.get(temp_ticker) if temp_ticker else None

    # jeśli istnieje kontekst → blokujemy ticker
    existing_ticker = state["ticker"] if state else None

    # parsujemy tekst z blokadą tickera
    piece = parse_piece(req.text, existing_ticker=existing_ticker)

    ticker = piece.get("ticker")

    # jeśli nadal brak tickera → zwracamy pusty szkielet
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
            "signal": None,
            "comment": "Brak tickera — podaj nazwę spółki."
        }

    # pobieramy lub tworzymy kontekst
    state = memory.get(ticker)
    if state is None:
        state = empty_state()
        state["ticker"] = ticker
        memory[ticker] = state

    # aktualizacja stanu
    for key in ["interval","time","open","high","low","close","ma20","dema9","rsi","volume"]:
        if piece.get(key) is not None:
            state[key] = piece[key]

    # logika 4.5+
    sig, com = system_45_logic(state)
    if sig:
        state["signal"] = sig
        state["comment"] = com
    else:
        state["comment"] = "Czekam na brakujące dane…"

    return state
