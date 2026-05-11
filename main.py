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
    interval: str | None = None

def empty_state(ticker, interval):
    return {
        "ticker": ticker,
        "interval": interval,
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
        "after_price": None,
        "signal": None,
        "tp3": None,
        "comment": "Czekam na dane…",
    }

memory = {}
last_used_key = None

BAD_WORDS = {
    "o","l","h","c",
    "m",  # blokujemy pojedyncze "m"
    "ma","ma20","dema","dema9",
    "rsi","wolumen","volume","entry","usuń","usun",
    "open","low","high","close","cena",
    "m1","m5","m15","m30","h1","h4","d1","w1",
    "hi","haj","hai","hay","hał","hajh","haih",
    "loł","lowe","lołe","lołł","lołu","loło","lołej","loły",
    "bema","bema9","b ma","b ema",
    "clos","closs","closse","cloos","cloose","clołs","klołs","kloz","kloze"
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
        if re.fullmatch(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]{2,}", w_clean):
            return w.upper()
    return None

def extract_interval(t):
    if "m15" in t: return "M15"
    if "m5" in t: return "M5"
    if "m1" in t: return "M1"
    if "m30" in t: return "M30"
    return None

# ---------------------------------------------------------
# AUTOKOREKTA MA / DEMA
# ---------------------------------------------------------
def autocorrect_indicators(text: str):
    t = text.lower().strip()

    t = t.replace("e ma", "ma")
    t = t.replace("m a", "ma")
    t = t.replace("ema", "ma")

    t = t.replace("bema", "dema")
    t = t.replace("b ma", "dema")
    t = t.replace("b ema", "dema")
    t = t.replace("de ma", "dema")
    t = t.replace("deema", "dema")

    if t == "ma":
        return "ma20"
    if t == "dema":
        return "dema9"

    if t.startswith("ma "):
        return t.replace("ma ", "ma20 ")
    if t.startswith("dema "):
        return t.replace("dema ", "dema9 ")

    return t

def parse_piece(text: str):
    t = autocorrect_indicators(text.lower())
    out = {}

    if "usuń" in t or "usun" in t:
        out["delete"] = True

    m = re.search(r"\b(\d{1,2}:\d{2})\b", t)
    if m: out["time"] = m.group(1)

    m = re.search(r"entry\s*([\d\., ]+)", t)
    if m: out["entry"] = norm(m.group(1))

    m = re.search(r"\b(o|open)\s+([\d\., ]+)", t)
    if m: out["open"] = norm(m.group(2))

    m = re.search(r"\b(l|low)\s+([\d\., ]+)", t)
    if m: out["low"] = norm(m.group(2))

    for alias in ["loł","lowe","lołe","lołł","lołu","loło","lołej","loły"]:
        m = re.search(rf"\b{alias}\s+([\d\., ]+)", t)
        if m: out["low"] = norm(m.group(1))

    m = re.search(r"\b(h|high)\s+([\d\., ]+)", t)
    if m: out["high"] = norm(m.group(2))

    for alias in ["hi","haj","hai","hay","hał","hajh","haih"]:
        m = re.search(rf"\b{alias}\s+([\d\., ]+)", t)
        if m: out["high"] = norm(m.group(1))

    m = re.search(r"ma20\s*([\d\., ]+)", t)
    if m: out["ma20"] = norm(m.group(1))

    m = re.search(r"dema9\s*([\d\., ]+)", t)
    if m: out["dema9"] = norm(m.group(1))

    for alias in ["bema9","bema","b ma","b ema"]:
        m = re.search(rf"\b{alias}\s*([\d\., ]+)", t)
        if m: out["dema9"] = norm(m.group(1))

    m = re.search(r"rsi\s*([\d\., ]+)", t)
    if m: out["rsi"] = norm(m.group(1))

    m = re.search(r"(wolumen|volume)\s*([\d\., ]+)", t)
    if m: out["volume"] = norm(m.group(2))

    m = re.search(r"(close|cena)\s+([\d\., ]+)", t)
    if m: out["close"] = norm(m.group(2))

    for alias in ["clos","closs","closse","cloos","cloose","clołs","klołs","kloz","kloze"]:
        m = re.search(rf"\b{alias}\s+([\d\., ]+)", t)
        if m: out["close"] = norm(m.group(1))

    m = re.search(r"(po godzinie|after|after price|after hours)\s*([\d\., ]+)", t)
    if m: out["after_price"] = norm(m.group(2))

    out["interval"] = extract_interval(t)
    return out

# ---------------------------------------------------------
# SYSTEM 7.0 — sygnały
# ---------------------------------------------------------
def system_45_logic(d):
    o, c, ma, de = d["open"], d["close"], d["ma20"], d["dema9"]
    if None in (o, c, ma, de):
        return None, "Brak kompletu danych do sygnału."

    if c > ma and c > de:
        return "BUY", "Cena powyżej MA20 i DEMA9 — trend wzrostowy."

    if c < ma and c < de:
        return "SELL", "Cena poniżej MA20 i DEMA9 — trend spadkowy."

    if c > ma and c <= de * 1.002:
        return "PRAWIE BUY", "Cena nad MA20, blisko DEMA9 — prawie sygnał BUY."

    if c < ma and c >= de * 0.998:
        return "PRAWIE SELL", "Cena pod MA20, blisko DEMA9 — prawie sygnał SELL."

    if (de < c < ma) or (ma < c < de):
        return "RESET", "Cena wróciła do środka — reset trendu."

    if abs(c - ma) < 0.001 * c or abs(c - de) < 0.001 * c:
        return "PRAWIE RESET", "Cena bardzo blisko środka — prawie reset."

    return "CZEKAJ", "Brak wyraźnego sygnału."

# ---------------------------------------------------------
# DYNAMICZNE TP3
# ---------------------------------------------------------
def dynamic_tp3(d):
    c, ma, de = d["close"], d["ma20"], d["dema9"]
    if None in (c, ma, de):
        return None

    trend_strength = abs(ma - de)
    mid = (ma + de) / 2
    distance = abs(c - mid)
    tp3 = distance + trend_strength

    if d["signal"] == "BUY":
        return round(c + tp3, 2)
    if d["signal"] == "SELL":
        return round(c - tp3, 2)

    return None

# ---------------------------------------------------------
# KORELACJA KGHM ↔ COPPER
# ---------------------------------------------------------
def apply_correlation(memory, state, ticker):
    if ticker != "KGHM":
        return state

    if "COPPER|M5" not in memory:
        return state

    copper = memory["COPPER|M5"]
    sig = copper.get("signal")

    if not sig:
        return state

    if sig == "BUY":
        state["comment"] += " | Korelacja: Copper BUY — wzmocnienie sygnału."
    elif sig == "SELL":
        state["comment"] += " | Korelacja: Copper SELL — ryzyko spadku."
    elif sig == "PRAWIE BUY":
        state["comment"] += " | Korelacja: Copper prawie BUY."
    elif sig == "PRAWIE SELL":
        state["comment"] += " | Korelacja: Copper prawie SELL."
    elif sig == "RESET":
        state["comment"] += " | Korelacja: Copper reset — możliwa zmiana kierunku."

    return state

# ---------------------------------------------------------
# GŁÓWNY ENDPOINT
# ---------------------------------------------------------
@app.post("/voice-parse")
def voice_parse(req: VoiceRequest):
    global last_used_key

    text = req.text.strip()
    piece = parse_piece(text)

    ticker = extract_ticker(text)
    interval = piece.get("interval")

    if ticker:
        if not interval:
            interval = "M5"
        last_used_key = f"{ticker}|{interval}"

    if not ticker:
        if not last_used_key:
            return {"ticker": None, "comment": "Brak tickera — podaj nazwę spółki."}
        ticker, interval = last_used_key.split("|")

    key = f"{ticker}|{interval}"

    if piece.get("delete"):
        if key in memory:
            del memory[key]
        if last_used_key == key:
            last_used_key = None
        return {"ticker": ticker, "interval": interval, "deleted": True}

    if key not in memory:
        memory[key] = empty_state(ticker, interval)

    state = memory[key]

    for k in ["time","open","high","low","close","ma20","dema9","rsi","volume","after_price"]:
        if piece.get(k) is not None:
            state[k] = piece[k]

    if piece.get("entry") is not None:
        if piece["entry"] == 0:
            state["entry"] = None
            state["signal"] = "CZEKAJ"
            state["comment"] = "Pozycja zamknięta."
        else:
            state["entry"] = piece["entry"]

    sig, com = system_45_logic(state)
    state["signal"] = sig
    state["comment"] = com
    state["tp3"] = dynamic_tp3(state)

    state = apply_correlation(memory, state, ticker)

    last_used_key = key
    return state

# ---------------------------------------------------------
# DELETE ENDPOINT
# ---------------------------------------------------------
@app.post("/voice-parse/delete")
def delete_ticker(req: DeleteRequest):
    global last_used_key
    key = f"{req.ticker.upper()}|{req.interval}"
    if key in memory:
        del memory[key]
        if last_used_key == key:
            last_used_key = None
        return {"status": "deleted", "key": key}
    return {"status": "not_found", "key": key}
