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
  [bold]/uygula SEMBOL[/]               → /durum kararını uygula (stop güncelle / kâr al / kes)
  [bold]/uygula hepsi[/]               → tüm bekleyen /durum kararlarını uygula
  [bold]/onayla 1 3[/]                  → /tara adaylarını uygula
  [bold]/reddet[/]                      → bekleyen /tara önerilerini temizle
  [bold]/ai SEMBOL[/]                   → tek sembol derin analiz   örn: /ai altin
[bold cyan]İşlem (Paper)[/]
  [bold]/al SEMBOL TUTAR[/]             → Spot Long paper alım   (stop/hedef otomatik)
  [bold]/sat SEMBOL \\[TUTAR][/]          → Sat (tutar yoksa hepsi)
  [bold]/short SEMBOL TUTAR[/]          → Short paper (yalnızca realtime kripto)
  [bold]/scalp SEMBOL TUTAR[/]          → Scalp paper (max 30dk, fee/slippage dahil)
  [bold]/koru SEMBOL[/]                 → Claude stop/hedefi yeniden belirlesin
[bold cyan]Scalp[/]
  [bold]/scalp ac[/]  [bold]/scalp kapat[/]  [bold]/scalp durum[/]
[bold cyan]Kaldıraç (Paper)[/]
  [bold]/kaldirac ac[/]  [bold]/kaldirac kapat[/]  [bold]/kaldirac durum[/]
  [bold yellow3]⚠ Yalnızca PAPER — gerçek kaldıraçlı emir HİÇBİR ZAMAN gönderilmez.[/]
[bold cyan]Otonom[/]
  [bold]/otonom ac[/]  [bold]/otonom kapat[/]  [bold]/otonom durum[/]
  [bold]/otonom mod[/]  [bold]/otonom mod guvenli|dengeli|agresif[/]
  [bold]/otonom ayar max_islem|max_pozisyon|zarar_serisi|gunluk_zarar N[/]
[bold cyan]Diğer[/]
  [bold]/ekle SEMBOL[/]  [bold]/cikar SEMBOL[/]  → kripto izleme listesi (max 5)
  [bold]/detay SEMBOL[/]               → veri kalitesi + kaldıraç izin bilgisi
  [bold]/model \\[opus|sonnet|haiku][/]  → Claude modelini değiştir
  [bold]/canli[/]                       → Binance API bağlantısı
  [bold]/rapor[/]  [bold]/gecmis[/]  [bold]/sifirla[/]  [bold]/ayarlar[/]  [bold]q[/]=çıkış
[bold cyan]Not:[/] Otonom mod yalnızca PAPER işlem açar — live bağlantı olsa dahi gerçek emir gönderilmez."""

_HELP_EN = """\
[bold cyan]Analysis[/]
  [bold]/scan[/]  [bold]/scan crypto|global|forex|commodity|index[/]  → Claude scans for opportunities
  [bold]/scan long|short|scalp|day|swing|leverage[/]  → filter by trade type
  [bold]/status[/]                       → analyze open positions with Claude
  [bold]/apply SYMBOL[/]                 → apply /status decision (stop update / take profit / cut)
  [bold]/apply all[/]                    → apply all pending decisions
  [bold]/approve 1 3[/]                  → execute /scan candidates
  [bold]/reject[/]                       → clear pending /scan suggestions
  [bold]/ai SYMBOL[/]                    → single symbol deep-dive   e.g. /ai gold
[bold cyan]Trade (Paper)[/]
  [bold]/buy SYMBOL AMOUNT[/]            → Spot Long paper buy   (stop/target auto)
  [bold]/sell SYMBOL \\[AMOUNT][/]         → Sell position (all if no amount)
  [bold]/short SYMBOL AMOUNT[/]          → Short paper (realtime crypto only)
  [bold]/scalp SYMBOL AMOUNT[/]          → Scalp paper (max 30min, fee/slippage simulated)
  [bold]/protect SYMBOL[/]              → Let Claude re-set stop/target
[bold cyan]Scalp[/]
  [bold]/scalp on[/]  [bold]/scalp off[/]  [bold]/scalp status[/]
[bold cyan]Leverage (Paper)[/]
  [bold]/leverage on[/]  [bold]/leverage off[/]  [bold]/leverage status[/]
  [bold yellow3]⚠ PAPER only — real leveraged orders are NEVER sent.[/]
[bold cyan]Autonomous[/]
  [bold]/auto on[/]  [bold]/auto off[/]  [bold]/auto status[/]
  [bold]/auto mode[/]  [bold]/auto mode safe|balanced|aggressive[/]
  [bold]/auto set max_trades|max_positions|loss_streak|daily_loss N[/]
[bold cyan]Other[/]
  [bold]/add SYMBOL[/]  [bold]/remove SYMBOL[/]  → crypto watchlist (max 5)
  [bold]/details SYMBOL[/]              → data quality + leverage eligibility
  [bold]/model \\[opus|sonnet|haiku][/]   → change Claude model
  [bold]/live[/]                        → Binance API connection
  [bold]/report[/]  [bold]/history[/]  [bold]/reset[/]  [bold]/settings[/]  [bold]q[/]=quit
[bold cyan]Note:[/] Autonomous mode is PAPER-only — no real orders even with live connection."""

_STRINGS: dict[str, dict[str, str]] = {
    "help": {"tr": _HELP_TR, "en": _HELP_EN},

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
        "en": "Status: [green3]CONNECTED[/] (API key verified) — orders still PAPER; see real balance with /live bakiye.",
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
        "tr": "Alt komutlar: /canli  /canli bagla KEY SECRET  /canli bakiye  /canli kes",
        "en": "Subcommands: /live  /live bagla KEY SECRET  /live bakiye  /live kes",
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
