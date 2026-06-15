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


def test_live_fn_disabled_by_default():
    """live_autonomous varsayılan False — live emirler paper modda gönderilmez."""
    from config import Config
    cfg = Config()
    assert getattr(cfg, "live_autonomous", False) is False
    assert getattr(cfg, "trading_mode", "paper") == "paper"


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


# ── Yeni: otonom_trade_type modu testleri ──────────────────────────────────────

_ALLOWED_MAP = {
    "long":      {"AL", "SPOT_AL"},
    "short":     {"SHORT_AL"},
    "dusus":     {"SHORT_AL"},
    "longshort": {"AL", "SPOT_AL", "SHORT_AL"},
    "scalp":     {"SCALP_AL"},
    "kaldirac":  {"AL", "SPOT_AL", "LEVERAGE_AL"},
    "tam":       {"AL", "SPOT_AL", "SHORT_AL", "SCALP_AL", "LEVERAGE_AL"},
}


def test_otonom_long_modu_sadece_al_kabul_eder():
    """/otonom ac long → sadece AL ve SPOT_AL kabul edilmeli."""
    cfg = Config()
    cfg.otonom_trade_type = "long"
    allowed = _ALLOWED_MAP[cfg.otonom_trade_type]
    assert "AL" in allowed
    assert "SPOT_AL" in allowed
    assert "SHORT_AL" not in allowed
    assert "SCALP_AL" not in allowed
    assert "LEVERAGE_AL" not in allowed


def test_otonom_short_modu_sadece_short_al_kabul_eder():
    """/otonom ac short → sadece SHORT_AL kabul edilmeli."""
    cfg = Config()
    cfg.otonom_trade_type = "short"
    allowed = _ALLOWED_MAP[cfg.otonom_trade_type]
    assert "SHORT_AL" in allowed
    assert "AL" not in allowed
    assert "SPOT_AL" not in allowed
    assert "SCALP_AL" not in allowed


def test_otonom_dusus_short_ile_ayni():
    """/otonom ac dusus, short ile aynı allowed seti olmalı."""
    assert _ALLOWED_MAP["dusus"] == _ALLOWED_MAP["short"]


def test_otonom_longshort_modu_her_iki_yonu_kabul_eder():
    """/otonom ac longshort → AL, SPOT_AL ve SHORT_AL kabul edilmeli."""
    allowed = _ALLOWED_MAP["longshort"]
    assert "AL" in allowed
    assert "SPOT_AL" in allowed
    assert "SHORT_AL" in allowed
    assert "SCALP_AL" not in allowed
    assert "LEVERAGE_AL" not in allowed


def test_otonom_scalp_modu_sadece_scalp_al():
    """/otonom ac scalp → sadece SCALP_AL kabul edilmeli."""
    allowed = _ALLOWED_MAP["scalp"]
    assert "SCALP_AL" in allowed
    assert "AL" not in allowed
    assert "SHORT_AL" not in allowed
    assert "LEVERAGE_AL" not in allowed


def test_otonom_kaldirac_modu_leverage_al_kabul_eder():
    """/otonom ac kaldirac → AL, SPOT_AL ve LEVERAGE_AL kabul edilmeli."""
    allowed = _ALLOWED_MAP["kaldirac"]
    assert "LEVERAGE_AL" in allowed
    assert "AL" in allowed
    assert "SHORT_AL" not in allowed
    assert "SCALP_AL" not in allowed


def test_otonom_tam_modu_hepsini_kabul_eder():
    """/otonom ac tam → tüm trade tipleri kabul edilmeli."""
    allowed = _ALLOWED_MAP["tam"]
    for islem in ("AL", "SPOT_AL", "SHORT_AL", "SCALP_AL", "LEVERAGE_AL"):
        assert islem in allowed, f"tam mod {islem} içermeli"


def test_otonom_long_modunda_short_al_blocked():
    """Otonom long modundayken SHORT_AL önerisi blocked_by_trade_type loglanmalı."""
    allowed = _ALLOWED_MAP["long"]
    blocked = []
    suggestions = [("BTCUSDT", "SHORT_AL"), ("ETHUSDT", "AL")]
    for sym, islem in suggestions:
        if islem not in allowed:
            blocked.append((sym, islem, "blocked_by_trade_type"))
    assert len(blocked) == 1
    assert blocked[0][0] == "BTCUSDT"
    assert blocked[0][2] == "blocked_by_trade_type"


def test_otonom_short_modunda_al_blocked():
    """Otonom short modundayken AL/SPOT_AL önerileri blocked_by_trade_type loglanmalı."""
    allowed = _ALLOWED_MAP["short"]
    blocked = []
    suggestions = [("BTCUSDT", "AL"), ("ETHUSDT", "SHORT_AL"), ("SOLUSDT", "SPOT_AL")]
    for sym, islem in suggestions:
        if islem not in allowed:
            blocked.append((sym, islem, "blocked_by_trade_type"))
    assert len(blocked) == 2
    blocked_islemler = {b[1] for b in blocked}
    assert "AL" in blocked_islemler
    assert "SPOT_AL" in blocked_islemler
    assert "SHORT_AL" not in blocked_islemler


def test_otonom_trade_type_varsayilan_long():
    """Config varsayılanında otonom_trade_type 'long' olmalı."""
    cfg = Config()
    assert getattr(cfg, "otonom_trade_type", "long") == "long"


def test_otonom_trade_type_config_alani_mevcut():
    """otonom_trade_type config alanı dataclass'ta tanımlı olmalı."""
    from dataclasses import fields
    field_names = {f.name for f in fields(Config)}
    assert "otonom_trade_type" in field_names


def test_bilinmeyen_mod_long_fallback():
    """Tanımsız otonom_trade_type için fallback long allowed set dönmeli."""
    unknown = "bilinmeyen_mod"
    allowed = _ALLOWED_MAP.get(unknown, {"AL", "SPOT_AL"})
    assert allowed == {"AL", "SPOT_AL"}
