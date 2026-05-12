from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Optional
import uvicorn
import re

app = FastAPI()

# Pamięć ostatnich świec per (ticker, interval)
last_candles: Dict[str, dict] = {}

FINAL_INTERVALS = ["M5", "M15", "H1"]


class VoiceRequest(BaseModel):
    text: str


# ---------- PARSER TEKSTU ----------

def parse_payload(text: str) -> dict:
    """
    Format:
    TICKER INTERVAL open X high X low X close X ma20 X dema9 X volume X rsi X
    lub:
    TICKER INTERVAL close X
    """
    parts = text.strip().split()
    if len(parts) < 3:
        raise ValueError("Za mało danych w tekście")

    ticker = parts[0].upper()
    interval = parts[1].upper()

    data = {
        "ticker": ticker,
        "interval": interval,
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "ma20": None,
        "dema9": None,
        "volume": None,
        "rsi": None,
    }

    key = None
    for p in parts[2:]:
        pl = p.lower()
        if pl in ["open", "high", "low", "close", "ma20", "dema9", "volume", "rsi"]:
            key = pl
        else:
            if key is None:
                continue
            m = re.match(r"^-?\d+([.,]\d+)?$", p)
            if not m:
                continue
            val = float(p.replace(",", "."))
            data[key] = val

    return data


# ---------- POMOCNICZE KLASYFIKACJE ----------

def classify_momentum(close: Optional[float], dema9: Optional[float]) -> str:
    if close is None or dema9 is None:
        return "BRAK"
    if close > dema9:
        return "MOCNE"
    if close < dema9:
        return "SŁABE"
    return "NEUTRALNE"


def classify_bias(close: Optional[float], ma20: Optional[float]) -> str:
    if close is None or ma20 is None:
        return "BRAK"
    if close > ma20:
        return "UP"
    if close < ma20:
        return "DOWN"
    return "NEUTRAL"


def classify_rsi(rsi: Optional[float]) -> str:
    if rsi is None:
        return "BRAK"
    if rsi >= 55:
        return "MOCNE"
    if rsi >= 50:
        return "OK"
    return "SŁABE"


def classify_volume(vol: Optional[float]) -> str:
    if vol is None:
        return "BRAK"
    if vol >= 1500:
        return "MOCNE"
    if vol >= 500:
        return "OK"
    return "SŁABE"


# ---------- SYGNAŁ DLA POJEDYNCZEGO INTERWAŁU (7.9 PRO – UPROSZCZONY) ----------

def calc_signal_for_interval(c: dict) -> str:
    close = c.get("close")
    low = c.get("low")
    high = c.get("high")
    ma20 = c.get("ma20")
    dema9 = c.get("dema9")
    rsi = c.get("rsi")

    if close is None or low is None or high is None or ma20 is None:
        return "CZEKAJ"

    momentum = classify_momentum(close, dema9)
    bias = classify_bias(close, ma20)
    rsi_power = classify_rsi(rsi)

    rng = high - low
    if rng <= 0:
        return "CZEKAJ"

    dol = low + 0.20 * rng
    gor = low + 0.35 * rng

    # RESET – mocne wybicie w dół + słabe momentum + słabe RSI
    if close < low and momentum == "SŁABE" and rsi_power == "SŁABE":
        return "RESET"

    # CZEKAJ DO – cena poniżej dolnej strefy
    if close < dol:
        return "CZEKAJ"

    # CZEKAJ – cena powyżej górnej strefy
    if close > gor:
        return "CZEKAJ"

    # W strefie widełek
    if dol <= close <= gor:
        if momentum == "MOCNE" and bias == "UP" and rsi_power in ["MOCNE", "OK"]:
            return "BUY"
        if momentum == "SŁABE":
            return "PRAWIE BUY"

    # Domyślnie
    return "CZEKAJ"


# ---------- KORELACJA KGHM ↔ COPPER ----------

def copper_correlation_comment() -> str:
    """
    Patrzymy tylko na COPPER (dowolny interwał, np. M15/H1).
    Uproszczenie: bierzemy ostatni COPPER (jeśli jest).
    """
    copper_keys = [k for k in last_candles.keys() if k.startswith("COPPER|")]
    if not copper_keys:
        return "Korelacja: brak danych COPPER"

    # bierzemy ostatni
    key = copper_keys[-1]
    c = last_candles[key]

    close = c.get("close")
    low = c.get("low")
    high = c.get("high")
    ma20 = c.get("ma20")

    if close is None or low is None or high is None or ma20 is None:
        return "Korelacja: COPPER brak pełnych danych"

    rng = high - low
    if rng <= 0:
        return "Korelacja: COPPER brak zakresu"

    dol = low + 0.20 * rng
    gor = low + 0.35 * rng

    if close < low:
        return "Korelacja: COPPER RESET (poniżej L)"
    if dol <= close <= gor and close < ma20:
        return "Korelacja: COPPER w strefie BUY"
    if close > ma20:
        return "Korelacja: COPPER powyżej MA20 (ostrożnie)"

    return "Korelacja: COPPER neutralny"


# ---------- ŁĄCZENIE M5/M15/H1 W FINAL ----------

def combine_final_signal(ticker: str) -> (str, Optional[float], Optional[float], Optional[float], str):
    candles = {}
    signals = {}

    for iv in FINAL_INTERVALS:
        key = f"{ticker}|{iv}"
        if key in last_candles:
            candles[iv] = last_candles[key]
            signals[iv] = calc_signal_for_interval(last_candles[key])

    if not signals:
        return "CZEKAJ", None, None, None, "Brak danych interwałów"

    h1_sig = signals.get("H1")
    m15_sig = signals.get("M15")
    m5_sig = signals.get("M5")

    comment_parts = []
    if h1_sig:
        comment_parts.append(f"H1: {h1_sig}")
    if m15_sig:
        comment_parts.append(f"M15: {m15_sig}")
    if m5_sig:
        comment_parts.append(f"M5: {m5_sig}")

    # Prosta hierarchia FINAL
    if h1_sig == "BUY":
        if m15_sig == "BUY":
            final_signal = "BUY" if m5_sig == "BUY" else "PRAWIE BUY"
        elif m15_sig == "CZEKAJ":
            final_signal = "CZEKAJ"
        elif m15_sig == "SELL":
            final_signal = "RESET"
    elif h1_sig == "SELL":
        if m15_sig == "SELL":
            final_signal = "SELL" if m5_sig == "SELL" else "PRAWIE SELL"
        elif m15_sig == "CZEKAJ":
            final_signal = "CZEKAJ"
        elif m15_sig == "BUY":
            final_signal = "RESET"
    else:
        # brak H1
        if m15_sig == "BUY":
            final_signal = "BUY"
        elif m15_sig == "SELL":
            final_signal = "SELL"
        elif m5_sig in ["BUY", "SELL"]:
            final_signal = m5_sig
        else:
            final_signal = "CZEKAJ"

    # baza do TP3/widełek: M15 > H1 > M5
    base_iv = None
    if "M15" in candles:
        base_iv = candles["M15"]
    elif "H1" in candles:
        base_iv = candles["H1"]
    elif "M5" in candles:
        base_iv = candles["M5"]

    tp3 = None
    low = None
    high = None

    if base_iv:
        close = base_iv.get("close")
        l = base_iv.get("low")
        h = base_iv.get("high")
        ma20 = base_iv.get("ma20")

        if close is not None and l is not None and h is not None and ma20 is not None:
            rng = h - l
            dol = l + 0.20 * rng
            gor = l + 0.35 * rng
            low = dol
            high = gor

            dist = abs(close - ma20)
            if final_signal == "BUY":
                tp3 = close + 2.0 * dist
            elif final_signal == "SELL":
                tp3 = close - 2.0 * dist

    # komentarz PRO: momentum/RSI/Volume/Bias + korelacja (tylko KGHM)
    if base_iv:
        close = base_iv.get("close")
        dema9 = base_iv.get("dema9")
        rsi = base_iv.get("rsi")
        vol = base_iv.get("volume")
        ma20 = base_iv.get("ma20")

        momentum = classify_momentum(close, dema9)
        rsi_power = classify_rsi(rsi)
        vol_power = classify_volume(vol)
        bias = classify_bias(close, ma20)

        comment_parts.append(f"Momentum: {momentum} (close vs DEMA9)")
        comment_parts.append(f"RSI: {rsi_power} ({rsi})")
        comment_parts.append(f"Volume: {vol_power} ({vol})")
        comment_parts.append(f"Bias: {bias} (close vs MA20)")

    # korelacja tylko dla KGHM
    if ticker.upper() == "KGHM":
        comment_parts.append(copper_correlation_comment())

    comment = " | ".join(comment_parts) if comment_parts else "Brak komentarza"

    return final_signal, tp3, low, high, comment


# ---------- ENDPOINT ----------

@app.post("/voice-parse")
def voice_parse(req: VoiceRequest):
    try:
        data = parse_payload(req.text)
    except ValueError as e:
        return {"error": str(e)}

    ticker = data["ticker"]
    interval = data["interval"]

    key = f"{ticker}|{interval}"
    last_candles[key] = data

    # sygnał dla tego interwału (opcjonalnie)
    signal = calc_signal_for_interval(data)

    # FINAL z M5/M15/H1
    final_signal, tp3, low, high, comment = combine_final_signal(ticker)

    close = data.get("close")

    return {
        "ticker": ticker,
        "interval": interval,
        "signal": signal,
        "final_signal": final_signal,
        "close": close,
        "tp3": tp3,
        "low": low,
        "high": high,
        "comment": comment,
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
