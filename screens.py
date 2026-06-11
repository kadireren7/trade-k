"""Açılış ekranları — ilk kurulum sihirbazı ve şifreli giriş.

SetupScreen: dil → isim → şifre (x2) → model. Sonuç: kayıtlı Config.
LoginScreen: şifre sorar; 3 yanlışta False döner (app kapanır).
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Middle, Vertical
from textual.screen import Screen
from textual.widgets import Input, Static

import i18n
from config import MODELS, MIN_PW_LEN, Config
from i18n import t

_MODEL_ORDER = ["opus", "sonnet", "haiku", "varsayilan"]


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
