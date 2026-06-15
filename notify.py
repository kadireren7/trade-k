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


# ── Telegram Komut Botu ─────────────────────────────────────────────────────

class TelegramCommandBot:
    """Telegram'dan çift yönlü kontrol — sadece yetkili chat_id kabul edilir.

    Desteklenen komutlar:
      /yardim  /bakiye  /durum  /otonom ac|kapat|durum  /mod  /sat
    """

    def __init__(self, notifier: Notifier) -> None:
        self._n = notifier
        self._offset = 0
        self._task: "asyncio.Task | None" = None
        self._portfolio = None
        self._engine = None
        self._cfg = None
        self._feed = None

    # ── Yaşam döngüsü ───────────────────────────────────────────────────────

    def start(self, portfolio, engine, cfg, feed=None) -> None:
        if not self._n.enabled:
            return
        self._portfolio = portfolio
        self._engine = engine
        self._cfg = cfg
        self._feed = feed
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._poll_loop())

    def update_engine(self, engine) -> None:
        self._engine = engine

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None

    # ── Polling döngüsü ─────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(5)  # hata sonrası kısa bekleme
                continue
            await asyncio.sleep(0)  # long-poll zaten bekledi, hemen devam et

    async def _poll_once(self) -> None:
        url = f"{TELEGRAM_API}/bot{self._n.token}/getUpdates"
        params = {"offset": self._offset, "timeout": 20, "limit": 10}
        # connect=5s, read=25s (long-poll için)
        _timeout = httpx.Timeout(connect=5.0, read=25.0, write=5.0, pool=5.0)
        try:
            async with httpx.AsyncClient(timeout=_timeout) as client:
                r = await client.get(url, params=params)
        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError,
                httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout,
                httpx.WriteError, OSError):
            return
        except Exception:
            return
        if r.status_code != 200:
            return
        for update in r.json().get("result", []):
            self._offset = update["update_id"] + 1
            await self._handle_update(update)

    async def _handle_update(self, update: dict) -> None:
        msg = update.get("message") or update.get("edited_message") or {}
        if not msg:
            return
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id != self._n.chat_id:
            return  # yetkisiz kişi
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return
        parts = text.split()
        cmd = parts[0].lstrip("/").lower().split("@")[0]
        args = parts[1:]
        try:
            reply = await self._dispatch(cmd, args)
        except Exception as e:
            reply = f"❌ Hata: {e}"
        if reply:
            await self._n.send(reply)

    # ── Komut yönlendirici ──────────────────────────────────────────────────

    async def _dispatch(self, cmd: str, args: list) -> str:
        if cmd in ("yardim", "start", "help"):
            return self._yardim()
        if cmd == "bakiye":
            return await self._bakiye()
        if cmd == "durum":
            return await self._durum()
        if cmd == "otonom":
            return await self._otonom(args)
        if cmd == "sat":
            return await self._sat(args)
        if cmd == "mod":
            return self._profil(args)
        return f"❓ Bilinmeyen komut: /{cmd}\n/yardim yaz"

    # ── Komut handler'ları ──────────────────────────────────────────────────

    def _yardim(self) -> str:
        return (
            "🤖 <b>trade-k Komutları</b>\n\n"
            "/durum — Açık pozisyonlar ve K/Z\n"
            "/bakiye — Nakit ve toplam varlık\n"
            "\n<b>Otonom mod:</b>\n"
            "/otonom ac long\n"
            "/otonom ac short\n"
            "/otonom ac longshort\n"
            "/otonom ac scalp\n"
            "/otonom ac kaldirac\n"
            "/otonom ac tam\n"
            "/otonom kapat\n"
            "/otonom durum\n"
            "\n<b>Diğer:</b>\n"
            "/mod guvenli — Risk profili değiştir\n"
            "/mod dengeli\n"
            "/mod agresif\n"
            "/sat BTC — Pozisyon kapat\n"
            "/yardim — Bu liste"
        )

    async def _bakiye(self) -> str:
        if not self._portfolio:
            return "❌ Portföy bağlı değil"
        p = self._portfolio
        prices: dict = {}
        for sym in p.positions:
            try:
                import market as _mkt
                prices[sym] = await _mkt.quote(sym)
            except Exception:
                prices[sym] = p.positions[sym].entry
        equity = p.equity(prices) if prices else p.cash
        mode_str = "🟢 GERÇEK" if (
            self._cfg and getattr(self._cfg, "trading_mode", "paper") == "live"
        ) else "📝 Paper"
        return (
            f"💰 <b>Bakiye [{mode_str}]</b>\n\n"
            f"Nakit: <b>{p.cash:,.2f} USDT</b>\n"
            f"Pozisyon değeri: {equity - p.cash:,.2f} USDT\n"
            f"Toplam varlık: <b>{equity:,.2f} USDT</b>\n"
            f"Açık pozisyon: {len(p.positions)}"
        )

    async def _durum(self) -> str:
        if not self._portfolio:
            return "❌ Portföy bağlı değil"
        p = self._portfolio
        if not p.positions:
            return "📭 Açık pozisyon yok"
        lines = [f"📊 <b>Pozisyonlar ({len(p.positions)})</b>\n"]
        for sym, pos in p.positions.items():
            try:
                import market as _mkt
                cur = await _mkt.quote(sym)
            except Exception:
                cur = pos.entry
            pnl, pct = p.unrealized_pnl(sym, cur)
            emoji = "📈" if pnl >= 0 else "📉"
            sign = "+" if pnl >= 0 else ""
            direction = "LONG" if pos.direction == "long" else "SHORT"
            lev = f" {pos.leverage}x" if pos.is_leveraged else ""
            name = sym.replace("USDT", "")
            block = (
                f"{emoji} <b>{name}/USDT</b> [{direction}{lev}]\n"
                f"  Giriş: {pos.entry:,.4f} → Şimdi: {cur:,.4f}\n"
                f"  K/Z: {sign}{pnl:,.2f} USDT ({sign}{pct:.2f}%)"
            )
            if pos.stop and pos.target:
                block += f"\n  Stop: {pos.stop:,.4f} | Hedef: {pos.target:,.4f}"
            elif pos.stop:
                block += f"\n  Stop: {pos.stop:,.4f}"
            lines.append(block)
        return "\n\n".join(lines)

    async def _otonom(self, args: list) -> str:
        if not args:
            return "Kullanım:\n/otonom ac [long|short|longshort|scalp|kaldirac|tam]\n/otonom kapat\n/otonom durum"
        sub = args[0].lower()
        if sub == "kapat":
            if not self._engine:
                return "❌ Motor bağlı değil"
            await self._engine.stop("Telegram komutu")
            return "⏹ Otonom mod kapatıldı."
        if sub == "durum":
            if not self._engine:
                return "❌ Motor bağlı değil"
            e = self._engine
            status = "🟢 AÇIK" if e.state.enabled else "⚫ KAPALI"
            mod = getattr(self._cfg, "otonom_trade_type", "long") if self._cfg else "?"
            profil = getattr(self._cfg, "autonomous_mode", "dengeli") if self._cfg else "?"
            n_pos = len(self._portfolio.positions) if self._portfolio else "?"
            return (
                f"🤖 <b>Otonom Durum</b>\n\n"
                f"Durum: {status}\n"
                f"Mod: <b>{mod.upper()}</b>\n"
                f"Profil: {profil}\n"
                f"Bugünkü işlem: {e.state.daily_trades}\n"
                f"Açık pozisyon: {n_pos}"
            )
        if sub == "ac":
            if not self._engine or not self._cfg:
                return "❌ Motor bağlı değil"
            _MAP = {
                "long":      ("long",      "sadece_long", False, False),
                "short":     ("short",     "dengeli",     False, False),
                "longshort": ("longshort", "dengeli",     False, False),
                "scalp":     ("scalp",     "dengeli",     True,  False),
                "kaldirac":  ("kaldirac",  "dengeli",     False, True),
                "tam":       ("tam",       "tam",         True,  True),
            }
            trade_arg = args[1].lower() if len(args) > 1 else "long"
            if trade_arg not in _MAP:
                return (
                    f"❌ Geçersiz mod: <b>{trade_arg}</b>\n"
                    "Seçenekler: long, short, longshort, scalp, kaldirac, tam"
                )
            ot, plan, scalp, lev = _MAP[trade_arg]
            self._cfg.otonom_trade_type = ot
            self._cfg.trade_plan = plan
            self._cfg.scalp_enabled = scalp
            self._cfg.leverage_enabled = lev
            self._cfg.save()
            await self._engine.start()
            return f"✅ Otonom mod açıldı: <b>{trade_arg.upper()}</b>"
        return "Kullanım:\n/otonom ac [long|short|longshort|scalp|kaldirac|tam]\n/otonom kapat\n/otonom durum"

    async def _sat(self, args: list) -> str:
        if not self._portfolio:
            return "❌ Portföy bağlı değil"
        p = self._portfolio
        if not args:
            if not p.positions:
                return "📭 Açık pozisyon yok"
            names = ", ".join(s.replace("USDT", "") for s in p.positions)
            return f"Hangi sembol? /sat BTC\nAçık: {names}"
        sym = args[0].upper()
        if not sym.endswith("USDT"):
            sym += "USDT"
        if sym not in p.positions:
            return f"❌ {sym.replace('USDT','')} pozisyonu yok"
        try:
            import market as _mkt
            cur = await _mkt.quote(sym)
        except Exception:
            cur = p.positions[sym].entry
        try:
            p.sell(sym, cur)
            name = sym.replace("USDT", "")
            return f"✅ {name}/USDT pozisyonu kapatıldı (paper fiyat: {cur:,.4f})"
        except Exception as e:
            return f"❌ Satış hatası: {e}"

    def _profil(self, args: list) -> str:
        if not self._cfg:
            return "❌ Config bağlı değil"
        if not args:
            cur = getattr(self._cfg, "autonomous_mode", "dengeli")
            return f"Mevcut profil: <b>{cur}</b>\nDeğiştir: /mod guvenli | /mod dengeli | /mod agresif"
        p = args[0].lower()
        if p not in {"guvenli", "dengeli", "agresif"}:
            return f"❌ Geçersiz profil: {p}\nSeçenekler: guvenli, dengeli, agresif"
        self._cfg.autonomous_mode = p
        self._cfg.save()
        return f"✅ Risk profili değiştirildi: <b>{p.upper()}</b>"


# ── Global tekil örnekler ────────────────────────────────────────────────────

_notifier = Notifier()
_bot = TelegramCommandBot(_notifier)


def get() -> Notifier:
    """Global Notifier örneğini döndür."""
    return _notifier


def get_bot() -> TelegramCommandBot:
    """Global TelegramCommandBot örneğini döndür."""
    return _bot


def configure(token: str, chat_id: str) -> None:
    _notifier.configure(token, chat_id)
