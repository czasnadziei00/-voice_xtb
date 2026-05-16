from datetime import datetime
from typing import Dict, List, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(title="VOICE XTB 8.1 HYBRID", version="8.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

memory: Dict[str, Dict] = {}
HISTORY_LIMITS = {"M5": 14, "M15": 7, "H1": 3, "D1": 2}

TURNOVER_LIMITS = {
    "M5": 50000.0,
    "M15": 150000.0,
    "H1": 400000.0,
    "D1": 1000000.0,
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
    
    if vol_ratio > 2.5:
        return "CHAOS"
    if vol_ratio > 1.8:
        return "BREAKOUT"
        
    if abs(rec.dema9 - rec.ma20) < (avg_range * 0.15):
        return "RANGE"
    return "TREND" if trend_direction(history) != "NEUTRAL" else "RANGE"


def calc_confidence(rec: VoiceRecord, history: List[Dict]) -> Dict:
    turnover = rec.close * rec.volume
    min_required_turnover = TURNOVER_LIMITS.get(rec.interval.upper(), 50000.0)

    if turnover < min_required_turnover:
        return {
            "signal": "NO LIQUIDITY",
            "confidence": 0,
            "trend": "UNKNOWN",
            "market_state": "ILLIQUID",
            "vol_spike": 0.0,
            "turnover": turnover,
        }

    score = 0
    trend = trend_direction(history)
    market_state = detect_market_state(rec, history)
    
    rsi_delta = rec.rsi - history[-1]["rsi"] if history else 0
    
    avg_vol = avg([x.get("volume", 0) for x in history[-3:]])
    vol_spike = rec.volume / avg_vol if avg_vol > 0 else 1.0
    
    strength = (abs(rec.close - rec.open) / (rec.high - rec.low)) if (rec.high - rec.low) > 0 else 0

    if trend == "UP" and rec.close > rec.dema9:
        score += 25
    if trend == "DOWN" and rec.close < rec.dema9:
        score += 25
    if (rec.dema9 > rec.ma20 and trend == "UP") or (
        rec.dema9 < rec.ma20 and trend == "DOWN"
    ):
        score += 10
    if (trend == "UP" and rsi_delta > 0) or (trend == "DOWN" and rsi_delta < 0):
        score += 20
    if vol_spike > 1.05:
        score += 15
    if strength > 0.45:
        score += 15
    if market_state == "BREAKOUT":
        score += 10
    if market_state == "CHAOS":
        score -= 25
    if market_state == "RANGE":
        score -= 2

    signal = "CZEKAJ"
    if trend == "UP":
        if score >= 70:
            signal = "BUY PREMIUM"
        elif score >= 52:
            signal = "BUY AGRESYWNY"
        elif score >= 40:
            signal = "PRAWIE BUY"
    elif trend == "DOWN":
        if score >= 70:
            signal = "EXIT PREMIUM"
        elif score >= 52:
            signal = "REDUKUJ"
        elif score >= 40:
            signal = "TREND SŁABNIE"

    return {
        "signal": signal,
        "confidence": max(0, min(100, score)),
        "trend": trend,
        "market_state": market_state,
        "vol_spike": vol_spike,
        "turnover": turnover,
    }


def get_final_consensus(ticker: str):
    t_data = memory.get(ticker, {})
    m5 = t_data.get("M5", {}).get("history", [])
    m15 = t_data.get("M15", {}).get("history", [])
    h1 = t_data.get("H1", {}).get("history", [])
    d1 = t_data.get("D1", {}).get("history", [])

    if not m5:
        return {"signal": "CZEKAJ", "confidence": 0}

    last_m5 = m5[-1]
    s5, c5 = last_m5.get("signal", "CZEKAJ"), last_m5.get("confidence", 0)

    if s5 == "NO LIQUIDITY":
        return {"signal": "NO LIQUIDITY", "confidence": 0}

    d1_trend = "NEUTRAL"
    if d1:
        d1_rec = d1[-1]
        if (
            d1_rec.get("close", 0) > d1_rec.get("ma20", 0)
            and d1_rec.get("close", 0) > d1_rec.get("dema9", 0)
        ):
            d1_trend = "UP"
        elif (
            d1_rec.get("close", 0) < d1_rec.get("ma20", 0)
            and d1_rec.get("close", 0) < d1_rec.get("dema9", 0)
        ):
            d1_trend = "DOWN"

    h1_trend = "NEUTRAL"
    if h1:
        h1_rec = h1[-1]
        if (
            h1_rec.get("close", 0) > h1_rec.get("ma20", 0)
            and h1_rec.get("close", 0) > h1_rec.get("dema9", 0)
        ):
            h1_trend = "UP"
        elif (
            h1_rec.get("close", 0) < h1_rec.get("ma20", 0)
            and h1_rec.get("close", 0) < h1_rec.get("dema9", 0)
        ):
            h1_trend = "DOWN"

    if not m15:
        if h1_trend == "UP" and "BUY" in s5:
            return {"signal": "M5 BUY (ZGODNY Z H1 WCH)", "confidence": c5}
        if h1_trend == "DOWN" and s5 in ["EXIT PREMIUM", "REDUKUJ"]:
            return {"signal": f"M5 {s5} (ZGODNY Z H1)", "confidence": c5}
        return {"signal": s5, "confidence": c5}

    last_m15 = m15[-1]
    s15, c15 = last_m15.get("signal", "CZEKAJ"), last_m15.get("confidence", 0)

    if s15 == "NO LIQUIDITY":
        return {"signal": "NO LIQUIDITY", "confidence": 0}

    m15_close = last_m15.get("close", 0)
    m15_open = last_m15.get("open", 0)
    m15_high = last_m15.get("high", 0)
    m15_low = last_m15.get("low", 0)

    candle_body = abs(m15_close - m15_open)
    upper_shadow = m15_high - max(m15_open, m15_close)
    lower_shadow = min(m15_open, m15_close) - m15_low

    body_ref = max(candle_body, 0.01)
    is_upper_rejection = upper_shadow > (body_ref * 1.5)
    is_lower_rejection = lower_shadow > (body_ref * 1.5)

    if d1_trend == "UP" and h1_trend == "UP":
        if "BUY" in s5 and not is_upper_rejection:
            return {
                "signal": "BUY PREMIUM",
                "confidence": min(100, round((c5 + c15) / 2) + 10),
            }
        elif is_lower_rejection or m15_close < last_m15.get("dema9", 0):
            return {
                "signal": "BUY ON DIP",
                "confidence": max(0, round((c5 + c15) / 2) - 5),
            }

    elif d1_trend == "DOWN" and h1_trend == "DOWN":
        if s5 in ["EXIT PREMIUM", "REDUKUJ"] and not is_lower_rejection:
            return {
                "signal": "EXIT PREMIUM",
                "confidence": min(100, round((c5 + c15) / 2) + 10),
            }
        elif is_upper_rejection:
            return {
                "signal": "REALIZUJ",
                "confidence": max(0, round((c5 + c15) / 2) - 5),
            }

    elif d1_trend == "DOWN" and h1_trend == "UP":
        if "BUY" in s5 and is_upper_rejection:
            return {"signal": "REALIZUJ (OPÓR D1)", "confidence": 15}
        elif "BUY" in s5:
            return {
                "signal": "BUY KONTRA",
                "confidence": max(10, round((c5 + c15) / 2) - 15),
            }

    elif d1_trend == "UP" and h1_trend == "DOWN":
        if s5 in ["EXIT PREMIUM", "REDUKUJ"] and is_lower_rejection:
            return {"signal": "CZEKAJ (WSPARCIE D1)", "confidence": 20}
        elif s5 in ["EXIT PREMIUM", "REDUKUJ"]:
            return {
                "signal": "REDUKUJ KONTRA",
                "confidence": max(10, round((c5 + c15) / 2) - 15),
            }

    if "BUY" in s5 and "BUY" in s15:
        return {"signal": "BUY STRONG", "confidence": round((c5 + c15) / 2)}
    if s5 in ["EXIT PREMIUM", "REDUKUJ"] and s15 in ["EXIT PREMIUM", "REDUKUJ"]:
        return {"signal": "EXIT STRONG", "confidence": round((c5 + c15) / 2)}

    if len(m5) >= 2:
        if (
            m5[-1]["close"] > m5[-1]["open"]
            and m5[-2]["close"] > m5[-2]["open"]
            and c5 >= 52
        ):
            return {"signal": "BUY ACCEL", "confidence": c5}
        if (
            m5[-1]["close"] < m5[-1]["open"]
            and m5[-2]["close"] < m5[-2]["open"]
            and c5 >= 52
        ):
            return {"signal": "REDUKUJ ACCEL", "confidence": c5}

    return {
        "signal": (
            "REALIZUJ (KONFLIKT)"
            if (
                ("BUY" in s5 and s15 in ["EXIT PREMIUM", "REDUKUJ"])
                or (s5 in ["EXIT PREMIUM", "REDUKUJ"] and "BUY" in s15)
            )
            else s15
        ),
        "confidence": c15,
    }


def generate_tp(signal, conf, ref_close, rng):
    if signal == "NO LIQUIDITY":
        return {}
    mult = 1.4 if conf >= 80 else 1.1 if conf >= 65 else 0.8
    if "BUY" in signal or "STRONG" in signal:
        return {
            "tp1": round(ref_close + rng * 0.55 * mult, 2),
            "tp2": round(ref_close + rng * 1.1 * mult, 2),
            "tp3": round(ref_close + rng * 1.6 * mult, 2),
        }
    if any(keyword in signal for keyword in ["EXIT", "REDUKUJ", "SŁABNIE", "REALIZUJ"]):
        return {
            "tp1": round(ref_close - rng * 0.55 * mult, 2),
            "tp2": round(ref_close - rng * 1.1 * mult, 2),
            "tp3": round(ref_close - rng * 1.6 * mult, 2),
        }
    return {}


@app.post("/voice-parse")
def voice_parse(rec: VoiceRecord):
    if not rec.time:
        rec.time = datetime.now().strftime("%H:%M")
    t, tf = rec.ticker.upper().strip(), rec.interval.upper()
    
    if t not in memory:
        memory[t] = {
            "global_entry": "",
            "M5": {"history": [], "last_data": {}},
            "M15": {"history": [], "last_data": {}},
            "H1": {"history": [], "last_data": {}},
            "D1": {"history": [], "last_data": {}}
        }
        
    if tf not in memory[t]:
        memory[t][tf] = {"history": [], "last_data": {}}

    if rec.entry is not None and rec.entry > 0:
        memory[t]["global_entry"] = str(rec.entry)
    elif rec.entry == 0:
        memory[t]["global_entry"] = ""

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
    
    memory[t][tf]["history"].append(temp)
    if len(memory[t][tf]["history"]) > HISTORY_LIMITS.get(tf, 5):
        memory[t][tf]["history"].pop(0)
    
    consensus = get_final_consensus(t)
    final_signal = consensus["signal"]
    confidence = consensus["confidence"]

    interpretation = "STÓJ Z BOKU. Rynek szuka kierunku."
    if final_signal == "NO LIQUIDITY":
        min_required = TURNOVER_LIMITS.get(tf, 50000.0)
        interpretation = f"BRAK PŁYNNOŚCI! Obrót ({analysis['turnover']:,.2f} PLN) poniżej wymaganego limitu {min_required:,.2f} PLN dla {tf}. Analiza zawieszona."
    elif confidence >= 75:
        if "BUY" in final_signal:
            interpretation = "MOCNY SYGNAŁ! Wszystkie warunki spełnione. Można wchodzić w pozycję długą."
        else:
            interpretation = "KRYTYCZNY SYGNAŁ DECYZYJNY! Maksymalne ryzyko dla pozycji Long. Zabezpiecz kapitał."
    elif confidence >= 52:
        if "BUY" in final_signal:
            interpretation = "DOBRY MOMENT dla pozycji Long, ale pilnuj trendu. Możliwa szybka akcja."
        else:
            interpretation = "WZRASTAJĄCA SŁABOŚĆ RYNKU. Rozważ częściowe zamknięcie lub zacieśnienie Stop Loss."
    elif "KONFLIKT" in final_signal or "REALIZUJ" in final_signal:
        interpretation = "NIESTABILNOŚĆ! Walka popytu z podażą na interwałach. Dobry moment na realizację zysków."

    comment = (
        f"--- 🎙️ RAPORT 8.1 HYBRID (DOJI CORRECTION) ---\n\n"
        f"📌 WERDYKT: {final_signal}\n"
        f"🔥 PEWNOŚĆ: {confidence}% "
        f"({'Wysoka' if confidence >= 70 else 'Średnia' if confidence >= 52 else 'Niska'})\n\n"
        f"📈 ANALIZA TECHNICZNA:\n"
        f"• Trend: {analysis['trend']}\n"
        f"• Stan: {analysis['market_state']}\n"
        f"• RSI: {rec.rsi:.1f}\n"
        f"• Obrót świecy: {analysis.get('turnover', 0):,.2f} PLN\n"
        f"• Wolumen: {rec.volume:.0f} szt. ({'Prawidłowy' if final_signal != 'NO LIQUIDITY' else 'ZA NISKI OBRÓT'})\n\n"
        f"💡 CO ROBIĆ:\n{interpretation}"
    )

    data = temp.copy()
    data.update(
        {
            "signal": final_signal,
            "confidence": confidence,
            "entry": memory[t]["global_entry"],
            "comment": comment,
        }
    )

    m15_h = memory[t].get("M15", {}).get("history", [])
    if m15_h and final_signal != "NO LIQUIDITY":
        ref = m15_h[-1]
        rng = ref["high"] - ref["low"]
        data["widelki"] = (
            f"{ref['low'] + rng*0.18:.2f} - {ref['low'] + rng*0.32:.2f}"
        )
        data.update(
            generate_tp(data["signal"], data["confidence"], ref["close"], rng)
        )

    memory[t][tf]["last_data"] = data
    return data


@app.post("/voice-parse/delete")
def voice_delete(req: DeleteReq):
    if req.ticker.upper() in memory:
        del memory[req.ticker.upper()]
    return {"deleted": True}


@app.get("/memory")
def memory_view():
    return memory


@app.get("/")
def root():
    return {"name": "VOICE XTB 8.1 HYBRID", "status": "ONLINE"}
