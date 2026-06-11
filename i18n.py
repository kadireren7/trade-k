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
[bold cyan]Komutlar[/]
  [bold]/tara[/]                         → Claude tüm piyasayı tarar, AL adayları listeler
  [bold]/tara kripto|global|forex|emtia|endeks[/] → belirli piyasayı tara
  [bold]/durum[/]                        → açık pozisyonları Claude ile analiz et
  [bold]/onayla 1 3[/]                   → listeden seçtiğin adayları uygula
  [bold]/reddet[/]                       → bekleyen önerileri temizle
  [bold]/ai SEMBOL[/]                    → tek sembol analizi     örn: /ai altin
  [bold]/al SEMBOL TUTAR[/]              → manuel alım (stop/hedef otomatik)
  [bold]/sat SEMBOL \\[TUTAR][/]           → satış (tutar yoksa hepsi)
  [bold]/koru SEMBOL[/]                  → Claude stop/hedefi yeniden belirlesin
  [bold]/otonom ac[/]                    → otonom modu başlat
  [bold]/otonom kapat[/]                 → otonom modu durdur
  [bold]/otonom durum[/]                 → otonom mod istatistikleri
  [bold]/ekle SEMBOL[/]  [bold]/cikar SEMBOL[/]   → kripto izleme listesi (max 5)
  [bold]/model \\[isim][/]                → Claude modeli: opus / sonnet / haiku / varsayilan
  [bold]/canli[/]                        → Binance API bağlantısı durumu ve kurulum
  [bold]/performans[/]  [bold]/gecmis[/]  [bold]/sifirla[/]  [bold]q[/]=çıkış
[bold cyan]Otonom kurallar:[/] max 2 açık pozisyon | tek işlem max %10 nakit | günlük max 3 işlem
  min güven %55 | min R/R 1.5 | günlük zarar %2 → oto kapanır | 2 ardışık zarar → kilitlenir
[bold cyan]Kripto dışı:[/] altin, gumus, petrol, dogalgaz, bakir, eurusd, gbpusd, usdjpy,
  dolar(USD/TL), sp500, nasdaq, dow, dax, bist"""

_HELP_EN = """\
[bold cyan]Commands[/]
  [bold]/tara[/]                         → Claude scans the market, lists AL candidates
  [bold]/tara kripto|global|forex|emtia|endeks[/] → scan specific market
  [bold]/durum[/]                        → analyze open positions with Claude
  [bold]/onayla 1 3[/]                   → apply selected candidates
  [bold]/reddet[/]                       → clear pending suggestions
  [bold]/ai SYMBOL[/]                    → single symbol analysis    e.g. /ai gold
  [bold]/al SYMBOL AMOUNT[/]             → manual buy (stop/target auto)
  [bold]/sat SYMBOL \\[AMOUNT][/]          → sell (all if no amount)
  [bold]/koru SYMBOL[/]                  → let Claude re-set stop/target
  [bold]/otonom ac[/]                    → start autonomous mode
  [bold]/otonom kapat[/]                 → stop autonomous mode
  [bold]/otonom durum[/]                 → autonomous mode statistics
  [bold]/ekle SYMBOL[/]  [bold]/cikar SYMBOL[/]   → crypto watchlist (max 5)
  [bold]/model \\[name][/]                → Claude model: opus / sonnet / haiku / varsayilan
  [bold]/canli[/]                        → real-money connection (Binance API)
  [bold]/performans[/]  [bold]/gecmis[/]  [bold]/sifirla[/]  [bold]q[/]=quit
[bold cyan]Autonomous rules:[/] max 2 positions | single trade max 10% cash | daily max 3 trades
  min confidence 55% | min R/R 1.5 | daily loss 2% → auto-off | 2 consecutive losses → locked
[bold cyan]Non-crypto:[/] altin(gold), gumus(silver), petrol(oil), dogalgaz(natgas),
  bakir(copper), eurusd, gbpusd, usdjpy, dolar(USD/TRY), sp500, nasdaq, dow, dax, bist"""

_STRINGS: dict[str, dict[str, str]] = {
    "help": {"tr": _HELP_TR, "en": _HELP_EN},

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
        "en": "Type a command... (/yardim)",
    },

    "app.started": {
        "tr": "[bold gold3]trade-k[/] başlatıldı — hoş geldin [bold]{name}[/]! Sanal hesap, gerçek fiyatlar.",
        "en": "[bold gold3]trade-k[/] started — welcome [bold]{name}[/]! Paper account, real prices.",
    },
    "app.mode_model": {
        "tr": "Model: [bold]{model}[/]   (/model ile değiştir)  |  Otonom: /otonom ac",
        "en": "Model: [bold]{model}[/]   (change with /model)  |  Autonomous: /otonom ac",
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
        "tr": "Kullanım: /model opus|sonnet|haiku|varsayilan",
        "en": "Usage: /model opus|sonnet|haiku|varsayilan",
    },
    "model.changed": {
        "tr": "Model değişti → [bold]{model}[/]",
        "en": "Model changed → [bold]{model}[/]",
    },

    # ── otonom ──
    "otonom.started": {
        "tr": (
            "[grey58]Otonom döngü başladı: fiyat kontrolü 2sn | "
            "pozisyon analizi 5dk | tarama 15dk.[/]"
        ),
        "en": (
            "[grey58]Autonomous loop started: price check 2s | "
            "position analysis 5min | scan 15min.[/]"
        ),
    },

    # ── canlı (gerçek para) ──
    "live.header": {
        "tr": "[bold cyan]── GERÇEK PARA BAĞLANTISI (Binance) ──[/]",
        "en": "[bold cyan]── REAL-MONEY CONNECTION (Binance) ──[/]",
    },
    "live.status_off": {
        "tr": "Durum: [grey58]bağlı değil[/] — işlemler sanal hesapta (PAPER).",
        "en": "Status: [grey58]not connected[/] — trades run on the paper account.",
    },
    "live.status_on": {
        "tr": "Durum: [green3]BAĞLI[/] (API anahtarı doğrulandı) — emirler hâlâ PAPER, gerçek bakiyeni /canli bakiye ile görebilirsin.",
        "en": "Status: [green3]CONNECTED[/] (API key verified) — orders still PAPER; see real balance with /canli bakiye.",
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
        "en": "Connect first: /canli bagla API_KEY SECRET",
    },
    "live.balances": {
        "tr": "[bold]Gerçek Binance spot bakiyen:[/]",
        "en": "[bold]Your real Binance spot balance:[/]",
    },
    "live.usage": {
        "tr": "Alt komutlar: /canli  /canli bagla KEY SECRET  /canli bakiye  /canli kes",
        "en": "Subcommands: /canli  /canli bagla KEY SECRET  /canli bakiye  /canli kes",
    },
    "live.warning": {
        "tr": (
            "[dark_orange]⚠ Gerçek paraya geçmeden önce: paper hesapta en az birkaç hafta "
            "pozitif performans görmeni öneririm. Claude'un /performans karnesi bunun için var.[/]"
        ),
        "en": (
            "[dark_orange]⚠ Before going live: I recommend several weeks of positive paper "
            "performance first. That's what Claude's /performans report card is for.[/]"
        ),
    },
}
