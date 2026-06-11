"""trade-k — Claude destekli paper trading terminali.

Çalıştır:  ./basla.sh   (veya .venv/bin/python app.py)
Komutlar:  /yardim yazınca listelenir.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Footer, Input, RichLog, Static

import commands as cmd_mod

import ai
import config as config_mod
import i18n
import live
import market
import modes
from autonomous import AutonomousEngine
from config import MODELS, Config
from i18n import t
from portfolio import Portfolio, sanitize_levels
from screens import LoginScreen, SetupScreen, SplashMenuScreen
from tracker import STATUS_TR, Tracker

WATCHLIST_FILE = Path(__file__).parent / "watchlist.json"
DEFAULT_WATCHLIST = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT"]
OLD_DEFAULTS = [
    ["BTCUSDT", "ETHUSDT", "SOLUSDT", "PAXGUSDT", "XRPUSDT"],
    ["BTCUSDT", "ETHUSDT", "GC=F", "USDTRY=X", "^GSPC"],
]
MAX_SYMBOLS = 5

SCAN_CATEGORIES = {"kripto", "global", "forex", "emtia", "endeks"}


def fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:.6f}"


class AccountBar(Static):
    """Üst bar: hesap tipi, otonom durum, pozisyon sayısı, günlük bilgiler."""

    def update_view(
        self,
        equity: float,
        cash: float,
        start: float,
        live_ok: bool,
        name: str,
        auto_enabled: bool,
        auto_daily_trades: int,
        auto_risk_locked: bool,
        open_positions: int,
        daily_pnl: float,
        ws_connected: bool = True,
    ) -> None:
        pnl = equity - start
        pct = pnl / start * 100
        color = "green3" if pnl >= 0 else "red3"
        sign = "+" if pnl >= 0 else ""

        txt = Text()
        txt.append("  trade-k ", style="bold black on gold3")
        txt.append("  PAPER  ", style="bold white on dark_orange")
        if live_ok:
            txt.append(" LIVE✓ ", style="bold black on green3")

        # Otonom durum
        if auto_enabled:
            txt.append(" OTONOM:AÇIK ", style="bold black on green3")
        else:
            txt.append(" OTONOM:KAPALI ", style="bold white on grey23")

        # WS bağlantı durumu
        if ws_connected:
            txt.append(" WS:ON ", style="bold black on green3")
        else:
            txt.append(" WS:OFF ", style="bold white on red3")

        # Risk kilidi
        if auto_risk_locked:
            txt.append(" ⚠KİLİT ", style="bold white on red3")

        txt.append(f"  Pos:{open_positions}  ", style="grey70")
        txt.append(f"Gün:{auto_daily_trades}/3  ", style="grey70")

        # Günlük PnL
        dpnl_color = "green3" if daily_pnl >= 0 else "red3"
        dpnl_sign = "+" if daily_pnl >= 0 else ""
        txt.append(f"GünPnL:{dpnl_sign}{daily_pnl:,.2f}  ",
                   style=f"bold {dpnl_color}")

        txt.append(f"{t('bar.equity')}: ", style="bold")
        txt.append(f"${equity:,.2f}", style="bold white")
        txt.append(f"  {t('bar.cash')}: ${cash:,.2f}", style="grey70")
        txt.append(f"  {t('bar.pnl')}: ", style="bold")
        txt.append(f"{sign}{pnl:,.2f} ({sign}{pct:.2f}%)", style=f"bold {color}")
        txt.append(f"  {name}", style="grey58")
        self.update(txt)


class CommandInput(Input):
    """Input subclass — palette navigation keylerini yakalar."""

    def _on_key(self, event: events.Key) -> None:
        app: "TradeApp" = self.app  # type: ignore[assignment]
        if app._palette_visible:
            if event.key in ("down", "tab"):
                app._palette_cursor = min(app._palette_cursor + 1,
                                          len(app._palette_items) - 1)
                app._update_palette_display()
                event.prevent_default()
                event.stop()
                return
            elif event.key == "up":
                app._palette_cursor = max(0, app._palette_cursor - 1)
                app._update_palette_display()
                event.prevent_default()
                event.stop()
                return
            elif event.key == "escape":
                app._close_palette()
                event.prevent_default()
                event.stop()
                return
            elif event.key == "enter":
                app._apply_palette_selection()
                event.prevent_default()
                event.stop()
                return
        super()._on_key(event)


class TradeApp(App):
    CSS_PATH = "app.tcss"
    BINDINGS = [("q", "action_open_menu", "Menü")]
    TITLE = "trade-k"

    def __init__(self) -> None:
        super().__init__()
        self.cfg: Config | None = Config.load() if Config.exists() else None
        if self.cfg:
            config_mod.set_current(self.cfg)
            i18n.set_language(self.cfg.language)
        self.portfolio = Portfolio.load()
        self.watchlist = self._load_watchlist()
        self.feed = market.MarketFeed(symbols=self._feed_symbols())
        self.tracker = Tracker.load()
        self.pending: list[ai.Suggestion] = []
        self.pending_ids: list[str] = []
        self.ai_busy = False
        # Otonom motor (cfg hazır olunca _start_main'de tam kurulur)
        self._auto_engine: AutonomousEngine | None = None
        # Son Claude kararları (pozisyon tablosu için)
        self._position_decisions: dict[str, str] = {}
        # Günlük başlangıç varlığı (günlük PnL hesabı için)
        self._daily_start_equity: float = 0.0
        self._daily_date: str = ""
        # Komut paleti
        self._palette_items: list = []
        self._palette_cursor: int = 0
        self._palette_visible: bool = False
        self._main_started: bool = False

    # ── yerleşim ─────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield AccountBar(id="account")
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield Static(t("panel.market"), id="title-market",
                             classes="paneltitle")
                yield DataTable(id="watch", cursor_type="none")
                yield Static(t("panel.positions"), id="title-positions",
                             classes="paneltitle")
                yield DataTable(id="positions", cursor_type="none")
            with Vertical(id="right"):
                yield Static(t("panel.log"), id="title-log", classes="paneltitle")
                yield RichLog(id="log", wrap=True, markup=True)
        yield Static("", id="palette")
        yield CommandInput(placeholder=t("cmd.placeholder"), id="cmd")
        yield Footer()

    async def on_mount(self) -> None:
        if self.cfg is None:
            self.push_screen(SetupScreen(), self._after_setup)
        else:
            self.push_screen(LoginScreen(self.cfg), self._after_login)

    def action_open_menu(self) -> None:
        if not self._main_started:
            return
        summary = self._portfolio_summary()
        self.push_screen(SplashMenuScreen(self.cfg, summary), self._after_menu)

    def _after_menu(self, result) -> None:
        if result == "exit":
            self.exit()
        elif result == "auto_start":
            if self._auto_engine:
                self.run_worker(self._do_auto_start(), exclusive=False)

    async def _do_auto_start(self) -> None:
        log = self.query_one("#log", RichLog)
        msg = await self._auto_engine.start()
        if msg:
            log.write(msg)
        else:
            log.write(t("otonom.started"))

    def _portfolio_summary(self) -> str:
        prices = {s: tk.price for s, tk in self.feed.tickers.items()}
        eq = self.portfolio.equity(prices)
        pos_count = len(self.portfolio.positions)
        return f"Varlık: {eq:,.0f} USDT | {pos_count} pozisyon"

    def _after_setup(self, cfg: Config) -> None:
        self.cfg = cfg
        config_mod.set_current(cfg)
        i18n.set_language(cfg.language)
        self.run_worker(self._start_main(first_run=True), exclusive=False)

    def _after_login(self, ok: bool) -> None:
        if not ok:
            self.exit()
            return
        summary = self._portfolio_summary()
        self.push_screen(SplashMenuScreen(self.cfg, summary), self._after_splash)

    def _after_splash(self, result) -> None:
        if result == "exit":
            self.exit()
            return
        auto_start = (result == "auto_start")
        self.run_worker(self._start_main(auto_start=auto_start), exclusive=False)

    async def _start_main(self, first_run: bool = False, auto_start: bool = False) -> None:
        self.query_one("#title-market", Static).update(t("panel.market"))
        self.query_one("#title-positions", Static).update(t("panel.positions"))
        self.query_one("#title-log", Static).update(t("panel.log"))
        self.query_one("#cmd", Input).placeholder = t("cmd.placeholder")

        watch = self.query_one("#watch", DataTable)
        if i18n.lang() == "en":
            watch.add_columns("Instrument", "Price", "Change %", "High", "Low")
        else:
            watch.add_columns("Enstrüman", "Fiyat", "Değişim %", "Yüksek", "Düşük")

        pos = self.query_one("#positions", DataTable)
        if i18n.lang() == "en":
            pos.add_columns("Instrument", "Qty", "Entry", "Now", "P/L", "P/L %",
                            "Stop", "Target", "Stop%", "Tgt%", "Duration", "Decision")
        else:
            pos.add_columns("Enstrüman", "Miktar", "Giriş", "Şimdi", "K/Z", "K/Z %",
                            "Stop", "Hedef", "Stop%", "Hdf%", "Süre", "Karar")

        # Otonom motoru başlat
        self._auto_engine = AutonomousEngine(
            portfolio=self.portfolio,
            feed=self.feed,
            tracker=self.tracker,
            cfg=self.cfg,
            log_fn=lambda msg: self.query_one("#log", RichLog).write(msg),
            watchlist_fn=lambda: list(self.watchlist),
            sync_feed_fn=self._sync_feed_bg,
        )
        self._position_decisions = self._auto_engine.position_decisions

        # Günlük başlangıç varlığını ayarla
        self._daily_date = datetime.now().strftime("%Y-%m-%d")
        all_prices = {s: tk.price for s, tk in self.feed.tickers.items()}
        self._daily_start_equity = self.portfolio.equity(all_prices) or 10_000.0

        log = self.query_one("#log", RichLog)
        if first_run:
            log.write(t("setup.done", name=self.cfg.name))
        log.write(t("app.started", name=self.cfg.name))
        log.write(t("app.mode_model", model=self.cfg.model))
        log.write(t("app.hint"))
        await self.feed.start()
        self.set_interval(0.5, self.refresh_tables)
        self.set_interval(2.0, self.check_protections)
        self._main_started = True
        self.query_one("#cmd", CommandInput).focus()
        if auto_start and self._auto_engine:
            msg = await self._auto_engine.start()
            log.write(msg if msg else t("otonom.started"))

    def _sync_feed_bg(self) -> None:
        """Otonom motordan çağrılabilen sync wrapper."""
        self.run_worker(self._sync_feed(), exclusive=False)

    def _feed_symbols(self) -> list[str]:
        syms = list(self.watchlist) + list(market.SCAN_INSTRUMENTS)
        for s in self.portfolio.positions:
            if s not in syms:
                syms.append(s)
        return syms

    async def _sync_feed(self) -> None:
        await self.feed.set_symbols(self._feed_symbols())

    # ── komut paleti ──────────────────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "cmd":
            return
        val = event.value.strip()
        if not val.startswith("/"):
            self._close_palette()
            return
        ctx = {
            "has_positions": bool(self.portfolio.positions),
            "auto_enabled": bool(self._auto_engine and self._auto_engine.enabled),
            "scalp_enabled": bool(self.cfg and self.cfg.scalp_enabled),
            "leverage_enabled": bool(self.cfg and self.cfg.leverage_enabled),
        }
        self._palette_items = cmd_mod.get_palette_suggestions(val, ctx)
        self._palette_cursor = 0
        if self._palette_items:
            self._palette_visible = True
            self._update_palette_display()
        else:
            self._close_palette()

    def _update_palette_display(self) -> None:
        lang = i18n.lang()
        lines = []
        for i, (cmd_text, cat, desc_tr, desc_en) in enumerate(self._palette_items[:8]):
            cursor = "▶" if i == self._palette_cursor else " "
            highlight = "bold gold3" if i == self._palette_cursor else "white"
            cat_str = f"[grey50]{cat[:10]:10}[/]"
            desc = desc_en if (lang == "en" and desc_en) else desc_tr
            desc_str = f"[grey70]{desc[:38]:38}[/]"
            lines.append(f" {cursor} [{highlight}]{cmd_text:<20}[/] {cat_str} {desc_str}")
        if lang == "tr":
            lines.append("[grey50] ↑↓ seç  Tab ilerle  Enter çalıştır  Esc kapat[/]")
        else:
            lines.append("[grey50] ↑↓ move  Tab next  Enter run  Esc close[/]")
        try:
            self.query_one("#palette", Static).update("\n".join(lines))
        except Exception:
            pass

    def _close_palette(self) -> None:
        self._palette_visible = False
        self._palette_items = []
        self._palette_cursor = 0
        try:
            self.query_one("#palette", Static).update("")
        except Exception:
            pass

    def _apply_palette_selection(self) -> None:
        if not self._palette_items:
            return
        idx = min(self._palette_cursor, len(self._palette_items) - 1)
        cmd_text = self._palette_items[idx][0]
        cmd_inp = self.query_one("#cmd", CommandInput)
        cmd_inp.value = cmd_text
        cmd_inp.cursor_position = len(cmd_text)
        self._close_palette()

    # ── tablo yenileme ────────────────────────────────────────────────────────

    def _watch_row(self, watch: DataTable, sym: str) -> None:
        tk = self.feed.tickers.get(sym)
        if not tk:
            watch.add_row(market.short_name(sym), "...", "", "", "")
            return
        chg_color = "green3" if tk.change_pct >= 0 else "red3"
        tick_color = (
            ("green3" if tk.price >= tk.prev_price else "red3")
            if tk.prev_price else "white"
        )
        arrow = "▲" if tk.price > tk.prev_price else (
            "▼" if tk.price < tk.prev_price else " "
        )
        # Price age indicator for Yahoo symbols
        if market.is_yahoo(sym) and tk.last_updated:
            age = time.time() - tk.last_updated
            if age < 5:
                age_color = "green3"
            elif age < 30:
                age_color = "gold3"
            else:
                age_color = "red3"
            price_txt = Text(f"{fmt_price(tk.price)} {arrow}", style=tick_color)
            price_txt.append(f" ·{int(age)}s", style=age_color)
        else:
            price_txt = Text(f"{fmt_price(tk.price)} {arrow}", style=tick_color)
        watch.add_row(
            Text(market.short_name(sym), style="bold"),
            price_txt,
            Text(f"{tk.change_pct:+.2f}%", style=chg_color),
            Text(fmt_price(tk.high), style="grey58"),
            Text(fmt_price(tk.low), style="grey58"),
        )

    def refresh_tables(self) -> None:
        try:
            watch = self.query_one("#watch", DataTable)
            watch.clear()
            watch.add_row(Text(t("watch.crypto"), style="bold grey50"), "", "", "", "")
            for sym in self.watchlist:
                self._watch_row(watch, sym)
            watch.add_row(Text(t("watch.global"), style="bold grey50"), "", "", "", "")
            for sym in market.SCAN_INSTRUMENTS:
                self._watch_row(watch, sym)

            pos_table = self.query_one("#positions", DataTable)
            pos_table.clear()
            for sym, p in self.portfolio.positions.items():
                cur = self.feed.price(sym) or p.entry
                pnl, pct = self.portfolio.unrealized_pnl(sym, cur)
                color = "green3" if pnl >= 0 else "red3"
                sign = "+" if pnl >= 0 else ""

                # Stop/hedef mesafe %
                stop_pct_txt = Text("—", style="grey50")
                if p.stop and cur > 0:
                    sp = (cur - p.stop) / cur * 100
                    sp_color = "red3" if sp < 2 else "dark_orange" if sp < 5 else "grey70"
                    stop_pct_txt = Text(f"{sp:.1f}%", style=sp_color)

                tgt_pct_txt = Text("—", style="grey50")
                if p.target and cur > 0:
                    tp = (p.target - cur) / cur * 100
                    tp_color = "green3" if tp < 5 else "grey70"
                    tgt_pct_txt = Text(f"{tp:.1f}%", style=tp_color)

                # Son Claude kararı
                karar = self._position_decisions.get(sym, "")
                karar_colors = {
                    "DEVAM": "green3", "BEKLE": "gold3", "KAR_AL": "green3",
                    "ZARARI_KES": "red3", "STOP_GUNCELLE": "dark_orange",
                }
                karar_txt = (
                    Text(karar, style=karar_colors.get(karar, "grey50"))
                    if karar else Text("—", style="grey50")
                )

                # Süre / Duration sütunu
                now_ts = time.time()
                elapsed = now_ts - (p.opened_at or now_ts)
                if p.trade_style == "scalp":
                    from portfolio import SCALP_MAX_DURATION
                    remaining = max(0.0, SCALP_MAX_DURATION - elapsed)
                    rm = int(remaining // 60)
                    rs = int(remaining % 60)
                    dur_color = "red3" if remaining < 300 else ("gold3" if remaining < 600 else "cyan")
                    dur_txt = Text(f"⏱{rm}:{rs:02d}", style=dur_color)
                elif elapsed < 3600:
                    dur_txt = Text(f"{int(elapsed // 60)}m", style="grey58")
                elif elapsed < 86400:
                    dur_txt = Text(f"{int(elapsed // 3600)}h{int((elapsed % 3600) // 60)}m", style="grey58")
                else:
                    dur_txt = Text(f"{int(elapsed // 86400)}d", style="grey58")

                pos_table.add_row(
                    Text(market.short_name(sym), style="bold"),
                    f"{p.qty:.6f}",
                    fmt_price(p.entry),
                    fmt_price(cur),
                    Text(f"{sign}{pnl:,.2f}", style=color),
                    Text(f"{sign}{pct:.2f}%", style=color),
                    Text(fmt_price(p.stop), style="red3") if p.stop
                    else Text("—", style="grey50"),
                    Text(fmt_price(p.target), style="green3") if p.target
                    else Text("—", style="grey50"),
                    stop_pct_txt,
                    tgt_pct_txt,
                    dur_txt,
                    karar_txt,
                )

            # Günlük PnL hesapla
            all_prices = {s: tk.price for s, tk in self.feed.tickers.items()}
            cur_equity = self.portfolio.equity(all_prices)

            today = datetime.now().strftime("%Y-%m-%d")
            if today != self._daily_date:
                self._daily_date = today
                self._daily_start_equity = cur_equity

            daily_pnl = cur_equity - self._daily_start_equity

            auto_enabled = bool(self._auto_engine and self._auto_engine.enabled)
            auto_trades = self._auto_engine.daily_trades if self._auto_engine else 0
            auto_locked = bool(self._auto_engine and self._auto_engine.risk_locked)

            self.query_one("#account", AccountBar).update_view(
                equity=cur_equity,
                cash=self.portfolio.cash,
                start=10_000.0,
                live_ok=bool(self.cfg and self.cfg.binance_key),
                name=self.cfg.name if self.cfg else "",
                auto_enabled=auto_enabled,
                auto_daily_trades=auto_trades,
                auto_risk_locked=auto_locked,
                open_positions=len(self.portfolio.positions),
                daily_pnl=daily_pnl,
                ws_connected=self.feed.ws_connected if self.feed.crypto_symbols else True,
            )
        except Exception:
            pass

    # ── komutlar ─────────────────────────────────────────────────────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        cmd = event.value.strip()
        event.input.value = ""
        if not cmd:
            return
        log = self.query_one("#log", RichLog)
        shown = (
            "/canli bagla ********"
            if cmd.lower().startswith("/canli bagla")
            else cmd
        )
        log.write(f"[grey50]> {shown}[/]")
        try:
            await self.handle_command(cmd)
        except ValueError as e:
            log.write(f"[red3]Hata: {e}[/]")
        except Exception as e:
            log.write(f"[red3]Beklenmeyen hata: {e}[/]")

    async def handle_command(self, cmd: str) -> None:
        log = self.query_one("#log", RichLog)
        parts = cmd.split()
        op = parts[0].lower().lstrip("/")

        # TR/EN alias tablosu
        _ALIASES = {
            "scan": "tara", "status": "durum", "buy": "al", "sell": "sat",
            "protect": "koru", "auto": "otonom", "approve": "onayla",
            "reject": "reddet", "add": "ekle", "remove": "cikar",
            "report": "performans", "rapor": "performans",
            "reset": "sifirla",
        }
        op = _ALIASES.get(op, op)

        if op in ("yardim", "help", "h"):
            log.write(t("help"))

        elif op == "al":
            if len(parts) < 3:
                raise ValueError("Kullanım: /al SEMBOL TUTAR  (örn: /al btc 500)")
            sym = market.resolve_symbol(parts[1])
            usdt = float(parts[2].replace(",", "."))
            price = await self._price_of(sym)
            log.write(f"[green3]{self.portfolio.buy(sym, usdt, price)}[/]")
            await self._sync_feed()
            self.run_protect(sym)

        elif op == "short":
            if len(parts) < 3:
                raise ValueError("Kullanım: /short SEMBOL TUTAR  (örn: /short btcusdt 500)")
            sym = market.resolve_symbol(parts[1])
            allowed, reason = market.trade_allowed(sym)
            if not allowed:
                raise ValueError(reason)
            raise ValueError("Short paper işlemi bu sürümde desteklenmiyor.")

        elif op == "scalp":
            if len(parts) < 3:
                raise ValueError("Kullanım: /scalp SEMBOL TUTAR")
            sym = market.resolve_symbol(parts[1])
            allowed, reason = market.trade_allowed(sym)
            if not allowed:
                raise ValueError(reason)
            raise ValueError("Scalp paper işlemi bu sürümde desteklenmiyor.")

        elif op == "sat":
            if len(parts) < 2:
                raise ValueError("Kullanım: /sat SEMBOL [TUTAR]")
            sym = market.resolve_symbol(parts[1])
            usdt = (
                float(parts[2].replace(",", ".")) if len(parts) > 2 else None
            )
            price = await self._price_of(sym)
            log.write(f"[dark_orange]{self.portfolio.sell(sym, price, usdt)}[/]")
            await self._sync_feed()

        elif op == "koru":
            if len(parts) < 2:
                raise ValueError("Kullanım: /koru SEMBOL")
            sym = market.resolve_symbol(parts[1])
            if sym not in self.portfolio.positions:
                raise ValueError(f"{market.short_name(sym)} pozisyonu yok.")
            self.run_protect(sym)

        elif op == "durum":
            await self._cmd_durum()

        elif op == "ekle":
            if len(parts) < 2:
                raise ValueError("Kullanım: /ekle SEMBOL")
            sym = market.resolve_symbol(parts[1])
            if market.is_yahoo(sym):
                raise ValueError(
                    f"{market.short_name(sym)} zaten GLOBAL panelde gösteriliyor."
                )
            if sym in self.watchlist:
                raise ValueError(f"{market.short_name(sym)} zaten listede.")
            if len(self.watchlist) >= MAX_SYMBOLS:
                raise ValueError(
                    f"En fazla {MAX_SYMBOLS} kripto. Önce /cikar ile yer aç."
                )
            await self._validate_symbol(sym)
            self.watchlist.append(sym)
            self._save_watchlist()
            await self._sync_feed()
            log.write(f"[green3]{market.short_name(sym)} eklendi.[/]")

        elif op == "cikar":
            if len(parts) < 2:
                raise ValueError("Kullanım: /cikar SEMBOL")
            sym = market.resolve_symbol(parts[1])
            if sym not in self.watchlist:
                raise ValueError(f"{market.short_name(sym)} listede yok.")
            self.watchlist.remove(sym)
            self._save_watchlist()
            await self._sync_feed()
            log.write(f"{market.short_name(sym)} çıkarıldı.")

        elif op == "ai":
            if len(parts) < 2:
                raise ValueError("Kullanım: /ai SEMBOL  (tüm piyasa için /tara)")
            sym = market.resolve_symbol(parts[1])
            await self._validate_symbol(sym)
            self.run_ai(sym)

        elif op == "tara":
            category = parts[1].lower() if len(parts) > 1 else None
            if category and category not in SCAN_CATEGORIES:
                raise ValueError(
                    f"Geçersiz kategori: {category}. "
                    f"Seçenekler: {', '.join(sorted(SCAN_CATEGORIES))}"
                )
            self.run_scan(category)

        elif op == "onayla":
            await self._apply_suggestions(parts[1:])

        elif op == "reddet":
            n = len(self.pending)
            self.tracker.set_status(self.pending_ids, "rejected")
            self.pending.clear()
            self.pending_ids.clear()
            log.write(
                f"{n} öneri reddedildi." if n else "Bekleyen öneri yoktu."
            )

        elif op == "otonom":
            await self._cmd_otonom(parts[1:])

        elif op == "model":
            self._cmd_model(parts[1:])

        elif op == "canli":
            await self._cmd_live(parts[1:])

        elif op == "gecmis":
            self._show_history()

        elif op == "performans":
            await self._show_performance()

        elif op == "sifirla":
            self.portfolio.reset()
            self.tracker.expire_pending()
            self.tracker.save()
            self.pending.clear()
            self.pending_ids.clear()
            if self._auto_engine:
                self._auto_engine.reset_risk_lock()
            self._position_decisions.clear()
            all_prices = {s: tk.price for s, tk in self.feed.tickers.items()}
            self._daily_start_equity = self.portfolio.equity(all_prices)
            log.clear()
            if i18n.lang() == "tr":
                log.write("[bold]Hesap sıfırlandı — 10.000 USDT[/] "
                          "[grey58](öneri geçmişi /rapor için saklandı)[/]")
            else:
                log.write("[bold]Account reset — 10,000 USDT[/] "
                          "[grey58](recommendation history kept for /report)[/]")

        else:
            raise ValueError(f"Bilinmeyen komut: /{op}  (/yardim)")

    # ── otonom komut ──────────────────────────────────────────────────────────

    async def _cmd_otonom(self, args: list[str]) -> None:
        log = self.query_one("#log", RichLog)
        if not self._auto_engine:
            raise ValueError("Otonom motor henüz hazır değil.")
        sub = args[0].lower() if args else "durum"

        if sub == "ac":
            msg = await self._auto_engine.start()
            log.write(f"[bold green3]{msg}[/]")
            if self._auto_engine.enabled:
                log.write(t("otonom.started"))

        elif sub == "kapat":
            msg = await self._auto_engine.stop()
            log.write(f"[bold dark_orange]{msg}[/]")

        elif sub == "durum":
            log.write("[bold cyan]── OTONOM MOD DURUMU ──[/]")
            log.write(self._auto_engine.status_text())

        else:
            raise ValueError(
                "Kullanım: /otonom ac | /otonom kapat | /otonom durum"
            )

    # ── /durum komutu ─────────────────────────────────────────────────────────

    async def _cmd_durum(self) -> None:
        log = self.query_one("#log", RichLog)
        if not self.portfolio.positions:
            log.write("[grey58]Açık pozisyon yok. Yeni fırsat için /tara.[/]")
            return

        # Zengin pozisyon tablosu
        tbl = Table(
            title="AÇIK POZİSYONLAR", title_style="bold gold3",
            border_style="grey37", header_style="bold grey70",
        )
        for col in ("Sembol", "Giriş", "Şimdi", "K/Z", "K/Z%",
                    "Stop", "Hedef", "Stop%", "Hdf%", "R/R"):
            tbl.add_column(col)

        for sym, p in self.portfolio.positions.items():
            cur = self.feed.price(sym) or p.entry
            pnl, pct = self.portfolio.unrealized_pnl(sym, cur)
            sign = "+" if pnl >= 0 else ""
            pnl_color = "green3" if pnl >= 0 else "red3"

            stop_pct = (
                f"{(cur - p.stop)/cur*100:.1f}%"
                if p.stop else "—"
            )
            tgt_pct = (
                f"{(p.target - cur)/cur*100:.1f}%"
                if p.target else "—"
            )
            rr_val = "—"
            if p.stop and p.target:
                sr = abs(cur - p.stop)
                tg = abs(p.target - cur)
                rr_val = f"{tg/sr:.2f}" if sr > 0 else "—"

            tbl.add_row(
                Text(market.short_name(sym), style="bold"),
                fmt_price(p.entry),
                fmt_price(cur),
                Text(f"{sign}{pnl:,.2f}", style=pnl_color),
                Text(f"{sign}{pct:.2f}%", style=pnl_color),
                Text(fmt_price(p.stop), style="red3") if p.stop else Text("—", style="grey50"),
                Text(fmt_price(p.target), style="green3") if p.target else Text("—", style="grey50"),
                stop_pct,
                tgt_pct,
                rr_val,
            )
        log.write(tbl)

        # Claude analizi
        if self.ai_busy:
            log.write("[dark_orange]Claude zaten çalışıyor, bekle...[/]")
            return

        log.write("[cyan]Claude açık pozisyonları analiz ediyor...[/]")
        self.ai_busy = True
        try:
            positions_data = []
            for sym, p in self.portfolio.positions.items():
                cur = self.feed.price(sym) or p.entry
                pnl_v = (cur - p.entry) * p.qty
                stop_dist = (
                    round((cur - p.stop) / cur * 100, 2)
                    if p.stop else None
                )
                tgt_dist = (
                    round((p.target - cur) / cur * 100, 2)
                    if p.target else None
                )
                stop_risk = abs(cur - p.stop) if p.stop else 0
                tgt_gain = abs(p.target - cur) if p.target else 0
                rr = (
                    round(tgt_gain / stop_risk, 2)
                    if stop_risk > 0 else None
                )
                positions_data.append({
                    "sembol": sym,
                    "giris": p.entry,
                    "guncel": cur,
                    "kz_usdt": round(pnl_v, 2),
                    "kz_pct": round((cur / p.entry - 1) * 100, 2) if p.entry else 0,
                    "stop": p.stop,
                    "hedef": p.target,
                    "stop_uzaklik_pct": stop_dist,
                    "hedef_uzaklik_pct": tgt_dist,
                    "rr": rr,
                })

            result = await ai.analyze_positions(
                positions_data, self.portfolio.cash
            )
            summary = ai.strip_machine_lines(result)
            if summary:
                log.write(summary)

            analysis = ai.parse_status_analysis(result)
            if analysis:
                log.write("[bold gold3]── CLAUDE KARARLARI ──[/]")
                karar_colors = {
                    "DEVAM": "green3", "BEKLE": "gold3",
                    "KAR_AL": "green3", "ZARARI_KES": "red3",
                    "STOP_GUNCELLE": "dark_orange",
                }
                for pd in analysis.pozisyonlar:
                    sym = market.resolve_symbol(pd.sembol)
                    self._position_decisions[sym] = pd.karar
                    if self._auto_engine:
                        self._auto_engine.position_decisions[sym] = pd.karar
                    kcolor = karar_colors.get(pd.karar, "white")
                    urgent = "[bold red3]⚡ ACİL[/] " if pd.acil else ""
                    log.write(
                        f"  [bold]{market.short_name(sym)}[/] → "
                        f"{urgent}[{kcolor}]{pd.karar}[/]: {pd.gerekce}"
                    )
                if analysis.genel_oneri:
                    log.write(
                        f"[bold gold3]Genel:[/] {analysis.genel_oneri}"
                    )
            else:
                log.write("[grey58]Claude yapılandırılmış analiz üretemedi.[/]")

        except Exception as e:
            log.write(f"[red3]Durum analizi hatası: {e}[/]")
        finally:
            self.ai_busy = False

    # ── model / canlı ─────────────────────────────────────────────────────────

    def _cmd_model(self, args: list[str]) -> None:
        log = self.query_one("#log", RichLog)
        if not args:
            log.write(t("model.list", active=self.cfg.model))
            for key, (mid, tr, en) in MODELS.items():
                desc = tr if i18n.lang() == "tr" else en
                mark = " ◀" if key == self.cfg.model else ""
                log.write(f"  [bold]/model {key}[/] → {desc}{mark}")
            return
        key = args[0].lower()
        if key not in MODELS:
            raise ValueError(t("model.usage"))
        self.cfg.model = key
        self.cfg.save()
        log.write(t("model.changed", model=f"{key} ({self.cfg.model_id or 'CLI'})"))

    async def _cmd_live(self, args: list[str]) -> None:
        log = self.query_one("#log", RichLog)
        sub = args[0].lower() if args else ""

        if not sub:
            log.write(t("live.header"))
            log.write(
                t("live.status_on") if self.cfg.binance_key
                else t("live.status_off")
            )
            log.write(
                live.REQUIREMENTS_TR if i18n.lang() == "tr"
                else live.REQUIREMENTS_EN
            )
            log.write(t("live.warning"))
            log.write(f"[grey58]{t('live.usage')}[/]")

        elif sub == "bagla":
            if len(args) < 3:
                raise ValueError(t("live.usage"))
            key, secret = args[1], args[2]
            log.write(t("live.validating"))
            try:
                await live.validate_keys(key, secret)
            except live.LiveError as e:
                log.write(t("live.failed", err=e))
                return
            self.cfg.binance_key = key
            self.cfg.binance_secret = secret
            self.cfg.save()
            log.write(t("live.connected"))
            log.write(t("live.warning"))
            # Layer 5: Performance threshold check
            prices = await self._tracker_prices()
            stats = self.tracker.stats(prices)
            total = stats.get("onaylanan", 0)
            win_rate = stats.get("basari_orani")
            if total < 10:
                log.write(
                    f"[dark_orange]⚠ Öneri: Gerçek paraya geçmeden önce en az 10 onaylanan işlem "
                    f"önerilir. Şu an: {total}[/]"
                )
            elif win_rate is not None and win_rate < 45:
                log.write(
                    f"[dark_orange]⚠ Uyarı: Paper başarı oranı %{win_rate:.0f} — "
                    f"gerçek paraya geçmek için %50+ önerilir.[/]"
                )

        elif sub == "bakiye":
            if not self.cfg.binance_key:
                raise ValueError(t("live.no_keys"))
            log.write(t("live.validating"))
            try:
                balances = await live.fetch_balances(
                    self.cfg.binance_key, self.cfg.binance_secret
                )
            except live.LiveError as e:
                log.write(t("live.failed", err=e))
                return
            log.write(t("live.balances"))
            if not balances:
                log.write("  [grey58]0[/]")
            for b in balances[:15]:
                log.write(
                    f"  [bold]{b['asset']:<8}[/] {b['free']:,.8f}"
                    + (
                        f"  [grey58](kilitli: {b['locked']:,.8f})[/]"
                        if b["locked"] else ""
                    )
                )

        elif sub == "kes":
            self.cfg.binance_key = ""
            self.cfg.binance_secret = ""
            self.cfg.save()
            log.write(t("live.disconnected"))

        else:
            raise ValueError(t("live.usage"))

    # ── fiyat / sembol yardımcıları ──────────────────────────────────────────

    async def _price_of(self, symbol: str) -> float:
        p = self.feed.price(symbol)
        if p:
            return p
        return await market.quote(symbol)

    async def _validate_symbol(self, symbol: str) -> None:
        try:
            await market.quote(symbol)
        except Exception:
            raise ValueError(f"{symbol} bulunamadı.")

    # ── Claude işçileri ───────────────────────────────────────────────────────

    @work(exclusive=True)
    async def run_ai(self, symbol: str) -> None:
        """Tek sembol analizi (/ai SEMBOL)."""
        log = self.query_one("#log", RichLog)
        if self.ai_busy:
            log.write("[dark_orange]Claude zaten çalışıyor, bekle...[/]")
            return
        self.ai_busy = True
        try:
            positions = {
                s: {
                    "miktar": p.qty, "giris": p.entry,
                    "guncel_deger_usdt": round(
                        p.qty * (self.feed.price(s) or p.entry), 2
                    ),
                    "zarar_kes": p.stop, "kar_al": p.target,
                }
                for s, p in self.portfolio.positions.items()
            }
            log.write(
                f"[bold cyan]── Claude {market.short_name(symbol)} "
                f"analiz ediyor... ──[/]"
            )
            full = await ai.analyze_symbol(
                symbol, self.portfolio.cash, positions
            )
            summary = ai.strip_machine_lines(full)
            if summary:
                log.write(summary)

            self.pending = ai.parse_suggestions(full)
            if not self.pending:
                self.pending_ids = []
                log.write(
                    "[grey58]Claude net bir işlem önermedi (BEKLE). "
                    "Sermayen korunuyor.[/]"
                )
                return

            await self._record_pending_suggestions()
            log.write(
                "[bold]Seçim: /onayla 1   hepsi: /onayla hepsi   "
                "vazgeç: /reddet[/]"
            )
        except Exception as e:
            log.write(f"[red3]Claude hatası: {e}[/]")
        finally:
            self.ai_busy = False

    @work(exclusive=True)
    async def run_scan(self, category: str | None) -> None:
        """Piyasa taraması (/tara [kategori])."""
        log = self.query_one("#log", RichLog)
        if self.ai_busy:
            log.write("[dark_orange]Claude zaten çalışıyor, bekle...[/]")
            return
        self.ai_busy = True
        try:
            positions = {
                s: {
                    "miktar": p.qty, "giris": p.entry,
                    "stop": p.stop, "hedef": p.target,
                }
                for s, p in self.portfolio.positions.items()
            }
            cat_label = (
                f" ({category})" if category else " (kripto + emtia/forex/endeks)"
            )
            log.write(
                f"[bold cyan]── Claude piyasayı tarıyor{cat_label}... ──[/]"
            )
            trade_plan = getattr(self.cfg, "trade_plan", "dengeli")
            lev_enabled = getattr(self.cfg, "leverage_enabled", False)
            full = await ai.scan_market_filtered(
                list(self.watchlist), self.portfolio.cash, positions, category,
                leverage_enabled=lev_enabled,
                trade_plan=trade_plan,
            )
            summary = ai.strip_machine_lines(full)
            if summary:
                log.write(summary)

            self.pending = ai.parse_suggestions(full)
            # Kabul edilen işlem tipleri — plan'a göre filtrele
            _ALLOWED = {"AL", "SPOT_AL"}
            if trade_plan in ("dengeli", "tam"):
                _ALLOWED |= {"SHORT_AL", "SCALP_AL"}
            if trade_plan == "tam" and lev_enabled:
                _ALLOWED.add("LEVERAGE_AL")
            self.pending = [s for s in self.pending if s.islem in _ALLOWED]

            if not self.pending:
                self.pending_ids = []
                log.write(
                    "[grey58]Claude net bir fırsat bulamadı (BEKLE). "
                    "Sermayen korunuyor.[/]"
                )
                return

            await self._record_pending_suggestions()

            hist_prices = await self._tracker_prices()
            rate, n = self.tracker.win_rate(hist_prices)

            log.write("[bold gold3]── İŞLEM ADAYLARI ──[/]")
            _TYPE_STYLE = {
                "AL": ("[green3]AL[/]", "green3"),
                "SPOT_AL": ("[green3]AL[/]", "green3"),
                "SHORT_AL": ("[red3]SHORT[/]", "red3"),
                "SCALP_AL": ("[cyan]SCALP[/]", "cyan"),
                "LEVERAGE_AL": ("[bold gold3]LEV[/]", "gold3"),
            }
            for i, s in enumerate(self.pending, 1):
                cal = self.tracker.calibrate(s.basari_yuzdesi, hist_prices)
                note = (
                    f" [grey58](Claude: %{s.basari_yuzdesi})[/]"
                    if cal != s.basari_yuzdesi else ""
                )
                bar = self._success_bar(cal)
                type_lbl, type_color = _TYPE_STYLE.get(s.islem, ("[white]AL[/]", "white"))
                log.write(
                    f"[bold]{i})[/] {type_lbl} "
                    f"[bold]{market.short_name(market.resolve_symbol(s.sembol))}[/] — "
                    f"{s.tutar_usdt:,.0f} USDT — başarı {bar} %{cal}{note}"
                )
                if s.zarar_kes or s.kar_al:
                    log.write(
                        f"     [red3]stop {fmt_price(s.zarar_kes)}[/] / "
                        f"[green3]hedef {fmt_price(s.kar_al)}[/] — otomatik kapanır"
                    )
                log.write(f"     [grey58]{s.gerekce}[/]")
            if rate is not None and n >= 5:
                log.write(
                    f"[grey58]Kalibrasyon: Claude'un geçmiş {n} önerisinde "
                    f"isabet %{rate:.0f} — yüzdeler buna göre düşürüldü.[/]"
                )
            log.write(
                "[bold]Seçim: /onayla 1 3   hepsi: /onayla hepsi   "
                "vazgeç: /reddet[/]"
            )
        except Exception as e:
            log.write(f"[red3]Claude hatası: {e}[/]")
        finally:
            self.ai_busy = False

    async def _record_pending_suggestions(self) -> None:
        """Pending önerileri tracker'a kaydet."""
        items = []
        for s in self.pending:
            sym = market.resolve_symbol(s.sembol)
            try:
                entry = await self._price_of(sym)
            except Exception:
                entry = 0.0
            items.append({
                "symbol": sym,
                "side": s.islem,
                "suggested_amount": s.tutar_usdt,
                "confidence_percent": s.basari_yuzdesi,
                "reason": s.gerekce,
                "entry_price": entry,
            })
        recs = self.tracker.add(items)
        self.pending_ids = [r.id for r in recs]

    # ── zarar-kes / kâr-al ────────────────────────────────────────────────────

    def check_protections(self) -> None:
        try:
            prices = {s: tk.price for s, tk in self.feed.tickers.items()
                      if tk.price > 0}
            triggers = self.portfolio.check_triggers(prices)
            if not triggers:
                return
            log = self.query_one("#log", RichLog)
            for sym, kind, price in triggers:
                result = self.portfolio.sell(sym, price)
                if kind == "stop":
                    log.write(
                        f"[bold white on red3] ZARAR KESİLDİ [/] "
                        f"[red3]{market.short_name(sym)} stop seviyesinden kapatıldı.[/]"
                    )
                    log.write(f"   {result}")
                    self.notify(f"✕ {market.short_name(sym)}: ZARAR KESİLDİ", severity="warning", timeout=6)
                else:
                    log.write(
                        f"[bold black on green3] KÂR ALINDI [/] "
                        f"[green3]{market.short_name(sym)} hedef seviyesinden kapatıldı.[/]"
                    )
                    log.write(f"   {result}")
                    self.notify(f"✔ {market.short_name(sym)}: KÂR ALINDI", severity="information", timeout=5)
            self.run_worker(self._sync_feed(), exclusive=False)
        except Exception as e:
            try:
                self.query_one("#log", RichLog).write(f"[red3][hata] check_protections: {e}[/]")
            except Exception:
                pass

    @work(exclusive=True, group="protect")
    async def run_protect(self, symbol: str) -> None:
        log = self.query_one("#log", RichLog)
        pos = self.portfolio.positions.get(symbol)
        if not pos:
            return
        log.write(
            f"[cyan]Claude {market.short_name(symbol)} için koruma "
            f"seviyeleri belirliyor...[/]"
        )
        try:
            full = await ai.protect_position(
                symbol, pos.entry, pos.qty, self.portfolio.cash
            )
            prot = ai.parse_protection(full)
            if not prot:
                log.write(
                    "[red3]Koruma seviyesi alınamadı; /koru ile tekrar dene.[/]"
                )
                return
            stop, target = sanitize_levels(pos.entry, prot.zarar_kes, prot.kar_al)
            if symbol not in self.portfolio.positions:
                return
            self.portfolio.set_protection(symbol, stop, target)
            log.write(
                f"[bold]{market.short_name(symbol)} koruması:[/] "
                f"[red3]stop {fmt_price(stop)}[/] / "
                f"[green3]hedef {fmt_price(target)}[/] — otomatik kapanır"
            )
            if prot.gerekce:
                log.write(f"   [grey58]{prot.gerekce}[/]")
        except Exception as e:
            log.write(f"[red3]Koruma hatası: {e}[/]")

    @staticmethod
    def _success_bar(pct: int) -> str:
        filled = round(pct / 10)
        color = "green3" if pct >= 60 else ("gold3" if pct >= 45 else "red3")
        return f"[{color}]{'█' * filled}{'░' * (10 - filled)}[/]"

    async def _apply_suggestions(self, args: list[str]) -> None:
        log = self.query_one("#log", RichLog)
        if not self.pending:
            raise ValueError("Bekleyen öneri yok. Önce /tara veya /ai çalıştır.")

        if args and args[0].lower() in ("hepsi", "tum", "tüm", "all"):
            picks = list(range(1, len(self.pending) + 1))
        elif args:
            try:
                picks = sorted({int(a) for a in args})
            except ValueError:
                raise ValueError("Kullanım: /onayla 1 3  veya  /onayla hepsi")
            bad = [n for n in picks if not 1 <= n <= len(self.pending)]
            if bad:
                raise ValueError(
                    f"Geçersiz numara: {bad}. 1-{len(self.pending)} arası seç."
                )
        elif len(self.pending) == 1:
            picks = [1]
        else:
            raise ValueError(
                f"{len(self.pending)} aday var — numara ver: /onayla 1 3"
            )

        mode = modes.get(self.cfg.mode)
        pickset = set(picks)
        applied_ids: list[str] = []
        for n in picks:
            s = self.pending[n - 1]
            rec_id = (
                self.pending_ids[n - 1]
                if n - 1 < len(self.pending_ids) else None
            )
            sym = market.resolve_symbol(s.sembol)
            price = await self._price_of(sym)
            if s.islem in ("AL", "SPOT_AL"):
                cap = self.portfolio.cash * mode.max_trade_cash_ratio
                usdt = min(s.tutar_usdt, cap)
                if usdt < s.tutar_usdt:
                    log.write(
                        f"[dark_orange]Risk freni: {s.tutar_usdt:,.0f} → "
                        f"{usdt:,.0f} USDT'ye düşürüldü.[/]"
                    )
                if usdt < 1:
                    log.write(f"[red3]{market.short_name(sym)}: yeterli nakit yok, atlandı.[/]")
                    continue
                style = getattr(s, "trade_style", "spot") or "spot"
                stop, target = sanitize_levels(price, s.zarar_kes, s.kar_al)
                log.write(f"[green3]{self.portfolio.buy(sym, usdt, price, trade_style=style, stop=stop, target=target)}[/]")
                log.write(
                    f"[grey58]   Koruma: stop {fmt_price(stop)} / "
                    f"hedef {fmt_price(target)}[/]"
                )
            elif s.islem == "SHORT_AL":
                cap = self.portfolio.cash * mode.max_trade_cash_ratio
                usdt = min(s.tutar_usdt, cap)
                if usdt < 1:
                    log.write(f"[red3]{market.short_name(sym)}: yeterli nakit yok, atlandı.[/]")
                    continue
                allowed, reason = market.trade_allowed(sym)
                if not allowed:
                    log.write(f"[red3]SHORT engellendi: {reason}[/]")
                    continue
                log.write(f"[red3]{self.portfolio.buy_short(sym, usdt, price, s.zarar_kes or price*1.03, s.kar_al or price*0.95)}[/]")
            elif s.islem == "SCALP_AL":
                cap = self.portfolio.cash * mode.max_trade_cash_ratio
                usdt = min(s.tutar_usdt, cap)
                if usdt < 1:
                    log.write(f"[red3]{market.short_name(sym)}: yeterli nakit yok, atlandı.[/]")
                    continue
                allowed, reason = market.trade_allowed(sym)
                if not allowed:
                    log.write(f"[red3]SCALP engellendi: {reason}[/]")
                    continue
                stop, target = s.zarar_kes or price*0.99, s.kar_al or price*1.015
                log.write(f"[cyan]{self.portfolio.buy(sym, usdt, price, trade_style='scalp', stop=stop, target=target)}[/]")
                log.write(f"[grey58]   Scalp: max 30dk, stop {fmt_price(stop)} / hedef {fmt_price(target)}[/]")
            elif s.islem == "LEVERAGE_AL":
                cap = self.portfolio.cash * mode.max_trade_cash_ratio
                usdt = min(s.tutar_usdt, cap)
                lev = getattr(s, "leverage", 2) or 2
                if usdt < 1:
                    log.write(f"[red3]{market.short_name(sym)}: yeterli nakit yok, atlandı.[/]")
                    continue
                log.write(f"[gold3]{self.portfolio.buy_leveraged(sym, usdt, lev, price, s.zarar_kes or price*0.95, s.kar_al or price*1.10)}[/]")
            else:
                usdt = s.tutar_usdt if s.tutar_usdt > 0 else None
                log.write(f"[dark_orange]{self.portfolio.sell(sym, price, usdt)}[/]")
            if rec_id:
                applied_ids.append(rec_id)
        self.tracker.set_status(applied_ids, "approved")
        self.pending = [
            s for i, s in enumerate(self.pending, 1)
            if i not in pickset
        ]
        self.pending_ids = [
            r for i, r in enumerate(self.pending_ids, 1)
            if i not in pickset
        ]
        await self._sync_feed()
        if self.pending:
            log.write(
                f"[grey58]{len(self.pending)} aday hâlâ bekliyor "
                f"(/onayla N veya /reddet).[/]"
            )

    # ── performans ────────────────────────────────────────────────────────────

    async def _tracker_prices(self) -> dict[str, float]:
        prices: dict[str, float] = {}
        for sym in self.tracker.symbols()[:20]:
            try:
                prices[sym] = await self._price_of(sym)
            except Exception:
                pass
        return prices

    async def _show_performance(self) -> None:
        log = self.query_one("#log", RichLog)
        if not self.tracker.recs:
            log.write("Henüz kayıtlı öneri yok. Önce /tara çalıştır.")
            return
        log.write("[grey58]Fiyatlar çekiliyor...[/]")
        prices = await self._tracker_prices()
        st = self.tracker.stats(prices)

        table = Table(
            title="CLAUDE PERFORMANS KARNESİ", title_style="bold gold3",
            show_header=False, border_style="grey37",
        )
        table.add_column(style="bold")
        table.add_column(justify="right")
        table.add_row("Toplam öneri", str(st["toplam_oneri"]))
        table.add_row("Onaylanan işlem", str(st["onaylanan"]))
        table.add_row("Reddedilen", str(st["reddedilen"]))
        table.add_row("Süresi dolan", str(st["suresi_dolan"]))
        table.add_row("Bekleyen", str(st["bekleyen"]))
        table.add_row("Kazanan işlem", Text(str(st["kazanan"]), style="green3"))
        table.add_row("Kaybeden işlem", Text(str(st["kaybeden"]), style="red3"))
        pnl = st["toplam_pnl"]
        pnl_style = "green3" if pnl >= 0 else "red3"
        table.add_row(
            "Toplam sanal PnL",
            Text(f"{'+' if pnl >= 0 else ''}{pnl:,.2f} USDT", style=pnl_style),
        )
        if st["basari_orani"] is not None:
            rate = st["basari_orani"]
            rate_style = "green3" if rate >= 50 else "red3"
            table.add_row(
                "Claude başarı oranı", Text(f"%{rate:.0f}", style=rate_style)
            )
        else:
            table.add_row("Claude başarı oranı", "henüz veri yok")
        log.write(table)
        log.write(
            "[grey58]Not: kazanan/kaybeden, onaylanan önerilerin güncel fiyata "
            "göre yön isabetidir (sanal).[/]"
        )

    def _show_history(self) -> None:
        log = self.query_one("#log", RichLog)
        trades = Table(
            title="SON 10 İŞLEM", title_style="bold gold3",
            border_style="grey37", header_style="bold grey70",
        )
        for col in ("Zaman", "Yön", "Enstrüman", "Miktar", "Fiyat", "K/Z"):
            trades.add_column(col)
        if not self.portfolio.history:
            trades.add_row("-", "-", "-", "-", "-", "-")
        for h in self.portfolio.history[-10:]:
            pnl = h.get("pnl")
            pnl_txt = Text("-") if pnl is None else Text(
                f"{pnl:+,.2f}", style="green3" if pnl >= 0 else "red3"
            )
            trades.add_row(
                datetime.fromtimestamp(h["ts"]).strftime("%d.%m %H:%M"),
                Text(h["side"],
                     style="green3" if h["side"] == "AL" else "dark_orange"),
                market.short_name(h["symbol"]),
                f"{h['qty']:.6f}",
                fmt_price(h["price"]),
                pnl_txt,
            )
        log.write(trades)

        recs = Table(
            title="SON 10 ÖNERİ", title_style="bold gold3",
            border_style="grey37", header_style="bold grey70",
        )
        for col in ("Zaman", "Yön", "Enstrüman", "Tutar", "Güven", "Giriş", "Durum"):
            recs.add_column(col)
        if not self.tracker.recs:
            recs.add_row("-", "-", "-", "-", "-", "-", "-")
        for r in self.tracker.recs[-10:]:
            status_style = {
                "approved": "green3", "rejected": "red3",
                "expired": "grey58", "pending": "gold3",
            }[r.status]
            recs.add_row(
                datetime.fromtimestamp(r.timestamp).strftime("%d.%m %H:%M"),
                Text(r.side,
                     style="green3" if r.side == "AL" else "dark_orange"),
                market.short_name(r.symbol),
                f"{r.suggested_amount:,.0f}",
                f"%{r.confidence_percent}",
                fmt_price(r.entry_price) if r.entry_price else "-",
                Text(STATUS_TR[r.status], style=status_style),
            )
        log.write(recs)

    # ── watchlist kalıcılığı ──────────────────────────────────────────────────

    def _load_watchlist(self) -> list[str]:
        if WATCHLIST_FILE.exists():
            wl = json.loads(WATCHLIST_FILE.read_text())[:MAX_SYMBOLS]
            if wl in OLD_DEFAULTS:
                return list(DEFAULT_WATCHLIST)
            wl = [s for s in wl if not market.is_yahoo(s)]
            return wl or list(DEFAULT_WATCHLIST)
        return list(DEFAULT_WATCHLIST)

    def _save_watchlist(self) -> None:
        WATCHLIST_FILE.write_text(json.dumps(self.watchlist))


if __name__ == "__main__":
    TradeApp().run()
