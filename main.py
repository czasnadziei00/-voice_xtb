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
    mode: Optional[str] = "live"   # "live" albo "tomorrow"


# ====== POMOCNICZE ======

def parse_number_tokens(tokens, i):
    """
    Inteligentny parser liczb:
    - 123
    - 123 4        -> 123.4
    - 123 45       -> 123.45
    - 123 456      -> 123
    - 123 kropka 4 -> 123.4
    """
    if i >= len(tokens):
        return None, i

    t = tokens[i]

    if t.replace(",", ".").replace("-", "").replace("+", "").replace(".", "").isdigit():
        base = t.replace(",", ".")
        if i + 1 < len(tokens):
            t2 = tokens[i + 1]

            if t2 in ["kropka", "przecinek", "coma", "dot"]:
                if i + 2 < len(tokens) and tokens[i + 2].isdigit():
                    frac = tokens[i + 2]
                    return float(f"{base}.{frac}"), i + 3

            if t2.isdigit():
                if len(t2) <= 2:
                    return float(f"{base}.{t2}"), i + 2
                else:
                    return float(base), i + 1

        return float(base), i + 1

    return None, i + 1


def empty_ohlc():
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


# ====== LOGIKA LIVE (M5/M15/H1) ======

def analyze_live_signal(row: Dict) -> Dict:
    """
    Prosta logika LIVE:
    Zwraca sygnał: CZEKAJ / PRAWIE BUY / BUY / RESET / UWAGA RESET / CZEKAJ DO
    Tu możesz później włożyć swoją pełną 4.5.
    """
    signal = "CZEKAJ"
    comment = "Brak pełnych danych."

    close = row.get("close")
    ma20 = row.get("ma20")
    dema9 = row.get("dema9")
    rsi = row.get("rsi")

    if close and ma20 and dema9 and rsi:
        if close > ma20 and close > dema9 and 55 <= rsi <= 70:
            signal = "BUY"
            comment = "Silny sygnał BUY (LIVE)."
        elif close > ma20 and 50 <= rsi < 55:
            signal = "PRAWIE BUY"
            comment = "PRAWIE BUY — brakuje trochę RSI."
        elif rsi > 75:
            signal = "RESET"
            comment = "Przegrzanie — RESET."
        else:
            signal = "CZEKAJ"
            comment = "Warunki nie są idealne."

    return {
        "signal": signal,
        "comment": comment
    }


# ====== LOGIKA NA JUTRO (D1/H1) ======

def analyze_signal_d1_h1(ticker: str, d1: Dict, h1: Dict) -> Dict:
    final = empty_ohlc()

    if d1:
        final.update(d1)

    final["interval"] = "D1/H1"

    signal = "NIE"
    comment = "Brak pełnych danych D1."
    good = False
    widełki = ""
    tp = ""

    if d1 and d1.get("close") and d1.get("ma20") and d1.get("dema9") and d1.get("rsi"):
        close = d1["close"]
        ma20 = d1["ma20"]
        dema9 = d1["dema9"]
        rsi = d1["rsi"]

        if close > ma20 and close > dema9 and 50 <= rsi <= 70:
            signal = "TAK"
            good = True
            comment = "D1: trend wzrostowy, warto obserwować jutro."
        else:
            signal = "NIE"
            good = False
            comment = "D1 nie spełnia warunków."

        if d1.get("low") and d1.get("high"):
            low = d1["low"]
            high = d1["high"]
            widełki = f"{round(low, 2)} - {round(high, 2)}"
            tp1 = round(high * 1.01, 2)
            tp2 = round(high * 1.02, 2)
            tp3 = round(high * 1.03, 2)
            tp = f"{tp1} / {tp2} / {tp3}"

    if h1 and h1.get("rsi") is not None and h1["rsi"] < 40 and signal == "TAK":
        signal = "NIE"
        good = False
        comment += " H1 słabe momentum (RSI < 40)."

    return {
        "ticker": ticker,
        "d1": d1,
        "h1": h1,
        "final": final,
        "signal": signal,
        "widełki": widełki,
        "tp": tp,
        "good_for_tomorrow": good,
        "comment": comment
    }


# ====== PARSER MIX (LIVE / NA JUTRO) ======

def parse_mixed_live(text: str) -> Dict:
    """
    LIVE MIX:
    - KGHM M15 16:00 open 330 low 320 high 350 close 340 ma20 335 dema9 338 rsi 62 wolumen 3000
    - KGHM M15 330 320 350 340 335 338 62 3000 (Styl B)
    - open 330 / low 320 / high 350 / rsi 62 / wolumen 3000 (uzupełnianie)
    Backend zwraca tylko to, co udało się wyciągnąć z JEDNEGO wywołania.
    Pamięć między nagraniami trzymasz w JS.
    """
    t = text.lower().split()
    ticker = None
    interval = None
    time_str = None
    row = empty_ohlc()

    i = 0
    while i < len(t):
        token = t[i]

        # ticker
        if ticker is None and token not in ["m1", "m5", "m15", "m30", "h1", "h4"]:
            if not token.replace(",", ".").replace(".", "").isdigit():
                ticker = token.upper()
                i += 1
                continue

        # interwał
        if token in ["m1", "m5", "m15", "m30", "h1", "h4"]:
            interval = token.upper()
            i += 1
            continue

        # godzina (prosty format 16:00)
        if ":" in token and len(token) <= 5:
            time_str = token
            i += 1
            continue

        # słowa kluczowe
        if token in ["open", "otwarcie"]:
            i += 1
            row["open"], i = parse_number_tokens(t, i)
            continue
        if token in ["low", "minimum", "min"]:
            i += 1
            row["low"], i = parse_number_tokens(t, i)
            continue
        if token in ["high", "max", "maximum"]:
            i += 1
            row["high"], i = parse_number_tokens(t, i)
            continue
        if token in ["close", "zamknięcie", "zamkniecie", "entry"]:
            i += 1
            row["close"], i = parse_number_tokens(t, i)
            continue
        if token in ["ma20", "ema20"]:
            i += 1
            row["ma20"], i = parse_number_tokens(t, i)
            continue
        if token in ["dema9", "ema9"]:
            i += 1
            row["dema9"], i = parse_number_tokens(t, i)
            continue
        if token in ["rsi"]:
            i += 1
            row["rsi"], i = parse_number_tokens(t, i)
            continue
        if token in ["vwap"]:
            i += 1
            row["vwap"], i = parse_number_tokens(t, i)
            continue
        if token in ["wolumen", "volume", "obroty"]:
            i += 1
            vol, i2 = parse_number_tokens(t, i)
            row["volume"] = int(vol) if vol is not None else None
            i = i2
            continue

        # Styl B (jeśli nie ma słów kluczowych, a są same liczby)
        # Możesz rozbudować, jeśli chcesz.
        i += 1

    if not ticker:
        ticker = "UNKNOWN"

    sig = analyze_live_signal(row)

    return {
        "ticker": ticker,
        "interval": interval or "M15",
        "time": time_str or "--:--",
        "row": row,
        "signal": sig["signal"],
        "comment": sig["comment"]
    }


def parse_d1_h1_from_text(text: str) -> Dict:
    """
    NA JUTRO MIX:
    - KGHM D1 open ... low ... high ... close ... ma20 ... dema9 ... rsi ... vwap ... wolumen ...
    - KGHM D1 195 193 200 198 190 195 62 197 120000 (Styl B)
    - H1 ... (analogicznie)
    """
    t = text.lower().split()
    ticker = None
    d1 = empty_ohlc()
    h1 = empty_ohlc()
    has_d1 = False
    has_h1 = False

    i = 0
    current_frame = None  # "d1" albo "h1"

    while i < len(t):
        token = t[i]

        if ticker is None and token not in ["d1", "h1"]:
            if not token.replace(",", ".").replace(".", "").isdigit():
                ticker = token.upper()
                i += 1
                continue

        if token == "d1":
            current_frame = "d1"
            has_d1 = True
            i += 1
            continue

        if token == "h1":
            current_frame = "h1"
            has_h1 = True
            i += 1
            continue

        target = d1 if current_frame == "d1" else h1 if current_frame == "h1" else None

        if target is None:
            i += 1
            continue

        if token in ["open", "otwarcie"]:
            i += 1
            target["open"], i = parse_number_tokens(t, i)
            continue
        if token in ["low", "minimum", "min"]:
            i += 1
            target["low"], i = parse_number_tokens(t, i)
            continue
        if token in ["high", "max", "maximum"]:
            i += 1
            target["high"], i = parse_number_tokens(t, i)
            continue
        if token in ["close", "zamknięcie", "zamkniecie"]:
            i += 1
            target["close"], i = parse_number_tokens(t, i)
            continue
        if token in ["ma20", "ema20"]:
            i += 1
            target["ma20"], i = parse_number_tokens(t, i)
            continue
        if token in ["dema9", "ema9"]:
            i += 1
            target["dema9"], i = parse_number_tokens(t, i)
            continue
        if token in ["rsi"]:
            i += 1
            target["rsi"], i = parse_number_tokens(t, i)
            continue
        if token in ["vwap"]:
            i += 1
            target["vwap"], i = parse_number_tokens(t, i)
            continue
        if token in ["wolumen", "volume", "obroty"]:
            i += 1
            vol, i2 = parse_number_tokens(t, i)
            target["volume"] = int(vol) if vol is not None else None
            i = i2
            continue

        # Styl B dla D1/H1 możesz rozbudować analogicznie jak w LIVE
        i += 1

    if not ticker:
        ticker = "UNKNOWN"

    if not has_d1:
        d1 = None
    if not has_h1:
        h1 = None

    return analyze_signal_d1_h1(ticker, d1, h1)


# ====== ENDPOINT LIVE ======

@app.post("/voice-parse")
def parse_live(req: VoiceRequest):
    """
    LIVE 6.4 MIX
    """
    result = parse_mixed_live(req.text)
    return result


# ====== ENDPOINT NA JUTRO ======

@app.post("/parse")
def parse_tomorrow(req: VoiceRequest):
    """
    NA JUTRO 6.4 MIX
    """
    result = parse_d1_h1_from_text(req.text)
    return result


# ====== URUCHOMIENIE ======

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
