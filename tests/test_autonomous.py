"""Otonom mod + risk profili testleri."""
import asyncio
from pathlib import Path

import pytest

import ai
import market
import modes
from autonomous import (
    AUTONOMOUS_PROFILES,
    DEFAULT_AUTONOMOUS_MODE,
    AutonomousEngine,
    AutonomousState,
)
from portfolio import Portfolio
import portfolio as portfolio_mod


# ── fixtures ────────────────────────────────────────────────────────────────

class MockFeed:
    def __init__(self, prices: dict[str, float] | None = None):
        prices = prices or {}

        class T:
            def __init__(self, p):
                self.price = p

        self.tickers = {s: T(p) for s, p in prices.items()}

    def price(self, sym: str) -> float | None:
        t = self.tickers.get(sym)
        return t.price if t else None


class MockCfg:
    """Test için minimal config mock'u."""
    def __init__(self, autonomous_mode: str = "dengeli"):
        self.model_id = None
        self.mode = "standart"
        self.autonomous_mode = autonomous_mode

    def save(self) -> None:
        pass


@pytest.fixture(autouse=True)
def isolate_portfolio(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_mod, "STATE_FILE", tmp_path / "account.json")


@pytest.fixture
def portfolio():
    return Portfolio()


@pytest.fixture
def engine(portfolio, tmp_path):
    feed = MockFeed({"BTCUSDT": 50000.0, "GC=F": 3500.0})
    logs = []
    eng = AutonomousEngine(
        portfolio=portfolio,
        feed=feed,
        tracker=type("T", (), {"recs": []})(),
        cfg=MockCfg("dengeli"),
        log_fn=logs.append,
        watchlist_fn=lambda: ["BTCUSDT"],
        state_path=tmp_path / "auto_state.json",
        log_path=tmp_path / "auto_log.jsonl",
    )
    eng._logs = logs
    return eng


def make_engine(portfolio, tmp_path, autonomous_mode: str = "dengeli"):
    """Belirtilen modla engine oluşturur."""
    feed = MockFeed({"BTCUSDT": 50000.0, "ETHUSDT": 2000.0,
                     "SOLUSDT": 100.0, "GC=F": 3500.0})
    logs = []
    return AutonomousEngine(
        portfolio=portfolio,
        feed=feed,
        tracker=type("T", (), {"recs": []})(),
        cfg=MockCfg(autonomous_mode),
        log_fn=logs.append,
        watchlist_fn=lambda: ["BTCUSDT"],
        state_path=tmp_path / f"auto_state_{autonomous_mode}.json",
        log_path=tmp_path / f"auto_log_{autonomous_mode}.jsonl",
    )


# ── manuel mod sistemi testleri ──────────────────────────────────────────────

def test_sniper_modu_kaldirildi():
    assert "sniper" not in modes.MODES


def test_blitz_modu_kaldirildi():
    assert "blitz" not in modes.MODES


def test_inferno_modu_kaldirildi():
    assert "inferno" not in modes.MODES


def test_tek_standart_mod_var():
    assert "standart" in modes.MODES
    assert len(modes.MODES) == 1


def test_bilinmeyen_mod_standarta_dusuyor():
    m = modes.get("sniper")
    assert m.key == "standart"

    m2 = modes.get("blitz")
    assert m2.key == "standart"


# ── otonom mod profil testleri ───────────────────────────────────────────────

def test_varsayilan_otonom_mod_dengeli():
    assert DEFAULT_AUTONOMOUS_MODE == "dengeli"


def test_otonom_profiller_var():
    assert "guvenli" in AUTONOMOUS_PROFILES
    assert "dengeli" in AUTONOMOUS_PROFILES
    assert "agresif" in AUTONOMOUS_PROFILES


def test_guvenli_profil_degerleri():
    p = AUTONOMOUS_PROFILES["guvenli"]
    assert p.max_open_positions == 2
    assert p.max_trade_percent == 0.08
    assert p.max_daily_trades == 3
    assert p.min_confidence == 60
    assert p.min_risk_reward == 1.8
    assert p.max_consecutive_losses == 2
    assert p.daily_loss_limit_percent == 2.0


def test_dengeli_profil_degerleri():
    p = AUTONOMOUS_PROFILES["dengeli"]
    assert p.max_open_positions == 4
    assert p.max_trade_percent == 0.12
    assert p.max_daily_trades == 6
    assert p.min_confidence == 50
    assert p.min_risk_reward == 1.3
    assert p.max_consecutive_losses == 3
    assert p.daily_loss_limit_percent == 4.0


def test_agresif_profil_degerleri():
    p = AUTONOMOUS_PROFILES["agresif"]
    assert p.max_open_positions == 6
    assert p.max_trade_percent == 0.18
    assert p.max_daily_trades == 12
    assert p.min_confidence == 42
    assert p.min_risk_reward == 1.1
    assert p.max_consecutive_losses == 5
    assert p.daily_loss_limit_percent == 6.0


def test_engine_varsayilan_profil_dengeli(engine):
    assert engine.profile.key == "dengeli"


def test_otonom_mod_guvenli_ayarlanir(engine):
    msg = engine.set_mode("guvenli")
    assert "GÜVENLİ" in msg
    assert engine.profile.key == "guvenli"
    assert engine.cfg.autonomous_mode == "guvenli"


def test_otonom_mod_dengeli_ayarlanir(engine):
    engine.set_mode("guvenli")  # önce değiştir
    msg = engine.set_mode("dengeli")
    assert "DENGELİ" in msg
    assert engine.profile.key == "dengeli"


def test_otonom_mod_agresif_ayarlanir(engine):
    msg = engine.set_mode("agresif")
    assert "AGRESİF" in msg
    assert engine.profile.key == "agresif"
    assert engine.cfg.autonomous_mode == "agresif"


def test_gecersiz_mod_hata_mesaji(engine):
    msg = engine.set_mode("sniper")
    assert "Geçersiz" in msg


# ── pozisyon limiti testleri ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guvenli_modda_2_pozisyon_limiti(portfolio, tmp_path, monkeypatch):
    """Güvenli modda max 2 pozisyon — 2 açıkken tarama atlanır."""
    eng = make_engine(portfolio, tmp_path, "guvenli")
    eng.state.enabled = True
    eng.state.daily_date = "2026-06-11"

    portfolio.buy("BTCUSDT", 500, 50000.0)
    portfolio.buy("ETHUSDT", 300, 2000.0)  # limit doldu

    called = []

    async def mock_scan(*a, **kw):
        called.append(True)
        return ""

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert not called, "Güvenli modda 2 pozisyon doluyken tarama yapılmamalı"
    assert len(portfolio.positions) == 2


@pytest.mark.asyncio
async def test_dengeli_modda_4_pozisyon_limiti(portfolio, tmp_path, monkeypatch):
    """Dengeli modda max 4 pozisyon — 4 açıkken tarama atlanır."""
    eng = make_engine(portfolio, tmp_path, "dengeli")
    eng.state.enabled = True
    eng.state.daily_date = "2026-06-11"

    portfolio.buy("BTCUSDT", 200, 50000.0)
    portfolio.buy("ETHUSDT", 200, 2000.0)
    portfolio.buy("SOLUSDT", 200, 100.0)
    portfolio.buy("BNBUSDT", 200, 600.0)

    called = []

    async def mock_scan(*a, **kw):
        called.append(True)
        return ""

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert not called, "Dengeli modda 4 pozisyon doluyken tarama yapılmamalı"


@pytest.mark.asyncio
async def test_agresif_modda_6_pozisyon_limiti(portfolio, tmp_path, monkeypatch):
    """Agresif modda max 6 pozisyon — 6 açıkken tarama atlanır."""
    eng = make_engine(portfolio, tmp_path, "agresif")
    eng.state.enabled = True
    eng.state.daily_date = "2026-06-11"

    portfolio.buy("BTCUSDT", 100, 50000.0)
    portfolio.buy("ETHUSDT", 100, 2000.0)
    portfolio.buy("SOLUSDT", 100, 100.0)
    portfolio.buy("BNBUSDT", 100, 600.0)
    portfolio.buy("XRPUSDT", 100, 2.0)
    portfolio.buy("AVAXUSDT", 100, 40.0)

    called = []

    async def mock_scan(*a, **kw):
        called.append(True)
        return ""

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert not called, "Agresif modda 6 pozisyon doluyken tarama yapılmamalı"


@pytest.mark.asyncio
async def test_agresif_modda_4_pozisyon_varsa_tarama_devam_eder(portfolio, tmp_path, monkeypatch):
    """Agresif modda 4 pozisyon varken tarama devam etmeli (limit 6)."""
    eng = make_engine(portfolio, tmp_path, "agresif")
    eng.state.enabled = True
    eng.state.daily_date = "2026-06-11"
    eng.state.daily_start_equity = portfolio.cash

    portfolio.buy("BTCUSDT", 200, 50000.0)
    portfolio.buy("ETHUSDT", 200, 2000.0)
    portfolio.buy("SOLUSDT", 200, 100.0)
    portfolio.buy("BNBUSDT", 200, 600.0)

    called = []

    async def mock_scan(*a, **kw):
        called.append(True)
        return 'ONERILER: []'

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert called, "Agresif modda 4 pozisyon varken tarama yapılmalı (limit 6)"


# ── confidence eşiği testleri ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guvenli_mod_confidence_59_atlar(portfolio, tmp_path, monkeypatch):
    """Güvenli modda confidence < 60 olan aday atlanır."""
    eng = make_engine(portfolio, tmp_path, "guvenli")
    eng.state.enabled = True
    eng.state.daily_date = "2026-06-11"

    mock_response = (
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":59,"zarar_kes":49000,"kar_al":53000,"gerekce":"test"}]'
    )

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert len(portfolio.positions) == 0, "confidence 59 < 60 → güvenli modda atlanmalı"


@pytest.mark.asyncio
async def test_guvenli_mod_confidence_60_kabul_eder(portfolio, tmp_path, monkeypatch):
    """Güvenli modda confidence = 60 olan aday kabul edilir (R/R uygun ise)."""
    eng = make_engine(portfolio, tmp_path, "guvenli")
    eng.state.enabled = True
    eng.state.daily_date = "2026-06-11"
    eng.state.daily_start_equity = portfolio.cash

    mock_response = (
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":60,"zarar_kes":49000,"kar_al":53000,"gerekce":"güçlü sinyal"}]'
    )
    # BTC=50000, stop=49000 (risk=1000), hedef=53000 (gain=3000) → R/R=3.0 ≥ 1.8 ✓

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert len(portfolio.positions) == 1, "confidence 60 = min → güvenli modda kabul edilmeli"


@pytest.mark.asyncio
async def test_dengeli_mod_confidence_49_atlar(portfolio, tmp_path, monkeypatch):
    """Dengeli modda confidence < 50 olan aday atlanır."""
    eng = make_engine(portfolio, tmp_path, "dengeli")
    eng.state.enabled = True
    eng.state.daily_date = "2026-06-11"

    mock_response = (
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":49,"zarar_kes":49000,"kar_al":52500,"gerekce":"test"}]'
    )

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert len(portfolio.positions) == 0, "confidence 49 < 50 → dengeli modda atlanmalı"


@pytest.mark.asyncio
async def test_agresif_mod_confidence_41_atlar(portfolio, tmp_path, monkeypatch):
    """Agresif modda confidence < 42 olan aday atlanır."""
    eng = make_engine(portfolio, tmp_path, "agresif")
    eng.state.enabled = True
    eng.state.daily_date = "2026-06-11"

    mock_response = (
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":41,"zarar_kes":49000,"kar_al":52000,"gerekce":"test"}]'
    )

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert len(portfolio.positions) == 0, "confidence 41 < 42 → agresif modda atlanmalı"


@pytest.mark.asyncio
async def test_agresif_mod_confidence_42_kabul_eder(portfolio, tmp_path, monkeypatch):
    """Agresif modda confidence = 42 olan aday kabul edilir (R/R uygun ise)."""
    eng = make_engine(portfolio, tmp_path, "agresif")
    eng.state.enabled = True
    eng.state.daily_date = "2026-06-11"
    eng.state.daily_start_equity = portfolio.cash

    mock_response = (
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":42,"zarar_kes":49000,"kar_al":52300,"gerekce":"momentum"}]'
    )
    # BTC=50000, stop=49000 (risk=1000), hedef=52300 (gain=2300) → R/R=2.3 ≥ 1.1 ✓

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert len(portfolio.positions) == 1, "confidence 42 = min → agresif modda kabul edilmeli"


# ── risk/reward eşiği testleri ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guvenli_mod_rr_1_7_atlar(portfolio, tmp_path, monkeypatch):
    """Güvenli modda R/R < 1.8 olan aday atlanır."""
    eng = make_engine(portfolio, tmp_path, "guvenli")
    eng.state.enabled = True
    eng.state.daily_date = "2026-06-11"

    mock_response = (
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":70,"zarar_kes":49000,"kar_al":51700,"gerekce":"test"}]'
    )
    # BTC=50000, stop=49000 (risk=1000), hedef=51700 (gain=1700) → R/R=1.7 < 1.8 ✗

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert len(portfolio.positions) == 0, "R/R 1.7 < 1.8 → güvenli modda atlanmalı"


@pytest.mark.asyncio
async def test_dengeli_mod_rr_1_2_atlar(portfolio, tmp_path, monkeypatch):
    """Dengeli modda R/R < 1.3 olan aday atlanır."""
    eng = make_engine(portfolio, tmp_path, "dengeli")
    eng.state.enabled = True
    eng.state.daily_date = "2026-06-11"

    mock_response = (
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":60,"zarar_kes":49500,"kar_al":50600,"gerekce":"test"}]'
    )
    # BTC=50000, stop=49500 (risk=500), hedef=50600 (gain=600) → R/R=1.2 < 1.3 ✗

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert len(portfolio.positions) == 0, "R/R 1.2 < 1.3 → dengeli modda atlanmalı"


@pytest.mark.asyncio
async def test_agresif_mod_rr_1_0_atlar(portfolio, tmp_path, monkeypatch):
    """Agresif modda R/R < 1.1 olan aday atlanır."""
    eng = make_engine(portfolio, tmp_path, "agresif")
    eng.state.enabled = True
    eng.state.daily_date = "2026-06-11"

    mock_response = (
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":55,"zarar_kes":49500,"kar_al":50500,"gerekce":"test"}]'
    )
    # BTC=50000, stop=49500 (risk=500), hedef=50500 (gain=500) → R/R=1.0 < 1.1 ✗

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert len(portfolio.positions) == 0, "R/R 1.0 < 1.1 → agresif modda atlanmalı"


# ── günlük işlem limiti testleri ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guvenli_mod_gunluk_3_islem_limiti(portfolio, tmp_path, monkeypatch):
    """Güvenli modda günlük 3 işlem dolunca tarama atlanır."""
    eng = make_engine(portfolio, tmp_path, "guvenli")
    eng.state.enabled = True
    eng.state.daily_trades = 3  # limit doldu

    called = []

    async def mock_scan(*a, **kw):
        called.append(True)
        return ""

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert not called, "Güvenli modda 3 işlem doluyken tarama yapılmamalı"


@pytest.mark.asyncio
async def test_dengeli_mod_gunluk_6_islem_limiti(portfolio, tmp_path, monkeypatch):
    """Dengeli modda günlük 6 işlem dolunca tarama atlanır."""
    eng = make_engine(portfolio, tmp_path, "dengeli")
    eng.state.enabled = True
    eng.state.daily_trades = 6  # limit doldu

    called = []

    async def mock_scan(*a, **kw):
        called.append(True)
        return ""

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert not called, "Dengeli modda 6 işlem doluyken tarama yapılmamalı"


@pytest.mark.asyncio
async def test_agresif_mod_gunluk_12_islem_limiti(portfolio, tmp_path, monkeypatch):
    """Agresif modda günlük 12 işlem dolunca tarama atlanır."""
    eng = make_engine(portfolio, tmp_path, "agresif")
    eng.state.enabled = True
    eng.state.daily_trades = 12  # limit doldu

    called = []

    async def mock_scan(*a, **kw):
        called.append(True)
        return ""

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert not called, "Agresif modda 12 işlem doluyken tarama yapılmamalı"


@pytest.mark.asyncio
async def test_agresif_mod_10_islem_varken_tarama_devam_eder(portfolio, tmp_path, monkeypatch):
    """Agresif modda 10 işlem yapılmışken tarama devam etmeli (limit 12)."""
    eng = make_engine(portfolio, tmp_path, "agresif")
    eng.state.enabled = True
    eng.state.daily_trades = 10
    eng.state.daily_date = "2026-06-11"
    eng.state.daily_start_equity = portfolio.cash

    called = []

    async def mock_scan(*a, **kw):
        called.append(True)
        return 'ONERILER: []'

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert called, "Agresif modda 10 işlemde tarama devam etmeli (limit 12)"


# ── günlük zarar limiti testleri ─────────────────────────────────────────────

def test_guvenli_mod_gunluk_zarar_2_pct_kapatir(portfolio, tmp_path):
    """Güvenli modda %2 zarar → otonom kapanır."""
    eng = make_engine(portfolio, tmp_path, "guvenli")
    eng.state.enabled = True
    eng.state.daily_start_equity = 10_000.0
    portfolio.cash = 9_780.0  # %2.2 zarar

    eng._check_daily_loss_limit()

    assert not eng.state.enabled, "Güvenli modda %2.2 zarar → kapatılmalı"
    assert eng.state.risk_locked


def test_guvenli_mod_gunluk_zarar_altinda_devam(portfolio, tmp_path):
    """%1.5 zarar → güvenli mod limiti (%2) aşılmadı."""
    eng = make_engine(portfolio, tmp_path, "guvenli")
    eng.state.enabled = True
    eng.state.daily_start_equity = 10_000.0
    portfolio.cash = 9_850.0  # %1.5 zarar

    eng._check_daily_loss_limit()

    assert eng.state.enabled, "Güvenli modda %1.5 zarar → devam etmeli"
    assert not eng.state.risk_locked


def test_dengeli_mod_gunluk_zarar_4_pct_kapatir(portfolio, tmp_path):
    """Dengeli modda %4 zarar → otonom kapanır."""
    eng = make_engine(portfolio, tmp_path, "dengeli")
    eng.state.enabled = True
    eng.state.daily_start_equity = 10_000.0
    portfolio.cash = 9_580.0  # %4.2 zarar

    eng._check_daily_loss_limit()

    assert not eng.state.enabled, "Dengeli modda %4.2 zarar → kapatılmalı"
    assert eng.state.risk_locked


def test_agresif_mod_gunluk_zarar_6_pct_kapatir(portfolio, tmp_path):
    """Agresif modda %6 zarar → otonom kapanır."""
    eng = make_engine(portfolio, tmp_path, "agresif")
    eng.state.enabled = True
    eng.state.daily_start_equity = 10_000.0
    portfolio.cash = 9_380.0  # %6.2 zarar

    eng._check_daily_loss_limit()

    assert not eng.state.enabled, "Agresif modda %6.2 zarar → kapatılmalı"
    assert eng.state.risk_locked


def test_agresif_mod_4_pct_zarar_devam_eder(portfolio, tmp_path):
    """%4 zarar → agresif mod limiti (%6) aşılmadı."""
    eng = make_engine(portfolio, tmp_path, "agresif")
    eng.state.enabled = True
    eng.state.daily_start_equity = 10_000.0
    portfolio.cash = 9_600.0  # %4.0 zarar

    eng._check_daily_loss_limit()

    assert eng.state.enabled, "Agresif modda %4 zarar → devam etmeli"
    assert not eng.state.risk_locked


# ── ardışık zarar testleri ───────────────────────────────────────────────────

def test_guvenli_modda_2_zarar_kilitleniyor(portfolio, tmp_path):
    """Güvenli modda 2 ardışık zarar → cooldown aktif olmalı."""
    import time as _time
    eng = make_engine(portfolio, tmp_path, "guvenli")
    portfolio.history.extend([
        {"side": "SAT", "symbol": "BTCUSDT", "pnl": -50.0,
         "ts": 0, "qty": 0.01, "price": 49000.0, "usdt": 490.0},
        {"side": "SAT", "symbol": "ETHUSDT", "pnl": -30.0,
         "ts": 0, "qty": 0.1, "price": 1900.0, "usdt": 190.0},
    ])
    portfolio.save()

    eng._history_len = 0
    eng._check_trades_from_history()

    # Güvenli profil max_consecutive_losses=2: limit dolunca cooldown tetiklenir
    assert eng.state.cooldown_until > _time.time(), (
        "Güvenli modda 2 zarar → cooldown süresi ayarlanmalıydı"
    )


def test_dengeli_modda_3_zarar_kilitleniyor(portfolio, engine):
    """Dengeli modda 3 ardışık zarar → cooldown aktif olmalı."""
    import time as _time
    portfolio.history.extend([
        {"side": "SAT", "symbol": "BTCUSDT", "pnl": -50.0,
         "ts": 0, "qty": 0.01, "price": 49000.0, "usdt": 490.0},
        {"side": "SAT", "symbol": "ETHUSDT", "pnl": -30.0,
         "ts": 0, "qty": 0.1, "price": 1900.0, "usdt": 190.0},
        {"side": "SAT", "symbol": "SOLUSDT", "pnl": -20.0,
         "ts": 0, "qty": 1.0, "price": 95.0, "usdt": 95.0},
    ])
    portfolio.save()

    engine._history_len = 0
    engine._check_trades_from_history()

    # Dengeli profil max_consecutive_losses=3: 3 zarar sonrası cooldown tetiklenir
    assert engine.state.cooldown_until > _time.time(), (
        "Dengeli modda 3 zarar → cooldown süresi ayarlanmalıydı"
    )


def test_dengeli_modda_2_zarar_kilitlenmez(portfolio, engine):
    """Dengeli modda 2 ardışık zarar → henüz kilitlenmez (limit 3)."""
    portfolio.history.extend([
        {"side": "SAT", "symbol": "BTCUSDT", "pnl": -50.0,
         "ts": 0, "qty": 0.01, "price": 49000.0, "usdt": 490.0},
        {"side": "SAT", "symbol": "ETHUSDT", "pnl": -30.0,
         "ts": 0, "qty": 0.1, "price": 1900.0, "usdt": 190.0},
    ])
    portfolio.save()

    engine._history_len = 0
    engine._check_trades_from_history()

    assert engine.state.consecutive_losses == 2
    assert not engine.state.risk_locked, "Dengeli modda 2 zarar → henüz kilitlenmemeli"


def test_kazanc_ardisik_zarar_sifirliyor(portfolio, engine):
    """Kazanç sonrası ardışık zarar sayacı sıfırlanır."""
    portfolio.history.extend([
        {"side": "SAT", "symbol": "BTCUSDT", "pnl": -50.0,
         "ts": 0, "qty": 0.01, "price": 49000.0, "usdt": 490.0},
        {"side": "SAT", "symbol": "ETHUSDT", "pnl": 80.0,
         "ts": 0, "qty": 0.1, "price": 2100.0, "usdt": 210.0},
    ])
    portfolio.save()

    engine._history_len = 0
    engine._check_trades_from_history()

    assert engine.state.consecutive_losses == 0


# ── güvenlik testleri ─────────────────────────────────────────────────────────

def test_engine_paper_mode_no_live_fn(engine):
    """Paper modda live_buy_fn ve live_sell_fn None olmalı."""
    assert engine.live_buy_fn is None
    assert engine.live_sell_fn is None


def test_engine_live_fn_set(portfolio, tmp_path):
    """live_buy_fn ve live_sell_fn parametre olarak iletilebilmeli."""
    dummy_buy = lambda s, u: (100.0, 0.001, u)
    dummy_sell = lambda s, q: (100.0, q, q * 100.0)
    cfg = type("cfg", (), {"autonomous_mode": "dengeli", "leverage_enabled": False,
                            "scalp_enabled": False, "trade_plan": "dengeli",
                            "live_autonomous": True})()
    feed = type("feed", (), {"tickers": {}, "price": lambda s: 0.0})()
    tracker = type("tracker", (), {})()
    e = AutonomousEngine(
        portfolio=portfolio, feed=feed, tracker=tracker, cfg=cfg,
        log_fn=lambda m: None, watchlist_fn=lambda: [],
        state_path=tmp_path / "s.json", log_path=tmp_path / "l.jsonl",
        live_buy_fn=dummy_buy, live_sell_fn=dummy_sell,
    )
    assert e.live_buy_fn is dummy_buy
    assert e.live_sell_fn is dummy_sell


def test_live_autonomous_flag_default(portfolio, tmp_path):
    """live_autonomous varsayılan olarak False olmalı (config'de)."""
    from config import Config
    cfg = Config()
    assert cfg.live_autonomous is False


# ── otonom motor durum testleri ───────────────────────────────────────────────

def test_otonom_varsayilan_kapali(engine):
    assert not engine.enabled


@pytest.mark.asyncio
async def test_risk_kilitli_iken_tarama_yapilmaz(portfolio, engine, monkeypatch):
    """Risk kilidi aktifken _run_scan erken döner."""
    engine.state.enabled = True
    engine.state.risk_locked = True

    called = []

    async def mock_scan(*a, **kw):
        called.append(True)
        return ""

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await engine._run_scan()

    assert not called
    assert len(portfolio.positions) == 0


@pytest.mark.asyncio
async def test_uygun_adayda_paper_trade_aciliyor(portfolio, engine, monkeypatch):
    """Otonom açıkken uygun aday varsa paper trade açılmalı."""
    engine.state.enabled = True
    engine.state.daily_date = "2026-06-11"
    engine.state.daily_start_equity = portfolio.cash

    mock_response = (
        "Kripto piyasası yükseliş sinyali veriyor.\n"
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":65,"zarar_kes":49000,"kar_al":52500,"gerekce":"güçlü destek"}]'
    )

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    initial_cash = portfolio.cash

    await engine._run_scan()

    assert len(portfolio.positions) == 1
    assert "BTCUSDT" in portfolio.positions
    assert portfolio.cash < initial_cash
    assert engine.state.daily_trades == 1


@pytest.mark.asyncio
async def test_dusuk_rr_adayi_atlaniyor(portfolio, engine, monkeypatch):
    """R/R < 1.5 (dengeli min) olan aday atlanır."""
    engine.state.enabled = True
    engine.state.daily_date = "2026-06-11"

    mock_response = (
        "Tarama.\n"
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":60,"zarar_kes":49500,"kar_al":50300,"gerekce":"zayıf RR"}]'
    )
    # BTC=50000, stop=49500 (risk=500), hedef=50300 (gain=300) → R/R=0.6 < 1.5 ✗

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await engine._run_scan()

    assert len(portfolio.positions) == 0


@pytest.mark.asyncio
async def test_sat_onerisi_aday_olarak_islenmez(portfolio, engine, monkeypatch):
    """Taramada SAT önerisi paper trade olarak açılmaz."""
    engine.state.enabled = True
    engine.state.daily_date = "2026-06-11"

    mock_response = (
        "Tarama.\n"
        'ONERILER: [{"islem":"SAT","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":60,"zarar_kes":0,"kar_al":0,"gerekce":"düşüş bekleniyor"}]'
    )

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await engine._run_scan()

    assert len(portfolio.positions) == 0


# ── kategori testleri ─────────────────────────────────────────────────────────

def test_emtia_kategorisi():
    instruments = market.instruments_for_category("emtia")
    assert "GC=F" in instruments
    assert "CL=F" in instruments
    assert "NG=F" in instruments
    assert "EURUSD=X" not in instruments


def test_forex_kategorisi():
    instruments = market.instruments_for_category("forex")
    assert "EURUSD=X" in instruments
    assert "GBPUSD=X" in instruments
    assert "GC=F" not in instruments
    assert "^GSPC" not in instruments


def test_endeks_kategorisi():
    instruments = market.instruments_for_category("endeks")
    assert "^GSPC" in instruments
    assert "^DJI" in instruments
    assert "XU100.IS" in instruments
    assert "GC=F" not in instruments
    assert "EURUSD=X" not in instruments


def test_global_kategorisi():
    instruments = market.instruments_for_category("global")
    assert set(instruments) == set(market.SCAN_INSTRUMENTS)


def test_scan_instruments_tumlugu():
    expected = market.SCAN_EMTIA + market.SCAN_FOREX + market.SCAN_ENDEKS
    assert market.SCAN_INSTRUMENTS == expected


# ── /durum testi ──────────────────────────────────────────────────────────────

def test_durum_analizi_ayristirma():
    text = (
        "BTC pozisyonu destekte duruyor.\n"
        'DURUM_ANALIZI: {"genel_oneri":"Pozisyonlar stabil, devam","pozisyonlar":'
        '[{"sembol":"BTCUSDT","karar":"DEVAM","gerekce":"trend bozulmadı","acil":false},'
        '{"sembol":"GC=F","karar":"KAR_AL","gerekce":"hedefe %5 kaldı","acil":true}]}'
    )
    result = ai.parse_status_analysis(text)

    assert result is not None
    assert result.genel_oneri == "Pozisyonlar stabil, devam"
    assert len(result.pozisyonlar) == 2
    assert result.pozisyonlar[0].karar == "DEVAM"
    assert result.pozisyonlar[0].acil is False
    assert result.pozisyonlar[1].karar == "KAR_AL"
    assert result.pozisyonlar[1].acil is True


def test_durum_analizi_bozuk_json_none():
    assert ai.parse_status_analysis("json yok") is None
    assert ai.parse_status_analysis("DURUM_ANALIZI: {bozuk") is None


def test_durum_analizi_gecersiz_karar_bekleye_dusuyor():
    text = (
        'DURUM_ANALIZI: {"genel_oneri":"test","pozisyonlar":'
        '[{"sembol":"BTCUSDT","karar":"GEÇERSIZ_KARAR","gerekce":"x","acil":false}]}'
    )
    result = ai.parse_status_analysis(text)
    assert result is not None
    assert result.pozisyonlar[0].karar == "BEKLE"


def test_tara_scan_sadece_al_onerisi_isleniyor():
    """/tara akışında SAT önerileri filtrelenir."""
    response = (
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":60,"zarar_kes":49000,"kar_al":52000,"gerekce":"test"},'
        '{"islem":"SAT","sembol":"ETHUSDT","tutar_usdt":300,'
        '"basari_yuzdesi":55,"zarar_kes":0,"kar_al":0,"gerekce":"düşüş"}]'
    )
    suggestions = ai.parse_suggestions(response)
    al_only = [s for s in suggestions if s.islem == "AL"]
    sat = [s for s in suggestions if s.islem == "SAT"]

    assert len(al_only) == 1
    assert len(sat) == 1

    filtered = [s for s in suggestions if s.islem == "AL"]
    assert len(filtered) == 1
    assert filtered[0].sembol == "BTCUSDT"


@pytest.mark.asyncio
async def test_tara_kripto_sadece_kripto_verisi(monkeypatch):
    movers_called = []
    yahoo_called = []

    async def mock_top_movers(limit=12):
        movers_called.append(limit)
        return []

    async def mock_yahoo_snapshot(instruments=None):
        yahoo_called.append(instruments)
        return []

    monkeypatch.setattr(market, "fetch_top_movers", mock_top_movers)
    monkeypatch.setattr(market, "fetch_yahoo_snapshot", mock_yahoo_snapshot)

    async def mock_ask(prompt, system):
        return 'ONERILER: []'

    monkeypatch.setattr(ai, "_ask", mock_ask)

    await ai.scan_market_filtered([], 10000.0, {}, category="kripto")

    assert movers_called, "fetch_top_movers çağrılmalıydı"
    assert not yahoo_called, "fetch_yahoo_snapshot çağrılmamalıydı"


@pytest.mark.asyncio
async def test_tara_global_sadece_yahoo_verisi(monkeypatch):
    movers_called = []
    yahoo_called = []

    async def mock_top_movers(limit=12):
        movers_called.append(limit)
        return []

    async def mock_yahoo_snapshot(instruments=None):
        yahoo_called.append(instruments)
        return []

    monkeypatch.setattr(market, "fetch_top_movers", mock_top_movers)
    monkeypatch.setattr(market, "fetch_yahoo_snapshot", mock_yahoo_snapshot)

    async def mock_ask(prompt, system):
        return 'ONERILER: []'

    monkeypatch.setattr(ai, "_ask", mock_ask)

    await ai.scan_market_filtered([], 10000.0, {}, category="global")

    assert not movers_called, "fetch_top_movers çağrılmamalıydı"
    assert yahoo_called, "fetch_yahoo_snapshot çağrılmalıydı"


@pytest.mark.asyncio
async def test_tara_tum_piyasa_ikisini_de_cagiriyor(monkeypatch):
    movers_called = []
    yahoo_called = []

    async def mock_top_movers(limit=12):
        movers_called.append(limit)
        return []

    async def mock_yahoo_snapshot(instruments=None):
        yahoo_called.append(instruments)
        return []

    monkeypatch.setattr(market, "fetch_top_movers", mock_top_movers)
    monkeypatch.setattr(market, "fetch_yahoo_snapshot", mock_yahoo_snapshot)

    async def mock_ask(prompt, system):
        return 'ONERILER: []'

    monkeypatch.setattr(ai, "_ask", mock_ask)

    await ai.scan_market_filtered([], 10000.0, {}, category=None)

    assert movers_called, "fetch_top_movers çağrılmalıydı"
    assert yahoo_called, "fetch_yahoo_snapshot çağrılmalıydı"
