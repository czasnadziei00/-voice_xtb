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

# 🔥 BUFOR DANYCH (system 4.6)
current = {
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
    "volume": None
}

INTERVALS = ["M1","M5","M15","M30","H1","H4","D1","W1"]

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

def extract_ticker(text):
    for w in text.split():
        w_clean = w.lower()
        if w_clean in BAD_WORDS:
            continue
        if re.fullmatch(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+", w_clean):
            return w.upper()
    return None

def parse_piece(text):
    t = text.lower()
    out = {}

    # ticker
    tick = extract_ticker(text)
    if tick:
        out["ticker"] = tick

    # interval
    for iv in INTERVALS:
        if iv.lower() in t:
            out["interval"] = iv
            break

    # time
    m = re.search(r"\b(\d{1,2}:\d{2})\b", t)
    if m:
        out["time"] = m.group(1)

    # OLHC
    m = re.search(r"\bo\s+([\d\., ]+)", t)
    if m: out["open"] = norm(m.group(1))

    m = re.search(r"\bl\s+([\d\., ]+)", t)
    if m: out["low"] = norm(m.group(1))

    m = re.search(r"\bh\s+([\d\., ]+)", t)
    if m: out["high"] = norm(m.group(1))

    m = re.search(r"\bc\s*([\d\., ]+)", t)
    if m: out["close"] = norm(m.group(1))

    # MA20
    m = re.search(r"ma20\s*([\d\., ]+)", t)
    if m: out["ma20"] = norm(m.group(1))

    # DEMA9
    m = re.search(r"dema9\s*([\d\., ]+)", t)
    if m: out["dema9"] = norm(m.group(1))

    # RSI
    m = re.search(r"rsi\s*([\d\., ]+)", t)
    if m: out["rsi"] = norm(m.group(1))

    # Volume
    m = re.search(r"wolumen\s*([\d\., ]+)", t)
    if m: out["volume"] = norm(m.group(1))

    return out

def system_45_logic(d):
    o = d.get("open")
    c = d.get("close")
    ma = d.get("ma20")
    de = d.get("dema9")

    if None in (o, c, ma, de):
        return None, "Brak danych do sygnału."

    if c > ma and c > de:
        return "BUY", "Cena powyżej MA20 i DEMA9 — trend wzrostowy."
    elif c < ma and c < de:
        return "SELL", "Cena poniżej MA20 i DEMA9 — trend spadkowy."
    else:
        return "CZEKAJ", "Brak wyraźnego sygnału."

def is_complete(d):
    return all([
        d["ticker"],
        d["interval"],
        d["time"],
        d["open"],
        d["high"],
        d["low"],
        d["close"],
        d["ma20"],
        d["dema9"],
        d["rsi"],
        d["volume"]
    ])

@app.post("/voice-parse")
def voice_parse(req: VoiceRequest):
    global current

    piece = parse_piece(req.text)

    # 🔥 uzupełniamy bufor
    for k, v in piece.items():
        if v is not None:
            current[k] = v

    # 🔥 jeśli komplet → zwracamy i czyścimy
    if is_complete(current):
        signal, comment = system_45_logic(current)
        out = current.copy()
        out["signal"] = signal
        out["comment"] = comment

        # czyścimy bufor
        current = {k: None for k in current}

        return out

    # 🔥 jeśli niekompletne → zwracamy tylko to, co mamy
    return {**current, "signal": None, "comment": "Czekam na brakujące dane…"}
