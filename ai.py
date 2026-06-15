"""AI analiz katmanı — Claude, OpenAI, Gemini, Ollama veya Grok destekli.

Sağlayıcılar:
- claude:  claude-agent-sdk (Claude Code aboneliği, ayrı key gerekmez)
- openai:  OpenAI API (gpt-4o, o3-mini vb.) — openai_api_key gerekli
- gemini:  Google Gemini API (gemini-2.0-flash vb.) — gemini_api_key gerekli
- ollama:  Yerel Ollama (llama3.2, mistral vb.) — Ollama kurulu + ollama serve
- grok:    xAI Grok API (grok-3-mini vb.) — grok_api_key gerekli
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
ÖNEMLİ: Yanıtları YALNIZCA Türkçe ver. Belirtilen JSON formatına kesinlikle uy."""

SLTP_RULES = """\
ZARAR-KES / KÂR-AL KURALLARI (her AL önerisi için zorunlu):
- "zarar_kes": yapısal desteğin ALTINA koy, girişten en fazla %2-8 uzakta (volatiliteye göre).
  Stop avından korunmak için tam yuvarlak sayılara ve bariz seviyenin 1-2 tık dibine koyma.
- "kar_al": gerçekçi bir direnç/hedef. Risk/ödül oranı EN AZ 1.5 olsun
  (hedefin uzaklığı, stopun uzaklığının en az 1.5 katı).
- Bakiye küçüldüyse stoplar daha sıkı olsun; sermaye korunması her şeyden önce gelir."""


def _risk_rules() -> str:
    return modes.risk_rules(modes.get(config.current().mode))


def _leverage_section(max_leverage: int = 5) -> str:
    """Tarama promptuna eklenen kaldıraç bölümü."""
    return f"""
KALDIRAÇLI PAPER İŞLEM SEÇENEĞİ (sadece ÇOK güçlü setup'ta kullan):
- confidence >= 70, risk_reward >= 2.0, setup_quality "A" veya "A-" olduğunda LEVERAGE_AL öner
- Maksimum {max_leverage}x kaldıraç
- stop_loss ve take_profit ZORUNLU — sıfır veya boş olamaz
- liquidation_price = giriş × (1 − 1/kaldıraç + 0.005) formülüyle hesapla
- liquidation_price stop_loss'tan DÜŞÜK olmalı (stop önce tetiklenmelidir)
- Manipülasyon, pump, düşük likidite → LEVERAGE_AL önerme
- Short kaldıraç önerme
- Şüphen varsa SPOT_AL veya BEKLE kullan

LEVERAGE_AL JSON örneği:
{{"islem":"LEVERAGE_AL","sembol":"BTCUSDT","tutar_usdt":250,"leverage":2,
  "notional_usdt":500,"basari_yuzdesi":74,"zarar_kes":61800,"kar_al":64900,
  "liquidation_price":58200,"setup_quality":"A-","risk_reward":2.4,
  "gerekce":"trend kırılımı + hacim teyidi + düşük manipülasyon riski"}}
"""


def _plan_rules(trade_plan: str, leverage_enabled: bool, max_leverage: int) -> str:
    """Trade planına göre Claude'a izin verilen işlem tipleri."""
    lev_section = _leverage_section(max_leverage) if (leverage_enabled and trade_plan == "tam") else ""
    if trade_plan == "sadece_long":
        return (
            "İŞLEM KISITLARI: SADECE AL veya SPOT_AL öner. "
            "SHORT_AL, SCALP_AL, LEVERAGE_AL KESİNLİKLE YASAK.\n"
        )
    elif trade_plan == "dengeli":
        return (
            "İŞLEM KISITLARI:\n"
            "- Piyasa koşuluna göre AL/SPOT_AL, SHORT_AL veya SCALP_AL önerebilirsin.\n"
            "- LEVERAGE_AL YASAK.\n"
            "- SHORT_AL: SADECE güçlü düşüş trendi + yüksek likidite kripto (BTC/ETH/SOL). "
            "  zarar_kes giriş fiyatının ÜSTÜNDE, kar_al ALTINDA olmalı.\n"
            "- SCALP_AL: SADECE yüksek hacim + momentum, BTC/ETH/SOL/BNB, max 30dk hedef. "
            "  stop %0.3-%1, hedef %0.5-%2.\n"
            "- Her piyasa koşulunu dürüstçe değerlendir: "
            "  yükselişte AL, düşüşte SHORT_AL, yatayda BEKLE. Taraflı olma.\n"
        ) + lev_section
    elif trade_plan == "tam":
        return (
            "İŞLEM KISITLARI:\n"
            "- Piyasa koşuluna göre AL/SPOT_AL, SHORT_AL veya SCALP_AL önerebilirsin.\n"
            "- SHORT_AL: yüksek likidite kripto, zarar_kes > giriş, kar_al < giriş.\n"
            "- SCALP_AL: BTC/ETH/SOL/BNB, max 30dk, stop %0.3-%1.\n"
            "- Her piyasa koşulunu dürüstçe değerlendir: "
            "  yükselişte AL, düşüşte SHORT_AL, yatayda BEKLE.\n"
        ) + lev_section
    return "İŞLEM KISITLARI: SADECE AL veya SPOT_AL öner.\n"


def _scan_system(
    category_label: str = "",
    leverage_enabled: bool = False,
    max_leverage: int = 5,
    trade_plan: str = "dengeli",
) -> str:
    cat_note = f" ({category_label})" if category_label else ""
    plan_rules = _plan_rules(trade_plan, leverage_enabled, max_leverage)

    # JSON örneği plan'a göre seç
    if trade_plan == "sadece_long":
        json_example = '{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,"basari_yuzdesi":65,"zarar_kes":60000,"kar_al":65000,"gerekce":"kısa açıklama"}'
    else:
        json_example = (
            '{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,"basari_yuzdesi":65,'
            '"zarar_kes":60000,"kar_al":65000,"direction":"long","trade_style":"swing","gerekce":"..."} '
            'veya {"islem":"SHORT_AL","sembol":"ETHUSDT","tutar_usdt":400,"basari_yuzdesi":62,'
            '"zarar_kes":3500,"kar_al":3100,"direction":"short","trade_style":"day","gerekce":"..."}'
        )

    return f"""{PERSONA}

Sana{cat_note} piyasa verisi ve portföy durumu verilecek.

ÇIKTI FORMATI (kesin uy, uzun analiz YAZMA):
1. En fazla 2-3 cümlelik genel piyasa özeti.
2. Son satır, tek satır JSON:
ONERILER: [{json_example}]

{plan_rules}
GENEL KISITLAR:
- SAT komutu YASAK (pozisyon yönetimi /durum ile yapılır).
- Zaten açık olan sembolde YENİ öneri yapma.
- 2 ila 4 aday. "sembol" alanında SANA VERİLEN kodu aynen kullan (BTCUSDT, GC=F, ...).
- Fırsat yoksa BEKLE döndür, zorla öneri yapma.
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
DURUM_ANALIZI: {{"genel_oneri":"...","pozisyonlar":[{{"sembol":"BTCUSDT","karar":"DEVAM","gerekce":"tek cümle","acil":false,"new_stop_loss":0,"new_take_profit":0,"close_reason":""}}]}}

Karar seçenekleri (kesinlikle sadece bunlar):
- DEVAM: pozisyon planlandığı gibi ilerliyor → new_stop_loss=0, new_take_profit=0, close_reason=""
- BEKLE: belirsizlik var, şimdilik izle → new_stop_loss=0, new_take_profit=0, close_reason=""
- KAR_AL: hedefe yakın veya güçlü direnç, kâr al → close_reason doldur, new_stop_loss=0
- ZARARI_KES: yapı bozuldu veya stop çok yakın, kapat → close_reason doldur, new_stop_loss=0
- STOP_GUNCELLE: stop trailing gerekiyor veya güvensiz → new_stop_loss doldur (anlık fiyatın ALTINDA, mevcut stoptan daha iyi)
- KORU: stop/hedef eksik, ekle → new_stop_loss ve/veya new_take_profit doldur

ALAN KURALLARI:
- new_stop_loss: STOP_GUNCELLE ve KORU için. Anlık fiyatın ALTINDA olmalı. Long pozisyonda mevcut stoptan daha kötüye çekme.
- new_take_profit: KORU ve hedef güncellemesi için. Anlık fiyatın ÜSTÜNDE olmalı.
- close_reason: KAR_AL ve ZARARI_KES için tek cümlelik kapatma gerekçesi; diğerleri için boş.
- "acil":true sadece ÇOK güçlü ve acil gerekçeyle. Belirsizse acil=false, karar=BEKLE."""

PROTECT_SYSTEM = f"""{PERSONA}

Görev: Kullanıcının AÇIK pozisyonu için zarar-kes ve kâr-al seviyesi belirle.
Mum verilerine, giriş fiyatına ve bakiyeye göre karar ver. 2-3 cümle gerekçe yaz.

Yanıtının EN SON satırı tek satır JSON:
KORUMA: {{"zarar_kes":4010.0,"kar_al":4180.0,"gerekce":"tek cümle"}}

{SLTP_RULES}"""


@dataclass
class Suggestion:
    islem: str  # AL | SPOT_AL | LEVERAGE_AL | SHORT_AL | SCALP_AL | BEKLE
    sembol: str
    tutar_usdt: float
    basari_yuzdesi: int
    gerekce: str
    zarar_kes: float = 0.0
    kar_al: float = 0.0
    # Kaldıraç alanları (LEVERAGE_AL için)
    leverage: int = 1
    notional_usdt: float = 0.0
    liquidation_price: float = 0.0
    setup_quality: str = ""
    risk_reward: float = 0.0
    # Yön ve stil alanları
    direction: str = "long"         # "long" | "short"
    trade_style: str = "swing"      # "scalp" | "day" | "swing"
    expected_duration: str = ""     # "30m" | "4h" | "1-3d" vb.
    invalidation: str = ""          # pozisyon geçersiz sayılma koşulu


@dataclass
class Protection:
    zarar_kes: float
    kar_al: float
    gerekce: str


@dataclass
class PositionDecision:
    sembol: str
    karar: str  # DEVAM | BEKLE | KAR_AL | ZARARI_KES | STOP_GUNCELLE | KORU
    gerekce: str
    acil: bool = False
    new_stop_loss: float = 0.0   # STOP_GUNCELLE / KORU için yeni stop fiyatı
    new_take_profit: float = 0.0 # KORU / hedef güncellemesi için yeni hedef
    close_reason: str = ""       # KAR_AL / ZARARI_KES için kapatma gerekçesi


@dataclass
class StatusAnalysis:
    genel_oneri: str
    pozisyonlar: list[PositionDecision]


_VALID_ISLEM = {"AL", "SAT", "BEKLE", "SPOT_AL", "LEVERAGE_AL",
                "SHORT_AL", "SCALP_AL", "SCALP_SHORT"}


def _to_suggestion(d: dict) -> Suggestion | None:
    try:
        islem = str(d.get("islem", "BEKLE")).upper()
        if islem not in _VALID_ISLEM:
            return None
        s = Suggestion(
            islem=islem,
            sembol=str(d.get("sembol", "")).upper(),
            tutar_usdt=float(d.get("tutar_usdt", 0) or 0),
            basari_yuzdesi=int(d.get("basari_yuzdesi", 0) or 0),
            gerekce=str(d.get("gerekce", "")),
            zarar_kes=float(d.get("zarar_kes", 0) or 0),
            kar_al=float(d.get("kar_al", 0) or 0),
            leverage=int(d.get("leverage", 1) or 1),
            notional_usdt=float(d.get("notional_usdt", 0) or 0),
            liquidation_price=float(d.get("liquidation_price", 0) or 0),
            setup_quality=str(d.get("setup_quality", "") or ""),
            risk_reward=float(d.get("risk_reward", 0) or 0),
            direction=str(d.get("direction", "long") or "long").lower(),
            trade_style=str(d.get("trade_style", "swing") or "swing").lower(),
            expected_duration=str(d.get("expected_duration", "") or ""),
            invalidation=str(d.get("invalidation", "") or ""),
        )
        return s
    except (ValueError, TypeError):
        return None


_ACTIONABLE_ISLEM = {"AL", "SAT", "SPOT_AL", "LEVERAGE_AL", "SHORT_AL", "SCALP_AL", "SCALP_SHORT"}


def parse_suggestions(text: str) -> list[Suggestion]:
    """ONERILER: [...] (tara) veya ONERI: {...} (tek analiz) satırını ayıkla."""
    m = re.search(r"ONERILER:\s*(\[.*?\])", text, re.DOTALL)
    if m:
        try:
            items = json.loads(m.group(1))
        except json.JSONDecodeError:
            return []
        out = [s for d in items if (s := _to_suggestion(d))]
        return [s for s in out if s.islem in _ACTIONABLE_ISLEM]
    m = re.search(r"ONERI:\s*(\{.*?\})", text, re.DOTALL)
    if m:
        try:
            s = _to_suggestion(json.loads(m.group(1)))
        except json.JSONDecodeError:
            return []
        return [s] if s and s.islem in _ACTIONABLE_ISLEM else []
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
    """DURUM_ANALIZI: {...} satırını ayrıştır — brace sayımıyla iç içe JSON desteklenir."""
    idx = text.find("DURUM_ANALIZI:")
    if idx == -1:
        return None
    brace = text.find("{", idx)
    if brace == -1:
        return None
    try:
        d, _ = json.JSONDecoder().raw_decode(text, brace)
    except (json.JSONDecodeError, ValueError):
        return None
    try:
        valid_kararlar = {"DEVAM", "BEKLE", "KAR_AL", "ZARARI_KES", "STOP_GUNCELLE", "KORU"}
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
                new_stop_loss=float(p.get("new_stop_loss", 0) or 0),
                new_take_profit=float(p.get("new_take_profit", 0) or 0),
                close_reason=str(p.get("close_reason", "") or ""),
            ))
        return StatusAnalysis(
            genel_oneri=str(d.get("genel_oneri", "")),
            pozisyonlar=pozisyonlar,
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        return None


def _strip_json_object(text: str, prefix: str) -> str:
    """prefix: {...} bloğunu brace sayımıyla metinden kaldır (iç içe JSON destekli)."""
    result = text
    while True:
        idx = result.find(prefix + ":")
        if idx == -1:
            break
        brace = result.find("{", idx)
        if brace == -1:
            break
        depth, end = 0, brace
        for i, ch in enumerate(result[brace:], brace):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        result = result[:idx] + result[end + 1:]
    return result


def strip_machine_lines(text: str) -> str:
    """Kullanıcıya gösterilecek metinden ham JSON satırlarını çıkar."""
    text = re.sub(r"ONERILER:\s*\[.*?\]", "", text, flags=re.DOTALL)
    text = re.sub(r"ONERI:\s*\{.*?\}", "", text, flags=re.DOTALL)
    text = _strip_json_object(text, "KORUMA")
    text = _strip_json_object(text, "DURUM_ANALIZI")
    return text.strip()


async def _ask_claude(prompt: str, system: str) -> str:
    """Claude Agent SDK üzerinden analiz (Claude Code aboneliği kullanır)."""
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


async def _ask_openai(prompt: str, system: str) -> str:
    """OpenAI API (GPT-4o vb.) üzerinden analiz."""
    try:
        import openai as _openai
    except ImportError:
        raise RuntimeError("openai paketi yok: pip install openai")
    cfg = config.current()
    key = getattr(cfg, "openai_api_key", "")
    if not key:
        raise RuntimeError("OpenAI API key eksik. /model key openai YOUR_KEY ile ayarla.")
    model = getattr(cfg, "openai_model", "gpt-4o")
    client = _openai.AsyncOpenAI(api_key=key)
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=2048,
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""


async def _ask_gemini(prompt: str, system: str) -> str:
    """Google Gemini API üzerinden analiz."""
    try:
        import google.generativeai as genai
    except ImportError:
        raise RuntimeError("google-generativeai paketi yok: pip install google-generativeai")
    cfg = config.current()
    key = getattr(cfg, "gemini_api_key", "")
    if not key:
        raise RuntimeError("Gemini API key eksik. /model key gemini YOUR_KEY ile ayarla.")
    model_name = getattr(cfg, "gemini_model", "gemini-2.0-flash")
    genai.configure(api_key=key)
    model = genai.GenerativeModel(
        model_name,
        system_instruction=system,
        generation_config={"temperature": 0.3, "max_output_tokens": 2048},
    )
    resp = await model.generate_content_async(prompt)
    return resp.text


async def _ask_ollama(prompt: str, system: str) -> str:
    """Yerel Ollama sunucusu üzerinden analiz (API key gerekmez)."""
    import httpx
    cfg = config.current()
    model_name = getattr(cfg, "ollama_model", "llama3.2")
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.3},
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        try:
            resp = await client.post("http://localhost:11434/api/chat", json=payload)
            resp.raise_for_status()
            return resp.json().get("message", {}).get("content", "")
        except httpx.ConnectError:
            raise RuntimeError(
                "Ollama bağlantısı yok. Terminal'de 'ollama serve' çalıştır, "
                f"sonra 'ollama pull {model_name}' ile modeli indir."
            )
        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Ollama hata {e.response.status_code}: {e.response.text[:200]}")


async def _ask_grok(prompt: str, system: str) -> str:
    """xAI Grok API üzerinden analiz (OpenAI uyumlu)."""
    try:
        import openai as _openai
    except ImportError:
        raise RuntimeError("openai paketi yok: pip install openai")
    cfg = config.current()
    key = getattr(cfg, "grok_api_key", "")
    if not key:
        raise RuntimeError("Grok API key eksik. /model key grok YOUR_KEY ile ayarla.")
    model = getattr(cfg, "grok_model", "grok-3-mini")
    client = _openai.AsyncOpenAI(api_key=key, base_url="https://api.x.ai/v1")
    resp = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        max_tokens=2048,
        temperature=0.3,
    )
    return resp.choices[0].message.content or ""


def _friendly_error(provider: str, exc: Exception) -> RuntimeError:
    """Teknik hata mesajlarını kullanıcı dostu Türkçe'ye çevirir."""
    msg = str(exc)
    lmsg = msg.lower()
    if "authentication" in lmsg or "api key" in lmsg or "invalid_api_key" in lmsg or "401" in lmsg:
        tips = {
            "openai": "/model key openai YOUR_KEY",
            "gemini": "/model key gemini YOUR_KEY",
            "grok": "/model key grok YOUR_KEY",
            "claude": "Claude Code aboneliğinin aktif olduğundan emin ol",
        }
        tip = tips.get(provider, "API key'ini kontrol et")
        return RuntimeError(f"[{provider.upper()}] Kimlik doğrulama hatası — {tip}")
    if "rate" in lmsg or "429" in lmsg or "quota" in lmsg:
        return RuntimeError(
            f"[{provider.upper()}] İstek limiti aşıldı — bir dakika bekle, sonra tekrar dene"
        )
    if "model" in lmsg and ("not found" in lmsg or "does not exist" in lmsg or "404" in lmsg):
        return RuntimeError(
            f"[{provider.upper()}] Model bulunamadı — /model komutuyla geçerli bir model seç"
        )
    if "connection" in lmsg or "connect" in lmsg or "timeout" in lmsg:
        return RuntimeError(
            f"[{provider.upper()}] Bağlantı hatası — internet bağlantını ve servis durumunu kontrol et"
        )
    if "insufficient" in lmsg or "balance" in lmsg or "credit" in lmsg:
        return RuntimeError(
            f"[{provider.upper()}] Yetersiz kredi — hesabına kredi yükle"
        )
    # fallback: ilk 120 karakteri göster
    return RuntimeError(f"[{provider.upper()}] {msg[:120]}")


async def _ask(prompt: str, system: str) -> str:
    """Aktif AI sağlayıcısına göre analiz yap."""
    provider = getattr(config.current(), "ai_provider", "claude")
    try:
        if provider == "openai":
            return await _ask_openai(prompt, system)
        elif provider == "gemini":
            return await _ask_gemini(prompt, system)
        elif provider == "ollama":
            return await _ask_ollama(prompt, system)
        elif provider == "grok":
            return await _ask_grok(prompt, system)
        return await _ask_claude(prompt, system)
    except RuntimeError:
        raise  # zaten biçimlendirilmiş hata
    except Exception as exc:
        raise _friendly_error(provider, exc) from exc


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
    leverage_enabled: bool = False,
    max_leverage: int = 5,
    trade_plan: str = "dengeli",
) -> str:
    """Kategori filtreli piyasa taraması.

    category: None=tüm, 'kripto', 'global', 'forex', 'emtia', 'endeks'
    trade_plan: 'sadece_long' | 'dengeli' | 'tam'
    """
    _plan = trade_plan or "dengeli"
    if category == "kripto":
        movers = await market.fetch_top_movers(12)
        gorev = "Kripto piyasasını tara. Plan kurallarına göre en iyi 2-4 fırsat bul."
        payload = {
            "gorev": gorev,
            "kripto_en_hareketli": movers,
            "watchlist": watchlist,
            "portfoy": _portfolio_ctx(cash, positions),
        }
        system = _scan_system("sadece kripto", leverage_enabled, max_leverage, _plan)

    elif category in ("emtia", "forex", "endeks", "global"):
        instruments = market.instruments_for_category(category)
        snapshot = await market.fetch_yahoo_snapshot(instruments)
        cat_labels = {
            "emtia": "emtia (altın, gümüş, petrol, doğalgaz, bakır)",
            "forex": "forex (EUR/USD, GBP/USD, USD/JPY, USD/TRY)",
            "endeks": "endeksler (S&P 500, NASDAQ, DOW, DAX, BIST)",
            "global": "global (tüm emtia/forex/endeks)",
        }
        gorev = f"{cat_labels[category]} piyasasını tara. Plan kurallarına göre en iyi 2-4 fırsat bul."
        payload = {
            "gorev": gorev,
            "piyasa": snapshot,
            "portfoy": _portfolio_ctx(cash, positions),
        }
        system = _scan_system(cat_labels[category], leverage_enabled, max_leverage, _plan)

    else:  # None = tüm piyasa
        movers, snapshot = await asyncio.gather(
            market.fetch_top_movers(12),
            market.fetch_yahoo_snapshot(),
        )
        gorev = (
            "Tüm piyasayı tara (kripto + emtia/forex/endeks). "
            "Plan kurallarına göre en iyi 2-4 fırsat bul. "
            "Her enstrümanı hem yükseliş hem düşüş açısından değerlendir."
        )
        payload = {
            "gorev": gorev,
            "kripto_en_hareketli": movers,
            "emtia_forex_endeks": snapshot,
            "watchlist": watchlist,
            "portfoy": _portfolio_ctx(cash, positions),
        }
        system = _scan_system("", leverage_enabled, max_leverage, _plan)

    prompt = f"Piyasa taraması yap:\n{json.dumps(payload, separators=(',', ':'))}"
    return await _ask(prompt, system)


async def scan_leverage_market(
    watchlist: list[str],
    cash: float,
    positions: dict,
    max_leverage: int = 5,
) -> str:
    """Sadece kaldıraçlı fırsatları ara (/tara kaldirac için).

    Watchlist'in leverage_allowed sembollerini alır (çağıran tarafından
    zaten filtrelenmiş olmalı); payload'a veri kalite bilgisini ekler.
    """
    movers = await market.fetch_top_movers(12)
    # Watchlist'teki her sembol için veri kalitesini bildir
    watchlist_with_quality = [
        {
            "sembol": s,
            "veri_kalitesi": market.data_quality(s),
            "kaldirac_izinli": market.leverage_allowed(s),
        }
        for s in watchlist
    ]
    payload = {
        "gorev": (
            "Sadece kaldıraç izinli (kaldirac_izinli=true) ve veri kalitesi "
            "'realtime' olan sembolleri değerlendir. "
            "SADECE çok güçlü kaldıraçlı paper trade fırsatı varsa LEVERAGE_AL öner. "
            "Yoksa BEKLE döndür. "
            "confidence < 70, R/R < 2.0, setup_quality A/A- değilse LEVERAGE_AL önerme."
        ),
        "kripto_en_hareketli": movers,
        "watchlist": watchlist_with_quality,
        "portfoy": _portfolio_ctx(cash, positions),
    }
    system = _scan_system("kaldıraç taraması", leverage_enabled=True, max_leverage=max_leverage)
    prompt = f"Kaldıraçlı paper fırsat taraması:\n{json.dumps(payload, separators=(',', ':'))}"
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


async def scan_directional(
    watchlist: list[str],
    cash: float,
    positions: dict,
    direction: str = "long",
) -> str:
    """Yönsel/stilsel tarama — long/short/scalp/day/swing."""
    movers = await market.fetch_top_movers(12)

    direction_instruction = {
        "long": "Sadece LONG/YÜKSELİŞ fırsatları ara. AL veya SPOT_AL öner.",
        "yukselis": "Sadece LONG/YÜKSELİŞ fırsatları ara. AL veya SPOT_AL öner.",
        "short": (
            "Sadece SHORT/DÜŞÜŞ fırsatları ara. islem='SHORT_AL' olacak. "
            "watchlist'teki kripto semboller arasından düşüş sinyali verenleri seç. "
            "Stop fiyatı (zarar_kes) giriş fiyatının ÜSTÜNDE olmalı. "
            "Hedef fiyatı (kar_al) giriş fiyatının ALTINDA olmalı. "
            "En az 1, en fazla 3 SHORT önerisi ver."
        ),
        "scalp": (
            "Sadece SCALP (hızlı işlem, max 30dk) fırsatları ara. islem='SCALP_AL' olacak. "
            "watchlist'teki yüksek likidite Binance kripto sembollerinden seç (BTC/ETH/SOL/BNB öncelikli). "
            "Küçük hedef/stop (%0.3-%1). Yüksek momentum ve hacim teyidi şart. "
            "Komisyon: %0.1 açılış + %0.1 kapanış. En az 1, en fazla 2 SCALP önerisi ver."
        ),
        "hizli": "Sadece SCALP fırsatları ara. SCALP_AL öner.",
        "day": "Gün içi işlem (day trade) fırsatları ara. 15m/1h yapısına göre.",
        "swing": "Swing trade fırsatları ara. 4h/1d mantığıyla. AL veya SPOT_AL öner.",
    }.get(direction, "Genel piyasa taraması yap.")

    direction_json_example = {
        "long": '{"islem":"AL","sembol":"BTCUSDT","direction":"long","trade_style":"swing","tutar_usdt":500,"basari_yuzdesi":65,"zarar_kes":60000,"kar_al":65000,"gerekce":"kisa aciklama"}',
        "short": '{"islem":"SHORT_AL","sembol":"BTCUSDT","direction":"short","trade_style":"day","zarar_kes":65000,"kar_al":60000,"tutar_usdt":500,"basari_yuzdesi":60,"gerekce":"kisa aciklama"}',
        "scalp": '{"islem":"SCALP_AL","sembol":"BTCUSDT","direction":"long","trade_style":"scalp","expected_duration":"15m","zarar_kes":62000,"kar_al":63000,"tutar_usdt":300,"basari_yuzdesi":58,"gerekce":"kisa aciklama"}',
    }.get(direction, '{"islem":"AL","sembol":"BTCUSDT","direction":"long","trade_style":"swing","tutar_usdt":500,"basari_yuzdesi":65,"zarar_kes":60000,"kar_al":65000,"gerekce":"kisa aciklama"}')

    payload = {
        "gorev": direction_instruction,
        "kripto_en_hareketli": movers,
        "watchlist": watchlist,
        "portfoy": _portfolio_ctx(cash, positions),
    }
    system = f"""{PERSONA}

Sana piyasa verisi verilecek. {direction_instruction}

ÇIKTI FORMATI:
1. En fazla 2-3 cümle piyasa özeti.
2. Son satır JSON:
ONERILER: [{direction_json_example}]

Ekstra alanlar (zorunlu):
- "direction": "long" veya "short"
- "trade_style": "scalp" veya "day" veya "swing"
- "expected_duration": beklenen süre ("15m", "2h", "1-2d" vb.)
- "invalidation": pozisyonun geçersiz sayılacağı koşul
- "zarar_kes" ve "kar_al": ZORUNLU, sıfır olamaz

SHORT için: zarar_kes > giriş fiyatı, kar_al < giriş fiyatı
SCALP için: stop %0.3-%1, hedef %0.5-%2, sadece BTC/ETH/SOL/BNB

{SLTP_RULES}
{_risk_rules()}"""
    prompt = f"Yönsel tarama ({direction}):\n{json.dumps(payload, separators=(',', ':'))}"
    return await _ask(prompt, system)


async def protect_position(symbol: str, entry: float, qty: float,
                            cash: float, direction: str = "long") -> str:
    """Açık pozisyon için Claude'dan zarar-kes / kâr-al seviyesi iste."""
    k_short, k_long = await asyncio.gather(
        market.fetch_klines(symbol, "1h", 48),
        market.fetch_klines(symbol, "4h", 42),
    )
    dir_note = (
        "BU POZİSYON SHORT (satış yönlü): zarar_kes giriş fiyatının ÜSTÜNDE, "
        "kar_al giriş fiyatının ALTINDA olmalı."
        if direction == "short" else
        "BU POZİSYON LONG (alış yönlü): zarar_kes giriş fiyatının ALTINDA, "
        "kar_al giriş fiyatının ÜSTÜNDE olmalı."
    )
    payload = {
        "sembol": symbol,
        "yon": direction,
        "guncel_fiyat": k_short[-1]["c"],
        "pozisyon": {"giris_fiyati": entry, "miktar": qty,
                     "deger_usdt": round(qty * k_short[-1]["c"], 2)},
        "nakit_usdt": round(cash, 2),
        "mumlar_saatlik_OHLC": _compact_klines(k_short),
        "mumlar_uzunvade_OHLC": _compact_klines(k_long),
    }
    prompt = (
        f"{dir_note}\n"
        f"Bu pozisyon için koruma seviyeleri belirle:\n"
        f"{json.dumps(payload, separators=(',', ':'))}"
    )
    return await _ask(prompt, PROTECT_SYSTEM)
