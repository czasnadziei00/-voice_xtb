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

HISTORY_LIMITS = {
    "M5": 24,
    "M15": 16,
    "H1": 10,
    "D1": 10,
}

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

def avg(values):
    return sum(values) / len(values) if values else 0

def safe_time_sort(time_str: str):
    if "-" in time_str:
        return time_str
    return f"0000-00-00 {time_str}"

def get_trend_state(rec: VoiceRecord):
    if rec.close > rec.ma20 and rec.close > rec.dema9 and rec.dema9 > rec.ma20 and rec.rsi >= 55:
        return "LONG"
    if rec.close < rec.ma20 and rec.close < rec.dema9 and rec.dema9 < rec.ma20 and rec.rsi <= 45:
        return "SHORT"
    return "RANGE"

def detect_market_state(rec: VoiceRecord, history: List[Dict]):
    if not history:
        return "NEUTRAL"
    candle_range = rec.high - rec.low
    avg_range = avg([abs(x["high"] - x["low"]) for x in history[-3:]])
    if avg_range <= 0:
        return "RANGE"
    ratio = candle_range / avg_range
    if ratio > 2.8:
        return "CHAOS"
    if ratio > 1.55:
        return "BREAKOUT"
    return "NORMAL"

def detect_setup(rec: VoiceRecord):
    if rec.rsi > 78:
        return "OVERHEATED"
    if rec.close > rec.ma20 and rec.close > rec.dema9 and rec.rsi >= 58:
        return "BREAKOUT"
    if rec.close > rec.ma20 and rec.close <= rec.dema9 and rec.rsi >= 48:
        return "PULLBACK"
    if rec.rsi >= 45 and rec.rsi <= 58 and abs(rec.dema9 - rec.ma20) < (rec.close * 0.003):
        return "ACCUMULATION"
    return "NONE"

def detect_trigger(rec: VoiceRecord, history: List[Dict]):
    if not history or len(history) < 2:
        return "NO_TRIGGER"
    prev = history[-2] if history[-1]["time"] == rec.time else history[-1]
    bullish_candle = rec.close > rec.open
    rsi_up = rec.rsi > prev["rsi"]
    volume_up = rec.volume > prev["volume"]
    if bullish_candle and rsi_up and volume_up and rec.close > rec.dema9:
        return "ENTRY_TRIGGER"
    if rec.close < rec.dema9 and rec.rsi < prev["rsi"]:
        return "WEAK_MOMENTUM"
    return "NO_TRIGGER"

def build_final_signal(trend_d1, trend_h1, setup_m15, trigger_m5):
    confidence = 40
    signal = "CZEKAJ"

    if trend_d1 == "SHORT" and trend_h1 == "SHORT":
        return {"signal": "CZEKAJ", "confidence": 10}
    if setup_m15 == "NONE" and trigger_m5 == "WEAK_MOMENTUM":
        return {"signal": "CZEKAJ", "confidence": 25}

    if trend_d1 == "LONG": confidence += 15
    if trend_h1 == "LONG": confidence += 10

    if setup_m15 == "PULLBACK": confidence += 25
    elif setup_m15 == "ACCUMULATION": confidence += 20
    elif setup_m15 == "BREAKOUT": confidence += 20
    elif setup_m15 == "OVERHEATED": confidence -= 25

    if trigger_m5 == "ENTRY_TRIGGER": confidence += 15
    elif trigger_m5 == "WEAK_MOMENTUM": confidence -= 10

    if confidence >= 65: signal = "BUY"
    elif confidence >= 48: signal = "HOLD"
    else: signal = "CZEKAJ"

    return {"signal": signal, "confidence": max(0, min(100, confidence))}

# =========================================================
# NOWA DYNAMICZNA MATEMATYKA WYJŚCIA (TAKE PROFIT / TRAILING)
# =========================================================
def generate_dynamic_tp(signal, conf, close_price, setup_m15, h1_data, d1_data):
    if signal not in ["BUY", "HOLD"]:
        return {}

    # Obliczamy bazowy "Krok Zmienności" oparty o szacunek ceny (zamiast małej świeczki M15)
    # Dla spólki za 32 zł (Allegro) krok to ok 0.60 zł. Dla droższych odpowiednio skalowany (ok. 1.8% ceny)
    volatility_step = close_price * 0.018

    # Współczynnik siły trendu wyższego rzędu
    trend_multiplier = 1.0
    if d1_data.get("trend") == "LONG":
        trend_multiplier += 0.4
    if h1_data.get("trend") == "LONG":
        trend_multiplier += 0.2

    # Jeżeli rynek jest ekstremalnie rozgrzany silnym impulsem, rozszerzamy targety (Nie wysiadaj za wcześnie!)
    if setup_m15 == "BREAKOUT" and conf >= 75:
        trend_multiplier *= 1.5

    tp1 = close_price + (volatility_step * 0.6 * trend_multiplier)
    tp2 = close_price + (volatility_step * 1.3 * trend_multiplier)
    tp3 = close_price + (volatility_step * 2.2 * trend_multiplier)

    # Dynamiczny Trailing Stop oparty na strukturze logicznej średnich
    # System podpowiada gdzie uciekać z zyskiem, gdyby nagle zawróciło
    trailing_sl = h1_data.get("dema9") if h1_data.get("dema9") else close_price * 0.985
    if setup_m15 == "OVERHEATED":
        # Jeśli rynek jest przegrzany, natychmiast podciągamy stop loss pod bliską średnią z M15, aby chronić kasę
        trailing_sl = max(trailing_sl, close_price * 0.993)

    return {
        "tp1": round(tp1, 2),
        "tp2": round(tp2, 2),
        "tp3": round(tp3, 2),
        "trailing_sl": round(trailing_sl, 2)
    }

@app.post("/voice-parse")
def voice_parse(rec: VoiceRecord):
    if not rec.time:
        rec.time = datetime.now().strftime("%H:%M")

    t = rec.ticker.upper().strip()
    tf = rec.interval.upper()

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

    if rec.entry is not None:
        memory[t]["global_entry"] = "" if rec.entry <= 0 else str(rec.entry)

    temp = {
        "ticker": t, "interval": tf, "time": rec.time,
        "open": rec.open, "high": rec.high, "low": rec.low, "close": rec.close,
        "volume": rec.volume, "ma20": rec.ma20, "dema9": rec.dema9, "rsi": rec.rsi,
    }

    history = memory[t][tf]["history"]
    existing_index = next((i for i, item in enumerate(history) if item["time"] == rec.time), None)

    if existing_index is not None:
        history[existing_index] = temp
    else:
        history.append(temp)

    history.sort(key=lambda x: safe_time_sort(x["time"]))
    if len(history) > HISTORY_LIMITS.get(tf, 5):
        history.pop(0)

    trend = get_trend_state(rec)
    market_state = detect_market_state(rec, history)

    # Zapisujemy do pamięci wyłącznie poprawne, oczekiwane przez Pydantic klucze
    memory[t][tf]["last_data"] = {
        **temp,
        "trend": trend,
        "market_state": market_state
    }

    d1_data = memory[t]["D1"]["last_data"]
    h1_data = memory[t]["H1"]["last_data"]
    m15_data = memory[t]["M15"]["last_data"]
    m5_data = memory[t]["M5"]["last_data"]

    trend_d1 = d1_data.get("trend", "RANGE")
    trend_h1 = h1_data.get("trend", "RANGE")

    setup_m15 = "NONE"
    if m15_data:
        setup_m15 = detect_setup(VoiceRecord(**m15_data))

    trigger_m5 = "NO_TRIGGER"
    if m5_data:
        trigger_m5 = detect_trigger(VoiceRecord(**m5_data), memory[t]["M5"]["history"])

    final = build_final_signal(trend_d1, trend_h1, setup_m15, trigger_m5)
    final_signal = final["signal"]
    confidence = final["confidence"]

    # Generowanie ulepszonych, dynamicznych targetów
    ref_price = rec.close
    tp_data = generate_dynamic_tp(final_signal, confidence, ref_price, setup_m15, h1_data, d1_data)

    powod = "Oczekiwanie na klarowny układ struktur rynkowych."
    if final_signal == "BUY":
        if setup_m15 == "BREAKOUT":
            powod = "SILNY IMPULS (Breakout) na M15! Wyższy trend wspiera ruch. Pozwól zyskom rosnąć, kontroluj Trailing SL."
        elif setup_m15 == "PULLBACK":
            powod = "Książkowe łapanie korekty (Pullback) nad ważnym wsparciem średniej kroczącej."
    elif final_signal == "HOLD":
        if setup_m15 == "OVERHEATED":
            powod = "UWAGA: Rynek lokalnie mocno wykupiony (RSI M15 > 78). Trend główny trzyma pozycję, ale PODCIĄGNIJ SL blisko ceny!"
        elif setup_m15 == "ACCUMULATION":
            powod = "Ciasna konsolidacja przed potencjalnym wybiciem. Średnie splecione. Zachowaj cierpliwość."
    elif final_signal == "CZEKAJ":
        if trend_d1 == "SHORT" and trend_h1 == "SHORT":
            powod = "ZAKAZ BUY: Struktura D1 i H1 w silnej bessie. Próba kupna to łapanie spadającego noża."
        elif trigger_m5 == "WEAK_MOMENTUM":
            powod = "ALARM MOMENTUM: Wykryto dystrybucję lub pułapkę (Bull Trap) na M5. Zabezpiecz kapitał."

    tsl_val = tp_data.get('trailing_sl', '—')
    comment = (
        f"=== RAPORT SYSTEMU: {t} ===\n"
        f"WERDYKT: {final_signal} ({confidence}%)\n"
        f"LOGIKA: {powod}\n"
        f"-----------------------------------------\n"
        f"D1: {trend_d1} | H1: {trend_h1} | M15: {setup_m15} | M5: {trigger_m5}\n"
        f"-----------------------------------------\n"
        f"DYNAMICZNY DOPALACZ MATEMATYCZNY:\n"
        f"• Sugerowana obrona (Trailing SL): {tsl_val}\n"
        f"• Cele wyjścia (TP): TP1: {tp_data.get('tp1', '—')} | TP2: {tp_data.get('tp2', '—')} | TP3: {tp_data.get('tp3', '—')}"
    )

    # Paczka danych dla frontendu
    response_data = {
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
        "trailing_sl": tsl_val
    }

    if m15_data:
        rng = m15_data["high"] - m15_data["low"]
        response_data["widelki"] = f"{m15_data['low'] + rng*0.16:.2f} - {m15_data['low'] + rng*0.36:.2f}"

    return response_data

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
    return {"name": "VOICE XTB 9.0 STRUCTURE ENGINE", "status": "ONLINE"}
