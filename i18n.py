"""Basit iki dilli (TR/EN) metin katmanı."""
from __future__ import annotations

_LANG = "tr"


def set_language(lang: str) -> None:
    global _LANG
    _LANG = lang if lang in ("tr", "en") else "tr"


def lang() -> str:
    return _LANG


def t(key: str, **kw) -> str:
    table = _STRINGS.get(key, {})
    text = table.get(_LANG) or table.get("tr") or key
    return text.format(**kw) if kw else text


_HELP_TR = """\
[bold cyan]Analiz[/]
  [bold]/tara[/]  [bold]/tara kripto|global|forex|emtia|endeks[/]  → Claude fırsat tarar
  [bold]/tara long|short|scalp|day|swing|kaldirac[/]  → trade tipine göre tara
  [bold]/durum[/]                        → açık pozisyonları Claude ile analiz et
  [bold]/uygula SEMBOL[/]  [bold]/uygula hepsi[/]  → /durum kararlarını uygula
  [bold]/onayla 1 3[/]  [bold]/onayla hepsi[/]     → /tara adaylarını uygula
  [bold]/reddet[/]                       → bekleyen önerileri temizle
  [bold]/ai SEMBOL[/]                    → tek sembol derin analiz   örn: /ai altin
[bold cyan]İşlem[/]
  [bold]/al SEMBOL TUTAR[/]              → Alım (paper: sanal, live: Binance MARKET BUY)
  [bold]/sat SEMBOL \\[TUTAR][/]           → Satım (paper: sanal, live: Binance MARKET SELL)
  [bold]/short SEMBOL TUTAR[/]           → Short (yalnızca paper, realtime kripto)
  [bold]/koru SEMBOL[/]                  → Claude stop/hedef belirlesin (live: OCO emir)
[bold cyan]Scalp & Kaldıraç (Paper)[/]
  [bold]/scalp ac|kapat|durum[/]
  [bold]/kaldirac ac|kapat|durum[/]
[bold cyan]Otonom[/]
  [bold]/otonom ac[/]  [bold]/otonom kapat[/]  [bold]/otonom durum[/]
  [bold]/otonom mod[/]  [bold]/otonom mod guvenli|dengeli|agresif[/]
  [bold]/otonom ayar[/]  → özel limit ayarlarını göster
[bold cyan]Bağlantı & Mod[/]
  [bold]/canli bagla KEY SECRET[/]       → Binance API anahtarı kaydet
  [bold]/canli mod live[/]               → GERÇEK PARA moduna geç
  [bold]/canli mod paper[/]              → Paper (simülasyon) moduna dön
  [bold]/canli bakiye[/]                 → Gerçek Binance bakiyeni göster
  [bold]/canli kes[/]                    → API bağlantısını kes
[bold cyan]Diğer[/]
  [bold]/ekle SEMBOL[/]  [bold]/cikar SEMBOL[/]  → kripto izleme listesi (max 5)
  [bold]/detay SEMBOL[/]               → veri kalitesi + kaldıraç izin bilgisi
  [bold]/model[/]                        → aktif AI sağlayıcısını göster
  [bold]/model claude|openai|gemini|ollama|grok[/]  → AI sağlayıcısını değiştir
  [bold]/model key openai|gemini|grok API_KEY[/]    → API key kaydet
  [bold]/bildirim bagla TOKEN CHAT_ID[/]  → Telegram bildirim kur
  [bold]/bildirim test[/]  [bold]/bildirim kes[/]
[bold cyan]Teknik Analiz & Backtest[/]
  [bold]/ta SEMBOL [1m|5m|15m|1h|4h|1d][/]  → RSI, MACD, BB, EMA, ADX, sinyal
  [bold]/mtf SEMBOL[/]                        → 4 zaman dilimi konsensüs analizi
  [bold]/backtest SEMBOL [TF] [GÜN][/]       → geçmişte strateji test et
  [bold]/boyut SEMBOL STOP% [RİSK%][/]       → kaç USDT almalıyım? (risk yönetimi)
[bold cyan]Strateji & Risk[/]
  [bold]/strateji[/]  [bold]/strateji liste[/]         → aktif strateji
  [bold]/strateji momentum|dönüş|kırılım|konsensüs[/]
  [bold]/strateji analiz SEMBOL[/]  → 3 strateji aynı anda
  [bold]/risk[/]                              → portföy risk dashboardu (heat, VaR, stop)
[bold cyan]Limit Emirler (Paper)[/]
  [bold]/limit al SEMBOL TUTAR FİYAT [SA][/]  → fiyat hedefe düşünce al
  [bold]/limit sat SEMBOL FİYAT [SA][/]        → fiyat hedefe çıkınca sat
  [bold]/limit liste[/]  [bold]/limit iptal [ID|SEMBOL|hepsi][/]
[bold cyan]Fiyat Alarmları[/]
  [bold]/fiyat al SEMBOL TUTAR HEDEF[/]   → hedef fiyata düşünce otomatik al
  [bold]/fiyat sat SEMBOL HEDEF[/]        → hedef fiyata çıkınca otomatik sat
  [bold]/fiyat bildir SEMBOL HEDEF[/]     → fiyat hedefine ulaşınca bildir
  [bold]/fiyat liste[/]  [bold]/fiyat sil[/]
  [bold]/bakiye[/]                        → paper bakiyeni göster
  [bold]/bakiye ayarla 100[/]            → paper bakiyeyi 100 USDT yap (test için)
  [bold]/gecmis[/]  [bold]/performans[/]  [bold]/sifirla evet[/]
  [bold]/cikis[/]                        → menüye dön"""

_HELP_EN = """\
[bold cyan]Analysis[/]
  [bold]/scan[/]  [bold]/scan crypto|global|forex|commodity|index[/]  → Claude scans for opportunities
  [bold]/scan long|short|scalp|day|swing|leverage[/]  → filter by trade type
  [bold]/status[/]                       → analyze open positions with Claude
  [bold]/apply SYMBOL[/]  [bold]/apply all[/]          → apply /status decisions
  [bold]/approve 1 3[/]  [bold]/approve all[/]          → execute /scan candidates
  [bold]/reject[/]                       → clear pending suggestions
  [bold]/ai SYMBOL[/]                    → single symbol deep-dive   e.g. /ai gold
[bold cyan]Trade[/]
  [bold]/buy SYMBOL AMOUNT[/]            → Buy (paper: simulated, live: Binance MARKET BUY)
  [bold]/sell SYMBOL \\[AMOUNT][/]         → Sell (paper: simulated, live: Binance MARKET SELL)
  [bold]/short SYMBOL AMOUNT[/]          → Short (paper only, realtime crypto)
  [bold]/protect SYMBOL[/]              → Claude sets stop/target (live: places OCO order)
[bold cyan]Scalp & Leverage (Paper)[/]
  [bold]/scalp on|off|status[/]
  [bold]/leverage on|off|status[/]
[bold cyan]Autonomous[/]
  [bold]/auto on[/]  [bold]/auto off[/]  [bold]/auto status[/]
  [bold]/auto mode[/]  [bold]/auto mode safe|balanced|aggressive[/]
[bold cyan]Connection & Mode[/]
  [bold]/live bagla KEY SECRET[/]        → save Binance API key
  [bold]/live mod live[/]                → switch to REAL MONEY mode
  [bold]/live mod paper[/]               → switch to paper (simulation)
  [bold]/live bakiye[/]                  → show real Binance balance
  [bold]/live kes[/]                     → disconnect API
[bold cyan]Other[/]
  [bold]/add SYMBOL[/]  [bold]/remove SYMBOL[/]  → crypto watchlist (max 5)
  [bold]/details SYMBOL[/]              → data quality + leverage eligibility
  [bold]/model[/]                         → show active AI provider
  [bold]/model claude|openai|gemini|ollama|grok[/]  → switch AI provider
  [bold]/model key openai|gemini|grok API_KEY[/]    → save API key
  [bold]/notify bagla TOKEN CHAT_ID[/]    → Setup Telegram notifications
  [bold]/notify test[/]  [bold]/notify kes[/]
  [bold]/price buy SYMBOL AMOUNT TARGET[/]  → auto-buy when price drops to target
  [bold]/price sell SYMBOL TARGET[/]        → auto-sell when price rises to target
  [bold]/price alert SYMBOL TARGET[/]       → notify when price hits target
  [bold]/price list[/]  [bold]/price clear[/]
  [bold]/balance[/]                      → show paper balance
  [bold]/balance set 100[/]             → set paper balance to 100 USDT (for testing)
  [bold]/history[/]  [bold]/report[/]  [bold]/reset yes[/]
  [bold]/exit[/]                         → return to menu"""

_HELP_SHORT_TR = """\
[bold cyan]En sık kullanılanlar[/]
  [bold]/tara[/]              → Claude fırsat tarar
  [bold]/al BTC 500[/]        → 500 USDT Bitcoin al
  [bold]/sat BTC[/]           → Bitcoin sat
  [bold]/durum[/]             → açık pozisyonları analiz et
  [bold]/ai BTC[/]            → derin sembol analizi
  [bold]/otonom ac[/]         → otonom modu başlat
  [bold]/gecmis[/]            → işlem geçmişi
  [bold]/performans[/]        → performans istatistikleri
  [bold]/bakiye ayarla 100[/] → paper bakiyeyi ayarla
  [bold]/sifirla evet[/]      → hesabı sıfırla
  [bold]/cikis[/]             → menüye dön
  [bold]/yardim tam[/]        → tam komut listesi"""

_HELP_SHORT_EN = """\
[bold cyan]Most used commands[/]
  [bold]/scan[/]              → Claude scans for opportunities
  [bold]/buy BTC 500[/]       → buy 500 USDT of Bitcoin
  [bold]/sell BTC[/]          → sell Bitcoin
  [bold]/status[/]            → analyze open positions
  [bold]/ai BTC[/]            → deep symbol analysis
  [bold]/auto on[/]           → start autonomous mode
  [bold]/history[/]           → trade history
  [bold]/report[/]            → performance stats
  [bold]/balance set 100[/]   → set paper balance
  [bold]/reset yes[/]         → reset account
  [bold]/exit[/]              → return to menu
  [bold]/help full[/]         → full command list"""

_STRINGS: dict[str, dict[str, str]] = {
    "help": {"tr": _HELP_TR, "en": _HELP_EN},
    "help.short": {"tr": _HELP_SHORT_TR, "en": _HELP_SHORT_EN},

    # ── kısa açılış ipucu (startup hint, 1-2 satır) ──
    "app.hint": {
        "tr": "[grey58]Komut listesi: [bold]/yardim[/]   Piyasayı tara: [bold]/tara[/]   Manuel alım: [bold]/al BTC 500[/]   Otonom mod: [bold]/otonom ac[/][/grey58]",
        "en": "[grey58]Commands: [bold]/help[/]   Scan market: [bold]/scan[/]   Manual buy: [bold]/buy BTC 500[/]   Autonomous: [bold]/auto on[/][/grey58]",
    },

    # ── paneller / üst bar ──
    "panel.market": {"tr": " PİYASA ", "en": " MARKETS "},
    "panel.positions": {"tr": " POZİSYONLAR ", "en": " POSITIONS "},
    "panel.log": {"tr": " CLAUDE & İŞLEM GÜNLÜĞÜ ", "en": " CLAUDE & TRADE LOG "},
    "bar.equity": {"tr": "Varlık", "en": "Equity"},
    "bar.cash": {"tr": "Nakit", "en": "Cash"},
    "bar.pnl": {"tr": "K/Z", "en": "P/L"},
    "watch.crypto": {"tr": "── KRİPTO ──", "en": "── CRYPTO ──"},
    "watch.global": {"tr": "── GLOBAL ──", "en": "── GLOBAL ──"},
    "cmd.placeholder": {
        "tr": "Komut yaz... (/yardim)",
        "en": "Type a command... (/help)",
    },

    "app.started": {
        "tr": "[bold gold3]trade-k[/] başlatıldı — hoş geldin [bold]{name}[/]! Sanal hesap, gerçek fiyatlar.",
        "en": "[bold gold3]trade-k[/] started — welcome [bold]{name}[/]! Paper account, real prices.",
    },
    "app.mode_model": {
        "tr": "Model: [bold]{model}[/]   (/model ile değiştir)  |  Otonom: /otonom ac  /otonom mod",
        "en": "Model: [bold]{model}[/]   (change with /model)  |  Autonomous: /auto on  /auto mode",
    },

    # ── kurulum sihirbazı ──
    "setup.title": {"tr": "trade-k kurulumu", "en": "trade-k setup"},
    "setup.lang": {
        "tr": "Dil seç / Choose language:\n\n  [bold]1[/]) Türkçe\n  [bold]2[/]) English\n\nSeçim / choice (1-2):",
        "en": "Dil seç / Choose language:\n\n  [bold]1[/]) Türkçe\n  [bold]2[/]) English\n\nSeçim / choice (1-2):",
    },
    "setup.invalid": {"tr": "Geçersiz seçim, tekrar dene.", "en": "Invalid choice, try again."},
    "setup.name": {"tr": "Adın ne?", "en": "What's your name?"},
    "setup.name_short": {"tr": "En az 2 karakter gir.", "en": "Enter at least 2 characters."},
    "setup.pw": {
        "tr": "Bir şifre belirle (en az 4 karakter).\nBundan sonra her açılışta sorulacak:",
        "en": "Set a password (min 4 characters).\nIt will be asked on every launch:",
    },
    "setup.pw_short": {
        "tr": "Şifre en az 4 karakter olmalı.",
        "en": "Password must be at least 4 characters.",
    },
    "setup.pw2": {"tr": "Şifreyi tekrar gir:", "en": "Repeat the password:"},
    "setup.pw_mismatch": {
        "tr": "Şifreler uyuşmadı, baştan al.",
        "en": "Passwords don't match, start over.",
    },
    "setup.model": {
        "tr": "Claude modelini seç:\n\n{models}\nSeçim (1-{n}):",
        "en": "Choose the Claude model:\n\n{models}\nChoice (1-{n}):",
    },
    "setup.done": {
        "tr": "Kurulum tamam! İyi işlemler [bold]{name}[/]",
        "en": "Setup complete! Happy trading [bold]{name}[/]",
    },

    # ── giriş ──
    "login.title": {"tr": "trade-k — giriş", "en": "trade-k — login"},
    "login.prompt": {
        "tr": "Merhaba [bold]{name}[/], şifreni gir:",
        "en": "Hello [bold]{name}[/], enter your password:",
    },
    "login.wrong": {
        "tr": "Yanlış şifre. Kalan hak: {n}",
        "en": "Wrong password. Attempts left: {n}",
    },
    "login.locked": {
        "tr": "3 yanlış deneme — uygulama kapatılıyor.",
        "en": "3 failed attempts — closing.",
    },

    # ── model komutu ──
    "model.list": {
        "tr": "[bold cyan]Claude modelleri[/] (aktif: {active})",
        "en": "[bold cyan]Claude models[/] (active: {active})",
    },
    "model.usage": {
        "tr": "Kullanım: /model claude|openai|gemini|ollama|grok  veya  /model key openai|gemini|grok API_KEY",
        "en": "Usage: /model claude|openai|gemini|ollama|grok  or  /model key openai|gemini|grok API_KEY",
    },
    "model.changed": {
        "tr": "Model değişti → [bold]{model}[/]",
        "en": "Model changed → [bold]{model}[/]",
    },

    # ── otonom ──
    "otonom.started": {
        "tr": (
            "[grey58]Otonom döngü başladı: fiyat kontrolü 2sn | "
            "pozisyon analizi 5dk | tarama 15dk (scalp modda 3dk).[/]"
        ),
        "en": (
            "[grey58]Autonomous loop started: price check 2s | "
            "position analysis 5min | scan 15min (3min in scalp mode).[/]"
        ),
    },

    # ── canlı (gerçek para) ──
    "live.header": {
        "tr": "[bold cyan]── GERÇEK PARA BAĞLANTISI (Binance) ──[/]",
        "en": "[bold cyan]── REAL-MONEY CONNECTION (Binance) ──[/]",
    },
    "live.status_off": {
        "tr": "Durum: [grey58]bağlı değil[/] — mod: PAPER (simülasyon).",
        "en": "Status: [grey58]not connected[/] — mode: PAPER (simulation).",
    },
    "live.status_on": {
        "tr": "Durum: [green3]BAĞLI[/]  |  Mod: {mode}  |  /canli mod live → gerçek emir  |  /canli bakiye → bakiye",
        "en": "Status: [green3]CONNECTED[/]  |  Mode: {mode}  |  /live mod live → real orders  |  /live bakiye → balance",
    },
    "live.validating": {
        "tr": "Anahtarlar Binance'te doğrulanıyor...",
        "en": "Validating keys with Binance...",
    },
    "live.connected": {
        "tr": "[green3]Bağlantı başarılı![/] Hesap doğrulandı, anahtarlar kaydedildi.",
        "en": "[green3]Connected![/] Account verified, keys saved.",
    },
    "live.failed": {
        "tr": "[red3]Bağlantı başarısız: {err}[/]",
        "en": "[red3]Connection failed: {err}[/]",
    },
    "live.disconnected": {
        "tr": "Binance anahtarları silindi — tamamen PAPER moduna dönüldü.",
        "en": "Binance keys removed — back to pure PAPER mode.",
    },
    "live.no_keys": {
        "tr": "Önce bağlan: /canli bagla API_KEY SECRET",
        "en": "Connect first: /live bagla API_KEY SECRET",
    },
    "live.balances": {
        "tr": "[bold]Gerçek Binance spot bakiyen:[/]",
        "en": "[bold]Your real Binance spot balance:[/]",
    },
    "live.usage": {
        "tr": "Alt komutlar: /canli bagla KEY SECRET  /canli mod live|paper  /canli bakiye  /canli kes",
        "en": "Subcommands: /live bagla KEY SECRET  /live mod live|paper  /live bakiye  /live kes",
    },
    "live.warning": {
        "tr": (
            "[dark_orange]⚠ Gerçek paraya geçmeden önce: paper hesapta en az birkaç hafta "
            "pozitif performans görmeni öneririm. Claude'un /performans karnesi bunun için var.[/]"
        ),
        "en": (
            "[dark_orange]⚠ Before going live: I recommend several weeks of positive paper "
            "performance first. That's what Claude's /report card is for.[/]"
        ),
    },

    # ── splash menü ──
    "splash.back": {
        "tr": "Ana menü için Enter",
        "en": "Press Enter for main menu",
    },
}
