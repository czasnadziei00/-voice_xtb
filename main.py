from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class VoiceRecord(BaseModel):
    ticker: str
    interval: str
    open: float
    low: float
    high: float
    close: float
    volume: float
    ma20: float
    dema9: float
    rsi: float

@app.post("/analyze")
def analyze(record: VoiceRecord):

    close = record.close
    ma20 = record.ma20
    dema9 = record.dema9
    rsi = record.rsi
    volume = record.volume

    # PROSTA LOGIKA (placeholder)
    if close > ma20 and rsi > 55:
        signal = "BUY"
    elif close < ma20 and rsi < 45:
        signal = "SELL"
    else:
        signal = "NEUTRAL"

    # TP3
    if signal == "BUY":
        tp3 = round(close * 1.03, 2)
    elif signal == "SELL":
        tp3 = round(close * 0.97, 2)
    else:
        tp3 = None

    # Widełki
    widelki = [
        round(close * 0.99, 2),
        round(close * 1.01, 2)
    ]

    return {
        "ticker": record.ticker,
        "interval": record.interval,
        "close": close,
        "signal": signal,
        "tp3": tp3,
        "widelki": widelki,
        "rsi": rsi,
        "ma20": ma20,
        "dema9": dema9,
        "volume": volume,
        "comment": f"Sygnał={signal}, RSI={rsi}, MA20={ma20}, DEMA9={dema9}, Vol={volume}"
    }
