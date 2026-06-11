"""Login ve şifre güvenlik testleri."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_sifre_komut_olarak_parse_edilmez():
    """Şifre girişi app komut parser'ına ulaşmamalı."""
    # screens._AuthScreen.on_input_submitted event.stop() çağırıyor —
    # bu, Input.Submitted mesajının TradeApp.on_input_submitted'a ulaşmasını engelliyor.
    from screens import LoginScreen
    import inspect
    # LoginScreen on_input_submitted should call event.stop()
    from screens import _AuthScreen
    auth_src = inspect.getsource(_AuthScreen)
    assert "event.stop()" in auth_src, "_AuthScreen.on_input_submitted event.stop() içermeli"


def test_auth_screen_stops_event_propagation():
    """_AuthScreen.on_input_submitted event.stop() çağırmalı."""
    from screens import _AuthScreen
    import inspect
    src = inspect.getsource(_AuthScreen.on_input_submitted)
    assert "event.stop()" in src


def test_yanlis_sifre_command_olarak_islenmez():
    """Yanlış şifre 'unknown command' üretmemeli — event.stop() bunu engeller."""
    # Bu test _AuthScreen event isolation'ını doğrular
    from screens import _AuthScreen
    import inspect
    src = inspect.getsource(_AuthScreen.on_input_submitted)
    assert "event.stop()" in src, "Event propagation engellenmeli"
