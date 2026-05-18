from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="VOICE XTB 9.0 STRUCTURE ENGINE - PRODUCTION",
    version="9.0-INTEGRATED-CONSENSUS"
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
    "M5": 24,
    "M15": 16,
    "H1": 10,
    "D1": 10,
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


def safe_time_sort(time_str: str):
    if "-" in time_str:
        return time_str
    return f"0000-00-00 {time_str}"


# =========================================================
# TREND ENGINE
# =========================================================

def get_trend_state(rec: VoiceRecord):
    if (
        rec.close > rec.ma20 and
        rec.close > rec.dema9 and
        rec.dema9 > rec.ma20 and
        rec.rsi >= 55
    ):
        return "LONG"

    if (
        rec.close < rec.ma20 and
        rec.close < rec.dema9 and
        rec.dema9 < rec.ma20 and
        rec.rsi <= 45
    ):
        return "SHORT"

    return "RANGE"


# =========================================================
# MARKET STATE
# =========================================================

def detect_market_state(rec: VoiceRecord, history: List[Dict]):
    if not history:
        return "NEUTRAL"

    candle_range = rec.high - rec.low
    avg_range = avg([
        abs(x["high"] - x["low"])
        for x in history[-3:]
    ])

    if avg_range <= 0:
        return "RANGE"

    ratio = candle_range / avg_range

    if ratio > 2.8:
        return "CHAOS"
    if ratio > 1.55:
        return "BREAKOUT"

    return "NORMAL"


# =========================================================
# SETUP ENGINE (M15)
# =========================================================

def detect_setup(rec: VoiceRecord):
    if rec.rsi > 78:
        return "OVERHEATED"

    if (
        rec.close > rec.ma20 and
        rec.close > rec.dema9 and
        rec.rsi >= 58
    ):
        return "BREAKOUT"

    if (
        rec.close > rec.ma20 and
        rec.close <= rec.dema9 and
        rec.rsi >= 48
    ):
        return "PULLBACK"

    if (
        rec.rsi >= 45 and
        rec.rsi <= 58 and
        abs(rec.dema9 - rec.ma20) < (rec.close * 0.003)
    ):
        return "ACCUMULATION"

    return "NONE"


# =========================================================
# TRIGGER ENGINE (M5)
# =========================================================

def detect_trigger(rec: VoiceRecord, history: List[Dict]):
    if not history or len(history) < 2:
        return "NO_TRIGGER"

    # Zabezpieczenie przed nadpisywaniem tej samej świecy w tablicy historii
    prev = history[-2] if history[-1]["time"] == rec.time else history[-1]

    bullish_candle = rec.close > rec.open
    rsi_up = rec.rsi > prev["rsi"]
    volume_up = rec.volume > prev["volume"]

    if (
        bullish_candle and
        rsi_up and
        volume_up and
        rec.close > rec.dema9
    ):
        return "ENTRY_TRIGGER"

    if (
        rec.close < rec.dema9 and
        rec.rsi < prev["rsi"]
    ):
        return "WEAK_MOMENTUM"

    return "NO_TRIGGER"


# =========================================================
# FINAL ENGINE (ZBALANSOWANY KONSENSUS WAGOWY)
# =========================================================

def build_final_signal(trend_d1, trend_h1, setup_m15, trigger_m5):
    confidence = 40
    signal = "CZEKAJ"

    # 1. ZABEZPIECZENIE ANTY-KRACHOWE
    if trend_d1 == "SHORT" and trend_h1 == "SHORT":
        return {"signal": "CZEKAJ", "confidence": 10}

    # 2. SCENARIUSZ AWARYJNY: PUŁAPKA NA BYKI (BULL TRAP)
    if setup_m15 == "NONE" and trigger_m5 == "WEAK_MOMENTUM":
        return {"signal": "CZEKAJ", "confidence": 25}

    # 3. PREMIA ZA TREND BAZOWY (D1 / H1)
    if trend_d1 == "LONG": 
        confidence += 15
    if trend_h1 == "LONG": 
        confidence += 10

    # 4. OCENA STRUKTURY INTRADAY (M15)
    if setup_m15 == "PULLBACK":
        confidence += 25
    elif setup_m15 == "ACCUMULATION":
        confidence += 20
    elif setup_m15 == "BREAKOUT":
        confidence += 20
    elif setup_m15 == "OVERHEATED":
        confidence -= 25

    # 5. IMPULS MOMENTUM (M5)
    if trigger_m5 == "ENTRY_TRIGGER":
        confidence += 15
    elif trigger_m5 == "WEAK_MOMENTUM":
        confidence -= 10
    elif trigger_m5 == "NO_TRIGGER":
        confidence += 0

    # PROGI DECYZYJNE
    if confidence >= 65:
        signal = "BUY"
    elif confidence >= 48:
        signal = "HOLD"
    else:
        signal = "CZEKAJ"

    return {
        "signal": signal,
        "confidence": max(0, min(100, confidence))
    }


# =========================================================
# TAKE PROFIT
# =========================================================

def generate_tp(signal, conf, ref_close, rng):
    if signal not in ["BUY", "HOLD"]:
        return {}

    mult = (
        1.3 if conf >= 80
        else 1.0 if conf >= 65
        else 0.75
    )

    return {
        "tp1": round(ref_close + rng * 0.50 * mult, 2),
        "tp2": round(ref_close + rng * 1.00 * mult, 2),
        "tp3": round(ref_close + rng * 1.50 * mult, 2),
    }


# =========================================================
# MAIN PARSER
# =========================================================

@app.post("/voice-parse")
def voice_parse(rec: VoiceRecord):
    if not rec.time:
        rec.time = datetime.now().strftime("%H:%M")

    t = rec.ticker.upper().strip()
    tf = rec.interval.upper()

    # -----------------------------------------------------
    # INIT MEMORY
    # -----------------------------------------------------
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

    # -----------------------------------------------------
    # GLOBAL ENTRY SYNC
    # -----------------------------------------------------
    if rec.entry is not None:
        if rec.entry <= 0:
            memory[t]["global_entry"] = ""
        else:
            memory[t]["global_entry"] = str(rec.entry)

    # -----------------------------------------------------
    # PREPARE TEMP RECORD
    # -----------------------------------------------------
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

    # -----------------------------------------------------
    # UPDATE HISTORY
    # -----------------------------------------------------
    history = memory[t][tf]["history"]
    existing_index = next(
        (i for i, item in enumerate(history) if item["time"] == rec.time),
        None
    )

    if existing_index is not None:
        history[existing_index] = temp
    else:
        history.append(temp)

    history.sort(key=lambda x: safe_time_sort(x["time"]))

    if len(history) > HISTORY_LIMITS.get(tf, 5):
        history.pop(0)

    # -----------------------------------------------------
    # ENGINE COMPUTATIONS
    # -----------------------------------------------------
    trend = get_trend_state(rec)
    market_state = detect_market_state(rec, history)

    memory[t][tf]["last_data"] = {
        **temp,
        "trend": trend,
        "market_state": market_state
    }

    # -----------------------------------------------------
    # RECONSTRUCT INTRADAY CONTEXT
    # -----------------------------------------------------
    d1_data = memory[t]["D1"]["last_data"]
    h1_data = memory[t]["H1"]["last_data"]
    m15_data = memory[t]["M15"]["last_data"]
    m5_data = memory[t]["M5"]["last_data"]

    trend_d1 = d1_data.get("trend", "RANGE")
    trend_h1 = h1_data.get("trend", "RANGE")

    setup_m15 = "NONE"
    if m15_data:
        setup_m15 = detect_setup(
            VoiceRecord(**{
                "ticker": t, "interval": "M15", "time": m15_data.get("time"),
                "open": m15_data["open"], "high": m15_data["high"], "low": m15_data["low"], "close": m15_data["close"],
                "volume": m15_data["volume"], "ma20": m15_data["ma20"], "dema9": m15_data["dema9"], "rsi": m15_data["rsi"]
            })
        )

    trigger_m5 = "NO_TRIGGER"
    if m5_data:
        trigger_m5 = detect_trigger(
            VoiceRecord(**{
                "ticker": t, "interval": "M5", "time": m5_data.get("time"),
                "open": m5_data["open"], "high": m5_data["high"], "low": m5_data["low"], "close": m5_data["close"],
                "volume": m5_data["volume"], "ma20": m5_data["ma20"], "dema9": m5_data["dema9"], "rsi": m5_data["rsi"]
            }),
            memory[t]["M5"]["history"]
        )

    # -----------------------------------------------------
    # FINAL RE-EVALUATION
    # -----------------------------------------------------
    final = build_final_signal(trend_d1, trend_h1, setup_m15, trigger_m5)
    final_signal = final["signal"]
    confidence = final["confidence"]

    # -----------------------------------------------------
    # TAKE PROFIT GENERATION
    # -----------------------------------------------------
    tp_data = {}
    if m15_data:
        rng = m15_data["high"] - m15_data["low"]
        tp_data = generate_tp(final_signal, confidence, m15_data["close"], rng)

    # -----------------------------------------------------
    # DYNAMICZNE UZASADNIENIE DLA TRADERA (Jednoznaczny komunikat)
    # -----------------------------------------------------
    powod = "Oczekiwanie na klarowny układ struktur rynkowych."
    
    if final_signal == "BUY":
        if setup_m15 == "BREAKOUT":
            powod = "Mocne wybicie (Breakout) na M15 potwierdzone wolumenem. Wyższy trend jest wzrostowy."
        elif setup_m15 == "PULLBACK":
            powod = "Książkowe złapanie dołka (Pullback) na M15 nad wsparciem wyższego rzędu."
            
    elif final_signal == "HOLD":
        if setup_m15 == "ACCUMULATION":
            powod = "Trwa ciasna akumulacja (boczniak). Średnie się zeszły, RSI odpoczywa. TRZYMAJ pozycję przed wystrzałem."
        else:
            powod = "Pozycja bezpieczna. Wyższe interwały chronią układ, brak sygnałów do ucieczki."
            
    elif final_signal == "CZEKAJ":
        if trend_d1 == "SHORT" and trend_h1 == "SHORT":
            powod = "BLOKADA: D1 i H1 w trendzie spadkowym. Zakaz otwierania długich pozycji (łapanie noża)."
        elif trigger_m5 == "WEAK_MOMENTUM":
            powod = "ALARM: Wykryto pułapkę na byki (Bull Trap) lub gwałtowny zrzut na M5/M15. Stój z boku."
        else:
            powod = "Brak wyraźnej przewagi statystycznej. Rynek zbyt szarpany lub brak setupu na M15."

    # -----------------------------------------------------
    # COMMENT GENERATION (Maksymalna czytelność na żywo)
    # -----------------------------------------------------
    comment = (
        f"=== RAPORT SYSTEMU: {t} ===\n"
        f"WERDYKT: {final_signal} ({confidence}%)\n"
        f"UZASADNIENIE: {powod}\n"
        f"-----------------------------------------\n"
        f"MAPA REKORDU:\n"
        f"• D1 Trend:  {trend_d1}\n"
        f"• H1 Trend:  {trend_h1}\n"
        f"• M15 Setup: {setup_m15}\n"
        f"• M5 Spust:  {trigger_m5}\n"
        f"-----------------------------------------\n"
        f"CELE (TP):\n"
        f"TP1: {tp_data.get('tp1', '—')} | TP2: {tp_data.get('tp2', '—')} | TP3: {tp_data.get('tp3', '—')}"
    )

    # -----------------------------------------------------
    # OUTPUT DATA PACKAGING
    # -----------------------------------------------------
    data = {
        **temp,
        "signal": final_signal,
        "confidence": confidence,
        "trend_d1": trend_d1,
        "trend_h1": trend_h1,
        "setup_m15": setup_m15,
        "trigger_m5": trigger_m5,
        "trend": trend,
        "market_state": market_state,
        "entry": memory[t]["global_entry"],
        "comment": comment,
        "tp1": tp_data.get("tp1", "—"),
        "tp2": tp_data.get("tp2", "—"),
        "tp3": tp_data.get("tp3", "—"),
    }

    if m15_data:
        rng = m15_data["high"] - m15_data["low"]
        data["widelki"] = (
            f"{m15_data['low'] + rng*0.16:.2f}"
            f" - "
            f"{m15_data['low'] + rng*0.36:.2f}"
        )

    memory[t][tf]["last_data"] = data

    return data


# =========================================================
# DELETE ENDPOINT
# =========================================================

@app.post("/voice-parse/delete")
def voice_delete(req: DeleteReq):
    t_upper = req.ticker.upper().strip()
    if t_upper in memory:
        del memory[t_upper]
    return {"deleted": True, "ticker": t_upper}


# =========================================================
# MEMORY VIEW
# =========================================================

@app.get("/memory")
def memory_view():
    return memory


# =========================================================
# ROOT STATUS
# =========================================================

@app.get("/")
def root():
    return {
        "name": "VOICE XTB 9.0 STRUCTURE ENGINE",
        "status": "ONLINE"
    }
