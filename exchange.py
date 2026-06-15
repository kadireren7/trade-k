"""Exchange dispatcher — aktif borsaya göre doğru modülü seçer.

Desteklenen borsalar: binance (varsayılan), bybit, okx
Hepsi aynı arayüzü paylaşır: validate_keys, place_market_buy, place_market_sell,
place_oco_sell, cancel_open_orders, get_open_orders, get_usdt_balance, LiveError
"""
from __future__ import annotations

import config as _config_module

# Lazy import — modülleri sadece kullanıldığında yükle
def _mod():
    cfg = _config_module.current()
    ex = getattr(cfg, "exchange", "binance")
    if ex == "bybit":
        import bybit
        return bybit
    if ex == "okx":
        import okx
        return okx
    import live
    return live


# ---------- Yeniden ihraç (re-export) ----------
# app.py bunları doğrudan import edebilir: from exchange import place_market_buy, LiveError

class LiveError(Exception):
    """Yönlendirici LiveError — hangi borsa olursa olsun yakalanır."""


async def validate_keys(key: str, secret: str, extra: str = "") -> dict:
    m = _mod()
    return await m.validate_keys(key, secret, extra) if extra else await m.validate_keys(key, secret)


async def check_trading_permission(key: str, secret: str, extra: str = "") -> bool:
    m = _mod()
    try:
        return await m.check_trading_permission(key, secret, extra)
    except Exception:
        return await m.check_trading_permission(key, secret)


async def get_usdt_balance(key: str, secret: str, extra: str = "") -> float:
    m = _mod()
    try:
        return await m.get_usdt_balance(key, secret, extra)
    except TypeError:
        return await m.get_usdt_balance(key, secret)


async def fetch_balances(key: str, secret: str, extra: str = "") -> list[dict]:
    m = _mod()
    try:
        return await m.fetch_balances(key, secret, extra)
    except TypeError:
        return await m.fetch_balances(key, secret)


async def place_market_buy(key: str, secret: str, symbol: str,
                           usdt_amount: float, extra: str = "") -> tuple[float, float, float]:
    m = _mod()
    try:
        return await m.place_market_buy(key, secret, symbol, usdt_amount, extra)
    except TypeError:
        return await m.place_market_buy(key, secret, symbol, usdt_amount)


async def place_market_sell(key: str, secret: str, symbol: str,
                            qty: float, extra: str = "") -> tuple[float, float, float]:
    m = _mod()
    try:
        return await m.place_market_sell(key, secret, symbol, qty, extra)
    except TypeError:
        return await m.place_market_sell(key, secret, symbol, qty)


async def place_oco_sell(key: str, secret: str, symbol: str,
                         qty: float, take_profit_price: float,
                         stop_price: float, extra: str = "") -> dict:
    m = _mod()
    try:
        return await m.place_oco_sell(key, secret, symbol, qty, take_profit_price, stop_price, extra)
    except TypeError:
        return await m.place_oco_sell(key, secret, symbol, qty, take_profit_price, stop_price)


async def cancel_open_orders(key: str, secret: str, symbol: str,
                             extra: str = "") -> list[dict]:
    m = _mod()
    try:
        return await m.cancel_open_orders(key, secret, symbol, extra)
    except TypeError:
        return await m.cancel_open_orders(key, secret, symbol)


async def get_open_orders(key: str, secret: str, symbol: str | None = None,
                          extra: str = "") -> list[dict]:
    m = _mod()
    try:
        return await m.get_open_orders(key, secret, symbol, extra)
    except TypeError:
        return await m.get_open_orders(key, secret, symbol)


def requirements(lang: str = "tr") -> str:
    m = _mod()
    return m.REQUIREMENTS_TR if lang == "tr" else m.REQUIREMENTS_EN
