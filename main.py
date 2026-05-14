from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Dict, Optional, List
from datetime import datetime

app = FastAPI(
    title="VOICE XTB 7.4 PRO",
    version="7.4"
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
    if not (rec.low <= rec.open <= rec.high):
        raise HTTPException(status_code=400, detail="OPEN poza zakresem świecy")
    if not (rec.low <= rec.close <= rec.high):
        raise HTTPException(status_code=400, detail="CLOSE poza zakresem świecy")
    if rec.volume < 0:
        raise HTTPException(status_code=400, detail="Volume < 0")
    if not (0 <= rec.rsi <= 100):
        raise HTTPException(status_code=400, detail="RSI poza zakresem 0-100")

def ensure_time(rec: VoiceRecord):
    if not rec.time:
        rec.time = datetime.now().strftime("%H:%M")

def generate_pro_comment(rec: VoiceRecord, history: List[Dict], signal: str) -> str:
    dir_tf = trend_direction(history)
    
    # 1. TREND I STRUKTURA
    trend_map = {"UP": "Wzrostowy", "DOWN": "Spadkowy", "NEUTRAL": "Boczny/Neutralny"}
    t_dir = trend_map.get(dir_tf, "Neutralny")
    
    supp_min = round(rec.low * 0.998, 2)
    supp_max = round(rec.low, 2)
    
    # 2. MOMENTUM (RSI)
    r = rec.rsi
    if r <= 30:
        mom = f"RSI {r:.1f} = skrajne wyprzedanie. Sygnał paniki, statystycznie rynek odbija z tych poziomów."
    elif r >= 70:
        mom = f"RSI {r:.1f} = skrajne wykupienie. Możliwa dystrybucja, ryzyko korekty."
    else:
        mom = f"RSI {r:.1f} w strefie neutralnej. Momentum stabilne."

    # 3. SIŁA/SŁABOŚĆ
    rel = "Słabość krótkoterminowa (pod DEMA9)." if rec.close < rec.dema9 else "Siła krótkoterminowa (nad DEMA9)."
    knot = " Długi dolny knot sugeruje obecność popytu." if (rec.close - rec.low) > (rec.high - rec.close) * 2 else ""
    
    # 4. INTERPRETACJA I RYZYKO
    interp = "Rynek dąży do normalizacji/VWAP."
    if "BUY" in signal: interp = "Potwierdzona presja kupujących. Struktura pro-wzrostowa."
    if "SELL" in signal: interp = "Dominacja podaży. Możliwa kontynuacja przeceny."
    
    risk = f"Kluczowa ochrona struktury na poziomie {supp_min}."

    return (
        f"TREND: {t_dir}. Struktura trzyma, dopóki cena powyżej {supp_min}-{supp_max}.\n\n"
        f"MOMENTUM: {mom}\n\n"
        f"SIŁA: {rel}{knot}\n\n"
        f"INTERPRETACJA: {interp}\n\n"
        f"RYZYKO: Realne zagrożenie przy zamknięciu poniżej {supp_min}."
    )

# ======================================================
#  HISTORIA
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

# ======================================================
#  ANALIZA TRENDU
# ======================================================

def trend_direction(history: List[Dict]) -> str:
    if len(history) < 2:
        return "NEUTRAL"
    first = history[0]["close"]
    last = history[-1]["close"]
    if first == 0: return "NEUTRAL"
    diff = abs(last - first) / first
    if last > first and diff > 0.005: 
        return "UP"
    if last < first and diff > 0.005:
        return "DOWN"
    return "NEUTRAL"

def trend_strength(history: List[Dict]) -> float:
    if len(history) < 2:
        return 0.0
    last = history[-1]
    prev = history[-2]
    spread = abs(last["ma20"] - last["dema9"])
    slope = abs(last["ma20"] - prev["ma20"])
    return spread + slope

# ======================================================
#  RSI ENGINE
# ======================================================

def rsi_state(rsi: float) -> str:
    if rsi >= 75: return "EXTREME_OVERBOUGHT"
    if rsi >= 65: return "OVERBOUGHT"
    if rsi <= 25: return "EXTREME_OVERSOLD"
    if rsi <= 35: return "OVERSOLD"
    return "NEUTRAL"

# ======================================================
#  VOLATILITY
# ======================================================

def candle_volatility(low: float, high: float) -> float:
    return abs(high - low) / low if low > 0 else 0

# ======================================================
#  SIGNAL ENGINE PRO
# ======================================================

def calc_signal(rec: VoiceRecord, history: List[Dict]):
    c, ma, de, r = rec.close, rec.ma20, rec.dema9, rec.rsi
    dir_tf = trend_direction(history)
    strength = trend_strength(history)
    rsi_mode = rsi_state(r)
    vol = candle_volatility(rec.low, rec.high)

    score_buy = 0
    score_sell = 0

    if c > de > ma: score_buy += 3
    if c < de < ma: score_sell += 3
    if r >= 60: score_buy += 2
    if r <= 40: score_sell += 2
    if dir_tf == "UP": score_buy += 2
    if dir_tf == "DOWN": score_sell += 2
    if strength > 1:
        score_buy += 1
        score_sell += 1

    if score_buy >= 6 and rsi_mode != "EXTREME_OVERBOUGHT": return "BUY"
    if score_sell >= 6 and rsi_mode != "EXTREME_OVERSOLD": return "SELL"
    if score_buy >= 4: return "PRAWIE BUY"
    if score_sell >= 4: return "PRAWIE SELL"
    if 45 <= r <= 55: return "CZEKAJ DO"
    return "CZEKAJ"

# ======================================================
#  WIDEŁKI
# ======================================================

def compute_widelki(low: float, high: float):
    dol = low + (high - low) * 0.20
    gor = low + (high - low) * 0.35
    return round(dol, 2), round(gor, 2)

# ======================================================
#  TP
# ======================================================

def compute_tp(signal: str, close: float, low: float, high: float, ma: float, de: float):
    rng = high - low
    dol, gor = compute_widelki(low, high)
    tp1, tp2, tp3 = None, None, None

    if "BUY" in signal:
        tp1 = gor + rng * 0.5
        tp2 = gor + rng * 1.0
        tp3 = close + (abs(close - ((ma + de) / 2)) + abs(ma - de))
    elif "SELL" in signal:
        tp1 = dol - rng * 0.5
        tp2 = dol - rng * 1.0
        tp3 = close - (abs(close - ((ma + de) / 2)) + abs(ma - de))

    return {
        "tp1": round(tp1, 2) if tp1 else "—",
        "tp2": round(tp2, 2) if tp2 else "—",
        "tp3": round(tp3, 2) if tp3 else "—",
    }

# ======================================================
#  CONSENSUS
# ======================================================

def consensus_signal(ticker_data: Dict):
    sigs = []
    for tf in ["M5", "M15", "H1"]:
        if tf in ticker_data:
            s = ticker_data[tf].get("signal")
            if s: sigs.append(s)
            
    if sigs.count("BUY") >= 2: return "BUY"
    if sigs.count("SELL") >= 2: return "SELL"
    if "PRAWIE BUY" in sigs: return "PRAWIE BUY"
    if "PRAWIE SELL" in sigs: return "PRAWIE SELL"
    if "CZEKAJ DO" in sigs: return "CZEKAJ DO"
    return "CZEKAJ"

# ======================================================
#  ROOT
# ======================================================

@app.get("/")
def root():
    return {"name": "VOICE XTB 7.4 PRO", "status": "ONLINE", "tickers": len(memory)}

# ======================================================
#  MAIN ENDPOINT
# ======================================================

@app.post("/voice-parse")
def voice_parse(rec: VoiceRecord):
    validate_candle(rec)
    ensure_time(rec)
    
    t = rec.ticker.upper().strip()
    tf = normalize_tf(rec.interval)
    
    history = get_history(t, tf)
    signal = calc_signal(rec, history)
    
    data = {
        "ticker": t, "interval": tf, "time": rec.time,
        "open": rec.open, "low": rec.low, "high": rec.high, "close": rec.close,
        "volume": rec.volume, "ma20": rec.ma20, "dema9": rec.dema9, "rsi": rec.rsi,
        "signal": signal, "entry": "",
        "comment": generate_pro_comment(rec, history, signal)
    }

    push_history(t, tf, data)

    if tf == "M15":
        dol, gor = compute_widelki(rec.low, rec.high)
        data["widelki"] = f"{dol:.2f} - {gor:.2f}"
        data.update(compute_tp(signal, rec.close, rec.low, rec.high, rec.ma20, rec.dema9))

    if t not in memory: memory[t] = {}
    if tf not in memory[t]: memory[t][tf] = {"history": []}
    
    memory[t][tf].update({
        "last_data": data,
        "signal": signal
    })

    data["consensus"] = consensus_signal(memory[t])
    return data

# ======================================================
#  DELETE
# ======================================================

@app.post("/voice-parse/delete")
def voice_delete(req: DeleteReq):
    t = req.ticker.upper()
    if t in memory: del memory[t]
    return {"ticker": t, "deleted": True}

# ======================================================
#  MEMORY VIEW
# ======================================================

@app.get("/memory")
def memory_view():
    return memory

# ======================================================
#  HEALTH
# ======================================================

@app.get("/health")
def health():
    return {"status": "ok", "server_time": datetime.now().strftime("%H:%M:%S"), "tickers": len(memory)}
