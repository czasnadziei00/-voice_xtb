from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Optional

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# PAMIĘĆ MULTI‑TF:
# memory[ticker][interval] = {...}
memory: Dict[str, Dict[str, Dict]] = {}


class VoiceRecord(BaseModel):
    ticker: str
    interval: str
    time: Optional[str] = None
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


# ======================================================
#  LOGIKA SYGNAŁU (TA, KTÓRA DZIAŁAŁA)
# ======================================================

def calc_signal(rec: VoiceRecord) -> str:
    c = rec.close
    ma = rec.ma20
    de = rec.dema9
    r = rec.rsi

    if c > ma and c > de and r >= 60:
        return "BUY"

    if c > ma and 50 <= r < 60:
        return "PRAWIE BUY"

    if c < ma and c < de and r <= 40:
        return "SELL"

    if abs(c - ma) / ma < 0.003 and 45 <= r <= 55:
        return "CZEKAJ DO"

    return "CZEKAJ"


# ======================================================
#  GŁÓWNY ENDPOINT
# ======================================================

@app.post("/voice-parse")
def voice_parse(rec: VoiceRecord):
    t = rec.ticker.upper()
    tf = rec.interval.upper()

    signal = calc_signal(rec)

    # komentarz diagnostyczny
    comment = (
        f"{t} {tf} {rec.time} | "
        f"close={rec.close}, ma20={rec.ma20}, dema9={rec.dema9}, "
        f"rsi={rec.rsi}, vol={rec.volume}, signal={signal}"
    )

    data = {
        "ticker": t,
        "interval": tf,
        "time": rec.time,
        "open": rec.open,
        "low": rec.low,
        "high": rec.high,
        "close": rec.close,
        "volume": rec.volume,
        "ma20": rec.ma20,
        "dema9": rec.dema9,
        "rsi": rec.rsi,
        "entry": "",
        "signal": signal,
        "comment": comment,
    }

    # MULTI‑TF ZAPIS
    if t not in memory:
        memory[t] = {}

    memory[t][tf] = data

    return data


# ======================================================
#  USUWANIE TICKERA
# ======================================================

@app.post("/voice-parse/delete")
def voice_delete(req: DeleteReq):
    t = req.ticker.upper()
    if t in memory:
        del memory[t]
    return {"ticker": t, "deleted": True}
