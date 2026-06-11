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
              PAPER TRADING TERMINAL  [REAL ORDERS: OFF]"""


# ── Helper ────────────────────────────────────────────────────────────────────

def _build_status_chips(cfg: Config) -> str:
    """Status chip satırı - Rich markup string döner."""
    claude_ok = shutil.which("claude") is not None
    binance_on = bool(cfg.binance_key)
    lang_str = "TR" if cfg.language == "tr" else "EN"
    model_upper = cfg.model.upper()
    parts = [
        "[bold white on dark_orange] ◈ PAPER MODE [/]",
        "[bold white on dark_red] ✕ REAL ORDERS: OFF [/]",
        (f"[bold black on green3] ✔ CLAUDE:{model_upper} [/]" if claude_ok
         else "[bold white on red3] ✕ CLAUDE:OFFLINE [/]"),
        (f"[bold black on green3] ✔ BINANCE:KEY [/]" if binance_on
         else "[bold white on grey27] ○ BINANCE:NO KEY [/]"),
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
        Binding("q", "quit_app", "Çıkış", show=False),
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
    ]

    def __init__(self, cfg: Config, portfolio_summary: str = "") -> None:
        super().__init__()
        self._cfg = cfg
        self._portfolio_summary = portfolio_summary

    def _menu_items(self) -> list[str]:
        lang = i18n.lang()
        if lang == "tr":
            return [
                "  1.  Trading Terminal",
                "  2.  Otonom Kontrol",
                "  3.  Piyasa & Veri",
                "  4.  Bağlantılar",
                "  5.  Ayarlar",
                "  6.  Raporlar",
                "  7.  Çıkış",
            ]
        return [
            "  1.  Trading Terminal",
            "  2.  Autonomous Control",
            "  3.  Market & Data",
            "  4.  Connections",
            "  5.  Settings",
            "  6.  Reports",
            "  7.  Exit",
        ]

    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        welcome = (f"  Hoş geldin, {self._cfg.name}!" if lang == "tr"
                   else f"  Welcome, {self._cfg.name}!")
        hint = ("  ↑↓ seç   Enter aç   Q çıkış" if lang == "tr"
                else "  ↑↓ select   Enter open   Q quit")
        with Middle():
            with Center():
                with Vertical(id="splash-box"):
                    yield Static(SPLASH_LOGO, id="splash-logo")
                    yield Static(_build_status_chips(self._cfg), id="splash-chips")
                    yield Static(welcome, id="splash-welcome")
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
            self.app.push_screen(MarketDataScreen(self._cfg, self._portfolio_summary), self._on_sub)
        elif n == 4:
            self.app.push_screen(ConnectionsScreen(self._cfg), self._on_sub)
        elif n == 5:
            self.app.push_screen(SettingsScreen(self._cfg), self._on_sub)
        elif n == 6:
            self.app.push_screen(ReportsScreen(self._cfg, self._portfolio_summary), self._on_sub)
        elif n == 7:
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
            if lang == "tr":
                self.set_body(
                    "[bold white on dark_red]  !  REAL_ORDER_DISABLED — TÜM İŞLEMLER PAPER  ![/]\n\n"
                    "Otonom mod Claude AI kullanarak kripto piyasasını tarar ve\n"
                    "[bold]YALNIZCA PAPER (sanal)[/] işlem açıp kapatır.\n\n"
                    "API key bağlı olsa bile gerçek emir asla gönderilmez.\n"
                    "Tüm PnL sanal bakiyeden hesaplanır, gerçek para riski yok.\n\n"
                    "[grey58]Devam: Enter   İptal: Esc[/]"
                )
            else:
                self.set_body(
                    "[bold white on dark_red]  !  REAL_ORDER_DISABLED — ALL OPERATIONS PAPER  ![/]\n\n"
                    "Autonomous mode uses Claude AI to scan crypto markets and\n"
                    "[bold]ONLY opens/closes PAPER (virtual)[/] trades.\n\n"
                    "No real orders are sent even with API key connected.\n"
                    "All PnL tracks virtual balance — no real money at risk.\n\n"
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
        self._temp_key = ""

    def _items(self) -> list[str]:
        lang = i18n.lang()
        cfg = self._cfg
        claude_ok = shutil.which("claude") is not None
        binance_on = bool(cfg.binance_key)
        claude_st = "✓ CONNECTED" if claude_ok else "✗ DISCONNECTED"
        binance_st = f"ON [{cfg.binance_key[:4]}****]" if binance_on else "OFF"
        if lang == "tr":
            return [
                f"  Claude Durumu               [{claude_st}]",
                f"  Claude Modeli Seç           [{cfg.model}]",
                f"  Binance Read-Only Bağlantı  [{binance_st}]",
                "  Binance Bağlantısını Kes",
                "  Canlı Güvenlik Durumu       →",
                "  ← Geri",
            ]
        return [
            f"  Claude Status               [{claude_st}]",
            f"  Select Claude Model         [{cfg.model}]",
            f"  Binance Read-Only Connect   [{binance_st}]",
            "  Disconnect Binance",
            "  Live Safety Status          →",
            "  ← Back",
        ]

    def compose(self) -> ComposeResult:
        lang = i18n.lang()
        title = "──  BAĞLANTILAR  ──" if lang == "tr" else "──  CONNECTIONS  ──"
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
        if idx == 0:  # Claude status
            import shutil as _shutil
            found = _shutil.which("claude") is not None
            if lang == "tr":
                detail = (f"  claude CLI: {'bulundu ✓' if found else 'bulunamadı ✗'}\n"
                          f"  Seçili model: {cfg.model}\n"
                          f"  Not: PATH'de 'claude' komutu olmalı.")
            else:
                detail = (f"  claude CLI: {'found ✓' if found else 'not found ✗'}\n"
                          f"  Selected model: {cfg.model}\n"
                          f"  Note: 'claude' command must be in PATH.")
            self._safe_update("conn-detail", detail)
        elif idx == 1:  # Claude model
            mc = ["sonnet", "opus", "haiku", "varsayilan"]
            cur = cfg.model if cfg.model in mc else "sonnet"
            cfg.model = mc[(mc.index(cur) + 1) % len(mc)]
            cfg.save()
            self._flash_msg("conn-msg", f"✓ Claude: {cfg.model}")
            self._reload_list("conn-list", self._items())
        elif idx == 2:  # Binance connect
            self._entering_api = True
            self._entering_secret = False
            inp = self.query_one("#conn-input", Input)
            inp.password = False
            inp.placeholder = "Binance API Key (Read-Only only)"
            inp.remove_class("hidden")
            if lang == "tr":
                self._safe_update("conn-detail",
                    "[bold dark_orange]UYARI:[/] Sadece Read-Only key girin!\n"
                    "Trade/withdraw/margin izni OLMAYAN key kullanın.\n"
                    "Secret bir sonraki adımda girilecek — asla görüntülenmez.")
            else:
                self._safe_update("conn-detail",
                    "[bold dark_orange]WARNING:[/] Enter Read-Only API key only!\n"
                    "Use a key WITHOUT trade/withdraw/margin permissions.\n"
                    "Secret will be asked next — never displayed.")
            inp.focus()
        elif idx == 3:  # Disconnect
            cfg.binance_key = ""
            cfg.binance_secret = ""
            cfg.save()
            self._flash_msg("conn-msg", "✓ Binance bağlantısı kesildi." if lang == "tr" else "✓ Binance disconnected.")
            self._safe_update("conn-detail", "")
            self._reload_list("conn-list", self._items())
        elif idx == 4:  # Safety
            self.app.push_screen(SafetyStatusScreen(), self._on_sub)
        elif idx == 5:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        val = event.value.strip()
        event.input.value = ""
        lang = i18n.lang()
        if self._entering_api:
            self._temp_key = val
            self._entering_api = False
            self._entering_secret = True
            inp = self.query_one("#conn-input", Input)
            inp.password = True  # MASKED
            inp.placeholder = "Binance Secret (masked — not stored in logs)"
            self._safe_update("conn-detail",
                "[bold dark_orange]SECRET maskelenmiş.[/]\n"
                "Secret girin. Log veya ekranda gösterilmez." if lang == "tr" else
                "[bold dark_orange]SECRET is masked.[/]\n"
                "Enter secret. Never shown in logs or display.")
            inp.focus()
        elif self._entering_secret:
            self._entering_secret = False
            secret_val = val  # immediately use and discard
            if self._temp_key and secret_val:
                self._cfg.binance_key = self._temp_key
                self._cfg.binance_secret = secret_val
                self._cfg.save()
                self._temp_key = ""
                # secret_val goes out of scope — do NOT log or display it
                inp = self.query_one("#conn-input", Input)
                inp.password = False
                inp.add_class("hidden")
                self._flash_msg("conn-msg", "✓ Binance API kaydedildi." if lang == "tr" else "✓ Binance API saved.")
                self._safe_update("conn-detail", "")
                self._reload_list("conn-list", self._items())
            else:
                self._temp_key = ""
                inp = self.query_one("#conn-input", Input)
                inp.password = False
                inp.add_class("hidden")
                self._flash_msg("conn-msg", "✗ Boş olamaz." if lang == "tr" else "✗ Cannot be empty.")
            try:
                self.query_one("#conn-list", ListView).focus()
            except Exception:
                pass
        else:
            event.input.add_class("hidden")
            try:
                self.query_one("#conn-list", ListView).focus()
            except Exception:
                pass

    def on_key(self, event) -> None:
        if event.key == "escape":
            if self._entering_api or self._entering_secret:
                event.stop()
                self._entering_api = False
                self._entering_secret = False
                self._temp_key = ""
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
        lang = i18n.lang()
        title = "──  CANLI GÜVENLİK DURUMU  ──" if lang == "tr" else "──  LIVE SAFETY STATUS  ──"
        if lang == "tr":
            content = (
                "[bold white on dark_red]  Real Orders: OFF        [/]  "
                "[bold white on dark_red]  Withdraw: NOT SUPPORTED  [/]\n\n"
                "[bold white on dark_red]  Futures: DISABLED        [/]  "
                "[bold white on dark_red]  Margin: DISABLED         [/]\n\n"
                "[bold white on dark_red]  Order API: BLOCKED       [/]  "
                "[bold black on green3]   Paper Mode: ACTIVE       [/]\n\n"
                "[bold cyan]Bu uygulama YALNIZCA PAPER (sanal) işlem yapar.[/]\n"
                "create_order, futures_create_order, margin borrow, withdraw\n"
                "çağrıları REAL_ORDER_DISABLED hatası fırlatır.\n\n"
                "[grey58]Bu koruma kodu içinde hard-coded'dir, devre dışı bırakılamaz.[/]"
            )
        else:
            content = (
                "[bold white on dark_red]  Real Orders: OFF        [/]  "
                "[bold white on dark_red]  Withdraw: NOT SUPPORTED  [/]\n\n"
                "[bold white on dark_red]  Futures: DISABLED        [/]  "
                "[bold white on dark_red]  Margin: DISABLED         [/]\n\n"
                "[bold white on dark_red]  Order API: BLOCKED       [/]  "
                "[bold black on green3]   Paper Mode: ACTIVE       [/]\n\n"
                "[bold cyan]This app executes PAPER (virtual) trades ONLY.[/]\n"
                "create_order, futures_create_order, margin borrow, withdraw\n"
                "calls raise REAL_ORDER_DISABLED error.\n\n"
                "[grey58]This protection is hard-coded and cannot be disabled.[/]"
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
