from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

memory: Dict[str, Dict] = {}

class VoiceRecord(BaseModel):
    ticker: str
    interval: str
    time: str
    open: float
    low: float
    high: float
    close: float
    volume: float
    ma20: float
    dema9: float
    rsi: float

class DeleteReq(BaseModel):
    ticker: str


@app.post("/voice-parse")
def voice_parse(rec: VoiceRecord):
    t = rec.ticker.upper()

    # ===== SYGNAŁ =====
    if rec.close > rec.ma20 and rec.rsi > 55:
        signal = "BUY"
    elif rec.close < rec.ma20 and rec.rsi < 45:
        signal = "SELL"
    else:
        signal = "NEUTRAL"

    # ===== ENTRY =====
    entry = rec.close

    # ===== KOMENTARZ =====
    comment = (
        f"{t} {rec.interval} {rec.time} | "
        f"close={rec.close}, ma20={rec.ma20}, dema9={rec.dema9}, "
        f"rsi={rec.rsi}, vol={rec.volume}, signal={signal}"
    )

    data = {
        "ticker": t,
        "interval": rec.interval,
        "time": rec.time,
        "open": rec.open,
        "low": rec.low,
        "high": rec.high,
        "close": rec.close,
        "volume": rec.volume,
        "ma20": rec.ma20,
        "dema9": rec.dema9,
        "rsi": rec.rsi,
        "entry": entry,
        "signal": signal,
        "comment": comment,
    }

    memory[t] = data
    return data


@app.post("/voice-parse/delete")
def voice_delete(req: DeleteReq):
    t = req.ticker.upper()
    if t in memory:
        del memory[t]
    return {"ticker": t, "deleted": True}
