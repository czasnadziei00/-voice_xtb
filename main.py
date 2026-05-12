from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from math import isnan

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

    # Prosta logika sygnału (placeholder pod system 4.6/4.7)
    if close > ma20 and rsi > 55:
        signal = "BUY"
    elif close < ma20 and rsi < 45:
        signal = "SELL"
    else:
        signal = "NEUTRAL"

    # TP3 – przykładowo 3% od close w stronę sygnału
    if signal == "BUY":
        tp3 = round(close * 1.03, 2)
    elif signal == "SELL":
        tp3 = round(close * 0.97, 2)
    else:
        tp3 = None

    # Widełki – ±1% od close
    low_band = round(close * 0.99, 2)
    high_band = round(close * 1.01, 2)

    comment = f"Sygnał: {signal}, RSI={rsi}, MA20={ma20}, DEMA9={dema9}, Vol={volume}"

    return {
        "ticker": record.ticker,
        "interval": record.interval,
        "close": close,
        "signal": signal,
        "tp3": tp3,
        "widelki": [low_band, high_band],
        "rsi": rsi,
        "ma20": ma20,
        "dema9": dema9,
        "volume": volume,
        "comment": comment,
    }
