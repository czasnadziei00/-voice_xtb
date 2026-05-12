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

# ---------------------------------------------------------
# MODELE
# ---------------------------------------------------------
class VoiceRequest(BaseModel):
    text: str

class DeleteRequest(BaseModel):
    ticker: str
    interval: str | None = None

# ---------------------------------------------------------
# STAN PUSTY
# ---------------------------------------------------------
def empty_state(ticker, interval):
    return {
        "ticker": ticker,
        "interval": interval,
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
        "tp3": None,
        "comment": "Czekam na dane…",
    }

memory = {}
last_used_key = None

# ---------------------------------------------------------
# FUNKCJE POMOCNICZE
# ---------------------------------------------------------
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
        if re.fullmatch(r"[A-Za-z0-9]{2,}", w):
            return w.upper()
    return None

def extract_interval(t: str):
    t = t.replace(" ", "").lower()
    if "m15" in t: return "M15"
    if "m5" in t: return "M5"
    if "m1" in t: return "M1"
    if "m30" in t: return "M30"
    if "h1" in t: return "H1"
    if "h4" in t: return "H4"
    if "d1" in t: return "D1"
    return None

# ---------------------------------------------------------
# PARSER — CZYSTY
# ---------------------------------------------------------
def parse_piece(text: str):
    t = text.lower()
    out = {}

    # entry
    m = re.search(r"entry\s*([\d\.,]+)", t)
    if m: out["entry"] = norm(m.group(1))

    # open
    m = re.search(r"open\s*([\d\.,]+)", t)
    if m: out["open"] = norm(m.group(1))

    # high
    m = re.search(r"high\s*([\d\.,]+)", t)
    if m: out["high"] = norm(m.group(1))

    # low
    m = re.search(r"low\s*([\d\.,]+)", t)
    if m: out["low"] = norm(m.group(1))

    # close
    m = re.search(r"close\s*([\d\.,]+)", t)
    if m: out["close"] = norm(m.group(1))

    # ma20
    m = re.search(r"ma20\s*([\d\.,]+)", t)
    if m: out["ma20"] = norm(m.group(1))

    # dema9
    m = re.search(r"dema9\s*([\d\.,]+)", t)
    if m: out["dema9"] = norm(m.group(1))

    # rsi
    m = re.search(r"rsi\s*([\d\.,]+)", t)
    if m: out["rsi"] = norm(m.group(1))

    # volume
    m = re.search(r"(volume|wolumen)\s*([\d\.,]+)", t)
    if m: out["volume"] = norm(m.group(2))

    out["interval"] = extract_interval(t)
    return out

# ---------------------------------------------------------
# DYNAMICZNE MOMENTUM
# ---------------------------------------------------------
def compute_momentum(d):
    ma = d["ma20"]
    de = d["dema9"]
    if ma is None or de is None:
        return None, None, None

    diff = de - ma
    direction = "UP" if diff > 0 else "DOWN" if diff < 0 else "FLAT"
    strength = abs(diff) / ma if ma != 0 else 0.0
    return diff, direction, strength

# ---------------------------------------------------------
# SYSTEM 4.5+ LOGIC Z MOMENTUM
# ---------------------------------------------------------
def system_45_logic(d):
    o, c, ma, de = d["open"], d["close"], d["ma20"], d["dema9"]
    if None in (o, c, ma, de):
        return None, "Brak kompletu danych do sygnału."

    diff, direction, strength = compute_momentum(d)

    # SELL — momentum w dół, cena pod wszystkim
    if c < ma and c < de and direction == "DOWN":
        if abs(c - ma)/c < 0.0015 or abs(c - de)/c < 0.0015:
            return "CZEKAJ DO BUY", "Momentum spadkowe, ale cena blisko średnich — możliwy zwrot w górę."
        return "SELL", "Momentum spadkowe — cena poniżej MA20 i DEMA9."

    # BUY — momentum w górę, cena nad wszystkim
    if c > ma and c > de and direction == "UP":
        if abs(c - ma)/c < 0.0015 or abs(c - de)/c < 0.0015:
            return "CZEKAJ DO SELL", "Momentum wzrostowe, ale cena blisko średnich — możliwy zwrot w dół."
        return "BUY", "Momentum wzrostowe — cena powyżej MA20 i DEMA9."

    # CZEKAJ DO BUY — pullback do DEMA9 przy momentum UP
    if direction == "UP" and c < de and c > ma:
        return "CZEKAJ DO BUY", "Pullback do DEMA9 przy rosnącym momentum — przygotuj się na BUY."

    # CZEKAJ DO SELL — pullback do DEMA9 przy momentum DOWN
    if direction == "DOWN" and c > de and c < ma:
        return "CZEKAJ DO SELL", "Pullback do DEMA9 przy spadającym momentum — przygotuj się na SELL."

    # PRAWIE BUY — cena bardzo blisko DEMA9 przy momentum UP
    if direction == "UP" and c >= ma and abs(c - de)/c < 0.002:
        return "PRAWIE BUY", "Cena bardzo blisko DEMA9 przy rosnącym momentum — prawie BUY."

    # PRAWIE SELL — cena bardzo blisko DEMA9 przy momentum DOWN
    if direction == "DOWN" and c <= ma and abs(c - de)/c < 0.002:
        return "PRAWIE SELL", "Cena bardzo blisko DEMA9 przy spadającym momentum — prawie SELL."

    # RESET — momentum zmienia stronę względem MA20
    if (de > ma and c < ma) or (de < ma and c > ma):
        return "RESET", "Momentum po przeciwnej stronie MA20 niż cena — reset trendu."

    # PRAWIE RESET — wszystko bardzo blisko MA20
    if abs(c - ma)/c < 0.001 and abs(de - ma)/ma < 0.001:
        return "PRAWIE RESET", "Cena i DEMA9 bardzo blisko MA20 — prawie reset."

    return "CZEKAJ", "Brak wyraźnego sygnału — momentum niejednoznaczne."

# ---------------------------------------------------------
# TP3 — Z UWZGLĘDNIENIEM MOMENTUM
# ---------------------------------------------------------
def dynamic_tp3(d):
    c, ma, de = d["close"], d["ma20"], d["dema9"]
    if None in (c, ma, de):
        return None

    diff, direction, strength = compute_momentum(d)
    mid = (ma + de) / 2
    dist = abs(c - mid)

    # bazowy TP
    tp = dist + abs(ma - de)

    # wzmocnienie TP przy silnym momentum
    if strength is not None:
        if strength > 0.01:
            tp *= 1.3
        elif strength > 0.005:
            tp *= 1.15

    if d["signal"] == "BUY":
        return round(c + tp, 2)
    if d["signal"] == "SELL":
        return round(c - tp, 2)
    return None

# ---------------------------------------------------------
# WIDEŁKI
# ---------------------------------------------------------
def apply_widelki(state):
    sig = state["signal"]
    lo, hi = state["low"], state["high"]

    if sig in ("BUY", "PRAWIE BUY", "CZEKAJ DO BUY") and lo is not None and hi is not None:
        rng = hi - lo
        state["low"] = round(lo + rng*0.20, 2)
        state["high"] = round(lo + rng*0.35, 2)
    else:
        state["low"] = None
        state["high"] = None

    return state

# ---------------------------------------------------------
# BRAKUJĄCE POLA
# ---------------------------------------------------------
def missing_fields(d):
    req = ["open", "low", "high", "close", "ma20", "dema9"]
    return [k for k in req if d.get(k) is None]

# ---------------------------------------------------------
# KORELACJA
# ---------------------------------------------------------
def apply_correlation(memory, state, ticker):
    if ticker != "KGHM":
        return state
    if "COPPER|M5" not in memory:
        return state
    sig = memory["COPPER|M5"].get("signal")
    if sig:
        state["comment"] += f" | Korelacja: Copper {sig}"
    return state

# ---------------------------------------------------------
# RSI — DODATKOWY KOMENTARZ
# ---------------------------------------------------------
def apply_rsi_comment(state):
    rsi = state.get("rsi")
    if rsi is None:
        return state
    if rsi > 70:
        state["comment"] += " | RSI wysokie (przegrzanie)."
    elif rsi < 30:
        state["comment"] += " | RSI niskie (wyprzedanie)."
    return state

# ---------------------------------------------------------
# ENDPOINT
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
            return {"ticker": None, "comment": "Brak tickera."}
        ticker, interval = last_used_key.split("|")

    key = f"{ticker}|{interval}"

    if key not in memory:
        memory[key] = empty_state(ticker, interval)

    state = memory[key]

    # update fields
    for k in ["open","high","low","close","ma20","dema9","rsi","volume","entry"]:
        if piece.get(k) is not None:
            state[k] = piece[k]

    # entry = 0 → zamknięcie pozycji
    if piece.get("entry") is not None and piece["entry"] == 0:
        state["entry"] = None
        state["signal"] = "CZEKAJ"
        state["tp3"] = None
        state["comment"] = "Pozycja zamknięta."
        state["low"] = None
        state["high"] = None
        return state

    missing = missing_fields(state)
    if missing:
        state["signal"] = None
        state["comment"] = "Brakuje: " + ", ".join(missing)
        state["tp3"] = None
        state["low"] = None
        state["high"] = None
        return state

    sig, com = system_45_logic(state)
    state["signal"] = sig
    state["comment"] = com

    state["tp3"] = dynamic_tp3(state)
    state = apply_correlation(memory, state, ticker)
    state = apply_widelki(state)
    state = apply_rsi_comment(state)

    last_used_key = key
    return state

# ---------------------------------------------------------
# DELETE
# ---------------------------------------------------------
@app.post("/voice-parse/delete")
def delete_ticker(req: DeleteRequest):
    global last_used_key
    key = f"{req.ticker.upper()}|{req.interval}"
    if key in memory:
        del memory[key]
        if last_used_key == key:
            last_used_key = None
        return {"status": "deleted"}
    return {"status": "not_found"}
