"""OKX Spot gerçek hesap entegrasyonu.

KURULUM:
  OKX → API → Create API Key
  İzinler: Trade (Read + Spot Orders)
  Passphrase: API oluştururken belirlediğin ek şifre (zorunlu)
  Withdraw iznini ASLA açma.

NOT: OKX 3 bilgi ister: API Key + Secret + Passphrase
     Bağlantı komutu: /canli bagla OKX_KEY OKX_SECRET OKX_PASSPHRASE
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import httpx

API = "https://www.okx.com"


class LiveError(Exception):
    """Kullanıcıya gösterilebilir bağlantı hatası."""


def _timestamp() -> str:
    """ISO 8601 UTC timestamp — OKX formatı."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
           str(int(time.time() * 1000) % 1000).zfill(3) + "Z"


def _sign(secret: str, timestamp: str, method: str, path: str, body: str = "") -> str:
    prehash = f"{timestamp}{method.upper()}{path}{body}"
    sig = hmac.new(secret.encode(), prehash.encode(), hashlib.sha256).digest()
    return base64.b64encode(sig).decode()


def _headers(key: str, secret: str, passphrase: str, method: str,
             path: str, body: str = "") -> dict:
    ts = _timestamp()
    return {
        "OK-ACCESS-KEY": key,
        "OK-ACCESS-SIGN": _sign(secret, ts, method, path, body),
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": passphrase,
        "Content-Type": "application/json",
    }


def _check(data: dict) -> Any:
    code = data.get("code", "-1")
    if code != "0":
        msg = data.get("msg", "Bilinmeyen hata")
        raise LiveError(f"OKX hata {code}: {msg}")
    return data.get("data", [])


def _symbol_to_okx(symbol: str) -> str:
    """BTCUSDT → BTC-USDT."""
    if "-" in symbol:
        return symbol
    if symbol.endswith("USDT"):
        return symbol[:-4] + "-USDT"
    if symbol.endswith("BTC"):
        return symbol[:-3] + "-BTC"
    return symbol


async def _get(path: str, key: str, secret: str, passphrase: str,
               params: dict | None = None) -> Any:
    query = ("?" + urllib.parse.urlencode(params)) if params else ""
    hdrs = _headers(key, secret, passphrase, "GET", path + query)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{API}{path}", params=params, headers=hdrs)
    try:
        return _check(r.json())
    except LiveError:
        raise
    except Exception as e:
        raise LiveError(f"OKX ağ hatası: {e}") from e


async def _post(path: str, key: str, secret: str, passphrase: str,
                body: dict) -> Any:
    body_str = json.dumps(body)
    hdrs = _headers(key, secret, passphrase, "POST", path, body_str)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(f"{API}{path}", content=body_str, headers=hdrs)
    try:
        return _check(r.json())
    except LiveError:
        raise
    except Exception as e:
        raise LiveError(f"OKX ağ hatası: {e}") from e


async def validate_keys(key: str, secret: str, passphrase: str = "") -> dict:
    """Anahtarları ve passphrase'i doğrula."""
    if not key or not secret or not passphrase:
        raise LiveError("OKX için Key, Secret VE Passphrase gereklidir.")
    try:
        data = await _get("/api/v5/account/config", key, secret, passphrase)
        return data[0] if data else {}
    except httpx.HTTPError as e:
        raise LiveError(f"OKX ağ hatası: {e}") from e


async def check_trading_permission(key: str, secret: str, passphrase: str = "") -> bool:
    """Spot trade iznini kontrol et."""
    info = await validate_keys(key, secret, passphrase)
    # perm: "read_only" | "trade" | "withdraw"
    perm = info.get("perm", "")
    return "trade" in perm or perm == ""  # boşsa tüm izinler var


async def fetch_balances(key: str, secret: str, passphrase: str = "") -> list[dict]:
    """Sıfır olmayan spot bakiyeler."""
    try:
        data = await _get("/api/v5/account/balance", key, secret, passphrase)
    except httpx.HTTPError as e:
        raise LiveError(f"OKX ağ hatası: {e}") from e
    out = []
    for acct in data:
        for detail in acct.get("details", []):
            free = float(detail.get("availBal", 0))
            frozen = float(detail.get("frozenBal", 0))
            if free + frozen > 0:
                out.append({"asset": detail["ccy"], "free": free, "locked": frozen})
    out.sort(key=lambda b: -(b["free"] + b["locked"]))
    return out


async def get_usdt_balance(key: str, secret: str, passphrase: str = "") -> float:
    balances = await fetch_balances(key, secret, passphrase)
    for b in balances:
        if b["asset"] == "USDT":
            return b["free"]
    return 0.0


async def _query_order_fill(key: str, secret: str, passphrase: str,
                             inst_id: str, order_id: str) -> tuple[float, float, float]:
    """Emir dolum bilgisini sorgula."""
    for _ in range(5):
        await asyncio.sleep(0.3)
        try:
            data = await _get("/api/v5/trade/order", key, secret, passphrase,
                              {"instId": inst_id, "ordId": order_id})
            if data:
                o = data[0]
                qty = float(o.get("accFillSz", 0))
                px = float(o.get("avgPx", 0))
                usdt = qty * px
                if qty > 0 and px > 0:
                    return px, qty, usdt
        except Exception:
            pass
    return 0.0, 0.0, 0.0


async def place_market_buy(
    key: str, secret: str, symbol: str, usdt_amount: float, passphrase: str = ""
) -> tuple[float, float, float]:
    """OKX MARKET BUY (tgtCcy = USDT miktar)."""
    inst_id = _symbol_to_okx(symbol)
    body = {
        "instId": inst_id,
        "tdMode": "cash",
        "side": "buy",
        "ordType": "market",
        "sz": str(round(usdt_amount, 2)),
        "tgtCcy": "quote_ccy",  # sz USDT cinsinden
    }
    data = await _post("/api/v5/trade/order", key, secret, passphrase, body)
    if not data:
        raise LiveError("OKX order response boş")
    order_id = data[0].get("ordId", "")
    return await _query_order_fill(key, secret, passphrase, inst_id, order_id)


async def place_market_sell(
    key: str, secret: str, symbol: str, qty: float, passphrase: str = ""
) -> tuple[float, float, float]:
    """OKX MARKET SELL."""
    inst_id = _symbol_to_okx(symbol)
    body = {
        "instId": inst_id,
        "tdMode": "cash",
        "side": "sell",
        "ordType": "market",
        "sz": str(qty),
    }
    data = await _post("/api/v5/trade/order", key, secret, passphrase, body)
    if not data:
        raise LiveError("OKX order response boş")
    order_id = data[0].get("ordId", "")
    return await _query_order_fill(key, secret, passphrase, inst_id, order_id)


async def place_oco_sell(
    key: str, secret: str, symbol: str, qty: float,
    take_profit_price: float, stop_price: float, passphrase: str = ""
) -> dict:
    """OKX TP + SL (algo order olarak gönderilir)."""
    inst_id = _symbol_to_okx(symbol)
    body = {
        "instId": inst_id,
        "tdMode": "cash",
        "side": "sell",
        "ordType": "oco",
        "sz": str(qty),
        "tpTriggerPx": str(round(take_profit_price, 4)),
        "tpOrdPx": "-1",    # market price
        "slTriggerPx": str(round(stop_price, 4)),
        "slOrdPx": "-1",    # market price
        "tpTriggerPxType": "last",
        "slTriggerPxType": "last",
    }
    try:
        data = await _post("/api/v5/trade/order-algo", key, secret, passphrase, body)
        return {"algo_order": data}
    except LiveError:
        # OCO başarısız olursa ayrı TP + SL gönder
        tp = {
            "instId": inst_id, "tdMode": "cash", "side": "sell",
            "ordType": "limit", "sz": str(qty),
            "px": str(round(take_profit_price, 4)), "tgtCcy": "base_ccy",
        }
        sl = {
            "instId": inst_id, "tdMode": "cash", "side": "sell",
            "ordType": "optimal_limit_ioc", "sz": str(qty),
            "slTriggerPx": str(round(stop_price, 4)),
            "slOrdPx": "-1", "tgtCcy": "base_ccy",
        }
        tp_r = await _post("/api/v5/trade/order", key, secret, passphrase, tp)
        try:
            sl_r = await _post("/api/v5/trade/order-algo", key, secret, passphrase, sl)
        except Exception:
            sl_r = {}
        return {"tp": tp_r, "sl": sl_r}


async def cancel_open_orders(key: str, secret: str, symbol: str,
                              passphrase: str = "") -> list[dict]:
    """Açık emirleri iptal et."""
    inst_id = _symbol_to_okx(symbol)
    try:
        orders = await _get("/api/v5/trade/orders-pending", key, secret, passphrase,
                            {"instId": inst_id})
    except Exception:
        return []
    if not orders:
        return []
    cancel_list = [{"instId": inst_id, "ordId": o["ordId"]} for o in orders]
    try:
        result = await _post("/api/v5/trade/cancel-batch-orders", key, secret,
                             passphrase, cancel_list)
        return result if isinstance(result, list) else []
    except Exception:
        return []


async def get_open_orders(key: str, secret: str, symbol: str | None = None,
                          passphrase: str = "") -> list[dict]:
    """Açık emirleri listele."""
    params: dict = {"instType": "SPOT"}
    if symbol:
        params["instId"] = _symbol_to_okx(symbol)
    return await _get("/api/v5/trade/orders-pending", key, secret, passphrase, params)


REQUIREMENTS_TR = """\
[bold]OKX'e bağlanmak için:[/]
  1) OKX hesabı (KYC tamamlanmış)
  2) OKX → Profil → [bold]API Yönetimi[/] → "API Oluştur"
  3) İzinler: [green3]Okuma + İşlem[/]
              [red3]Çekim iznini ASLA açma[/]
  4) Passphrase belirle (API oluştururken zorunlu)
  5) Bağlan: [bold]/canli bagla OKX_KEY OKX_SECRET OKX_PASSPHRASE[/]
     (3 parametre gereklidir — passphrase dahil)"""

REQUIREMENTS_EN = """\
[bold]To connect OKX:[/]
  1) OKX account (KYC verified)
  2) OKX → Profile → [bold]API Management[/] → "Create API"
  3) Permissions: [green3]Read + Trade[/]
                  [red3]NEVER enable Withdrawals[/]
  4) Set a passphrase (required during API creation)
  5) Connect: [bold]/live bagla OKX_KEY OKX_SECRET OKX_PASSPHRASE[/]
     (3 parameters required — including passphrase)"""
