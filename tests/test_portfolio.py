"""Sanal cüzdan testleri."""
import pytest

import portfolio as portfolio_mod
from portfolio import Portfolio


@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_mod, "STATE_FILE", tmp_path / "account.json")


def test_buy_sell_pnl():
    p = Portfolio()
    p.buy("BTCUSDT", 500, 100.0)
    assert p.cash == 9500
    assert p.positions["BTCUSDT"].qty == pytest.approx(5.0)
    p.sell("BTCUSDT", 110.0)
    assert p.cash == pytest.approx(10050)  # +%10 → +50
    assert "BTCUSDT" not in p.positions


def test_buy_insufficient_cash():
    p = Portfolio()
    with pytest.raises(ValueError):
        p.buy("BTCUSDT", 20_000, 100.0)


def test_sell_without_position():
    p = Portfolio()
    with pytest.raises(ValueError):
        p.sell("BTCUSDT", 100.0)


def test_average_entry_on_second_buy():
    p = Portfolio()
    p.buy("ETHUSDT", 100, 100.0)  # 1 adet @ 100
    p.buy("ETHUSDT", 200, 200.0)  # 1 adet @ 200
    pos = p.positions["ETHUSDT"]
    assert pos.qty == pytest.approx(2.0)
    assert pos.entry == pytest.approx(150.0)


def test_partial_sell():
    p = Portfolio()
    p.buy("BTCUSDT", 1000, 100.0)
    p.sell("BTCUSDT", 100.0, usdt=400)
    assert p.positions["BTCUSDT"].qty == pytest.approx(6.0)
    assert p.cash == pytest.approx(9400)


def test_equity_with_prices():
    p = Portfolio()
    p.buy("BTCUSDT", 1000, 100.0)
    assert p.equity({"BTCUSDT": 120.0}) == pytest.approx(9000 + 10 * 120)
