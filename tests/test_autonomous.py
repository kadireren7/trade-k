"""Otonom mod + yeni mimari testleri."""
import asyncio
from pathlib import Path

import pytest

import ai
import market
import modes
from autonomous import (
    AutonomousEngine,
    AutonomousState,
    MAX_CONSECUTIVE_LOSSES,
    MAX_DAILY_TRADES,
    MAX_OPEN_POSITIONS,
    MIN_CONFIDENCE,
    MIN_RISK_REWARD,
    create_order,
    futures_create_order,
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
        cfg=type("C", (), {"model_id": None, "mode": "standart"})(),
        log_fn=logs.append,
        watchlist_fn=lambda: ["BTCUSDT"],
        state_path=tmp_path / "auto_state.json",
        log_path=tmp_path / "auto_log.jsonl",
    )
    eng._logs = logs
    return eng


# ── mod testleri ─────────────────────────────────────────────────────────────

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


# ── kategori testleri ─────────────────────────────────────────────────────────

def test_emtia_kategorisi():
    instruments = market.instruments_for_category("emtia")
    assert "GC=F" in instruments     # altın
    assert "CL=F" in instruments     # petrol
    assert "NG=F" in instruments     # doğalgaz
    assert "EURUSD=X" not in instruments


def test_forex_kategorisi():
    instruments = market.instruments_for_category("forex")
    assert "EURUSD=X" in instruments
    assert "GBPUSD=X" in instruments
    assert "GC=F" not in instruments
    assert "^GSPC" not in instruments


def test_endeks_kategorisi():
    instruments = market.instruments_for_category("endeks")
    assert "^GSPC" in instruments    # S&P 500
    assert "^DJI" in instruments     # DOW
    assert "XU100.IS" in instruments # BIST 100
    assert "GC=F" not in instruments
    assert "EURUSD=X" not in instruments


def test_global_kategorisi():
    instruments = market.instruments_for_category("global")
    assert set(instruments) == set(market.SCAN_INSTRUMENTS)


def test_scan_instruments_tumlugu():
    """SCAN_INSTRUMENTS = EMTIA + FOREX + ENDEKS."""
    expected = market.SCAN_EMTIA + market.SCAN_FOREX + market.SCAN_ENDEKS
    assert market.SCAN_INSTRUMENTS == expected


# ── güvenlik testleri ─────────────────────────────────────────────────────────

def test_create_order_real_order_disabled():
    with pytest.raises(RuntimeError, match="REAL_ORDER_DISABLED"):
        create_order()


def test_futures_create_order_real_order_disabled():
    with pytest.raises(RuntimeError, match="REAL_ORDER_DISABLED"):
        futures_create_order()


def test_create_order_kwargs_de_disabled():
    with pytest.raises(RuntimeError, match="REAL_ORDER_DISABLED"):
        create_order(symbol="BTCUSDT", side="BUY", type="MARKET", quantity=0.001)


# ── otonom motor durum testleri ───────────────────────────────────────────────

def test_otonom_varsayilan_kapali(engine):
    assert not engine.enabled


def test_ardisik_zarar_kilitleniyor(portfolio, engine):
    """2 ardışık zarar → risk kilidi aktif."""
    portfolio.history.extend([
        {"side": "SAT", "symbol": "BTCUSDT", "pnl": -50.0,
         "ts": 0, "qty": 0.01, "price": 49000.0, "usdt": 490.0},
        {"side": "SAT", "symbol": "ETHUSDT", "pnl": -30.0,
         "ts": 0, "qty": 0.1, "price": 1900.0, "usdt": 190.0},
    ])
    portfolio.save()

    engine._history_len = 0
    engine._check_trades_from_history()

    assert engine.state.consecutive_losses >= MAX_CONSECUTIVE_LOSSES
    assert engine.state.risk_locked


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


def test_gunluk_zarar_limiti_otomodu_kapatiyor(portfolio, engine):
    """Günlük %2 zarar → otonom mod kapanır."""
    engine.state.enabled = True
    engine.state.daily_start_equity = 10_000.0
    portfolio.cash = 9_700.0  # %3 zarar

    engine._check_daily_loss_limit()

    assert not engine.state.enabled
    assert engine.state.risk_locked


def test_gunluk_zarar_limiti_altinda_devam(portfolio, engine):
    """%1.5 zarar → limit aşılmadı, otonom açık kalır."""
    engine.state.enabled = True
    engine.state.daily_start_equity = 10_000.0
    portfolio.cash = 9_850.0  # %1.5 zarar

    engine._check_daily_loss_limit()

    assert engine.state.enabled
    assert not engine.state.risk_locked


# ── otonom tarama testleri ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_risk_kilitli_iken_tarama_yapilmaz(portfolio, engine, monkeypatch):
    """Risk kilidi aktifken _run_scan erken döner, Claude çağrılmaz."""
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
async def test_gunluk_limit_dolunca_tarama_yapilmaz(portfolio, engine, monkeypatch):
    """Günlük 3 işlem dolunca tarama yapılmaz."""
    engine.state.enabled = True
    engine.state.daily_trades = MAX_DAILY_TRADES

    called = []

    async def mock_scan(*a, **kw):
        called.append(True)
        return ""

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await engine._run_scan()

    assert not called


@pytest.mark.asyncio
async def test_max_pozisyon_dolunca_tarama_yapilmaz(portfolio, engine, monkeypatch):
    """Max açık pozisyon sayısına ulaşıldığında tarama yapılmaz."""
    engine.state.enabled = True
    # 2 pozisyon aç
    portfolio.buy("BTCUSDT", 500, 50000.0)
    portfolio.buy("ETHUSDT", 300, 2000.0)

    called = []

    async def mock_scan(*a, **kw):
        called.append(True)
        return ""

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await engine._run_scan()

    assert not called


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
async def test_dusuk_confidence_adayi_atlaniyor(portfolio, engine, monkeypatch):
    """Confidence < MIN_CONFIDENCE olan aday atlanır."""
    engine.state.enabled = True
    engine.state.daily_date = "2026-06-11"

    mock_response = (
        "Tarama sonucu.\n"
        f'ONERILER: [{{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        f'"basari_yuzdesi":{MIN_CONFIDENCE - 1},"zarar_kes":49000,'
        f'"kar_al":52500,"gerekce":"zayıf sinyal"}}]'
    )

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)

    await engine._run_scan()

    assert len(portfolio.positions) == 0


@pytest.mark.asyncio
async def test_dusuk_rr_adayi_atlaniyor(portfolio, engine, monkeypatch):
    """R/R < MIN_RISK_REWARD olan aday atlanır. (50000 fiyat, stop 49500, hedef 50300 → RR=0.6)"""
    engine.state.enabled = True
    engine.state.daily_date = "2026-06-11"

    mock_response = (
        "Tarama.\n"
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":60,"zarar_kes":49500,"kar_al":50300,"gerekce":"zayıf RR"}]'
    )

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


# ── /tara kategori testleri ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tara_kripto_sadece_kripto_verisi(monkeypatch):
    """/tara kripto → sadece fetch_top_movers çağrılır, yahoo çağrılmaz."""
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
    """/tara global → sadece fetch_yahoo_snapshot çağrılır, movers çağrılmaz."""
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
    """/tara (kategori yok) → hem movers hem yahoo çağrılır."""
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


# ── /durum testi ──────────────────────────────────────────────────────────────

def test_durum_analizi_ayristirma():
    """parse_status_analysis doğru JSON'u ayrıştırır."""
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


# ── tara SAT önerisi içermemeli ───────────────────────────────────────────────

def test_tara_scan_sadece_al_onerisi_isleniyor():
    """/tara akışında SAT önerileri filtrelenir (AL only)."""
    response = (
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":60,"zarar_kes":49000,"kar_al":52000,"gerekce":"test"},'
        '{"islem":"SAT","sembol":"ETHUSDT","tutar_usdt":300,'
        '"basari_yuzdesi":55,"zarar_kes":0,"kar_al":0,"gerekce":"düşüş"}]'
    )
    suggestions = ai.parse_suggestions(response)
    al_only = [s for s in suggestions if s.islem == "AL"]
    sat = [s for s in suggestions if s.islem == "SAT"]

    # parse_suggestions her ikisini de döndürür
    assert len(al_only) == 1
    assert len(sat) == 1

    # Ama run_scan işlevi sadece AL'ları pending'e alır
    # Bu filtre app.py'de: self.pending = [s for s in self.pending if s.islem == "AL"]
    filtered = [s for s in suggestions if s.islem == "AL"]
    assert len(filtered) == 1
    assert filtered[0].sembol == "BTCUSDT"


# ── durum açık pozisyon kapatma önerisi vermez ───────────────────────────────

@pytest.mark.asyncio
async def test_tara_acik_pozisyon_icin_sat_onerisi_vermez(
    portfolio, engine, monkeypatch
):
    """/tara SAT önerileri motor tarafından işlenmez."""
    engine.state.enabled = True
    engine.state.daily_date = "2026-06-11"
    portfolio.buy("BTCUSDT", 500, 50000.0)

    mock_response = (
        'ONERILER: [{"islem":"SAT","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":60,"zarar_kes":0,"kar_al":0,"gerekce":"kapat"}]'
    )

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)

    initial_positions = dict(portfolio.positions)
    await engine._run_scan()

    # SAT önerisi işlenmedi, pozisyon hâlâ açık
    assert "BTCUSDT" in portfolio.positions
    assert portfolio.positions["BTCUSDT"].qty == initial_positions["BTCUSDT"].qty
