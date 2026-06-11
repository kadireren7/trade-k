"""Kaldıraçlı paper trading testleri — portfolio + veri kalitesi filtresi."""
from __future__ import annotations

import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import portfolio as portfolio_mod
from portfolio import (
    Portfolio,
    Position,
    calc_liquidation_price,
    validate_leverage_trade,
    MAX_LEVERAGE,
    MAINTENANCE_MARGIN_RATE,
)
from market import (
    data_quality,
    leverage_allowed,
    leverage_reason,
    data_quality_label,
    leverage_eligible_symbols,
    SCAN_FOREX,
    SCAN_ENDEKS,
    SCAN_EMTIA,
)


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_mod, "STATE_FILE", tmp_path / "account.json")


# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────────

def make_portfolio(cash: float = 10_000.0) -> Portfolio:
    p = Portfolio(cash=cash)
    return p


# ── 1. calc_liquidation_price doğruluğu ──────────────────────────────────────

def test_likidasyon_fiyati_2x():
    """2x kaldıraçta likidasyon fiyatı doğru hesaplanmalı."""
    entry = 50_000.0
    liq = calc_liquidation_price(entry, 2)
    expected = round(entry * (1 - 1 / 2 + MAINTENANCE_MARGIN_RATE), 4)
    assert liq == expected
    assert liq < entry


def test_likidasyon_fiyati_5x():
    """5x kaldıraçta likidasyon giriş fiyatına çok yakın olmalı."""
    entry = 100.0
    liq = calc_liquidation_price(entry, 5)
    expected = round(entry * (1 - 1 / 5 + MAINTENANCE_MARGIN_RATE), 4)
    assert liq == expected
    assert liq > entry * 0.75  # %75'in üstünde → çok risk


def test_likidasyon_buyuk_kaldiracta_yuksek():
    """Kaldıraç büyüdükçe likidasyon fiyatı giriş fiyatına yaklaşır."""
    entry = 1_000.0
    liq2 = calc_liquidation_price(entry, 2)
    liq5 = calc_liquidation_price(entry, 5)
    assert liq5 > liq2  # 5x daha yakın → daha riskli


# ── 2. validate_leverage_trade kontrolleri ────────────────────────────────────

def test_validate_gecerli_islem():
    """Tüm koşullar sağlandığında geçerli dönmeli."""
    ok, msg = validate_leverage_trade(
        entry=50_000.0, stop=48_000.0, target=56_000.0,
        leverage=3, margin_usdt=200.0, portfolio_equity=10_000.0,
    )
    assert ok is True
    assert msg == ""


def test_validate_stop_yok():
    """Stop sıfır olduğunda reddedilmeli."""
    ok, msg = validate_leverage_trade(
        entry=50_000.0, stop=0.0, target=56_000.0,
        leverage=3, margin_usdt=200.0, portfolio_equity=10_000.0,
    )
    assert ok is False
    assert "stop" in msg.lower()


def test_validate_hedef_yok():
    """Hedef sıfır olduğunda reddedilmeli."""
    ok, msg = validate_leverage_trade(
        entry=50_000.0, stop=48_000.0, target=0.0,
        leverage=3, margin_usdt=200.0, portfolio_equity=10_000.0,
    )
    assert ok is False
    assert "take_profit" in msg.lower() or "hedef" in msg.lower()


def test_validate_asiri_kaldirac():
    """Max kaldıraç limitini aşan işlem reddedilmeli."""
    ok, msg = validate_leverage_trade(
        entry=50_000.0, stop=48_000.0, target=60_000.0,
        leverage=6, margin_usdt=200.0, portfolio_equity=10_000.0,
        max_leverage=5,
    )
    assert ok is False
    assert "6x" in msg


def test_validate_dusuk_rr():
    """R/R < 2.0 olan işlem reddedilmeli."""
    # stop %4 altı, hedef %4 üstü → R/R = 1.0
    ok, msg = validate_leverage_trade(
        entry=100.0, stop=96.0, target=104.0,
        leverage=3, margin_usdt=200.0, portfolio_equity=10_000.0,
    )
    assert ok is False
    assert "R/R" in msg


def test_validate_risk_cok_yuksek():
    """Portföyün %0.5'ini aşan risk reddedilmeli."""
    # entry=100, stop=90 → risk 10/100=10% per dollar, qty=200*3/100=6 → risk=60 USDT
    # portfolio=1000 → max_risk=0.5%*1000=5 USDT → reddedilmeli
    ok, msg = validate_leverage_trade(
        entry=100.0, stop=90.0, target=130.0,
        leverage=3, margin_usdt=200.0, portfolio_equity=1_000.0,
        max_risk_pct=0.005,
    )
    assert ok is False
    assert "risk" in msg.lower()


def test_validate_likidasyon_stoptan_yuksek():
    """Likidasyon fiyatı stoptan yüksekse reddedilmeli."""
    # 5x, entry=100, liq=80.5, stop=85 → liq < stop ama güvenlik tamponu az?
    # Burada stop=85, liq=80.5, fark=4.5, stop-entry=-15, güvenlik=7.5 → 4.5<7.5 → red
    ok, msg = validate_leverage_trade(
        entry=100.0, stop=85.0, target=140.0,
        leverage=5, margin_usdt=200.0, portfolio_equity=10_000.0,
    )
    assert ok is False  # güvenlik tamponu yetersiz


def test_validate_guvenlik_tamponu_yeterli():
    """Likidasyon stop'tan yeterince uzakta ise geçerli olmalı."""
    # 2x, entry=100, liq=50.5, stop=80, tampon=10, fark=29.5 > 10
    # margin=100 → notional=200, qty=2, risk=(100-80)*2=40 < 50 (0.5% of 10k) → geçerli
    ok, msg = validate_leverage_trade(
        entry=100.0, stop=80.0, target=140.0,
        leverage=2, margin_usdt=100.0, portfolio_equity=10_000.0,
    )
    assert ok is True, f"Beklenmedik hata: {msg}"


# ── 3. buy_leveraged ve pozisyon yönetimi ────────────────────────────────────

def test_buy_leveraged_pozisyon_acilir():
    """Kaldıraçlı pozisyon doğru alanlarla açılmalı."""
    p = make_portfolio(cash=10_000.0)
    result = p.buy_leveraged(
        "BTCUSDT", margin_usdt=500.0, leverage=3,
        price=50_000.0, stop=47_000.0, target=58_000.0,
    )
    assert "BTCUSDT" in p.positions
    pos = p.positions["BTCUSDT"]
    assert pos.is_leveraged
    assert pos.leverage == 3
    assert pos.margin_usdt == 500.0
    assert pos.notional_usdt == 1_500.0
    assert pos.liquidation_price > 0
    assert pos.liquidation_price < 50_000.0
    assert p.cash == 9_500.0
    assert "⚡" in result


def test_buy_leveraged_yetersiz_bakiye():
    """Yetersiz bakiyede hata fırlatılmalı."""
    p = make_portfolio(cash=100.0)
    with pytest.raises(ValueError, match="Yetersiz bakiye"):
        p.buy_leveraged(
            "ETHUSDT", margin_usdt=500.0, leverage=3,
            price=3_000.0, stop=2_800.0, target=3_500.0,
        )


def test_buy_leveraged_cift_pozisyon_engeli():
    """Aynı sembolde ikinci kaldıraçlı pozisyon açılamamalı."""
    p = make_portfolio(cash=10_000.0)
    p.buy_leveraged(
        "BTCUSDT", margin_usdt=300.0, leverage=2,
        price=50_000.0, stop=47_000.0, target=58_000.0,
    )
    with pytest.raises(ValueError, match="açık pozisyon var"):
        p.buy_leveraged(
            "BTCUSDT", margin_usdt=300.0, leverage=2,
            price=51_000.0, stop=48_000.0, target=59_000.0,
        )


# ── 4. Kapatma senaryoları ────────────────────────────────────────────────────

def test_leveraged_kapanma_karli():
    """Kârlı kaldıraçlı pozisyon doğru kapanmalı."""
    p = make_portfolio(cash=10_000.0)
    p.buy_leveraged(
        "BTCUSDT", margin_usdt=500.0, leverage=3,
        price=50_000.0, stop=47_000.0, target=58_000.0,
    )
    result = p.sell("BTCUSDT", price=55_000.0)
    assert "BTCUSDT" not in p.positions
    assert "LEVERAGE KAPATILDI" in result
    assert p.cash > 10_000.0 - 500.0  # Kâr geri döndü


def test_leveraged_kapanma_zararda():
    """Zararlı kaldıraçlı pozisyon kapanması."""
    p = make_portfolio(cash=10_000.0)
    p.buy_leveraged(
        "BTCUSDT", margin_usdt=500.0, leverage=3,
        price=50_000.0, stop=47_000.0, target=58_000.0,
    )
    result = p.sell("BTCUSDT", price=49_000.0)
    assert "BTCUSDT" not in p.positions
    assert p.cash < 10_000.0  # Zarar var


def test_likidasyon_tetiklemesi():
    """Likidasyon fiyatına ulaşıldığında tüm margin kaybolmalı."""
    p = make_portfolio(cash=10_000.0)
    p.buy_leveraged(
        "BTCUSDT", margin_usdt=500.0, leverage=5,
        price=50_000.0, stop=45_000.0, target=65_000.0,
    )
    liq_price = p.positions["BTCUSDT"].liquidation_price
    result = p.sell("BTCUSDT", price=liq_price)
    assert "BTCUSDT" not in p.positions
    assert "LİKİDE" in result
    assert p.cash == pytest.approx(10_000.0 - 500.0, abs=1.0)  # margin tamamen kayboldu


def test_check_triggers_likidasyon():
    """check_triggers likidasyon tetikleyicisini döndürmeli."""
    p = make_portfolio(cash=10_000.0)
    p.buy_leveraged(
        "ETHUSDT", margin_usdt=200.0, leverage=4,
        price=3_000.0, stop=2_700.0, target=3_600.0,
    )
    liq = p.positions["ETHUSDT"].liquidation_price
    triggers = p.check_triggers({"ETHUSDT": liq - 1.0})
    assert len(triggers) == 1
    assert triggers[0][1] == "liquidation"


def test_equity_leverage_sifirdan_asagi_gitmez():
    """Leveraged pozisyon için equity asla sıfırın altına düşmemeli."""
    p = make_portfolio(cash=5_000.0)
    p.buy_leveraged(
        "BTCUSDT", margin_usdt=500.0, leverage=5,
        price=50_000.0, stop=45_000.0, target=65_000.0,
    )
    # Fiyat sıfıra düşse bile equity negatif olmamalı
    eq = p.equity({"BTCUSDT": 1.0})
    assert eq >= 0.0


# ── 5. Veri kalitesi ve kaldıraç izin filtresi ────────────────────────────────

def test_binance_kripto_realtime_ve_izinli():
    """Binance kripto sembolleri realtime ve leverage_allowed olmalı."""
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT", "PAXGUSDT"):
        assert data_quality(sym) == "realtime", f"{sym} realtime değil"
        assert leverage_allowed(sym) is True, f"{sym} leverage_allowed değil"


def test_yahoo_forex_delayed_ve_izinsiz():
    """Yahoo Finance forex sembolleri delayed ve leverage_allowed=False olmalı."""
    for sym in SCAN_FOREX:
        assert data_quality(sym) == "delayed", f"{sym} delayed değil"
        assert leverage_allowed(sym) is False, f"{sym} leverage_allowed=True olmamalı"


def test_yahoo_endeks_delayed_ve_izinsiz():
    """Yahoo Finance endeks sembolleri delayed ve leverage_allowed=False olmalı."""
    for sym in SCAN_ENDEKS:
        assert data_quality(sym) == "delayed", f"{sym} delayed değil"
        assert leverage_allowed(sym) is False, f"{sym} leverage_allowed=True olmamalı"


def test_altin_gumus_near_realtime_ve_izinsiz():
    """Altın/gümüş (goldprice.org) near_realtime ama leverage_allowed=False olmalı."""
    assert data_quality("GC=F") == "near_realtime"
    assert leverage_allowed("GC=F") is False
    assert data_quality("SI=F") == "near_realtime"
    assert leverage_allowed("SI=F") is False


def test_emtia_futures_delayed_ve_izinsiz():
    """Petrol, doğalgaz, bakır Yahoo gecikmeli ve leverage izinsiz olmalı."""
    for sym in ("CL=F", "NG=F", "HG=F"):
        assert data_quality(sym) == "delayed", f"{sym} delayed değil"
        assert leverage_allowed(sym) is False, f"{sym} leverage izinsiz olmalı"


def test_bist_delayed_ve_izinsiz():
    """BIST100 Yahoo gecikmeli ve leverage izinsiz olmalı."""
    assert data_quality("XU100.IS") == "delayed"
    assert leverage_allowed("XU100.IS") is False


def test_leverage_eligible_symbols_sadece_kripto_doner():
    """/tara kaldirac için eligible filter sadece kripto sembol döndürmeli."""
    mixed = ["BTCUSDT", "ETHUSDT", "GC=F", "EURUSD=X", "^GSPC", "SOLUSDT"]
    eligible = leverage_eligible_symbols(mixed)
    assert set(eligible) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
    for s in eligible:
        assert leverage_allowed(s) is True


def test_leverage_eligible_bos_watchlist():
    """Tüm semboller Yahoo ise eligible boş liste döner — uyarı tetiklemeli."""
    only_yahoo = ["GC=F", "SI=F", "EURUSD=X", "^GSPC", "XU100.IS"]
    eligible = leverage_eligible_symbols(only_yahoo)
    assert eligible == []


def test_data_quality_label_okunabilir():
    """data_quality_label beklenen etiketleri döndürmeli."""
    assert "Anlık" in data_quality_label("BTCUSDT")
    assert "Yakın" in data_quality_label("GC=F")
    assert "Gecikmeli" in data_quality_label("EURUSD=X")


def test_leverage_reason_kripto_gerekce_icerir():
    """Kripto gerekçesi Binance kelimesini içermeli."""
    reason = leverage_reason("BTCUSDT")
    assert "Binance" in reason
    assert "anlık" in reason.lower() or "realtime" in reason.lower()


def test_leverage_reason_yahoo_gerekce_icerir():
    """Yahoo gerekçesi gecikmeli/izinsiz bilgisini içermeli."""
    reason = leverage_reason("EURUSD=X")
    assert "izinsiz" in reason.lower()


def test_delayed_veriyle_kaldirac_izni_yok():
    """Gecikmeli (delayed) semboller kaldıraç adayı olamaz — filtreden düşmeli."""
    delayed_syms = ["GC=F", "CL=F", "EURUSD=X", "^GSPC", "XU100.IS"]
    for sym in delayed_syms:
        assert not leverage_allowed(sym), (
            f"{sym} leverage_allowed=True döndü ama delayed/near_realtime veri"
        )


# ── 6. Pozisyon görünümü hesaplamaları ───────────────────────────────────────

def test_liq_distance_hesaplanir():
    """Likidasyon mesafesi (%) doğru hesaplanmalı."""
    p = make_portfolio(cash=10_000.0)
    p.buy_leveraged(
        "BTCUSDT", margin_usdt=500.0, leverage=3,
        price=50_000.0, stop=47_000.0, target=58_000.0,
    )
    pos = p.positions["BTCUSDT"]
    cur = 50_000.0
    liq = pos.liquidation_price
    liq_dist_pct = (cur - liq) / cur * 100
    # 3x, liq ≈ 50000*(1-1/3+0.005) = 50000*0.671667 ≈ 33583
    # dist = (50000-33583)/50000*100 ≈ 32.8%
    assert liq_dist_pct > 0
    assert liq_dist_pct < 100
    assert liq < cur  # liq her zaman anlık fiyatın altında (long)


def test_stop_distance_hesaplanir():
    """Stop mesafesi (%) doğru hesaplanmalı."""
    p = make_portfolio(cash=10_000.0)
    p.buy_leveraged(
        "BTCUSDT", margin_usdt=200.0, leverage=2,
        price=50_000.0, stop=47_500.0, target=57_000.0,
    )
    cur = 50_000.0
    stop = p.positions["BTCUSDT"].stop
    stop_dist_pct = (cur - stop) / cur * 100
    # (50000-47500)/50000*100 = 5%
    assert abs(stop_dist_pct - 5.0) < 0.01


def test_liq_stop_yakin_uyari_kosulu():
    """Likidasyon stop'a yakınsa uyarı koşulu doğru tetiklenmeli."""
    # liq_stop_gap < stop_entry_range * 0.4 → uyarı
    entry = 100.0
    # 5x: liq = 100*(1-0.2+0.005) = 80.5
    liq = calc_liquidation_price(entry, 5)
    stop = 85.0  # stop entry'den 15 puan düşük
    stop_entry_range = entry - stop  # 15
    liq_stop_gap = stop - liq          # 85 - 80.5 = 4.5
    # 4.5 < 15 * 0.4 = 6.0 → uyarı tetiklenmeli
    assert liq_stop_gap < stop_entry_range * 0.4, (
        f"Uyarı koşulu sağlanmadı: liq_stop_gap={liq_stop_gap:.2f} "
        f"threshold={stop_entry_range * 0.4:.2f}"
    )


def test_karli_kaldiracli_pozisyonda_stop_guncelle_uretilir():
    """Kârlı kaldıraçlı pozisyonda STOP_GUNCELLE kararı üretilebilmeli."""
    from ai import PositionDecision
    # Kârlı senaryo: entry=50000, cur=51500 → %3 kâr
    entry = 50_000.0
    cur = 51_500.0
    profit_pct = (cur - entry) / entry * 100
    assert profit_pct >= 2.0, "Test senaryosu kârlı olmalı"

    # Break-even stop hesabı
    be_stop = round(entry * 1.0005, 8)
    assert be_stop > entry
    assert be_stop < cur

    # STOP_GUNCELLE kararı geçerli stop_loss ile oluşturulabilmeli
    pd_item = PositionDecision(
        sembol="BTCUSDT",
        karar="STOP_GUNCELLE",
        gerekce="Kaldıraçlı %3 kâr — break-even koruması",
        new_stop_loss=be_stop,
    )
    assert pd_item.karar == "STOP_GUNCELLE"
    assert pd_item.new_stop_loss > entry

    # validate_stop_update onaylamalı
    from portfolio import validate_stop_update
    valid, msg = validate_stop_update(
        entry=entry,
        current_price=cur,
        current_stop=48_000.0,
        new_stop=be_stop,
    )
    assert valid is True, f"Geçersiz stop: {msg}"
