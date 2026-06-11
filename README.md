# trade-k

Claude destekli paper trading (sanal para) terminali. Gerçek piyasa fiyatları,
sanal 10.000 USDT bakiye, Claude Code aboneliğin üzerinden piyasa analizi.

## Başlat

```bash
./basla.sh
```

İlk açılışta kurulum sihirbazı çalışır: **dil → isim → şifre → mod → model**.
Sonraki her açılışta şifre sorulur; 3 yanlış denemede uygulama açılmaz.
Ayarlar `config.json`'da saklanır (şifre PBKDF2 ile özetlenir, düz metin tutulmaz).
Şifreni unutursan `config.json`'u silip kurulumu baştan yap.

## Trade modları

| Mod | Risk | Tek işlem (prompt) | Kod freni | Toplam öneri |
|---|---|---|---|---|
| 🎯 **SNIPER** | Düşük | %5-10 | nakitin %10'u | ≤ %30 |
| ⚡ **BLITZ** | Orta (varsayılan) | %5-15 | nakitin %20'si | ≤ %50 |
| 🔥 **INFERNO** | Yüksek risk / yüksek kazanç | %10-25 | nakitin %35'i | ≤ %75 |

`/mod` ile listele, `/mod inferno` ile değiştir. Mod hem Claude'a verilen risk
kurallarını hem kod tarafındaki freni değiştirir. Başarı yüzdesi tavanı (%80)
hiçbir modda gevşemez.

## Claude modeli seçimi

`/model` ile listele, `/model opus` ile değiştir:

| Anahtar | Model | Ne zaman |
|---|---|---|
| `opus` | Claude Opus 4.8 | En güçlü analiz, daha yavaş |
| `sonnet` | Claude Sonnet 4.6 | Hız/zekâ dengesi (önerilen, varsayılan) |
| `haiku` | Claude Haiku 4.5 | En hızlı, hafif analizler |
| `varsayilan` | — | Claude CLI'ın kendi varsayılanı |

Hepsi Claude Code aboneliğinden düşer, ayrı API key gerekmez.

## Gerçek para bağlantısı (`/canli`)

`/canli` komutu gereksinimleri adım adım gösterir: Binance hesabı (KYC) →
API Management'tan anahtar oluştur (**sadece "Enable Reading"**, Withdrawals ASLA) →
`/canli bagla API_KEY SECRET`. Anahtar imzalı istekle doğrulanır ve `config.json`'a
kaydedilir; `/canli bakiye` gerçek spot bakiyeni gösterir, `/canli kes` bağlantıyı koparır.

> Emirler şimdilik **her zaman PAPER** hesabında çalışır — gerçek emir gönderimi,
> paper'da kanıtlanmış performanstan sonraki adımdır. Üst barda `LIVE✓` rozeti
> sadece bağlantının doğrulandığını gösterir.

## Komutlar

| Komut | Açıklama |
|---|---|
| `/tara` | Claude tüm piyasayı tarar (kripto + altın/forex/endeks), 2-4 işlem adayı listeler |
| `/onayla 1 3` | Listeden seçtiğin adayları uygula (`/onayla hepsi` de olur) |
| `/reddet` | Bekleyen önerileri temizle |
| `/ai altin` | Tek enstrüman detaylı analizi |
| `/al btc 500` | Manuel alım — Claude stop/hedefi arkada otomatik belirler |
| `/sat btc` | Pozisyonun tamamını sat (`/sat btc 200` kısmi) |
| `/koru btc` | Claude açık pozisyonun stop/hedefini (yeniden) belirlesin |
| `/ekle doge` | Kripto watchlist'e ekle (en fazla 5) |
| `/cikar xrp` | Watchlist'ten çıkar |
| `/mod [isim]` | Trade modu listele / değiştir (sniper, blitz, inferno) |
| `/model [isim]` | Claude modeli listele / değiştir (opus, sonnet, haiku) |
| `/canli ...` | Gerçek para bağlantısı: durum, `bagla KEY SECRET`, `bakiye`, `kes` |
| `/performans` | Claude'un öneri karnesi: isabet oranı, kazanan/kaybeden, sanal PnL |
| `/gecmis` | Son 10 işlem + son 10 öneri (tablo) |
| `/sifirla` | Hesabı 10.000 USDT'ye sıfırla (öneri geçmişi saklanır) |
| `q` | Çıkış |

## Enstrümanlar

Piyasa paneli iki bölümdür (enstrümanlar uluslararası/gerçek adlarıyla gösterilir):
- **KRİPTO** (watchlist, düzenlenebilir, en fazla 5): btc, eth, sol, doge... (tüm Binance USDT pariteleri)
- **GLOBAL** (her zaman görünür): GOLD (XAU), SILVER (XAG), WTI CRUDE, NATURAL GAS,
  COPPER, EUR/USD, GBP/USD, USD/JPY, USD/TRY, S&P 500, NASDAQ 100, DOW JONES, DAX 40, BIST 100

Komutlarda Türkçe ad da yeterli: `/ai altin`, `/al gumus 300`, `/koru dogalgaz`, `/ai bakir`.

## Otomatik kapatma (zarar-kes / kâr-al)

Her açılan pozisyona Claude piyasa yapısına ve bakiyeye göre **stop** (zarar-kes) ve
**hedef** (kâr-al) fiyatı belirler; uygulama fiyatı 2 saniyede bir kontrol eder ve
seviye gelince pozisyonu **otomatik kapatır** (ZARAR KESİLDİ / KÂR ALINDI).

- `/onayla` ile açılan işlemler: stop/hedef Claude'un önerisinden gelir.
- `/al` ile manuel açılan işlemler: Claude arkada koruma seviyesi belirler.
- `/koru SEMBOL`: mevcut pozisyonun seviyelerini Claude'a yeniden belirletir.
- Kod tarafı doğrulama: stop girişin %0.1-20 altında, hedef %0.1-60 üstünde olmalı;
  Claude saçmalarsa güvenli varsayılana (%5 stop / %10 hedef) çekilir.

## Profesyonel trader profili

Claude'a kurumsal trader personası ve manipülasyon kontrol listesi gömülüdür:
sahte kırılım (hacim teyitsiz kırılıma girmez), stop avı (stopları kalabalığın
stop bölgesinin ötesine koyar), pump&dump (günlük +%15 üzeri FOMO alımı önermez),
düşük likidite ve tek-mum/haber tuzakları. İlke: "fırsatı kaçırmak para
kaybetmekten iyidir."

## Risk koruması (iki katman)

1. **Claude tarafı:** önerilerin toplamı ve tek işlem oranı aktif moda göre sınırlanır
   (yukarıdaki tabloya bak), başarı yüzdesi temkinli tahmin edilir (%80 üstü her modda yasak),
   zorlama işlem üretilmez.
2. **Kod tarafı:** Claude ne önerirse önersin tek işlem, aktif modun kod frenini
   (%10 / %20 / %35) geçemez — aşan tutar otomatik düşürülür.

Not: Bu spot paper trading'dir, kaldıraç yok → liquidation (liq) riski zaten yoktur.
Buradaki kurallar bakiyenin dengeli ve çeşitlendirilmiş kalması içindir.

## Performans takibi

Her `/tara` ve `/ai` önerisi giriş fiyatıyla `recommendations.json`'a kaydedilir
(durum: bekliyor → onaylandı / reddedildi / süresi doldu). `/performans` bu kayıtları
güncel fiyata göre değerlendirir: AL önerisinden sonra fiyat yükseldiyse kazanan,
düştüyse kaybeden (SAT için tersi).

Geçmişte en az 5 değerlendirilmiş öneri biriktiğinde, `/tara` çıktısındaki başarı
yüzdeleri Claude'un gerçek isabet oranıyla harmanlanarak **aşağı yönlü** kalibre
edilir — geçmiş kötüyse yüzde düşer, geçmiş iyi olsa bile yüzde asla yukarı çekilmez.

## Testler

```bash
.venv/bin/python -m pytest tests/
```

## Nasıl çalışır

- **Kripto fiyatları:** Binance public websocket (`data-stream.binance.vision`) — anlık, key gerekmez.
- **Altın/forex/endeks:** Yahoo Finance public API — ~5 sn'de bir yenilenir.
- **Claude:** `claude-agent-sdk` yerel `claude` CLI'ını kullanır → Claude Code aboneliğinden düşer.
- **Hesap:** `account.json`, **watchlist:** `watchlist.json` — kalıcıdır.
