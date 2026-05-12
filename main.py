from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict, Optional
import uvicorn
import re

app = FastAPI()

# Pamięć ostatnich świec per (ticker, interval)
last_candles: Dict[str, dict] = {}

# Interwały, które bierzemy do FINAL
FINAL_INTERVALS = ["M5", "M15", "H1"]


class VoiceRequest(BaseModel):
    text: str


def parse_payload(text: str) -> dict:
    """
    Oczekiwany format:
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

    # prosty parser par klucz-wartość
    key = None
    for p in parts[2:]:
        if p.lower() in ["open", "high", "low", "close", "ma20", "dema9", "volume", "rsi"]:
            key = p.lower()
        else:
            if key is None:
                continue
            # liczba
            m = re.match(r"^-?\d+([.,]\d+)?$", p)
            if not m:
                continue
            val = float(p.replace(",", "."))
            data[key] = val

    return data


def calc_signal_for_interval(candle: dict) -> str:
    """
    Bardzo uproszczona logika sygnału dla pojedynczego interwału.
    Możesz tu wstawić swoją logikę 7.9 PRO.
    """
    close = candle.get("close")
    ma20 = candle.get("ma20")
    rsi = candle.get("rsi")

    if close is None or ma20 is None:
        return "CZEKAJ"

    diff = close - ma20

    if rsi is not None:
        if rsi > 70 and diff > 0:
            return "SELL"
        if rsi < 30 and diff < 0:
            return "BUY"

    if diff > 0:
        return "BUY"
    if diff < 0:
        return "SELL"
    return "CZEKAJ"


def combine_final_signal(ticker: str) -> (str, Optional[float], Optional[float], Optional[float], str):
    """
    Łączy M5, M15, H1 w jeden sygnał FINAL.
    Prosta hierarchia:
    - H1 = kierunek
    - M15 = sygnał wejścia
    - M5 = potwierdzenie
    Zwraca: final_signal, tp3, low, high, comment
    """
    candles = {}
    for iv in FINAL_INTERVALS:
        key = f"{ticker}|{iv}"
        if key in last_candles:
            candles[iv] = last_candles[key]

    # jeśli mamy tylko jeden interwał → użyj jego sygnału
    signals = {}
    for iv, c in candles.items():
        signals[iv] = calc_signal_for_interval(c)

    if not signals:
        return "CZEKAJ", None, None, None, "Brak danych interwałów"

    # domyślnie
    final_signal = "CZEKAJ"
    comment_parts = []

    h1_sig = signals.get("H1")
    m15_sig = signals.get("M15")
    m5_sig = signals.get("M5")

    if h1_sig:
        comment_parts.append(f"H1: {h1_sig}")
    if m15_sig:
        comment_parts.append(f"M15: {m15_sig}")
    if m5_sig:
        comment_parts.append(f"M5: {m5_sig}")

    # prosta tabela decyzyjna
    if h1_sig == "BUY":
        if m15_sig == "BUY":
            if m5_sig == "BUY":
                final_signal = "BUY"
            else:
                final_signal = "PRAWIE BUY"
        elif m15_sig == "CZEKAJ":
            final_signal = "CZEKAJ"
        elif m15_sig == "SELL":
            final_signal = "RESET"
    elif h1_sig == "SELL":
        if m15_sig == "SELL":
            if m5_sig == "SELL":
                final_signal = "SELL"
            else:
                final_signal = "PRAWIE SELL"
        elif m15_sig == "CZEKAJ":
            final_signal = "CZEKAJ"
        elif m15_sig == "BUY":
            final_signal = "RESET"
    else:
        # brak H1 → opieramy się na M15/M5
        if m15_sig == "BUY":
            final_signal = "BUY"
        elif m15_sig == "SELL":
            final_signal = "SELL"
        elif m5_sig in ["BUY", "SELL"]:
            final_signal = m5_sig
        else:
            final_signal = "CZEKAJ"

    # TP3 i widełki — prosta wersja: z M15 jeśli jest, inaczej z H1, inaczej z M5
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

    if base_iv and base_iv.get("close") is not None and base_iv.get("ma20") is not None:
        close = base_iv["close"]
        ma20 = base_iv["ma20"]
        rng = abs(close - ma20)

        if final_signal == "BUY":
            tp3 = close + 1.5 * rng
            low = close - 0.5 * rng
            high = close + 0.3 * rng
        elif final_signal == "SELL":
            tp3 = close - 1.5 * rng
            low = close - 0.3 * rng
            high = close + 0.5 * rng

    comment = " | ".join(comment_parts) if comment_parts else "Brak komentarza"

    return final_signal, tp3, low, high, comment


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

    # wylicz sygnał dla tego interwału (opcjonalnie)
    signal = calc_signal_for_interval(data)

    # wylicz sygnał FINAL na podstawie wszystkich interwałów
    final_signal, tp3, low, high, comment = combine_final_signal(ticker)

    # close do wyświetlenia w jednym wierszu
    close = data.get("close")

    return {
        "ticker": ticker,
        "interval": interval,
        "signal": signal,          # sygnał dla tego interwału (opcjonalnie)
        "final_signal": final_signal,  # to czyta tabela
        "close": close,
        "tp3": tp3,
        "low": low,
        "high": high,
        "comment": comment,
    }


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000)
