"""Menü sistemi ve ekran testleri."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import inspect


def test_auth_screen_stops_event():
    """_AuthScreen event.stop() çağırmalı."""
    from screens import _AuthScreen
    src = inspect.getsource(_AuthScreen.on_input_submitted)
    assert "event.stop()" in src


def test_login_screen_stops_event():
    """LoginScreen event.stop() çağırmalı."""
    from screens import LoginScreen
    src = inspect.getsource(LoginScreen.on_input_submitted)
    assert "event.stop()" in src


def test_setup_screen_stops_event():
    """SetupScreen event.stop() çağırmalı."""
    from screens import SetupScreen
    src = inspect.getsource(SetupScreen.on_input_submitted)
    assert "event.stop()" in src


def test_confirm_screen_stops_event():
    """ConfirmScreen event.stop() çağırmalı."""
    from screens import ConfirmScreen
    src = inspect.getsource(ConfirmScreen.on_input_submitted)
    assert "event.stop()" in src


def test_splash_menu_number_bindings():
    """SplashMenuScreen 1-7 tuş binding'leri var."""
    from screens import SplashMenuScreen
    # Check BINDINGS has 1-7
    keys = [b.key for b in SplashMenuScreen.BINDINGS]
    for n in "1234567":
        assert n in keys, f"SplashMenuScreen {n} binding eksik"


def test_settings_language_toggle(tmp_path, monkeypatch):
    """Settings dil değişikliği config'e kaydedilmeli."""
    import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", tmp_path / "config.json")
    cfg = cfg_mod.Config(language="tr", name="test")
    cfg.pw_salt = "aa"
    cfg.pw_hash = "bb"
    cfg.save()

    # Simulate language toggle
    original = cfg.language
    cfg.language = "en" if cfg.language == "tr" else "tr"
    cfg.save()

    # Reload and verify
    loaded = cfg_mod.Config.load()
    assert loaded.language != original


def test_settings_scalp_toggle(tmp_path, monkeypatch):
    """Scalp toggle config'e yazılmalı."""
    import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", tmp_path / "config.json")
    cfg = cfg_mod.Config()
    cfg.pw_salt = "aa"; cfg.pw_hash = "bb"; cfg.save()

    cfg.scalp_enabled = True
    cfg.save()
    loaded = cfg_mod.Config.load()
    assert loaded.scalp_enabled is True

    cfg.scalp_enabled = False
    cfg.save()
    loaded2 = cfg_mod.Config.load()
    assert loaded2.scalp_enabled is False


def test_settings_leverage_toggle(tmp_path, monkeypatch):
    """Leverage toggle config'e yazılmalı."""
    import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", tmp_path / "config.json")
    cfg = cfg_mod.Config()
    cfg.pw_salt = "aa"; cfg.pw_hash = "bb"; cfg.save()

    cfg.leverage_enabled = True
    cfg.save()
    loaded = cfg_mod.Config.load()
    assert loaded.leverage_enabled is True


def test_settings_model_change(tmp_path, monkeypatch):
    """Claude model değişikliği config'e kaydedilmeli."""
    import config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CONFIG_FILE", tmp_path / "config.json")
    cfg = cfg_mod.Config(model="sonnet")
    cfg.pw_salt = "aa"; cfg.pw_hash = "bb"; cfg.save()

    cfg.model = "opus"
    cfg.save()
    loaded = cfg_mod.Config.load()
    assert loaded.model == "opus"


def test_config_theme_field():
    """Config.theme alanı var ve varsayılanı 'cyber'."""
    from config import Config
    cfg = Config()
    assert hasattr(cfg, "theme")
    assert cfg.theme == "cyber"


def test_autonomous_control_uses_setup_wizard():
    """AutonomousControlScreen başlatmak için AutonomousSetupScreen sihirbazını kullanır."""
    from screens import AutonomousControlScreen
    src = inspect.getsource(AutonomousControlScreen)
    assert "AutonomousSetupScreen" in src


def test_autonomous_setup_screen_exists():
    """AutonomousSetupScreen sihirbazı tanımlı ve adımları içeriyor."""
    from screens import AutonomousSetupScreen
    src = inspect.getsource(AutonomousSetupScreen)
    assert "REAL_ORDER_DISABLED" in src
    assert "welcome" in src
    assert "confirm" in src
    assert "dismiss" in src


def test_connections_secret_not_logged():
    """ConnectionsScreen secret'ı log'a veya print'e yazmaz."""
    from screens import ConnectionsScreen
    src = inspect.getsource(ConnectionsScreen)
    # secret_val should NOT appear in any log/print/write call
    # The key check: no "log(secret" or "print(secret" or "write(secret"
    assert "log(secret" not in src
    assert "print(secret" not in src
    # Also verify password=True masking is applied
    assert "inp.password = True" in src


def test_connections_secret_masking():
    """ConnectionsScreen API secret alanı masked (password=True)."""
    from screens import ConnectionsScreen
    src = inspect.getsource(ConnectionsScreen)
    assert "password = True" in src


def test_safety_status_screen_shows_off():
    """SafetyStatusScreen Real Orders OFF mesajı içeriyor."""
    from screens import SafetyStatusScreen
    src = inspect.getsource(SafetyStatusScreen)
    assert "Real Orders: OFF" in src
    assert "REAL_ORDER_DISABLED" in src


def test_risk_limits_screen_input_stops_event():
    """RiskLimitsScreen input submitted event.stop() çağırmalı."""
    from screens import RiskLimitsScreen
    src = inspect.getsource(RiskLimitsScreen.on_input_submitted)
    assert "event.stop()" in src


def test_splash_menu_has_7_items():
    """SplashMenuScreen 7 menü öğesi içeriyor."""
    from config import Config
    cfg = Config(name="test")
    screen = SplashMenuScreen_check = __import__("screens").SplashMenuScreen
    # Check _menu_items has 7 items
    import i18n
    i18n.set_language("tr")
    tmp_screen = screen.__new__(screen)
    tmp_screen._cfg = cfg
    items = tmp_screen._menu_items()
    assert len(items) == 7


def test_menu_screen_go_back_action():
    """_MenuScreen action_go_back dismiss(None) çağırıyor."""
    from screens import _MenuScreen
    src = inspect.getsource(_MenuScreen.action_go_back)
    assert "dismiss(None)" in src


def test_real_order_disabled_still_active():
    """REAL_ORDER_DISABLED koruması hala çalışıyor."""
    import autonomous
    import pytest
    with pytest.raises(RuntimeError, match="REAL_ORDER_DISABLED"):
        autonomous.create_order("BTCUSDT", "BUY", "MARKET", 0.001)
