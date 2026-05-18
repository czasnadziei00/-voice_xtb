from datetime import datetime
from typing import Dict, List, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="VOICE XTB 8.3 PURE SIGNAL",
    version="8.3.0-PURE-SIGNALS"
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

    avg_range = avg([
        abs(x["high"] - x["low"])
        for x in history[-3:]
    ])

    if avg_range == 0:
        return "RANGE"

    vol_ratio = c_range / avg_range

    if vol_ratio > 2.8:
        return "CHAOS"

    if vol_ratio > 1.55:
        return "BREAKOUT"

    if abs(rec.dema9 - rec.ma20) < (avg_range * 0.12):
        return "RANGE"

    return (
        "TREND"
        if trend_direction(history) != "NEUTRAL"
        else "RANGE"
    )

# =========================================================
# NOWA CZYSTA LOGIKA SYGNAŁÓW
# BUY / BUY / HOLD / REDUKUJ / SELL
# =========================================================

def calc_confidence(rec: VoiceRecord, history: List[Dict]) -> Dict:

    turnover = float(rec.close * rec.volume)

    min_required_turnover = TURNOVER_LIMITS.get(
        rec.interval.upper(),
        20000.0
    )

    if turnover < min_required_turnover:

        return {
            "signal": "SELL",
            "confidence": 0,
            "trend": "UNKNOWN",
            "market_state": "ILLIQUID",
            "vol_spike": 0.0,
            "turnover": turnover,
        }

    trend = trend_direction(history)

    market_state = detect_market_state(rec, history)

    rsi_delta = (
        rec.rsi - history[-1]["rsi"]
        if history else 0
    )

    avg_vol = avg([
        x.get("volume", 0)
        for x in history[-3:]
    ])

    vol_spike = (
        rec.volume / avg_vol
        if avg_vol > 0 else 1.0
    )

    candle_range = rec.high - rec.low

    strength = (
        abs(rec.close - rec.open) / candle_range
        if candle_range > 0 else 0
    )

    close_at_high = (
        (rec.close - rec.low) / candle_range
        if candle_range > 0 else 0
    )

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
        score_con -= 35

    if rec.rsi > 78:
        score_con -= 20

    if market_state == "CHAOS":
        score_con -= 20

    score_con = max(0, min(100, score_con))

    score = round(
        (score_agg * 0.625) +
        (score_con * 0.375)
    )

    # =====================================================
    # NOWA PROSTA MAPA SYGNAŁÓW
    # =====================================================

    signal = "HOLD"

    # PREMIUM BUY
    if (
        score >= 72 and
        trend == "UP" and
        rec.close > rec.dema9 and
        rec.dema9 > rec.ma20
    ):
        signal = "BUY"

    # NORMAL BUY
    elif (
        score >= 52 and
        trend == "UP"
    ):
        signal = "BUY"

    # HOLD (momentum)
    elif (
        score >= 38 and
        (
            market_state == "BREAKOUT" or
            vol_spike > 1.2 or
            rec.rsi > 55
        )
    ):
        signal = "HOLD"

    # REDUKUJ
    elif (
        trend == "DOWN" or
        rec.close < rec.dema9 or
        rec.rsi < 45
    ):
        signal = "REDUKUJ"

    # SELL
    elif (
        score < 20 or
        (
            trend == "DOWN" and
            rec.close < rec.ma20 and
            rec.rsi < 38
        )
    ):
        signal = "SELL"

    return {
        "signal": signal,
        "confidence": max(0, min(100, score)),
        "trend": trend,
        "market_state": market_state,
        "vol_spike": vol_spike,
        "turnover": turnover,
    }

# =========================================================

def get_final_consensus(
    ticker: str,
    current_tf: str,
    current_signal: str,
    current_conf: int
):

    t_data = memory.get(ticker, {})

    m5 = t_data.get("M5", {}).get("history", [])
    h1 = t_data.get("H1", {}).get("history", [])
    d1 = t_data.get("D1", {}).get("history", [])

    if not m5:
        return {
            "signal": current_signal,
            "confidence": current_conf
        }

    d1_trend = "NEUTRAL"

    if d1:

        d1_rec = d1[-1]

        if (
            d1_rec.get("close", 0)
            > d1_rec.get("ma20", 0)
        ):
            d1_trend = "UP"

        elif (
            d1_rec.get("close", 0)
            < d1_rec.get("ma20", 0)
        ):
            d1_trend = "DOWN"

    h1_trend = "NEUTRAL"

    if h1:

        h1_rec = h1[-1]

        if (
            h1_rec.get("close", 0)
            > h1_rec.get("ma20", 0)
        ):
            h1_trend = "UP"

        elif (
            h1_rec.get("close", 0)
            < h1_rec.get("ma20", 0)
        ):
            h1_trend = "DOWN"

    # =====================================================
    # WZMOCNIENIE BUY
    # =====================================================

    if (
        current_signal == "BUY" and
        d1_trend == "UP" and
        h1_trend == "UP"
    ):

        return {
            "signal": "BUY",
            "confidence": min(100, current_conf + 12)
        }

    # =====================================================
    # HOLD PRZY MOMENTUM
    # =====================================================

    if (
        current_signal == "HOLD" and
        (
            d1_trend == "UP" or
            h1_trend == "UP"
        )
    ):

        return {
            "signal": "HOLD",
            "confidence": max(45, current_conf)
        }

    # =====================================================
    # REDUKUJ
    # =====================================================

    if (
        current_signal == "REDUKUJ" and
        (
            d1_trend == "DOWN" or
            h1_trend == "DOWN"
        )
    ):

        return {
            "signal": "REDUKUJ",
            "confidence": max(55, current_conf)
        }

    return {
        "signal": current_signal,
        "confidence": current_conf
    }

def generate_tp(signal, conf, ref_close, rng):

    if signal in ["SELL", "REDUKUJ"]:
        return {}

    mult = (
        1.3 if conf >= 80 else
        1.0 if conf >= 65 else
        0.75
    )

    return {
        "tp1": round(
            ref_close + rng * 0.50 * mult,
            2
        ),

        "tp2": round(
            ref_close + rng * 1.0 * mult,
            2
        ),

        "tp3": round(
            ref_close + rng * 1.5 * mult,
            2
        ),
    }

def safe_time_sort(time_str: str) -> str:

    if "-" in time_str:
        return time_str

    return f"0000-00-00 {time_str}"

# =========================================================

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
        memory[t][tf] = {
            "history": [],
            "last_data": {}
        }

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

    analysis = calc_confidence(
        rec,
        memory[t][tf]["history"]
    )

    temp.update(analysis)

    history_list = memory[t][tf]["history"]

    existing_index = next(
        (
            i for i, item in enumerate(history_list)
            if item["time"] == rec.time
        ),
        None
    )

    if existing_index is not None:

        history_list[existing_index] = temp

    else:

        history_list.append(temp)

    history_list.sort(
        key=lambda x: safe_time_sort(x["time"])
    )

    if len(history_list) > HISTORY_LIMITS.get(tf, 5):
        history_list.pop(0)

    consensus = get_final_consensus(
        t,
        tf,
        analysis["signal"],
        analysis["confidence"]
    )

    final_signal = consensus["signal"]

    confidence = consensus["confidence"]

    memory[t][tf]["last_data"] = temp.copy()

    memory[t][tf]["last_data"].update({
        "signal": final_signal,
        "confidence": confidence
    })

    comment = (
        f"--- VOICE XTB 8.3 PURE SIGNAL ---\n"
        f"Ticker: {t}\n"
        f"Signal: {final_signal}\n"
        f"Confidence: {confidence}%\n"
        f"Trend: {analysis['trend']}\n"
        f"Market: {analysis['market_state']}\n"
        f"RSI: {rec.rsi}\n"
        f"Volume Spike: {analysis['vol_spike']:.2f}"
    )

    data = temp.copy()

    data.update({
        "signal": final_signal,
        "confidence": confidence,
        "entry": memory[t]["global_entry"],
        "comment": comment,
    })

    m15_h = memory[t].get(
        "M15",
        {}
    ).get(
        "history",
        []
    )

    if m15_h and final_signal not in ["SELL", "REDUKUJ"]:

        ref = m15_h[-1]

        rng = ref["high"] - ref["low"]

        data["widelki"] = (
            f"{ref['low'] + rng*0.16:.2f}"
            f" - "
            f"{ref['low'] + rng*0.36:.2f}"
        )

        data.update(
            generate_tp(
                data["signal"],
                data["confidence"],
                ref["close"],
                rng
            )
        )

    memory[t][tf]["last_data"] = data

    return data

# =========================================================

@app.post("/voice-parse/delete")
def voice_delete(req: DeleteReq):

    t_upper = req.ticker.upper().strip()

    if t_upper in memory:
        del memory[t_upper]

    return {
        "deleted": True,
        "ticker": t_upper
    }

@app.get("/memory")
def memory_view():
    return memory

@app.get("/")
def root():

    return {
        "name": "VOICE XTB 8.3 PURE SIGNAL",
        "status": "ONLINE"
    }
