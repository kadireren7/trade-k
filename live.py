"""Binance gerçek hesap entegrasyonu — doğrulama, bakiye ve emir gönderme.

KURULUM:
  Emir göndermek için Binance API Management'ta "Enable Spot & Margin Trading" iznini aç.
  Stop emirleri için OCO (One-Cancels-the-Other) kullanılır.
  Çekim (Withdraw) iznini ASLA açma; IP kısıtlaması ekle.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import time
import urllib.parse
from typing import Any

import httpx

API = "https://api.binance.com"

# Sembol bilgisi bellekte önbellek
_SYMBOL_INFO_CACHE: dict[str, dict] = {}


class LiveError(Exception):
    """Kullanıcıya gösterilebilir bağlantı hatası."""


def _sign(secret: str, params: dict) -> str:
    query = urllib.parse.urlencode(params)
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return f"{query}&signature={sig}"


def _raise_for_status(r: httpx.Response) -> None:
    """401/403/4xx için detaylı LiveError fırlatır."""
    if r.status_code == 200:
        return
    try:
        body = r.json()
        code = body.get("code", "")
        msg = body.get("msg", r.text)
    except Exception:
        code = ""
        msg = r.text
    if r.status_code == 401:
        raise LiveError("API anahtarı geçersiz (401). Anahtarı kontrol et.")
    if r.status_code == 403:
        raise LiveError(
            "İşlem izni yok (403) — Binance API Management'ta "
            "'Enable Spot & Margin Trading' iznini aç."
        )
    raise LiveError(f"Binance {r.status_code} (kod {code}): {msg}")


async def _signed_get(path: str, key: str, secret: str, extra: dict | None = None) -> Any:
    params: dict = {"timestamp": int(time.time() * 1000), "recvWindow": 10_000}
    if extra:
        params.update(extra)
    url = f"{API}{path}?{_sign(secret, params)}"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers={"X-MBX-APIKEY": key})
    _raise_for_status(r)
    return r.json()


async def _signed_post(path: str, key: str, secret: str, params: dict) -> Any:
    """POST emirler için — Content-Type: application/x-www-form-urlencoded."""
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 10_000
    body = _sign(secret, params)
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            f"{API}{path}",
            content=body,
            headers={
                "X-MBX-APIKEY": key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
    _raise_for_status(r)
    return r.json()


async def _signed_delete(path: str, key: str, secret: str, params: dict) -> Any:
    """DELETE emirler için."""
    params = dict(params)
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 10_000
    url = f"{API}{path}?{_sign(secret, params)}"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.delete(url, headers={"X-MBX-APIKEY": key})
    _raise_for_status(r)
    return r.json()


async def validate_keys(key: str, secret: str) -> dict:
    """Anahtarları imzalı hesap isteğiyle doğrula; hesap bilgisini döndür."""
    if not key or not secret or len(key) < 10 or len(secret) < 10:
        raise LiveError("Anahtar formatı geçersiz görünüyor.")
    try:
        return await _signed_get("/api/v3/account", key, secret)
    except httpx.HTTPError as e:
        raise LiveError(f"Ağ hatası: {e}") from e


async def check_trading_permission(key: str, secret: str) -> bool:
    """Hesabın işlem iznini kontrol et; canTrade değerini döndür."""
    acct = await validate_keys(key, secret)
    return bool(acct.get("canTrade", False))


async def fetch_balances(key: str, secret: str) -> list[dict]:
    """Sıfır olmayan spot bakiyeler: [{asset, free, locked}, ...]"""
    acct = await validate_keys(key, secret)
    out = []
    for b in acct.get("balances", []):
        free, locked = float(b["free"]), float(b["locked"])
        if free + locked > 0:
            out.append({"asset": b["asset"], "free": free, "locked": locked})
    out.sort(key=lambda b: -(b["free"] + b["locked"]))
    return out


async def get_usdt_balance(key: str, secret: str) -> float:
    """Sadece USDT serbest (free) bakiyeyi döndür."""
    balances = await fetch_balances(key, secret)
    for b in balances:
        if b["asset"] == "USDT":
            return b["free"]
    return 0.0


def _get_filter(sym_info: dict, filter_type: str) -> dict:
    """exchangeInfo sembol verisinden belirtilen filtre tipini döndür."""
    for f in sym_info.get("filters", []):
        if f.get("filterType") == filter_type:
            return f
    return {}


async def get_symbol_info(symbol: str) -> dict:
    """GET /api/v3/exchangeInfo?symbol=X — basit in-memory önbellekle."""
    if symbol in _SYMBOL_INFO_CACHE:
        return _SYMBOL_INFO_CACHE[symbol]
    url = f"{API}/api/v3/exchangeInfo"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params={"symbol": symbol})
    if r.status_code != 200:
        try:
            msg = r.json().get("msg", r.text)
        except Exception:
            msg = r.text
        raise LiveError(f"Sembol bilgisi alınamadı ({symbol}): {msg}")
    data = r.json()
    symbols = data.get("symbols", [])
    if not symbols:
        raise LiveError(f"Sembol bulunamadı: {symbol}")
    info = symbols[0]
    _SYMBOL_INFO_CACHE[symbol] = info
    return info


def round_qty(qty: float, sym_info: dict) -> float:
    """LOT_SIZE filtresine göre miktarı aşağı yuvarla."""
    lot = _get_filter(sym_info, "LOT_SIZE")
    step_str = lot.get("stepSize", "0.00000000")
    step = float(step_str)
    if step == 0:
        return qty
    result = math.floor(qty / step) * step
    # Ondalık hassasiyeti step'ten belirle
    if "." in step_str:
        decimals = max(0, len(step_str.rstrip("0").split(".")[1]))
    else:
        decimals = 0
    return round(result, decimals)


def round_price(price: float, sym_info: dict) -> float:
    """PRICE_FILTER tickSize'a göre fiyatı yuvarla."""
    pf = _get_filter(sym_info, "PRICE_FILTER")
    tick_str = pf.get("tickSize", "0.00000000")
    tick = float(tick_str)
    if tick == 0:
        return price
    result = math.floor(price / tick) * tick
    if "." in tick_str:
        decimals = max(0, len(tick_str.rstrip("0").split(".")[1]))
    else:
        decimals = 0
    return round(result, decimals)


def check_min_notional(qty: float, price: float, sym_info: dict) -> tuple[bool, str]:
    """MIN_NOTIONAL veya NOTIONAL filtresi kontrolü — (geçerli_mi, mesaj) döndür."""
    notional = qty * price
    # Önce NOTIONAL (yeni), sonra MIN_NOTIONAL (eski) kontrol et
    nf = _get_filter(sym_info, "NOTIONAL") or _get_filter(sym_info, "MIN_NOTIONAL")
    min_notional = float(nf.get("minNotional", nf.get("minNotional", 0)))
    if notional < min_notional:
        return False, (
            f"Minimum işlem tutarı karşılanmıyor: "
            f"{notional:.2f} USDT < {min_notional:.2f} USDT"
        )
    return True, ""


def parse_fill(order_result: dict) -> tuple[float, float, float]:
    """Order response'tan (fill_price, fill_qty, fill_usdt) hesapla.

    fill_price = cummulativeQuoteQty / executedQty
    fill_qty   = float(executedQty)
    fill_usdt  = float(cummulativeQuoteQty)
    """
    fill_qty = float(order_result.get("executedQty", 0))
    fill_usdt = float(order_result.get("cummulativeQuoteQty", 0))
    if fill_qty > 0:
        fill_price = fill_usdt / fill_qty
    else:
        fill_price = 0.0
    return fill_price, fill_qty, fill_usdt


async def place_market_buy(
    key: str, secret: str, symbol: str, usdt_amount: float
) -> tuple[float, float, float]:
    """MARKET BUY — quoteOrderQty ile. (fill_price, fill_qty, fill_usdt) döndür."""
    params = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quoteOrderQty": f"{usdt_amount:.2f}",
    }
    try:
        result = await _signed_post("/api/v3/order", key, secret, params)
    except httpx.HTTPError as e:
        raise LiveError(f"Ağ hatası (market buy): {e}") from e
    return parse_fill(result)


async def place_market_sell(
    key: str, secret: str, symbol: str, qty: float
) -> tuple[float, float, float]:
    """MARKET SELL — round_qty ile miktar yuvarlanır. (fill_price, fill_qty, fill_usdt) döndür."""
    sym_info = await get_symbol_info(symbol)
    qty = round_qty(qty, sym_info)
    params = {
        "symbol": symbol,
        "side": "SELL",
        "type": "MARKET",
        "quantity": str(qty),
    }
    try:
        result = await _signed_post("/api/v3/order", key, secret, params)
    except httpx.HTTPError as e:
        raise LiveError(f"Ağ hatası (market sell): {e}") from e
    return parse_fill(result)


async def place_oco_sell(
    key: str,
    secret: str,
    symbol: str,
    qty: float,
    take_profit_price: float,
    stop_price: float,
) -> dict:
    """OCO SELL — stopLimitPrice = stop_price * 0.999, GTC."""
    sym_info = await get_symbol_info(symbol)
    qty = round_qty(qty, sym_info)
    tp_price = round_price(take_profit_price, sym_info)
    sl_price = round_price(stop_price, sym_info)
    sl_limit_price = round_price(stop_price * 0.999, sym_info)
    params = {
        "symbol": symbol,
        "side": "SELL",
        "quantity": str(qty),
        "price": str(tp_price),
        "stopPrice": str(sl_price),
        "stopLimitPrice": str(sl_limit_price),
        "stopLimitTimeInForce": "GTC",
    }
    try:
        return await _signed_post("/api/v3/order/oco", key, secret, params)
    except httpx.HTTPError as e:
        raise LiveError(f"Ağ hatası (OCO sell): {e}") from e


async def cancel_open_orders(key: str, secret: str, symbol: str) -> list[dict]:
    """DELETE /api/v3/openOrders — -2011 (açık emir yok) hatasını sessizce geç."""
    try:
        result = await _signed_delete(
            "/api/v3/openOrders", key, secret, {"symbol": symbol}
        )
    except LiveError as e:
        # -2011: Unknown order sent — açık emir yoksa sessizce boş liste dön
        if "-2011" in str(e):
            return []
        raise
    except httpx.HTTPError as e:
        raise LiveError(f"Ağ hatası (cancel orders): {e}") from e
    if isinstance(result, list):
        return result
    return [result]


async def get_open_orders(key: str, secret: str, symbol: str | None = None) -> list[dict]:
    """GET /api/v3/openOrders — sembol belirtilmezse tüm açık emirler."""
    extra = {}
    if symbol:
        extra["symbol"] = symbol
    try:
        result = await _signed_get("/api/v3/openOrders", key, secret, extra=extra)
    except httpx.HTTPError as e:
        raise LiveError(f"Ağ hatası (open orders): {e}") from e
    if isinstance(result, list):
        return result
    return [result]


REQUIREMENTS_TR = """\
[bold]Gerçek para bağlamak için gerekenler:[/]
  1) Binance hesabı (kimlik doğrulaması/KYC tamamlanmış olmalı)
  2) Binance → Profil → [bold]API Management[/] → "Create API" ile anahtar oluştur
  3) İzinler: [green3]Enable Reading[/] zorunlu
              [green3]Enable Spot & Margin Trading[/] — emir göndermek için gerekli
              [red3]Enable Withdrawals'ı ASLA açma[/]
  4) Güvenlik için IP kısıtlaması ekle (önerilir)
  5) Buraya yapıştır:  [bold]/canli bagla API_KEY SECRET[/]
     (komut günlüğe maskelenerek yazılır, anahtar config.json'da yerelde saklanır)"""

REQUIREMENTS_EN = """\
[bold]To connect real money you need:[/]
  1) A Binance account (KYC verified)
  2) Binance → Profile → [bold]API Management[/] → "Create API"
  3) Permissions: [green3]Enable Reading[/] required
                  [green3]Enable Spot & Margin Trading[/] — required for placing orders
                  [red3]NEVER enable Withdrawals[/]
  4) Add an IP restriction for safety (recommended)
  5) Paste here:  [bold]/canli bagla API_KEY SECRET[/]
     (the command is masked in the log; keys are stored locally in config.json)"""
