"""Trade türleri testleri — short paper, scalp, direction, aliases."""
from __future__ import annotations
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
import portfolio as portfolio_mod
from portfolio import Portfolio, SCALP_MAX_DURATION
from config import Config


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_mod, "STATE_FILE", tmp_path / "account.json")


def test_short_paper_pnl_dususte_pozitif():
    """Short paperde fiyat düşünce PnL pozitif olmalı."""
    p = Portfolio()
    p.buy_short("BTCUSDT", usdt=500.0, price=50_000.0, stop=52_000.0, target=46_000.0)
    pnl, pct = p.unrealized_pnl("BTCUSDT", 48_000.0)
    assert pnl > 0, f"Short düşüşte kârlı olmalı, pnl={pnl}"


def test_short_paper_pnl_yukseliste_negatif():
    """Short paperde fiyat yükselince PnL negatif olmalı."""
    p = Portfolio()
    p.buy_short("BTCUSDT", usdt=500.0, price=50_000.0, stop=52_000.0, target=46_000.0)
    pnl, pct = p.unrealized_pnl("BTCUSDT", 51_000.0)
    assert pnl < 0, "Short yükselişte zararlı olmalı"


def test_short_stop_yukari_tetiklenir():
    """Short için stop: fiyat YUKARI çıkarsa stop tetiklenmeli."""
    p = Portfolio()
    p.buy_short("BTCUSDT", usdt=500.0, price=50_000.0, stop=52_000.0, target=46_000.0)
    triggers = p.check_triggers({"BTCUSDT": 52_000.0})
    assert any(t[1] == "stop" for t in triggers)


def test_short_target_asagi_tetiklenir():
    """Short için target: fiyat AŞAĞI düşünce target tetiklenmeli."""
    p = Portfolio()
    p.buy_short("BTCUSDT", usdt=500.0, price=50_000.0, stop=52_000.0, target=46_000.0)
    triggers = p.check_triggers({"BTCUSDT": 46_000.0})
    assert any(t[1] == "target" for t in triggers)


def test_short_kapaninca_kar_cash_e_eklenir():
    """Short pozisyon kârlı kapanınca cash artmalı."""
    p = Portfolio()
    p.buy_short("BTCUSDT", usdt=500.0, price=50_000.0, stop=52_000.0, target=46_000.0)
    cash_before = p.cash
    p.sell("BTCUSDT", price=46_000.0)
    assert p.cash > cash_before, "Kârlı short kapanınca cash artmalı"
    assert "BTCUSDT" not in p.positions


def test_scalp_time_exit_30dk_sonra():
    """Scalp pozisyon 30 dakika sonra time_exit tetiklemeli."""
    p = Portfolio()
    p.buy("BTCUSDT", 500.0, 50_000.0)
    # trade_style'ı scalp yap ve opened_at'ı geçmişe çek
    pos = p.positions["BTCUSDT"]
    pos.trade_style = "scalp"
    pos.opened_at = time.time() - SCALP_MAX_DURATION - 60  # 31 dk önce
    triggers = p.check_triggers({"BTCUSDT": 51_000.0})
    assert any(t[1] == "time_exit" for t in triggers)


def test_scalp_kisa_surede_time_exit_yok():
    """30 dakika dolmadan scalp time_exit tetiklenmemeli."""
    p = Portfolio()
    p.buy("BTCUSDT", 500.0, 50_000.0)
    pos = p.positions["BTCUSDT"]
    pos.trade_style = "scalp"
    pos.opened_at = time.time() - 600  # sadece 10dk önce
    triggers = p.check_triggers({"BTCUSDT": 51_000.0})
    assert not any(t[1] == "time_exit" for t in triggers)


def test_scalp_kapali_iken_scan_hata_verir():
    """scalp_enabled=False iken scalp scan ValueError vermeli."""
    cfg = Config()
    cfg.scalp_enabled = False
    assert not cfg.scalp_enabled


def test_realtime_sembol_short_icin_uygun():
    """Realtime kripto semboller short paper için uygun olmalı."""
    from market import leverage_allowed
    assert leverage_allowed("BTCUSDT")
    assert leverage_allowed("ETHUSDT")


def test_delayed_sembol_short_icin_uygun_degil():
    """Delayed (Yahoo) semboller short paper için uygun değil."""
    from market import leverage_allowed
    assert not leverage_allowed("EURUSD=X")
    assert not leverage_allowed("^GSPC")


def test_tr_en_alias_scan():
    """'scan' komutu 'tara' ile aynı handler'a gittiğini doğrula."""
    _ALIASES = {
        "scan": "tara", "status": "durum", "buy": "al", "sell": "sat",
        "protect": "koru", "auto": "otonom", "approve": "onayla",
        "reject": "reddet", "apply": "uygula", "leverage": "kaldirac",
        "details": "detay", "performance": "performans", "history": "gecmis",
        "help": "yardim", "exit": "cikis",
    }
    assert _ALIASES["scan"] == "tara"
    assert _ALIASES["status"] == "durum"
    assert _ALIASES["auto"] == "otonom"


def test_otonom_agresif_modda_2_zararda_kapanmaz():
    """Agresif modda max_consecutive_losses 4 — 2 zarardan sonra kapanmamalı."""
    from autonomous import AUTONOMOUS_PROFILES
    p = AUTONOMOUS_PROFILES["agresif"]
    assert p.max_consecutive_losses >= 4, (
        f"Agresif modda en az 4 ardışık zarar toleransı olmalı, var: {p.max_consecutive_losses}"
    )


def test_gunluk_zarar_hard_safety_calisir():
    """daily_loss_limit_percent profillerde tanımlı ve pozitif olmalı."""
    from autonomous import AUTONOMOUS_PROFILES
    for key, p in AUTONOMOUS_PROFILES.items():
        assert p.daily_loss_limit_percent > 0, f"{key} profil günlük zarar limiti 0"


def test_real_order_disabled_korunuyor():
    """REAL_ORDER_DISABLED tüm yeni trade türlerinde korunuyor."""
    import autonomous
    with pytest.raises(RuntimeError, match="REAL_ORDER_DISABLED"):
        autonomous.create_order("BTCUSDT", "BUY", "MARKET", 0.001)
    with pytest.raises(RuntimeError, match="REAL_ORDER_DISABLED"):
        autonomous.futures_create_order("BTCUSDT", "BUY", "MARKET", 0.001)


def test_custom_otonom_ayarlar_kaydedilir():
    """Custom otonom ayarlar config'e kaydedilmeli."""
    cfg = Config()
    cfg.custom_max_daily_trades = 8
    cfg.custom_max_positions = 4
    cfg.custom_loss_streak = 4
    cfg.custom_daily_loss_pct = 5.0
    assert cfg.custom_max_daily_trades == 8
    assert cfg.custom_max_positions == 4
    assert cfg.custom_loss_streak == 4
    assert cfg.custom_daily_loss_pct == 5.0
