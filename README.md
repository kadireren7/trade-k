# trade-k

Claude destekli paper trading terminali. Gerçek piyasa fiyatları, sanal 10.000 USDT
bakiye, Claude Code aboneliği üzerinden AI piyasa analizi.

> **Güvenlik:** Gerçek emir gönderimi `REAL_ORDER_DISABLED` ile kalıcı olarak devre dışıdır.
> API key bağlı olsa bile tüm işlemler PAPER/simülasyon olarak kalır.

---

## Başlangıç

```bash
./basla.sh
```

İlk açılışta kurulum sihirbazı: **dil → isim → şifre → model**.
Sonraki her açılışta şifre sorulur; 3 yanlış denemede uygulama kapanır.
Ayarlar `config.json`'da saklanır (şifre PBKDF2-SHA256 ile özetlenir, düz metin yoktur).
Şifreni unutursan `config.json`'u sil ve kurulumu baştan yap.

---

## Özellikler

| Özellik | Durum | Notlar |
|---|---|---|
| Paper trading (spot long) | ✅ | Stop/target otomatik belirleme |
| Paper short | ✅ | Isolated margin simülasyonu |
| Paper scalp | ✅ | Max 30dk, fee + slippage dahil |
| Paper kaldıraç | ✅ | Max 5x, likidasyon simülasyonu |
| Otonom mod (Claude AI) | ✅ | PAPER only, 3 risk profili |
| Binance realtime fiyat | ✅ | WebSocket, key gerekmez |
| Yahoo Finance (gecikmeli) | ✅ | ~15dk gecikme, global piyasalar |
| Altın fiyatı | ✅ | goldprice.org near-realtime |
| Komut paleti (`/` + Tab) | ✅ | Fuzzy match, TR/EN |
| İki dil | ✅ | Türkçe / English |
| Gerçek emir gönderimi | ❌ | Kalıcı olarak devre dışı |

---

## Komut Referansı

### Türkçe komutlar

| Komut | Açıklama |
|---|---|
| `/tara` | Claude piyasa analizi — 2-4 işlem adayı |
| `/al SEMBOL [miktar]` | Paper long aç |
| `/sat SEMBOL` | Paper pozisyon kapat |
| `/short SEMBOL [miktar]` | Paper short aç |
| `/scalp SEMBOL [miktar]` | Paper scalp (max 30dk) |
| `/onayla 1 3` veya `/onayla hepsi` | Bekleyen önerileri uygula |
| `/reddet` | Bekleyen önerileri iptal et |
| `/koru SEMBOL` | Claude stop/hedefi yeniden belirlesin |
| `/durum` | Açık pozisyonlar |
| `/sonuc` | Kapalı işlem geçmişi |
| `/rapor` | Performans özeti |
| `/bakiye` | Paper bakiye ve özsermaye |
| `/mod [isim]` | Risk modunu listele / değiştir |
| `/model [isim]` | Claude modelini listele / değiştir |
| `/ekle SEMBOL` | Kripto watchlist'e ekle |
| `/cikar SEMBOL` | Watchlist'ten çıkar |
| `/ayarlar` | Ayarlar menüsü |
| `/canli` | Binance API bağlantısı |
| `/otonomu` | Otonom mod menüsü |
| `/guvenlik` | Güvenlik durumu |
| `/yardim` | Komut listesi |
| `q` | Çıkış |

### English commands

Tüm komutların İngilizce karşılığı mevcuttur:
`/scan`, `/buy`, `/sell`, `/short`, `/scalp`, `/approve`, `/reject`, `/protect`,
`/status`, `/history`, `/report`, `/balance`, `/mode`, `/model`, `/add`, `/remove`,
`/settings`, `/live`, `/autonomous`, `/safety`, `/help`

`/` yazıp Tab'a basınca komut paleti açılır; yukarı/aşağı ok ve Tab ile seçim yapılır.

---

## Trade Risk Modları

| Mod | Tek işlem | Kod freni | Toplam öneri |
|---|---|---|---|
| `sniper` | %5-10 | Nakitin %10'u | ≤ %30 |
| `standart` / `blitz` | %5-15 | Nakitin %20'si | ≤ %50 |
| `inferno` | %10-25 | Nakitin %35'i | ≤ %75 |

Başarı yüzdesi tavanı (%80) hiçbir modda gevşemez.
`/mod inferno` ile değiştir, `/mod` ile listele.

---

## Otonom Mod

Claude AI piyasayı periyodik olarak tarar ve PAPER işlem açıp kapatır.

**Başlatma:** `/otonomu` → **Otonom Modu Başlat** → 4 adımlı kurulum sihirbazı:
1. Güvenlik uyarısı onayı (REAL_ORDER_DISABLED teyidi)
2. Risk profili seçimi
3. Özellik seçimi (scalp paper, kaldıraç paper)
4. Özet onayı → terminal ekranına geçiş

### Risk Profilleri

| Profil | Max Poz | Max/Gün | Zarar Serisi Kilidi | Günlük Kayıp Kilidi |
|---|---|---|---|---|
| `güvenli` | 1 | 3 | 2 ard. zarar | %1 |
| `dengeli` | 2 | 6 | 3 ard. zarar | %2 |
| `agresif` | 3 | 10 | 4 ard. zarar | %3 |

Kaldıraç sınırı: güvenli=2x, dengeli=3x, agresif=5x.

---

## Claude Modelleri

| Anahtar | Model | Kullanım |
|---|---|---|
| `opus` | Claude Opus 4.8 | En güçlü analiz, daha yavaş |
| `sonnet` | Claude Sonnet 4.6 | Hız/zekâ dengesi — önerilen (varsayılan) |
| `haiku` | Claude Haiku 4.5 | En hızlı, hafif analizler |
| `varsayilan` | CLI varsayılanı | Claude CLI'ın kendi seçimi |

Hepsi Claude Code aboneliğinden düşer; ayrı API key gerekmez.

---

## Veri Kaynakları

| Sembol | Kaynak | Gecikme | Kaldıraç |
|---|---|---|---|
| BTC, ETH ve kripto | Binance WebSocket | Gerçek zamanlı | ✅ |
| Altın (XAU/USD) | goldprice.org | ~1dk | ❌ |
| Hisse, ETF, döviz, emtia | Yahoo Finance | ~15dk | ❌ |

Kaldıraçlı paper işlem yalnızca gerçek zamanlı Binance verisi olan sembollerde açılır.
Market tablosunda RT/NRT/DLY (realtime/near-realtime/delayed) ve L✓/L✗ (kaldıraç
uygunluğu) göstergeleri vardır.

---

## Otomatik Kapatma (Stop / Target)

Her pozisyona Claude piyasa yapısına göre stop ve hedef fiyatı belirler.
Uygulama fiyatı 2 saniyede bir kontrol eder, seviye gelince otomatik kapatır.

- `Kod doğrulaması:` stop %0.1-20 aşağıda, hedef %0.1-60 yukarıda olmalı
- Claude geçersiz değer önerirse güvenli varsayılana (%5 stop / %10 hedef) çekilir

---

## Kurulum

### Gereksinimler

- Python 3.11+
- Claude Code CLI (terminalde `claude` komutuna erişilebilir olmalı)
- İnternet bağlantısı

### Kurulum adımları

```bash
git clone <repo-url>
cd trade-k
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
./basla.sh
```

---

## Testler

```bash
pytest tests/ -v
# veya
.venv/bin/python -m pytest tests/ -v
```

| Test dosyası | Kapsam |
|---|---|
| `tests/test_login.py` | Kurulum ve giriş sihirbazı (3 test) |
| `tests/test_trade_types.py` | Spot, short, scalp mantığı (15 test) |
| `tests/test_leverage.py` | Kaldıraç, likidasyon, pozisyon büyüklüğü (35 test) |
| `tests/test_commands.py` | Komut kayıt defteri, fuzzy match (21 test) |
| `tests/test_menu.py` | Menü sistemi, ekran geçişleri (18 test) |

---

## Dosya Yapısı

```
trade-k/
├── app.py            — Ana TUI uygulaması, komut işleme, AccountBar
├── app.tcss          — Textual CSS stilleri
├── screens.py        — Ekranlar (kurulum, menü, ayarlar, otonom sihirbazı)
├── commands.py       — Komut kayıt defteri ve palette mantığı
├── autonomous.py     — Otonom trading motoru (PAPER only, güvenlik kilidi)
├── portfolio.py      — Pozisyon ve paper hesap yönetimi
├── ai.py             — Claude AI entegrasyonu
├── config.py         — Yapılandırma ve PBKDF2 şifre yönetimi
├── i18n.py           — TR/EN çeviri
├── basla.sh          — Başlatma betiği
├── config.json       — Kullanıcı ayarları (otomatik, git'e ekleme!)
├── account.json      — Paper bakiye (otomatik)
└── tests/            — Pytest test dosyaları
```

---

## Güvenlik Notları

- `config.json` dosyasını asla paylaşma — Binance API key ve şifre özeti içerir
- Binance API key sadece okuma için kullanılır; trading / withdraw izni **açma**
- Binance secret ekranda `***` olarak gösterilir, hiçbir log dosyasına yazılmaz
- `REAL_ORDER_DISABLED` katmanı: `create_order`, `futures_create_order`, `margin_borrow`,
  `withdraw` çağrıları `RuntimeError("REAL_ORDER_DISABLED")` fırlatır
- Bu davranış arayüzden değiştirilemez; `/guvenlik` komutuyla durumu doğrulayabilirsin

---

## Geliştirici Notu

TCSS renk değerleri: yalnızca `#rrggbb`, `rgb(r,g,b)` veya standart CSS renk isimleri kullan.
`grey85`, `grey42` gibi Rich markup renk isimleri TCSS'de **geçersizdir** ve CSS parse hatasına yol açar.

Yeni komut eklemek için `commands.py` içindeki `REGISTRY` listesini güncelle.
