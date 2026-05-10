from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import re
from typing import Optional

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class VoiceReq(BaseModel):
    text: str

class VoiceResp(BaseModel):
    ticker: Optional[str] = None
    interval: Optional[str] = None
    time: Optional[str] = None
    open: Optional[float] = None
    low: Optional[float] = None
    high: Optional[float] = None
    close: Optional[float] = None
    ma20: Optional[float] = None
    dema9: Optional[float] = None
    rsi: Optional[float] = None
    volume: Optional[float] = None
    signal: Optional[str] = None
    widełki: Optional[str] = None
    tp: Optional[str] = None
    comment: Optional[str] = None

class TomorrowReq(BaseModel):
    text: str

class TomorrowResp(BaseModel):
    ticker: Optional[str] = None
    interval: Optional[str] = None
    good_for_tomorrow: bool = False
    signal: Optional[str] = None
    comment: Optional[str] = None

def to_float(x: Optional[str]):
    if not x:
        return None
    x = x.replace(",", ".").replace(" ", "")
    try:
        return float(x)
    except:
        return None

def extract_num(pattern: str, text: str):
    m = re.search(pattern, text)
    return to_float(m.group(1)) if m else None

def parse_common(text: str) -> dict:
    t = text.lower()

    ticker = None
    for tk in ["kghm","orlen","pzu","pko","peo","mbank","jsw","cd projekt","allegro","dino","lpp","xtb"]:
        if tk in t:
            ticker = tk.upper()

    interval = "M15"
    for iv in ["m1","m5","m15","m30","h1","h4","d1"]:
        if iv in t:
            interval = iv.upper()

    time = None
    m = re.search(r"(\d{1,2}[:\.]\d{2})", t)
    if m:
        time = m.group(1).replace(".", ":")

    O = extract_num(r"o\s*([\d\.,]+)", t)
    L = extract_num(r"l\s*([\d\.,]+)", t)
    H = extract_num(r"h\s*([\d\.,]+)", t)
    C = extract_num(r"c\s*([\d\.,]+)", t)
    MA20 = extract_num(r"ma20\s*([\d\.,]+)", t)
    DEMA9 = extract_num(r"dema9\s*([\d\.,]+)", t) or extract_num(r"bema9\s*([\d\.,]+)", t)
    RSI = extract_num(r"rsi\s*([\d\.,]+)", t)
    VOL = extract_num(r"wolumen\s*([\d\.,]+)", t)

    return {
        "ticker": ticker,
        "interval": interval,
        "time": time,
        "open": O,
        "low": L,
        "high": H,
        "close": C,
        "ma20": MA20,
        "dema9": DEMA9,
        "rsi": RSI,
        "volume": VOL,
    }

def calc_widelki(low, high, signal: str | None):
    if low is None or high is None:
        return None
    r = high - low
    if signal == "SELL":
        dol = high - r * 0.35
        gor = high - r * 0.20
    else:
        dol = low + r * 0.20
        gor = low + r * 0.35
    return f"{dol:.2f}–{gor:.2f}"

def calc_tp(low, high, close, signal: str | None):
    if low is None or high is None or close is None:
        return None
    r = abs(high - low)
    if signal == "SELL":
        tp1 = close - r * 0.5
        tp2 = close - r * 1.0
        tp3 = close - r * 1.5
    else:
        tp1 = close + r * 0.5
        tp2 = close + r * 1.0
        tp3 = close + r * 1.5
    return f"{tp1:.2f} / {tp2:.2f} / {tp3:.2f}"

def signal_multi_tf(d: dict) -> tuple[str, str]:
    C = d["close"]
    L = d["low"]
    H = d["high"]
    MA20 = d["ma20"]
    DEMA9 = d["dema9"]
    RSI = d["rsi"]
    VOL = d["volume"]
    interval = d["interval"]

    if C is None or L is None or H is None:
        return "CZEKAJ", "Brak danych."

    dol = L + (H - L) * 0.20
    gor = L + (H - L) * 0.35

    momentum = "SŁABE"
    bias = "DOWN"
    rsiPower = "SŁABE"
    volPower = "SŁABE"

    if DEMA9 is not None and C > DEMA9:
        momentum = "MOCNE"
    if MA20 is not None and C > MA20:
        bias = "UP"
    if RSI is not None:
        if RSI >= 55:
            rsiPower = "MOCNE"
        elif RSI >= 50:
            rsiPower = "OK"
    if VOL is not None:
        if VOL >= 1500:
            volPower = "MOCNE"
        elif VOL >= 500:
            volPower = "OK"

    s = "CZEKAJ"

    # M5 — bardziej czułe na momentum
    if interval == "M5":
        if dol <= C <= gor and momentum == "MOCNE" and rsiPower != "SŁABE":
            s = "BUY"
        elif dol <= C <= gor and momentum == "SŁABE":
            s = "PRAWIE BUY"
        elif C < dol:
            s = "CZEKAJ DO"
    # M15 — główne widełki
    elif interval == "M15":
        if dol <= C <= gor and momentum == "MOCNE" and bias == "UP" and rsiPower != "SŁABE" and volPower != "SŁABE":
            s = "BUY"
        elif dol <= C <= gor and (momentum == "SŁABE" or rsiPower == "SŁABE"):
            s = "PRAWIE BUY"
        elif C < dol:
            s = "CZEKAJ DO"
        elif C > gor:
            s = "CZEKAJ"
    # H1 — bias dnia, bardziej ostrożny
    elif interval == "H1":
        if bias == "UP" and momentum == "MOCNE" and C > dol and C < gor:
            s = "BUY"
        elif bias == "UP" and C < dol:
            s = "CZEKAJ DO"
        else:
            s = "CZEKAJ"
    # D1 — kierunek dnia, raczej komentarz niż agresywny sygnał
    elif interval == "D1":
        if bias == "UP" and momentum == "MOCNE":
            s = "BUY"
        else:
            s = "CZEKAJ"

    # reset logic (uniwersalne)
    if C < dol * 0.995 and momentum == "SŁABE" and rsiPower == "SŁABE":
        s = "UWAGA RESET"
    if C < L and momentum == "SŁABE" and rsiPower == "SŁABE":
        s = "RESET"

    comment = f"TF={interval}, Momentum={momentum}, Bias={bias}, RSI={rsiPower}, VOL={volPower}"
    return s, comment

@app.post("/voice-parse", response_model=VoiceResp)
def voice_parse(req: VoiceReq):
    d = parse_common(req.text)
    sig, comment = signal_multi_tf(d)
    wid = calc_widelki(d["low"], d["high"], sig)
    tp = calc_tp(d["low"], d["high"], d["close"], sig)

    return VoiceResp(
        ticker=d["ticker"],
        interval=d["interval"],
        time=d["time"],
        open=d["open"],
        low=d["low"],
        high=d["high"],
        close=d["close"],
        ma20=d["ma20"],
        dema9=d["dema9"],
        rsi=d["rsi"],
        volume=d["volume"],
        signal=sig,
        widełki=wid,
        tp=tp,
        comment=comment
    )

# ============================
# NA JUTRO — VWAP ONLY
# ============================

def parse_tomorrow(text: str) -> dict:
    d = parse_common(text)
    t = text.lower()
    vwap = extract_num(r"vwap\s*([\d\.,]+)", t)
    d["vwap"] = vwap
    return d

def logic_tomorrow(d: dict) -> tuple[bool, str, str]:
    ticker = d["ticker"] or "???"
    interval = "D1/H1"
    C = d["close"]
    MA20 = d["ma20"]
    DEMA9 = d["dema9"]
    RSI = d["rsi"]
    VOL = d["volume"]
    VWAP = d.get("vwap")

    score = 0
    parts = []

    if C is not None and MA20 is not None and C > MA20:
        score += 1
        parts.append("D1: C > MA20 (trend UP)")
    if DEMA9 is not None and MA20 is not None and DEMA9 > MA20:
        score += 1
        parts.append("D1: DEMA9 > MA20 (momentum UP)")
    if RSI is not None and 45 <= RSI <= 70:
        score += 1
        parts.append("RSI w zdrowym zakresie (45–70)")
    if VOL is not None and VOL >= 1000:
        score += 1
        parts.append("Wolumen powyżej średniej")
    if VWAP is not None and C is not None and C > VWAP:
        score += 1
        parts.append("H1: C > VWAP (bias UP)")

    good = score >= 3
    sig = "BUY" if good else "CZEKAJ"
    comment = "; ".join(parts) if parts else "Brak mocnych argumentów."

    return good, sig, comment

@app.post("/parse", response_model=TomorrowResp)
def parse_tomorrow_endpoint(req: TomorrowReq):
    d = parse_tomorrow(req.text)
    good, sig, comment = logic_tomorrow(d)
    return TomorrowResp(
        ticker=d["ticker"],
        interval="D1/H1",
        good_for_tomorrow=good,
        signal=sig,
        comment=comment
    )
