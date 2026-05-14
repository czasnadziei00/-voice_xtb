from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Optional, List
from datetime import datetime

app = FastAPI(
    title="VOICE XTB 7.5.3 PRO",
    version="7.5.3"
)

# ======================================================
#  CORS
# ======================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ======================================================
#  PAMIĘĆ MULTI-TF
# ======================================================

memory: Dict[str, Dict[str, Dict]] = {}

HISTORY_LIMITS = {
    "M5": 14,
    "M15": 7,
    "H1": 3
}

# ======================================================
#  MODELE
# ======================================================

class VoiceRecord(BaseModel):
    ticker: str = Field(..., min_length=1)
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
    entry: Optional[float] = None 

class DeleteReq(BaseModel):
    ticker: str

# ======================================================
#  PRO-COMMENT GENERATOR (SYGNAŁOWY)
# ======================================================

def generate_pro_comment(rec: VoiceRecord, history: List[Dict], signal: str) -> str:
    dir_tf = trend_direction(history)
    trend_map = {"UP": "WZROSTOWY", "DOWN": "SPADKOWY", "NEUTRAL": "BOCZNY"}
    t_dir = trend_map.get(dir_tf, "NEUTRALNY")
    
    supp_min = round(rec.low * 0.998, 2)
    supp_max = round(rec.low, 2)
    
    r = rec.rsi
    if r <= 30:
        mom = f"RSI {r:.1f} - SKRAJNE WYPRZEDANIE. MOŻLIWA AKUMULACJA."
    elif r >= 70:
        mom = f"RSI {r:.1f} - SKRAJNE WYKUPIENIE. RYZYKO DYSTRYBUCJI."
    else:
        mom = f"RSI {r:.1f} - MOMENTUM STABILNE W STREFIE NEUTRALNEJ."

    rel = "SILNA STRUKTURA POWYŻEJ DEMA9." if rec.close > rec.dema9 else "SŁABOŚĆ POD DEMA9 - MOŻLIWA KONTRA."
    
    if "BUY" in signal:
        interp = "POTWIERDZONA PRESJA POPYTU. SZUKANIE WEJŚCIA W STRUKTURZE WZROSTOWEJ."
    elif "SELL" in signal:
        interp = "DOMINACJA PODAŻY. STRUKTURA SUGERUJE KONTYNUACJĘ SPADKÓW."
    else:
        interp = "BRAK KLAROWNEGO SYGNAŁU. RUCH W KONSOLIDACJI."

    return (
        f"--- RAPORT ANALITYCZNY ---\n\n"
        f"TREND GŁÓWNY: {t_dir}\n"
        f"STREFA WSPARCIA: {supp_min} - {supp_max}\n\n"
        f"MOMENTUM: {mom}\n"
        f"SIŁA RELATYWNA: {rel}\n\n"
        f"INTERPRETACJA: {interp}\n\n"
        f"RYZYKO (STOP LOSS): OCHRONA PONIŻEJ POZIOMU {supp_min}."
    )

# ======================================================
#  ANALIZA TECHNICZNA
# ======================================================

def push_history(ticker: str, tf: str, candle: Dict):
    if ticker not in memory: memory[ticker] = {}
    if tf not in memory[ticker]: memory[ticker][tf] = {"history": []}
    memory[ticker][tf]["history"].append(candle)
    limit = HISTORY_LIMITS.get(tf, 5)
    if len(memory[ticker][tf]["history"]) > limit:
        memory[ticker][tf]["history"] = memory[ticker][tf]["history"][-limit:]

def trend_direction(history: List[Dict]) -> str:
    if len(history) < 2: return "NEUTRAL"
    first, last = history[0]["close"], history[-1]["close"]
    if first == 0: return "NEUTRAL"
    diff = abs(last - first) / first
    if last > first and diff > 0.005: return "UP"
    if last < first and diff > 0.005: return "DOWN"
    return "NEUTRAL"

def calc_signal(rec: VoiceRecord, history: List[Dict]):
    c, de, r = rec.close, rec.dema9, rec.rsi
    dir_tf = trend_direction(history)
    if dir_tf == "UP" and c > de: return "CZEKAJ DO" if r >= 80 else "BUY"
    if dir_tf == "DOWN" and c < de: return "CZEKAJ DO" if r <= 20 else "SELL"
    if dir_tf == "UP": return "PRAWIE BUY"
    if dir_tf == "DOWN": return "PRAWIE SELL"
    return "CZEKAJ"

# ======================================================
#  OBSŁUGA TP I WIDEŁEK
# ======================================================

def compute_tp(signal: str, close: float, low: float, high: float, ma: float, de: float):
    rng = high - low
    tp1, tp2, tp3 = None, None, None
    if "BUY" in signal:
        tp1, tp2 = close + rng * 0.55, close + rng * 1.1
        tp3 = close + (abs(close - ((ma + de) / 2)) * 1.8)
    elif "SELL" in signal:
        tp1, tp2 = close - rng * 0.55, close - rng * 1.1
        tp3 = close - (abs(close - ((ma + de) / 2)) * 1.8)
    return {"tp1": round(tp1, 2) if tp1 else "—", "tp2": round(tp2, 2) if tp2 else "—", "tp3": round(tp3, 2) if tp3 else "—"}

# ======================================================
#  MAIN ENDPOINT
# ======================================================

@app.post("/voice-parse")
def voice_parse(rec: VoiceRecord):
    if not rec.time: rec.time = datetime.now().strftime("%H:%M")
    t, tf = rec.ticker.upper().strip(), rec.interval.upper()
    
    if t not in memory: memory[t] = {}
    if tf not in memory[t]: memory[t][tf] = {"history": [], "last_data": {}}

    history = memory[t][tf]["history"]
    signal = calc_signal(rec, history)

    prev_entry = memory[t][tf]["last_data"].get("entry", "")
    if rec.entry is not None:
        final_entry = "" if rec.entry == 0 else str(rec.entry)
    else:
        final_entry = prev_entry

    data = {
        "ticker": t, "interval": tf, "time": rec.time,
        "open": rec.open, "low": rec.low, "high": rec.high, "close": rec.close,
        "volume": rec.volume, "ma20": rec.ma20, "dema9": rec.dema9, "rsi": rec.rsi,
        "signal": signal, "entry": final_entry,
        "comment": generate_pro_comment(rec, history, signal)
    }

    if tf in ["M15", "15"]:
        rng = rec.high - rec.low
        data["widelki"] = f"{rec.low + rng*0.18:.2f} - {rec.low + rng*0.32:.2f}"
        data.update(compute_tp(signal, rec.close, rec.low, rec.high, rec.ma20, rec.dema9))

    push_history(t, tf, data)
    memory[t][tf]["last_data"] = data
    
    return data

# ======================================================
#  SYSTEM
# ======================================================

@app.post("/voice-parse/delete")
def voice_delete(req: DeleteReq):
    if req.ticker.upper() in memory: del memory[req.ticker.upper()]
    return {"deleted": True}

@app.get("/memory")
def memory_view(): return memory

@app.get("/")
def root(): return {"name": "VOICE XTB 7.5.3 PRO", "status": "ONLINE"}
