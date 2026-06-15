# trade-k

**AI destekli terminal trading uygulaması** — Claude, OpenAI, Gemini, Ollama veya Grok ile piyasa analizi; paper ve gerçek işlem desteği.

```
┌─────────────────────────────────────────────────────────────────┐
│  ◈ PAPER    ✔ CLAUDE:SONNET    ✔ BİNANCE:BAĞLI    AUTO·LONG   │
│                                                                   │
│  PİYASA            POZİSYONLAR        HESAP / GÜNLÜK            │
│  BTCUSDT  105,420  BTC  LONG  +2.1%   Nakit:    8,240 USDT     │
│  ETHUSDT   3,890   ETH  SHORT -0.4%   Varlık:  10,150 USDT     │
│  SOLUSDT     185   SOL  SCALP  ⏱9:30  Gün K/Z: +150 (+1.5%)   │
│                                        AUTO·LONG 3/6 işlem      │
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
| **Otonom mod** | ✅ AI 15dk'da bir 134+ kripto tarar — **yalnızca kripto** |
| **Otonom LONG** | ✅ Sadece yükseliş adayları |
| **Otonom SHORT** | ✅ Sadece düşüş adayları |
| **Otonom SCALP** | ✅ Hızlı işlem, 3dk tarama, 30dk süre limiti |
| **Otonom LONG+SHORT** | ✅ Her iki yön, dengeli |
| **Otonom KALDIRAÇ** | ✅ Kaldıraçlı paper adaylar |
| **Short paper trading** | ✅ Düşüşten kar, stop/hedef doğru yönde |
| **Kaldıraç paper** | ✅ 1-10x simüle kaldıraç, likidasyon hesabı |
| **Gerçek trading** | ✅ Binance / Bybit / OKX spot |
| **Stop / Take Profit** | ✅ AI belirler, otomatik tetikler |
| **Fiyat alarmları** | ✅ Hedef fiyatta otomatik al/sat/bildir |
| **Limit emirleri** | ✅ Paper modda limit al/sat, otomatik doldurma |
| **Teknik analiz** | ✅ RSI, MACD, BB, EMA20/50, ADX, ATR, hacim |
| **Multi-timeframe** | ✅ 15m·1h·4h·1d aynı anda analiz |
| **Backtesting** | ✅ Walk-forward, Monte Carlo, sembol taraması |
| **Performans raporu** | ✅ Sharpe, Sortino, Calmar, MDD, equity curve |
| **Dışa aktarma** | ✅ Tam detaylı .txt rapor — her metrik dahil |
| **Telegram bot** | ✅ Çift yönlü kontrol — tüm komutlar Telegram'dan |
| **Türkçe / İngilizce** | ✅ Tam dil desteği |
| **Web UI** | 🚧 Geliştirme aşamasında |

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

## Otonom Mod

AI her 15 dakikada bir 134 kripto sembolü tarar, uygun adaylarda otomatik paper trade açar.

```
/otonom ac long       → Sadece LONG (yükseliş) adayları — en güvenli
/otonom ac short      → Sadece SHORT (düşüş) adayları
/otonom ac longshort  → LONG + SHORT (her iki yön)
/otonom ac scalp      → Sadece SCALP (hızlı, 3dk tarama, 30dk süre)
/otonom ac kaldirac   → Kaldıraçlı paper adaylar (1-10x)
/otonom ac tam        → Tüm türler (LONG+SHORT+SCALP+KALDIRAÇ)

/otonom mod guvenli   → Max 2 pozisyon, %60 min güven, %2 günlük zarar limiti
/otonom mod dengeli   → Max 4 pozisyon, %50 min güven, %4 günlük zarar limiti (varsayılan)
/otonom mod agresif   → Max 6 pozisyon, %45 min güven, %7 günlük zarar limiti

/otonom ayar işlem-limit 10   → Günlük max işlem sayısını özelleştir
/otonom ayar pozisyon-limit 5 → Eş zamanlı max pozisyon sayısını özelleştir
/otonom durum         → Aktif mod, izinler, günlük istatistik
/otonom kapat         → Durdur
/otonom sifirla       → Günlük sayaçları ve risk kilidini sıfırla
```

> **Not:** Otonom mod yalnızca kripto (USDT çiftleri) çalışır. Altın, döviz, endeks fiyatları 15dk gecikmeli olduğu için otonom tarama dışında tutulur.

---

## Tüm Terminal Komutları

### Analiz & Bilgi
| Komut | Açıklama |
|---|---|
| `/tara` | AI tüm kripto piyasasını tarar |
| `/tara kripto` | Kripto odaklı tarama |
| `/tara long` | Sadece yükseliş adayları |
| `/tara short` | Sadece düşüş adayları |
| `/tara scalp` | Hızlı işlem fırsatları (scalp) |
| `/tara kaldirac` | Kaldıraçlı paper adayları |
| `/tara swing` | Swing trade fırsatları |
| `/durum` | Açık pozisyonları AI ile analiz et |
| `/detay BTCUSDT` | Tek sembol detayı (veri kalitesi, kaldıraç izni) |
| `/ta BTC 1h` | Teknik analiz: RSI, MACD, BB, EMA, ATR |
| `/mtf BTC` | Multi-timeframe: 15m·1h·4h·1d |
| `/backtest BTC 1h 30` | 30 günlük backtest |
| `/backtest wf BTC` | Walk-forward analizi |
| `/backtest mc BTC` | Monte Carlo simülasyonu (200 senaryo) |
| `/backtest scan` | İzleme listesi backtest taraması |
| `/performans` | Sharpe, Sortino, Calmar, win rate, equity curve |
| `/gecmis` | Son 10 işlem + son 10 öneri |
| `/risk` | Portföy risk dashboardu |
| `/strateji liste` | Tüm stratejiler (momentum/dönüş/kırılım/konsensüs) |
| `/strateji analiz BTC` | Tüm stratejileri tek sembolde çalıştır |

### Trade
| Komut | Açıklama |
|---|---|
| `/al BTC 500` | 500 USDT BTC al (paper/gerçek) |
| `/short BTC 500` | 500 USDT BTC short (paper only) |
| `/scalp ac` | Scalp modunu etkinleştir |
| `/sat BTC` | Pozisyonu kapat |
| `/sat BTC 200` | 200 USDT kısmi kapat |
| `/koru BTC` | AI stop/target belirlesin |
| `/onayla 1 2` | /tara önerilerini onayla |
| `/onayla hepsi` | Tüm önerileri onayla |
| `/reddet` | Bekleyen önerileri reddet |
| `/uygula BTC` | /durum kararını uygula |
| `/uygula hepsi` | Tüm durum kararlarını uygula |
| `/kaldirac ac` | Kaldıraçlı paper modunu etkinleştir |
| `/limit al BTC 500 103000` | 103000'e düşünce 500 USDT al |
| `/limit sat BTC 110000` | 110000'e çıkınca pozisyonu sat |
| `/limit liste` | Bekleyen limit emirler |
| `/limit iptal hepsi` | Tüm limit emirleri iptal et |
| `/fiyat al BTC 500 90000` | BTC 90000'e düşünce 500$ al (alarm) |
| `/fiyat sat BTC 110000` | BTC 110000'e çıkınca sat (alarm) |
| `/fiyat bildir BTC 100000` | Hedef fiyata ulaşınca bildir |
| `/fiyat liste` | Aktif alarmları listele |
| `/fiyat sil` | Tüm alarmları sil |

### Otonom
| Komut | Açıklama |
|---|---|
| `/otonom ac [mod]` | Otonom modu başlat |
| `/otonom kapat` | Otonom modu durdur |
| `/otonom durum` | Detaylı durum ve istatistik |
| `/otonom mod guvenli\|dengeli\|agresif` | Risk profilini değiştir |
| `/otonom ayar işlem-limit N` | Günlük max işlem sayısı |
| `/otonom ayar pozisyon-limit N` | Max açık pozisyon sayısı |
| `/otonom sifirla` | Sayaçları ve risk kilidini sıfırla |

### Ayarlar
| Komut | Açıklama |
|---|---|
| `/model` | Aktif AI göster, tüm seçenekler |
| `/model claude sonnet` | Claude Sonnet'e geç |
| `/model openai gpt-4o` | OpenAI GPT-4o'ya geç |
| `/model gemini flash` | Gemini Flash'a geç |
| `/model key openai sk-...` | OpenAI API key kaydet |
| `/canli bagla API SECRET` | Borsa API bağla |
| `/canli mod live` | Gerçek para moduna geç |
| `/canli mod paper` | Paper moduna dön |
| `/canli bakiye` | Borsa gerçek bakiyeni göster |
| `/bildirim bagla TOKEN CHAT_ID` | Telegram bağla |
| `/bildirim test` | Telegram test mesajı gönder |
| `/bildirim kes` | Telegram bağlantısını kes |
| `/strateji momentum\|dönüş\|kırılım\|konsensüs` | Aktif stratejiyi değiştir |
| `/ekle SOLUSDT` | İzleme listesine ekle |
| `/cikar SOLUSDT` | İzleme listesinden çıkar |
| `/bakiye` | Paper bakiyeyi göster |
| `/bakiye ayarla 5000` | Paper bakiyeyi ayarla |
| `/sifirla evet` | Hesabı 10.000 USDT'ye sıfırla |
| `/cikis` | Menüye dön |
| `/yardim` | Kısa komut listesi |
| `/yardim tam` | Tüm komutlar |

---

## Telegram Bot Komutları

Telegram'dan uygulamayı uzaktan kontrol edebilirsin. Sadece yetkili `chat_id`'den gelen komutlar kabul edilir.

| Komut | Açıklama |
|---|---|
| `/durum` | Açık pozisyonlar, K/Z, stop/hedef |
| `/bakiye` | Nakit, varlık, pozisyon sayısı |
| `/performans` | Detaylı performans raporu (win rate, PF, MDD) |
| `/gecmis` | Son 8 işlem |
| `/fiyat BTC ETH SOL` | Anlık fiyatlar (max 5) |
| `/otonom ac long` | Otonom LONG modunu başlat |
| `/otonom ac short` | Otonom SHORT modunu başlat |
| `/otonom ac longshort` | LONG+SHORT modunu başlat |
| `/otonom ac scalp` | SCALP modunu başlat |
| `/otonom ac kaldirac` | Kaldıraç modunu başlat |
| `/otonom ac tam` | Tüm modları başlat |
| `/otonom kapat` | Otonom modu durdur |
| `/otonom durum` | Detaylı durum (equity, loss%, ws, cooldown, pozisyonlar) |
| `/durdur` | Otonom modu hızlıca durdur |
| `/acil` | **ACİL:** Tüm pozisyonları kapat + otonom durdur |
| `/limit 5` | Günlük işlem limitini runtime'da değiştir (1-50) |
| `/limit durum` | Aktif limit ve bugünkü kullanım |
| `/sat BTC` | Pozisyonu kapat (paper) |
| `/mod guvenli\|dengeli\|agresif` | Risk profilini değiştir |
| `/sifirla` | Risk kilidini sıfırla |
| `/ping` | Bağlantı testi |
| `/yardim` | Tam komut listesi |

---

## Güvenlik — Token & Secret Yönetimi

### İlk kurulum (.env ile)

```bash
cp .env.example .env
# .env dosyasını aç ve gerçek değerleri yaz:
#   TELEGRAM_TOKEN=<BotFather'dan aldığın token>
#   TELEGRAM_CHAT_ID=<chat ID>
#   ANTHROPIC_API_KEY=<Claude key>
```

`.env` dosyası `.gitignore`'da — asla repo'ya commit edilmez.

### Telegram Token Sızdıysa Yapılacaklar

Token git geçmişine veya herkese açık bir yere düştüyse:

1. **Token hemen iptal et:** Telegram'da `@BotFather` → `/revoke` → botu seç → onayla
2. **Yeni token al:** `/newbot` veya `/mybots` → `API Token`
3. **`.env` dosyasını güncelle:** `TELEGRAM_TOKEN=<yeni_token>`
4. **`config.json`'daki eski token'ı temizle** (varsa)
5. Git geçmişini temizlemek opsiyonel — token revoke edilince geçmişte kalan değer geçersizdir

> **Not:** `config.json` `.gitignore`'da. Bu dosyayı asla `git add` ile ekleme.

### Neyi Commit Etme

```
❌ config.json          — Telegram token, API key, şifre hash
❌ .env                 — Tüm secret'lar
❌ account.json         — Portföy verisi
❌ autonomous_state.json
❌ *.token, secrets.*   — Herhangi bir secret dosyası
✅ .env.example         — Sadece placeholder içerir, commit edilebilir
```

---

## Otonom Güvenlik Özellikleri (M2.5)

| Özellik | Açıklama |
|---|---|
| **Günlük zarar limiti bildirimi** | Limit tetiklenince Telegram'a net uyarı gider |
| **WebSocket stale koruması** | WS kopuksa tarama atlanır, spam olmadan bildirim |
| **/acil komutu** | Tüm pozisyonları anında kapat + otonom durdur |
| **/limit komutu** | Günlük işlem limitini runtime'da değiştir |
| **Zengin /otonom durum** | Equity, loss%, ws durumu, cooldown, pozisyon listesi |
| **PnL bildirimi düzeltildi** | Satış/kapanış Telegram mesajında K/Z artık doğru |
| **Incident log** | Kritik olaylar `logs/incidents.jsonl`'e kalıcı yazılır |
| **Restart güvenliği** | Bot restart → otonom kapalı başlar, açık pozisyonlar korunur |

### Restart Davranışı

Bot yeniden başlatılınca otonom mod **otomatik açılmaz** — bu bilinçli güvenlik kararıdır.
Açık pozisyonların stop/target koruması anında devam eder.
Otonom devam için: `/otonom ac [mod]`

---

## Performans Raporu

`/performans` komutu veya Menü → Raporlar → Dışa Aktar seçeneği ile tam rapor alınır.

**Rapor içeriği:**
- Sistem bilgileri (mod, borsa, AI, otonom profil)
- Portföy anlık durumu (pozisyon detayları, süre, stop, hedef)
- Tam işlem geçmişi (zaman damgalı, her kayıt)
- **Performans metrikleri:**
  - Kazanma oranı (Win Rate)
  - Profit Factor
  - Beklenti (USDT/işlem)
  - Ortalama kazanç / kayıp
  - En iyi / en kötü işlem
  - Max ardışık kazanç/kayıp serisi
  - Sharpe Ratio (yıllıklaştırılmış, >1.0 iyi, >2.0 mükemmel)
  - Sortino Ratio (aşağı yönlü risk bazlı)
  - Calmar Ratio (yıllık getiri / MDD)
  - Max Drawdown (peak-to-trough %)
- Günlük K/Z dağılımı (bar grafik)
- Otonom mod istatistikleri (gün sayacı, risk kilidi)
- AI öneri performansı (kabul oranı, sembol dağılımı)

---

## AI Seçenekleri

### Claude (varsayılan — abonelik gerekli)
```
# Claude Code aboneliğin varsa hazır, ek kurulum yok
/model claude sonnet   → claude-sonnet-4-6 (varsayılan)
/model claude opus     → claude-opus-4-8 (en güçlü)
/model claude haiku    → claude-haiku-4-5 (en hızlı)
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

## Telegram Kurulum

```
/bildirim bagla BOT_TOKEN CHAT_ID
/bildirim test
```

[@BotFather](https://t.me/BotFather) → `/newbot` → token al → bota mesaj gönder → `getUpdates` ile chat_id bul.

---

## Algoritmik İyileştirme Önerileri

Mevcut sistem çalışıyor, ancak aşağıdaki geliştirmeler güvenilirliği ve karlılığı artırır:

### 1. Sinyal Kalitesi
- **ATR-bazlı dinamik stop**: Sabit % yerine `ATR × 1.5` kullanmak volatiliteye uyum sağlar
- **Volume confirmation**: Hacim ortalamanın 1.5x üstündeyken giriş güvenini artırır
- **RSI divergence**: Fiyat yeni zirve yaparken RSI yapamazsa — erken dönüş sinyali
- **EMA ribbon**: EMA 8/13/21/34 gruplaması trendin güçlenip zayıfladığını gösterir

### 2. Risk Yönetimi
- **Kelly Criterion pozisyon boyutlaması**: Win rate + profit factor kullanarak optimal miktar hesabı
  ```
  f = W/L - (1-W)/W  →  yatırılacak bakiye yüzdesi
  ```
- **Korelasyon filtresi**: BTC+ETH+SOL aynı anda LONG ise korelasyonlu pozisyon sayılır — limit 2 ile
- **Trailing stop**: ATR bazlı trailing (sabit değil kayan) stop zararları minimize eder
- **Time-based exit**: Scalp pozisyon 30dk'dan, spot 7 günden uzunsa zorla kapat

### 3. Tarama Kalitesi
- **Likidite filtresi**: 24h hacim < 5M USDT olan coinleri tara dışı bırak (spread çok geniş)
- **Funding rate sinyali**: Perpetual kontrat funding rate > %0.1 ise short için iyi sinyal
- **Order book imbalance**: Bid/ask oranı > 60/40 ise yön güvenilirliği artar
- **Volatility clustering**: ATR son 5 bar'da artıyorsa breakout yaklaşıyor olabilir

### 4. Çıkış Stratejisi
- **Kısmi kar alma**: Hedefin %50'sine ulaşınca pozisyonun %50'sini kapat, stop'u başa al
- **Time decay exit**: Pozisyon belirli bir süre sonra kara geçmemişse zararı kes (düşük R/R)
- **Momentum death**: MACD histogram sıfır çizgisini geçerse pozisyondan çık

### 5. Backtesting Gerçekçiliği
- **Slippage modeli**: Şu an %0.1 sabit — hacime göre dinamik olmalı (büyük emirde %0.2-0.3)
- **Komisyon tiers**: Binance VIP seviyeleri — yüksek hacimde %0.075 komisyon
- **Gap risk**: Gece açılış gaplerini simüle et (özellikle weekend kripto tarafında)

---

## Güvenlik

- API anahtarları **yalnızca yerelde** (`config.json`, izin 600) saklanır
- Şifreler PBKDF2-SHA256 ile hashlenir, düz metin asla yazılmaz
- Anahtarlar log'da **maskelenir**
- **Withdraw izni gerektirmez**
- IP kısıtlaması önerilir
- Tüm kaldıraçlı işlemler **paper only** — `REAL_ORDER_DISABLED` guard koruması
- Telegram botu yalnızca kayıtlı `chat_id`'den komut kabul eder

---

## Kısıtlamalar

| Alan | Durum |
|---|---|
| **Otonom mod** | Yalnızca kripto (USDT çiftleri) |
| **Non-kripto alım-satım** | Fiyat izleme var, otonom/paper devre dışı |
| **Gerçek kaldıraç** | Paper only — gerçek futures emri gönderilmez |
| **Web UI** | Geliştirme aşamasında |
| **Fiyat alarmı kalıcılığı** | Uygulama kapatılırsa alarmlar sıfırlanır |

---

## Mimari

```
app.py          — Textual TUI, komut dispatcher (~3200 satır)
ai.py           — AI provider abstraction (Claude/OpenAI/Gemini/Ollama/Grok)
autonomous.py   — Otonom trading engine (134 kripto, çoklu mod, risk profilleri)
portfolio.py    — Pozisyon ve bakiye takibi (LONG/SHORT/SCALP/LEV, liquidation)
market.py       — Fiyat verileri (Binance WS + bookTicker REST + Yahoo Finance)
indicators.py   — Teknik analiz (RSI/MACD/BB/EMA/ADX/ATR, multi-TF)
strategies.py   — Strateji motoru (momentum/dönüş/kırılım/konsensüs)
performance.py  — Performans metrikleri (Sharpe/Sortino/Calmar/MDD/equity curve)
backtest.py     — Backtesting (walk-forward, Monte Carlo, sembol taraması)
screens.py      — Menü ekranları ve rapor dışa aktarma (Textual)
commands.py     — Komut kayıt defteri ve palet sistemi
config.py       — Yapılandırma ve şifre yönetimi (PBKDF2-SHA256)
exchange.py     — Borsa dispatcher (Binance/Bybit/OKX)
live.py         — Binance spot API
bybit.py        — Bybit spot API
okx.py          — OKX spot API
notify.py       — Telegram bildirim + çift yönlü komut botu
orders.py       — Limit emir defteri (paper modda)
risk.py         — Risk kapısı, portföy heat map, korelasyon kontrolü
tracker.py      — AI öneri takibi ve performans ölçümü
api.py          — Web UI backend (FastAPI) — geliştirmede
web/            — Web UI frontend — geliştirmede
tests/          — Otomatik test paketi
```

---

## Test

```bash
.venv/bin/python -m pytest tests/ -v
```

---

## Lisans

MIT License — özgürce kullanabilir, dağıtabilir, katkıda bulunabilirsin.

> **Risk Uyarısı:** Bu yazılım eğitim ve araştırma amaçlıdır. Gerçek para ile işlem yaparken kayıp riski vardır. Yazılım geliştiricisi mali sorumluluk kabul etmez. Her zaman küçük miktarlarla başla, yatırım tavsiyesi olarak değerlendirme.
