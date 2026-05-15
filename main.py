from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Optional, List
from datetime import datetime

app = FastAPI(
    title="VOICE XTB 7.6.0 PRO - KONSENSUS",
    version="7.6.0"
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
#  PAMIĘĆ I KONFIGURACJA
# ======================================================

memory: Dict[str, Dict] = {}
HISTORY_LIMITS = {"M5": 14, "M15": 7, "H1": 3}

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
#  LOGIKA ANALITYCZNA
# ======================================================

def trend_direction(history: List[Dict]) -> str:
    if len(history) < 2: return "NEUTRAL"
    first, last = history[0]["close"], history[-1]["close"]
    if first == 0: return "NEUTRAL"
    diff = abs(last - first) / first
    if last > first and diff > 0.003: return "UP"
    if last < first and diff > 0.003: return "DOWN"
    return "NEUTRAL"

def calc_raw_signal(rec: VoiceRecord, history: List[Dict]) -> str:
    c, de, r = rec.close, rec.dema9, rec.rsi
    dt = trend_direction(history)
    if dt == "UP" and c > de: return "BUY" if r < 80 else "CZEKAJ"
    if dt == "DOWN" and c < de: return "SELL" if r > 20 else "CZEKAJ"
    return "PRAWIE BUY" if dt == "UP" else "PRAWIE SELL" if dt == "DOWN" else "CZEKAJ"

# ======================================================
#  SYSTEM KONSENSUSU (HYBRYDA M5 + M15)
# ======================================================

def get_final_consensus(ticker: str) -> str:
    t_data = memory.get(ticker, {})
    m5_list = t_data.get("M5", {}).get("history", [])
    m15_list = t_data.get("M15", {}).get("history", [])

    if not m15_list: 
        return m5_list[-1]["signal_raw"] if m5_list else "CZEKAJ"
    
    last_m15 = m15_list[-1]
    s15 = last_m15.get("signal_raw", "CZEKAJ")
    
    if not m5_list: return s15
    
    last_m5 = m5_list[-1]
    s5 = last_m5.get("signal_raw", "CZEKAJ")

    if "BUY" in s15 and "BUY" in s5: return "BUY (STRONG)"
    if "SELL" in s15 and "SELL" in s5: return "SELL (STRONG)"
    
    if len(m5_list) >= 2:
        m5_prev = m5_list[-2]
        m5_now = m5_list[-1]
        
        if s15 in ["BUY", "PRAWIE BUY", "CZEKAJ"]:
            if m5_now["close"] > m5_now["open"] and m5_prev["close"] > m5_prev["open"]:
                if m5_now["close"] > m5_now["dema9"]:
                    return "BUY (M5 ACCEL)"
        
        if s15 in ["SELL", "PRAWIE SELL", "CZEKAJ"]:
            if m5_now["close"] < m5_now["open"] and m5_prev["close"] < m5_prev["open"]:
                if m5_now["close"] < m5_now["dema9"]:
                    return "SELL (M5 ACCEL)"

    if ("BUY" in s15 and "SELL" in s5) or ("SELL" in s15 and "BUY" in s5):
        return "CZEKAJ (KONFLIKT)"

    return s15

# ======================================================
#  PRO-COMMENT GENERATOR
# ======================================================

def generate_pro_comment(rec: VoiceRecord, history: List[Dict], final_signal: str) -> str:
    dt = trend_direction(history)
    rsi_status = "WYKUPIONY" if rec.rsi > 70 else "WYPRZEDANY" if rec.rsi < 30 else "NEUTRALNY"
    supp_min = round(rec.low * 0.998, 2)
    
    return (
        f"--- RAPORT KONSENSUSU 7.6.0 ---\n\n"
        f"WERDYKT KOŃCOWY: {final_signal}\n"
        f"TREND GŁÓWNY: {dt}\n"
        f"MOMENTUM RSI: {rec.rsi:.1f} ({rsi_status})\n"
        f"POZIOM WEJŚCIA: {rec.close}\n"
        f"WSPARCIE DLA STOP LOSS: {supp_min}\n\n"
        f"INTERPRETACJA: {'Szukaj okazji' if 'BUY' in final_signal else 'Rozważ S' if 'SELL' in final_signal else 'Stój z boku'}.\n"
    )

# ======================================================
#  MAIN ENDPOINT
# ======================================================

@app.post("/voice-parse")
def voice_parse(rec: VoiceRecord):
    if not rec.time: rec.time = datetime.now().strftime("%H:%M")
    t, tf = rec.ticker.upper().strip(), rec.interval.upper()
    
    if t not in memory: memory[t] = {"global_entry": ""}
    if tf not in memory[t]: memory[t][tf] = {"history": [], "last_data": {}}

    history = memory[t][tf]["history"]
    raw_sig = calc_raw_signal(rec, history)

    if rec.entry is not None:
        memory[t]["global_entry"] = "" if rec.entry == 0 else str(rec.entry)

    temp_data = {
        "ticker": t, "interval": tf, "time": rec.time,
        "close": rec.close, "open": rec.open, "low": rec.low, "high": rec.high,
        "dema9": rec.dema9, "ma20": rec.ma20, "rsi": rec.rsi,
        "signal_raw": raw_sig
    }
    
    memory[t][tf]["history"].append(temp_data)
    if len(memory[t][tf]["history"]) > HISTORY_LIMITS.get(tf, 5):
        memory[t][tf]["history"].pop(0)

    final_sig = get_final_consensus(t)

    data = temp_data.copy()
    data["signal"] = final_sig
    data["entry"] = memory[t]["global_entry"]
    data["comment"] = generate_pro_comment(rec, history, final_sig)

    if tf == "M15":
        rng = rec.high - rec.low
        data["widelki"] = f"{rec.low + rng*0.18:.2f} - {rec.low + rng*0.32:.2f}"
        if "BUY" in final_sig:
            data.update({"tp1": round(rec.close + rng*0.55, 2), "tp2": round(rec.close + rng*1.1, 2)})
        elif "SELL" in final_sig:
            data.update({"tp1": round(rec.close - rng*0.55, 2), "tp2": round(rec.close - rng*1.1, 2)})

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
def root(): return {"name": "VOICE XTB 7.6.0 PRO", "status": "ONLINE"}
