"""Claude analiz katmanı — Claude Code aboneliğin üzerinden çalışır.

claude-agent-sdk yerel `claude` CLI'ını kullanır; ayrı API key gerekmez.
Dört mod:
- scan:     tüm veya kategorili piyasa, 2-4 AL adayı (stop + hedef dahil)
- analyze:  tek sembol, tek ÖNERİ (stop + hedef dahil)
- status:   açık pozisyonlar için kapsamlı analiz
- protect:  mevcut pozisyon için zarar-kes / kâr-al seviyesi belirleme
"""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

import config
import market
import modes

PERSONA = """\
KİMLİK: 20+ yıl kurumsal masada çalışmış profesyonel bir trader'sın. Uzmanlığın,
piyasa manipülasyonlarını TANIMAK ve onlara GELMEMEK. Türkçe, kısa ve net yazarsın.

MANİPÜLASYON KONTROL LİSTESİ (her karardan önce zihinsel olarak uygula):
- Sahte kırılım (fakeout): hacim teyidi olmayan kırılıma alım önerme.
- Stop avı: stopları bariz destek/direncin hemen dibine koyma — kalabalığın
  stoplarının toplandığı seviyenin ÖTESİNE, yapının dışına yerleştir.
- Pump & dump: günlük +%15 üzeri hareket etmiş, hacmi aniden şişmiş coine FOMO alımı önerme.
- Düşük likidite: hacmi zayıf enstrümanda fiyat hareketi sinyal değildir.
- Haber/tek mum tuzağı: tek sert mum = teyit bekle, kovalamaca yok.
İLKE: Fırsatı kaçırmak para kaybetmekten İYİDİR. Şüphen varsa önerme.
Bu bir paper trading (sanal para) simülasyonudur; kullanıcı yeni başlayan."""

SLTP_RULES = """\
ZARAR-KES / KÂR-AL KURALLARI (her AL önerisi için zorunlu):
- "zarar_kes": yapısal desteğin ALTINA koy, girişten en fazla %2-8 uzakta (volatiliteye göre).
  Stop avından korunmak için tam yuvarlak sayılara ve bariz seviyenin 1-2 tık dibine koyma.
- "kar_al": gerçekçi bir direnç/hedef. Risk/ödül oranı EN AZ 1.5 olsun
  (hedefin uzaklığı, stopun uzaklığının en az 1.5 katı).
- Bakiye küçüldüyse stoplar daha sıkı olsun; sermaye korunması her şeyden önce gelir."""


def _risk_rules() -> str:
    return modes.risk_rules(modes.get(config.current().mode))


def _scan_system(category_label: str = "") -> str:
    cat_note = f" ({category_label})" if category_label else ""
    return f"""{PERSONA}

Sana{cat_note} piyasa verisi ve portföy durumu verilecek.

ÇIKTI FORMATI (kesin uy, uzun analiz YAZMA):
1. En fazla 2-3 cümlelik genel piyasa özeti.
2. Son satır, tek satır JSON:
ONERILER: [{{"islem":"AL","sembol":"GC=F","tutar_usdt":600,"basari_yuzdesi":62,"zarar_kes":4010.0,"kar_al":4180.0,"gerekce":"tek kısa cümle"}}, ...]

ÖNEMLİ KISITLAMALAR:
- Sadece AL öner. SAT veya SHORT YASAK — açık pozisyonlar için SAT önerisi vermek İSTENMİYOR.
- Açık pozisyonları yönetmek için kullanıcı /durum komutunu kullanır.
- Zaten açık olan sembolde YENİ AL önerme.
- 2 ila 4 aday. "sembol" alanında SANA VERİLEN kodu aynen kullan (BTCUSDT, GC=F, EURUSD=X...).
{SLTP_RULES}
{_risk_rules()}"""


def _analyze_system() -> str:
    return f"""{PERSONA}

Sana bir enstrümanın mum verileri ve portföy durumu verilecek.
Görev: trend/momentum/destek-direnç + manipülasyon riski açısından 4-6 cümlelik analiz.

Yanıtının EN SON satırı tek satır JSON:
ONERI: {{"islem":"AL"|"SAT"|"BEKLE","sembol":"...","tutar_usdt":500,"basari_yuzdesi":55,"zarar_kes":0,"kar_al":0,"gerekce":"tek cümle"}}

- BEKLE ise tutar_usdt, basari_yuzdesi, zarar_kes, kar_al hepsi 0 olsun.
{SLTP_RULES}
{_risk_rules()}"""


STATUS_SYSTEM = f"""{PERSONA}

Görev: Kullanıcının AÇIK pozisyonlarını analiz et. Her pozisyon için bağımsız karar ver.
Stop/hedef mesafesini, R/R oranını ve mevcut piyasa yapısını değerlendir.

ÇIKTI FORMATI (kesin uy):
1-3 cümle genel özet (pozisyon durumu, genel risk, dikkat çekici noktalar).
Son satır, TEK satır JSON:
DURUM_ANALIZI: {{"genel_oneri":"...","pozisyonlar":[{{"sembol":"BTCUSDT","karar":"DEVAM","gerekce":"tek cümle","acil":false}}]}}

Karar seçenekleri (kesinlikle sadece bunlar):
- DEVAM: pozisyon planlandığı gibi ilerliyor, bekle
- BEKLE: belirsizlik var, şimdilik tut ama izle
- KAR_AL: hedefe yakın veya güçlü direnç, kâr al
- ZARARI_KES: yapı bozuldu veya stop çok yakın, kapat
- STOP_GUNCELLE: stop güvenli değil veya trailing gerekiyor

"acil":true sadece ÇOK güçlü ve acil gerekçeyle (yapı tamamen bozuldu, büyük fakeout).
Belirsizse acil=false, karar=BEKLE. Çoğu durumda "acil" false olmalı."""

PROTECT_SYSTEM = f"""{PERSONA}

Görev: Kullanıcının AÇIK pozisyonu için zarar-kes ve kâr-al seviyesi belirle.
Mum verilerine, giriş fiyatına ve bakiyeye göre karar ver. 2-3 cümle gerekçe yaz.

Yanıtının EN SON satırı tek satır JSON:
KORUMA: {{"zarar_kes":4010.0,"kar_al":4180.0,"gerekce":"tek cümle"}}

{SLTP_RULES}"""


@dataclass
class Suggestion:
    islem: str  # AL | SAT | BEKLE
    sembol: str
    tutar_usdt: float
    basari_yuzdesi: int
    gerekce: str
    zarar_kes: float = 0.0
    kar_al: float = 0.0


@dataclass
class Protection:
    zarar_kes: float
    kar_al: float
    gerekce: str


@dataclass
class PositionDecision:
    sembol: str
    karar: str  # DEVAM | BEKLE | KAR_AL | ZARARI_KES | STOP_GUNCELLE
    gerekce: str
    acil: bool = False


@dataclass
class StatusAnalysis:
    genel_oneri: str
    pozisyonlar: list[PositionDecision]


def _to_suggestion(d: dict) -> Suggestion | None:
    try:
        s = Suggestion(
            islem=str(d.get("islem", "BEKLE")).upper(),
            sembol=str(d.get("sembol", "")).upper(),
            tutar_usdt=float(d.get("tutar_usdt", 0) or 0),
            basari_yuzdesi=int(d.get("basari_yuzdesi", 0) or 0),
            gerekce=str(d.get("gerekce", "")),
            zarar_kes=float(d.get("zarar_kes", 0) or 0),
            kar_al=float(d.get("kar_al", 0) or 0),
        )
        return s if s.islem in ("AL", "SAT", "BEKLE") else None
    except (ValueError, TypeError):
        return None


def parse_suggestions(text: str) -> list[Suggestion]:
    """ONERILER: [...] (tara) veya ONERI: {...} (tek analiz) satırını ayıkla."""
    m = re.search(r"ONERILER:\s*(\[.*?\])", text, re.DOTALL)
    if m:
        try:
            items = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []
        out = [s for d in items if (s := _to_suggestion(d))]
        return [s for s in out if s.islem in ("AL", "SAT")]
    m = re.search(r"ONERI:\s*(\{.*?\})", text, re.DOTALL)
    if m:
        try:
            s = _to_suggestion(json.loads(m.group(1)))
        except json.JSONDecodeError:
            return []
        return [s] if s and s.islem in ("AL", "SAT") else []
    return []


def parse_protection(text: str) -> Protection | None:
    m = re.search(r"KORUMA:\s*(\{.*?\})", text, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
        return Protection(
            zarar_kes=float(d.get("zarar_kes", 0) or 0),
            kar_al=float(d.get("kar_al", 0) or 0),
            gerekce=str(d.get("gerekce", "")),
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def parse_status_analysis(text: str) -> StatusAnalysis | None:
    """DURUM_ANALIZI: {...} satırını ayrıştır (iç içe JSON için greedy)."""
    m = re.search(r"DURUM_ANALIZI:\s*(\{.*\})", text, re.DOTALL)
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
        valid_kararlar = {"DEVAM", "BEKLE", "KAR_AL", "ZARARI_KES", "STOP_GUNCELLE"}
        pozisyonlar = []
        for p in d.get("pozisyonlar", []):
            karar = str(p.get("karar", "BEKLE")).upper()
            if karar not in valid_kararlar:
                karar = "BEKLE"
            pozisyonlar.append(PositionDecision(
                sembol=str(p.get("sembol", "")),
                karar=karar,
                gerekce=str(p.get("gerekce", "")),
                acil=bool(p.get("acil", False)),
            ))
        return StatusAnalysis(
            genel_oneri=str(d.get("genel_oneri", "")),
            pozisyonlar=pozisyonlar,
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def strip_machine_lines(text: str) -> str:
    """Kullanıcıya gösterilecek metinden ham JSON satırlarını çıkar."""
    text = re.sub(r"ONERILER:\s*\[.*?\]", "", text, flags=re.DOTALL)
    text = re.sub(r"ONERI:\s*\{.*?\}", "", text, flags=re.DOTALL)
    text = re.sub(r"KORUMA:\s*\{.*?\}", "", text, flags=re.DOTALL)
    text = re.sub(r"DURUM_ANALIZI:\s*\{.*?\}", "", text, flags=re.DOTALL)
    return text.strip()


async def _ask(prompt: str, system: str) -> str:
    options = ClaudeAgentOptions(
        system_prompt=system,
        max_turns=1,
        allowed_tools=[],
        model=config.current().model_id,
    )
    full = ""
    async for message in query(prompt=prompt, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    full += block.text
    return full


def _compact_klines(klines: list[dict]) -> list[list[float]]:
    return [[k["o"], k["h"], k["l"], k["c"]] for k in klines]


def _portfolio_ctx(cash: float, positions: dict) -> dict:
    mode = modes.get(config.current().mode)
    return {
        "nakit_usdt": round(cash, 2),
        "pozisyonlar": positions,
        "max_toplam_oneri_usdt": round(cash * mode.total_ratio, 2),
        "max_tek_islem_usdt": round(cash * mode.single_hi / 100, 2),
    }


async def scan_market_filtered(
    watchlist: list[str],
    cash: float,
    positions: dict,
    category: str | None = None,
) -> str:
    """Kategori filtreli piyasa taraması. Sadece AL önerileri çıkarır.

    category: None=tüm, 'kripto', 'global', 'forex', 'emtia', 'endeks'
    """
    if category == "kripto":
        movers = await market.fetch_top_movers(12)
        payload = {
            "gorev": "Kripto piyasasını tara, en iyi 2-4 AL fırsatını bul.",
            "kripto_en_hareketli": movers,
            "watchlist": watchlist,
            "portfoy": _portfolio_ctx(cash, positions),
        }
        system = _scan_system("sadece kripto")

    elif category in ("emtia", "forex", "endeks", "global"):
        instruments = market.instruments_for_category(category)
        snapshot = await market.fetch_yahoo_snapshot(instruments)
        cat_labels = {
            "emtia": "emtia (altın, gümüş, petrol, doğalgaz, bakır)",
            "forex": "forex (EUR/USD, GBP/USD, USD/JPY, USD/TRY)",
            "endeks": "endeksler (S&P 500, NASDAQ, DOW, DAX, BIST)",
            "global": "global (tüm emtia/forex/endeks)",
        }
        payload = {
            "gorev": f"{cat_labels[category]} piyasasını tara, en iyi 2-4 AL fırsatını bul.",
            "piyasa": snapshot,
            "portfoy": _portfolio_ctx(cash, positions),
        }
        system = _scan_system(cat_labels[category])

    else:  # None = tüm piyasa
        movers, snapshot = await asyncio.gather(
            market.fetch_top_movers(12),
            market.fetch_yahoo_snapshot(),
        )
        payload = {
            "gorev": "Tüm piyasayı tara (kripto + emtia/forex/endeks), en iyi 2-4 AL fırsatını bul.",
            "kripto_en_hareketli": movers,
            "emtia_forex_endeks": snapshot,
            "watchlist": watchlist,
            "portfoy": _portfolio_ctx(cash, positions),
        }
        system = _scan_system()

    prompt = f"Piyasa taraması yap:\n{json.dumps(payload, separators=(',', ':'))}"
    return await _ask(prompt, system)


async def analyze_symbol(symbol: str, cash: float, positions: dict) -> str:
    """Tek sembol analizi: kısa + uzun vade mumlar ve portföy bağlamı."""
    k_short, k_long = await asyncio.gather(
        market.fetch_klines(symbol, "1h", 48),
        market.fetch_klines(symbol, "4h", 42),
    )
    payload = {
        "sembol": symbol,
        "guncel_fiyat": k_short[-1]["c"],
        "mumlar_saatlik_OHLC": _compact_klines(k_short),
        "mumlar_uzunvade_OHLC": _compact_klines(k_long),
        "portfoy": _portfolio_ctx(cash, positions),
    }
    prompt = f"Şu enstrümanı analiz et:\n{json.dumps(payload, separators=(',', ':'))}"
    return await _ask(prompt, _analyze_system())


async def analyze_positions(positions_data: list[dict], cash: float) -> str:
    """Açık pozisyonlar için kapsamlı analiz (/durum ve otonom mod için)."""
    payload = {
        "nakit_usdt": round(cash, 2),
        "pozisyon_sayisi": len(positions_data),
        "pozisyonlar": positions_data,
    }
    prompt = f"Açık pozisyonları analiz et:\n{json.dumps(payload, separators=(',', ':'))}"
    return await _ask(prompt, STATUS_SYSTEM)


async def protect_position(symbol: str, entry: float, qty: float,
                            cash: float) -> str:
    """Açık pozisyon için Claude'dan zarar-kes / kâr-al seviyesi iste."""
    k_short, k_long = await asyncio.gather(
        market.fetch_klines(symbol, "1h", 48),
        market.fetch_klines(symbol, "4h", 42),
    )
    payload = {
        "sembol": symbol,
        "guncel_fiyat": k_short[-1]["c"],
        "pozisyon": {"giris_fiyati": entry, "miktar": qty,
                     "deger_usdt": round(qty * k_short[-1]["c"], 2)},
        "nakit_usdt": round(cash, 2),
        "mumlar_saatlik_OHLC": _compact_klines(k_short),
        "mumlar_uzunvade_OHLC": _compact_klines(k_long),
    }
    prompt = f"Bu pozisyon için koruma seviyeleri belirle:\n{json.dumps(payload, separators=(',', ':'))}"
    return await _ask(prompt, PROTECT_SYSTEM)
