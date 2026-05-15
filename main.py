VOICE XTB 8.0 PRO — CONSENSUS ENGINE
======================================================
IMPORTY I KONFIGURACJA
======================================================

from fastapi import FastAPI from fastapi.middleware.cors import CORSMiddleware from pydantic import BaseModel, Field from typing import Dict, Optional, List from datetime import datetime

app = FastAPI( title="VOICE XTB 8.0 PRO", version="8.0" )

======================================================
CORS
======================================================

app.add_middleware( CORSMiddleware, allow_origins=[""], allow_credentials=True, allow_methods=[""], allow_headers=["*"], )

======================================================
PAMIĘĆ
======================================================

memory: Dict[str, Dict] = {}

HISTORY_LIMITS = { "M5": 14, "M15": 7, "H1": 3 }

======================================================
MODELE
======================================================

class VoiceRecord(BaseModel): ticker: str = Field(..., min_length=1) interval: str time: Optional[str] = None

open: float
low: float
high: float
close: float

volume: float
ma20: float
dema9: float
rsi: float

entry: Optional[float] = None

class DeleteReq(BaseModel): ticker: str

======================================================
HELPERS
======================================================

def safe_div(a, b): if b == 0: return 0 return a / b

def avg(values): if not values: return 0 return sum(values) / len(values)

======================================================
TREND DETECTION
======================================================

def trend_direction(history: List[Dict]) -> str: if len(history) < 3: return "NEUTRAL"

closes = [x["close"] for x in history[-3:]]
dema = [x["dema9"] for x in history[-3:]]

close_slope = closes[-1] - closes[0]
dema_slope = dema[-1] - dema[0]

if close_slope > 0 and dema_slope > 0:
    return "UP"

if close_slope < 0 and dema_slope < 0:
    return "DOWN"

return "NEUTRAL"

======================================================
MARKET STATE
======================================================

def detect_market_state(rec: VoiceRecord, history: List[Dict]) -> str: if len(history) < 3: return "UNKNOWN"

candle_range = rec.high - rec.low

recent_ranges = [
    abs(x["high"] - x["low"])
    for x in history[-3:]
]

avg_range = avg(recent_ranges)

if avg_range == 0:
    return "RANGE"

volatility_ratio = candle_range / avg_range

dema_distance = abs(rec.dema9 - rec.ma20)

if volatility_ratio > 1.8:
    return "BREAKOUT"

if volatility_ratio > 2.5:
    return "CHAOS"

if dema_distance < (avg_range * 0.15):
    return "RANGE"

trend = trend_direction(history)

if trend in ["UP", "DOWN"]:
    return "TREND"

return "RANGE"

======================================================
RSI MOMENTUM
======================================================

def rsi_momentum(history: List[Dict]) -> float: if len(history) < 2: return 0

return history[-1]["rsi"] - history[-2]["rsi"]

======================================================
VOLUME SPIKE
======================================================

def volume_spike(rec: VoiceRecord, history: List[Dict]) -> float: if len(history) < 3: return 1

volumes = [x.get("volume", 0) for x in history[-3:]]
avg_volume = avg(volumes)

if avg_volume == 0:
    return 1

return rec.volume / avg_volume

======================================================
CANDLE STRENGTH
======================================================

def candle_strength(rec: VoiceRecord) -> float: rng = rec.high - rec.low

if rng <= 0:
    return 0

body = abs(rec.close - rec.open)

return body / rng

======================================================
CONFIDENCE ENGINE
======================================================

def calc_confidence(rec: VoiceRecord, history: List[Dict]) -> Dict: score = 0

trend = trend_direction(history)
market_state = detect_market_state(rec, history)

rsi_delta = rsi_momentum(history)
vol_spike = volume_spike(rec, history)

strength = candle_strength(rec)

# ==================================================
# TREND
# ==================================================

if trend == "UP" and rec.close > rec.dema9:
    score += 20

if trend == "DOWN" and rec.close < rec.dema9:
    score += 20

# ==================================================
# MA ALIGNMENT
# ==================================================

if rec.dema9 > rec.ma20:
    score += 10

if rec.dema9 < rec.ma20:
    score += 10

# ==================================================
# RSI MOMENTUM
# ==================================================

if rec.rsi > 52 and rsi_delta > 0:
    score += 15

if rec.rsi < 48 and rsi_delta < 0:
    score += 15

# ==================================================
# VOLUME
# ==================================================

if vol_spike > 1.2:
    score += 15

if vol_spike > 1.6:
    score += 10

# ==================================================
# CANDLE QUALITY
# ==================================================

if strength > 0.6:
    score += 15

# ==================================================
# MARKET STATE
# ==================================================

if market_state == "BREAKOUT":
    score += 15

if market_state == "CHAOS":
    score -= 20

if market_state == "RANGE":
    score -= 10

# ==================================================
# FINAL SIGNAL
# ==================================================

signal = "CZEKAJ"

if trend == "UP":
    if score >= 80:
        signal = "BUY PREMIUM"
    elif score >= 65:
        signal = "BUY AGRESYWNY"
    elif score >= 50:
        signal = "PRAWIE BUY"

elif trend == "DOWN":
    if score >= 80:
        signal = "SELL PREMIUM"
    elif score >= 65:
        signal = "SELL AGRESYWNY"
    elif score >= 50:
        signal = "PRAWIE SELL"

return {
    "signal": signal,
    "confidence": max(0, min(100, score)),
    "trend": trend,
    "market_state": market_state,
    "rsi_delta": round(rsi_delta, 2),
    "volume_spike": round(vol_spike, 2),
    "candle_strength": round(strength, 2)
}

======================================================
KONSENSUS MTF
======================================================

def get_final_consensus(ticker: str): t_data = memory.get(ticker, {})

m5 = t_data.get("M5", {}).get("history", [])
m15 = t_data.get("M15", {}).get("history", [])

if not m5:
    return {
        "signal": "CZEKAJ",
        "confidence": 0
    }

last_m5 = m5[-1]

if not m15:
    return {
        "signal": last_m5.get("signal", "CZEKAJ"),
        "confidence": last_m5.get("confidence", 0)
    }

last_m15 = m15[-1]

s5 = last_m5.get("signal", "CZEKAJ")
s15 = last_m15.get("signal", "CZEKAJ")

c5 = last_m5.get("confidence", 0)
c15 = last_m15.get("confidence", 0)

# ==================================================
# STRONG ALIGNMENT
# ==================================================

if "BUY" in s5 and "BUY" in s15:
    return {
        "signal": "BUY STRONG",
        "confidence": round((c5 + c15) / 2)
    }

if "SELL" in s5 and "SELL" in s15:
    return {
        "signal": "SELL STRONG",
        "confidence": round((c5 + c15) / 2)
    }

# ==================================================
# M5 ACCELERATION
# ==================================================

if len(m5) >= 2:
    prev = m5[-2]
    now = m5[-1]

    bullish = (
        now["close"] > now["open"] and
        prev["close"] > prev["open"]
    )

    bearish = (
        now["close"] < now["open"] and
        prev["close"] < prev["open"]
    )

    if bullish and c5 >= 60:
        return {
            "signal": "BUY ACCEL",
            "confidence": c5
        }

    if bearish and c5 >= 60:
        return {
            "signal": "SELL ACCEL",
            "confidence": c5
        }

# ==================================================
# CONFLICT
# ==================================================

if (
    ("BUY" in s5 and "SELL" in s15) or
    ("SELL" in s5 and "BUY" in s15)
):
    return {
        "signal": "CZEKAJ (KONFLIKT)",
        "confidence": 25
    }

return {
    "signal": s15,
    "confidence": c15
}

======================================================
KOMENTARZ PRO
======================================================

def generate_comment(rec, final_signal, confidence, trend, market_state): rsi_status = ( "WYKUPIONY" if rec.rsi > 70 else "WYPRZEDANY" if rec.rsi < 30 else "NEUTRALNY" )

interpretation = "STÓJ Z BOKU"

if "BUY" in final_signal:
    interpretation = "SZUKAJ LONG"

if "SELL" in final_signal:
    interpretation = "SZUKAJ SHORT"

return (
    f"--- VOICE XTB 8.0 PRO ---\n\n"
    f"SYGNAŁ: {final_signal}\n"
    f"CONFIDENCE: {confidence}%\n"
    f"TREND: {trend}\n"
    f"MARKET STATE: {market_state}\n"
    f"RSI: {rec.rsi:.1f} ({rsi_status})\n"
    f"CLOSE: {rec.close}\n"
    f"DEMA9: {rec.dema9}\n"
    f"MA20: {rec.ma20}\n\n"
    f"INTERPRETACJA: {interpretation}\n"
)

======================================================
DYNAMIC TP
======================================================

def generate_tp(final_signal, confidence, ref_close, rng): multiplier = 1

if confidence >= 80:
    multiplier = 1.4

elif confidence >= 65:
    multiplier = 1.1

else:
    multiplier = 0.8

if "BUY" in final_signal:
    return {
        "tp1": round(ref_close + rng * 0.55 * multiplier, 2),
        "tp2": round(ref_close + rng * 1.1 * multiplier, 2),
        "tp3": round(ref_close + rng * 1.6 * multiplier, 2)
    }

if "SELL" in final_signal:
    return {
        "tp1": round(ref_close - rng * 0.55 * multiplier, 2),
        "tp2": round(ref_close - rng * 1.1 * multiplier, 2),
        "tp3": round(ref_close - rng * 1.6 * multiplier, 2)
    }

return {}

======================================================
GŁÓWNY ENDPOINT
======================================================

@app.post("/voice-parse") def voice_parse(rec: VoiceRecord):

if not rec.time:
    rec.time = datetime.now().strftime("%H:%M")

ticker = rec.ticker.upper().strip()
tf = rec.interval.upper()

if ticker not in memory:
    memory[ticker] = {
        "global_entry": ""
    }

if tf not in memory[ticker]:
    memory[ticker][tf] = {
        "history": [],
        "last_data": {}
    }

if rec.entry is not None:
    memory[ticker]["global_entry"] = (
        "" if rec.entry == 0 else str(rec.entry)
    )

history = memory[ticker][tf]["history"]

# ==================================================
# TEMP DATA
# ==================================================

temp = {
    "ticker": ticker,
    "interval": tf,
    "time": rec.time,

    "open": rec.open,
    "high": rec.high,
    "low": rec.low,
    "close": rec.close,

    "volume": rec.volume,
    "ma20": rec.ma20,
    "dema9": rec.dema9,
    "rsi": rec.rsi
}

history.append(temp)

limit = HISTORY_LIMITS.get(tf, 5)

if len(history) > limit:
    history.pop(0)

# ==================================================
# ANALIZA
# ==================================================

analysis = calc_confidence(rec, history)

temp.update(analysis)

consensus = get_final_consensus(ticker)

final_signal = consensus["signal"]
confidence = consensus["confidence"]

# ==================================================
# OUTPUT
# ==================================================

data = temp.copy()

data["signal"] = final_signal
data["confidence"] = confidence

data["entry"] = memory[ticker]["global_entry"]

data["comment"] = generate_comment(
    rec,
    final_signal,
    confidence,
    analysis["trend"],
    analysis["market_state"]
)

# ==================================================
# M15 REFERENCE
# ==================================================

m15_history = memory[ticker].get("M15", {}).get("history", [])

if m15_history:
    ref = m15_history[-1]

    rng = ref["high"] - ref["low"]

    data["widelki"] = (
        f"{ref['low'] + rng*0.18:.2f} - "
        f"{ref['low'] + rng*0.32:.2f}"
    )

    tp = generate_tp(
        final_signal,
        confidence,
        ref["close"],
        rng
    )

    data.update(tp)

memory[ticker][tf]["last_data"] = data

return data

======================================================
DELETE
======================================================

@app.post("/voice-parse/delete") def voice_delete(req: DeleteReq):

ticker = req.ticker.upper()

if ticker in memory:
    del memory[ticker]

return {
    "deleted": True
}

======================================================
MEMORY VIEW
======================================================

@app.get("/memory") def memory_view(): return memory

======================================================
ROOT
======================================================

@app.get("/") def root(): return { "name": "VOICE XTB 8.0 PRO", "status": "ONLINE" }
