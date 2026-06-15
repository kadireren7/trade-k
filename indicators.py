"""Teknik analiz motoru — Binance OHLCV'den RSI, MACD, BB, EMA, ATR.

Harici kütüphane gerekmez: httpx zaten var, formüller sıfırdan yazıldı.
Kullanım: await indicators.analyze("BTCUSDT", "1h")
"""
from __future__ import annotations

import httpx
from dataclasses import dataclass, field

BINANCE_BASE = "https://api.binance.com"

# Geçerli zaman dilimleri
TIMEFRAMES = ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "12h", "1d")


@dataclass
class TAResult:
    symbol: str
    timeframe: str
    price: float
    rsi: float
    macd: float
    macd_signal: float
    macd_hist: float
    bb_upper: float
    bb_mid: float
    bb_lower: float
    bb_pct: float       # 0.0 = alt bant, 1.0 = üst bant
    ema20: float
    ema50: float
    atr: float
    vol_ratio: float    # anlık hacim / 20 mum ortalaması
    adx: float          # trend gücü 0-100 (>25 trend var, >50 güçlü)
    adx_plus_di: float  # +DI (alıcı gücü)
    adx_minus_di: float # -DI (satıcı gücü)
    support: float      # yakın destek (son 20 mum en düşüğü)
    resistance: float   # yakın direnç (son 20 mum en yükseği)
    signal: str         # GÜÇLÜ_AL | AL | BEKLE | SAT | GÜÇLÜ_SAT
    score: int          # -6 … +6
    reasons: list[str] = field(default_factory=list)


# ── Matematiksel yardımcılar ───────────────────────────────────────────────────

def _ema(prices: list[float], n: int) -> list[float]:
    if not prices:
        return []
    if len(prices) < n:
        avg = sum(prices) / len(prices)
        return [avg] * len(prices)
    k = 2.0 / (n + 1)
    out = [sum(prices[:n]) / n]
    for p in prices[n:]:
        out.append(p * k + out[-1] * (1.0 - k))
    return out


def _rsi(closes: list[float], n: int = 14) -> float:
    if len(closes) < n + 2:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(0.0, d))
        losses.append(max(0.0, -d))
    # Wilder smoothing: seed with SMA of first n periods, then EMA-style
    ag = sum(gains[:n]) / n
    al = sum(losses[:n]) / n
    for i in range(n, len(gains)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
    if al == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + ag / al)


def _bb(closes: list[float], n: int = 20, k: float = 2.0) -> tuple[float, float, float]:
    w = closes[-n:] if len(closes) >= n else closes
    mid = sum(w) / len(w)
    std = (sum((p - mid) ** 2 for p in w) / len(w)) ** 0.5
    return mid + k * std, mid, mid - k * std


def _atr(highs: list[float], lows: list[float], closes: list[float], n: int = 14) -> float:
    trs = [max(highs[i] - lows[i],
               abs(highs[i] - closes[i - 1]),
               abs(lows[i] - closes[i - 1]))
           for i in range(1, len(closes))]
    if not trs:
        return 0.0
    return sum(trs[-n:]) / min(n, len(trs))


def _adx(highs: list[float], lows: list[float], closes: list[float], n: int = 14) -> tuple[float, float, float]:
    """ADX, +DI, -DI — trend gücü ve yönü.

    ADX > 25: trend var  |  +DI > -DI: yükselen  |  -DI > +DI: düşen
    """
    if len(closes) < n * 2 + 1:
        return 25.0, 50.0, 50.0

    plus_dm, minus_dm, tr_list = [], [], []
    for i in range(1, len(closes)):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm.append(up if up > dn and up > 0 else 0.0)
        minus_dm.append(dn if dn > up and dn > 0 else 0.0)
        tr_list.append(max(highs[i] - lows[i],
                           abs(highs[i] - closes[i - 1]),
                           abs(lows[i] - closes[i - 1])))

    def wilder(data: list[float], period: int) -> list[float]:
        if len(data) < period:
            return [sum(data) / len(data)] * len(data)
        out = [sum(data[:period])]
        for x in data[period:]:
            out.append(out[-1] - out[-1] / period + x)
        return out

    atr14 = wilder(tr_list, n)
    pdm14 = wilder(plus_dm, n)
    ndm14 = wilder(minus_dm, n)

    pdi = [100.0 * p / a if a else 0.0 for p, a in zip(pdm14, atr14)]
    ndi = [100.0 * m / a if a else 0.0 for m, a in zip(ndm14, atr14)]
    dx = [100.0 * abs(p - m) / (p + m) if (p + m) else 0.0 for p, m in zip(pdi, ndi)]
    adx_list = wilder(dx, n)

    return (
        round(adx_list[-1], 1) if adx_list else 25.0,
        round(pdi[-1], 1) if pdi else 50.0,
        round(ndi[-1], 1) if ndi else 50.0,
    )


def _support_resistance(highs: list[float], lows: list[float], lookback: int = 20) -> tuple[float, float]:
    """Son 'lookback' mumdaki min/max → destek ve direnç seviyeleri."""
    w_h = highs[-lookback:] if len(highs) >= lookback else highs
    w_l = lows[-lookback:] if len(lows) >= lookback else lows
    return min(w_l), max(w_h)


def _macd(closes: list[float]) -> tuple[float, float]:
    e12 = _ema(closes, 12)
    e26 = _ema(closes, 26)
    # Uzunlukları eşitle
    if len(e12) > len(e26):
        e12 = e12[-len(e26):]
    elif len(e26) > len(e12):
        e26 = e26[-len(e12):]
    ml = [a - b for a, b in zip(e12, e26)]
    ms = _ema(ml, 9)
    return (ml[-1] if ml else 0.0), (ms[-1] if ms else 0.0)


# ── Sinyal motoru ──────────────────────────────────────────────────────────────

def _score_and_signal(
    price: float,
    rsi: float,
    macd_val: float,
    macd_sig: float,
    bb_upper: float,
    bb_lower: float,
    ema20: float,
    ema50: float,
    vol_ratio: float,
    adx: float = 0.0,
    plus_di: float = 0.0,
    minus_di: float = 0.0,
) -> tuple[str, int, list[str]]:
    score = 0
    reasons: list[str] = []

    # RSI
    if rsi < 25:
        score += 3; reasons.append(f"RSI kritik satım ({rsi:.0f})")
    elif rsi < 35:
        score += 2; reasons.append(f"RSI aşırı satım ({rsi:.0f})")
    elif rsi < 45:
        score += 1; reasons.append(f"RSI düşük ({rsi:.0f})")
    elif rsi > 75:
        score -= 3; reasons.append(f"RSI kritik alım ({rsi:.0f})")
    elif rsi > 65:
        score -= 2; reasons.append(f"RSI aşırı alım ({rsi:.0f})")
    elif rsi > 55:
        score -= 1; reasons.append(f"RSI yüksek ({rsi:.0f})")

    # MACD crossover
    if macd_val > macd_sig:
        score += 1; reasons.append("MACD yukarı kesim")
    else:
        score -= 1; reasons.append("MACD aşağı kesim")

    # Bollinger Bands
    if price < bb_lower:
        score += 2; reasons.append("Alt Bollinger altında")
    elif price > bb_upper:
        score -= 2; reasons.append("Üst Bollinger üstünde")

    # EMA trend
    if price > ema20 > ema50:
        score += 1; reasons.append("EMA20 > EMA50 (yükselen trend)")
    elif price < ema20 < ema50:
        score -= 1; reasons.append("EMA20 < EMA50 (düşen trend)")

    # ADX trend gücü ve yön onayı
    if adx > 25:
        if plus_di > minus_di:
            score += 1; reasons.append(f"ADX güçlü yükselen trend ({adx:.0f})")
        elif minus_di > plus_di:
            score -= 1; reasons.append(f"ADX güçlü düşen trend ({adx:.0f})")
    elif adx < 15:
        # Trendsiz piyasada sinyalleri hafiflet
        score = int(score * 0.8)
        reasons.append(f"ADX düşük ({adx:.0f}) — trendsiz piyasa")

    # Hacim onayı
    if vol_ratio > 1.5 and score > 0:
        score += 1; reasons.append(f"Yüksek hacim ×{vol_ratio:.1f}")
    elif vol_ratio > 1.5 and score < 0:
        score -= 1; reasons.append(f"Yüksek hacim ×{vol_ratio:.1f}")

    if score >= 5:
        sig = "GÜÇLÜ_AL"
    elif score >= 2:
        sig = "AL"
    elif score <= -5:
        sig = "GÜÇLÜ_SAT"
    elif score <= -2:
        sig = "SAT"
    else:
        sig = "BEKLE"

    return sig, score, reasons


# ── Async ana fonksiyon ────────────────────────────────────────────────────────

async def analyze(symbol: str, timeframe: str = "1h", limit: int = 120) -> TAResult:
    """Binance OHLCV çek → TA hesapla → TAResult döndür."""
    async with httpx.AsyncClient(timeout=12) as c:
        r = await c.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": symbol, "interval": timeframe, "limit": limit},
        )
        r.raise_for_status()
        raw = r.json()

    highs  = [float(k[2]) for k in raw]
    lows   = [float(k[3]) for k in raw]
    closes = [float(k[4]) for k in raw]
    vols   = [float(k[5]) for k in raw]

    price = closes[-1]
    rsi_val = _rsi(closes)
    macd_val, macd_sig_val = _macd(closes)
    macd_hist = macd_val - macd_sig_val
    bb_u, bb_m, bb_l = _bb(closes)
    bb_range = bb_u - bb_l
    bb_pct = (price - bb_l) / bb_range if bb_range > 0 else 0.5

    ema20_list = _ema(closes, 20)
    ema50_list = _ema(closes, 50)
    ema20 = ema20_list[-1] if ema20_list else price
    ema50 = ema50_list[-1] if ema50_list else price

    atr_val = _atr(highs, lows, closes)
    avg_vol = sum(vols[-20:]) / 20 if len(vols) >= 20 else (sum(vols) / len(vols) if vols else 1)
    vol_ratio = vols[-1] / avg_vol if avg_vol > 0 else 1.0
    adx_val, plus_di, minus_di = _adx(highs, lows, closes)
    support, resistance = _support_resistance(highs, lows)

    sig, score, reasons = _score_and_signal(
        price, rsi_val, macd_val, macd_sig_val, bb_u, bb_l, ema20, ema50, vol_ratio,
        adx_val, plus_di, minus_di,
    )

    return TAResult(
        symbol=symbol, timeframe=timeframe, price=price,
        rsi=rsi_val, macd=macd_val, macd_signal=macd_sig_val, macd_hist=macd_hist,
        bb_upper=bb_u, bb_mid=bb_m, bb_lower=bb_l, bb_pct=bb_pct,
        ema20=ema20, ema50=ema50, atr=atr_val, vol_ratio=vol_ratio,
        adx=adx_val, adx_plus_di=plus_di, adx_minus_di=minus_di,
        support=support, resistance=resistance,
        signal=sig, score=score, reasons=reasons,
    )


# ── Multi-timeframe analiz ────────────────────────────────────────────────────

MTF_FRAMES = ("15m", "1h", "4h", "1d")

SIGNAL_SCORE = {
    "GÜÇLÜ_AL": 2, "AL": 1, "BEKLE": 0, "SAT": -1, "GÜÇLÜ_SAT": -2
}
SIGNAL_EMOJI = {
    "GÜÇLÜ_AL": "⬆⬆", "AL": "⬆", "BEKLE": "→", "SAT": "⬇", "GÜÇLÜ_SAT": "⬇⬇"
}


async def multi_timeframe(symbol: str) -> str:
    """4 zaman dilimini analiz et, konsensüs skoru döndür (Rich markup)."""
    import asyncio
    tasks = [analyze(symbol, tf) for tf in MTF_FRAMES]
    raw = await asyncio.gather(*tasks, return_exceptions=True)

    results: list[TAResult] = []
    for r in raw:
        if isinstance(r, TAResult):
            results.append(r)

    if not results:
        return "[red3]MTF analiz başarısız[/]"

    lines = [f"[bold cyan]── MTF Analiz: {symbol} ──[/]"]
    total_score = 0
    for r in results:
        sc = SIGNAL_SCORE.get(r.signal, 0)
        total_score += sc
        em = SIGNAL_EMOJI.get(r.signal, "")
        c = "green3" if sc > 0 else ("red3" if sc < 0 else "grey58")
        adx_str = f"ADX:{r.adx:.0f}" + ("↑trend" if r.adx > 25 else "")
        lines.append(
            f"  [bold]{r.timeframe:>3}[/]  [{c}]{em} {r.signal:<10}[/]"
            f"  RSI:{r.rsi:.0f}  {adx_str}  ATR:{r.atr/r.price*100:.1f}%"
        )

    # Konsensüs
    max_score = len(results) * 2
    consensus_pct = (total_score / max_score * 100) if max_score else 0
    if total_score >= 4:
        verdict, vc = "GÜÇLÜ YUKARI MOMENTUM ⬆⬆", "green3"
    elif total_score >= 2:
        verdict, vc = "YUKARI EĞİLİMLİ ⬆", "green3"
    elif total_score <= -4:
        verdict, vc = "GÜÇLÜ AŞAĞI MOMENTUM ⬇⬇", "red3"
    elif total_score <= -2:
        verdict, vc = "AŞAĞI EĞİLİMLİ ⬇", "red3"
    else:
        verdict, vc = "KARIŞIK / BEKLE →", "gold3"

    lines.append(f"")
    lines.append(
        f"  Konsensüs: [{vc}][bold]{verdict}[/][/]  "
        f"(skor: {total_score:+d}/{max_score})"
    )

    if total_score >= 4:
        lines.append("  [green3]✔ Tüm zaman dilimleri uyumlu — yüksek güvenilirlik[/]")
    elif abs(total_score) <= 1:
        lines.append("  [gold3]~ Zaman dilimleri çelişiyor — bekle veya küçük poz.[/]")

    return "\n".join(lines)


# ── Çoklu sembol taraması ──────────────────────────────────────────────────────

async def scan_signals(
    symbols: list[str],
    timeframe: str = "1h",
    filter_signal: str | None = None,
) -> list[TAResult]:
    """Birden fazla sembolü paralel analiz et. filter_signal=None → hepsini döndür."""
    import asyncio
    results: list[TAResult] = []
    # Semaphore ile eş zamanlı istek sayısını sınırla (Binance rate limit)
    sem = asyncio.Semaphore(20)

    async def _safe(sym: str) -> TAResult | Exception:
        async with sem:
            try:
                return await analyze(sym, timeframe)
            except Exception as e:
                return e

    raw_results = await asyncio.gather(*[_safe(s) for s in symbols])
    for r in raw_results:
        if isinstance(r, TAResult):
            if filter_signal is None or r.signal == filter_signal or (
                filter_signal == "AL" and r.signal in ("AL", "GÜÇLÜ_AL")
            ) or (
                filter_signal == "SAT" and r.signal in ("SAT", "GÜÇLÜ_SAT")
            ):
                results.append(r)
    results.sort(key=lambda x: abs(x.score), reverse=True)
    return results
