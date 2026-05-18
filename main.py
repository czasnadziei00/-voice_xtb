from datetime import datetime
from typing import Dict, List, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="VOICE XTB 8.3 PURE SIGNAL",
    version="8.3.1-DYNAMIC-COMMENTS"
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
            "signal": "SELL",
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
        score_con -= 35
    if rec.rsi > 78:
        score_con -= 20
    if market_state == "CHAOS":
        score_con -= 20
    score_con = max(0, min(100, score_con))

    score = round((score_agg * 0.625) + (score_con * 0.375))

    signal = "HOLD"
    if score >= 72 and trend == "UP" and rec.close > rec.dema9 and rec.dema9 > rec.ma20:
        signal = "BUY"
    elif score >= 52 and trend == "UP":
        signal = "BUY"
    elif score >= 38 and (market_state == "BREAKOUT" or vol_spike > 1.2 or rec.rsi > 55):
        signal = "HOLD"
    elif trend == "DOWN" or rec.close < rec.dema9 or rec.rsi < 45:
        signal = "REDUKUJ"
    elif score < 20 or (trend == "DOWN" and rec.close < rec.ma20 and rec.rsi < 38):
        signal = "SELL"

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
    h1 = t_data.get("H1", {}).get("history", [])
    d1 = t_data.get("D1", {}).get("history", [])

    if not m5:
        return {"signal": current_signal, "confidence": current_conf}

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

    if current_signal == "BUY" and d1_trend == "UP" and h1_trend == "UP":
        return {"signal": "BUY", "confidence": min(100, current_conf + 12)}

    if current_signal == "HOLD" and (d1_trend == "UP" or h1_trend == "UP"):
        return {"signal": "HOLD", "confidence": max(45, current_conf)}

    if current_signal == "REDUKUJ" and (d1_trend == "DOWN" or h1_trend == "DOWN"):
        return {"signal": "REDUKUJ", "confidence": max(55, current_conf)}

    return {"signal": current_signal, "confidence": current_conf}

def generate_tp(signal, conf, ref_close, rng):
    if signal in ["SELL", "REDUKUJ"]:
        return {}
    mult = 1.3 if conf >= 80 else 1.0 if conf >= 65 else 0.75
    return {
        "tp1": round(ref_close + rng * 0.50 * mult, 2),
        "tp2": round(ref_close + rng * 1.0 * mult, 2),
        "tp3": round(ref_close + rng * 1.5 * mult, 2),
    }

def safe_time_sort(time_str: str) -> str:
    if "-" in time_str:
        return time_str
    return f"0000-00-00 {time_str}"

# =========================================================
# GENERATOR DYNAMICZNYCH RAPORTÓW DLA LAIKA
# =========================================================
def build_structural_comment(t: str, final_signal: str, confidence: int, current_rec: VoiceRecord, t_memory: Dict) -> str:
    m5_last = t_memory.get("M5", {}).get("last_data", {})
    m15_last = t_memory.get("M15", {}).get("last_data", {})
    h1_last = t_memory.get("H1", {}).get("last_data", {})
    d1_last = t_memory.get("D1", {}).get("last_data", {})

    # 1. Budowanie bloków interwałów
    def fmt_line(name, data):
        if not data: return f"* **{name}:** Brak bieżących danych w tej sesji."
        c, d, m, r = data.get('close', 0), data.get('dema9', 0), data.get('ma20', 0), data.get('rsi', 0)
        rel_dema = "nad linią DEMA9 (silny impuls)" if c >= d else "pod linią DEMA9 (lokalne cofnięcie)"
        rel_ma = "bezpiecznie powyżej MA20" if c >= m else "poniżej linii MA20 (ryzyko strukturalne)"
        return f"* **{name}:** Cena {c:.2f} jest {rel_dema} oraz {rel_ma}. Siła rynku (RSI): {r:.1f}."

    str_d1 = fmt_line("D1 (Długi dystans)", d1_last)
    str_h1 = fmt_line("H1 (Ostatnie godziny)", h1_last)
    str_m15 = fmt_line("M15 (Bieżący układ)", m15_last)
    str_m5 = f"* **M5 (Mikroskop):** Cena: {m5_last.get('close',0):.2f}, RSI: {m5_last.get('rsi',0):.1f}." if m5_last else "* **M5:** Brak danych."

    # 2. Dobór wniosku na bazie sygnału i parametrów matematycznych
    wniosek = ""
    header_icon = "🟢"
    
    if final_signal == "BUY":
        if current_rec.close < current_rec.dema9:
            header_icon = "🟡"
            wniosek = ("🔥 **KOREKTA W HOSSIE (BUY ON DIP) / STREFA KUPNA!**\n"
                       "Duży obrazek (D1/H1) jest całkowicie bezpieczny. Inwestorzy na chwilę odbierają zyski, "
                       "przez co cena kucnęła i dotarła do lokalnego wsparcia. Dla systemu to nie jest strach – to techniczna promocja na zakupy!")
        else:
            header_icon = "🟢"
            wniosek = ("🔥 **PEŁNA SYSTEMOWA HARMONIA KUPUJĄCYCH!**\n"
                       "Główne interwały grają w jednej drużynie na wzrosty. Rynek ma potężne paliwo (momentum), "
                       "a na wykresie nie ma śladów aktywnej podaży. Idziemy z najsilniejszym prądem rynkowym.")
            
    elif final_signal == "HOLD":
        header_icon = "🔵"
        wniosek = ("⏳ **RYNEK W FAZIE WYCZEKIWANIA (RUCH W BOK).**\n"
                   "Cena porusza się bokiem, tworząc lokalne pasmo wahań (konsolidację). Średnie się zacieśniają, "
                   "co oznacza zbieranie energii pod mocniejszy ruch. Agresywny wskaźnik szuka tu okazji, ale czekamy na skok wolumenu.")
        
    elif final_signal == "REDUKUJ":
        header_icon = "🟠"
        wniosek = ("⚠️ **ZAGROŻENIE SPADKU / ZMNIEJSZANIE RYZYKA.**\n"
                   "To nie jest lekka korekta – popyt traci kontrolę na niższych interwałach. Wskaźniki pękają, "
                   "a cena osunęła się pod szybkie średnie. Rośnie ryzyko głębszego zjazdu. Czas zabezpieczyć zyski.")
        
    elif final_signal == "SELL":
        header_icon = "🔴"
        wniosek = ("🚨 **PEŁNA EWAKUACJA! STRUKTURA ZOSTAŁA ZNISZCZONA.**\n"
                   "Na rynku pojawiła się silna, agresywna wyprzedaż. Kluczowe linie obrony popytu pękły jak zapałki. "
                   "Próba kupowania tutaj to łapanie spadających noży. System nakazuje natychmiastowy odwrót.")
        
    else:
        header_icon = "⚪"
        wniosek = "⚠️ **BRAK WYSTARCZAJĄCEJ PŁYNNOŚCI NA TYM INTERWALE.**\nObrót nie osiągnął wymaganego minimum systemowego."

    # 3. Wyliczenie poziomów do tabeli logicznej
    m15_history = t_memory.get("M15", {}).get("history", [])
    tp1_v = tp2_v = tp3_v = wsparcie = opor = "—"
    
    if m15_history:
        ref = m15_history[-1]
        rng = ref["high"] - ref["low"]
        wsparcie = f"{ref['low']:.2f}"
        opor = f"{ref['high']:.2f}"
        
        if final_signal not in ["SELL", "REDUKUJ"]:
            tp_d = generate_tp(final_signal, confidence, ref["close"], rng)
            tp1_v = f"{tp_d.get('tp1', 0):.2f}"
            tp2_v = f"{tp_d.get('tp2', 0):.2f}"
            tp3_v = f"{tp_d.get('tp3', 0):.2f}"

    comment = (
        f"--- {header_icon} RAPORT HYBRYDOWY STRUKTURALNY ({t}) ---\n"
        f"📌 WERDYKT SYSTEMU: {final_signal} ({confidence}%)\n\n"
        f"⭐ GŁÓWNY WNIOSEK TERAZ:\n{wniosek}\n\n"
        f"1. STRUKTURA BAZOWA (D1 / H1)\n{str_d1}\n{str_h1}\n\n"
        f"2. STRUKTURA INTRADAY (M15 / M5)\n{str_m15}\n{str_m5}\n\n"
        f"⭐ LOGICZNE POZIOMY WG SYSTEMU:\n"
        f"| Cel / Zapora | Poziom | Logika rynkowa |\n"
        f"| :--- | :--- | :--- |\n"
        f"| OPÓR (Sufit ceny) | {opor if final_signal in ['HOLD','REDUKUJ','SELL'] else tp2_v} | Bariera podażowa lub cel pełnego impulsu |\n"
        f"| CENA AKTUALNA | {current_rec.close:.2f} | Punkt odniesienia w bieżącej minucie |\n"
        f"| LINIA OBRONY (Sl) | {wsparcie} | Kluczowa podłoga - jej pęknięcie zmienia układ sił |\n\n"
        f"Układ średnich: {'Wzrostowy (UP)' if current_rec.dema9 > current_rec.ma20 else 'Spadkowy/Boczny'} | Stan Momentum: {'Dodatnie' if current_rec.rsi > 50 else 'Ujemne/Słabe'}"
    )
    return comment

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

    # BUDOWANIE NOWEGO BOKSERSKIEGO KOMENTARZA
    comment = build_structural_comment(t, final_signal, confidence, rec, memory[t])

    data = temp.copy()
    data.update({
        "signal": final_signal,
        "confidence": confidence,
        "entry": memory[t]["global_entry"],
        "comment": comment,
    })

    m15_h = memory[t].get("M15", {}).get("history", [])
    if m15_h and final_signal not in ["SELL", "REDUKUJ"]:
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
    return {"name": "VOICE XTB 8.3 PURE SIGNAL", "status": "ONLINE"}
