from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Dict

app = FastAPI()

# ======================================================
#  STATIC FILES — FRONTEND
# ======================================================
# To wystawia katalog "frontend" jako pliki statyczne
# i pozwala ładować voice.js z:
#   /frontend/js/voice.js
app.mount("/frontend", StaticFiles(directory="frontend"), name="frontend")

# ======================================================
#  CORS
# ======================================================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================================================
#  PAMIĘĆ
# ======================================================
memory: Dict[str, Dict] = {}


# ======================================================
#  MODELE
# ======================================================
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


# ======================================================
#  LOGIKA SYGNAŁU 6.5 PRO
# ======================================================
def calc_signal(rec: VoiceRecord) -> str:
    c = rec.close
    ma = rec.ma20
    de = rec.dema9
    r = rec.rsi

    # mocny BUY
    if c > ma and c > de and r >= 60:
        return "BUY"

    # prawie buy
    if c > ma and 50 <= r < 60:
        return "PRAWIE BUY"

    # mocny SELL
    if c < ma and c < de and r <= 40:
        return "SELL"

    # czekaj do
    if abs(c - ma) / ma < 0.003 and 45 <= r <= 55:
        return "CZEKAJ DO"

    # neutralne czekanie
    return "CZEKAJ"


# ======================================================
#  ENDPOINT: PARSOWANIE
# ======================================================
@app.post("/voice-parse")
def voice_parse(rec: VoiceRecord):
    t = rec.ticker.upper()
    signal = calc_signal(rec)
    entry = float(rec.close)

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


# ======================================================
#  ENDPOINT: DELETE
# ======================================================
@app.post("/voice-parse/delete")
def voice_delete(req: DeleteReq):
    t = req.ticker.upper()
    if t in memory:
        del memory[t]
    return {"ticker": t, "deleted": True}
