from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="VOICE XTB 8.2 GPW LONG PRO",
    version="8.2.4-CLEAN-SIGNALS"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

memory: Dict[str, Dict] = {}

# =========================================================
# CONFIG
# =========================================================

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

# =========================================================
# MODELS
# =========================================================

class VoiceRecord(BaseModel):
    ticker: str = Field(..., min_length=1)
    interval: str
    time: Optional[str] = None

    open: float
    high: float
    low: float
    close: float

    volume: float

    ma20: float
    dema9: float
    rsi: float

    entry: Optional[float] = None


class DeleteReq(BaseModel):
    ticker: str


# =========================================================
# HELPERS
# =========================================================

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

    candle_range = rec.high - rec.low

    avg_range = avg([
        abs(x["high"] - x["low"])
        for x in history[-3:]
    ])

    if avg_range == 0:
        return "RANGE"

    vol_ratio = candle_range / avg_range

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
# SIGNAL ENGINE
# =========================================================

def calc_confidence(rec: VoiceRecord, history: List[Dict]) -> Dict:

    turnover = float(rec.close * rec.volume)

    min_required_turnover = TURNOVER_LIMITS.get(
        rec.interval.upper(),
        20000.0
    )

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

    market_state = detect_market_state(
        rec,
        history
    )

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

    # =====================================================
    # AGGRESSIVE SCORE
    # =====================================================

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

    # =====================================================
    # CONSERVATIVE SCORE
    # =====================================================

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

    # =====================================================
    # FINAL SCORE
    # =====================================================

    score = round(
        (score_agg * 0.625) +
        (score_con * 0.375)
    )

    # =====================================================
    # FINAL SIGNALS
    # =====================================================

    signal = "CZEKAJ"

    if score >= 70:
        signal = "BUY"

    elif score >= 52:
        signal = "BUY"

    elif score >= 40:
        signal = "HOLD"

    elif 28 <= score < 40:
        signal = "REDUKUJ"

    elif trend == "DOWN" or score < 28:
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
# CONSENSUS
# =========================================================

def get_final_consensus(
    ticker: str,
    current_tf: str,
    current_signal: str,
    current_conf: int
):

    t_data = memory.get(ticker, {})

    h1 = t_data.get("H1", {}).get("history", [])
    d1 = t_data.get("D1", {}).get("history", [])

    if current_signal == "BRAK PŁYNNOŚCI":

        return {
            "signal": "BRAK PŁYNNOŚCI",
            "confidence": 0
        }

    d1_trend = "NEUTRAL"

    if d1:

        d1_rec = d1[-1]

        if d1_rec.get("close", 0) > d1_rec.get("ma20", 0):
            d1_trend = "UP"

        elif d1_rec.get("close", 0) < d1_rec.get("ma20", 0):
            d1_trend = "DOWN"

    h1_trend = "NEUTRAL"

    if h1:

        h1_rec = h1[-1]

        if h1_rec.get("close", 0) > h1_rec.get("ma20", 0):
            h1_trend = "UP"

        elif h1_rec.get("close", 0) < h1_rec.get("ma20", 0):
            h1_trend = "DOWN"

    # =====================================================
    # TREND FILTER
    # =====================================================

    if d1_trend == "UP" and h1_trend == "UP":

        if current_signal == "BUY":

            return {
                "signal": "BUY",
                "confidence": min(100, current_conf + 12)
            }

    if d1_trend == "DOWN" or h1_trend == "DOWN":

        if current_signal == "BUY":

            return {
                "signal": "HOLD",
                "confidence": max(35, current_conf - 18)
            }

        if current_signal == "HOLD":

            return {
                "signal": "REDUKUJ",
                "confidence": current_conf
            }

    return {
        "signal": current_signal,
        "confidence": current_conf
    }


# =========================================================
# TP
# =========================================================

def generate_tp(signal, conf, ref_close, rng):

    if signal == "BRAK PŁYNNOŚCI":
        return {}

    mult = (
        1.3 if conf >= 80
        else 1.0 if conf >= 65
        else 0.75
    )

    if signal in ["BUY", "HOLD"]:

        return {
            "tp1": round(ref_close + rng * 0.50 * mult, 2),
            "tp2": round(ref_close + rng * 1.00 * mult, 2),
            "tp3": round(ref_close + rng * 1.50 * mult, 2),
        }

    return {}


def safe_time_sort(time_str: str) -> str:

    if "-" in time_str:
        return time_str

    return f"0000-00-00 {time_str}"


# =========================================================
# MAIN
# =========================================================

@app.post("/voice-parse")
def voice_parse(rec: VoiceRecord):

    if not rec.time:
        rec.time = datetime.now().strftime("%H:%M")

    t = rec.ticker.upper().strip()
    tf = rec.interval.upper()

    # =====================================================
    # INIT
    # =====================================================

    if t not in memory:

        memory[t] = {
            "global_entry": "",
            "updated_at": datetime.now().timestamp(),

            "M5": {"history": [], "last_data": {}},
            "M15": {"history": [], "last_data": {}},
            "H1": {"history": [], "last_data": {}},
            "D1": {"history": [], "last_data": {}},
        }

    memory[t]["updated_at"] = datetime.now().timestamp()

    # =====================================================
    # ENTRY
    # =====================================================

    if rec.entry is not None:

        if rec.entry <= 0:
            memory[t]["global_entry"] = ""

        else:
            memory[t]["global_entry"] = str(rec.entry)

    # =====================================================
    # TEMP
    # =====================================================

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

    # =====================================================
    # ANALYSIS
    # =====================================================

    analysis = calc_confidence(
        rec,
        memory[t][tf]["history"]
    )

    temp.update(analysis)

    # =====================================================
    # HISTORY
    # =====================================================

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

    # =====================================================
    # CONSENSUS
    # =====================================================

    consensus = get_final_consensus(
        t,
        tf,
        analysis["signal"],
        analysis["confidence"]
    )

    final_signal = consensus["signal"]
    confidence = consensus["confidence"]

    # =====================================================
    # TP
    # =====================================================

    tp1_v = tp2_v = tp3_v = "—"

    m15_h = memory[t].get("M15", {}).get("history", [])

    if m15_h and final_signal != "BRAK PŁYNNOŚCI":

        ref = m15_h[-1]

        rng = ref["high"] - ref["low"]

        tp_d = generate_tp(
            final_signal,
            confidence,
            ref["close"],
            rng
        )

        tp1_v = (
            f"{tp_d.get('tp1', 0):.2f}"
            if tp_d.get("tp1")
            else "—"
        )

        tp2_v = (
            f"{tp_d.get('tp2', 0):.2f}"
            if tp_d.get("tp2")
            else "—"
        )

        tp3_v = (
            f"{tp_d.get('tp3', 0):.2f}"
            if tp_d.get("tp3")
            else "—"
        )

    # =====================================================
    # QUICK COMMENT
    # =====================================================

    m15_last = memory[t]["M15"].get("last_data", {})
    m5_last = memory[t]["M5"].get("last_data", {})

    trend_label = (
        "WZROSTOWY"
        if final_signal in ["BUY", "HOLD"]
        else "SŁABNIE"
    )

    if final_signal == "BUY":

        quick_text = (
            "Momentum aktywne. "
            "Popyt utrzymuje przewagę."
        )

    elif final_signal == "HOLD":

        quick_text = (
            "Trend nadal aktywny, "
            "ale pojawia się schłodzenie."
        )

    elif final_signal == "REDUKUJ":

        quick_text = (
            "Popyt słabnie. "
            "Rośnie ryzyko głębszej korekty."
        )

    elif final_signal == "SELL":

        quick_text = (
            "Układ techniczny słaby. "
            "Przewaga podaży."
        )

    else:

        quick_text = "Brak wyraźnej przewagi rynku."

    comment = (
        f"🎯 {t} | {final_signal} ({confidence}%)\n\n"

        f"📈 M15\n"
        f"• Cena: {m15_last.get('close', 0):.2f}\n"
        f"• DEMA9: {m15_last.get('dema9', 0):.2f}\n"
        f"• MA20: {m15_last.get('ma20', 0):.2f}\n"
        f"• RSI: {m15_last.get('rsi', 0):.1f}\n\n"

        f"⚡ M5\n"
        f"• Cena: {m5_last.get('close', 0):.2f}\n"
        f"• DEMA9: {m5_last.get('dema9', 0):.2f}\n"
        f"• RSI: {m5_last.get('rsi', 0):.1f}\n\n"

        f"🧠 WNIOSEK\n"
        f"{quick_text}\n\n"

        f"🎯 TP\n"
        f"TP1: {tp1_v}\n"
        f"TP2: {tp2_v}\n"
        f"TP3: {tp3_v}\n\n"

        f"📌 Trend: {trend_label}"
    )

    # =====================================================
    # FINAL DATA
    # =====================================================

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

    # =====================================================
    # SAVE
    # =====================================================

    memory[t][tf]["last_data"] = data

    return data


# =========================================================
# DELETE
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


# =========================================================
# MEMORY
# =========================================================

@app.get("/memory")
def memory_view():
    return memory


# =========================================================
# ROOT
# =========================================================

@app.get("/")
def root():

    return {
        "name": "VOICE XTB 8.2 CLEAN SIGNALS",
        "status": "ONLINE"
    }
