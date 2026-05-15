# ======================================================
#  VOICE XTB 8.1 HYBRID - CONFIDENCE & CONSENSUS ENGINE
# ======================================================

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Optional, List
from datetime import datetime

app = FastAPI(title="VOICE XTB 8.1 HYBRID", version="8.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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

def avg(values):
    return sum(values) / len(values) if values else 0

def trend_direction(history: List[Dict]) -> str:
    if len(history) < 3: return "NEUTRAL"
    closes = [x["close"] for x in history[-3:]]
    dema = [x["dema9"] for x in history[-3:]]
    c_slope = closes[-1] - closes[0]
    d_slope = dema[-1] - dema[0]
    if c_slope > 0 and d_slope > 0: return "UP"
    if c_slope < 0 and d_slope < 0: return "DOWN"
    return "NEUTRAL"

def detect_market_state(rec: VoiceRecord, history: List[Dict]) -> str:
    if len(history) < 3: return "UNKNOWN"
    c_range = rec.high - rec.low
    avg_range = avg([abs(x["high"] - x["low"]) for x in history[-3:]])
    if avg_range == 0: return "RANGE"
    vol_ratio = c_range / avg_range
    if vol_ratio > 1.8: return "BREAKOUT"
    if vol_ratio > 2.5: return "CHAOS"
    if abs(rec.dema9 - rec.ma20) < (avg_range * 0.15): return "RANGE"
    return "TREND" if trend_direction(history) != "NEUTRAL" else "RANGE"

def calc_confidence(rec: VoiceRecord, history: List[Dict]) -> Dict:
    score = 0
    trend = trend_direction(history)
    market_state = detect_market_state(rec, history)
    rsi_delta = history[-1]["rsi"] - history[-2]["rsi"] if len(history) > 1 else 0
    vol_spike = rec.volume / avg([x.get("volume", 0) for x in history[-3:]]) if len(history) > 1 else 1
    strength = (abs(rec.close - rec.open) / (rec.high - rec.low)) if (rec.high - rec.low) > 0 else 0

    if trend == "UP" and rec.close > rec.dema9: score += 25
    if trend == "DOWN" and rec.close < rec.dema9: score += 25
    if (rec.dema9 > rec.ma20 and trend == "UP") or (rec.dema9 < rec.ma20 and trend == "DOWN"): score += 10
    if (trend == "UP" and rsi_delta > 0) or (trend == "DOWN" and rsi_delta < 0): score += 20
    if vol_spike > 1.1: score += 15
    if strength > 0.45: score += 15
    if market_state == "BREAKOUT": score += 10
    if market_state == "CHAOS": score -= 25
    if market_state == "RANGE": score -= 5

    signal = "CZEKAJ"
    if trend == "UP":
        if score >= 70: signal = "BUY PREMIUM"
        elif score >= 55: signal = "BUY AGRESYWNY"
        elif score >= 40: signal = "PRAWIE BUY"
    elif trend == "DOWN":
        if score >= 70: signal = "SELL PREMIUM"
        elif score >= 55: signal = "SELL AGRESYWNY"
        elif score >= 40: signal = "PRAWIE SELL"

    return {
        "signal": signal, "confidence": max(0, min(100, score)),
        "trend": trend, "market_state": market_state,
        "vol_spike": vol_spike
    }

def get_final_consensus(ticker: str):
    t_data = memory.get(ticker, {})
    m5, m15 = t_data.get("M5", {}).get("history", []), t_data.get("M15", {}).get("history", [])
    if not m5: return {"signal": "CZEKAJ", "confidence": 0}
    last_m5 = m5[-1]
    if not m15: return {"signal": last_m5.get("signal", "CZEKAJ"), "confidence": last_m5.get("confidence", 0)}
    last_m15 = m15[-1]
    s5, s15 = last_m5.get("signal", "CZEKAJ"), last_m15.get("signal", "CZEKAJ")
    c5, c15 = last_m5.get("confidence", 0), last_m15.get("confidence", 0)

    if ("BUY" in s5 and "BUY" in s15): return {"signal": "BUY STRONG", "confidence": round((c5+c15)/2)}
    if ("SELL" in s5 and "SELL" in s15): return {"signal": "SELL STRONG", "confidence": round((c5+c15)/2)}
    
    if len(m5) >= 2:
        if m5[-1]["close"] > m5[-1]["open"] and m5[-2]["close"] > m5[-2]["open"] and c5 >= 55:
            return {"signal": "BUY ACCEL", "confidence": c5}
        if m5[-1]["close"] < m5[-1]["open"] and m5[-2]["close"] < m5[-2]["open"] and c5 >= 55:
            return {"signal": "SELL ACCEL", "confidence": c5}

    return {"signal": "CZEKAJ (KONFLIKT)" if (("BUY" in s5 and "SELL" in s15) or ("SELL" in s5 and "BUY" in s15)) else s15, "confidence": c15}

def generate_tp(signal, conf, ref_close, rng):
    mult = 1.4 if conf >= 80 else 1.1 if conf >= 65 else 0.8
    if "BUY" in signal:
        return {"tp1": round(ref_close + rng*0.55*mult, 2), "tp2": round(ref_close + rng*1.1*mult, 2), "tp3": round(ref_close + rng*1.6*mult, 2)}
    if "SELL" in signal:
        return {"tp1": round(ref_close - rng*0.55*mult, 2), "tp2": round(ref_close - rng*1.1*mult, 2), "tp3": round(ref_close - rng*1.6*mult, 2)}
    return {}

@app.post("/voice-parse")
def voice_parse(rec: VoiceRecord):
    if not rec.time: rec.time = datetime.now().strftime("%H:%M")
    t, tf = rec.ticker.upper().strip(), rec.interval.upper()
    if t not in memory: memory[t] = {"global_entry": ""}
    if tf not in memory[t]: memory[t][tf] = {"history": [], "last_data": {}}
    if rec.entry is not None: memory[t]["global_entry"] = "" if rec.entry == 0 else str(rec.entry)

    temp = {"ticker": t, "interval": tf, "time": rec.time, "open": rec.open, "high": rec.high, "low": rec.low, "close": rec.close, "volume": rec.volume, "ma20": rec.ma20, "dema9": rec.dema9, "rsi": rec.rsi}
    memory[t][tf]["history"].append(temp)
    if len(memory[t][tf]["history"]) > HISTORY_LIMITS.get(tf, 5): memory[t][tf]["history"].pop(0)

    analysis = calc_confidence(rec, memory[t][tf]["history"])
    temp.update(analysis)
    consensus = get_final_consensus(t)
    
    final_signal = consensus["signal"]
    confidence = consensus["confidence"]
    
    interpretation = "STÓJ Z BOKU. Rynek szuka kierunku."
    if confidence >= 75:
        interpretation = "MOCNY SYGNAŁ! Wszystkie warunki spełnione. Można wchodzić."
    elif confidence >= 55:
        interpretation = "DOBRY MOMENT, ale pilnuj trendu. Możliwa szybka akcja."
    elif "KONFLIKT" in final_signal:
        interpretation = "ZAKAZ WEJŚCIA! M5 i M15 walczą ze sobą."

    comment = (
        f"--- 🎙️ RAPORT 8.1 HYBRID ---\n\n"
        f"📌 WERDYKT: {final_signal}\n"
        f"🔥 PEWNOŚĆ: {confidence}% "
        f"({'Wysoka' if confidence >= 70 else 'Średnia' if confidence >= 45 else 'Niska'})\n\n"
        f"📈 ANALIZA TECHNICZNA:\n"
        f"• Trend: {analysis['trend']}\n"
        f"• Stan: {analysis['market_state']}\n"
        f"• RSI: {rec.rsi:.1f}\n"
        f"• Wolumen: {'WYSOKI' if analysis.get('vol_spike', 1) > 1.2 else 'Stabilny'}\n\n"
        f"💡 CO ROBIĆ:\n{interpretation}"
    )

    data = temp.copy()
    data.update({"signal": final_signal, "confidence": confidence, "entry": memory[t]["global_entry"], "comment": comment})

    m15_h = memory[t].get("M15", {}).get("history", [])
    if m15_h:
        ref = m15_h[-1]
        rng = ref["high"] - ref["low"]
        data["widelki"] = f"{ref['low'] + rng*0.18:.2f} - {ref['low'] + rng*0.32:.2f}"
        data.update(generate_tp(data["signal"], data["confidence"], ref["close"], rng))

    memory[t][tf]["last_data"] = data
    return data

@app.post("/voice-parse/delete")
def voice_delete(req: DeleteReq):
    if req.ticker.upper() in memory: del memory[req.ticker.upper()]
    return {"deleted": True}

@app.get("/memory")
def memory_view(): return memory

@app.get("/")
def root(): return {"name": "VOICE XTB 8.1 HYBRID", "status": "ONLINE"}
