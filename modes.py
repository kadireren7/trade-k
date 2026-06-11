"""Trade modu — tek sabit risk profili (SNIPER/BLITZ/INFERNO kaldırıldı)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mode:
    key: str
    name: str
    color: str
    max_trade_cash_ratio: float  # KOD FRENİ: tek işlem nakitin en fazla bu oranı
    total_ratio: float           # prompt: toplam öneriler nakitin en fazla bu oranı
    single_lo: int               # prompt: tek işlem alt sınır %
    single_hi: int               # prompt: tek işlem üst sınır %
    style_tr: str


MODES: dict[str, Mode] = {
    "standart": Mode(
        key="standart", name="STANDART", color="cyan",
        max_trade_cash_ratio=0.10, total_ratio=0.25, single_lo=5, single_hi=10,
        style_tr=(
            "MOD: STANDART. Sadece net, hacim teyitli kurulumlar öner; "
            "şüphe varsa BEKLE. Stoplar sıkı (%2-6), hedefler gerçekçi. "
            "Confidence 55'in altındaki hiçbir adayı listeleme."
        ),
    ),
}

DEFAULT_MODE = "standart"


def get(key: str | None = None) -> Mode:
    return MODES.get(key or DEFAULT_MODE, MODES[DEFAULT_MODE])


def risk_rules(mode: Mode) -> str:
    return f"""\
{mode.style_tr}

RİSK KURALLARI (kesinlikle uy):
- Önerilen TÜM işlemlerin toplam tutarı nakitin %{mode.total_ratio * 100:.0f}'ini AŞMASIN.
- Tek işlem nakitin %{mode.single_lo}-{mode.single_hi}'i arasında, asla daha fazla değil.
- Zaten pozisyonda olan varlığa ekleme önerme (çeşitlendirme öncelikli).
- basari_yuzdesi: gerçekçi ve TEMKİNLİ (tipik 40-70). Asla %80 üstü verme.
- Risk/ödül oranı EN AZ 1.5 olsun (kar_al uzaklığı ≥ zarar_kes uzaklığı × 1.5).
- Net fırsat yoksa az aday ver; hiç yoksa boş liste. Zorlama işlem üretme."""
