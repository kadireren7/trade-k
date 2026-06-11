"""Gerçek Binance hesabı bağlantısı — API anahtarı doğrulama ve bakiye okuma.

Sadece OKUMA yapılır (GET /api/v3/account). Emir gönderme bilerek yok:
gerçek emirler, paper'da kanıtlanmış performanstan sonraki adım.

Anahtar oluştururken: Binance → API Management → "Enable Reading" yeterli.
"Enable Withdrawals" iznini ASLA verme; IP kısıtlaması eklemen önerilir.
"""
from __future__ import annotations

import hashlib
import hmac
import time
import urllib.parse

import httpx

API = "https://api.binance.com"


class LiveError(Exception):
    """Kullanıcıya gösterilebilir bağlantı hatası."""


def _sign(secret: str, params: dict) -> str:
    query = urllib.parse.urlencode(params)
    sig = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return f"{query}&signature={sig}"


async def _signed_get(path: str, key: str, secret: str) -> dict:
    params = {"timestamp": int(time.time() * 1000), "recvWindow": 10_000}
    url = f"{API}{path}?{_sign(secret, params)}"
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers={"X-MBX-APIKEY": key})
    if r.status_code == 401:
        raise LiveError("API anahtarı geçersiz (401). Anahtarı kontrol et.")
    if r.status_code != 200:
        try:
            msg = r.json().get("msg", r.text)
        except Exception:
            msg = r.text
        raise LiveError(f"Binance hatası ({r.status_code}): {msg}")
    return r.json()


async def validate_keys(key: str, secret: str) -> dict:
    """Anahtarları imzalı hesap isteğiyle doğrula; hesap bilgisini döndür."""
    if not key or not secret or len(key) < 10 or len(secret) < 10:
        raise LiveError("Anahtar formatı geçersiz görünüyor.")
    try:
        return await _signed_get("/api/v3/account", key, secret)
    except httpx.HTTPError as e:
        raise LiveError(f"Ağ hatası: {e}") from e


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


REQUIREMENTS_TR = """\
[bold]Gerçek para bağlamak için gerekenler:[/]
  1) Binance hesabı (kimlik doğrulaması/KYC tamamlanmış olmalı)
  2) Binance → Profil → [bold]API Management[/] → "Create API" ile anahtar oluştur
  3) İzinler: [green3]Enable Reading[/] yeterli — [red3]Enable Withdrawals'ı ASLA açma[/]
  4) Güvenlik için IP kısıtlaması ekle (önerilir)
  5) Buraya yapıştır:  [bold]/canli bagla API_KEY SECRET[/]
     (komut günlüğe maskelenerek yazılır, anahtar config.json'da yerelde saklanır)"""

REQUIREMENTS_EN = """\
[bold]To connect real money you need:[/]
  1) A Binance account (KYC verified)
  2) Binance → Profile → [bold]API Management[/] → "Create API"
  3) Permissions: [green3]Enable Reading[/] is enough — [red3]NEVER enable Withdrawals[/]
  4) Add an IP restriction for safety (recommended)
  5) Paste here:  [bold]/canli bagla API_KEY SECRET[/]
     (the command is masked in the log; keys are stored locally in config.json)"""
