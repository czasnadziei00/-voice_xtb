from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re

app = FastAPI()

# 🔥 CORS — MUSI BYĆ
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # pozwala na 127.0.0.1:5500
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class VoiceRequest(BaseModel):
    text: str


# -----------------------------
# 🔥 FUNKCJE POMOCNICZE
# -----------------------------

def norm(x):
    if not x:
        return None
    x = x.replace(" ", "").replace(",", ".")
    try:
        return float(x)
    except:
        return None


INTERVALS = ["M1","M5","M15","M30","H1","H4","D1","W1"]

BAD_WORDS = {
    "o","l","h","c",
    "ma","ma20","dema","dema9",
    "rsi","wolumen",
    "m1","m5","m15","m30","h1","h4","d1","w1"
}

def extract_ticker(text):
    for w in text.split():
        w_clean = w.lower()
        if w_clean in BAD_WORDS:
            continue
        if re.fullmatch(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+", w_clean):
            return w.upper()
    return None


# -----------------------------
# 🔥 PARSER GŁOSU
# -----------------------------

def parse_voice(text: str):
    t = text.lower()

    data = {
        "ticker": extract_ticker(text),
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

    # interval
    for iv in INTERVALS:
        if iv.lower() in t:
            data["interval"] = iv
            break

    # time
    m = re.search(r"\b(\d{1,2}:\d{2})\b", t)
    if m:
        data["time"] = m.group(1)

    # OLHC
    m = re.search(r"\bo\s+([\d\., ]+)", t)
    if m: data["open"] = norm(m.group(1))

    m = re.search(r"\bl\s+([\d\., ]+)", t)
    if m: data["low"] = norm(m.group(1))

    m = re.search(r"\bh\s+([\d\., ]+)", t)
    if m: data["high"] = norm(m.group(1))

    m = re.search(r"\bc\s*([\d\., ]+)", t)
    if m: data["close"] = norm(m.group(1))

    # MA20
    m = re.search(r"ma20\s*([\d\., ]+)", t)
    if m: data["ma20"] = norm(m.group(1))

    # DEMA9
    m = re.search(r"dema9\s*([\d\., ]+)", t)
    if m: data["dema9"] = norm(m.group(1))

    # RSI
    m = re.search(r"rsi\s*([\d\., ]+)", t)
    if m: data["rsi"] = norm(m.group(1))

    # Volume
    m = re.search(r"wolumen\s*([\d\., ]+)", t)
    if m: data["volume"] = norm(m.group(1))

    return data


# -----------------------------
# 🔥 LOGIKA SYSTEMU 4.5+
# -----------------------------

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


# -----------------------------
# 🔥 JEDYNY POPRAWNY ENDPOINT
# -----------------------------

@app.post("/voice-parse")
def voice_parse(req: VoiceRequest):
    parsed = parse_voice(req.text)
    signal, comment = system_45_logic(parsed)
    parsed["signal"] = signal
    parsed["comment"] = comment
    return parsed
