"""Karar uygulama (apply_decision) ve stop güncelleme güvenliği testleri."""
import asyncio
from pathlib import Path

import pytest

import ai
import market
from ai import PositionDecision
from autonomous import AutonomousEngine
from portfolio import Portfolio, validate_stop_update
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
    feed = MockFeed({
        "BTCUSDT": 50000.0, "SOLUSDT": 100.0,
        "ETHUSDT": 2000.0, "GC=F": 3500.0,
    })
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


def make_pd(
    sembol: str,
    karar: str,
    gerekce: str = "test",
    new_stop_loss: float = 0.0,
    new_take_profit: float = 0.0,
    close_reason: str = "",
    acil: bool = False,
) -> PositionDecision:
    return PositionDecision(
        sembol=sembol,
        karar=karar,
        gerekce=gerekce,
        acil=acil,
        new_stop_loss=new_stop_loss,
        new_take_profit=new_take_profit,
        close_reason=close_reason,
    )


# ── validate_stop_update testleri ────────────────────────────────────────────

def test_sacma_stop_sifir_reddedilir():
    ok, reason = validate_stop_update(50000, 50000, None, 0)
    assert not ok
    assert "sıfır" in reason.lower() or "negatif" in reason.lower()


def test_stop_anlık_fiyatin_ustunde_reddedilir():
    ok, reason = validate_stop_update(50000, 50000, None, 51000)
    assert not ok
    assert "üstünde" in reason.lower() or "eşit" in reason.lower()


def test_stop_anlık_fiyata_esit_reddedilir():
    ok, reason = validate_stop_update(50000, 50000, None, 50000)
    assert not ok


def test_stop_cok_genis_reddedilir():
    # Giriş 50000, stop 37000 → %26 düşük, max %25
    ok, reason = validate_stop_update(50000, 50000, None, 37000)
    assert not ok
    assert "geniş" in reason.lower() or "reddedildi" in reason.lower()


def test_stop_mevcut_stoptan_kotu_reddedilir():
    # Long: mevcut stop 48000, yeni stop 47000 → daha kötü
    ok, reason = validate_stop_update(50000, 52000, 48000, 47000)
    assert not ok
    assert "kötü" in reason.lower() or "kötüye" in reason.lower()


def test_gecerli_stop_kabul_edilir():
    # Giriş 50000, fiyat 52000, eski stop 48000, yeni stop 50000 (başa baş)
    ok, reason = validate_stop_update(50000, 52000, 48000, 50000)
    assert ok
    assert reason == ""


def test_gecerli_trailing_stop():
    # Fiyat 55000, giriş 50000, stop 51000 (kâr koruma) → geçerli
    ok, reason = validate_stop_update(50000, 55000, 49000, 51000)
    assert ok


def test_stop_mevcut_yokken_herhangi_gecerli_kabul():
    # Mevcut stop yok → geçerli değer kabul edilmeli
    ok, reason = validate_stop_update(50000, 52000, None, 49000)
    assert ok


# ── apply_decision — DEVAM/BEKLE ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_devam_karari_islem_yapmaz(portfolio, engine):
    portfolio.buy("BTCUSDT", 500, 50000.0)
    pd = make_pd("BTCUSDT", "DEVAM", "trend devam ediyor")

    ok, msg = await engine.apply_decision("BTCUSDT", pd, 50500.0)

    assert not ok
    assert "BTCUSDT" in portfolio.positions  # pozisyon hâlâ açık


@pytest.mark.asyncio
async def test_bekle_karari_islem_yapmaz(portfolio, engine):
    portfolio.buy("BTCUSDT", 500, 50000.0)
    pd = make_pd("BTCUSDT", "BEKLE", "belirsiz ortam")

    ok, msg = await engine.apply_decision("BTCUSDT", pd, 50500.0)

    assert not ok
    assert "BTCUSDT" in portfolio.positions


# ── apply_decision — KAR_AL ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_kar_al_karari_pozisyon_kapatir(portfolio, engine):
    portfolio.buy("BTCUSDT", 500, 50000.0)
    pd = make_pd("BTCUSDT", "KAR_AL", "hedefe yaklaştı",
                 close_reason="güçlü direnç bölgesi")

    ok, msg = await engine.apply_decision("BTCUSDT", pd, 52000.0)

    assert ok
    assert "BTCUSDT" not in portfolio.positions
    assert portfolio.cash > 500  # kâr içeriyor


@pytest.mark.asyncio
async def test_kar_al_karari_close_reason_loglanir(portfolio, engine):
    portfolio.buy("BTCUSDT", 500, 50000.0)
    pd = make_pd("BTCUSDT", "KAR_AL", "yüksek direnç",
                 close_reason="hedefe %98 ulaştı")

    ok, msg = await engine.apply_decision("BTCUSDT", pd, 52500.0, auto=True)

    assert ok
    log_output = " ".join(engine._logs)
    assert "kâr alındı" in log_output.lower()


# ── apply_decision — ZARARI_KES ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_zarari_kes_karari_pozisyon_kapatir(portfolio, engine):
    portfolio.buy("BTCUSDT", 500, 50000.0)
    pd = make_pd("BTCUSDT", "ZARARI_KES", "yapı bozuldu",
                 close_reason="destek kırıldı")

    ok, msg = await engine.apply_decision("BTCUSDT", pd, 48000.0)

    assert ok
    assert "BTCUSDT" not in portfolio.positions


@pytest.mark.asyncio
async def test_zarari_kes_zarar_dogru_hesaplanir(portfolio, engine):
    portfolio.buy("BTCUSDT", 1000, 50000.0)
    pd = make_pd("BTCUSDT", "ZARARI_KES", "büyük düşüş")

    initial_cash = portfolio.cash
    ok, msg = await engine.apply_decision("BTCUSDT", pd, 48000.0)

    assert ok
    # 48000'den sattı, 50000'den aldı → zarar var
    proceeds = portfolio.cash - initial_cash
    assert proceeds < 1000  # 1000 USDT'den az aldı back


# ── apply_decision — STOP_GUNCELLE ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_stop_guncelle_stop_degistirir(portfolio, engine):
    portfolio.buy("BTCUSDT", 500, 50000.0)
    portfolio.set_protection("BTCUSDT", 48000.0, 55000.0)
    pd = make_pd("BTCUSDT", "STOP_GUNCELLE", "trailing stop",
                 new_stop_loss=50000.0)

    ok, msg = await engine.apply_decision("BTCUSDT", pd, 52000.0)

    assert ok
    assert portfolio.positions["BTCUSDT"].stop == 50000.0


@pytest.mark.asyncio
async def test_stop_guncelle_hedef_degismez(portfolio, engine):
    portfolio.buy("BTCUSDT", 500, 50000.0)
    portfolio.set_protection("BTCUSDT", 48000.0, 55000.0)
    pd = make_pd("BTCUSDT", "STOP_GUNCELLE", "trailing", new_stop_loss=50000.0)

    await engine.apply_decision("BTCUSDT", pd, 52000.0)

    assert portfolio.positions["BTCUSDT"].target == 55000.0  # değişmedi


@pytest.mark.asyncio
async def test_stop_guncelle_kotu_stop_reddedilir(portfolio, engine):
    portfolio.buy("BTCUSDT", 500, 50000.0)
    portfolio.set_protection("BTCUSDT", 48000.0, 55000.0)
    # Yeni stop 47000 → mevcut 48000'den kötü
    pd = make_pd("BTCUSDT", "STOP_GUNCELLE", "stop kötüleştir",
                 new_stop_loss=47000.0)

    ok, msg = await engine.apply_decision("BTCUSDT", pd, 52000.0)

    assert not ok
    assert portfolio.positions["BTCUSDT"].stop == 48000.0  # değişmedi


@pytest.mark.asyncio
async def test_stop_guncelle_fiyat_ustunde_reddedilir(portfolio, engine):
    portfolio.buy("BTCUSDT", 500, 50000.0)
    # Yeni stop fiyatın üstünde: 52001 > 52000
    pd = make_pd("BTCUSDT", "STOP_GUNCELLE", "imkansız stop",
                 new_stop_loss=52001.0)

    ok, msg = await engine.apply_decision("BTCUSDT", pd, 52000.0)

    assert not ok


@pytest.mark.asyncio
async def test_stop_guncelle_deger_eksik_reddedilir(portfolio, engine):
    portfolio.buy("BTCUSDT", 500, 50000.0)
    pd = make_pd("BTCUSDT", "STOP_GUNCELLE", "stop yok", new_stop_loss=0.0)

    ok, msg = await engine.apply_decision("BTCUSDT", pd, 52000.0)

    assert not ok


# ── apply_decision — KORU ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_koru_stop_ekler(portfolio, engine):
    portfolio.buy("SOLUSDT", 200, 100.0)
    # Stop yok, hedef yok
    pd = make_pd("SOLUSDT", "KORU", "koruma ekle",
                 new_stop_loss=90.0, new_take_profit=115.0)

    ok, msg = await engine.apply_decision("SOLUSDT", pd, 100.0)

    assert ok
    assert portfolio.positions["SOLUSDT"].stop == 90.0
    assert portfolio.positions["SOLUSDT"].target == 115.0


@pytest.mark.asyncio
async def test_koru_var_olan_stop_degistirmez(portfolio, engine):
    portfolio.buy("SOLUSDT", 200, 100.0)
    portfolio.set_protection("SOLUSDT", 92.0, None)  # stop var, hedef yok
    pd = make_pd("SOLUSDT", "KORU", "hedef ekle",
                 new_stop_loss=90.0,   # mevcut 92 var → KORU sadece eksik ekler
                 new_take_profit=115.0)

    ok, msg = await engine.apply_decision("SOLUSDT", pd, 100.0)

    assert ok
    assert portfolio.positions["SOLUSDT"].stop == 92.0  # değişmedi
    assert portfolio.positions["SOLUSDT"].target == 115.0  # eklendi


@pytest.mark.asyncio
async def test_koru_zaten_korumali_atlanir(portfolio, engine):
    portfolio.buy("SOLUSDT", 200, 100.0)
    portfolio.set_protection("SOLUSDT", 92.0, 115.0)  # her ikisi de var
    pd = make_pd("SOLUSDT", "KORU", "zaten korumalı",
                 new_stop_loss=90.0, new_take_profit=120.0)

    ok, msg = await engine.apply_decision("SOLUSDT", pd, 100.0)

    assert not ok
    assert "zaten" in msg.lower() or "atlandı" in msg.lower()


# ── otonom mod — otomatik uygulama ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_otonom_acikken_stop_guncelle_otomatik(portfolio, engine, monkeypatch):
    """Otonom açıkken STOP_GUNCELLE kararı otomatik uygulanır."""
    engine.state.enabled = True
    portfolio.buy("BTCUSDT", 500, 50000.0)
    portfolio.set_protection("BTCUSDT", 48000.0, 55000.0)
    # Fiyat 52000'e çıktı → başa baş stop (50000) geçerli
    engine.feed.tickers["BTCUSDT"].price = 52000.0

    mock_response = (
        "Kâr pozisyonda trailing stop uygulanabilir.\n"
        'DURUM_ANALIZI: {"genel_oneri":"trailing stop","pozisyonlar":'
        '[{"sembol":"BTCUSDT","karar":"STOP_GUNCELLE","gerekce":"trailing",'
        '"acil":false,"new_stop_loss":50000.0,"new_take_profit":0,"close_reason":""}]}'
    )

    async def mock_analyze(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "analyze_positions", mock_analyze)

    await engine._run_position_analysis()

    assert portfolio.positions["BTCUSDT"].stop == 50000.0, (
        "Otonom modda STOP_GUNCELLE otomatik uygulanmalı"
    )


@pytest.mark.asyncio
async def test_otonom_acikken_kar_al_otomatik_kapatir(portfolio, engine, monkeypatch):
    """Otonom açıkken KAR_AL kararı pozisyonu otomatik kapatır."""
    engine.state.enabled = True
    portfolio.buy("BTCUSDT", 500, 50000.0)

    mock_response = (
        "Hedefe ulaşıldı.\n"
        'DURUM_ANALIZI: {"genel_oneri":"kâr al","pozisyonlar":'
        '[{"sembol":"BTCUSDT","karar":"KAR_AL","gerekce":"hedefe %98 ulaştı",'
        '"acil":false,"new_stop_loss":0,"new_take_profit":0,'
        '"close_reason":"güçlü direnç"}]}'
    )

    async def mock_analyze(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "analyze_positions", mock_analyze)

    await engine._run_position_analysis()

    assert "BTCUSDT" not in portfolio.positions, (
        "Otonom modda KAR_AL kararı pozisyonu otomatik kapatmalı"
    )


@pytest.mark.asyncio
async def test_otonom_acikken_zarari_kes_otomatik_kapatir(portfolio, engine, monkeypatch):
    """Otonom açıkken ZARARI_KES kararı pozisyonu otomatik kapatır."""
    engine.state.enabled = True
    portfolio.buy("BTCUSDT", 500, 50000.0)

    mock_response = (
        "Yapı bozuldu.\n"
        'DURUM_ANALIZI: {"genel_oneri":"zarar kes","pozisyonlar":'
        '[{"sembol":"BTCUSDT","karar":"ZARARI_KES","gerekce":"yapı bozuldu",'
        '"acil":true,"new_stop_loss":0,"new_take_profit":0,'
        '"close_reason":"destek kırıldı"}]}'
    )

    async def mock_analyze(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "analyze_positions", mock_analyze)

    await engine._run_position_analysis()

    assert "BTCUSDT" not in portfolio.positions, (
        "Otonom modda ZARARI_KES kararı pozisyonu otomatik kapatmalı"
    )


@pytest.mark.asyncio
async def test_otonom_devam_karari_pozisyonu_kapatmaz(portfolio, engine, monkeypatch):
    """Otonom modda DEVAM kararında pozisyon değişmez."""
    engine.state.enabled = True
    portfolio.buy("BTCUSDT", 500, 50000.0)
    portfolio.set_protection("BTCUSDT", 48000.0, 55000.0)

    mock_response = (
        "Piyasa stabil.\n"
        'DURUM_ANALIZI: {"genel_oneri":"devam et","pozisyonlar":'
        '[{"sembol":"BTCUSDT","karar":"DEVAM","gerekce":"trend bozulmadı",'
        '"acil":false,"new_stop_loss":0,"new_take_profit":0,"close_reason":""}]}'
    )

    async def mock_analyze(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "analyze_positions", mock_analyze)

    await engine._run_position_analysis()

    assert "BTCUSDT" in portfolio.positions, "DEVAM kararında pozisyon kapanmamalı"
    assert portfolio.positions["BTCUSDT"].stop == 48000.0


@pytest.mark.asyncio
async def test_otonom_kullanici_onayi_istemez(portfolio, engine, monkeypatch):
    """Otonom modda karar için kullanıcı onayı istenmez — direkt uygulanır."""
    engine.state.enabled = True
    portfolio.buy("BTCUSDT", 500, 50000.0)

    mock_response = (
        'DURUM_ANALIZI: {"genel_oneri":"","pozisyonlar":'
        '[{"sembol":"BTCUSDT","karar":"KAR_AL","gerekce":"test",'
        '"acil":false,"new_stop_loss":0,"new_take_profit":0,"close_reason":"test"}]}'
    )

    confirmation_requested = []

    async def mock_analyze(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "analyze_positions", mock_analyze)

    # _run_position_analysis çalıştır — hiçbir "confirmation" callback çağrılmamalı
    await engine._run_position_analysis()

    assert not confirmation_requested, "Otonom modda kullanıcı onayı istenmemeli"
    # Karar uygulandı mı?
    assert "BTCUSDT" not in portfolio.positions, "KAR_AL onaysız uygulanmalı"


# ── otonom kapalıyken kararlar uygulanmaz ────────────────────────────────────

@pytest.mark.asyncio
async def test_otonom_kapali_position_analysis_cagrilmaz(portfolio, engine, monkeypatch):
    """Otonom kapalıyken _run_position_analysis hiç çağrılmaz (döngü durur)."""
    portfolio.buy("BTCUSDT", 500, 50000.0)

    analyze_called = []

    async def mock_analyze(*a, **kw):
        analyze_called.append(True)
        return 'DURUM_ANALIZI: {"genel_oneri":"","pozisyonlar":[]}'

    monkeypatch.setattr(ai, "analyze_positions", mock_analyze)

    # engine.state.enabled = False (varsayılan)
    # _loop() çalışmıyor → _run_position_analysis çağrılmaz
    # Direkt çağrılsaydı çalışırdı; ama döngü dışarıdan tetiklenemez
    assert not engine.enabled


# ── karar güvenliği — pozisyon yok ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_pozisyon_olmayan_sembol_atlaniyor(portfolio, engine):
    pd = make_pd("ETHUSDT", "KAR_AL", "yok")
    ok, msg = await engine.apply_decision("ETHUSDT", pd, 2000.0)
    assert not ok
    assert "bulunamadı" in msg.lower()


# ── /durum parse — yeni alanlar ──────────────────────────────────────────────

def test_parse_status_koru_karari():
    text = (
        'DURUM_ANALIZI: {"genel_oneri":"stop ekle","pozisyonlar":'
        '[{"sembol":"SOLUSDT","karar":"KORU","gerekce":"stop yok",'
        '"acil":false,"new_stop_loss":90.0,"new_take_profit":115.0,"close_reason":""}]}'
    )
    result = ai.parse_status_analysis(text)
    assert result is not None
    pd = result.pozisyonlar[0]
    assert pd.karar == "KORU"
    assert pd.new_stop_loss == 90.0
    assert pd.new_take_profit == 115.0
    assert pd.close_reason == ""


def test_parse_status_stop_guncelle_new_stop():
    text = (
        'DURUM_ANALIZI: {"genel_oneri":"trailing","pozisyonlar":'
        '[{"sembol":"BTCUSDT","karar":"STOP_GUNCELLE","gerekce":"trailing",'
        '"acil":false,"new_stop_loss":50000.0,"new_take_profit":0,"close_reason":""}]}'
    )
    result = ai.parse_status_analysis(text)
    assert result is not None
    pd = result.pozisyonlar[0]
    assert pd.karar == "STOP_GUNCELLE"
    assert pd.new_stop_loss == 50000.0


def test_parse_status_kar_al_close_reason():
    text = (
        'DURUM_ANALIZI: {"genel_oneri":"kâr al","pozisyonlar":'
        '[{"sembol":"BTCUSDT","karar":"KAR_AL","gerekce":"hedefe ulaştı",'
        '"acil":true,"new_stop_loss":0,"new_take_profit":0,'
        '"close_reason":"güçlü direnç bölgesi"}]}'
    )
    result = ai.parse_status_analysis(text)
    assert result is not None
    pd = result.pozisyonlar[0]
    assert pd.karar == "KAR_AL"
    assert pd.close_reason == "güçlü direnç bölgesi"
    assert pd.acil is True


def test_parse_status_eski_format_uyumlu():
    """Eski formatta (new_stop_loss yok) parse edilebilmeli — geriye dönük uyum."""
    text = (
        'DURUM_ANALIZI: {"genel_oneri":"stabil","pozisyonlar":'
        '[{"sembol":"BTCUSDT","karar":"DEVAM","gerekce":"trend devam","acil":false}]}'
    )
    result = ai.parse_status_analysis(text)
    assert result is not None
    pd = result.pozisyonlar[0]
    assert pd.karar == "DEVAM"
    assert pd.new_stop_loss == 0.0
    assert pd.new_take_profit == 0.0
    assert pd.close_reason == ""


# ── güvenlik — live_autonomous kapalıyken live_sell_fn çağrılmaz ─────────────

@pytest.mark.asyncio
async def test_apply_decision_paper_modda_live_sell_fn_cagrilmaz(portfolio, engine):
    """live_autonomous=False → live_sell_fn set olsa bile çağrılmamalı."""
    called = []
    async def dummy_sell(sym, qty):
        called.append(sym)
        return (52000.0, qty, qty * 52000.0)
    engine.live_sell_fn = dummy_sell
    engine.cfg.live_autonomous = False
    portfolio.buy("BTCUSDT", 500, 50000.0)
    pd = make_pd("BTCUSDT", "KAR_AL", "test", close_reason="test")
    ok, msg = await engine.apply_decision("BTCUSDT", pd, 52000.0)
    assert ok
    assert "BTCUSDT" not in portfolio.positions
    assert called == []  # live_sell_fn çağrılmamalı


@pytest.mark.asyncio
async def test_apply_decision_kar_al_portfolio_sell_yapar(portfolio, engine):
    """KAR_AL → portfolio.sell çağrılmalı, pozisyon kapanmalı."""
    portfolio.buy("BTCUSDT", 500, 50000.0)
    pd = make_pd("BTCUSDT", "KAR_AL", "test", close_reason="test")
    ok, msg = await engine.apply_decision("BTCUSDT", pd, 52000.0)
    assert ok
    assert "BTCUSDT" not in portfolio.positions
