"""M2 Reporting & Telegram Polish — test suite.

Kapsam:
  - equity_breakdown() doğruluğu ve yapısı
  - closed_by_type() gruplama
  - telegram_summary() içerik ve format
  - full_report() genişletilmiş parametreler
  - _strip_rich() markup temizleme
  - Paper mode disclaimer varlığı
  - positions_data bölümü
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import performance as perf_mod
from performance import (
    STARTING_CASH,
    _strip_rich,
    closed_by_type,
    equity_breakdown,
    full_report,
    telegram_summary,
    trade_stats,
    cost_summary,
)


# ── Yardımcı fabrikalar ──────────────────────────────────────────────────────

def _buy(sym="BTCUSDT", usdt=500.0, ts_offset=0):
    return {"ts": time.time() - ts_offset, "side": "AL", "symbol": sym,
            "qty": usdt / 50000, "price": 50000.0, "usdt": usdt, "pnl": None,
            "fee_usdt": 0.0, "slip_usdt": 0.0}


def _sell(sym="BTCUSDT", pnl=50.0, usdt=550.0, ts_offset=0):
    return {"ts": time.time() - ts_offset, "side": "SAT", "symbol": sym,
            "qty": usdt / 52000, "price": 52000.0, "usdt": usdt, "pnl": pnl,
            "fee_usdt": 0.5, "slip_usdt": 0.25}


def _short_kap(sym="ETHUSDT", pnl=30.0, usdt=530.0, ts_offset=0):
    return {"ts": time.time() - ts_offset, "side": "SHORT_KAP", "symbol": sym,
            "qty": 0.25, "price": 1900.0, "usdt": usdt, "pnl": pnl,
            "fee_usdt": 0.3, "slip_usdt": 0.15}


def _scalp_kap(sym="SOLUSDT", pnl=10.0, usdt=110.0, ts_offset=0):
    return {"ts": time.time() - ts_offset, "side": "SCALP_KAP", "symbol": sym,
            "qty": 1.0, "price": 110.0, "usdt": usdt, "pnl": pnl,
            "fee_usdt": 0.1, "slip_usdt": 0.05}


def _lev_kap(sym="BTCUSDT", pnl=100.0, usdt=1100.0, ts_offset=0):
    return {"ts": time.time() - ts_offset, "side": "LEVERAGE KAPATILDI", "symbol": sym,
            "qty": 0.02, "price": 52000.0, "usdt": usdt, "pnl": pnl,
            "fee_usdt": 1.0, "slip_usdt": 0.5}


def _likit(sym="BTCUSDT", ts_offset=0):
    return {"ts": time.time() - ts_offset, "side": "LİKİDE", "symbol": sym,
            "qty": 0.02, "price": 40000.0, "usdt": 0.0, "pnl": -1000.0,
            "fee_usdt": 0.0, "slip_usdt": 0.0}


# ── equity_breakdown() ───────────────────────────────────────────────────────

def test_equity_breakdown_keys():
    bd = equity_breakdown([], cash=10000.0)
    expected = {
        "starting_equity", "current_equity", "cash", "pos_value",
        "realized_pnl", "unrealized_pnl", "gross_pnl",
        "total_fee", "total_slip", "net_pnl",
        "net_return_pct", "total_return_pct",
    }
    assert set(bd.keys()) == expected


def test_equity_breakdown_no_history():
    bd = equity_breakdown([], cash=9500.0, pos_value=600.0)
    assert bd["starting_equity"] == STARTING_CASH
    assert bd["cash"] == 9500.0
    assert bd["pos_value"] == 600.0
    assert bd["current_equity"] == pytest.approx(10100.0)
    assert bd["realized_pnl"] == 0.0
    assert bd["net_pnl"] == 0.0


def test_equity_breakdown_net_pnl_math():
    h = [_buy(), _sell(pnl=50.0, usdt=550.0)]
    bd = equity_breakdown(h, cash=9550.0, pos_value=0.0)
    costs = cost_summary(h)
    assert bd["gross_pnl"] == pytest.approx(costs["gross_pnl"])
    assert bd["total_fee"] == pytest.approx(costs["total_fee"])
    assert bd["net_pnl"] == pytest.approx(costs["net_pnl"])


def test_equity_breakdown_net_return_pct():
    h = [_buy(), _sell(pnl=100.0)]
    bd = equity_breakdown(h, cash=10100.0, starting_equity=10000.0)
    # net_pnl = gross - fee - slip = 100 - 0.5 - 0.25 = 99.25
    assert bd["net_return_pct"] == pytest.approx(bd["net_pnl"] / 10000.0 * 100, rel=1e-3)


def test_equity_breakdown_total_return_pct():
    bd = equity_breakdown([], cash=10500.0, pos_value=500.0, starting_equity=10000.0)
    # current_equity = 11000, total_return = 10%
    assert bd["total_return_pct"] == pytest.approx(10.0)


def test_equity_breakdown_with_unrealized():
    bd = equity_breakdown([], cash=9500.0, pos_value=600.0, unrealized_pnl=20.0)
    assert bd["unrealized_pnl"] == pytest.approx(20.0)


def test_equity_breakdown_custom_starting_equity():
    bd = equity_breakdown([], cash=5000.0, starting_equity=5000.0)
    assert bd["starting_equity"] == 5000.0
    assert bd["net_return_pct"] == pytest.approx(0.0)


# ── closed_by_type() ─────────────────────────────────────────────────────────

def test_closed_by_type_empty():
    groups = closed_by_type([])
    assert groups["LONG"]["count"] == 0
    assert groups["SHORT"]["count"] == 0
    assert groups["SCALP"]["count"] == 0
    assert groups["LEVERAGE"]["count"] == 0


def test_closed_by_type_long_only():
    h = [_buy(), _sell(pnl=50.0), _sell(pnl=-20.0)]
    groups = closed_by_type(h)
    assert groups["LONG"]["count"] == 2
    assert groups["LONG"]["wins"] == 1
    assert groups["LONG"]["losses"] == 1
    assert groups["SHORT"]["count"] == 0


def test_closed_by_type_short():
    h = [_short_kap(pnl=30.0), _short_kap(pnl=-10.0)]
    groups = closed_by_type(h)
    assert groups["SHORT"]["count"] == 2
    assert groups["SHORT"]["wins"] == 1


def test_closed_by_type_scalp():
    h = [_scalp_kap(pnl=5.0), _scalp_kap(pnl=8.0)]
    groups = closed_by_type(h)
    assert groups["SCALP"]["count"] == 2
    assert groups["SCALP"]["wins"] == 2
    assert groups["SCALP"]["win_rate"] == pytest.approx(100.0)


def test_closed_by_type_leverage():
    h = [_lev_kap(pnl=100.0), _likit()]
    groups = closed_by_type(h)
    assert groups["LEVERAGE"]["count"] == 2
    assert groups["LEVERAGE"]["wins"] == 1
    assert groups["LEVERAGE"]["losses"] == 1


def test_closed_by_type_all_types():
    h = [
        _buy(), _sell(pnl=50.0),
        _short_kap(pnl=30.0),
        _scalp_kap(pnl=10.0),
        _lev_kap(pnl=100.0),
    ]
    groups = closed_by_type(h)
    assert groups["LONG"]["count"] == 1
    assert groups["SHORT"]["count"] == 1
    assert groups["SCALP"]["count"] == 1
    assert groups["LEVERAGE"]["count"] == 1


def test_closed_by_type_win_rate():
    h = [_sell(pnl=50.0), _sell(pnl=30.0), _sell(pnl=-10.0), _sell(pnl=-5.0)]
    groups = closed_by_type(h)
    assert groups["LONG"]["win_rate"] == pytest.approx(50.0)


def test_closed_by_type_net_pnl_deducts_fees():
    h = [_sell(pnl=50.0)]  # fee_usdt=0.5, slip_usdt=0.25
    groups = closed_by_type(h)
    assert groups["LONG"]["total_pnl"] == pytest.approx(50.0)
    assert groups["LONG"]["net_pnl"] == pytest.approx(50.0 - 0.5 - 0.25)


def test_closed_by_type_open_records_ignored():
    h = [_buy(), _sell(pnl=20.0)]
    groups = closed_by_type(h)
    assert groups["LONG"]["count"] == 1


# ── telegram_summary() ───────────────────────────────────────────────────────

def test_telegram_summary_no_trades_format():
    msg = telegram_summary([], cash=10000.0, equity=10000.0)
    assert "Henüz kapalı işlem yok" in msg
    assert "10,000.00" in msg or "10000" in msg


def test_telegram_summary_no_trades_is_html():
    msg = telegram_summary([], cash=10000.0, equity=10000.0)
    assert "<b>" in msg or "<i>" in msg


def test_telegram_summary_with_trades_has_sections():
    h = [_buy(), _sell(pnl=50.0), _sell(pnl=-10.0)]
    msg = telegram_summary(h, cash=9540.0, equity=9540.0, n_positions=0)
    assert "Portföy" in msg
    assert "İşlemler" in msg or "Toplam" in msg
    assert "PnL" in msg or "K/Z" in msg
    assert "Net" in msg


def test_telegram_summary_net_pnl_present():
    h = [_buy(), _sell(pnl=50.0)]
    msg = telegram_summary(h, cash=9549.25, equity=9549.25)
    # Net = 50 - 0.5 - 0.25 = 49.25
    assert "49.25" in msg or "49,25" in msg


def test_telegram_summary_unrealized_shown():
    msg = telegram_summary([], cash=9900.0, equity=10100.0,
                           unrealized_pnl=200.0, n_positions=2)
    assert "200" in msg
    assert "2" in msg


def test_telegram_summary_paper_note():
    h = [_buy(), _sell(pnl=50.0)]
    msg = telegram_summary(h, cash=9549.25, equity=9549.25)
    assert "dosyaya" in msg or "rapor" in msg.lower()


def test_telegram_summary_win_rate_shown():
    h = [_buy(), _sell(pnl=50.0), _buy(), _sell(pnl=-10.0)]
    msg = telegram_summary(h, cash=9539.5, equity=9539.5)
    assert "50.0%" in msg or "50%" in msg


# ── _strip_rich() ────────────────────────────────────────────────────────────

def test_strip_rich_removes_color_tags():
    text = "[bold cyan]Merhaba[/] [green3]dünya[/]"
    assert _strip_rich(text) == "Merhaba dünya"


def test_strip_rich_removes_nested():
    text = "[bold][red3]test[/red3][/bold]"
    assert _strip_rich(text) == "test"


def test_strip_rich_keeps_content():
    text = "[bold]12,345.67 USDT[/]"
    assert "12,345.67 USDT" in _strip_rich(text)


def test_strip_rich_no_markup_unchanged():
    text = "plain text 100.00"
    assert _strip_rich(text) == text


# ── full_report() genişletilmiş parametreler ─────────────────────────────────

def test_full_report_paper_disclaimer_always_present():
    h = [_buy(), _sell(pnl=50.0)]
    report = full_report(h)
    assert "Paper" in report or "paper" in report
    assert "simülasyon" in report.lower() or "komisyon" in report.lower()


def test_full_report_paper_disclaimer_no_trades():
    report = full_report([])
    # Early return case — no disclaimer expected here for no trades
    assert "kapalı işlem" in report.lower()


def test_full_report_with_cash_shows_equity_section():
    h = [_buy(), _sell(pnl=50.0)]
    report = full_report(h, cash=9549.25, pos_value=0.0)
    assert "Portföy Durumu" in report
    assert "Nakit" in report
    assert "Mevcut Varlık" in report


def test_full_report_pnl_section_with_cash():
    h = [_buy(), _sell(pnl=50.0)]
    report = full_report(h, cash=9549.25, pos_value=0.0)
    assert "PnL Dökümü" in report
    assert "Komisyon" in report
    assert "Kayma" in report
    assert "Net PnL" in report


def test_full_report_with_positions_data():
    h = [_buy(), _sell(pnl=50.0)]
    pd_list = [{
        "symbol": "BTCUSDT", "side": "LONG",
        "entry": 50000.0, "current": 52000.0, "qty": 0.01,
        "unrealized_pnl": 20.0, "pnl_pct": 4.0,
        "stop": 47000.0, "target": 55000.0,
    }]
    report = full_report(h, cash=9549.25, positions_data=pd_list)
    assert "Açık Pozisyonlar" in report
    assert "BTC" in report
    assert "LONG" in report
    assert "50,000" in report or "50000" in report


def test_full_report_positions_shows_stop_and_target():
    h = [_buy(), _sell(pnl=50.0)]
    pd_list = [{
        "symbol": "ETHUSDT", "side": "SHORT",
        "entry": 2000.0, "current": 1900.0, "qty": 0.5,
        "unrealized_pnl": 50.0, "pnl_pct": 5.0,
        "stop": 2100.0, "target": 1800.0,
    }]
    report = full_report(h, cash=9549.25, positions_data=pd_list)
    assert "2,100" in report or "2100" in report
    assert "1,800" in report or "1800" in report


def test_full_report_positions_none_stop_shows_dash():
    h = [_buy(), _sell(pnl=50.0)]
    pd_list = [{
        "symbol": "SOLUSDT", "side": "LONG",
        "entry": 100.0, "current": 105.0, "qty": 5.0,
        "unrealized_pnl": 25.0, "pnl_pct": 5.0,
        "stop": None, "target": None,
    }]
    report = full_report(h, cash=9549.25, positions_data=pd_list)
    assert "—" in report


def test_full_report_closed_by_type_section():
    h = [_buy(), _sell(pnl=50.0), _short_kap(pnl=30.0), _scalp_kap(pnl=10.0)]
    report = full_report(h)
    assert "Tipe Göre" in report
    assert "LONG" in report
    assert "SHORT" in report
    assert "SCALP" in report


def test_full_report_no_type_section_if_no_trades():
    report = full_report([], cash=10000.0)
    # No trades → no type section
    assert "Tipe Göre" not in report


def test_full_report_backward_compat_no_cash():
    """cash param verilmeden mevcut davranış korunmalı."""
    h = [_buy(), _sell(pnl=50.0)]
    report = full_report(h)
    # Still shows PnL Dökümü (legacy section)
    assert "PnL Dökümü" in report


def test_full_report_backward_compat_unrealized():
    """unrealized_pnl parametresi cash olmadan çalışmalı."""
    h = [_buy(), _sell(pnl=50.0)]
    report = full_report(h, unrealized_pnl=25.0)
    assert "Unrealized" in report
    assert "25" in report


def test_full_report_unrealized_in_equity_breakdown_when_cash_given():
    h = [_buy(), _sell(pnl=50.0)]
    report = full_report(h, unrealized_pnl=25.0, cash=9549.25, pos_value=525.0)
    # unrealized should appear in the equity section
    assert "Unrealized" in report
    assert "25" in report


def test_full_report_issue_stats_section_always():
    h = [_buy(), _sell(pnl=50.0), _sell(pnl=-10.0)]
    report = full_report(h)
    assert "İşlem Özeti" in report
    assert "Kazanan" in report


def test_full_report_risk_section_present():
    # Need enough trades for Sharpe (5+ daily returns)
    h = []
    base = time.time() - 10 * 86400
    for i in range(6):
        h.append(_buy(ts_offset=-(i * 86400 + 3600)))
        h.append(_sell(ts_offset=-(i * 86400), pnl=20.0 - i * 5))
    report = full_report(h)
    assert "Risk-Adjusted" in report or "Sharpe" in report


def test_full_report_monthly_section():
    h = [_buy(ts_offset=86400), _sell(pnl=50.0, ts_offset=86400),
         _buy(), _sell(pnl=30.0)]
    report = full_report(h)
    assert "Aylık" in report


# ── write_report_txt integration ─────────────────────────────────────────────

def test_strip_rich_output_is_readable_text():
    h = [_buy(), _sell(pnl=50.0)]
    rich = full_report(h, cash=9549.25, pos_value=0.0)
    plain = _strip_rich(rich)
    # Should still contain numbers and Turkish keywords
    assert "USDT" in plain
    assert "50" in plain
    assert "Nakit" in plain or "PnL" in plain


def test_strip_rich_no_brackets_in_output():
    h = [_buy(), _sell(pnl=50.0)]
    plain = _strip_rich(full_report(h))
    # No Rich markup brackets should remain
    import re
    assert not re.search(r"\[[^\]]+\]", plain), "Rich markup still present in stripped text"
