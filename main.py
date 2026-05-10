from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict
import uvicorn

app = FastAPI()

# ====== CORS — MUSI BYĆ NA RENDER ======
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

    # czysta liczba
    if t.replace(",", ".").replace("-", "").replace("+", "").replace(".", "").isdigit():
        base = t.replace(",", ".")
        # spróbuj zajrzeć w następny token
        if i + 1 < len(tokens):
            t2 = tokens[i + 1]
            # wariant "kropka 4"
            if t2 in ["kropka", "przecinek", "coma", "dot"]:
                if i + 2 < len(tokens) and tokens[i + 2].isdigit():
                    frac = tokens[i + 2]
                    return float(f"{base}.{frac}"), i + 3
            # wariant "123 4" / "123 45" / "123 456"
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


def analyze_signal_d1_h1(ticker: str,
                         d1: Dict,
                         h1: Dict) -> Dict:
    """
    Logika NA JUTRO 2.0:
    FINAL = D1
    H1 = filtr
    """
    final = empty_ohlc()

    # FINAL = D1
    if d1:
        final.update(d1)
    final["interval"] = "D1/H1"

    signal = "CZEKAJ"
    comment = "Brak pełnych danych D1."
    good = False
    widełki = ""
    tp = ""

    # ====== LOGIKA D1 ======
    if d1 and d1.get("close") and d1.get("ma20") and d1.get("dema9") and d1.get("rsi"):
        close = d1["close"]
        ma20 = d1["ma20"]
        dema9 = d1["dema9"]
        rsi = d1["rsi"]

        if close > ma20 and close > dema9 and 50 <= rsi <= 70:
            signal = "BUY"
            good = True
            comment = "Trend wzrostowy D1, close > MA20 i DEMA9, RSI w strefie siły."
        else:
            signal = "CZEKAJ"
            good = False
            comment = "D1 nie spełnia warunków trendu."

        # widełki + TP
        if d1.get("low") and d1.get("high"):
            low = d1["low"]
            high = d1["high"]
            widełki = f"{round(low, 2)} - {round(high, 2)}"
            tp1 = round(high * 1.01, 2)
            tp2 = round(high * 1.02, 2)
            tp3 = round(high * 1.03, 2)
            tp = f"{tp1} / {tp2} / {tp3}"

    # ====== FILTR H1 ======
    if h1 and h1.get("rsi") is not None and h1["rsi"] < 40 and signal == "BUY":
        signal = "CZEKAJ"
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


def parse_d1_h1_from_text(text: str) -> Dict:
    """
    Styl B:
    - 'KGHM D1 195 193 200 198 190 195 62 197 120000'
    - 'KGHM H1 196 194 198 197 195 196 58 196.5 34000'
    """
    t = text.lower().split()
    ticker = None
    d1 = empty_ohlc()
    h1 = empty_ohlc()
    has_d1 = False
    has_h1 = False

    i = 0
    while i < len(t):
        token = t[i]

        # ticker = pierwsze słowo nie będące liczbą ani d1/h1
        if ticker is None and token not in ["d1", "h1"]:
            if not token.replace(",", ".").replace(".", "").isdigit():
                ticker = token
                i += 1
                continue

        if token == "d1":
            has_d1 = True
            i += 1
            d1["open"], i = parse_number_tokens(t, i)
            d1["low"], i = parse_number_tokens(t, i)
            d1["high"], i = parse_number_tokens(t, i)
            d1["close"], i = parse_number_tokens(t, i)
            d1["ma20"], i = parse_number_tokens(t, i)
            d1["dema9"], i = parse_number_tokens(t, i)
            d1["rsi"], i = parse_number_tokens(t, i)
            d1["vwap"], i = parse_number_tokens(t, i)
            vol, i = parse_number_tokens(t, i)
            d1["volume"] = int(vol) if vol is not None else None
            continue

        if token == "h1":
            has_h1 = True
            i += 1
            h1["open"], i = parse_number_tokens(t, i)
            h1["low"], i = parse_number_tokens(t, i)
            h1["high"], i = parse_number_tokens(t, i)
            h1["close"], i = parse_number_tokens(t, i)
            h1["ma20"], i = parse_number_tokens(t, i)
            h1["dema9"], i = parse_number_tokens(t, i)
            h1["rsi"], i = parse_number_tokens(t, i)
            h1["vwap"], i = parse_number_tokens(t, i)
            vol, i = parse_number_tokens(t, i)
            h1["volume"] = int(vol) if vol is not None else None
            continue

        i += 1

    if not ticker:
        ticker = "UNKNOWN"

    if not has_d1:
        d1 = None
    if not has_h1:
        h1 = None

    return analyze_signal_d1_h1(ticker, d1, h1)


# ====== ENDPOINT NA JUTRO 2.0 ======

@app.post("/parse")
def parse_tomorrow(req: VoiceRequest):
    text = req.text
    result = parse_d1_h1_from_text(text)
    return result


# ====== URUCHOMIENIE ======

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
