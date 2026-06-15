"""Bildirim katmanı — Telegram Bot API (httpx, ayrı paket gerekmez).

Kurulum:
  1) Telegram'da @BotFather'a yaz → /newbot → token al
  2) Botunu başlat (bir mesaj gönder)
  3) https://api.telegram.org/bot<TOKEN>/getUpdates → chat_id al
  4) Uygulamada: /bildirim bagla TOKEN CHAT_ID

Desteklenen olaylar:
  - Alım / satım gerçekleştiğinde
  - Stop loss / take profit tetiklendiğinde
  - Otonom mod kararları (AL / ZARARI_KES)
  - Günlük özet (gün sonu)
"""
from __future__ import annotations

import asyncio
import logging
from enum import Enum

import httpx

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class NotifyEvent(str, Enum):
    BUY = "buy"
    SELL = "sell"
    STOP_HIT = "stop_hit"
    TARGET_HIT = "target_hit"
    AUTO_DECISION = "auto_decision"
    DAILY_SUMMARY = "daily_summary"
    ERROR = "error"


class Notifier:
    """Telegram bildirimcisi — token ve chat_id config'den gelir."""

    def __init__(self, token: str = "", chat_id: str = "") -> None:
        self.token = token
        self.chat_id = chat_id
        self._enabled = bool(token and chat_id)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def configure(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id
        self._enabled = bool(token and chat_id)

    async def send(self, text: str, silent: bool = False) -> bool:
        """Telegram mesajı gönder. Başarı durumunu döndür."""
        if not self._enabled:
            return False
        url = f"{TELEGRAM_API}/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_notification": silent,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(url, json=payload)
            return r.status_code == 200
        except Exception as e:
            logger.debug("Telegram gönderme hatası: %s", e)
            return False

    async def validate(self, token: str, chat_id: str) -> tuple[bool, str]:
        """Token ve chat_id'yi doğrula; (başarı, mesaj) döndür."""
        url = f"{TELEGRAM_API}/bot{token}/getMe"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url)
            if r.status_code != 200:
                return False, f"Geçersiz token (HTTP {r.status_code})"
            bot_name = r.json().get("result", {}).get("username", "?")
            # chat_id doğrula: test mesajı gönder
            test_url = f"{TELEGRAM_API}/bot{token}/sendMessage"
            test_r = await client.post(test_url, json={
                "chat_id": chat_id,
                "text": "✅ <b>trade-k</b> bağlantısı doğrulandı!",
                "parse_mode": "HTML",
            })
            if test_r.status_code != 200:
                body = test_r.json()
                return False, f"Chat ID hatası: {body.get('description', 'Bilinmeyen')}"
            return True, f"Bot: @{bot_name}"
        except httpx.ConnectError:
            return False, "Telegram'a bağlanılamadı (internet bağlantısını kontrol et)"
        except Exception as e:
            return False, str(e)

    # ── Olay metodları ──────────────────────────────────────────────────────

    async def notify_buy(self, symbol: str, qty: float, price: float,
                         usdt: float, is_live: bool) -> None:
        mode = "🟢 GERÇEK" if is_live else "📝 Paper"
        text = (
            f"🛒 <b>ALIM</b> [{mode}]\n"
            f"Sembol: <code>{symbol}</code>\n"
            f"Miktar: {qty:.6f}\n"
            f"Fiyat: {price:,.4f} USDT\n"
            f"Toplam: {usdt:,.2f} USDT"
        )
        await self.send(text)

    async def notify_sell(self, symbol: str, qty: float, price: float,
                          usdt: float, pnl_pct: float, is_live: bool) -> None:
        mode = "🔴 GERÇEK" if is_live else "📝 Paper"
        emoji = "✅" if pnl_pct >= 0 else "❌"
        text = (
            f"{emoji} <b>SATIM</b> [{mode}]\n"
            f"Sembol: <code>{symbol}</code>\n"
            f"Fiyat: {price:,.4f} USDT\n"
            f"Toplam: {usdt:,.2f} USDT\n"
            f"K/Z: {pnl_pct:+.2f}%"
        )
        await self.send(text)

    async def notify_stop(self, symbol: str, price: float, pnl_pct: float) -> None:
        text = (
            f"🛑 <b>STOP LOSS</b>\n"
            f"Sembol: <code>{symbol}</code>\n"
            f"Fiyat: {price:,.4f} USDT\n"
            f"Zarar: {pnl_pct:.2f}%"
        )
        await self.send(text)

    async def notify_target(self, symbol: str, price: float, pnl_pct: float) -> None:
        text = (
            f"🎯 <b>HEDEF ULAŞILDI</b>\n"
            f"Sembol: <code>{symbol}</code>\n"
            f"Fiyat: {price:,.4f} USDT\n"
            f"Kâr: +{pnl_pct:.2f}%"
        )
        await self.send(text)

    async def notify_auto_decision(self, symbol: str, decision: str,
                                   reason: str) -> None:
        emoji = {"AL": "🤖🛒", "ZARARI_KES": "🤖🛑", "KAR_AL": "🤖🎯"}.get(decision, "🤖")
        text = (
            f"{emoji} <b>OTONOM: {decision}</b>\n"
            f"Sembol: <code>{symbol}</code>\n"
            f"Gerekçe: {reason}"
        )
        await self.send(text)

    async def notify_daily_summary(self, equity: float, cash: float,
                                   pnl_pct: float, n_positions: int) -> None:
        emoji = "📈" if pnl_pct >= 0 else "📉"
        text = (
            f"{emoji} <b>Günlük Özet — trade-k</b>\n"
            f"Varlık: {equity:,.2f} USDT\n"
            f"Nakit: {cash:,.2f} USDT\n"
            f"Günlük K/Z: {pnl_pct:+.2f}%\n"
            f"Açık Poz: {n_positions}"
        )
        await self.send(text, silent=True)


# Global tekil örnek — app.py buradan kullanır
_notifier = Notifier()


def get() -> Notifier:
    """Global Notifier örneğini döndür."""
    return _notifier


def configure(token: str, chat_id: str) -> None:
    _notifier.configure(token, chat_id)
