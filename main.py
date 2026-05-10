from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Optional
import uvicorn

app = FastAPI()

# ====== CORS ======
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ====== MODELE ======

class VoiceRequest(BaseModel):
    text: str


# ====== POMOCNICZE ======

def parse_number(tokens, i):
    """Inteligentny parser liczb."""
    if i >= len(tokens):
        return None, i

    t = tokens[i].replace(",", ".")
    if t.replace(".", "").isdigit():
        return float(t), i + 1

    return None, i + 1


def empty_row():
    return {
        "open": None,
        "low": None,
        "high": None,
        "close": None,
        "ma20": None,
        "dema9": None,
        "rsi": None,
        "vwap": None,
        "volume": None,
    }


# ============================================================
#  LIVE — ANALIZA TERAZ (M5/M15/H1)
# ============================================================

def analyze_live(row: Dict) -> Dict:
    """Sygnały LIVE 4.5+ uproszczone."""
    close = row.get("close")
    ma20 = row.get("ma20")
    dema9 = row.get("dema9")
    rsi = row.get("rsi")

    if not close or not ma20 or not dema9 or not rsi:
        return {"signal": "CZEKAJ", "comment": "Brak pełnych danych."}

    if close > ma20 and close > dema9 and 55 <= rsi <= 70:
        return {"signal": "BUY", "comment": "Silny sygnał BUY."}

    if close > ma20 and 50 <= rsi < 55:
        return {"signal": "PRAWIE BUY", "comment": "PRAWIE BUY — brakuje trochę RSI."}

    if rsi > 75:
        return {"signal": "RESET", "comment": "Przegrzanie — RESET."}

    return {"signal": "CZEKAJ", "comment": "Warunki nie są idealne."}


def parse_live(text: str) -> Dict:
    tokens = text.lower().split()

    ticker = None
    interval = None
    time_str = None
    row = empty_row()

    i = 0
    while i < len(tokens):
        t = tokens[i]

        # ticker
        if ticker is None and t not in ["m1", "m5", "m15", "m30", "h1"]:
            if not t.replace(".", "").isdigit():
                ticker = t.upper()
                i += 1
                continue

        # interwał
        if t in ["m1", "m5", "m15", "m30", "h1"]:
            interval = t.upper()
            i += 1
            continue

        # godzina
        if ":" in t:
            time_str = t
            i += 1
            continue

        # słowa kluczowe
        if t == "open":
            i += 1
            row["open"], i = parse_number(tokens, i)
            continue
        if t == "low":
            i += 1
            row["low"], i = parse_number(tokens, i)
            continue
        if t == "high":
            i += 1
            row["high"], i = parse_number(tokens, i)
            continue
        if t in ["close", "entry"]:
            i += 1
            row["close"], i = parse_number(tokens, i)
            continue
        if t == "ma20":
            i += 1
            row["ma20"], i = parse_number(tokens, i)
            continue
        if t in ["dema9", "ema9"]:
            i += 1
            row["dema9"], i = parse_number(tokens, i)
            continue
        if t == "rsi":
            i += 1
            row["rsi"], i = parse_number(tokens, i)
            continue
        if t in ["wolumen", "volume"]:
            i += 1
            vol, i = parse_number(tokens, i)
            row["volume"] = int(vol) if vol else None
            continue

        i += 1

    if not ticker:
        ticker = "UNKNOWN"

    sig = analyze_live(row)

    return {
        "ticker": ticker,
        "interval": interval or "M15",
        "time": time_str or "--:--",
        "row": row,
        "signal": sig["signal"],
        "comment": sig["comment"]
    }


# ============================================================
#  NA JUTRO — ANALIZA D1/H1
# ============================================================

def analyze_tomorrow(ticker: str, d1: Dict, h1: Dict) -> Dict:
    """Analiza D1/H1 — wynik TAK/NIE + widełki + TP."""
    if not d1:
        return {
            "ticker": ticker,
            "signal": "NIE",
            "comment": "Brak danych D1.",
            "widełki": "",
            "tp": "",
            "d1": d1,
            "h1": h1
        }

    close = d1.get("close")
    ma20 = d1.get("ma20")
    dema9 = d1.get("dema9")
    rsi = d1.get("rsi")

    signal = "NIE"
    comment = "D1 nie spełnia warunków."

    if close and ma20 and dema9 and rsi:
        if close > ma20 and close > dema9 and 50 <= rsi <= 70:
            signal = "TAK"
            comment = "D1 OK — warto obserwować jutro."

    # filtr H1
    if h1 and h1.get("rsi") and h1["rsi"] < 40:
        signal = "NIE"
        comment += " H1 słabe momentum."

    # widełki + TP
    widełki = ""
    tp = ""

    if d1.get("low") and d1.get("high"):
        low = d1["low"]
        high = d1["high"]
        widełki = f"{low} - {high}"

        tp1 = round(high * 1.01, 2)
        tp2 = round(high * 1.02, 2)
        tp3 = round(high * 1.03, 2)
        tp = f"{tp1}/{tp2}/{tp3}"

    return {
        "ticker": ticker,
        "signal": signal,
        "comment": comment,
        "widełki": widełki,
        "tp": tp,
        "d1": d1,
        "h1": h1
    }


def parse_tomorrow(text: str) -> Dict:
    tokens = text.lower().split()

    ticker = None
    d1 = empty_row()
    h1 = empty_row()
    mode = None  # "d1" albo "h1"

    i = 0
    while i < len(tokens):
        t = tokens[i]

        if ticker is None and t not in ["d1", "h1"]:
            if not t.replace(".", "").isdigit():
                ticker = t.upper()
                i += 1
                continue

        if t == "d1":
            mode = "d1"
            i += 1
            continue

        if t == "h1":
            mode = "h1"
            i += 1
            continue

        target = d1 if mode == "d1" else h1 if mode == "h1" else None
        if not target:
            i += 1
            continue

        if t == "open":
            i += 1
            target["open"], i = parse_number(tokens, i)
            continue
        if t == "low":
            i += 1
            target["low"], i = parse_number(tokens, i)
            continue
        if t == "high":
            i += 1
            target["high"], i = parse_number(tokens, i)
            continue
        if t == "close":
            i += 1
            target["close"], i = parse_number(tokens, i)
            continue
        if t == "ma20":
            i += 1
            target["ma20"], i = parse_number(tokens, i)
            continue
        if t in ["dema9", "ema9"]:
            i += 1
            target["dema9"], i = parse_number(tokens, i)
            continue
        if t == "rsi":
            i += 1
            target["rsi"], i = parse_number(tokens, i)
            continue
        if t in ["wolumen", "volume"]:
            i += 1
            vol, i = parse_number(tokens, i)
            target["volume"] = int(vol) if vol else None
            continue

        i += 1

    if not ticker:
        ticker = "UNKNOWN"

    return analyze_tomorrow(ticker, d1, h1)


# ============================================================
#  ENDPOINTY
# ============================================================

@app.post("/voice-parse")
def live(req: VoiceRequest):
    return parse_live(req.text)


@app.post("/parse")
def tomorrow(req: VoiceRequest):
    return parse_tomorrow(req.text)


# ============================================================
#  URUCHOMIENIE
# ============================================================

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
