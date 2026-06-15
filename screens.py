"""Açılış ekranları — ilk kurulum sihirbazı, şifreli giriş ve menü sistemi.

SetupScreen: dil → isim → şifre (x2) → model. Sonuç: kayıtlı Config.
LoginScreen: şifre sorar; 3 yanlışta False döner (app kapanır).
SplashMenuScreen: giriş sonrası ana menü (ListView tabanlı).
SettingsScreen, RiskLimitsScreen, AutonomousControlScreen, ConnectionsScreen,
MarketDataScreen, ReportsScreen ve diğer alt ekranlar.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Middle, Vertical, ScrollableContainer
from textual.screen import Screen
from textual.widgets import Input, Label, ListItem, ListView, Static

import i18n
from config import MODELS, MIN_PW_LEN, Config
from i18n import t

if TYPE_CHECKING:
    pass  # Config already imported above

_MODEL_ORDER = ["opus", "sonnet", "haiku", "varsayilan"]


# ── Logo ──────────────────────────────────────────────────────────────────────

SPLASH_LOGO = """\
 ████████╗██████╗  █████╗ ██████╗ ███████╗    ██╗  ██╗
 ╚══██╔══╝██╔══██╗██╔══██╗██╔══██╗██╔════╝    ██║ ██╔╝
    ██║   ██████╔╝███████║██║  ██║█████╗      █████╔╝
    ██║   ██╔══██╗██╔══██║██║  ██║██╔══╝      ██╔═██╗
    ██║   ██║  ██║██║  ██║██████╔╝███████╗    ██║  ██╗
    ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═════╝ ╚══════╝    ╚═╝  ╚═╝
                   Claude destekli trading terminali"""


# ── Helper ────────────────────────────────────────────────────────────────────

def _build_status_chips(cfg: Config) -> str:
    """Status chip satırı - Rich markup string döner."""
    binance_on = bool(cfg.binance_key)
    is_live = binance_on and getattr(cfg, "trading_mode", "paper") == "live"
    lang_str = "TR" if cfg.language == "tr" else "EN"
    provider = getattr(cfg, "ai_provider", "claude")
    _pmodel = {
        "claude": cfg.model.upper(),
        "openai": getattr(cfg, "openai_model", "gpt-4o").upper(),
        "gemini": getattr(cfg, "gemini_model", "gemini-2.0-flash").replace("gemini-", "").upper(),
        "ollama": getattr(cfg, "ollama_model", "llama3.2").upper(),
        "grok": getattr(cfg, "grok_model", "grok-3-mini").upper(),
    }.get(provider, provider.upper())
    ai_label = f"{provider.upper()}:{_pmodel}"
    ai_ok = shutil.which("claude") is not None if provider == "claude" else bool(
        getattr(cfg, f"{provider}_api_key", "") or provider == "ollama"
    )
    parts = [
        ("[bold black on green3] ⚡ LIVE [/]" if is_live
         else "[bold white on dark_orange] ◈ PAPER [/]"),
        (f"[bold black on green3] ✔ {ai_label} [/]" if ai_ok
         else f"[bold white on red3] ✕ {ai_label}:YOK [/]"),
        (f"[bold black on green3] ✔ BİNANCE:BAĞLI [/]" if binance_on
         else "[bold white on red3] ✕ BİNANCE:BAĞ­LANMADI [/]"),
        f"[bold white on grey35] {lang_str} [/]",
    ]
    return "  ".join(parts)


# ── Auth base (kurulum & giriş için) ─────────────────────────────────────────

class _AuthScreen(Screen):
    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title

    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                with Vertical(id="authbox"):
                    yield Static(self._title, id="authtitle")
                    yield Static("", id="authbody")
                    yield Static("", id="autherr")
                    yield Input(id="authinput")

    def on_mount(self) -> None:
        self.query_one("#authinput", Input).focus()

    def set_body(self, text: str) -> None:
        self.query_one("#authbody", Static).update(text)

    def set_error(self, text: str) -> None:
        self.query_one("#autherr", Static).update(text)

    def set_secret(self, secret: bool) -> None:
        self.query_one("#authinput", Input).password = secret

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Base: event.stop() to prevent bubbling up to TradeApp."""
        event.stop()


# ── SetupScreen ───────────────────────────────────────────────────────────────

class SetupScreen(_AuthScreen):
    """İlk açılış sihirbazı: dil → isim → şifre × 2 → model."""

    def __init__(self) -> None:
        super().__init__(t("setup.title"))
        self.cfg = Config()
        self.step = "lang"
        self._pw1 = ""

    def on_mount(self) -> None:
        super().on_mount()
        self.set_body(t("setup.lang"))

    def _model_menu(self) -> str:
        lines = []
        for i, key in enumerate(_MODEL_ORDER, 1):
            _, tr, en = MODELS[key]
            desc = tr if i18n.lang() == "tr" else en
            lines.append(f"  [bold]{i}[/]) {desc}")
        return "\n".join(lines) + "\n"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        value = event.value.strip()
        event.input.value = ""
        self.set_error("")

        if self.step == "lang":
            if value not in ("1", "2"):
                self.set_error(t("setup.invalid"))
                return
            self.cfg.language = "tr" if value == "1" else "en"
            i18n.set_language(self.cfg.language)
            self.step = "name"
            self.set_body(t("setup.name"))

        elif self.step == "name":
            if len(value) < 2:
                self.set_error(t("setup.name_short"))
                return
            self.cfg.name = value
            self.step = "pw"
            self.set_secret(True)
            self.set_body(t("setup.pw"))

        elif self.step == "pw":
            if len(value) < MIN_PW_LEN:
                self.set_error(t("setup.pw_short"))
                return
            self._pw1 = value
            self.step = "pw2"
            self.set_body(t("setup.pw2"))

        elif self.step == "pw2":
            if value != self._pw1:
                self.step = "pw"
                self.set_body(t("setup.pw"))
                self.set_error(t("setup.pw_mismatch"))
                return
            self.cfg.set_password(self._pw1)
            self._pw1 = ""
            self.step = "model"
            self.set_secret(False)
            self.set_body(
                t("setup.model",
                  models=self._model_menu(),
                  n=len(_MODEL_ORDER))
            )

        elif self.step == "model":
            if value not in [str(i) for i in range(1, len(_MODEL_ORDER) + 1)]:
                self.set_error(t("setup.invalid"))
                return
            self.cfg.model = _MODEL_ORDER[int(value) - 1]
            self.cfg.mode = "standart"  # tek mod
            self.cfg.save()
            self.dismiss(self.cfg)


# ── LoginScreen ───────────────────────────────────────────────────────────────

class LoginScreen(_AuthScreen):
    """Sonraki açılışlar: şifre doğrulama, 3 deneme hakkı."""

    MAX_ATTEMPTS = 3

    def __init__(self, cfg: Config) -> None:
        super().__init__(t("login.title"))
        self.cfg = cfg
        self.attempts = 0

    def on_mount(self) -> None:
        super().on_mount()
        self.set_secret(True)
        self.set_body(t("login.prompt", name=self.cfg.name))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        value = event.value
        event.input.value = ""
        if self.cfg.verify_password(value):
            self.dismiss(True)
            return
        self.attempts += 1
        left = self.MAX_ATTEMPTS - self.attempts
        if left <= 0:
            self.set_error(t("login.locked"))
            self.set_body("")
            self.query_one("#authinput", Input).disabled = True
            self.set_timer(1.2, self._locked_close)
        else:
            self.set_error(t("login.wrong", n=left))

    def _locked_close(self) -> None:
        self.dismiss(False)


# ── _MenuScreen (tüm menü ekranları için temel) ───────────────────────────────

class _MenuScreen(Screen):
    """ListView tabanlı menü ekranları için temel sınıf."""

    BINDINGS = [
        Binding("escape", "go_back", "Geri", show=False),
        Binding("q", "go_back", "Geri", show=False),
    ]

    def action_go_back(self) -> None:
        self.dismiss(None)

    def action_quit_app(self) -> None:
        self.dismiss("exit")

    @staticmethod
    def _item(text: str) -> ListItem:
        return ListItem(Label(text))

    def _safe_update(self, widget_id: str, text: str) -> None:
        try:
            self.query_one(f"#{widget_id}", Static).update(text)
        except Exception:
            pass

    def _flash_msg(self, widget_id: str, text: str, delay: float = 3.0) -> None:
        self._safe_update(widget_id, text)
        self.set_timer(delay, lambda: self._safe_update(widget_id, ""))

    def _reload_list(self, list_id: str, items: list[str]) -> None:
        try:
            lv = self.query_one(f"#{list_id}", ListView)
            lv.clear()
            for item in items:
                lv.append(self._item(item))
        except Exception:
            pass


# ── ConfirmScreen ─────────────────────────────────────────────────────────────

class ConfirmScreen(_AuthScreen):
    def __init__(self, title: str, message: str) -> None:
        super().__init__(title)
        self._message = message

    def on_mount(self) -> None:
        super().on_mount()
        lang = i18n.lang()
        hint = "\n[grey58]Enter: onayla   Esc: iptal[/]" if lang == "tr" else "\n[grey58]Enter: confirm   Esc: cancel[/]"
        self.set_body(self._message + hint)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        event.input.value = ""
        self.dismiss(True)

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            self.dismiss(False)


# ── SplashMenuScreen ──────────────────────────────────────────────────────────

class SplashMenuScreen(_MenuScreen):
    BINDINGS = [
        Binding("q", "quit_app", "Çıkış", show=False),
        Binding("1", "select_1", show=False),
        Binding("2", "select_2", show=False),
        Binding("3", "select_3", show=False),
        Binding("4", "select_4", show=False),
        Binding("5", "select_5", show=False),
        Binding("6", "select_6", show=False),
        Binding("7", "select_7", show=False),
        Binding("8", "select_8", show=False),
        Binding("9", "select_9", show=False),
    ]

    def __init__(self, cfg: Config, portfolio_summary: str = "") -> None:
        super().__init__()
        self._cfg = cfg
        self._portfolio_summary = portfolio_summary

    def _ex_label(self) -> str:
        """Aktif borsanın bağlantı durumunu dinamik göster."""
        cfg = self._cfg
        ex = getattr(cfg, "exchange", "binance")
        mode = getattr(cfg, "trading_mode", "paper")
        if ex == "binance":
            on = bool(cfg.binance_key)
        elif ex == "bybit":
            on = bool(getattr(cfg, "bybit_key", ""))
        elif ex == "okx":
            on = bool(getattr(cfg, "okx_key", ""))
        else:
            on = False
        status = "✔ BAĞLI" if on else "✗ BAĞLANMADI"
        return f"{ex.upper()} · {status} · {mode.upper()}"

    def _ai_label(self) -> str:
        cfg = self._cfg
        provider = getattr(cfg, "ai_provider", "claude")
        model = getattr(cfg, "model", "sonnet")
        return f"{provider.upper()} · {model}"

    def _auto_label(self) -> str:
        from pathlib import Path as _P
        import json as _j
        try:
            st = _j.loads((_P(__file__).parent / "autonomous_state.json").read_text())
            enabled = st.get("enabled", False)
            mode = getattr(self._cfg, "autonomous_mode", "dengeli")
            return ("AÇIK · " if enabled else "KAPALI · ") + mode
        except Exception:
            return "KAPALI"

    def _menu_items(self) -> list[str]:
        lang = i18n.lang()
        cfg = self._cfg
        ex_label   = self._ex_label()
        ai_label   = self._ai_label()
        auto_label = self._auto_label()
        lev   = "AÇIK" if cfg.leverage_enabled else "KAPALI"
        scalp = "AÇIK" if cfg.scalp_enabled else "KAPALI"
        strat = getattr(cfg, "active_strategy", "konsensüs")
        theme = getattr(cfg, "theme", "cyber")

        if lang == "tr":
            return [
                f"  1.  Trading Terminali           [komutlar · işlemler · alarmlar]",
                f"  2.  Otonom AI Modu              [{auto_label}]",
                f"  3.  Backtest & Teknik Analiz    [walk-forward · Monte Carlo · TA]",
                f"  4.  Piyasa & İzleme             [fiyatlar · haberler · tarama]",
                f"  5.  Bağlantılar & API           [{ex_label}]",
                f"  6.  AI & Strateji               [{ai_label} · {strat}]",
                f"  7.  Ayarlar                     [tema:{theme} · scalp:{scalp} · lev:{lev}]",
                f"  8.  Raporlar & Performans       [Sharpe · Sortino · PnL · geçmiş]",
                f"  9.  Çıkış",
            ]
        return [
            f"  1.  Trading Terminal            [commands · trades · alerts]",
            f"  2.  Autonomous AI Mode          [{auto_label}]",
            f"  3.  Backtest & Technical Anal.  [walk-forward · Monte Carlo · TA]",
            f"  4.  Market & Watchlist          [prices · news · scan]",
            f"  5.  Connections & API           [{ex_label}]",
            f"  6.  AI & Strategy               [{ai_label} · {strat}]",
            f"  7.  Settings                    [theme:{theme} · scalp:{scalp} · lev:{lev}]",
            f"  8.  Reports & Performance       [Sharpe · Sortino · PnL · history]",
            f"  9.  Exit",
        ]

    def _tip_line(self) -> str:
        cfg = self._cfg
        lang = i18n.lang()
        ex = getattr(cfg, "exchange", "binance")
        mode = getattr(cfg, "trading_mode", "paper")
        if ex == "binance":
            on = bool(cfg.binance_key)
        elif ex == "bybit":
            on = bool(getattr(cfg, "bybit_key", ""))
        elif ex == "okx":
            on = bool(getattr(cfg, "okx_key", ""))
        else:
            on = False

        if lang == "tr":
            if not on:
                return (f"  [dark_orange]→ {ex.upper()} bağlantısı yok. "
                        "Menü 5 → API Key gir → Trading modunu seç.[/]")
            return (f"  [green3]→ {ex.upper()} bağlı · Mod: {mode.upper()}[/]  "
                    "[grey58]Borsa/mod için Menü 5.[/]")
        if not on:
            return (f"  [dark_orange]→ {ex.upper()} not connected. "
                    "Menu 5 → Enter API Key → Choose mode.[/]")
        return (f"  [green3]→ {ex.upper()} connected · Mode: {mode.upper()}[/]  "
                "[grey58]Exchange/mode in Menu 5.[/]")

    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        cfg = self._cfg
        welcome = (f"  Hoş geldin, {cfg.name}!" if lang == "tr"
                   else f"  Welcome, {cfg.name}!")
        hint = ("  ↑↓ seç   Enter aç   1-9 hızlı   Q çıkış" if lang == "tr"
                else "  ↑↓ select   Enter open   1-9 quick   Q quit")
        with Middle():
            with Center():
                with Vertical(id="splash-box"):
                    yield Static(SPLASH_LOGO, id="splash-logo")
                    yield Static(_build_status_chips(cfg), id="splash-chips")
                    yield Static(welcome, id="splash-welcome")
                    yield Static(self._tip_line(), id="splash-tip")
                    yield ListView(*[self._item(i) for i in self._menu_items()], id="splash-menu")
                    yield Static(hint, id="splash-hint")

    def on_mount(self) -> None:
        self.query_one("#splash-menu", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self._open_item((event.list_view.index or 0) + 1)

    def _open_item(self, n: int) -> None:
        if n == 1:
            self.dismiss("trade")
        elif n == 2:
            self.app.push_screen(AutonomousControlScreen(self._cfg), self._on_sub)
        elif n == 3:
            self.app.push_screen(AnalysisScreen(), self._on_sub)
        elif n == 4:
            self.app.push_screen(MarketDataScreen(self._cfg, self._portfolio_summary), self._on_sub)
        elif n == 5:
            self.app.push_screen(ConnectionsScreen(self._cfg), self._on_sub)
        elif n == 6:
            self.app.push_screen(ConnectionsScreen(self._cfg), self._on_sub)
        elif n == 7:
            self.app.push_screen(SettingsScreen(self._cfg), self._on_sub)
        elif n == 8:
            self.app.push_screen(ReportsScreen(self._cfg, self._portfolio_summary), self._on_sub)
        elif n == 9:
            self.dismiss("exit")

    def _on_sub(self, result) -> None:
        if result == "exit":
            self.dismiss("exit")
            return
        if result == "auto_start":
            self.dismiss("auto_start")
            return
        try:
            self.query_one("#splash-chips", Static).update(_build_status_chips(self._cfg))
        except Exception:
            pass
        try:
            self._reload_list("splash-menu", self._menu_items())
        except Exception:
            pass
        try:
            self.query_one("#splash-tip", Static).update(self._tip_line())
        except Exception:
            pass

    def action_go_back(self) -> None:
        self.dismiss("exit")

    def action_quit_app(self) -> None:
        self.dismiss("exit")

    def action_select_1(self) -> None:
        self._open_item(1)

    def action_select_2(self) -> None:
        self._open_item(2)

    def action_select_3(self) -> None:
        self._open_item(3)

    def action_select_4(self) -> None:
        self._open_item(4)

    def action_select_5(self) -> None:
        self._open_item(5)

    def action_select_6(self) -> None:
        self._open_item(6)

    def action_select_7(self) -> None:
        self._open_item(7)

    def action_select_8(self) -> None:
        self._open_item(8)

    def action_select_9(self) -> None:
        self._open_item(9)


# ── SettingsScreen ────────────────────────────────────────────────────────────

class SettingsScreen(_MenuScreen):
    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self._cfg = cfg

    def _items(self) -> list[str]:
        lang = i18n.lang()
        cfg = self._cfg
        lev = ("AÇIK" if lang == "tr" else "ON") if cfg.leverage_enabled else ("KAPALI" if lang == "tr" else "OFF")
        scalp = ("AÇIK" if lang == "tr" else "ON") if cfg.scalp_enabled else ("KAPALI" if lang == "tr" else "OFF")
        lang_disp = "[TR] Türkçe" if cfg.language == "tr" else "[EN] English"
        theme = getattr(cfg, "theme", "cyber")
        if lang == "tr":
            return [
                f"  Dil / Language              [{lang_disp}]",
                f"  Tema / Theme                [{theme}]",
                f"  Claude Modeli               [{cfg.model}]",
                f"  Scalp Paper                 [{scalp}]",
                f"  Kaldıraç Paper              [{lev}]",
                f"  Otonom Mod                  [{cfg.autonomous_mode}]",
                "  Risk Limitleri              →",
                "  Paper Hesabı Sıfırla        →",
                "  Performans Sıfırla          →",
                "  ← Geri",
            ]
        return [
            f"  Language / Dil              [{lang_disp}]",
            f"  Theme                       [{theme}]",
            f"  Claude Model                [{cfg.model}]",
            f"  Scalp Paper                 [{scalp}]",
            f"  Leverage Paper              [{lev}]",
            f"  Autonomous Mode             [{cfg.autonomous_mode}]",
            "  Risk Limits                 →",
            "  Reset Paper Account         →",
            "  Reset Performance History   →",
            "  ← Back",
        ]

    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = "──  AYARLAR  ──" if lang == "tr" else "──  SETTINGS  ──"
        hint = "↑↓ seç   Enter değiştir/aç   Esc geri" if lang == "tr" else "↑↓ select   Enter toggle/open   Esc back"
        with Middle():
            with Center():
                with Vertical(id="settings-box"):
                    yield Static(title, id="settings-title")
                    yield Static("", id="settings-msg")
                    yield ListView(*[self._item(i) for i in self._items()], id="settings-list")
                    yield Static(hint, id="settings-hint")

    def on_mount(self) -> None:
        self.query_one("#settings-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self._handle(event.list_view.index or 0)

    def _handle(self, idx: int) -> None:
        lang = i18n.lang()
        cfg = self._cfg
        if idx == 0:  # Language
            cfg.language = "en" if cfg.language == "tr" else "tr"
            i18n.set_language(cfg.language)
            cfg.save()
            self._flash_msg("settings-msg", f"✓ Dil: {cfg.language.upper()}")
            self._reload_list("settings-list", self._items())
        elif idx == 1:  # Theme
            themes = ["cyber", "minimal", "matrix", "amber"]
            cur = getattr(cfg, "theme", "cyber")
            cfg.theme = themes[(themes.index(cur) + 1) % len(themes)] if cur in themes else "cyber"
            cfg.save()
            self._flash_msg("settings-msg", f"✓ Theme: {cfg.theme}")
            self._reload_list("settings-list", self._items())
        elif idx == 2:  # Model
            mc = ["sonnet", "opus", "haiku", "varsayilan"]
            cur = cfg.model if cfg.model in mc else "sonnet"
            cfg.model = mc[(mc.index(cur) + 1) % len(mc)]
            cfg.save()
            self._flash_msg("settings-msg", f"✓ Claude: {cfg.model}")
            self._reload_list("settings-list", self._items())
        elif idx == 3:  # Scalp
            cfg.scalp_enabled = not cfg.scalp_enabled
            cfg.save()
            st = ("AÇIK" if lang == "tr" else "ON") if cfg.scalp_enabled else ("KAPALI" if lang == "tr" else "OFF")
            self._flash_msg("settings-msg", f"✓ Scalp: {st}")
            self._reload_list("settings-list", self._items())
        elif idx == 4:  # Leverage
            cfg.leverage_enabled = not cfg.leverage_enabled
            cfg.save()
            st = ("AÇIK" if lang == "tr" else "ON") if cfg.leverage_enabled else ("KAPALI" if lang == "tr" else "OFF")
            self._flash_msg("settings-msg", f"✓ Kaldıraç: {st}")
            self._reload_list("settings-list", self._items())
        elif idx == 5:  # Auto mode
            mc = ["guvenli", "dengeli", "agresif"]
            cur = cfg.autonomous_mode if cfg.autonomous_mode in mc else "dengeli"
            cfg.autonomous_mode = mc[(mc.index(cur) + 1) % len(mc)]
            cfg.save()
            self._flash_msg("settings-msg", f"✓ Otonom: {cfg.autonomous_mode}")
            self._reload_list("settings-list", self._items())
        elif idx == 6:  # Risk limits
            self.app.push_screen(RiskLimitsScreen(self._cfg), self._on_sub)
        elif idx == 7:  # Reset paper
            title = "Paper Hesabı Sıfırla" if lang == "tr" else "Reset Paper Account"
            msg = ("Tüm pozisyonlar ve işlem geçmişi silinecek. Geri alınamaz!"
                   if lang == "tr" else "All positions and trade history will be deleted. Irreversible!")
            self.app.push_screen(ConfirmScreen(title, msg), self._on_reset_paper)
        elif idx == 8:  # Reset perf
            title = "Performans Sıfırla" if lang == "tr" else "Reset Performance"
            msg = ("Tüm öneri geçmişi silinecek." if lang == "tr"
                   else "All recommendation history will be deleted.")
            self.app.push_screen(ConfirmScreen(title, msg), self._on_reset_perf)
        elif idx == 9:  # Back
            self.dismiss(None)

    def _on_reset_paper(self, confirmed: bool) -> None:
        if confirmed:
            p = Path(__file__).parent / "account.json"
            if p.exists():
                p.unlink()
            lang = i18n.lang()
            self._flash_msg("settings-msg", "✓ Paper hesap sıfırlandı." if lang == "tr" else "✓ Paper account reset.")

    def _on_reset_perf(self, confirmed: bool) -> None:
        if confirmed:
            p = Path(__file__).parent / "recommendations.json"
            if p.exists():
                p.unlink()
            lang = i18n.lang()
            self._flash_msg("settings-msg", "✓ Performans sıfırlandı." if lang == "tr" else "✓ Performance reset.")

    def _on_sub(self, result) -> None:
        if result == "exit":
            self.dismiss("exit")
            return
        self._reload_list("settings-list", self._items())

    def action_go_back(self) -> None:
        self.dismiss(None)


# ── RiskLimitsScreen ──────────────────────────────────────────────────────────

class RiskLimitsScreen(_MenuScreen):
    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self._cfg = cfg
        self._editing_field: int = -1

    def _items(self) -> list[str]:
        lang = i18n.lang()
        cfg = self._cfg
        mp = cfg.custom_max_positions or ("—" if lang == "tr" else "—")
        mt = cfg.custom_max_daily_trades or "—"
        ml = cfg.custom_loss_streak or "—"
        md = cfg.custom_daily_loss_pct or "—"
        if lang == "tr":
            return [
                f"  Max Açık Pozisyon         [{mp}]  (0=profil varsayılanı)",
                f"  Max Günlük İşlem          [{mt}]",
                f"  Max Ardışık Zarar         [{ml}]",
                f"  Max Günlük Zarar %        [{md}]",
                "  Özel Ayarları Temizle",
                "  ← Geri",
            ]
        return [
            f"  Max Open Positions        [{mp}]  (0=profile default)",
            f"  Max Daily Trades          [{mt}]",
            f"  Max Loss Streak           [{ml}]",
            f"  Max Daily Loss %          [{md}]",
            "  Clear Custom Settings",
            "  ← Back",
        ]

    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = "──  RİSK LİMİTLERİ  ──" if lang == "tr" else "──  RISK LIMITS  ──"
        with Middle():
            with Center():
                with Vertical(id="risk-box"):
                    yield Static(title, id="risk-title")
                    yield Static("", id="risk-msg")
                    yield ListView(*[self._item(i) for i in self._items()], id="risk-list")
                    yield Input(id="risk-input", placeholder="sayı gir (0=varsayılan)...", classes="hidden")
                    hint = "↑↓ seç   Enter düzenle   Esc geri" if lang == "tr" else "↑↓ select   Enter edit   Esc back"
                    yield Static(hint, id="risk-hint")

    def on_mount(self) -> None:
        self.query_one("#risk-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index or 0
        lang = i18n.lang()
        if idx == 4:  # Clear
            self._cfg.custom_max_positions = 0
            self._cfg.custom_max_daily_trades = 0
            self._cfg.custom_loss_streak = 0
            self._cfg.custom_daily_loss_pct = 0.0
            self._cfg.save()
            self._flash_msg("risk-msg", "✓ Temizlendi." if lang == "tr" else "✓ Cleared.")
            self._reload_list("risk-list", self._items())
        elif idx == 5:
            self.dismiss(None)
        else:
            self._editing_field = idx
            inp = self.query_one("#risk-input", Input)
            cur = [
                str(self._cfg.custom_max_positions),
                str(self._cfg.custom_max_daily_trades),
                str(self._cfg.custom_loss_streak),
                str(self._cfg.custom_daily_loss_pct),
            ][idx]
            inp.value = cur
            inp.remove_class("hidden")
            inp.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        val = event.value.strip()
        event.input.value = ""
        event.input.add_class("hidden")
        lang = i18n.lang()
        try:
            n = float(val)
            if self._editing_field == 0:
                self._cfg.custom_max_positions = int(n)
            elif self._editing_field == 1:
                self._cfg.custom_max_daily_trades = int(n)
            elif self._editing_field == 2:
                self._cfg.custom_loss_streak = int(n)
            elif self._editing_field == 3:
                if n < 0 or n > 20:
                    raise ValueError("out of range")
                self._cfg.custom_daily_loss_pct = n
            self._cfg.save()
            self._flash_msg("risk-msg", "✓ Kaydedildi." if lang == "tr" else "✓ Saved.")
            self._reload_list("risk-list", self._items())
        except ValueError:
            self._flash_msg("risk-msg", "✗ Geçersiz değer." if lang == "tr" else "✗ Invalid value.")
        self._editing_field = -1
        try:
            self.query_one("#risk-list", ListView).focus()
        except Exception:
            pass

    def on_key(self, event) -> None:
        if event.key == "escape":
            if self._editing_field >= 0:
                event.stop()
                self._editing_field = -1
                try:
                    inp = self.query_one("#risk-input", Input)
                    inp.value = ""
                    inp.add_class("hidden")
                    self.query_one("#risk-list", ListView).focus()
                except Exception:
                    pass
            else:
                self.dismiss(None)

    def action_go_back(self) -> None:
        self.dismiss(None)


# ── AutonomousSetupScreen ─────────────────────────────────────────────────────

class AutonomousSetupScreen(_AuthScreen):
    """Otonom mod başlatmadan önce adım adım ayar sihirbazı."""

    _STEPS = ["welcome", "plan", "mode", "confirm"]

    def __init__(self, cfg: Config) -> None:
        lang = i18n.lang()
        title = "  ⚙  OTONOM MOD KURULUM  ⚙  " if lang == "tr" else "  ⚙  AUTONOMOUS MODE SETUP  ⚙  "
        super().__init__(title)
        self._cfg = cfg
        self._step = "welcome"
        self._data: dict = {
            "mode": cfg.autonomous_mode,
            "plan": getattr(cfg, "trade_plan", "dengeli"),
            "scalp": cfg.scalp_enabled,
            "leverage": cfg.leverage_enabled,
        }

    def on_mount(self) -> None:
        super().on_mount()
        self._show_step()

    def _show_step(self) -> None:
        lang = i18n.lang()
        step = self._step
        cur_mode = self._data["mode"]

        if step == "welcome":
            is_live = bool(
                getattr(self._cfg, "live_autonomous", False)
                and getattr(self._cfg, "trading_mode", "paper") == "live"
                and self._cfg.binance_key
            )
            if lang == "tr":
                mode_line = (
                    "[bold white on red3]  ⚡ LIVE AUTONOMOUS — GERÇEK EMİR GÖNDERİLECEK  ![/]\n"
                    "[grey58]/canli mod paper ile paper moduna dönebilirsin.[/]\n"
                    if is_live else
                    "[bold white on dark_orange]  ◈ PAPER MOD — TÜM İŞLEMLER SANAL  [/]\n"
                    "[grey58]Gerçek emir için: /canli mod live[/]\n"
                )
                self.set_body(
                    f"{mode_line}\n"
                    "Otonom mod Claude AI kullanarak kripto piyasasını tarar ve\n"
                    "otomatik olarak işlem açıp kapatır.\n\n"
                    "[grey58]Devam: Enter   İptal: Esc[/]"
                )
            else:
                mode_line = (
                    "[bold white on red3]  ⚡ LIVE AUTONOMOUS — REAL ORDERS WILL BE SENT  ![/]\n"
                    "[grey58]Use /live mod paper to switch back to paper mode.[/]\n"
                    if is_live else
                    "[bold white on dark_orange]  ◈ PAPER MODE — ALL TRADES ARE SIMULATED  [/]\n"
                    "[grey58]For real orders: /live mod live[/]\n"
                )
                self.set_body(
                    f"{mode_line}\n"
                    "Autonomous mode uses Claude AI to scan crypto markets and\n"
                    "automatically open and close positions.\n\n"
                    "[grey58]Continue: Enter   Cancel: Esc[/]"
                )

        elif step == "plan":
            cur_plan = self._data["plan"]
            plans = ["sadece_long", "dengeli", "tam"]
            if lang == "tr":
                labels = {
                    "sadece_long": "Sadece Long",
                    "dengeli": "Dengeli",
                    "tam": "Tam",
                }
                descs = {
                    "sadece_long": "Sadece spot AL  •  Short/scalp/leverage KAPALI",
                    "dengeli": "Long + Short + Scalp  •  Leverage KAPALI  ★ önerilen",
                    "tam":    "Her şey: Long + Short + Scalp + Leverage (ayrıca açılmalı)",
                }
                header = "[bold]Trade Planı Seç:[/]\n"
                header += "[grey58](Bu plan Claude'un ne tür işlem önereceğini belirler)[/]\n\n"
                footer = "\n\n[grey58]1/2/3 gir veya Enter = mevcut koru[/]"
            else:
                labels = {
                    "sadece_long": "Long Only",
                    "dengeli": "Balanced",
                    "tam": "Full",
                }
                descs = {
                    "sadece_long": "Spot long only  •  No short/scalp/leverage",
                    "dengeli": "Long + Short + Scalp  •  No leverage  ★ recommended",
                    "tam":    "Everything: Long + Short + Scalp + Leverage (must enable)",
                }
                header = "[bold]Select Trade Plan:[/]\n"
                header += "[grey58](This determines what types Claude can recommend)[/]\n\n"
                footer = "\n\n[grey58]Type 1/2/3 or Enter to keep current[/]"
            lines = []
            for i, key in enumerate(plans, 1):
                sel = "[bold #e3b341]>> [/]" if key == cur_plan else "   "
                col = "#e3b341" if key == cur_plan else "white"
                lines.append(f"{sel}[bold]{i}[/]) [{col}]{labels[key]}[/]  — {descs[key]}")
            self.set_body(header + "\n".join(lines) + footer)

        elif step == "mode":
            keys = ["guvenli", "dengeli", "agresif"]
            if lang == "tr":
                labels = {"guvenli": "güvenli", "dengeli": "dengeli", "agresif": "agresif"}
                descs = {
                    "guvenli": "Max 1 poz  •  %1 günlük kayıp kilidi",
                    "dengeli": "Max 2 poz  •  %2 günlük kayıp kilidi  ★ önerilen",
                    "agresif": "Max 3 poz  •  %3 günlük kayıp kilidi",
                }
                header = "[bold]Risk Modu Seç:[/]\n\n"
                footer = "\n\n[grey58]1/2/3 gir veya Enter = mevcut koru[/]"
            else:
                labels = {"guvenli": "safe", "dengeli": "balanced", "agresif": "aggressive"}
                descs = {
                    "guvenli": "Max 1 pos  •  1% daily loss lock",
                    "dengeli": "Max 2 pos  •  2% daily loss lock  ★ recommended",
                    "agresif": "Max 3 pos  •  3% daily loss lock",
                }
                header = "[bold]Select Risk Mode:[/]\n\n"
                footer = "\n\n[grey58]Type 1/2/3 or Enter to keep current[/]"

            lines = []
            for i, key in enumerate(keys, 1):
                sel = "[bold #e3b341]>> [/]" if key == cur_mode else "   "
                col = "#e3b341" if key == cur_mode else "white"
                lines.append(f"{sel}[bold]{i}[/]) [{col}]{labels[key]}[/]  — {descs[key]}")
            self.set_body(header + "\n".join(lines) + footer)

        elif step == "features":
            scalp = self._data["scalp"]
            lev = self._data["leverage"]
            if lang == "tr":
                s_val = "[bold green3]AÇIK ✔[/]" if scalp else "[grey50]KAPALI[/]"
                l_val = "[bold green3]AÇIK ✔[/]" if lev else "[grey50]KAPALI[/]"
                self.set_body(
                    "[bold]Paper Özellikler:[/]\n\n"
                    f"  [bold]S[/])  Scalp Paper:    {s_val}\n"
                    "       Anlık kripto, max 30dk, fee/slippage dahil\n\n"
                    f"  [bold]L[/])  Kaldıraç Paper: {l_val}\n"
                    "       Yalnızca Binance kripto, max 5x, likidasyon sim.\n\n"
                    "[grey58]S = scalp toggle   L = kaldıraç toggle   Enter = devam[/]"
                )
            else:
                s_val = "[bold green3]ON ✔[/]" if scalp else "[grey50]OFF[/]"
                l_val = "[bold green3]ON ✔[/]" if lev else "[grey50]OFF[/]"
                self.set_body(
                    "[bold]Paper Features:[/]\n\n"
                    f"  [bold]S[/])  Scalp Paper:    {s_val}\n"
                    "       Realtime crypto, max 30min, fee/slippage included\n\n"
                    f"  [bold]L[/])  Leverage Paper: {l_val}\n"
                    "       Binance crypto only, max 5x, liquidation simulated\n\n"
                    "[grey58]S = toggle scalp   L = toggle leverage   Enter = continue[/]"
                )

        elif step == "confirm":
            mode = self._data["mode"]
            plan = self._data["plan"]
            plan_labels_tr = {"sadece_long": "Sadece Long", "dengeli": "Dengeli", "tam": "Tam"}
            plan_labels_en = {"sadece_long": "Long Only", "dengeli": "Balanced", "tam": "Full"}
            if lang == "tr":
                plan_str = plan_labels_tr.get(plan, plan)
                self.set_body(
                    "[bold #e3b341]──  OTONOM MOD ÖZETİ  ──[/]\n\n"
                    f"  Trade Planı:    [bold white]{plan_str}[/]\n"
                    f"  Risk Modu:      [bold white]{mode}[/]\n"
                    f"  Gerçek Emirler: [bold red3]KAPALI — değiştirilemez[/]\n\n"
                    "[bold]Başlat: Enter   Geri: Esc[/]"
                )
            else:
                plan_str = plan_labels_en.get(plan, plan)
                self.set_body(
                    "[bold #e3b341]──  AUTONOMOUS MODE SUMMARY  ──[/]\n\n"
                    f"  Trade Plan:     [bold white]{plan_str}[/]\n"
                    f"  Risk Mode:      [bold white]{mode}[/]\n"
                    f"  Real Orders:    [bold red3]OFF — cannot be changed[/]\n\n"
                    "[bold]Start: Enter   Back: Esc[/]"
                )

        self.set_error("")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        val = event.value.strip().lower()
        event.input.value = ""
        self.set_error("")
        lang = i18n.lang()

        if self._step == "welcome":
            self._step = "plan"
            self._show_step()

        elif self._step == "plan":
            if val == "1":
                self._data["plan"] = "sadece_long"
                self._data["scalp"] = False
                self._data["leverage"] = False
            elif val == "2":
                self._data["plan"] = "dengeli"
                self._data["scalp"] = True
                self._data["leverage"] = False
            elif val == "3":
                self._data["plan"] = "tam"
                self._data["scalp"] = True
                # leverage hâlâ ayrıca cfg'de ayarlanabilir
            elif val == "":
                pass
            else:
                self.set_error("1, 2 veya 3 girin." if lang == "tr" else "Enter 1, 2 or 3.")
                return
            self._step = "mode"
            self._show_step()

        elif self._step == "mode":
            if val == "1":
                self._data["mode"] = "guvenli"
            elif val == "2":
                self._data["mode"] = "dengeli"
            elif val == "3":
                self._data["mode"] = "agresif"
            elif val == "":
                pass
            else:
                self.set_error("1, 2 veya 3 girin." if lang == "tr" else "Enter 1, 2 or 3.")
                return
            self._step = "confirm"
            self._show_step()

        elif self._step == "confirm":
            self._cfg.autonomous_mode = self._data["mode"]
            self._cfg.trade_plan = self._data["plan"]
            self._cfg.scalp_enabled = self._data["scalp"]
            self._cfg.leverage_enabled = self._data["leverage"]
            self._cfg.save()
            self.dismiss(True)

    def on_key(self, event) -> None:
        if event.key == "escape":
            event.stop()
            idx = self._STEPS.index(self._step)
            if idx == 0:
                self.dismiss(False)
            else:
                self._step = self._STEPS[idx - 1]
                self._show_step()


# ── AutonomousControlScreen ───────────────────────────────────────────────────

class AutonomousControlScreen(_MenuScreen):
    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self._cfg = cfg

    def _status_text(self) -> str:
        lang = i18n.lang()
        cfg = self._cfg
        from autonomous import AUTONOMOUS_PROFILES
        p = AUTONOMOUS_PROFILES.get(cfg.autonomous_mode, AUTONOMOUS_PROFILES["dengeli"])
        max_pos = cfg.custom_max_positions or p.max_open_positions
        max_trades = cfg.custom_max_daily_trades or p.max_daily_trades
        loss_streak = cfg.custom_loss_streak or p.max_consecutive_losses
        daily_loss = cfg.custom_daily_loss_pct or p.daily_loss_limit_percent
        scalp = ("AÇIK" if lang == "tr" else "ON") if cfg.scalp_enabled else ("KAPALI" if lang == "tr" else "OFF")
        lev = ("AÇIK" if lang == "tr" else "ON") if cfg.leverage_enabled else ("KAPALI" if lang == "tr" else "OFF")
        if lang == "tr":
            return (f"  Mod: [bold]{cfg.autonomous_mode}[/]   "
                    f"Max Poz: {max_pos}   Max İşlem/Gün: {max_trades}\n"
                    f"  Zarar Serisi Kilidi: {loss_streak}   "
                    f"Günlük Zarar Kilidi: %{daily_loss}\n"
                    f"  Scalp: {scalp}   Kaldıraç Paper: {lev}")
        return (f"  Mode: [bold]{cfg.autonomous_mode}[/]   "
                f"Max Pos: {max_pos}   Max Trades/Day: {max_trades}\n"
                f"  Loss Streak Lock: {loss_streak}   "
                f"Daily Loss Lock: {daily_loss}%\n"
                f"  Scalp: {scalp}   Leverage Paper: {lev}")

    def _items(self) -> list[str]:
        lang = i18n.lang()
        if lang == "tr":
            return [
                "  Otonom Modu Başlat  (Terminale Geç)",
                "  Modu Değiştir  (güvenli ↔ dengeli ↔ agresif)",
                "  Özel Limitleri Düzenle  →",
                "  Otonom Günlüklerini Gör  →",
                "  ← Geri",
            ]
        return [
            "  Start Autonomous Mode  (Enter Terminal)",
            "  Change Mode  (safe ↔ balanced ↔ aggressive)",
            "  Edit Custom Limits  →",
            "  View Autonomous Logs  →",
            "  ← Back",
        ]

    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = "──  OTONOM KONTROL  ──" if lang == "tr" else "──  AUTONOMOUS CONTROL  ──"
        hint = "↑↓ seç   Enter aç   Esc geri" if lang == "tr" else "↑↓ select   Enter open   Esc back"
        with Middle():
            with Center():
                with Vertical(id="auto-box"):
                    yield Static(title, id="auto-title")
                    yield Static(self._status_text(), id="auto-status")
                    yield Static("", id="auto-msg")
                    yield ListView(*[self._item(i) for i in self._items()], id="auto-list")
                    yield Static(hint, id="auto-hint")

    def on_mount(self) -> None:
        self.query_one("#auto-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index or 0
        lang = i18n.lang()
        if idx == 0:  # Start autonomous — wizard
            self.app.push_screen(AutonomousSetupScreen(self._cfg), self._on_auto_confirm)
        elif idx == 1:  # Change mode
            mc = ["guvenli", "dengeli", "agresif"]
            cur = self._cfg.autonomous_mode if self._cfg.autonomous_mode in mc else "dengeli"
            self._cfg.autonomous_mode = mc[(mc.index(cur) + 1) % len(mc)]
            self._cfg.save()
            self._flash_msg("auto-msg", f"✓ {self._cfg.autonomous_mode}")
            self._safe_update("auto-status", self._status_text())
            self._reload_list("auto-list", self._items())
        elif idx == 2:  # Risk limits
            self.app.push_screen(RiskLimitsScreen(self._cfg), self._on_sub)
        elif idx == 3:  # Logs
            self.app.push_screen(AutoLogsScreen(), self._on_sub)
        elif idx == 4:  # Back
            self.dismiss(None)

    def _on_auto_confirm(self, confirmed: bool) -> None:
        if confirmed:
            self.dismiss("auto_start")

    def _on_sub(self, result) -> None:
        if result == "exit":
            self.dismiss("exit")
            return
        self._safe_update("auto-status", self._status_text())

    def action_go_back(self) -> None:
        self.dismiss(None)


# ── AutoLogsScreen ────────────────────────────────────────────────────────────

class AutoLogsScreen(_MenuScreen):
    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = "──  OTONOM GÜNLÜKLER  ──" if lang == "tr" else "──  AUTONOMOUS LOGS  ──"
        log_path = Path(__file__).parent / "autonomous_log.jsonl"
        lines = []
        if log_path.exists():
            raw = log_path.read_text().strip().splitlines()[-20:]
            for line in raw:
                try:
                    d = __import__("json").loads(line)
                    from datetime import datetime
                    ts = datetime.fromtimestamp(d.get("ts", 0)).strftime("%m.%d %H:%M")
                    action = d.get("action", "?")
                    symbol = d.get("symbol", "")
                    note = d.get("note", "")
                    lines.append(f"  {ts}  {action:12}  {symbol:10}  {note[:40]}")
                except Exception:
                    lines.append(f"  {line[:70]}")
        else:
            lines = ["  (günlük yok)" if lang == "tr" else "  (no logs yet)"]

        hint = "Esc geri" if lang == "tr" else "Esc back"
        with Middle():
            with Center():
                with Vertical(id="logs-box"):
                    yield Static(title, id="logs-title")
                    with ScrollableContainer(id="logs-scroll"):
                        yield Static("\n".join(lines), id="logs-content")
                    yield Static(hint, id="logs-hint")

    def action_go_back(self) -> None:
        self.dismiss(None)


# ── MarketDataScreen ──────────────────────────────────────────────────────────

class MarketDataScreen(_MenuScreen):
    def __init__(self, cfg: Config, portfolio_summary: str = "") -> None:
        super().__init__()
        self._cfg = cfg
        self._portfolio_summary = portfolio_summary

    def _items(self) -> list[str]:
        lang = i18n.lang()
        if lang == "tr":
            return [
                "  İzleme Listesini Gör  →",
                "  Veri Kaynağı Durumu  →",
                "  Enstrüman Detayı  →",
                "  Küresel Piyasalar  (Terminale Geç)",
                "  ← Geri",
            ]
        return [
            "  View Watchlist  →",
            "  Data Source Status  →",
            "  Instrument Details  →",
            "  Global Markets  (Enter Terminal)",
            "  ← Back",
        ]

    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = "──  PİYASA & VERİ  ──" if lang == "tr" else "──  MARKET & DATA  ──"
        hint = "↑↓ seç   Enter aç   Esc geri" if lang == "tr" else "↑↓ select   Enter open   Esc back"
        with Middle():
            with Center():
                with Vertical(id="market-box"):
                    yield Static(title, id="market-title")
                    yield Static("", id="market-msg")
                    yield ListView(*[self._item(i) for i in self._items()], id="market-list")
                    yield Static("", id="market-detail")
                    yield Input(id="market-input", placeholder="sembol gir (örn: BTCUSDT)...", classes="hidden")
                    yield Static(hint, id="market-hint")

    def on_mount(self) -> None:
        self.query_one("#market-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index or 0
        lang = i18n.lang()
        if idx == 0:  # Watchlist
            self.app.push_screen(WatchlistScreen(), self._on_sub)
        elif idx == 1:  # Data source status
            self.app.push_screen(DataSourceStatusScreen(), self._on_sub)
        elif idx == 2:  # Instrument details
            inp = self.query_one("#market-input", Input)
            inp.remove_class("hidden")
            inp.focus()
        elif idx == 3:  # Global markets → terminal
            self.dismiss("trade")
        elif idx == 4:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        sym = event.value.strip().upper()
        event.input.value = ""
        event.input.add_class("hidden")
        if sym:
            self.app.push_screen(InstrumentDetailScreen(sym), self._on_sub)
        try:
            self.query_one("#market-list", ListView).focus()
        except Exception:
            pass

    def on_key(self, event) -> None:
        if event.key == "escape":
            try:
                inp = self.query_one("#market-input", Input)
                if not inp.has_class("hidden"):
                    event.stop()
                    inp.value = ""
                    inp.add_class("hidden")
                    self.query_one("#market-list", ListView).focus()
                    return
            except Exception:
                pass
            self.dismiss(None)

    def _on_sub(self, result) -> None:
        if result == "exit":
            self.dismiss("exit")
            return
        if result == "trade":
            self.dismiss("trade")
            return

    def action_go_back(self) -> None:
        self.dismiss(None)


# ── WatchlistScreen ───────────────────────────────────────────────────────────

class WatchlistScreen(_MenuScreen):
    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = "──  İZLEME LİSTESİ  ──" if lang == "tr" else "──  WATCHLIST  ──"
        import json as _json
        wl_path = Path(__file__).parent / "watchlist.json"
        wl = []
        if wl_path.exists():
            try:
                wl = _json.loads(wl_path.read_text())
            except Exception:
                wl = []
        lines = []
        try:
            import market
            for sym in wl:
                q = market.data_quality(sym)
                allowed = market.leverage_allowed(sym)
                q_label = {"realtime": "Anlık", "near_realtime": "Yakın-anlık",
                           "delayed": "Gecikmeli", "daily": "Günlük"}.get(q, q)
                lev_str = "✓ Kaldıraç" if allowed else "✗ Kaldıraç"
                lines.append(f"  {sym:12}  {q_label:15}  {lev_str}")
        except Exception:
            for sym in wl:
                lines.append(f"  {sym}")
        if not lines:
            lines = ["  (izleme listesi boş)" if lang == "tr" else "  (watchlist is empty)"]
        add_hint = ("  Ekle/Çıkar için terminalde: /ekle SEMBOL, /cikar SEMBOL"
                    if lang == "tr" else "  To add/remove use terminal: /add SYMBOL, /remove SYMBOL")
        hint = "Esc geri" if lang == "tr" else "Esc back"
        with Middle():
            with Center():
                with Vertical(id="wl-box"):
                    yield Static(title, id="wl-title")
                    yield Static("\n".join(lines), id="wl-content")
                    yield Static(add_hint, id="wl-add-hint")
                    yield Static(hint, id="wl-hint")

    def action_go_back(self) -> None:
        self.dismiss(None)


# ── DataSourceStatusScreen ────────────────────────────────────────────────────

class DataSourceStatusScreen(_MenuScreen):
    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = "──  VERİ KAYNAĞI DURUMU  ──" if lang == "tr" else "──  DATA SOURCE STATUS  ──"
        import json as _json
        wl_path = Path(__file__).parent / "watchlist.json"
        wl = []
        if wl_path.exists():
            try:
                wl = _json.loads(wl_path.read_text())
            except Exception:
                wl = []
        lines = []
        try:
            import market
            lines.append("  Sembol          Kalite          Kaldıraç  Kaynak")
            lines.append("  " + "─" * 55)
            for sym in wl:
                q = market.data_quality(sym)
                allowed = market.leverage_allowed(sym)
                reason = market.leverage_reason(sym)
                q_color = {"realtime": "green3", "near_realtime": "gold3",
                           "delayed": "red3", "daily": "red3"}.get(q, "grey50")
                q_label = {"realtime": "Anlık       ", "near_realtime": "Yakın-anlık ",
                           "delayed": "Gecikmeli   ", "daily": "Günlük      "}.get(q, q)
                lev = "✓" if allowed else "✗"
                lines.append(f"  [{q_color}]{sym:14}[/]  {q_label}  {lev}  {reason[:30]}")
        except Exception:
            lines = ["  (veri yüklenemedi)" if lang == "tr" else "  (could not load data)"]
        hint = "Esc geri" if lang == "tr" else "Esc back"
        with Middle():
            with Center():
                with Vertical(id="ds-box"):
                    yield Static(title, id="ds-title")
                    with ScrollableContainer(id="ds-scroll"):
                        yield Static("\n".join(lines), id="ds-content")
                    yield Static(hint, id="ds-hint")

    def action_go_back(self) -> None:
        self.dismiss(None)


# ── InstrumentDetailScreen ────────────────────────────────────────────────────

class InstrumentDetailScreen(_MenuScreen):
    def __init__(self, symbol: str) -> None:
        super().__init__()
        self._symbol = symbol.upper()

    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = f"──  {self._symbol}  ──"
        try:
            import market
            q = market.data_quality(self._symbol)
            allowed = market.leverage_allowed(self._symbol)
            reason = market.leverage_reason(self._symbol)
            q_label = market.data_quality_label(self._symbol)
            q_color = {"realtime": "green3", "near_realtime": "gold3",
                       "delayed": "red3", "daily": "red3"}.get(q, "grey50")
            lev_str = "[bold green3]✓ İzin Verildi[/]" if allowed else "[bold red3]✗ İzin Yok[/]"
            if lang == "tr":
                detail = (f"  Sembol:           [bold]{self._symbol}[/]\n"
                          f"  Veri Kalitesi:    [{q_color}]{q_label}[/]\n"
                          f"  Kaldıraç Paper:   {lev_str}\n"
                          f"  Gerekçe:          {reason}")
            else:
                detail = (f"  Symbol:           [bold]{self._symbol}[/]\n"
                          f"  Data Quality:     [{q_color}]{q_label}[/]\n"
                          f"  Leverage Paper:   {lev_str}\n"
                          f"  Reason:           {reason}")
        except Exception as e:
            detail = f"  Hata: {e}"
        hint = "Esc geri" if lang == "tr" else "Esc back"
        with Middle():
            with Center():
                with Vertical(id="detail-box"):
                    yield Static(title, id="detail-title")
                    yield Static(detail, id="detail-content")
                    yield Static(hint, id="detail-hint")

    def action_go_back(self) -> None:
        self.dismiss(None)


# ── ConnectionsScreen ─────────────────────────────────────────────────────────

class ConnectionsScreen(_MenuScreen):
    def __init__(self, cfg: Config) -> None:
        super().__init__()
        self._cfg = cfg
        self._entering_api = False
        self._entering_secret = False
        self._entering_passphrase = False
        self._temp_key = ""
        self._temp_secret = ""

    def _exchange_status(self) -> str:
        cfg = self._cfg
        ex = getattr(cfg, "exchange", "binance")
        mode = getattr(cfg, "trading_mode", "paper")
        if ex == "binance":
            on = bool(cfg.binance_key)
            key_hint = cfg.binance_key[:6] if on else ""
        elif ex == "bybit":
            on = bool(getattr(cfg, "bybit_key", ""))
            key_hint = cfg.bybit_key[:6] if on else ""  # type: ignore[attr-defined]
        elif ex == "okx":
            on = bool(getattr(cfg, "okx_key", ""))
            key_hint = cfg.okx_key[:6] if on else ""  # type: ignore[attr-defined]
        else:
            on, key_hint = False, ""
        return (f"✓ {ex.upper()} · {key_hint}**** · {mode.upper()}"
                if on else f"✗ {ex.upper()} · BAĞLANMADI")

    def _items(self) -> list[str]:
        lang = i18n.lang()
        cfg = self._cfg
        claude_ok = shutil.which("claude") is not None
        mode = getattr(cfg, "trading_mode", "paper")
        ex = getattr(cfg, "exchange", "binance")
        provider = getattr(cfg, "ai_provider", "claude")
        ai_st = "✓ BAĞLI" if claude_ok else "✗ BULUNAMADI"
        ex_st = self._exchange_status()
        if lang != "en":
            mode_action = ("→ PAPER moda geç" if mode == "live" else "→ LIVE moda geç")
            return [
                f"  AI Sağlayıcı                [{provider.upper()} · {ai_st}]",
                "  AI Modelini Değiştir        (/model komutu — terminal)",
                f"  Borsa Seç                   [{ex.upper()} — Binance / Bybit / OKX]",
                f"  Borsa API Bağlantısı        [{ex_st}]",
                f"  Trading Modu Değiştir       [{mode.upper()} — {mode_action}]",
                "  Bağlantıyı Kes",
                "  Güvenlik & Mod Durumu       →",
                "  ← Geri",
            ]
        mode_action_en = ("→ switch to PAPER" if mode == "live" else "→ switch to LIVE")
        return [
            f"  AI Provider                 [{provider.upper()} · {ai_st}]",
            "  Change AI Model             (/model command — in terminal)",
            f"  Select Exchange             [{ex.upper()} — Binance / Bybit / OKX]",
            f"  Exchange API Connection     [{ex_st}]",
            f"  Switch Trading Mode         [{mode.upper()} — {mode_action_en}]",
            "  Disconnect",
            "  Safety & Mode Status        →",
            "  ← Back",
        ]

    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = "──  BAĞLANTILAR & MOD  ──" if lang == "tr" else "──  CONNECTIONS & MODE  ──"
        hint = "↑↓ seç   Enter aç   Esc geri" if lang == "tr" else "↑↓ select   Enter open   Esc back"
        with Middle():
            with Center():
                with Vertical(id="conn-box"):
                    yield Static(title, id="conn-title")
                    yield Static("", id="conn-msg")
                    yield Static("", id="conn-detail")
                    yield ListView(*[self._item(i) for i in self._items()], id="conn-list")
                    yield Input(id="conn-input", placeholder="", classes="hidden")
                    yield Static(hint, id="conn-hint")

    def on_mount(self) -> None:
        self.query_one("#conn-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index or 0
        lang = i18n.lang()
        cfg = self._cfg
        if idx == 0:  # AI provider durum
            provider = getattr(cfg, "ai_provider", "claude")
            found = shutil.which("claude") is not None if provider == "claude" else True
            if lang == "tr":
                detail = (
                    f"  Aktif AI:  [bold]{provider.upper()}[/]\n"
                    f"  Claude CLI: {'bulundu ✓' if found else 'bulunamadı ✗'}\n"
                    f"  Değiştirmek için terminale: [bold]/model claude|openai|gemini|ollama|grok[/]\n"
                    f"  API key kaydetmek için: [bold]/model key openai|gemini|grok API_KEY[/]"
                )
            else:
                detail = (
                    f"  Active AI:  [bold]{provider.upper()}[/]\n"
                    f"  Claude CLI: {'found ✓' if found else 'not found ✗'}\n"
                    f"  To switch: [bold]/model claude|openai|gemini|ollama|grok[/]\n"
                    f"  To set key: [bold]/model key openai|gemini|grok API_KEY[/]"
                )
            self._safe_update("conn-detail", detail)
        elif idx == 1:  # AI model bilgi
            if lang == "tr":
                self._safe_update("conn-detail",
                    "  Terminal'de [bold]/model[/] yazarak tüm AI seçeneklerini gör.\n"
                    "  Örnek: [bold]/model openai gpt-4o[/]   [bold]/model ollama llama3.2[/]")
            else:
                self._safe_update("conn-detail",
                    "  Type [bold]/model[/] in terminal to see all AI options.\n"
                    "  Example: [bold]/model openai gpt-4o[/]   [bold]/model ollama llama3.2[/]")
        elif idx == 2:  # Borsa seç (döngüsel)
            _exchanges = ["binance", "bybit", "okx"]
            cur_ex = getattr(cfg, "exchange", "binance")
            next_ex = _exchanges[(_exchanges.index(cur_ex) + 1) % len(_exchanges)] if cur_ex in _exchanges else "binance"
            cfg.exchange = next_ex
            cfg.save()
            self._flash_msg("conn-msg", f"✓ Borsa: {next_ex.upper()}")
            _instructions = {
                "binance": ("Binance API Management → 'Enable Spot & Margin Trading'" if lang == "tr"
                            else "Binance API Management → 'Enable Spot & Margin Trading'"),
                "bybit": ("Bybit API Management → Unified Trading: Read + Orders" if lang == "tr"
                          else "Bybit API Management → Unified Trading: Read + Orders"),
                "okx": ("OKX API → Read + Trade izni + Passphrase belirle\n"
                        "  Bağlantı: /canli bagla KEY SECRET PASSPHRASE" if lang == "tr"
                        else "OKX API → Read + Trade permission + set Passphrase\n"
                             "  Connect: /live bagla KEY SECRET PASSPHRASE"),
            }.get(next_ex, "")
            self._safe_update("conn-detail", f"  [cyan]{_instructions}[/]")
            self._reload_list("conn-list", self._items())
        elif idx == 3:  # Exchange API bağlantı
            self._entering_api = True
            self._entering_secret = False
            ex = getattr(cfg, "exchange", "binance")
            inp = self.query_one("#conn-input", Input)
            inp.password = False
            inp.placeholder = f"{ex.upper()} API Key"
            inp.remove_class("hidden")
            _ex_guide = {
                "binance": (
                    "[bold cyan]Binance API Key girin.[/]\n"
                    "  ✔ Enable Spot & Margin Trading iznini aç\n"
                    "  ✗ Withdraw iznini AÇMA  ✔ IP kısıtlaması ekle\n"
                    "Secret bir sonraki adımda — maskelenir."
                    if lang == "tr" else
                    "[bold cyan]Enter Binance API Key.[/]\n"
                    "  ✔ Enable Spot & Margin Trading\n"
                    "  ✗ No Withdrawals  ✔ Add IP restriction\n"
                    "Secret next — masked."
                ),
                "bybit": (
                    "[bold cyan]Bybit API Key girin.[/]\n"
                    "  ✔ Unified Trading: Read + Orders\n"
                    "  ✗ Withdraw iznini AÇMA\n"
                    "Secret bir sonraki adımda — maskelenir."
                    if lang == "tr" else
                    "[bold cyan]Enter Bybit API Key.[/]\n"
                    "  ✔ Unified Trading: Read + Orders\n"
                    "  ✗ No Withdrawals\n"
                    "Secret next — masked."
                ),
                "okx": (
                    "[bold cyan]OKX API Key girin.[/]\n"
                    "  ✔ Read + Trade izni\n"
                    "  ✗ Withdraw iznini AÇMA\n"
                    "Secret, sonra Passphrase girilecek — maskelenir."
                    if lang == "tr" else
                    "[bold cyan]Enter OKX API Key.[/]\n"
                    "  ✔ Read + Trade permission\n"
                    "  ✗ No Withdrawals\n"
                    "Secret then Passphrase will be asked — masked."
                ),
            }.get(ex, "[bold cyan]API Key girin.[/]")
            self._safe_update("conn-detail", _ex_guide)
            inp.focus()
        elif idx == 4:  # Trading mode toggle
            self.run_worker(self._toggle_trading_mode(), exclusive=True)
        elif idx == 5:  # Bağlantıyı kes
            ex = getattr(cfg, "exchange", "binance")
            if ex == "binance":
                cfg.binance_key = ""
                cfg.binance_secret = ""
            elif ex == "bybit":
                cfg.bybit_key = ""  # type: ignore[attr-defined]
                cfg.bybit_secret = ""  # type: ignore[attr-defined]
            elif ex == "okx":
                cfg.okx_key = ""  # type: ignore[attr-defined]
                cfg.okx_secret = ""  # type: ignore[attr-defined]
                cfg.okx_passphrase = ""  # type: ignore[attr-defined]
            cfg.trading_mode = "paper"
            cfg.save()
            msg = (f"✓ {ex.upper()} bağlantısı kesildi, paper moda dönüldü." if lang == "tr"
                   else f"✓ {ex.upper()} disconnected, switched to paper mode.")
            self._flash_msg("conn-msg", msg)
            self._safe_update("conn-detail", "")
            self._reload_list("conn-list", self._items())
        elif idx == 6:  # Safety
            self.app.push_screen(SafetyStatusScreen(), self._on_sub)
        elif idx == 7:
            self.dismiss(None)

    async def _toggle_trading_mode(self) -> None:
        import exchange as _exchange
        lang = i18n.lang()
        cfg = self._cfg
        ex = getattr(cfg, "exchange", "binance")
        cur = getattr(cfg, "trading_mode", "paper")

        # Aktif borsa için key kontrolü
        _key = {
            "binance": cfg.binance_key,
            "bybit": getattr(cfg, "bybit_key", ""),
            "okx": getattr(cfg, "okx_key", ""),
        }.get(ex, "")
        _secret = {
            "binance": cfg.binance_secret,
            "bybit": getattr(cfg, "bybit_secret", ""),
            "okx": getattr(cfg, "okx_secret", ""),
        }.get(ex, "")
        _extra = getattr(cfg, "okx_passphrase", "") if ex == "okx" else ""

        if not _key:
            msg = (f"Önce {ex.upper()} API bağlantısı gerekli (seçenek 4)."
                   if lang == "tr" else
                   f"Connect {ex.upper()} API first (option 4).")
            self._safe_update("conn-detail", f"[dark_orange]{msg}[/]")
            return

        if cur == "paper":
            self._safe_update("conn-detail",
                f"[grey58]{ex.upper()}'de işlem izni kontrol ediliyor...[/]" if lang == "tr" else
                f"[grey58]Checking trading permission on {ex.upper()}...[/]")
            try:
                can_trade = await _exchange.check_trading_permission(_key, _secret, _extra)
            except Exception as e:
                self._safe_update("conn-detail", f"[red3]Hata: {e}[/]")
                return
            if not can_trade:
                self._safe_update("conn-detail",
                    f"[red3]Hesabın 'Spot Trading' izni yok!\n"
                    f"{ex.upper()} API ayarlarından Trade iznini aç.[/]" if lang == "tr" else
                    f"[red3]Account has no 'Spot Trading' permission!\n"
                    f"Enable Trade permission in {ex.upper()} API settings.[/]")
                return
            cfg.trading_mode = "live"
            cfg.save()
            self._flash_msg("conn-msg",
                f"[green3]✓ LIVE moda geçildi — gerçek emirler {ex.upper()}'e gidecek![/]" if lang == "tr" else
                f"[green3]✓ Switched to LIVE mode — real orders will go to {ex.upper()}![/]", delay=5.0)
        else:
            cfg.trading_mode = "paper"
            cfg.save()
            self._flash_msg("conn-msg",
                "[dark_orange]✓ PAPER moda döndü — emirler simüle edilir.[/]" if lang == "tr" else
                "[dark_orange]✓ Back to PAPER mode — orders are simulated.[/]")
        self._safe_update("conn-detail", "")
        self._reload_list("conn-list", self._items())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        val = event.value.strip()
        event.input.value = ""
        lang = i18n.lang()
        ex = getattr(self._cfg, "exchange", "binance")
        inp = self.query_one("#conn-input", Input)

        if self._entering_api:
            self._temp_key = val
            self._entering_api = False
            self._entering_secret = True
            inp.password = True
            inp.placeholder = f"{ex.upper()} Secret (maskelenir)"
            self._safe_update("conn-detail",
                "[bold dark_orange]SECRET maskelenmiş.[/]\n"
                "Secret girin — log veya ekranda gösterilmez." if lang == "tr" else
                "[bold dark_orange]SECRET is masked.[/]\n"
                "Enter secret — never shown in logs or display.")
            inp.focus()

        elif self._entering_secret:
            self._temp_secret = val
            if ex == "okx":
                # OKX için 3. adım: passphrase
                self._entering_secret = False
                self._entering_passphrase = True
                inp.password = True
                inp.placeholder = "OKX Passphrase (maskelenir)"
                self._safe_update("conn-detail",
                    "[bold dark_orange]PASSPHRASE maskelenmiş.[/]\n"
                    "API oluştururken belirlediğin passphrase'i gir." if lang == "tr" else
                    "[bold dark_orange]PASSPHRASE is masked.[/]\n"
                    "Enter the passphrase you set when creating the API key.")
                inp.focus()
            else:
                self._entering_secret = False
                self._save_exchange_keys(ex, self._temp_key, val, "", lang)

        elif getattr(self, "_entering_passphrase", False):
            self._entering_passphrase = False
            self._save_exchange_keys(ex, self._temp_key, getattr(self, "_temp_secret", ""), val, lang)

        else:
            inp.add_class("hidden")
            try:
                self.query_one("#conn-list", ListView).focus()
            except Exception:
                pass

    def _save_exchange_keys(self, ex: str, key: str, secret: str,
                            passphrase: str, lang: str) -> None:
        cfg = self._cfg
        inp = self.query_one("#conn-input", Input)
        if not key or not secret:
            inp.password = False
            inp.add_class("hidden")
            self._flash_msg("conn-msg", "✗ Boş olamaz." if lang == "tr" else "✗ Cannot be empty.")
            try:
                self.query_one("#conn-list", ListView).focus()
            except Exception:
                pass
            return
        if ex == "binance":
            cfg.binance_key = key
            cfg.binance_secret = secret
        elif ex == "bybit":
            cfg.bybit_key = key  # type: ignore[attr-defined]
            cfg.bybit_secret = secret  # type: ignore[attr-defined]
        elif ex == "okx":
            if not passphrase:
                self._flash_msg("conn-msg", "✗ OKX passphrase boş olamaz." if lang == "tr"
                                else "✗ OKX passphrase cannot be empty.")
                return
            cfg.okx_key = key  # type: ignore[attr-defined]
            cfg.okx_secret = secret  # type: ignore[attr-defined]
            cfg.okx_passphrase = passphrase  # type: ignore[attr-defined]
        cfg.save()
        self._temp_key = ""
        self._temp_secret = ""  # type: ignore[attr-defined]
        inp.password = False
        inp.add_class("hidden")
        self._flash_msg("conn-msg",
                        f"✓ {ex.upper()} API kaydedildi." if lang == "tr"
                        else f"✓ {ex.upper()} API saved.")
        self._safe_update("conn-detail", "")
        self._reload_list("conn-list", self._items())
        try:
            self.query_one("#conn-list", ListView).focus()
        except Exception:
            pass

    def on_key(self, event) -> None:
        if event.key == "escape":
            if self._entering_api or self._entering_secret or self._entering_passphrase:
                event.stop()
                self._entering_api = False
                self._entering_secret = False
                self._entering_passphrase = False
                self._temp_key = ""
                self._temp_secret = ""
                try:
                    inp = self.query_one("#conn-input", Input)
                    inp.value = ""
                    inp.password = False
                    inp.add_class("hidden")
                    self.query_one("#conn-list", ListView).focus()
                except Exception:
                    pass
            else:
                self.dismiss(None)

    def _on_sub(self, result) -> None:
        if result == "exit":
            self.dismiss("exit")

    def action_go_back(self) -> None:
        self.dismiss(None)


# ── SafetyStatusScreen ────────────────────────────────────────────────────────

class SafetyStatusScreen(_MenuScreen):
    def compose(self) -> ComposeResult:
        from config import current as _cur_cfg
        try:
            _cfg = _cur_cfg()
            trading_mode = getattr(_cfg, "trading_mode", "paper")
            live_auto = getattr(_cfg, "live_autonomous", False)
        except Exception:
            trading_mode, live_auto = "paper", False

        lang = i18n.lang()
        title = "──  TRADING GÜVENLİK DURUMU  ──" if lang == "tr" else "──  TRADING SAFETY STATUS  ──"
        mode_color = "green3" if trading_mode == "live" else "dark_orange"
        auto_color = "red3" if live_auto else "dark_orange"
        if lang == "tr":
            content = (
                f"[bold black on {mode_color}]  Trading Modu: {trading_mode.upper():<12}[/]  "
                f"[bold black on {auto_color}]  Otonom Emirler: {'GERÇEK' if live_auto else 'PAPER':<12}[/]\n\n"
                "[bold white on dark_red]  Futures: DESTEKLENMEZ    [/]  "
                "[bold white on dark_red]  Margin: DESTEKLENMEZ     [/]\n\n"
                "[bold white on dark_red]  Withdraw: DESTEKLENMEZ   [/]  "
                "[bold black on green3]   Spot Emirler: Binance API [/]\n\n"
                f"[bold cyan]Aktif mod: {trading_mode.upper()}[/]\n"
                "Paper: tüm işlemler sanal bakiyede simüle edilir.\n"
                "Live: spot emirler Binance API üzerinden gönderilir.\n"
                "Kaldıraç ve short yalnızca paper modunda çalışır.\n\n"
                "[grey58]/canli mod live|paper ile mod değiştirilir.[/]"
            )
        else:
            content = (
                f"[bold black on {mode_color}]  Trading Mode: {trading_mode.upper():<12}[/]  "
                f"[bold black on {auto_color}]  Auto Orders: {'REAL' if live_auto else 'PAPER':<12}[/]\n\n"
                "[bold white on dark_red]  Futures: NOT SUPPORTED   [/]  "
                "[bold white on dark_red]  Margin: NOT SUPPORTED    [/]\n\n"
                "[bold white on dark_red]  Withdraw: NOT SUPPORTED  [/]  "
                "[bold black on green3]   Spot Orders: Binance API  [/]\n\n"
                f"[bold cyan]Active mode: {trading_mode.upper()}[/]\n"
                "Paper: all trades are simulated on virtual balance.\n"
                "Live: spot orders are sent via Binance API.\n"
                "Leverage and short are paper-only.\n\n"
                "[grey58]Use /live mod live|paper to switch modes.[/]"
            )
        hint = "Esc geri" if lang == "tr" else "Esc back"
        with Middle():
            with Center():
                with Vertical(id="safety-box"):
                    yield Static(title, id="safety-title")
                    yield Static(content, id="safety-content")
                    yield Static(hint, id="safety-hint")

    def action_go_back(self) -> None:
        self.dismiss(None)


# ── ReportsScreen ─────────────────────────────────────────────────────────────

class ReportsScreen(_MenuScreen):
    def __init__(self, cfg: Config, portfolio_summary: str = "") -> None:
        super().__init__()
        self._cfg = cfg
        self._portfolio_summary = portfolio_summary

    def _items(self) -> list[str]:
        lang = i18n.lang()
        if lang == "tr":
            return [
                "  Performans  →",
                "  İşlem Geçmişi  →",
                "  Öneriler  →",
                "  Otonom Günlükleri  →",
                "  Rapor Dışa Aktar  →",
                "  ← Geri",
            ]
        return [
            "  Performance  →",
            "  Trade History  →",
            "  Recommendations  →",
            "  Autonomous Logs  →",
            "  Export Report  →",
            "  ← Back",
        ]

    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = "──  RAPORLAR  ──" if lang == "tr" else "──  REPORTS  ──"
        hint = "↑↓ seç   Enter aç   Esc geri" if lang == "tr" else "↑↓ select   Enter open   Esc back"
        with Middle():
            with Center():
                with Vertical(id="rep-box"):
                    yield Static(title, id="rep-title")
                    yield Static("", id="rep-msg")
                    yield ListView(*[self._item(i) for i in self._items()], id="rep-list")
                    yield Static(hint, id="rep-hint")

    def on_mount(self) -> None:
        self.query_one("#rep-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index or 0
        lang = i18n.lang()
        if idx == 0:  # Performance
            self.app.push_screen(PerformanceScreen(self._portfolio_summary), self._on_sub)
        elif idx == 1:  # Trade history
            self.app.push_screen(TradeHistoryScreen(), self._on_sub)
        elif idx == 2:  # Recommendations
            self.app.push_screen(RecommendationsScreen(), self._on_sub)
        elif idx == 3:  # Auto logs
            self.app.push_screen(AutoLogsScreen(), self._on_sub)
        elif idx == 4:  # Export
            self._export_report(lang)
        elif idx == 5:
            self.dismiss(None)

    def _export_report(self, lang: str) -> None:
        import json as _json
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path(__file__).parent / f"report_{ts}.txt"
        lines = [f"trade-k Report — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
        lines.append("=== PORTFOLIO SUMMARY ===")
        lines.append(self._portfolio_summary)
        try:
            acc = Path(__file__).parent / "account.json"
            if acc.exists():
                d = _json.loads(acc.read_text())
                lines.append(f"\nCash: {d.get('cash', 0):,.2f} USDT")
                lines.append(f"Open positions: {len(d.get('positions', {}))}")
                for h in d.get("history", [])[-20:]:
                    from datetime import datetime as dt
                    lines.append(
                        f"  {dt.fromtimestamp(h['ts']).strftime('%m.%d %H:%M')}  "
                        f"{h['side']:8}  {h['symbol']:12}  {h['price']:>12.4f}"
                    )
        except Exception as e:
            lines.append(f"(portfolio read error: {e})")
        out_path.write_text("\n".join(lines), encoding="utf-8")
        msg = f"✓ Dışa aktarıldı: {out_path.name}" if lang == "tr" else f"✓ Exported: {out_path.name}"
        self._flash_msg("rep-msg", msg)

    def _on_sub(self, result) -> None:
        if result == "exit":
            self.dismiss("exit")

    def action_go_back(self) -> None:
        self.dismiss(None)


# ── PerformanceScreen ─────────────────────────────────────────────────────────

class PerformanceScreen(_MenuScreen):
    def __init__(self, portfolio_summary: str = "") -> None:
        super().__init__()
        self._summary = portfolio_summary

    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = "──  PERFORMANS  ──" if lang == "tr" else "──  PERFORMANCE  ──"
        lines = [self._summary, ""]
        try:
            import json as _json
            rec_path = Path(__file__).parent / "recommendations.json"
            if rec_path.exists():
                recs = _json.loads(rec_path.read_text())
                total = len(recs)
                approved = sum(1 for r in recs if r.get("status") == "approved")
                rejected = sum(1 for r in recs if r.get("status") == "rejected")
                lines.append(f"  Toplam öneri: {total}" if lang == "tr" else f"  Total recommendations: {total}")
                lines.append(f"  Onaylanan: {approved}   Reddedilen: {rejected}" if lang == "tr"
                             else f"  Approved: {approved}   Rejected: {rejected}")
        except Exception as e:
            lines.append(f"  (veri yüklenemedi: {e})" if lang == "tr" else f"  (data load error: {e})")
        hint = "Esc geri" if lang == "tr" else "Esc back"
        with Middle():
            with Center():
                with Vertical(id="perf-box"):
                    yield Static(title, id="perf-title")
                    yield Static("\n".join(lines), id="perf-content")
                    yield Static(hint, id="perf-hint")

    def action_go_back(self) -> None:
        self.dismiss(None)


# ── TradeHistoryScreen ────────────────────────────────────────────────────────

class TradeHistoryScreen(_MenuScreen):
    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = "──  İŞLEM GEÇMİŞİ  ──" if lang == "tr" else "──  TRADE HISTORY  ──"
        lines = []
        try:
            import json as _json
            from datetime import datetime
            acc = Path(__file__).parent / "account.json"
            if acc.exists():
                d = _json.loads(acc.read_text())
                history = d.get("history", [])
                if history:
                    header = ("  Zaman       Yön       Sembol         Miktar         Fiyat"
                              if lang == "tr" else
                              "  Time        Side      Symbol         Qty            Price")
                    lines.append(header)
                    lines.append("  " + "─" * 60)
                    for h in history[-25:]:
                        ts = datetime.fromtimestamp(h["ts"]).strftime("%m.%d %H:%M")
                        side_color = "green3" if h["side"] == "AL" else "dark_orange"
                        lines.append(
                            f"  {ts}  [{side_color}]{h['side']:8}[/]  "
                            f"{h['symbol']:12}  {h['qty']:>12.6f}  {h['price']:>12.4f}"
                        )
                else:
                    lines.append("  (işlem yok)" if lang == "tr" else "  (no trades)")
            else:
                lines.append("  (hesap dosyası yok)" if lang == "tr" else "  (no account file)")
        except Exception as e:
            lines.append(f"  (hata: {e})")
        hint = "Esc geri" if lang == "tr" else "Esc back"
        with Middle():
            with Center():
                with Vertical(id="hist-box"):
                    yield Static(title, id="hist-title")
                    with ScrollableContainer(id="hist-scroll"):
                        yield Static("\n".join(lines), id="hist-content")
                    yield Static(hint, id="hist-hint")

    def action_go_back(self) -> None:
        self.dismiss(None)


# ── RecommendationsScreen ─────────────────────────────────────────────────────

class RecommendationsScreen(_MenuScreen):
    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = "──  ÖNERİLER  ──" if lang == "tr" else "──  RECOMMENDATIONS  ──"
        lines = []
        try:
            import json as _json
            from datetime import datetime
            rec_path = Path(__file__).parent / "recommendations.json"
            if rec_path.exists():
                recs = _json.loads(rec_path.read_text())
                for r in recs[-20:]:
                    ts = datetime.fromtimestamp(r.get("timestamp", 0)).strftime("%m.%d %H:%M")
                    status = r.get("status", "?")
                    st_color = {"approved": "green3", "rejected": "red3",
                                "expired": "grey50", "pending": "gold3"}.get(status, "grey50")
                    lines.append(
                        f"  {ts}  [{st_color}]{status:8}[/]  {r.get('side', '?'):8}  "
                        f"{r.get('symbol', '?'):12}  %{r.get('confidence_percent', 0)}"
                    )
            else:
                lines.append("  (öneri yok)" if lang == "tr" else "  (no recommendations)")
        except Exception as e:
            lines.append(f"  (hata: {e})")
        hint = "Esc geri" if lang == "tr" else "Esc back"
        with Middle():
            with Center():
                with Vertical(id="recs-box"):
                    yield Static(title, id="recs-title")
                    with ScrollableContainer(id="recs-scroll"):
                        yield Static("\n".join(lines), id="recs-content")
                    yield Static(hint, id="recs-hint")

    def action_go_back(self) -> None:
        self.dismiss(None)


# ── AnalysisScreen: Backtest & TA komut referansı ─────────────────────────────

class AnalysisScreen(_MenuScreen):
    """Backtest & Teknik Analiz komutlarına hızlı referans."""

    def _items(self) -> list[str]:
        lang = i18n.lang()
        if lang == "tr":
            return [
                "  /ta BTC 1h              → Teknik analiz (RSI/MACD/BB/EMA/ADX)",
                "  /ta BTC 4h              → Farklı zaman dilimi analizi",
                "  /mtf BTC                → 4 zaman dilimi konsensüs (15m/1h/4h/1d)",
                "  /backtest BTC 1h 30     → 30 günlük backtest",
                "  /backtest wf BTC 1h 90  → Walk-forward (%70/%30 in/out-sample)",
                "  /backtest mc BTC 1h 30  → Monte Carlo (200 simülasyon)",
                "  /backtest scan 1h 30    → Tüm izleme listesini tara",
                "  /strateji momentum      → Strateji: momentum/dönüş/kırılım/konsensüs",
                "  /boyut BTC 2.5          → Pozisyon boyutu hesapla (%2.5 stop)",
                "  /risk                   → Portföy heat & korelasyon raporu",
                "  /fiyat BTC 95000 al     → Fiyat alarmı + otomatik al",
                "  ← Geri",
            ]
        return [
            "  /ta BTC 1h              → Technical analysis (RSI/MACD/BB/EMA/ADX)",
            "  /ta BTC 4h              → Different timeframe analysis",
            "  /mtf BTC                → 4 timeframe consensus (15m/1h/4h/1d)",
            "  /backtest BTC 1h 30     → 30-day backtest",
            "  /backtest wf BTC 1h 90  → Walk-forward (70%/30% in/out-sample)",
            "  /backtest mc BTC 1h 30  → Monte Carlo (200 simulations)",
            "  /backtest scan 1h 30    → Scan entire watchlist",
            "  /strateji momentum      → Strategy: momentum/dönüş/kırılım/konsensüs",
            "  /boyut BTC 2.5          → Position size calculator (2.5% stop)",
            "  /risk                   → Portfolio heat & correlation report",
            "  /fiyat BTC 95000 al     → Price alert + auto buy",
            "  ← Back",
        ]

    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = "──  BACKTEST & TEKNİK ANALİZ  ──" if lang == "tr" else "──  BACKTEST & TECHNICAL ANALYSIS  ──"
        sub = ("  Komutları terminalde kullan." if lang == "tr"
               else "  Use these commands in the terminal.")
        hint = "Enter → terminale geç   Esc geri" if lang == "tr" else "Enter → go to terminal   Esc back"
        with Middle():
            with Center():
                with Vertical(id="analysis-box"):
                    yield Static(title, id="analysis-title")
                    yield Static(sub, id="analysis-sub")
                    yield ListView(*[self._item(i) for i in self._items()], id="analysis-list")
                    yield Static(hint, id="analysis-hint")

    def on_mount(self) -> None:
        self.query_one("#analysis-list", ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = event.list_view.index or 0
        if idx == len(self._items()) - 1:
            self.dismiss(None)
        else:
            self.dismiss("trade")
