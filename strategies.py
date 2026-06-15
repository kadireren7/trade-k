"""Multi-strateji framework — Momentum, Ortalamaya Dönüş, Kırılım + Konsensüs.

Her strateji bir TAResult alır ve -6…+6 skor üretir.
Konsensüs modu ağırlıklı ortalama alır.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from indicators import TAResult

STRATEGIES = ("momentum", "dönüş", "kırılım", "konsensüs")
STRATEGY_NAMES = {
    "momentum":   "Momentum (Trend Takibi)",
    "dönüş":      "Ortalamaya Dönüş",
    "kırılım":    "Kırılım (Breakout)",
    "konsensüs":  "Konsensüs (3'ü Bir Arada)",
}


@dataclass
class StrategyResult:
    name: str
    signal: str          # GÜÇLÜ_AL | AL | BEKLE | SAT | GÜÇLÜ_SAT
    score: int           # -6 … +6
    confidence: float    # 0–100 %
    reasons: list[str]


# ── Momentum Stratejisi ───────────────────────────────────────────────────────
# Prensip: Trend yönünde işlem yap (trend senin arkadaşın).
# Girdi sinyali: EMA crossover + MACD momentum + RSI yükselen trend bölgesi.

def momentum(ta: "TAResult") -> StrategyResult:
    score = 0
    reasons: list[str] = []

    # EMA 20/50 crossover — ana trend filtresi
    if ta.ema20 > ta.ema50 * 1.002:   # belirgin fark
        score += 2; reasons.append("EMA20 > EMA50 — yükselen trend")
    elif ta.ema20 < ta.ema50 * 0.998:
        score -= 2; reasons.append("EMA20 < EMA50 — düşen trend")

    # Fiyat EMA20 üstünde mi?
    if ta.price > ta.ema20:
        score += 1; reasons.append("Fiyat EMA20 üstünde")
    else:
        score -= 1; reasons.append("Fiyat EMA20 altında")

    # MACD momentum
    if ta.macd > ta.macd_signal and ta.macd_hist > 0:
        score += 2; reasons.append("MACD pozitif ve yükseliyor")
    elif ta.macd > ta.macd_signal:
        score += 1; reasons.append("MACD sinyal üstünde")
    elif ta.macd < ta.macd_signal and ta.macd_hist < 0:
        score -= 2; reasons.append("MACD negatif ve düşüyor")
    else:
        score -= 1; reasons.append("MACD sinyal altında")

    # RSI — aşırı alım/satım dışındaysa momentum sağlıklı
    if 40 <= ta.rsi <= 65:
        score += 1; reasons.append(f"RSI sağlıklı trend bölgesi ({ta.rsi:.0f})")
    elif ta.rsi > 70:
        score -= 2; reasons.append(f"RSI aşırı alım ({ta.rsi:.0f}) — momentum tükeniyor")
    elif ta.rsi < 35:
        score -= 1; reasons.append(f"RSI düşük ({ta.rsi:.0f}) — zayıf momentum")

    # Hacim onayı
    if ta.vol_ratio > 1.4:
        score += 1 if score > 0 else -1
        reasons.append(f"Hacim onayı ×{ta.vol_ratio:.1f}")

    return _make_result("Momentum", score, reasons)


# ── Ortalamaya Dönüş Stratejisi ───────────────────────────────────────────────
# Prensip: Aşırı ucuzlayan geri döner, aşırı pahalılanan düşer.
# Girdi sinyali: RSI aşırı satım + BB alt bandı + Stoch düşük.

def mean_reversion(ta: "TAResult") -> StrategyResult:
    score = 0
    reasons: list[str] = []

    # RSI aşırı satım/alım — bu stratejinin kalbi
    if ta.rsi < 25:
        score += 4; reasons.append(f"RSI kritik aşırı satım ({ta.rsi:.0f})")
    elif ta.rsi < 35:
        score += 3; reasons.append(f"RSI aşırı satım ({ta.rsi:.0f})")
    elif ta.rsi < 45:
        score += 1; reasons.append(f"RSI düşük ({ta.rsi:.0f})")
    elif ta.rsi > 75:
        score -= 4; reasons.append(f"RSI kritik aşırı alım ({ta.rsi:.0f})")
    elif ta.rsi > 65:
        score -= 3; reasons.append(f"RSI aşırı alım ({ta.rsi:.0f})")
    elif ta.rsi > 55:
        score -= 1; reasons.append(f"RSI yüksek ({ta.rsi:.0f})")

    # Bollinger Band konumu
    if ta.bb_pct < 0.1:
        score += 2; reasons.append(f"Alt Bollinger altında (pct:{ta.bb_pct:.0%})")
    elif ta.bb_pct < 0.25:
        score += 1; reasons.append(f"Alt Bollinger yakını")
    elif ta.bb_pct > 0.9:
        score -= 2; reasons.append(f"Üst Bollinger üstünde (pct:{ta.bb_pct:.0%})")
    elif ta.bb_pct > 0.75:
        score -= 1; reasons.append(f"Üst Bollinger yakını")

    # MACD — dönüş için sinyal çizgisi kesimi
    if ta.macd > ta.macd_signal:
        score += 1; reasons.append("MACD yukarı kesim (dönüş onayı)")
    else:
        score -= 1; reasons.append("MACD henüz sinyal altında")

    return _make_result("Ortalamaya Dönüş", score, reasons)


# ── Kırılım (Breakout) Stratejisi ────────────────────────────────────────────
# Prensip: Güçlü hacimle direnci kıran fiyat devam eder.
# Girdi sinyali: Fiyat BB mid üstünde + EMA yükseliyor + Hacim artıyor.

def breakout(ta: "TAResult") -> StrategyResult:
    score = 0
    reasons: list[str] = []

    # Fiyat orta BB üstünde mi?
    bb_pos = ta.bb_pct
    if bb_pos > 0.65:
        score += 2; reasons.append(f"BB üst bölgede ({bb_pos:.0%}) — kırılım potansiyeli")
    elif bb_pos > 0.5:
        score += 1; reasons.append(f"BB orta üstü ({bb_pos:.0%})")
    elif bb_pos < 0.35:
        score -= 2; reasons.append(f"BB alt bölgede ({bb_pos:.0%}) — kırılım yok")
    else:
        score -= 1; reasons.append(f"BB nötr bölge")

    # Hacim — kırılımın olmazsa olmazı
    if ta.vol_ratio > 2.0:
        score += 3; reasons.append(f"Çok güçlü hacim kırılımı ×{ta.vol_ratio:.1f}")
    elif ta.vol_ratio > 1.5:
        score += 2; reasons.append(f"Güçlü hacim ×{ta.vol_ratio:.1f}")
    elif ta.vol_ratio > 1.2:
        score += 1; reasons.append(f"Yüksek hacim ×{ta.vol_ratio:.1f}")
    elif ta.vol_ratio < 0.8:
        score -= 2; reasons.append(f"Düşük hacim ×{ta.vol_ratio:.1f} — kırılım zayıf")

    # EMA trend yönü
    if ta.ema20 > ta.ema50 and ta.price > ta.ema20:
        score += 1; reasons.append("Trend ve fiyat uyumlu")
    elif ta.ema20 < ta.ema50:
        score -= 1; reasons.append("Ana trend düşüyor — yükseliş kırılımı riskli")

    # RSI — ne çok yüksek ne çok düşük (40-60 ideal kırılım bölgesi)
    if 40 <= ta.rsi <= 65:
        score += 1; reasons.append(f"RSI kırılım bölgesinde ({ta.rsi:.0f})")
    elif ta.rsi > 70:
        score -= 1; reasons.append(f"RSI yüksek, kırılım yorgun ({ta.rsi:.0f})")

    return _make_result("Kırılım", score, reasons)


# ── Konsensüs (3'ü bir arada) ────────────────────────────────────────────────

def consensus(ta: "TAResult") -> StrategyResult:
    """3 stratejiyi ağırlıklandırarak birleştir."""
    r_mom = momentum(ta)
    r_rev = mean_reversion(ta)
    r_brk = breakout(ta)

    # Ağırlıklar: hangi piyasa koşulunda ağır basması gerektiği fikrine göre
    # Ortalaması alınarak hem trend hem dönüş hem kırılım sinyalleri değerlendiriliyor
    weighted = r_mom.score * 0.35 + r_rev.score * 0.40 + r_brk.score * 0.25
    combined_score = int(round(weighted))

    reasons = [
        f"Momentum: {r_mom.signal} ({r_mom.score:+d})",
        f"Ort.Dönüş: {r_rev.signal} ({r_rev.score:+d})",
        f"Kırılım: {r_brk.signal} ({r_brk.score:+d})",
    ]
    return _make_result("Konsensüs", combined_score, reasons)


# ── Strateji çalıştırıcı ─────────────────────────────────────────────────────

def evaluate(ta: "TAResult", strategy: str = "konsensüs") -> StrategyResult:
    """Aktif stratejiyi TAResult üzerinde çalıştır."""
    fn = {
        "momentum": momentum,
        "dönüş": mean_reversion,
        "kırılım": breakout,
        "konsensüs": consensus,
    }.get(strategy, consensus)
    return fn(ta)


def evaluate_all(ta: "TAResult") -> list[StrategyResult]:
    """3 stratejiyi hepsini ayrı ayrı çalıştır."""
    return [momentum(ta), mean_reversion(ta), breakout(ta), consensus(ta)]


# ── Yardımcı ─────────────────────────────────────────────────────────────────

def _make_result(name: str, score: int, reasons: list[str]) -> StrategyResult:
    score = max(-6, min(6, score))
    confidence = min(100.0, abs(score) / 6 * 100)
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
    return StrategyResult(name=name, signal=sig, score=score,
                          confidence=round(confidence, 1), reasons=reasons)
