from datetime import datetime
from typing import Dict, List, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="VOICE XTB 8.2 GPW LONG PRO",
    version="8.2.2-WEIGHTED-HYBRID"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

memory: Dict[str, Dict] = {}

HISTORY_LIMITS = {
    "M5": 18,
    "M15": 10,
    "H1": 5,
    "D1": 5,
}

TURNOVER_LIMITS = {
    "M5": 20000.0,
    "M15": 75000.0,
    "H1": 200000.0,
    "D1": 600000.0,
}

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
    if len(history) < 3:
        return "NEUTRAL"
    closes = [x["close"] for x in history[-3:]]
    dema = [x["dema9"] for x in history[-3:]]
    c_slope = closes[-1] - closes[0]
    d_slope = dema[-1] - dema[0]
    if c_slope > 0 and d_slope > 0:
        return "UP"
    if c_slope < 0 and d_slope < 0:
        return "DOWN"
    return "NEUTRAL"

def detect_market_state(rec: VoiceRecord, history: List[Dict]) -> str:
    if not history:
        return "UNKNOWN"
    c_range = rec.high - rec.low
    avg_range = avg([abs(x["high"] - x["low"]) for x in history[-3:]])
    if avg_range == 0:
        return "RANGE"
    vol_ratio = c_range / avg_range
    if vol_ratio > 2.8:
        return "CHAOS"
    if vol_ratio > 1.55:
        return "BREAKOUT"
    if abs(rec.dema9 - rec.ma20) < (avg_range * 0.12):
        return "RANGE"
    return "TREND" if trend_direction(history) != "NEUTRAL" else "RANGE"

def calc_confidence(rec: VoiceRecord, history: List[Dict]) -> Dict:
    turnover = float(rec.close * rec.volume)
    min_required_turnover = TURNOVER_LIMITS.get(rec.interval.upper(), 20000.0)

    if turnover < min_required_turnover:
        return {
            "signal": "BRAK PŁYNNOŚCI",
            "confidence": 0,
            "trend": "UNKNOWN",
            "market_state": "ILLIQUID",
            "vol_spike": 0.0,
            "turnover": turnover,
        }

    trend = trend_direction(history)
    market_state = detect_market_state(rec, history)
    rsi_delta = rec.rsi - history[-1]["rsi"] if history else 0
    avg_vol = avg([x.get("volume", 0) for x in history[-3:]])
    vol_spike = rec.volume / avg_vol if avg_vol > 0 else 1.0
    candle_range = rec.high - rec.low
    strength = (abs(rec.close - rec.open) / candle_range) if candle_range > 0 else 0
    close_at_high = ((rec.close - rec.low) / candle_range) if candle_range > 0 else 0

    score_agg = 0
    if trend == "UP" and rsi_delta > 0:
        score_agg += 25
    if vol_spike > 1.15:
        score_agg += 25
    if strength > 0.38:
        score_agg += 20
    if close_at_high > 0.72:
        score_agg += 15
    if market_state == "BREAKOUT":
        score_agg += 15
    score_agg = max(0, min(100, score_agg))

    score_con = 0
    if trend == "UP" and rec.close > rec.dema9:
        score_con += 40
    if rec.dema9 > rec.ma20 and rec.close > rec.ma20:
        score_con += 30
    if 52 <= rec.rsi <= 72:
        score_con += 30
        
    if trend == "DOWN":
        score_con -= 30
    if rec.rsi > 78:
        score_con -= 25
    if market_state == "CHAOS":
        score_con -= 20
    if market_state == "RANGE":
        score_con -= 5
    score_con = max(0, min(100, score_con))

    score = round((score_agg * 0.625) + (score_con * 0.375))

    signal = "CZEKAJ"
    if score >= 68:
        signal = "BUY PREMIUM"
    elif score >= 48:
        signal = "BUY AGRESYWNY"
    elif score >= 36:
        signal = "PRAWIE BUY"
    elif trend == "DOWN" or score < 25:
        signal = "TREND SŁABNIE"

    return {
        "signal": signal,
        "confidence": max(0, min(100, score)),
        "trend": trend,
        "market_state": market_state,
        "vol_spike": vol_spike,
        "turnover": turnover,
    }

def get_final_consensus(ticker: str, current_tf: str, current_signal: str, current_conf: int):
    t_data = memory.get(ticker, {})
    m5 = t_data.get("M5", {}).get("history", [])
    m15 = t_data.get("M15", {}).get("history", [])
    h1 = t_data.get("H1", {}).get("history", [])
    d1 = t_data.get("D1", {}).get("history", [])

    if current_signal == "BRAK PŁYNNOŚCI":
        return {"signal": "BRAK PŁYNNOŚCI", "confidence": 0}

    if not m5:
        return {"signal": current_signal, "confidence": current_conf}

    last_m5 = m5[-1]
    s5 = last_m5.get("signal", "CZEKAJ")
    c5 = last_m5.get("confidence", 0)

    if s5 == "BRAK PŁYNNOŚCI" and current_tf != "M5":
        s5 = current_signal
        c5 = current_conf

    d1_trend = "NEUTRAL"
    if d1:
        d1_rec = d1[-1]
        if d1_rec.get("close", 0) > d1_rec.get("ma20", 0) and d1_rec.get("close", 0) > d1_rec.get("dema9", 0):
            d1_trend = "UP"
        elif d1_rec.get("close", 0) < d1_rec.get("ma20", 0):
            d1_trend = "DOWN"

    h1_trend = "NEUTRAL"
    if h1:
        h1_rec = h1[-1]
        if h1_rec.get("close", 0) > h1_rec.get("ma20", 0) and h1_rec.get("close", 0) > h1_rec.get("dema9", 0):
            h1_trend = "UP"
        elif h1_rec.get("close", 0) < h1_rec.get("ma20", 0):
            h1_trend = "DOWN"

    if d1_trend == "UP" and h1_trend == "UP":
        if "BUY" in s5:
            return {"signal": "BUY PREMIUM", "confidence": min(100, c5 + 15)}
        elif s5 in ["CZEKAJ", "TREND SŁABNIE"] and current_conf > 30:
            return {"signal": "KOREKTA W HOSSIE (BUY ON DIP)", "confidence": 65}

    if d1_trend == "DOWN" or h1_trend == "DOWN":
        if "BUY" in s5:
            return {"signal": "BUY AGRESYWNY (KONTRA TREND D1)", "confidence": max(35, c5 - 20)}

    if "BUY" in s5:
        return {"signal": s5, "confidence": c5}

    return {"signal": current_signal, "confidence": current_conf}

def generate_tp(signal, conf, ref_close, rng):
    if signal == "BRAK PŁYNNOŚCI":
        return {}
    mult = 1.3 if conf >= 80 else 1.0 if conf >= 65 else 0.75
    if "BUY" in signal or "KOREKTA" in signal:
        return {
            "tp1": round(ref_close + rng * 0.50 * mult, 2),
            "tp2": round(ref_close + rng * 1.0 * mult, 2),
            "tp3": round(ref_close + rng * 1.5 * mult, 2),
        }
    return {}

def safe_time_sort(time_str: str) -> str:
    if "-" in time_str:
        return time_str
    return f"0000-00-00 {time_str}"

@app.post("/voice-parse")
def voice_parse(rec: VoiceRecord):
    if not rec.time:
        rec.time = datetime.now().strftime("%H:%M")

    t = rec.ticker.upper().strip()
    tf = rec.interval.upper()

    if t not in memory:
        memory[t] = {
            "global_entry": "",
            "M5": {"history": [], "last_data": {}},
            "M15": {"history": [], "last_data": {}},
            "H1": {"history": [], "last_data": {}},
            "D1": {"history": [], "last_data": {}},
        }

    if tf not in memory[t]:
        memory[t][tf] = {"history": [], "last_data": {}}

    if rec.entry is not None:
        if rec.entry <= 0:
            memory[t]["global_entry"] = ""
        else:
            memory[t]["global_entry"] = str(rec.entry)

    temp = {
        "ticker": t,
        "interval": tf,
        "time": rec.time,
        "open": rec.open,
        "high": rec.high,
        "low": rec.low,
        "close": rec.close,
        "volume": rec.volume,
        "ma20": rec.ma20,
        "dema9": rec.dema9,
        "rsi": rec.rsi,
    }

    analysis = calc_confidence(rec, memory[t][tf]["history"])
    temp.update(analysis)

    history_list = memory[t][tf]["history"]
    existing_index = next((i for i, item in enumerate(history_list) if item["time"] == rec.time), None)

    if existing_index is not None:
        history_list[existing_index] = temp
    else:
        history_list.append(temp)

    history_list.sort(key=lambda x: safe_time_sort(x["time"]))

    if len(history_list) > HISTORY_LIMITS.get(tf, 5):
        history_list.pop(0)

    consensus = get_final_consensus(t, tf, analysis["signal"], analysis["confidence"])
    final_signal = consensus["signal"]
    confidence = consensus["confidence"]

    memory[t][tf]["last_data"] = temp.copy()
    memory[t][tf]["last_data"].update({"signal": final_signal, "confidence": confidence})

    m5_last = memory[t]["M5"].get("last_data", {})
    m15_last = memory[t]["M15"].get("last_data", {})

    str_m15 = "BRAK DANYCH STRUKTURALNYCH M15"
    str_m5 = "BRAK DANYCH STRUKTURALNYCH M5"
    wniosek = "Oczekiwanie na komplet danych z interwałów M5 oraz M15."
    
    if m15_last:
        c_m15 = m15_last.get('close', 0)
        d_m15 = m15_last.get('dema9', 0)
        m_m15 = m15_last.get('ma20', 0)
        r_m15 = m15_last.get('rsi', 0)
        
        rel_dema15 = "wróciła pod DEMA9" if c_m15 < d_m15 else "utrzymuje się nad DEMA9"
        rel_ma15 = "daleko pod ceną → trend średnioterminowy nadal silny" if c_m15 > m_m15 else "w pobliżu lub pod MA20"
        rel_rsi15 = "→ momentum nadal dodatnie, nie ma załamania" if r_m15 >= 60 else "→ momentum ulega osłabieniu"
        
        str_m15 = (
            f"- Cena: {c_m15:.2f}\n"
            f"- DEMA9: {d_m15:.2f}\n"
            f"- MA20: {m_m15:.2f}\n"
            f"- RSI: {r_m15:.1f}\n\n"
            f"Interpretacja systemowa:\n"
            f"- Cena {rel_dema15}, ale:\n"
            f"- MA20 jest {rel_ma15}\n"
            f"- RSI {r_m15:.1f} {rel_rsi15}\n"
            f"- Brak agresywnej podaży strukturalnej."
        )

    if m5_last:
        c_m5 = m5_last.get('close', 0)
        d_m5 = m5_last.get('dema9', 0)
        m_m5 = m5_last.get('ma20', 0)
        r_m5 = m5_last.get('rsi', 0)
        
        rel_ma5 = "jest nad ceną → to normalne w korekcie" if m_m5 > c_m5 else "jest pod ceną → popyt dominuje"
        rel_rsi5 = "→ momentum schłodzone, ale nie słabe" if 40 <= r_m5 <= 59 else f"→ momentum na poziomie {r_m5:.1f}"
        
        str_m5 = (
            f"- Cena: {c_m5:.2f}\n"
            f"- DEMA9: {d_m5:.2f}\n"
            f"- MA20: {m_m5:.2f}\n"
            f"- RSI: {r_m5:.1f}\n\n"
            f"Interpretacja systemowa:\n"
            f"- Cena testuje DEMA9 M5\n"
            f"- MA20 M5 {rel_ma5}\n"
            f"- RSI {r_m5:.1f} {rel_rsi5}"
        )

    if "BUY" in final_signal or "KOREKTA" in final_signal:
        wniosek = (
            "🔥 To jest KOREKTA IMPULSU, nie odwrócenie trendu.\n"
            "🔥 Struktura nadal jest wzrostowa.\n"
            "🔥 System nie widzi sygnału słabości strukturalnej."
        )
    elif "SŁABNIE" in final_signal:
        wniosek = (
            "⚠️ System wykrywa strukturalne osłabienie popytu.\n"
            "⚠️ Zwiększone ryzyko dystrybucji na wyższym interwale."
        )

    tp1_v = tp2_v = tp3_v = "—"
    m15_h = memory[t].get("M15", {}).get("history", [])
    if m15_h and final_signal != "BRAK PŁYNNOŚCI":
        ref = m15_h[-1]
        rng = ref["high"] - ref["low"]
        tp_d = generate_tp(final_signal, confidence, ref["close"], rng)
        tp1_v = f"{tp_d.get('tp1', 0):.2f}" if tp_d.get('tp1') else "—"
        tp2_v = f"{tp_d.get('tp2', 0):.2f}" if tp_d.get('tp2') else "—"
        tp3_v = f"{tp_d.get('tp3', 0):.2f}" if tp_d.get('tp3') else "—"

    comment = (
        f"--- 🎙️ RAPORT HYBRYDOWY STRUKTURALNY ({t}) ---\n"
        f"📌 WERDYKT: {final_signal} ({confidence}%)\n\n"
        f"1. STRUKTURA (M15)\n{str_m15}\n\n"
        f"📌 2. STRUKTURA (M5)\n{str_m5}\n\n"
        f"⭐ GŁÓWNY WNIOSEK SYSTEMOWY TERAZ\n{wniosek}\n\n"
        f"⭐ LOGICZNE TP WG SYSTEMU (czysto techniczne)\n"
        f"| TP  | Poziom   | Logika |\n"
        f"|-----|----------|--------|\n"
        f"| TP1 | {tp1_v}   | powrót do DEMA9 M15 + opór intraday |\n"
        f"| TP2 | {tp2_v}   | pełny zasięg impulsu M15/H1 |\n"
        f"| TP3 | {tp3_v}   | rozszerzenie impulsu, jeśli momentum wróci |\n\n"
        f"Struktura = wzrostowa | Korekta = normalna, nieagresywna | Momentum = nie zgasło"
    )

    data = temp.copy()
    data.update({
        "signal": final_signal,
        "confidence": confidence,
        "entry": memory[t]["global_entry"],
        "comment": comment,
    })

    if m15_h and final_signal != "BRAK PŁYNNOŚCI":
        ref = m15_h[-1]
        rng = ref["high"] - ref["low"]
        data["widelki"] = f"{ref['low'] + rng*0.16:.2f} - {ref['low'] + rng*0.36:.2f}"
        data.update(generate_tp(data["signal"], data["confidence"], ref["close"], rng))

    memory[t][tf]["last_data"] = data
    return data

@app.post("/voice-parse/delete")
def voice_delete(req: DeleteReq):
    t_upper = req.ticker.upper().strip()
    if t_upper in memory:
        del memory[t_upper]
    return {"deleted": True, "ticker": t_upper}

@app.get("/memory")
def memory_view():
    return memory

@app.get("/")
def root():
    return {"name": "VOICE XTB 8.2 STRUCTURAL HYBRID", "status": "ONLINE"}
