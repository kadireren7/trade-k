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
        test_url = f"{TELEGRAM_API}/bot{token}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.get(url)
                if r.status_code != 200:
                    return False, f"Geçersiz token (HTTP {r.status_code})"
                bot_name = r.json().get("result", {}).get("username", "?")
                # chat_id doğrula — aynı client içinde
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

_BOT_COMMANDS = [
    ("yardim",       "Komut listesi"),
    ("durum",        "Açık pozisyonlar ve K/Z"),
    ("bakiye",       "Nakit ve toplam varlık"),
    ("performans",   "Detaylı performans raporu"),
    ("gecmis",       "Son işlemler özeti"),
    ("otonom",       "Otonom mod: ac/kapat/durum + [long|short|scalp|tam...]"),
    ("durdur",       "Otonom modu durdur"),
    ("acil",         "ACİL: tüm pozisyonları kapat, otonom durdur"),
    ("limit",        "Günlük işlem limiti: /limit 5 veya /limit durum"),
    ("mod",          "Risk profili: guvenli / dengeli / agresif"),
    ("sat",          "Pozisyon kapat: /sat BTC"),
    ("fiyat",        "Anlık fiyat: /fiyat BTC"),
    ("sifirla",      "Risk kilidini sıfırla"),
    ("ping",         "Bot bağlantısını test et"),
]


class TelegramCommandBot:
    """Telegram'dan çift yönlü kontrol — sadece yetkili chat_id kabul edilir."""

    def __init__(self, notifier: Notifier) -> None:
        self._n = notifier
        self._offset = 0
        self._task: "asyncio.Task | None" = None
        self._portfolio = None
        self._engine = None
        self._cfg = None
        self._feed = None
        self._log_fn = None          # terminal'e yazmak için callback

    # ── Yaşam döngüsü ───────────────────────────────────────────────────────

    def start(self, portfolio, engine, cfg, feed=None, log_fn=None) -> None:
        if not self._n.enabled:
            return
        self._portfolio = portfolio
        self._engine = engine
        self._cfg = cfg
        self._feed = feed
        if log_fn:
            self._log_fn = log_fn
        if self._task and not self._task.done():
            self._log("[grey50]📱 Telegram komut botu aktif (chat_id: "
                      f"{self._n.chat_id})[/]")
            return
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._poll_loop())
        except RuntimeError:
            # Event loop yoksa asyncio.create_task dene
            self._task = asyncio.create_task(self._poll_loop())

    def set_log_fn(self, fn) -> None:
        self._log_fn = fn

    def _log(self, text: str) -> None:
        if self._log_fn:
            try:
                self._log_fn(text)
            except Exception:
                pass

    def update_engine(self, engine) -> None:
        self._engine = engine

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    # ── Polling döngüsü ─────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        self._log("[grey50]📱 Telegram komut botu başladı (polling aktif)[/]")
        await self._register_commands()
        _err_count = 0
        _conflict_logged = False
        while True:
            try:
                conflict = await self._poll_once()
                _err_count = 0
                if conflict:
                    # 409: önceki oturumun poll'u bitmesini bekle (20s timeout + buffer)
                    if not _conflict_logged:
                        self._log(
                            "[gold3]📱 Telegram 409: önceki oturum kapanıyor, "
                            "35sn bekleniyor…[/]"
                        )
                        _conflict_logged = True
                    await asyncio.sleep(35)
                else:
                    _conflict_logged = False
            except asyncio.CancelledError:
                self._log("[grey50]📱 Telegram botu durduruldu.[/]")
                break
            except Exception as e:
                _err_count += 1
                if _err_count <= 3:
                    self._log(f"[red3]📱 Telegram poll hatası: {e}[/]")
                await asyncio.sleep(5)
                continue
            await asyncio.sleep(0)

    async def _register_commands(self) -> None:
        """setMyCommands ile Telegram'da / menüsünü ayarla."""
        url = f"{TELEGRAM_API}/bot{self._n.token}/setMyCommands"
        cmds = [{"command": c, "description": d} for c, d in _BOT_COMMANDS]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                r = await client.post(url, json={"commands": cmds})
                if r.status_code == 200:
                    self._log("[grey50]📱 Telegram / menüsü kaydedildi.[/]")
        except Exception as e:
            self._log(f"[grey50]📱 Telegram komut menüsü kaydedilemedi: {e}[/]")

    async def _poll_once(self) -> None:
        url = f"{TELEGRAM_API}/bot{self._n.token}/getUpdates"
        params = {"offset": self._offset, "timeout": 20, "limit": 10}
        _timeout = httpx.Timeout(connect=5.0, read=25.0, write=5.0, pool=5.0)
        try:
            async with httpx.AsyncClient(timeout=_timeout) as client:
                r = await client.get(url, params=params)
        except (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError,
                httpx.ReadTimeout, httpx.ConnectTimeout, httpx.PoolTimeout,
                httpx.WriteError, OSError):
            return
        if r.status_code == 401:
            # Geçersiz token — poll loopunu durdur, tekrar deneme
            self._log(
                "[red3]📱 Telegram token geçersiz (401). "
                "Bot durduruldu. /bildirim bagla TOKEN CHAT_ID ile yenile.[/]"
            )
            raise asyncio.CancelledError
        if r.status_code == 409:
            # Başka bir oturum aktif — loop'a sinyal gönder, orada beklenir
            return True
        if r.status_code != 200:
            self._log(f"[grey58]📱 Telegram getUpdates hata: HTTP {r.status_code}[/]")
            return
        for update in r.json().get("result", []):
            self._offset = update["update_id"] + 1
            await self._handle_update(update)

    async def _handle_update(self, update: dict) -> None:
        msg = update.get("message") or update.get("edited_message") or {}
        if not msg:
            return
        chat_id_raw = msg.get("chat", {}).get("id", "")
        chat_id = str(chat_id_raw).strip()
        configured_id = str(self._n.chat_id).strip()
        if chat_id != configured_id:
            self._log(f"[grey50]📱 Telegram: yetkisiz mesaj chat_id={chat_id} (beklenen={configured_id})[/]")
            return
        text = (msg.get("text") or "").strip()
        if not text.startswith("/"):
            return
        parts = text.split()
        cmd = parts[0].lstrip("/").lower().split("@")[0]
        args = parts[1:]
        self._log(f"[cyan]📱 Telegram ← /{cmd}{' ' + ' '.join(args) if args else ''}[/]")
        try:
            reply = await self._dispatch(cmd, args)
        except Exception as e:
            reply = f"❌ Hata: {e}"
            self._log(f"[red3]📱 Telegram dispatch hatası ({cmd}): {e}[/]")
        if reply:
            await self._n.send(reply)

    # ── Komut yönlendirici ──────────────────────────────────────────────────

    async def _dispatch(self, cmd: str, args: list) -> str:
        if cmd in ("yardim", "start", "help"):
            return self._yardim()
        if cmd in ("ping", "test"):
            return "🏓 Pong! Bot aktif ve komutları dinliyor."
        if cmd == "bakiye":
            return await self._bakiye()
        if cmd == "durum":
            return await self._durum()
        if cmd in ("otonom", "auto"):
            return await self._otonom(args)
        if cmd in ("durdur", "stop", "dur"):
            return await self._otonom(["kapat"])
        if cmd in ("acil", "emergency", "kill", "panic", "hepsini_kapat"):
            return await self._acil()
        if cmd in ("limit",):
            return await self._limit(args)
        if cmd in ("sifirla", "reset", "kilit"):
            return await self._sifirla()
        if cmd == "sat":
            return await self._sat(args)
        if cmd in ("mod", "profil", "risk"):
            return self._profil(args)
        if cmd in ("fiyat", "price", "p"):
            return await self._fiyat(args)
        if cmd in ("tarama", "scan", "tara"):
            return await self._tarama()
        if cmd in ("gecmis", "history", "ozet"):
            return await self._gecmis()
        if cmd in ("performans", "performance", "rapor", "report", "stats"):
            return await self._performans()
        return f"❓ Bilinmeyen komut: /{cmd}\n/yardim yaz"

    # ── Komut handler'ları ──────────────────────────────────────────────────

    def _yardim(self) -> str:
        return (
            "🤖 <b>trade-k Komutları</b>\n\n"
            "<b>📊 Bilgi &amp; Analiz:</b>\n"
            "/durum — Açık pozisyonlar ve K/Z\n"
            "/bakiye — Nakit ve toplam varlık\n"
            "/performans — Detaylı performans raporu\n"
            "/gecmis — Son 8 işlem özeti\n"
            "/fiyat BTC — Anlık fiyat\n"
            "/fiyat ETH SOL — Çoklu fiyat\n"
            "\n<b>🤖 Otonom Kontrol:</b>\n"
            "/otonom ac long — Sadece LONG adayları\n"
            "/otonom ac short — Sadece SHORT adayları\n"
            "/otonom ac longshort — Her iki yön\n"
            "/otonom ac scalp — Hızlı işlem modu\n"
            "/otonom ac kaldirac — Kaldıraçlı paper\n"
            "/otonom ac tam — Tüm modlar\n"
            "/otonom kapat — Otonom durdur\n"
            "/otonom durum — Durum ve istatistik\n"
            "/durdur — Hızlı durdur\n"
            "\n<b>🚨 Güvenlik &amp; Acil:</b>\n"
            "/acil — Tüm pozisyonları kapat + otonom durdur\n"
            "/limit 5 — Günlük işlem limitini değiştir\n"
            "/limit durum — Limit bilgisi\n"
            "\n<b>⚙️ İşlem &amp; Ayarlar:</b>\n"
            "/sat BTC — Pozisyon kapat\n"
            "/mod guvenli|dengeli|agresif — Risk profili\n"
            "/sifirla — Risk kilidini sıfırla\n"
            "/ping — Bağlantı testi\n"
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
            st = e.state
            p_eff = e.effective_profile
            status = "🟢 AÇIK" if st.enabled else "⚫ KAPALI"
            mod = getattr(self._cfg, "otonom_trade_type", "long") if self._cfg else "?"
            profil = getattr(self._cfg, "autonomous_mode", "dengeli") if self._cfg else "?"
            n_pos = len(self._portfolio.positions) if self._portfolio else 0
            risk_str = "🔴 AKTİF" if st.risk_locked else "✅ Yok"

            # Günlük zarar hesapla
            daily_loss_str = "—"
            try:
                import market as _mkt_mod
                prices = {s: tk.price for s, tk in e.feed.tickers.items()
                          if tk.price > 0}
                cur_eq = (self._portfolio.equity(prices)
                          if self._portfolio and prices else 0.0)
                if st.daily_start_equity and cur_eq:
                    loss_pct = ((st.daily_start_equity - cur_eq)
                                / st.daily_start_equity * 100)
                    sign = "+" if loss_pct <= 0 else ""
                    color_tag = "" if loss_pct <= 0 else ""
                    daily_loss_str = (
                        f"{'+' if loss_pct <= 0 else ''}{-loss_pct:.2f}% "
                        f"(limit: %{p_eff.daily_loss_limit_percent:.0f})"
                    )
            except Exception:
                pass

            # Cooldown kalan süre
            cooldown_str = ""
            import time as _time_mod
            if st.cooldown_until and _time_mod.time() < st.cooldown_until:
                rem = int(st.cooldown_until - _time_mod.time()) // 60
                cooldown_str = f"\n⏳ Circuit breaker soğuma: {rem}dk kaldı"

            # WebSocket durumu
            ws_ok = getattr(e.feed, "ws_connected", True)
            ws_str = "✅ Bağlı" if ws_ok else "⚠️ Kopuk"

            # Pozisyon listesi
            pos_list = ""
            if self._portfolio and self._portfolio.positions:
                lines = []
                for sym, pos in list(self._portfolio.positions.items())[:5]:
                    name = sym.replace("USDT", "")
                    side = "L" if pos.direction == "long" else "S"
                    lines.append(f"  • {name} [{side}] @ {pos.entry:,.4f}")
                pos_list = "\n" + "\n".join(lines)
                if len(self._portfolio.positions) > 5:
                    pos_list += f"\n  ...ve {len(self._portfolio.positions)-5} daha"

            last_scan_str = "—"
            if st.last_scan_time:
                import time as _t
                ago = int(_t.time() - st.last_scan_time) // 60
                last_scan_str = f"{ago}dk önce"

            limit_str = (f"{st.daily_trade_limit_override} ⚡(override)"
                         if st.daily_trade_limit_override
                         else str(p_eff.max_daily_trades))

            msg = (
                f"🤖 <b>Otonom Durum</b>\n\n"
                f"Durum: {status}\n"
                f"Mod: <b>{mod.upper()}</b> | Profil: <b>{profil}</b>\n"
                f"İşlem: {st.daily_trades}/{limit_str} bugün\n"
                f"Açık pozisyon: {n_pos}/{p_eff.max_open_positions}{pos_list}\n"
                f"Risk kilidi: {risk_str}\n"
                f"Günlük K/Z: {daily_loss_str}\n"
                f"WebSocket: {ws_str}\n"
                f"Son tarama: {last_scan_str}"
                f"{cooldown_str}\n\n"
                f"📝 <i>Paper mode — gerçek para riski yok</i>"
            )
            if st.risk_locked:
                msg += "\n\n⚠️ <b>Risk kilidi aktif — yeni işlem açılmıyor.</b>\nDevam: /sifirla"
            if not ws_ok:
                msg += "\n\n⚠️ <b>WebSocket kopuk — tarama duraklatıldı.</b>"
            return msg
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
            # Eğer risk kilidi varsa açıkça bildir
            if self._engine.state.risk_locked:
                return (
                    "⚠️ <b>Risk kilidi aktif</b> — otonom başlatılamaz.\n"
                    "Terminalde <code>/sifirla</code> yaz veya gün sonu bekle."
                )
            ot, plan, scalp, lev = _MAP[trade_arg]
            self._cfg.otonom_trade_type = ot
            self._cfg.trade_plan = plan
            self._cfg.scalp_enabled = scalp
            self._cfg.leverage_enabled = lev
            self._cfg.save()
            result = await self._engine.start()
            if self._engine.state.enabled:
                self._log(f"[green3]📱 Telegram: otonom mod açıldı → {trade_arg.upper()}[/]")
                return f"✅ Otonom mod açıldı: <b>{trade_arg.upper()}</b>"
            return f"⚠️ {result}"
        return "Kullanım:\n/otonom ac [long|short|longshort|scalp|kaldirac|tam]\n/otonom kapat\n/otonom durum"

    async def _acil(self) -> str:
        """Acil kapatma: tüm pozisyonları kapat + otonom durdur."""
        if not self._engine or not self._portfolio:
            return "❌ Motor veya portföy bağlı değil"
        if not self._portfolio.positions:
            await self._engine.stop("Acil kapatma — pozisyon yok")
            return "⏹ Otonom durduruldu. Açık pozisyon yok."
        self._log("[bold red3]📱 Telegram: /acil komutu alındı[/]")
        result = await self._engine.emergency_close()
        closed = result["closed"]
        errors = result["errors"]
        total_pnl = result["total_pnl"]
        sign = "+" if total_pnl >= 0 else ""
        lines = [f"🚨 <b>ACİL KAPATMA TAMAMLANDI</b>\n"]
        lines.append(f"Otonom: ⏹ Durduruldu | Risk kilidi: 🔴 Aktif")
        lines.append(f"Kapatılan: <b>{len(closed)}</b> | Hata: {len(errors)}\n")
        for c in closed:
            sym = c["symbol"].replace("USDT", "")
            pnl = c["pnl"]
            em = "✅" if pnl >= 0 else "❌"
            lines.append(
                f"{em} {sym}: {'+' if pnl >= 0 else ''}{pnl:,.2f} USDT "
                f"@ {c['exit_price']:,.4f}"
            )
        if errors:
            lines.append(f"\n⚠️ Kapatılamadı: {', '.join(e.replace('USDT','') for e in errors)}")
        lines.append(f"\n<b>Net K/Z: {sign}{total_pnl:,.2f} USDT</b>")
        lines.append("\nYeni işlem açmak için önce /sifirla yapın.")
        return "\n".join(lines)

    async def _limit(self, args: list) -> str:
        """Günlük işlem limitini runtime'da değiştir."""
        if not self._engine:
            return "❌ Motor bağlı değil"
        if not args or args[0].lower() == "durum":
            st = self._engine.state
            p = self._engine.effective_profile
            override = st.daily_trade_limit_override
            current_limit = override if override else p.max_daily_trades
            src = "⚡ override" if override else "profil"
            return (
                f"📊 <b>Günlük İşlem Limiti</b>\n\n"
                f"Aktif limit: <b>{current_limit}</b> ({src})\n"
                f"Bugün yapılan: {st.daily_trades}\n"
                f"Profil varsayılanı: {p.max_daily_trades}\n\n"
                f"Değiştirmek için: /limit 5"
            )
        raw = args[0]
        if not raw.isdigit():
            return f"❌ Geçersiz değer: <b>{raw}</b>\nKullanım: /limit 5"
        n = int(raw)
        msg = self._engine.set_daily_trade_limit(n)
        if msg.startswith("✅"):
            self._log(f"[cyan]📱 Telegram: /limit → {n}[/]")
        return msg

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
            mod = getattr(self._cfg, "otonom_trade_type", "long")
            return (
                f"📊 <b>Mevcut Ayarlar</b>\n\n"
                f"Risk profili: <b>{cur}</b>\n"
                f"Trade modu: <b>{mod}</b>\n\n"
                "Değiştir:\n"
                "/mod guvenli | /mod dengeli | /mod agresif"
            )
        p = args[0].lower()
        if p not in {"guvenli", "dengeli", "agresif"}:
            return f"❌ Geçersiz profil: {p}\nSeçenekler: guvenli, dengeli, agresif"
        self._cfg.autonomous_mode = p
        self._cfg.save()
        # Engine'e de bildir
        if self._engine:
            try:
                from autonomous import AUTONOMOUS_PROFILES
                self._engine.profile = AUTONOMOUS_PROFILES[p]
            except Exception:
                pass
        self._log(f"[cyan]📱 Telegram: Risk profili → {p}[/]")
        return f"✅ Risk profili değiştirildi: <b>{p.upper()}</b>"

    async def _fiyat(self, args: list) -> str:
        if not args:
            return "Kullanım: /fiyat BTC\nVeya: /fiyat ETH SOL BNB"
        results = []
        for raw in args[:5]:
            sym = raw.upper()
            if not sym.endswith("USDT"):
                sym += "USDT"
            try:
                import market as _mkt
                price = await _mkt.quote(sym)
                name = sym.replace("USDT", "")
                results.append(f"<b>{name}/USDT</b>: {price:,.4f}")
            except Exception:
                results.append(f"{sym.replace('USDT','')}: fiyat alınamadı")
        return "💹 <b>Anlık Fiyatlar</b>\n\n" + "\n".join(results)

    async def _sifirla(self) -> str:
        if not self._engine:
            return "❌ Motor bağlı değil"
        p = self._portfolio
        equity = p.cash if p else 100.0
        self._engine.state.risk_locked = False
        self._engine.state.consecutive_losses = 0
        self._engine.state.daily_trades = 0
        self._engine.state.daily_start_equity = equity
        self._engine.state.save(self._engine._state_path)
        self._log(f"[cyan]📱 Telegram: risk kilidi sıfırlandı (equity={equity:.2f})[/]")
        return (
            f"✅ <b>Risk kilidi sıfırlandı</b>\n"
            f"Başlangıç varlık: {equity:,.2f} USDT\n"
            "Artık /otonom ac ile başlatabilirsin."
        )

    async def _performans(self) -> str:
        if not self._portfolio:
            return "❌ Portföy bağlı değil"
        import performance as perf_mod
        from datetime import datetime as _dt
        from pathlib import Path as _Path
        p = self._portfolio
        h = p.history

        # Anlık fiyatları al
        prices: dict = {}
        for sym in p.positions:
            try:
                import market as _mkt
                prices[sym] = await _mkt.quote(sym)
            except Exception:
                prices[sym] = p.positions[sym].entry

        # Portföy değerleri hesapla
        equity = p.equity(prices) if prices else p.cash
        pos_value = equity - p.cash
        unrealized_pnl = 0.0
        for sym, pos in p.positions.items():
            cur = prices.get(sym, pos.entry)
            pnl_v = (pos.entry - cur if pos.direction == "short" else cur - pos.entry) * pos.qty
            unrealized_pnl += pnl_v

        # ── Kısa Telegram özeti ────────────────────────────────────────────
        short_msg = perf_mod.telegram_summary(
            h, p.cash, equity, unrealized_pnl, n_positions=len(p.positions)
        )

        # ── Otonom istatistik bloğu ────────────────────────────────────────
        if self._engine:
            st = self._engine.state
            auto_status = "⚠️ Aktif" if st.risk_locked else "✅ Yok"
            short_msg += (
                f"\n\n<b>🤖 Otonom:</b>\n"
                f"Bugün: {st.daily_trades} işlem  "
                f"Zarar serisi: {st.consecutive_losses}  "
                f"Risk kilidi: {auto_status}"
            )

        # ── Detaylı txt raporu yaz ─────────────────────────────────────────
        try:
            ts = _dt.now().strftime("%Y%m%d_%H%M%S")
            report_path = _Path(__file__).parent / f"report_{ts}.txt"

            # Positions data for full_report
            positions_data = []
            for sym, pos in p.positions.items():
                cur = prices.get(sym, pos.entry)
                if pos.is_leveraged:
                    upnl = (cur - pos.entry) * pos.qty
                    upct = (cur / pos.entry - 1) * 100 * pos.leverage if pos.entry else 0
                    side_label = f"LEV{pos.leverage}x"
                elif pos.direction == "short":
                    upnl = (pos.entry - cur) * pos.qty
                    upct = (pos.entry / cur - 1) * 100 if cur else 0
                    side_label = "SHORT"
                else:
                    upnl = (cur - pos.entry) * pos.qty
                    upct = (cur / pos.entry - 1) * 100 if pos.entry else 0
                    side_label = "SCALP" if pos.trade_style == "scalp" else "LONG"
                positions_data.append({
                    "symbol": sym, "side": side_label,
                    "entry": pos.entry, "current": cur, "qty": pos.qty,
                    "unrealized_pnl": upnl, "pnl_pct": upct,
                    "stop": pos.stop, "target": pos.target,
                })

            rich_report = perf_mod.full_report(
                h,
                unrealized_pnl=unrealized_pnl if p.positions else None,
                cash=p.cash,
                pos_value=pos_value,
                starting_equity=perf_mod.STARTING_CASH,
                positions_data=positions_data or None,
            )
            plain = perf_mod._strip_rich(rich_report)
            report_path.write_text(
                f"trade-k Performans Raporu — {_dt.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"{'=' * 60}\n\n" + plain,
                encoding="utf-8",
            )
            short_msg += f"\n\n📁 Detay: <code>{report_path.name}</code>"
        except Exception:
            pass

        return short_msg

    async def _tarama(self) -> str:
        if not self._engine:
            return "❌ Otonom motor bağlı değil"
        if not self._engine.state.enabled:
            return "⚠️ Otonom mod kapalı — önce /otonom ac [mod] yaz"
        return "🔍 Tarama otonom döngüde zaten çalışıyor. /durum ile pozisyonları gör."

    async def _gecmis(self) -> str:
        if not self._portfolio:
            return "❌ Portföy bağlı değil"
        h = self._portfolio.history
        if not h:
            return "📭 Bugün henüz işlem yapılmadı"
        today = __import__("time").strftime("%Y-%m-%d")
        bugun = [t for t in h if t.get("date", "")[:10] == today]
        if not bugun:
            bugun = list(h[-10:])  # son 10 işlem
        total_pnl = sum(t.get("pnl_usdt", 0) for t in bugun)
        lines = [f"📋 <b>Son İşlemler ({len(bugun)})</b>\n"]
        for t in bugun[-8:]:
            sym = t.get("symbol", "?").replace("USDT", "")
            side = t.get("side", "SAT")
            pnl = t.get("pnl_usdt", 0)
            emoji = "✅" if pnl >= 0 else "❌"
            sign = "+" if pnl >= 0 else ""
            lines.append(f"{emoji} {sym} {side}: {sign}{pnl:,.2f} USDT")
        lines.append(f"\n<b>Toplam K/Z: {'+' if total_pnl >= 0 else ''}{total_pnl:,.2f} USDT</b>")
        return "\n".join(lines)


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
