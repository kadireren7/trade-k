"""Zarar-kes / kâr-al (otomatik kapatma) testleri."""
import pytest

import ai
import portfolio as portfolio_mod
from portfolio import Portfolio, sanitize_levels


@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_mod, "STATE_FILE", tmp_path / "account.json")


# ---------- seviye doğrulama ----------

def test_sanitize_valid_levels_pass_through():
    stop, target = sanitize_levels(100.0, 95.0, 112.0)
    assert stop == 95.0 and target == 112.0


def test_sanitize_fixes_nonsense_levels():
    # stop girişin üstünde, hedef girişin altında → varsayılanlara çekilir
    stop, target = sanitize_levels(100.0, 120.0, 90.0)
    assert stop == pytest.approx(95.0)    # %5 altı
    assert target == pytest.approx(110.0)  # %10 üstü


def test_sanitize_fixes_zero_and_extreme():
    stop, target = sanitize_levels(100.0, 0, 0)
    assert stop == pytest.approx(95.0) and target == pytest.approx(110.0)
    # aşırı uzak stop (%-40) ve hedef (+%200) kabul edilmez
    stop, target = sanitize_levels(100.0, 60.0, 300.0)
    assert stop == pytest.approx(95.0) and target == pytest.approx(110.0)


# ---------- tetikleyiciler ----------

def make_protected_portfolio():
    p = Portfolio()
    p.buy("BTCUSDT", 1000, 100.0)
    p.set_protection("BTCUSDT", stop=95.0, target=112.0)
    return p


def test_no_trigger_between_levels():
    p = make_protected_portfolio()
    assert p.check_triggers({"BTCUSDT": 100.0}) == []
    assert p.check_triggers({"BTCUSDT": 95.01}) == []
    assert p.check_triggers({"BTCUSDT": 111.99}) == []


def test_stop_trigger():
    p = make_protected_portfolio()
    assert p.check_triggers({"BTCUSDT": 94.5}) == [("BTCUSDT", "stop", 94.5)]
    assert p.check_triggers({"BTCUSDT": 95.0}) == [("BTCUSDT", "stop", 95.0)]


def test_target_trigger():
    p = make_protected_portfolio()
    assert p.check_triggers({"BTCUSDT": 112.0}) == [("BTCUSDT", "target", 112.0)]


def test_unprotected_position_never_triggers():
    p = Portfolio()
    p.buy("ETHUSDT", 500, 100.0)
    assert p.check_triggers({"ETHUSDT": 1.0}) == []


def test_trigger_missing_price_skipped():
    p = make_protected_portfolio()
    assert p.check_triggers({}) == []


def test_protection_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_mod, "STATE_FILE", tmp_path / "acc2.json")
    p = Portfolio()
    p.buy("BTCUSDT", 1000, 100.0)
    p.set_protection("BTCUSDT", 95.0, 112.0)
    p2 = Portfolio.load()
    assert p2.positions["BTCUSDT"].stop == 95.0
    assert p2.positions["BTCUSDT"].target == 112.0


def test_set_protection_requires_position():
    p = Portfolio()
    with pytest.raises(ValueError):
        p.set_protection("YOKUSDT", 1.0, 2.0)


# ---------- Claude yanıtı ayrıştırma ----------

def test_parse_protection():
    text = 'Analiz...\nKORUMA: {"zarar_kes": 4010.5, "kar_al": 4180.0, "gerekce": "destek altı"}'
    prot = ai.parse_protection(text)
    assert prot.zarar_kes == 4010.5
    assert prot.kar_al == 4180.0
    assert prot.gerekce == "destek altı"


def test_parse_protection_garbage():
    assert ai.parse_protection("json yok") is None
    assert ai.parse_protection("KORUMA: {bozuk") is None


def test_suggestion_parses_stop_target():
    text = ('ONERILER: [{"islem":"AL","sembol":"GC=F","tutar_usdt":600,'
            '"basari_yuzdesi":62,"zarar_kes":4010.0,"kar_al":4180.0,"gerekce":"x"}]')
    s = ai.parse_suggestions(text)[0]
    assert s.zarar_kes == 4010.0 and s.kar_al == 4180.0


def test_suggestion_missing_stop_target_defaults_zero():
    text = ('ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
            '"basari_yuzdesi":55,"gerekce":"x"}]')
    s = ai.parse_suggestions(text)[0]
    assert s.zarar_kes == 0.0 and s.kar_al == 0.0
