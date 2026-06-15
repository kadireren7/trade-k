"""Bybit Spot gerçek hesap entegrasyonu.

KURULUM:
  Bybit → API Management → "Create New Key"
  İzinler: Unified Trading → Read + Spot Orders
  Çekim (Withdraw) iznini ASLA açma.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
import urllib.parse
from typing import Any

import httpx

API = "https://api.bybit.com"
RECV_WINDOW = "10000"


class LiveError(Exception):
    """Kullanıcıya gösterilebilir bağlantı hatası."""


def _sign(secret: str, timestamp: str, key: str, payload: str) -> str:
    sign_str = f"{timestamp}{key}{RECV_WINDOW}{payload}"
    return hmac.new(secret.encode(), sign_str.encode(), hashlib.sha256).hexdigest()


def _headers(key: str, secret: str, timestamp: str, payload: str) -> dict:
    return {
        "X-BAPI-API-KEY": key,
        "X-BAPI-SIGN": _sign(secret, timestamp, key, payload),
        "X-BAPI-TIMESTAMP": timestamp,
        "X-BAPI-RECV-WINDOW": RECV_WINDOW,
        "Content-Type": "application/json",
    }


def _check(data: dict) -> dict:
    code = data.get("retCode", -1)
    if code != 0:
        msg = data.get("retMsg", "Bilinmeyen hata")
        raise LiveError(f"Bybit hata {code}: {msg}")
    return data.get("result", {})


async def _get(path: str, key: str, secret: str, params: dict | None = None) -> Any:
    ts = str(int(time.time() * 1000))
    query = urllib.parse.urlencode(params or {})
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(
            f"{API}{path}",
            params=params,
            headers=_headers(key, secret, ts, query),
        )
    try:
        return _check(r.json())
    except LiveError:
        raise
    except Exception as e:
        raise LiveError(f"Bybit ağ hatası: {e}") from e


async def _post(path: str, key: str, secret: str, body: dict) -> Any:
    ts = str(int(time.time() * 1000))
    body_str = json.dumps(body)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{API}{path}",
            content=body_str,
            headers=_headers(key, secret, ts, body_str),
        )
    try:
        return _check(r.json())
    except LiveError:
        raise
    except Exception as e:
        raise LiveError(f"Bybit ağ hatası: {e}") from e


async def validate_keys(key: str, secret: str, _extra: str = "") -> dict:
    """API anahtarlarını doğrula; izin bilgisini döndür."""
    if not key or not secret or len(key) < 10:
        raise LiveError("Anahtar formatı geçersiz.")
    try:
        return await _get("/v5/user/query-api", key, secret)
    except httpx.HTTPError as e:
        raise LiveError(f"Bybit ağ hatası: {e}") from e


async def check_trading_permission(key: str, secret: str, _extra: str = "") -> bool:
    """Spot işlem iznini kontrol et."""
    info = await validate_keys(key, secret)
    perms = info.get("permissions", {})
    spot_perms = perms.get("spot", [])
    # "SpotTrade" veya "Order" içeriyorsa işlem izni var
    return bool(spot_perms)


async def fetch_balances(key: str, secret: str, _extra: str = "") -> list[dict]:
    """Unified hesap spot bakiyeleri."""
    try:
        result = await _get("/v5/account/wallet-balance", key, secret,
                            {"accountType": "UNIFIED"})
        accounts = result.get("list", [])
        if not accounts:
            # Eski hesap tipi
            result = await _get("/v5/account/wallet-balance", key, secret,
                                {"accountType": "SPOT"})
            accounts = result.get("list", [])
    except httpx.HTTPError as e:
        raise LiveError(f"Bybit ağ hatası: {e}") from e

    out = []
    for acct in accounts:
        for coin in acct.get("coin", []):
            free = float(coin.get("availableToWithdraw", 0) or coin.get("walletBalance", 0))
            locked = float(coin.get("locked", 0))
            if free + locked > 0:
                out.append({"asset": coin["coin"], "free": free, "locked": locked})
    out.sort(key=lambda b: -(b["free"] + b["locked"]))
    return out


async def get_usdt_balance(key: str, secret: str, _extra: str = "") -> float:
    balances = await fetch_balances(key, secret)
    for b in balances:
        if b["asset"] == "USDT":
            return b["free"]
    return 0.0


async def _query_order_fill(key: str, secret: str, symbol: str, order_id: str
                            ) -> tuple[float, float, float]:
    """Emir dolum bilgisini gerçek zamanlı sorgula (market order için)."""
    for _ in range(5):
        await asyncio.sleep(0.3)
        try:
            result = await _get("/v5/order/realtime", key, secret,
                                {"category": "spot", "symbol": symbol, "orderId": order_id})
            orders = result.get("list", [])
            if orders:
                o = orders[0]
                qty = float(o.get("cumExecQty", 0))
                usdt = float(o.get("cumExecValue", 0))
                price = float(o.get("avgPrice", 0)) or (usdt / qty if qty > 0 else 0)
                if qty > 0:
                    return price, qty, usdt
        except Exception:
            pass
    return 0.0, 0.0, 0.0


async def place_market_buy(
    key: str, secret: str, symbol: str, usdt_amount: float, _extra: str = ""
) -> tuple[float, float, float]:
    """Bybit MARKET BUY (quoteCoin = USDT miktar)."""
    body = {
        "category": "spot",
        "symbol": symbol,
        "side": "Buy",
        "orderType": "Market",
        "qty": str(round(usdt_amount, 2)),
        "marketUnit": "quoteCoin",
    }
    result = await _post("/v5/order/create", key, secret, body)
    order_id = result.get("orderId", "")
    return await _query_order_fill(key, secret, symbol, order_id)


async def place_market_sell(
    key: str, secret: str, symbol: str, qty: float, _extra: str = ""
) -> tuple[float, float, float]:
    """Bybit MARKET SELL."""
    body = {
        "category": "spot",
        "symbol": symbol,
        "side": "Sell",
        "orderType": "Market",
        "qty": str(qty),
    }
    result = await _post("/v5/order/create", key, secret, body)
    order_id = result.get("orderId", "")
    return await _query_order_fill(key, secret, symbol, order_id)


async def place_oco_sell(
    key: str, secret: str, symbol: str, qty: float,
    take_profit_price: float, stop_price: float, _extra: str = ""
) -> dict:
    """Bybit'te OCO yok — TP + SL ayrı limit/stop-market emirleri olarak gönderilir."""
    tp_body = {
        "category": "spot",
        "symbol": symbol,
        "side": "Sell",
        "orderType": "Limit",
        "qty": str(qty),
        "price": str(round(take_profit_price, 4)),
        "timeInForce": "GTC",
    }
    sl_body = {
        "category": "spot",
        "symbol": symbol,
        "side": "Sell",
        "orderType": "Market",
        "qty": str(qty),
        "triggerPrice": str(round(stop_price, 4)),
        "orderFilter": "tpslOrder",
    }
    tp_result = await _post("/v5/order/create", key, secret, tp_body)
    try:
        sl_result = await _post("/v5/order/create", key, secret, sl_body)
    except Exception:
        sl_result = {}
    return {"tp_order": tp_result, "sl_order": sl_result}


async def cancel_open_orders(key: str, secret: str, symbol: str, _extra: str = "") -> list[dict]:
    """Sembol için açık emirleri iptal et."""
    try:
        result = await _post("/v5/order/cancel-all", key, secret,
                             {"category": "spot", "symbol": symbol})
        return result.get("list", [])
    except LiveError as e:
        if "110001" in str(e):  # order not found
            return []
        raise
    except Exception:
        return []


async def get_open_orders(key: str, secret: str, symbol: str | None = None,
                          _extra: str = "") -> list[dict]:
    """Açık emirleri listele."""
    params: dict = {"category": "spot"}
    if symbol:
        params["symbol"] = symbol
    result = await _get("/v5/order/realtime", key, secret, params)
    return result.get("list", [])


REQUIREMENTS_TR = """\
[bold]Bybit'e bağlanmak için:[/]
  1) Bybit hesabı (KYC tamamlanmış)
  2) Bybit → Hesap → [bold]API Management[/] → "Create New Key"
  3) İzinler: [green3]Unified Trading: Read + Orders[/]
              [red3]Withdraw iznini ASLA açma[/]
  4) IP kısıtlaması ekle (güvenlik için)
  5) [bold]/canli bagla API_KEY SECRET[/] ile bağlan
     Menü 4 → Borsa seç: Bybit"""

REQUIREMENTS_EN = """\
[bold]To connect Bybit:[/]
  1) Bybit account (KYC verified)
  2) Bybit → Account → [bold]API Management[/] → "Create New Key"
  3) Permissions: [green3]Unified Trading: Read + Orders[/]
                  [red3]NEVER enable Withdrawals[/]
  4) Add IP restriction (recommended)
  5) Connect with [bold]/live bagla API_KEY SECRET[/]
     Menu 4 → Select Exchange: Bybit"""
