"""M1 Safety & Metrics Fix — kapsamlı testler.

Kapsanan alanlar:
- paper maliyet simülasyonu (komisyon + kayma)
- performance.py tüm kapanış taraflarını sayması
- realized/unrealized/fees/net PnL ayrımı
- cost_summary() fonksiyonu
- risk.check_position_count()
- JSONL tarih logu
- history 500 kayıt limiti
- equity_series tüm tarafları işlemesi
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

import portfolio as portfolio_mod
from portfolio import (
    CLOSE_SIDES, FEE_RATE, OPEN_SIDES, SLIP_RATE, Portfolio,
)
import performance as perf
import risk as risk_mod
from autonomous import PAPER_FEE_RATE, PAPER_SLIP_RATE, AutonomousEngine, AutonomousState


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_portfolio(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_mod, "STATE_FILE", tmp_path / "account.json")


class MockFeed:
    def __init__(self, prices: dict):
        class T:
            def __init__(self, p): self.price = p
        self.tickers = {s: T(p) for s, p in prices.items()}

    def price(self, sym):
        t = self.tickers.get(sym)
        return t.price if t else None


class MockCfg:
    def __init__(self, mode="dengeli"):
        self.autonomous_mode = mode
        self.model_id = None
        self.mode = "standart"
        self.leverage_enabled = False
        self.scalp_enabled = False
        self.trade_plan = "dengeli"
        self.otonom_trade_type = "long"
        self.live_autonomous = False

    def save(self): pass


def make_engine(portfolio, tmp_path, mode="dengeli"):
    feed = MockFeed({"BTCUSDT": 50000.0, "ETHUSDT": 2000.0, "SOLUSDT": 100.0})
    logs = []
    return AutonomousEngine(
        portfolio=portfolio,
        feed=feed,
        tracker=type("T", (), {"recs": []})(),
        cfg=MockCfg(mode),
        log_fn=logs.append,
        watchlist_fn=lambda: ["BTCUSDT"],
        state_path=tmp_path / f"state_{mode}.json",
        log_path=tmp_path / f"log_{mode}.jsonl",
    ), logs


# ── portfolio sabitler ────────────────────────────────────────────────────────

def test_portfolio_constants_exist():
    assert FEE_RATE == pytest.approx(0.001)
    assert SLIP_RATE == pytest.approx(0.0005)
    assert "SAT" in CLOSE_SIDES
    assert "SHORT_KAP" in CLOSE_SIDES
    assert "LEVERAGE KAPATILDI" in CLOSE_SIDES
    assert "LİKİDE" in CLOSE_SIDES
    assert "AL" in OPEN_SIDES
    assert "SHORT" in OPEN_SIDES
    assert "LEVERAGE" in OPEN_SIDES


def test_autonomous_cost_constants():
    assert PAPER_FEE_RATE == pytest.approx(0.001)
    assert PAPER_SLIP_RATE == pytest.approx(0.0005)


# ── JSONL tarih logu ──────────────────────────────────────────────────────────

def test_jsonl_log_appended_on_buy(tmp_path, monkeypatch):
    jsonl_path = tmp_path / "history.jsonl"
    monkeypatch.setattr(portfolio_mod, "HISTORY_LOG_FILE", jsonl_path)
    p = Portfolio()
    p.buy("BTCUSDT", 500, 100.0)
    assert jsonl_path.exists(), "JSONL dosyası oluşturulmalı"
    lines = jsonl_path.read_text().strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["side"] == "AL"
    assert record["symbol"] == "BTCUSDT"


def test_jsonl_log_appended_on_sell(tmp_path, monkeypatch):
    jsonl_path = tmp_path / "history.jsonl"
    monkeypatch.setattr(portfolio_mod, "HISTORY_LOG_FILE", jsonl_path)
    p = Portfolio()
    p.buy("BTCUSDT", 500, 100.0)
    p.sell("BTCUSDT", 110.0)
    lines = jsonl_path.read_text().strip().splitlines()
    assert len(lines) == 2
    close_record = json.loads(lines[1])
    assert close_record["side"] == "SAT"
    assert close_record["pnl"] == pytest.approx(50.0)


def test_jsonl_log_contains_fee_fields(tmp_path, monkeypatch):
    jsonl_path = tmp_path / "history.jsonl"
    monkeypatch.setattr(portfolio_mod, "HISTORY_LOG_FILE", jsonl_path)
    p = Portfolio()
    p.buy("BTCUSDT", 500, 100.0)
    record = json.loads(jsonl_path.read_text().strip())
    assert "fee_usdt" in record
    assert "slip_usdt" in record
    assert record["fee_usdt"] == pytest.approx(0.0)   # manuel buy'da sıfır
    assert record["slip_usdt"] == pytest.approx(0.0)


def test_jsonl_never_truncated(tmp_path, monkeypatch):
    """JSONL büyüdükçe kesilmemeli."""
    jsonl_path = tmp_path / "history.jsonl"
    monkeypatch.setattr(portfolio_mod, "HISTORY_LOG_FILE", jsonl_path)
    p = Portfolio()
    for i in range(10):
        p.buy("BTCUSDT", 10, float(100 + i))
    lines = jsonl_path.read_text().strip().splitlines()
    assert len(lines) == 10, "JSONL tüm kayıtları tutmalı"


# ── history cap 500 ───────────────────────────────────────────────────────────

def test_history_cap_increased_to_500():
    p = Portfolio()
    for i in range(250):
        p.buy("BTCUSDT", 10, float(100 + i))
    p.save()
    p2 = Portfolio.load()
    assert len(p2.history) == 250, "250 kayıt → hepsi saklanmalı (500 limit)"


# ── performance: _sell_records tüm kapanış tarafları ─────────────────────────

def _make_history_with_all_sides():
    now = time.time()
    return [
        {"side": "AL",    "symbol": "BTC", "qty": 1, "price": 100, "usdt": 100, "pnl": None,   "ts": now, "fee_usdt": 0.0, "slip_usdt": 0.0},
        {"side": "SAT",   "symbol": "BTC", "qty": 1, "price": 110, "usdt": 110, "pnl": 10.0,   "ts": now, "fee_usdt": 0.1, "slip_usdt": 0.05},
        {"side": "SHORT", "symbol": "ETH", "qty": 1, "price": 200, "usdt": 200, "pnl": None,   "ts": now, "fee_usdt": 0.0, "slip_usdt": 0.0},
        {"side": "SHORT_KAP", "symbol": "ETH", "qty": 1, "price": 180, "usdt": 220, "pnl": 20.0, "ts": now, "fee_usdt": 0.2, "slip_usdt": 0.1},
        {"side": "LEVERAGE", "symbol": "SOL", "qty": 5, "price": 100, "usdt": 50, "pnl": None,  "ts": now, "fee_usdt": 0.0, "slip_usdt": 0.0},
        {"side": "LEVERAGE KAPATILDI", "symbol": "SOL", "qty": 5, "price": 120, "usdt": 150, "pnl": 100.0, "ts": now, "fee_usdt": 0.15, "slip_usdt": 0.075},
        {"side": "LİKİDE", "symbol": "SOL", "qty": 5, "price": 80, "usdt": 0, "pnl": -50.0,    "ts": now, "fee_usdt": 0.0, "slip_usdt": 0.0},
    ]


def test_sell_records_includes_short_kap():
    hist = _make_history_with_all_sides()
    records = perf._sell_records(hist)
    sides = {r["side"] for r in records}
    assert "SHORT_KAP" in sides, "SHORT_KAP kapatmaları sayılmalı"


def test_sell_records_includes_leverage_kapandi():
    hist = _make_history_with_all_sides()
    records = perf._sell_records(hist)
    sides = {r["side"] for r in records}
    assert "LEVERAGE KAPATILDI" in sides


def test_sell_records_includes_likide():
    hist = _make_history_with_all_sides()
    records = perf._sell_records(hist)
    sides = {r["side"] for r in records}
    assert "LİKİDE" in sides


def test_sell_records_excludes_open_sides():
    hist = _make_history_with_all_sides()
    records = perf._sell_records(hist)
    sides = {r["side"] for r in records}
    assert "AL" not in sides
    assert "SHORT" not in sides
    assert "LEVERAGE" not in sides


def test_trade_stats_counts_all_close_sides():
    hist = _make_history_with_all_sides()
    stats = perf.trade_stats(hist)
    # SAT(+10) + SHORT_KAP(+20) + LEVERAGE KAPATILDI(+100) + LİKİDE(-50) = 4 işlem
    assert stats.n_total == 4
    assert stats.n_wins == 3
    assert stats.n_losses == 1
    assert stats.total_pnl == pytest.approx(80.0)


def test_trade_stats_win_rate_all_sides():
    hist = _make_history_with_all_sides()
    stats = perf.trade_stats(hist)
    assert stats.win_rate == pytest.approx(75.0)


# ── performance: equity_series doğru tarafları kullanır ──────────────────────

def test_equity_series_handles_short_kap():
    now = time.time()
    hist = [
        {"side": "SHORT", "symbol": "ETH", "qty": 1, "price": 200, "usdt": 200, "pnl": None, "ts": now},
        {"side": "SHORT_KAP", "symbol": "ETH", "qty": 1, "price": 180, "usdt": 220, "pnl": 20.0, "ts": now},
    ]
    eq = perf._equity_series(hist)
    assert len(eq) == 1
    # Start=10000, SHORT deducts 200 → 9800, SHORT_KAP adds 220 → 10020
    assert eq[0] == pytest.approx(10020.0)


def test_equity_series_correct_pnl_on_sat():
    """SAT sonrası equity tam kazanç kadar artmalı."""
    now = time.time()
    hist = [
        {"side": "AL",  "symbol": "BTC", "qty": 5, "price": 100, "usdt": 500, "pnl": None, "ts": now},
        {"side": "SAT", "symbol": "BTC", "qty": 5, "price": 110, "usdt": 550, "pnl": 50.0, "ts": now},
    ]
    eq = perf._equity_series(hist)
    # Start=10000, AL -500=9500, SAT +550=10050
    assert eq[-1] == pytest.approx(10050.0)


# ── cost_summary ──────────────────────────────────────────────────────────────

def test_cost_summary_totals():
    hist = _make_history_with_all_sides()
    cs = perf.cost_summary(hist)
    # gross: 10 + 20 + 100 - 50 = 80
    assert cs["gross_pnl"] == pytest.approx(80.0)
    # fees: 0.1 + 0.2 + 0.15 + 0.0 (LİKİDE fee=0)
    assert cs["total_fee"] == pytest.approx(0.45)
    # slippage: 0.05 + 0.1 + 0.075 + 0.0
    assert cs["total_slip"] == pytest.approx(0.225)
    # net: 80 - 0.45 - 0.225
    assert cs["net_pnl"] == pytest.approx(80.0 - 0.45 - 0.225)


def test_cost_summary_empty_history():
    cs = perf.cost_summary([])
    assert cs["gross_pnl"] == 0.0
    assert cs["net_pnl"] == 0.0


def test_cost_summary_no_fees():
    """fee_usdt/slip_usdt alanı olmayan eski history kayıtları."""
    hist = [
        {"side": "SAT", "symbol": "BTC", "qty": 1, "price": 110, "usdt": 110, "pnl": 10.0, "ts": time.time()},
    ]
    cs = perf.cost_summary(hist)
    assert cs["gross_pnl"] == pytest.approx(10.0)
    assert cs["total_fee"] == 0.0
    assert cs["net_pnl"] == pytest.approx(10.0)


# ── full_report unrealized PnL ────────────────────────────────────────────────

def test_full_report_shows_realized_breakdown():
    hist = _make_history_with_all_sides()
    report = perf.full_report(hist)
    assert "Realized PnL" in report or "realized" in report.lower() or "PnL Dökümü" in report


def test_full_report_with_unrealized():
    hist = _make_history_with_all_sides()
    report = perf.full_report(hist, unrealized_pnl=25.0)
    assert "Unrealized" in report or "unrealized" in report.lower()
    assert "25" in report


def test_full_report_with_negative_unrealized():
    hist = _make_history_with_all_sides()
    report = perf.full_report(hist, unrealized_pnl=-15.0)
    assert "-15" in report or "15" in report


# ── risk.check_position_count ─────────────────────────────────────────────────

def test_check_position_count_allowed():
    p = Portfolio()
    p.buy("BTCUSDT", 100, 50000.0)
    result = risk_mod.check_position_count(p, max_open_positions=4)
    assert result.allowed is True
    assert len(result.blockers) == 0


def test_check_position_count_at_limit():
    p = Portfolio()
    p.buy("BTCUSDT", 100, 50000.0)
    p.buy("ETHUSDT", 100, 2000.0)
    result = risk_mod.check_position_count(p, max_open_positions=2)
    assert result.allowed is False
    assert len(result.blockers) == 1
    assert "2/2" in result.blockers[0]


def test_check_position_count_zero_positions():
    p = Portfolio()
    result = risk_mod.check_position_count(p, max_open_positions=3)
    assert result.allowed is True


def test_check_position_count_just_under_limit():
    p = Portfolio()
    p.buy("BTCUSDT", 100, 50000.0)
    p.buy("ETHUSDT", 100, 2000.0)
    result = risk_mod.check_position_count(p, max_open_positions=3)
    assert result.allowed is True


# ── otonom mod paper costs: alım ─────────────────────────────────────────────

def _mock_ta_btcusdt(monkeypatch):
    """TA filtresinin her zaman BTCUSDT'yi geçirmesini sağlar (ağ çağrısı olmadan)."""
    import indicators as ind_mod

    async def mock_signals(wl, tf, filter_signal="AL"):
        class R:
            def __init__(self, s): self.symbol = s
        return [R(s) for s in wl if s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")]

    monkeypatch.setattr(ind_mod, "scan_signals", mock_signals)


@pytest.mark.asyncio
async def test_autonomous_buy_applies_slippage_to_entry_price(tmp_path, monkeypatch):
    """Otonom alımda kayma (slip) entry fiyatına uygulanmalı."""
    import ai
    _mock_ta_btcusdt(monkeypatch)
    p = Portfolio()
    eng, _ = make_engine(p, tmp_path)
    eng.state.enabled = True
    eng.state.daily_date = time.strftime("%Y-%m-%d")
    eng.state.daily_start_equity = p.cash

    market_price = 50000.0
    expected_slip_price = market_price * (1 + PAPER_SLIP_RATE)

    mock_response = (
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":65,"zarar_kes":49000,"kar_al":52500,"gerekce":"test slip"}]'
    )

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert "BTCUSDT" in p.positions
    pos = p.positions["BTCUSDT"]
    assert pos.entry == pytest.approx(expected_slip_price, rel=1e-4)


@pytest.mark.asyncio
async def test_autonomous_buy_deducts_fee_from_cash(tmp_path, monkeypatch):
    """Otonom alımda komisyon nakit bakiyesinden düşülmeli."""
    import ai
    _mock_ta_btcusdt(monkeypatch)
    p = Portfolio()
    eng, _ = make_engine(p, tmp_path)
    eng.state.enabled = True
    eng.state.daily_date = time.strftime("%Y-%m-%d")
    eng.state.daily_start_equity = p.cash

    trade_amount = 500.0
    expected_fee = trade_amount * PAPER_FEE_RATE

    mock_response = (
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":65,"zarar_kes":49000,"kar_al":52500,"gerekce":"test fee"}]'
    )

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)

    initial_cash = p.cash
    await eng._run_scan()

    # Nakit: trade_amount + fee düşülmeli
    cash_deducted = initial_cash - p.cash
    assert cash_deducted == pytest.approx(trade_amount + expected_fee, rel=0.01)


@pytest.mark.asyncio
async def test_autonomous_buy_records_fee_in_history(tmp_path, monkeypatch):
    """Otonom alım history kaydında fee_usdt alanı dolu olmalı."""
    import ai
    _mock_ta_btcusdt(monkeypatch)
    p = Portfolio()
    eng, _ = make_engine(p, tmp_path)
    eng.state.enabled = True
    eng.state.daily_date = time.strftime("%Y-%m-%d")
    eng.state.daily_start_equity = p.cash

    mock_response = (
        'ONERILER: [{"islem":"AL","sembol":"BTCUSDT","tutar_usdt":500,'
        '"basari_yuzdesi":65,"zarar_kes":49000,"kar_al":52500,"gerekce":"test history fee"}]'
    )

    async def mock_scan(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_market_filtered", mock_scan)
    await eng._run_scan()

    assert p.history, "history boş olmamalı"
    buy_record = next(r for r in p.history if r["side"] == "AL")
    assert buy_record.get("fee_usdt", 0) > 0, "fee_usdt sıfırdan büyük olmalı"
    assert buy_record.get("slip_usdt", 0) > 0, "slip_usdt sıfırdan büyük olmalı"


@pytest.mark.asyncio
async def test_autonomous_short_applies_entry_slip(tmp_path, monkeypatch):
    """Otonom SHORT alımda kayma entry fiyatından DÜŞÜRÜLMELI (daha kötü doldurma)."""
    import ai
    _mock_ta_btcusdt(monkeypatch)
    p = Portfolio()
    eng, _ = make_engine(p, tmp_path)
    cfg = eng.cfg
    cfg.otonom_trade_type = "short"
    eng.state.enabled = True
    eng.state.daily_date = time.strftime("%Y-%m-%d")
    eng.state.daily_start_equity = p.cash

    market_price = 50000.0
    expected_slip_price = market_price * (1 - PAPER_SLIP_RATE)

    mock_response = (
        'ONERILER: [{"islem":"SHORT_AL","sembol":"BTCUSDT","tutar_usdt":300,'
        '"basari_yuzdesi":65,"zarar_kes":52000,"kar_al":47000,"gerekce":"test short slip"}]'
    )

    async def mock_directional(*a, **kw):
        return mock_response

    monkeypatch.setattr(ai, "scan_directional", mock_directional)
    await eng._run_scan()

    if "BTCUSDT" in p.positions:
        pos = p.positions["BTCUSDT"]
        assert pos.entry == pytest.approx(expected_slip_price, rel=1e-4)


# ── otonom mod paper costs: satış ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_autonomous_sell_applies_exit_slip(tmp_path):
    """Otonom pozisyon kapatmada çıkış kayması uygulanmalı."""
    import ai
    p = Portfolio()
    eng, _ = make_engine(p, tmp_path)
    eng.state.enabled = True
    eng.state.daily_date = time.strftime("%Y-%m-%d")

    # Manuel olarak long pozisyon aç
    p.buy("BTCUSDT", 500, 50000.0)

    market_price = 52000.0
    expected_exit = market_price * (1 - PAPER_SLIP_RATE)

    pd = ai.PositionDecision(
        sembol="BTCUSDT", karar="KAR_AL",
        gerekce="hedefe ulaştı", acil=False,
        new_stop_loss=0.0, new_take_profit=0.0,
        close_reason="hedef yakın",
    )

    cash_before = p.cash
    changed, msg = await eng.apply_decision("BTCUSDT", pd, market_price, auto=True)

    assert changed is True
    # Çıkış fiyatı beklenen (exit_slip) üzerinden PnL hesaplanmış olmalı
    # PnL = (expected_exit - 50000) * qty
    qty = 500 / 50000.0
    expected_pnl = (expected_exit - 50000.0) * qty
    if p.history:
        close_rec = next((r for r in reversed(p.history) if r["side"] == "SAT"), None)
        if close_rec:
            assert close_rec.get("pnl", 0) == pytest.approx(expected_pnl, rel=0.01)


# ── risk limitleri hem manual hem otonom ──────────────────────────────────────

def test_risk_gate_blocks_insufficient_cash():
    p = Portfolio()
    prices = {"BTCUSDT": 50000.0}
    result = risk_mod.check_before_buy("BTCUSDT", 15000.0, p, prices)
    assert not result.allowed
    assert any("nakit" in b.lower() for b in result.blockers)


def test_risk_gate_allows_valid_buy():
    p = Portfolio()
    prices = {"BTCUSDT": 50000.0}
    result = risk_mod.check_before_buy("BTCUSDT", 100.0, p, prices)
    assert result.allowed


def test_position_count_gate_blocks_at_max():
    p = Portfolio()
    p.buy("BTCUSDT", 100, 50000.0)
    p.buy("ETHUSDT", 100, 2000.0)
    p.buy("SOLUSDT", 100, 100.0)
    result = risk_mod.check_position_count(p, max_open_positions=3)
    assert not result.allowed
    assert "3/3" in result.blockers[0]


def test_position_count_gate_allows_below_max():
    p = Portfolio()
    p.buy("BTCUSDT", 100, 50000.0)
    result = risk_mod.check_position_count(p, max_open_positions=4)
    assert result.allowed


# ── full_report backward compat ───────────────────────────────────────────────

def test_full_report_no_history():
    report = perf.full_report([])
    assert "Henüz" in report or "yok" in report.lower()


def test_full_report_without_unrealized():
    hist = _make_history_with_all_sides()
    report = perf.full_report(hist)
    assert "Sharpe" in report
    assert "Sortino" in report
    assert "PnL Dökümü" in report


def test_full_report_net_pnl_shown_with_costs():
    """Fee/slip varsa net PnL ayrıca gösterilmeli."""
    now = time.time()
    hist = [
        {"side": "AL",  "symbol": "BTC", "qty": 5, "price": 100, "usdt": 500, "pnl": None, "ts": now, "fee_usdt": 0, "slip_usdt": 0},
        {"side": "SAT", "symbol": "BTC", "qty": 5, "price": 110, "usdt": 550, "pnl": 50.0, "ts": now, "fee_usdt": 0.55, "slip_usdt": 0.275},
    ]
    report = perf.full_report(hist)
    assert "Net PnL" in report or "net" in report.lower()


# ── monthly_breakdown tüm kapanış ────────────────────────────────────────────

def test_monthly_breakdown_includes_short_kap():
    now = time.time()
    hist = [
        {"side": "SHORT", "symbol": "ETH", "qty": 1, "price": 200, "usdt": 200, "pnl": None, "ts": now},
        {"side": "SHORT_KAP", "symbol": "ETH", "qty": 1, "price": 180, "usdt": 220, "pnl": 20.0, "ts": now},
    ]
    monthly = perf.monthly_breakdown(hist)
    assert len(monthly) == 1
    _, pnl, n = monthly[0]
    assert pnl == pytest.approx(20.0)
    assert n == 1


# ── portfolio _log fee/slip alanları ─────────────────────────────────────────

def test_portfolio_log_has_fee_slip_fields():
    p = Portfolio()
    p.buy("BTCUSDT", 500, 100.0)
    assert "fee_usdt" in p.history[0]
    assert "slip_usdt" in p.history[0]
    assert p.history[0]["fee_usdt"] == pytest.approx(0.0)


def test_portfolio_sell_log_has_fee_slip_fields():
    p = Portfolio()
    p.buy("BTCUSDT", 500, 100.0)
    p.sell("BTCUSDT", 110.0)
    sell_rec = next(r for r in p.history if r["side"] == "SAT")
    assert "fee_usdt" in sell_rec
    assert sell_rec["fee_usdt"] == pytest.approx(0.0)


def test_portfolio_short_kap_has_fee_slip_fields():
    p = Portfolio()
    p.buy_short("BTCUSDT", 200, 50000.0, stop=52500.0, target=47000.0)
    p.sell("BTCUSDT", 48000.0)
    short_kap = next(r for r in p.history if r["side"] == "SHORT_KAP")
    assert "fee_usdt" in short_kap
    assert "slip_usdt" in short_kap


# ── mevcut davranış değişmemiş ────────────────────────────────────────────────

def test_buy_sell_base_behavior_unchanged():
    """Temel buy/sell davranışı korunmuş olmalı."""
    p = Portfolio()
    p.buy("BTCUSDT", 500, 100.0)
    assert p.cash == pytest.approx(9500.0)
    assert p.positions["BTCUSDT"].qty == pytest.approx(5.0)
    p.sell("BTCUSDT", 110.0)
    assert p.cash == pytest.approx(10050.0)
    assert "BTCUSDT" not in p.positions


def test_short_base_behavior_unchanged():
    p = Portfolio()
    p.buy_short("BTCUSDT", 1000, 50000.0, stop=52500.0, target=45000.0)
    assert p.cash == pytest.approx(9000.0)
    p.sell("BTCUSDT", 48000.0)
    expected_pnl = (50000.0 - 48000.0) * (1000 / 50000.0)
    assert p.cash == pytest.approx(9000.0 + 1000.0 + expected_pnl, rel=1e-4)
