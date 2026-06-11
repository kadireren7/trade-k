"""Claude öneri performans takibi — recommendations.json

Her /tara ve /ai önerisi buraya kaydedilir. Öneriler mark-to-market
değerlendirilir: AL önerisi sonrası fiyat yükseldiyse kazanan, düştüyse
kaybeden (SAT için tersi). Geçmiş isabet oranı, yeni önerilerin başarı
yüzdesini temkinli yönde kalibre etmek için kullanılır.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_FILE = Path(__file__).parent / "recommendations.json"
PENDING_TTL = 24 * 3600   # 24 saat onaylanmayan öneri süresi dolmuş sayılır
MIN_SAMPLES = 5           # kalibrasyon için gereken asgari değerlendirilmiş öneri

STATUS_TR = {
    "pending": "bekliyor",
    "approved": "onaylandı",
    "rejected": "reddedildi",
    "expired": "süresi doldu",
}


@dataclass
class Recommendation:
    id: str
    timestamp: float
    symbol: str
    side: str               # AL | SAT
    suggested_amount: float
    confidence_percent: int
    reason: str
    entry_price: float      # öneri anındaki fiyat
    status: str = "pending"  # pending | approved | rejected | expired


class Tracker:
    def __init__(self, recs: list[Recommendation] | None = None,
                 path: Path | None = None) -> None:
        self.recs = recs or []
        self.path = path or DEFAULT_FILE

    # ---- kalıcılık ----
    @classmethod
    def load(cls, path: Path | None = None) -> "Tracker":
        path = path or DEFAULT_FILE
        recs = []
        if path.exists():
            recs = [Recommendation(**d) for d in json.loads(path.read_text())]
        t = cls(recs, path)
        # 24 saatten eski bekleyen öneriler artık geçersiz
        now = time.time()
        changed = False
        for r in t.recs:
            if r.status == "pending" and now - r.timestamp > PENDING_TTL:
                r.status = "expired"
                changed = True
        if changed:
            t.save()
        return t

    def save(self) -> None:
        self.path.write_text(json.dumps(
            [asdict(r) for r in self.recs], indent=2, ensure_ascii=False))

    # ---- kayıt ----
    def add(self, items: list[dict]) -> list[Recommendation]:
        """Yeni tarama sonuçları: eski bekleyenler expired olur, yeniler pending."""
        self.expire_pending()
        new = [
            Recommendation(id=uuid.uuid4().hex[:8], timestamp=time.time(), **it)
            for it in items
        ]
        self.recs.extend(new)
        self.save()
        return new

    def set_status(self, ids: list[str], status: str) -> None:
        idset = set(ids)
        for r in self.recs:
            if r.id in idset and r.status == "pending":
                r.status = status
        self.save()

    def expire_pending(self) -> None:
        for r in self.recs:
            if r.status == "pending":
                r.status = "expired"

    def symbols(self) -> list[str]:
        """Değerlendirme için fiyatı gereken benzersiz semboller."""
        seen: list[str] = []
        for r in self.recs:
            if r.symbol not in seen:
                seen.append(r.symbol)
        return seen

    # ---- değerlendirme ----
    @staticmethod
    def pnl_of(rec: Recommendation, price: float) -> float:
        """Önerinin sanal PnL'i: yön doğruysa pozitif."""
        change = (price - rec.entry_price) / rec.entry_price
        if rec.side == "SAT":
            change = -change
        return change * rec.suggested_amount

    def stats(self, prices: dict[str, float]) -> dict:
        """/performans için özet. PnL ve kazan/kaybet sadece onaylananlar üzerinden."""
        approved = [r for r in self.recs if r.status == "approved"]
        wins = losses = 0
        pnl = 0.0
        for r in approved:
            p = prices.get(r.symbol)
            if p is None or r.entry_price <= 0:
                continue
            v = self.pnl_of(r, p)
            pnl += v
            if v > 0:
                wins += 1
            else:
                losses += 1
        evaluated = wins + losses
        return {
            "toplam_oneri": len(self.recs),
            "onaylanan": len(approved),
            "reddedilen": sum(r.status == "rejected" for r in self.recs),
            "suresi_dolan": sum(r.status == "expired" for r in self.recs),
            "bekleyen": sum(r.status == "pending" for r in self.recs),
            "kazanan": wins,
            "kaybeden": losses,
            "toplam_pnl": pnl,
            "basari_orani": (wins / evaluated * 100) if evaluated else None,
        }

    def win_rate(self, prices: dict[str, float]) -> tuple[float | None, int]:
        """Kalibrasyon için yön isabeti — bekleyenler hariç tüm öneriler.

        Reddedilen/süresi dolan öneriler de sayılır: Claude'un çağrısının
        isabeti, kullanıcının onaylayıp onaylamadığından bağımsızdır.
        """
        wins = total = 0
        for r in self.recs:
            if r.status == "pending":  # henüz taze, fiyat oynamadı
                continue
            p = prices.get(r.symbol)
            if p is None or r.entry_price <= 0:
                continue
            total += 1
            if self.pnl_of(r, p) > 0:
                wins += 1
        return (wins / total * 100 if total else None), total

    def calibrate(self, stated: int, prices: dict[str, float]) -> int:
        """Claude'un beyan ettiği yüzdeyi geçmiş isabete göre AŞAĞI çek.

        Yeterli geçmiş yoksa (MIN_SAMPLES'tan az örnek) beyan aynen kalır;
        geçmiş varsa beyan ile gerçek isabet oranının ortalaması alınır ama
        sonuç asla beyanın ÜSTÜNE çıkamaz (temkinli yönde tek taraflı).
        """
        rate, n = self.win_rate(prices)
        if rate is None or n < MIN_SAMPLES:
            return stated
        return max(5, min(stated, round((stated + rate) / 2)))
