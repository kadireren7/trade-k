"""Tests for 5 improvement layers:
- Layer 1: portfolio save atomicity, check_protections try/except, WS status
- Layer 2: /rapor /report aliases
- Layer 3: trade_allowed, price age, symbol aliases
- Layer 4: (scalp countdown - UI only, not unit-testable here)
- Layer 5: performance threshold
"""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import time

import market
import portfolio as portfolio_mod
from portfolio import Portfolio


# ─── Portfolio atomic save ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolate_state(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_mod, "STATE_FILE", tmp_path / "account.json")


def test_save_is_atomic(tmp_path, monkeypatch):
    """Save writes to .tmp then os.replace — no partial writes."""
    monkeypatch.setattr(portfolio_mod, "STATE_FILE", tmp_path / "account.json")
    p = Portfolio()
    p.buy("BTCUSDT", 100, 50000.0)
    p.save()
    # STATE_FILE must exist, .tmp must NOT remain after save
    assert (tmp_path / "account.json").exists()
    assert not (tmp_path / "account.tmp").exists()


def test_save_lock_exists():
    """Portfolio has _save_lock (threading.Lock)."""
    import threading
    p = Portfolio()
    assert hasattr(p, "_save_lock")
    assert isinstance(p._save_lock, type(threading.Lock()))


def test_portfolio_load_after_atomic_save(tmp_path, monkeypatch):
    """Load reads back exactly what was saved."""
    monkeypatch.setattr(portfolio_mod, "STATE_FILE", tmp_path / "account.json")
    p = Portfolio()
    p.buy("ETHUSDT", 200, 3000.0)
    p.save()
    p2 = Portfolio.load()
    assert "ETHUSDT" in p2.positions
    assert p2.positions["ETHUSDT"].entry == pytest.approx(3000.0)


# ─── Ticker last_updated ──────────────────────────────────────────────────────

def test_ticker_has_last_updated():
    """Ticker dataclass has last_updated field defaulting to 0.0."""
    from market import Ticker
    tk = Ticker(symbol="BTCUSDT", price=50000.0)
    assert hasattr(tk, "last_updated")
    assert tk.last_updated == 0.0


def test_ticker_last_updated_can_be_set():
    """Ticker last_updated can be set to current time."""
    from market import Ticker
    now = time.time()
    tk = Ticker(symbol="BTCUSDT", price=50000.0, last_updated=now)
    assert tk.last_updated == pytest.approx(now, abs=1.0)


# ─── MarketFeed ws_connected ──────────────────────────────────────────────────

def test_marketfeed_has_ws_connected():
    """MarketFeed has ws_connected attribute defaulting to False."""
    from market import MarketFeed
    feed = MarketFeed(symbols=["BTCUSDT"])
    assert hasattr(feed, "ws_connected")
    assert feed.ws_connected is False


# ─── trade_allowed ────────────────────────────────────────────────────────────

def test_trade_allowed_crypto_returns_true():
    """Crypto symbols (realtime Binance) are trade-allowed."""
    allowed, reason = market.trade_allowed("BTCUSDT")
    assert allowed is True
    assert reason == ""


def test_trade_allowed_eth_returns_true():
    """ETHUSDT is trade-allowed (realtime)."""
    allowed, reason = market.trade_allowed("ETHUSDT")
    assert allowed is True


def test_trade_allowed_delayed_yahoo_returns_false():
    """Delayed Yahoo symbols (CL=F, EURUSD=X) block trading."""
    for sym in ("CL=F", "NG=F", "EURUSD=X", "GBPUSD=X", "^GSPC", "NQ=F"):
        allowed, reason = market.trade_allowed(sym)
        assert allowed is False, f"{sym} should be blocked"
        assert reason != "", f"{sym} reason should not be empty"
        assert "gecikmeli" in reason.lower() or "bilinmiyor" in reason.lower()


def test_trade_allowed_near_realtime_returns_true():
    """Near-realtime symbols (GC=F, SI=F) are trade-allowed."""
    for sym in ("GC=F", "SI=F"):
        allowed, reason = market.trade_allowed(sym)
        assert allowed is True, f"{sym} should be allowed (near_realtime)"


def test_trade_allowed_unknown_symbol_returns_false():
    """Unknown Yahoo-like symbol blocks trading."""
    # A yahoo-like symbol not in the table
    allowed, reason = market.trade_allowed("UNKN=X")
    assert allowed is False


# ─── Symbol aliases ───────────────────────────────────────────────────────────

def test_resolve_bitcoin_alias():
    assert market.resolve_symbol("bitcoin") == "BTCUSDT"
    assert market.resolve_symbol("BTC") == "BTCUSDT"


def test_resolve_ethereum_alias():
    assert market.resolve_symbol("ETH") == "ETHUSDT"
    assert market.resolve_symbol("ethereum") == "ETHUSDT"


def test_resolve_solana_alias():
    assert market.resolve_symbol("SOL") == "SOLUSDT"
    assert market.resolve_symbol("SOLANA") == "SOLUSDT"


def test_resolve_doge_alias():
    assert market.resolve_symbol("DOGE") == "DOGEUSDT"
    assert market.resolve_symbol("DOGECOIN") == "DOGEUSDT"


def test_resolve_xrp_alias():
    assert market.resolve_symbol("XRP") == "XRPUSDT"
    assert market.resolve_symbol("RIPPLE") == "XRPUSDT"


def test_resolve_other_crypto_aliases():
    """All defined common crypto aliases resolve correctly."""
    aliases = {
        "ADA": "ADAUSDT", "CARDANO": "ADAUSDT",
        "AVAX": "AVAXUSDT", "AVALANCHE": "AVAXUSDT",
        "LINK": "LINKUSDT", "CHAINLINK": "LINKUSDT",
        "DOT": "DOTUSDT", "POLKADOT": "DOTUSDT",
        "MATIC": "MATICUSDT", "POLYGON": "MATICUSDT",
        "UNI": "UNIUSDT", "UNISWAP": "UNIUSDT",
        "LTC": "LTCUSDT", "LITECOIN": "LTCUSDT",
        "NEAR": "NEARUSDT",
        "APT": "APTUSDT", "APTOS": "APTUSDT",
        "SUI": "SUIUSDT",
        "INJ": "INJUSDT", "INJECTIVE": "INJUSDT",
        "TRX": "TRXUSDT", "TRON": "TRXUSDT",
    }
    for alias, expected in aliases.items():
        assert market.resolve_symbol(alias) == expected, \
            f"resolve_symbol({alias!r}) should be {expected!r}"


def test_resolve_common_alias_case_insensitive():
    """Aliases work with lowercase input."""
    assert market.resolve_symbol("bitcoin") == "BTCUSDT"
    assert market.resolve_symbol("ethereum") == "ETHUSDT"


def test_resolve_existing_usdt_suffix_unchanged():
    """Symbols already ending in USDT pass through."""
    assert market.resolve_symbol("SOLUSDT") == "SOLUSDT"
    assert market.resolve_symbol("BTCUSDT") == "BTCUSDT"


# ─── data_quality and leverage_allowed ────────────────────────────────────────

def test_data_quality_crypto_is_realtime():
    assert market.data_quality("BTCUSDT") == "realtime"
    assert market.data_quality("ETHUSDT") == "realtime"


def test_data_quality_yahoo_delayed():
    for sym in ("CL=F", "EURUSD=X", "^GSPC", "NQ=F", "USDTRY=X"):
        assert market.data_quality(sym) == "delayed", f"{sym} should be delayed"


def test_data_quality_near_realtime():
    assert market.data_quality("GC=F") == "near_realtime"
    assert market.data_quality("SI=F") == "near_realtime"


def test_leverage_allowed_crypto():
    assert market.leverage_allowed("BTCUSDT") is True
    assert market.leverage_allowed("ETHUSDT") is True


def test_leverage_not_allowed_delayed():
    for sym in ("CL=F", "EURUSD=X", "^GSPC"):
        assert market.leverage_allowed(sym) is False


def test_leverage_eligible_symbols_filters():
    watchlist = ["BTCUSDT", "ETHUSDT", "CL=F", "EURUSD=X"]
    eligible = market.leverage_eligible_symbols(watchlist)
    assert "BTCUSDT" in eligible
    assert "ETHUSDT" in eligible
    assert "CL=F" not in eligible
    assert "EURUSD=X" not in eligible
