# trade-k

**AI destekli terminal trading uygulaması** — Claude, OpenAI, Gemini, Ollama veya Grok ile piyasa analizi; paper ve gerçek işlem desteği.

```
┌─────────────────────────────────────────────────────────────────┐
│  ◈ PAPER    ✔ CLAUDE:SONNET    ✕ BİNANCE:BAĞLANMADI    TR     │
│                                                                   │
│  PİYASA            POZİSYONLAR        CLAUDE & İŞLEM GÜNLÜĞÜ   │
│  BTCUSDT  105,420  [açık poz yok]     > /tara                   │
│  ETHUSDT   3,890                       BTC trend kırılımı...    │
│  SOLUSDT     185                       ONERILER: [{"islem":"AL" │
│                                                                   │
│  Komut: _                             q → Menü   Esc → Menü    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Özellik Durumu

| Özellik | Durum |
|---|---|
| **Terminal UI** | ✅ Tam çalışıyor |
| **Paper trading** | ✅ Sanal bakiye, gerçek Binance fiyatları |
| **AI Analizi** | ✅ Claude · OpenAI · Gemini · Ollama · Grok |
| **Otonom mod** | ✅ AI 15dk'da bir tarar — **yalnızca kripto, 134 sembol** |
| **Otonom LONG modu** | ✅ Sadece yükseliş adayları |
| **Otonom SHORT modu** | ✅ Sadece düşüş adayları |
| **Otonom SCALP modu** | ✅ Hızlı işlem, 3dk tarama |
| **Otonom LONG+SHORT** | ✅ Her iki yön, dengeli |
| **Short paper trading** | ✅ Düşüşten kar, stop/hedef doğru yönde |
| **Kaldıraç paper** | ✅ 1-10x simüle kaldıraç |
| **Gerçek trading** | ✅ Binance / Bybit / OKX spot |
| **Stop / Take Profit** | ✅ AI belirler, otomatik tetikler |
| **Fiyat alarmları** | ✅ Hedef fiyatta otomatik al/sat/bildir |
| **Telegram bildirimleri** | ✅ Alım/satım/stop anında bildirim |
| **Teknik analiz** | ✅ RSI, MACD, BB, EMA, ADX (134 kripto paralel) |
| **Türkçe / İngilizce** | ✅ Tam dil desteği |
| **Web UI** | 🚧 Geliştirme aşamasında — henüz kullanıma hazır değil |

---

## Kurulum

```bash
git clone https://github.com/kullanici/trade-k
cd trade-k
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
./basla.sh                     # veya: python app.py
```

İlk açılışta kurulum sihirbazı çalışır: dil, isim, şifre, AI modeli seç.

---

## Terminal vs Web UI

| | Terminal | Web UI |
|---|---|---|
| **Çalıştırma** | `./basla.sh` | `./basla_web.sh` |
| **Durum** | ✅ Hazır | 🚧 Geliştirmede |
| **Bağımlılık** | Birbirinden bağımsız | Birbirinden bağımsız |
| **Otonom mod** | ✅ | 🚧 |

Terminal ve Web UI birbirinden **tamamen bağımsızdır** — sadece birini çalıştırmak yeterli.

---

## Otonom Mod

AI her 15 dakikada bir 134 kripto sembolü tarar, uygun adaylarda otomatik paper trade açar.

```
/otonom ac long       → Sadece LONG (yükseliş) adayları — en güvenli
/otonom ac short      → Sadece SHORT (düşüş) adayları
/otonom ac longshort  → LONG + SHORT (her iki yön)
/otonom ac scalp      → Sadece SCALP (hızlı, 3dk tarama)
/otonom ac kaldirac   → Kaldıraçlı paper adaylar
/otonom ac tam        → Tüm türler (LONG+SHORT+SCALP+KALDIRAÇ)

/otonom mod guvenli   → Max 1 pozisyon, %65 min güven
/otonom mod dengeli   → Max 2 pozisyon, %55 min güven  (varsayılan)
/otonom mod agresif   → Max 3 pozisyon, %50 min güven

/otonom durum         → Aktif mod, izinli işlemler, günlük istatistik
/otonom kapat         → Durdur
/otonom sifirla       → Günlük sayaçları sıfırla
```

> **Not:** Otonom mod yalnızca kripto (USDT çiftleri) çalışır. Altın, döviz, endeks fiyatları 15dk gecikmeli Yahoo Finance'den geldiği için otonom tarama dışında tutulur.

---

## Temel Komutlar

| Komut | Açıklama |
|---|---|
| `/tara` | AI tüm kripto piyasasını tarar |
| `/tara short` | Sadece düşüş adayları |
| `/tara long` | Sadece yükseliş adayları |
| `/tara scalp` | Hızlı işlem fırsatları |
| `/onayla 1 2` | /tara önerilerini onayla ve al |
| `/al BTC 500` | 500 USDT BTC al |
| `/short BTC 500` | 500 USDT BTC short (paper) |
| `/sat BTC` | Pozisyonu kapat |
| `/durum` | Açık pozisyonları AI ile analiz et |
| `/uygula hepsi` | /durum kararlarını uygula |
| `/koru BTC` | AI stop/target belirlesin |
| `/performans` | İşlem istatistikleri |
| `/fiyat al BTC 500 90000` | BTC 90000'e düşünce 500$ otomatik al |
| `/fiyat sat BTC 110000` | BTC 110000'e çıkınca otomatik sat |
| `/bildirim bagla TOKEN CHAT_ID` | Telegram bağla |
| `/canli bagla API SECRET` | Borsa API bağla |
| `/yardim` | Tüm komutlar |

**Navigasyon:** `q` veya `Esc` → Menü (komut kutusu boşken)

---

## AI Seçenekleri

### Claude (varsayılan — abonelik gerekli)
```
# Claude Code aboneliğin varsa hazır, ek kurulum yok
```

### OpenAI GPT-4o
```
/model openai gpt-4o
/model key openai sk-...YOUR_KEY...
```

### Google Gemini
```
/model gemini flash
/model key gemini AI...YOUR_KEY...
```

### Ollama (yerel — ücretsiz)
```bash
ollama pull llama3.2
ollama serve
```
```
/model ollama llama3.2
```

### xAI Grok
```
/model grok grok-3-mini
/model key grok xai-...YOUR_KEY...
```

---

## Borsa Bağlantısı

### Binance
1. Binance → Profil → API Management → "Create API"
2. **Enable Spot & Margin Trading** iznini aç
3. Withdraw iznini **ASLA açma** — IP kısıtlaması ekle

```
/canli bagla API_KEY SECRET
/canli mod live
```

### Bybit / OKX
```
# Menü → Bağlantılar & API → Borsa Seç
/canli bagla API_KEY SECRET          # Bybit
/canli bagla API_KEY SECRET PASS     # OKX (passphrase gerekli)
```

---

## Telegram Bildirimleri

```
/bildirim bagla BOT_TOKEN CHAT_ID
/bildirim test
```

[@BotFather](https://t.me/BotFather) → `/newbot` → token al → bota mesaj gönder → `getUpdates` ile chat_id bul.

---

## Güvenlik

- API anahtarları **yalnızca yerelde** (`config.json`, izin 600) saklanır
- Şifreler PBKDF2-SHA256 ile hashlenir, düz metin asla yazılmaz
- Anahtarlar log'da **maskelenir**
- **Withdraw izni gerektirmez**
- IP kısıtlaması önerilir
- Tüm kaldıraçlı işlemler **paper only** — `REAL_ORDER_DISABLED` guard koruması

---

## Kısıtlamalar

| Alan | Durum |
|---|---|
| **Otonom mod** | Yalnızca kripto (USDT çiftleri) |
| **Non-kripto alım-satım** | Fiyat izleme var, otonom/paper devre dışı |
| **Gerçek kaldıraç** | Paper only — gerçek futures emri gönderilmez |
| **Web UI** | Geliştirme aşamasında |

---

## Mimari

```
app.py          — Textual TUI, komut dispatcher
ai.py           — AI provider abstraction (Claude/OpenAI/Gemini/Ollama/Grok)
autonomous.py   — Otonom trading engine (134 kripto, çoklu mod)
portfolio.py    — Pozisyon ve bakiye takibi (LONG/SHORT/SCALP/LEV)
market.py       — Fiyat verileri (Binance WS + bookTicker REST)
indicators.py   — Teknik analiz (RSI/MACD/BB/EMA/ADX)
screens.py      — Menü ekranları (Textual)
config.py       — Yapılandırma ve şifre yönetimi
exchange.py     — Borsa dispatcher (Binance/Bybit/OKX)
live.py         — Binance spot API
bybit.py        — Bybit spot API
okx.py          — OKX spot API
notify.py       — Telegram bildirim sistemi
api.py          — Web UI backend (FastAPI) — geliştirmede
web/            — Web UI frontend — geliştirmede
tests/          — 263 otomatik test
```

---

## Test

```bash
.venv/bin/python -m pytest tests/ -v
# 263 test — tümü geçmeli
```

---

## Lisans

MIT License — özgürce kullanabilir, dağıtabilir, katkıda bulunabilirsin.

> **Risk Uyarısı:** Bu yazılım eğitim ve araştırma amaçlıdır. Gerçek para ile işlem yaparken kayıp riski vardır. Yazılım geliştiricisi mali sorumluluk kabul etmez. Her zaman küçük miktarlarla başla, yatırım tavsiyesi olarak değerlendirme.
