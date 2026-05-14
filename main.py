from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Optional, List
from datetime import datetime

app = FastAPI(
    title="VOICE XTB 7.4 PRO",
    version="7.4.7"
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
    entry: Optional[float] = None  # Dodane pole entry do modelu wejściowego

class DeleteReq(BaseModel):
    ticker: str

# ======================================================
#  UTILS
# ======================================================

def normalize_tf(tf: str) -> str:
    tf = tf.upper().strip()
    if tf in ["5", "M5"]: return "M5"
    if tf in ["15", "M15"]: return "M15"
    if tf in ["H1", "1H", "60"]: return "H1"
    return tf

def validate_candle(rec: VoiceRecord):
    if rec.high < rec.low:
        raise HTTPException(status_code=400, detail="HIGH < LOW")
    if not (rec.low <= rec.close <= rec.high):
        raise HTTPException(status_code=400, detail="CLOSE poza zakresem świecy")
    if not (0 <= rec.rsi <= 100):
        raise HTTPException(status_code=400, detail="RSI poza zakresem 0-100")

def ensure_time(rec: VoiceRecord):
    if not rec.time:
        rec.time = datetime.now().strftime("%H:%M")

def generate_pro_comment(rec: VoiceRecord, history: List[Dict], signal: str) -> str:
    dir_tf = trend_direction(history)
    trend_map = {"UP": "Wzrostowy", "DOWN": "Spadkowy", "NEUTRAL": "Boczny/Neutralny"}
    t_dir = trend_map.get(dir_tf, "Neutralny")
    supp_min = round(rec.low * 0.998, 2)
    supp_max = round(rec.low, 2)
    r = rec.rsi
    rel = "Słabość (pod DEMA9)." if rec.close < rec.dema9 else "Siła (nad DEMA9)."
    
    return (
        f"TREND: {t_dir}. Wsparcie: {supp_min}-{supp_max}.\n\n"
        f"MOMENTUM: RSI {r:.1f}.\n\n"
        f"SIŁA: {rel}\n\n"
        f"RYZYKO: SL poniżej {supp_min}."
    )

# ======================================================
#  HISTORIA I ANALIZA
# ======================================================

def push_history(ticker: str, tf: str, candle: Dict):
    if ticker not in memory:
        memory[ticker] = {}
    if tf not in memory[ticker] or "history" not in memory[ticker][tf]:
        memory[ticker][tf] = {"history": []}
    memory[ticker][tf]["history"].append(candle)
    limit = HISTORY_LIMITS.get(tf, 5)
    if len(memory[ticker][tf]["history"]) > limit:
        memory[ticker][tf]["history"] = memory[ticker][tf]["history"][-limit:]

def get_history(ticker: str, tf: str) -> List[Dict]:
    if ticker not in memory or tf not in memory[ticker]:
        return []
    return memory[ticker][tf].get("history", [])

def trend_direction(history: List[Dict]) -> str:
    if len(history) < 2: return "NEUTRAL"
    first, last = history[0]["close"], history[-1]["close"]
    if first == 0: return "NEUTRAL"
    diff = abs(last - first) / first
    if last > first and diff > 0.005: return "UP"
    if last < first and diff > 0.005: return "DOWN"
    return "NEUTRAL"

def calc_signal(rec: VoiceRecord, history: List[Dict]):
    c, ma, de, r = rec.close, rec.ma20, rec.dema9, rec.rsi
    dir_tf = trend_direction(history)
    if dir_tf == "UP" and c > de: return "CZEKAJ DO" if r >= 80 else "BUY"
    if dir_tf == "DOWN" and c < de: return "CZEKAJ DO" if r <= 20 else "SELL"
    if dir_tf == "UP": return "PRAWIE BUY"
    if dir_tf == "DOWN": return "PRAWIE SELL"
    return "CZEKAJ"

# ======================================================
#  WIDEŁKI I TP
# ======================================================

def compute_widelki(low: float, high: float):
    dol = low + (high - low) * 0.18
    gor = low + (high - low) * 0.32
    return round(dol, 2), round(gor, 2)

def compute_tp(signal: str, close: float, low: float, high: float, ma: float, de: float):
    rng = high - low
    tp1, tp2, tp3 = None, None, None
    if "BUY" in signal:
        tp1 = close + rng * 0.55
        tp2 = close + rng * 1.1
        tp3 = close + (abs(close - ((ma + de) / 2)) * 1.8)
    elif "SELL" in signal:
        tp1 = close - rng * 0.55
        tp2 = close - rng * 1.1
        tp3 = close - (abs(close - ((ma + de) / 2)) * 1.8)
    return {"tp1": round(tp1, 2) if tp1 else "—", "tp2": round(tp2, 2) if tp2 else "—", "tp3": round(tp3, 2) if tp3 else "—"}

def consensus_signal(ticker_data: Dict):
    sigs = []
    for tf in ["M5", "M15", "H1"]:
        if tf in ticker_data:
            s = ticker_data[tf].get("signal")
            if s: sigs.append(s)
    buy_score = sigs.count("BUY") + (0.5 if "PRAWIE BUY" in sigs else 0)
    sell_score = sigs.count("SELL") + (0.5 if "PRAWIE SELL" in sigs else 0)
    if buy_score >= 1.5: return "BUY"
    if sell_score >= 1.5: return "SELL"
    return "CZEKAJ"

# ======================================================
#  MAIN ENDPOINT
# ======================================================

@app.post("/voice-parse")
def voice_parse(rec: VoiceRecord):
    validate_candle(rec)
    ensure_time(rec)
    t, tf = rec.ticker.upper().strip(), normalize_tf(rec.interval)
    history = get_history(t, tf)
    signal = calc_signal(rec, history)

    # --- LOGIKA ENTRY (TRZYMANIE CENY LUB CZYSZCZENIE PRZEZ 0) ---
    current_entry_in_memory = ""
    if t in memory and tf in memory[t] and "last_data" in memory[t][tf]:
        current_entry_in_memory = memory[t][tf]["last_data"].get("entry", "")

    # Decyzja:
    if rec.entry is not None:
        if rec.entry == 0:
            final_entry = ""  # Wyzerowanie pozycji
        else:
            final_entry = str(rec.entry) # Nowa pozycja lub aktualizacja
    else:
        final_entry = current_entry_in_memory # Przepisanie starej jeśli w głosie nie było entry

    data = {
        "ticker": t, "interval": tf, "time": rec.time,
        "open": rec.open, "low": rec.low, "high": rec.high, "close": rec.close,
        "volume": rec.volume, "ma20": rec.ma20, "dema9": rec.dema9, "rsi": rec.rsi,
        "signal": signal, "entry": final_entry,
        "comment": generate_pro_comment(rec, history, signal)
    }

    push_history(t, tf, data)
    if tf == "M15":
        dol, gor = compute_widelki(rec.low, rec.high)
        data["widelki"] = f"{dol:.2f} - {gor:.2f}"
        data.update(compute_tp(signal, rec.close, rec.low, rec.high, rec.ma20, rec.dema9))

    if t not in memory: memory[t] = {}
    if tf not in memory[t]: memory[t][tf] = {"history": []}
    memory[t][tf].update({"last_data": data, "signal": signal})
    data["consensus"] = consensus_signal(memory[t])
    return data

# ======================================================
#  SYSTEM ENDPOINTS
# ======================================================

@app.post("/voice-parse/delete")
def voice_delete(req: DeleteReq):
    t = req.ticker.upper()
    if t in memory: del memory[t]
    return {"ticker": t, "deleted": True}

@app.get("/memory")
def memory_view():
    return memory

@app.get("/health")
def health():
    return {"status": "ok", "server_time": datetime.now().strftime("%H:%M:%S"), "tickers": len(memory)}

@app.get("/")
def root():
    return {"name": "VOICE XTB 7.4 PRO", "status": "ONLINE", "tickers": len(memory)}
