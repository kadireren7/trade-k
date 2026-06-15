"""trade-k — Claude destekli trading terminali (paper & live).

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
import exchange
import notify
import market
import indicators
import backtest as backtest_mod
import strategies as strategies_mod
import risk as risk_mod
import orders as orders_mod
import performance as perf_mod
import modes
from autonomous import AutonomousEngine
from config import MODELS, Config
from i18n import t
from portfolio import Portfolio, sanitize_levels
from screens import LoginScreen, SetupScreen, SplashMenuScreen
from tracker import STATUS_TR, Tracker

WATCHLIST_FILE = Path(__file__).parent / "watchlist.json"
DEFAULT_WATCHLIST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
    "BNBUSDT", "ADAUSDT", "AVAXUSDT", "DOTUSDT", "MATICUSDT",
    "LINKUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT", "NEARUSDT",
    "FILUSDT", "INJUSDT", "SUIUSDT", "ARBUSDT", "OPUSDT",
]
OLD_DEFAULTS = [
    ["BTCUSDT", "ETHUSDT", "SOLUSDT", "PAXGUSDT", "XRPUSDT"],
    ["BTCUSDT", "ETHUSDT", "GC=F", "USDTRY=X", "^GSPC"],
]
MAX_SYMBOLS = 20

SCAN_CATEGORIES = {"kripto", "global", "forex", "emtia", "endeks"}
SCAN_DIRECTIONS = {"long", "short", "yukselis", "scalp", "hizli", "day", "swing"}


def fmt_price(p: float) -> str:
    if p >= 1000:
        return f"{p:,.2f}"
    if p >= 1:
        return f"{p:,.4f}"
    return f"{p:.6f}"


class AccountBar(Static):
    """Üst bar: mod, borsa, AI, otonom durum."""

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
        auto_mode_name: str = "",
        auto_max_daily: int = 3,
        trading_mode: str = "paper",
        exchange_name: str = "binance",
        ai_provider: str = "claude",
        open_pnl: float = 0.0,
    ) -> None:
        txt = Text()

        # Logo
        txt.append(" trade-k ", style="bold black on gold3")
        txt.append(" ", style="")

        # İşlem modu
        if trading_mode == "live":
            txt.append(" GERÇEK ", style="bold black on green3")
        else:
            txt.append(" PAPER  ", style="bold black on dark_orange")
        txt.append(" ", style="")

        # Borsa + bağlantı
        ex_upper = exchange_name.upper()
        if not ws_connected:
            txt.append(f" {ex_upper}·YOK ", style="bold white on grey23")
            txt.append(" WS↯ ", style="bold red3 on #2d0a0a")
        elif live_ok:
            txt.append(f" {ex_upper}·BAĞLI ", style="bold black on cyan")
        else:
            txt.append(f" {ex_upper}·WS ", style="bold black on cyan")
        txt.append(" ", style="")

        # AI sağlayıcısı
        txt.append(f" {ai_provider.upper()} ", style="bold black on dark_violet")
        txt.append("  ", style="")

        # Otonom durum
        if auto_enabled:
            lbl = f"AUTO·{auto_mode_name.upper()}" if auto_mode_name else "AUTO"
            txt.append(f" {lbl} ", style="bold black on green3")
            txt.append(f" {auto_daily_trades}/{auto_max_daily} işlem ", style="grey58")
        if auto_risk_locked:
            txt.append(" ⚠KİLİT ", style="bold white on red3")

        # Hızlı bakiye özeti (sağa yaslanmış)
        txt.append("│ ", style="grey37")
        total_pnl = equity - start
        total_pct = total_pnl / start * 100 if start else 0
        pnl_c = "green3" if total_pnl >= 0 else "red3"
        ps = "+" if total_pnl >= 0 else ""
        txt.append(f"Nakit:{cash:,.2f}  Varlık:{equity:,.2f}  ", style="bold white")
        txt.append(f"ToplamK/Z:{ps}{total_pnl:,.2f} ({ps}{total_pct:.1f}%)", style=f"bold {pnl_c}")
        txt.append(f"  · {name}", style="grey50")
        self.update(txt)


class AccountPanel(Static):
    """Sağ panelde anlık hesap detay kartı — 0.5sn güncellenir."""

    def update_financials(
        self,
        cash: float,
        equity: float,
        start: float,
        open_pnl: float,
        daily_pnl: float,
        pos_count: int,
        auto_enabled: bool,
        auto_mode_name: str,
        auto_trades: int,
        auto_max: int,
        auto_risk_locked: bool,
        trade_plan: str,
        ws_connected: bool,
        trading_mode: str,
        ai_provider: str,
        name: str,
    ) -> None:
        total_pnl = equity - start
        total_pct = total_pnl / start * 100 if start else 0

        def gc(v: float) -> str:
            return "green3" if v >= 0 else "red3"

        def gs(v: float) -> str:
            return "+" if v >= 0 else ""

        tbl = Table(
            box=None, padding=(0, 1), show_header=False,
            expand=True, show_edge=False,
        )
        tbl.add_column("label", style="grey58", min_width=11, no_wrap=True)
        tbl.add_column("value", justify="right", min_width=20)

        # Nakit
        tbl.add_row("Nakit", Text(f"{cash:,.2f} USDT", style="bold white"))

        # Varlık + toplam %
        eq_txt = Text()
        eq_txt.append(f"{equity:,.2f} USDT", style="bold white")
        eq_txt.append(f"  {gs(total_pnl)}{total_pct:.2f}%", style=f"bold {gc(total_pnl)}")
        tbl.add_row("Varlık", eq_txt)

        # Açık K/Z
        tbl.add_row(
            "Açık K/Z",
            Text(
                f"{gs(open_pnl)}{open_pnl:,.2f} USDT",
                style=f"bold {gc(open_pnl)}" if open_pnl != 0 else "grey50",
            ),
        )

        # Gün K/Z
        tbl.add_row(
            "Gün K/Z",
            Text(f"{gs(daily_pnl)}{daily_pnl:,.2f} USDT", style=f"bold {gc(daily_pnl)}"),
        )

        # Toplam K/Z
        tbl.add_row(
            "Toplam K/Z",
            Text(
                f"{gs(total_pnl)}{total_pnl:,.2f} USDT",
                style=f"bold {gc(total_pnl)}",
            ),
        )

        # Pozisyon sayısı
        tbl.add_row(
            "Pozisyon",
            Text(
                f"{pos_count} açık pozisyon",
                style="bold white" if pos_count else "grey50",
            ),
        )

        # Otonom satırı
        if auto_enabled:
            plan_labels = {"sadece_long": "LONG", "dengeli": "L+S", "tam": "TAM"}
            plan_str = plan_labels.get(trade_plan, trade_plan.upper())
            auto_txt = Text()
            auto_txt.append("● AÇIK", style="bold green3")
            auto_txt.append(f"  {auto_mode_name.upper()} / {plan_str}", style="cyan")
            auto_txt.append(f"  {auto_trades}/{auto_max}", style="grey58")
            if auto_risk_locked:
                auto_txt.append("  ⚠KİLİT", style="bold red3")
        else:
            auto_txt = Text("● KAPALI", style="grey50")
        tbl.add_row("Otonom", auto_txt)

        # WS + mod satırı
        status_txt = Text()
        if ws_connected:
            status_txt.append("● WS  ", style="bold green3")
        else:
            status_txt.append("● WS↯  ", style="bold red3")
        if trading_mode == "live":
            status_txt.append("GERÇEK  ", style="bold green3")
        else:
            status_txt.append("PAPER  ", style="bold dark_orange")
        status_txt.append(ai_provider.upper(), style="dark_violet")
        tbl.add_row("Sistem", status_txt)

        self.update(tbl)


class CommandInput(Input):
    """Input subclass — palette navigation keylerini yakalar."""

    async def _on_key(self, event: events.Key) -> None:
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
        # Input boşken q veya escape → menüye dön
        if event.key in ("q", "escape") and not self.value:
            app.action_open_menu()
            event.prevent_default()
            event.stop()
            return
        await super()._on_key(event)


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
        # /uygula için tam PositionDecision nesneleri
        self._pending_position_decisions: dict[str, ai.PositionDecision] = {}
        # Günlük başlangıç varlığı (günlük PnL hesabı için)
        self._daily_start_equity: float = 0.0
        self._daily_date: str = ""
        # Komut paleti
        self._palette_items: list = []
        self._palette_cursor: int = 0
        self._palette_visible: bool = False
        self._main_started: bool = False
        # Fiyat alarmları: sym → [(direction, target_price, action, amount), ...]
        # direction: "asagi" | "yukari"  action: "al" | "sat" | "bildir"
        self._price_alerts: dict[str, list[tuple]] = {}
        # Limit emir defteri (paper modda)
        self._order_book = orders_mod.book()

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
                yield Static("💰 HESAP", id="title-account", classes="paneltitle")
                yield AccountPanel(id="acc-panel")
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
        # Telegram bildirimcisini yapılandır
        if self.cfg:
            notify.configure(
                getattr(self.cfg, "telegram_token", ""),
                getattr(self.cfg, "telegram_chat_id", ""),
            )
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
            pos.add_columns("Instrument", "Dir", "Entry", "Now", "P/L USDT", "P/L %",
                            "Stop", "Target", "Duration", "Decision")
        else:
            pos.add_columns("Enstrüman", "Yön", "Giriş", "Şimdi", "K/Z USDT", "K/Z %",
                            "Stop", "Hedef", "Süre", "Karar")

        # Live mod başlangıç bakiye sync
        if self.cfg and getattr(self.cfg, "trading_mode", "paper") == "live":
            try:
                _k, _s, _p = self._exchange_creds()
                if _k:
                    real_usdt = await exchange.get_usdt_balance(_k, _s, _p)
                    self.portfolio.cash = real_usdt
            except Exception:
                pass

        # Otonom motoru başlat
        live_buy = None
        live_sell = None
        if self.cfg and getattr(self.cfg, "trading_mode", "paper") == "live":
            _k, _s, _p = self._exchange_creds()
            if _k:
                live_buy = lambda s, u: exchange.place_market_buy(_k, _s, s, u, _p)
                live_sell = lambda s, q: exchange.place_market_sell(_k, _s, s, q, _p)

        self._auto_engine = AutonomousEngine(
            portfolio=self.portfolio,
            feed=self.feed,
            tracker=self.tracker,
            cfg=self.cfg,
            log_fn=lambda msg: self.query_one("#log", RichLog).write(msg),
            watchlist_fn=lambda: list(self.watchlist),
            sync_feed_fn=self._sync_feed_bg,
            live_buy_fn=live_buy,
            live_sell_fn=live_sell,
        )
        self._position_decisions = self._auto_engine.position_decisions

        # Günlük başlangıç varlığını ayarla
        self._daily_date = datetime.now().strftime("%Y-%m-%d")
        all_prices = {s: tk.price for s, tk in self.feed.tickers.items()}
        self._daily_start_equity = self.portfolio.equity(all_prices) or 10_000.0

        log = self.query_one("#log", RichLog)

        # Telegram komut botunu başlat (token varsa)
        notify.get_bot().start(
            portfolio=self.portfolio,
            engine=self._auto_engine,
            cfg=self.cfg,
            feed=self.feed,
            log_fn=log.write,
        )
        if first_run:
            log.write(t("setup.done", name=self.cfg.name))
        log.write(t("app.started", name=self.cfg.name))
        log.write(t("app.mode_model", model=self.cfg.model))
        log.write(t("app.hint"))
        await self.feed.start()
        self.set_interval(0.5, self.refresh_tables)
        self.set_interval(2.0, self.check_protections)
        self.set_interval(5.0, self._poll_web_flags)
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
            for sym in self.watchlist:
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

                # Yön etiketi: SHORT/LONG/SCALP/LEV
                if p.is_leveraged:
                    yon_txt = Text(f"LEV{p.leverage}x", style="bold gold3")
                elif p.direction == "short":
                    yon_txt = Text("SHORT", style="bold red3")
                elif p.trade_style == "scalp":
                    yon_txt = Text("SCALP", style="bold cyan")
                else:
                    yon_txt = Text("LONG", style="bold green3")

                pos_table.add_row(
                    Text(market.short_name(sym), style="bold"),
                    yon_txt,
                    fmt_price(p.entry),
                    fmt_price(cur),
                    Text(f"{sign}{pnl:,.2f}", style=color),
                    Text(f"{sign}{pct:.2f}%", style=color),
                    Text(fmt_price(p.stop), style="red3") if p.stop
                    else Text("—", style="grey50"),
                    Text(fmt_price(p.target), style="green3") if p.target
                    else Text("—", style="grey50"),
                    dur_txt,
                    karar_txt,
                )

            # Özet satırı — pozisyon varsa TOPLAM K/Z + nakit göster
            if self.portfolio.positions:
                total_upnl = sum(
                    self.portfolio.unrealized_pnl(s, self.feed.price(s) or self.portfolio.positions[s].entry)[0]
                    for s in self.portfolio.positions
                )
                cash_now = self.portfolio.cash
                tc = "green3" if total_upnl >= 0 else "red3"
                ts = "+" if total_upnl >= 0 else ""
                pos_table.add_row(
                    Text("── TOPLAM ──", style="bold grey50"),
                    "", "",
                    Text(f"{ts}{total_upnl:,.2f}", style=f"bold {tc}"),
                    "",
                    "", "", "",
                    Text(f"Nakit:{cash_now:,.2f}", style="grey58"),
                )

            # Bakiye hesaplamaları
            all_prices = {s: tk.price for s, tk in self.feed.tickers.items()}
            cur_equity = self.portfolio.equity(all_prices)

            # Açık pozisyon toplam K/Z
            open_pnl = sum(
                self.portfolio.unrealized_pnl(sym, self.feed.price(sym) or p.entry)[0]
                for sym, p in self.portfolio.positions.items()
            )

            today = datetime.now().strftime("%Y-%m-%d")
            if today != self._daily_date:
                self._daily_date = today
                self._daily_start_equity = cur_equity

            daily_pnl = cur_equity - self._daily_start_equity

            auto_enabled = bool(self._auto_engine and self._auto_engine.enabled)
            auto_trades = self._auto_engine.daily_trades if self._auto_engine else 0
            auto_locked = bool(self._auto_engine and self._auto_engine.risk_locked)
            auto_mode_name = self._auto_engine.profile.name if self._auto_engine else ""
            auto_max_daily = (
                self._auto_engine.effective_profile.max_daily_trades
                if self._auto_engine else 3
            )

            _ex_name = getattr(self.cfg, "exchange", "binance") if self.cfg else "binance"
            _ai_prov = getattr(self.cfg, "ai_provider", "claude") if self.cfg else "claude"
            _trading_mode = getattr(self.cfg, "trading_mode", "paper") if self.cfg else "paper"
            _trade_plan = getattr(self.cfg, "trade_plan", "dengeli") if self.cfg else "dengeli"
            _ws_ok = self.feed.ws_connected if self.feed.crypto_symbols else True
            _k, _, _ = self._exchange_creds()
            _name = self.cfg.name if self.cfg else ""

            self.query_one("#account", AccountBar).update_view(
                equity=cur_equity,
                cash=self.portfolio.cash,
                start=self._daily_start_equity or cur_equity,
                live_ok=bool(_k),
                name=_name,
                auto_enabled=auto_enabled,
                auto_daily_trades=auto_trades,
                auto_risk_locked=auto_locked,
                open_positions=len(self.portfolio.positions),
                daily_pnl=daily_pnl,
                ws_connected=_ws_ok,
                auto_mode_name=auto_mode_name,
                auto_max_daily=auto_max_daily,
                trading_mode=_trading_mode,
                exchange_name=_ex_name,
                ai_provider=_ai_prov,
                open_pnl=open_pnl,
            )

            # AccountPanel — anlık hesap detay kartı
            self.query_one("#acc-panel", AccountPanel).update_financials(
                cash=self.portfolio.cash,
                equity=cur_equity,
                start=self._daily_start_equity or cur_equity,
                open_pnl=open_pnl,
                daily_pnl=daily_pnl,
                pos_count=len(self.portfolio.positions),
                auto_enabled=auto_enabled,
                auto_mode_name=auto_mode_name,
                auto_trades=auto_trades,
                auto_max=auto_max_daily,
                auto_risk_locked=auto_locked,
                trade_plan=_trade_plan,
                ws_connected=_ws_ok,
                trading_mode=_trading_mode,
                ai_provider=_ai_prov,
                name=_name,
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
        _lc = cmd.lower()
        shown = (
            "/canli bagla ********"
            if _lc.startswith("/canli bagla")
            else "/model key *** ********"
            if _lc.startswith("/model key")
            else "/bildirim bagla *** ***"
            if _lc.startswith("/bildirim bagla") or _lc.startswith("/notify bagla")
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
            "performance": "performans",
            "reset": "sifirla", "apply": "uygula", "history": "gecmis",
            "details": "detay", "leverage": "kaldirac",
            "price": "fiyat", "alarm": "fiyat", "alert": "fiyat",
            "teknik": "ta", "indicator": "ta", "indikatör": "ta",
            "bt": "backtest", "test": "backtest",
            "size": "boyut", "pozisyon": "boyut",
            "multitf": "mtf", "cok-zaman": "mtf",
            "strategy": "strateji", "mod": "strateji",
            "heat": "risk", "isi": "risk",
            "lmt": "limit",
            "exit": "cikis", "quit": "cikis", "q": "cikis",
            "balance": "bakiye", "wallet": "bakiye",
        }
        op = _ALIASES.get(op, op)

        if op in ("yardim", "help", "h"):
            sub = parts[1].lower() if len(parts) > 1 else ""
            if sub in ("tam", "full"):
                log.write(t("help"))
            else:
                log.write(t("help.short"))

        elif op == "al":
            if len(parts) < 3:
                raise ValueError("Kullanım: /al SEMBOL TUTAR  (örn: /al btc 500)")
            sym = market.resolve_symbol(parts[1])
            usdt = float(parts[2].replace(",", "."))
            # Risk kapısı kontrolü
            _prices_now = {s: tk.price for s, tk in self.feed.tickers.items() if tk.price > 0}
            _rg = risk_mod.check_before_buy(sym, usdt, self.portfolio, _prices_now)
            for _blocker in _rg.blockers:
                log.write(f"[bold red3]⛔ Risk Engeli:[/] {_blocker}")
            if _rg.blockers:
                return
            for _warn in _rg.warnings:
                log.write(f"[gold3]⚠ Risk Uyarısı:[/] {_warn}")
            if self._is_live:
                _k, _s, _p = self._exchange_creds()
                _ex = getattr(self.cfg, "exchange", "binance").upper()
                log.write(f"[cyan]{_ex} MARKET BUY: {usdt:,.2f} USDT {market.short_name(sym)}...[/]")
                try:
                    fill_price, fill_qty, fill_usdt = await exchange.place_market_buy(_k, _s, sym, usdt, _p)
                    log.write(f"[green3]ALINDI: {fill_qty:.6f} {sym} @ {fmt_price(fill_price)} "
                              f"({fill_usdt:,.2f} USDT)[/]")
                    self.portfolio.buy(sym, fill_usdt, fill_price)
                    await self._sync_live_balance()
                    asyncio.ensure_future(notify.get().notify_buy(
                        sym, fill_qty, fill_price, fill_usdt, True))
                except Exception as e:
                    log.write(f"[red3]{_ex} hatası: {e}[/]")
                    return
            else:
                price = await self._price_of(sym)
                # Gerçekçi paper: %0.1 slippage + %0.1 komisyon simülasyonu
                slip_price = price * 1.001
                result = self.portfolio.buy(sym, usdt, slip_price)
                log.write(f"[green3]{result}[/]")
                log.write(f"[grey50]  (paper slippage simüle edildi: {fmt_price(price)} → {fmt_price(slip_price)})[/]")
                asyncio.ensure_future(notify.get().notify_buy(
                    sym, usdt / slip_price if slip_price else 0, slip_price, usdt, False))
            await self._sync_feed()
            self.run_protect(sym)

        elif op == "short":
            if len(parts) < 3:
                raise ValueError("Kullanım: /short SEMBOL TUTAR  (örn: /short btcusdt 500)")
            sym = market.resolve_symbol(parts[1])
            allowed, reason = market.trade_allowed(sym)
            if not allowed:
                raise ValueError(reason)
            if sym in self.portfolio.positions:
                raise ValueError(f"{sym}: zaten açık pozisyon var.")
            usdt = float(parts[2].replace(",", "."))
            if usdt > self.portfolio.cash:
                raise ValueError(f"Yetersiz bakiye: {self.portfolio.cash:,.2f} USDT mevcut.")
            price = await self._price_of(sym)
            # Short için varsayılan stop/target — Claude hemen ardından günceller
            default_stop = round(price * 1.05, 8)
            default_target = round(price * 0.90, 8)
            result = self.portfolio.buy_short(sym, usdt, price,
                                              stop=default_stop, target=default_target)
            log.write(f"[red3]{result}[/]")
            log.write(
                f"[grey58]  Varsayılan stop: {fmt_price(default_stop)} (+%5) | "
                f"hedef: {fmt_price(default_target)} (-%10)[/]"
            )
            log.write("[grey58]  Claude koruma seviyeleri belirliyor...[/]")
            await self._sync_feed()
            asyncio.ensure_future(self.run_protect(sym))

        elif op == "scalp":
            await self._cmd_scalp(parts[1:])

        elif op == "sat":
            if len(parts) < 2:
                raise ValueError("Kullanım: /sat SEMBOL [TUTAR]")
            sym = market.resolve_symbol(parts[1])
            partial_usdt = float(parts[2].replace(",", ".")) if len(parts) > 2 else None
            pos = self.portfolio.positions.get(sym)
            if not pos:
                raise ValueError(f"{market.short_name(sym)} pozisyonu yok.")
            if self._is_live:
                _k, _s, _p = self._exchange_creds()
                _ex = getattr(self.cfg, "exchange", "binance").upper()
                qty = pos.qty if partial_usdt is None else min(partial_usdt / (pos.entry or 1), pos.qty)
                log.write(f"[cyan]{_ex} MARKET SELL: {qty:.6f} {sym}...[/]")
                try:
                    fill_price, fill_qty, fill_usdt = await exchange.place_market_sell(_k, _s, sym, qty, _p)
                    log.write(f"[dark_orange]SATILDI: {fill_qty:.6f} {sym} @ "
                              f"{fmt_price(fill_price)} → {fill_usdt:,.2f} USDT[/]")
                    _pnl_pct = ((fill_price - pos.entry) / pos.entry * 100) if pos.entry else 0
                    self.portfolio.sell(sym, fill_price, partial_usdt)
                    await self._sync_live_balance()
                    asyncio.ensure_future(notify.get().notify_sell(
                        sym, fill_qty, fill_price, fill_usdt, _pnl_pct, True))
                except Exception as e:
                    log.write(f"[red3]{_ex} hatası: {e}[/]")
                    return
            else:
                price = await self._price_of(sym)
                _pnl_pct = ((price - pos.entry) / pos.entry * 100) if pos and pos.entry else 0
                _result = self.portfolio.sell(sym, price, partial_usdt)
                log.write(f"[dark_orange]{_result}[/]")
                asyncio.ensure_future(notify.get().notify_sell(
                    sym, pos.qty if pos else 0, price, (pos.qty or 0) * price, _pnl_pct, False))
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
            if category in SCAN_DIRECTIONS:
                self.run_directional(category)
            elif category and category not in SCAN_CATEGORIES:
                raise ValueError(
                    f"Geçersiz: {category}. "
                    f"Piyasa: {', '.join(sorted(SCAN_CATEGORIES))} | "
                    f"Yön: {', '.join(sorted(SCAN_DIRECTIONS))}"
                )
            else:
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

        elif op == "detay":
            if len(parts) < 2:
                raise ValueError("Kullanım: /detay SEMBOL  (örn: /detay BTCUSDT)")
            sym = market.resolve_symbol(parts[1])
            self._cmd_detay(sym)

        elif op == "kaldirac":
            await self._cmd_kaldirac(parts[1:])

        elif op == "uygula":
            await self._cmd_uygula(parts[1:])

        elif op == "otonom":
            await self._cmd_otonom(parts[1:])

        elif op == "model":
            self._cmd_model(parts[1:])

        elif op == "canli":
            await self._cmd_live(parts[1:])

        elif op in ("bildirim", "notify", "notification"):
            await self._cmd_notify(parts[1:])

        elif op in ("fiyat", "price", "alarm", "alert"):
            await self._cmd_fiyat(parts[1:])

        elif op in ("ta", "teknik", "indikatör", "indicator"):
            await self._cmd_ta(parts[1:])

        elif op in ("backtest", "bt", "test"):
            await self._cmd_backtest(parts[1:])

        elif op in ("boyut", "size", "pozisyon"):
            await self._cmd_boyut(parts[1:])

        elif op in ("mtf", "cok-zaman", "multitf"):
            await self._cmd_mtf(parts[1:])

        elif op in ("strateji", "strategy", "mod"):
            await self._cmd_strateji(parts[1:])

        elif op in ("risk", "heat", "isi"):
            self._cmd_risk()

        elif op in ("limit", "lmt"):
            await self._cmd_limit(parts[1:])

        elif op == "gecmis":
            self._show_history()

        elif op == "performans":
            await self._show_performance()

        elif op == "sifirla":
            confirm = parts[1].lower() if len(parts) > 1 else ""
            if confirm != "evet":
                log.write(
                    "[bold dark_orange]⚠ Bu işlem tüm pozisyon ve bakiyeyi sıfırlar![/] "
                    "[grey58]Onaylamak için: /sifirla evet[/]"
                )
            else:
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

        elif op == "cikis":
            self.action_open_menu()

        elif op == "bakiye":
            sub = parts[1].lower() if len(parts) > 1 else ""
            if sub in ("ayarla", "set") and len(parts) > 2:
                try:
                    yeni = float(parts[2].replace(",", "."))
                    if yeni <= 0:
                        raise ValueError("Bakiye sıfırdan büyük olmalı")
                    self.portfolio.cash = yeni
                    self.portfolio.save()
                    self._daily_start_equity = yeni
                    # Otonom engine'i de güncelle — yoksa eski equity'ye göre zarar limiti tetiklenir
                    if self._auto_engine:
                        self._auto_engine.state.daily_start_equity = yeni
                        self._auto_engine.state.risk_locked = False
                        self._auto_engine.state.save(self._auto_engine._state_path)
                    if i18n.lang() == "tr":
                        log.write(
                            f"[bold green3]Paper bakiye {yeni:,.2f} USDT olarak ayarlandı.[/] "
                            f"[grey58]Mevcut pozisyonlar etkilenmez.[/]"
                        )
                    else:
                        log.write(
                            f"[bold green3]Paper balance set to {yeni:,.2f} USDT.[/] "
                            f"[grey58]Existing positions are unaffected.[/]"
                        )
                except ValueError as e:
                    log.write(f"[red3]Hata: {e}[/]")
            else:
                all_prices = {s: tk.price for s, tk in self.feed.tickers.items() if tk.price > 0}
                eq = self.portfolio.equity(all_prices)
                if i18n.lang() == "tr":
                    log.write(
                        f"[bold]Bakiye:[/] nakit {self.portfolio.cash:,.2f} USDT | "
                        f"toplam varlık {eq:,.2f} USDT | "
                        f"[grey58]değiştirmek için: /bakiye ayarla 100[/]"
                    )
                else:
                    log.write(
                        f"[bold]Balance:[/] cash {self.portfolio.cash:,.2f} USDT | "
                        f"total equity {eq:,.2f} USDT | "
                        f"[grey58]to change: /balance set 100[/]"
                    )

        else:
            raise ValueError(f"Bilinmeyen komut: /{op}  (/yardim)")

    # ── otonom komut ──────────────────────────────────────────────────────────

    async def _cmd_otonom(self, args: list[str]) -> None:
        log = self.query_one("#log", RichLog)
        if not self._auto_engine:
            raise ValueError("Otonom motor henüz hazır değil.")
        sub = args[0].lower() if args else "durum"

        if sub in ("ac", "on"):
            # Trade türü argümanı verilmişse doğrudan başlat, yoksa soru sor
            trade_arg = args[1].lower() if len(args) > 1 else ""
            # (otonom_type, trade_plan, scalp_enabled, leverage_enabled)
            _trade_map = {
                "long":        ("long",      "sadece_long", False, False),
                "sadece_long": ("long",      "sadece_long", False, False),
                "short":       ("short",     "dengeli",     False, False),
                "longshort":   ("longshort", "dengeli",     False, False),
                "dengeli":     ("longshort", "dengeli",     False, False),
                "scalp":       ("scalp",     "dengeli",     True,  False),
                "kaldirac":    ("kaldirac",  "dengeli",     False, True),
                "kaldıraç":    ("kaldirac",  "dengeli",     False, True),
                "tam":         ("tam",       "tam",         True,  True),
                "hepsi":       ("tam",       "tam",         True,  True),
            }
            _TYPE_DISPLAY = {
                "long":      "LONG",
                "short":     "SHORT",
                "longshort": "LONG+SHORT",
                "scalp":     "SCALP",
                "kaldirac":  "KALDIRAÇ",
                "tam":       "LONG+SHORT+SCALP+LEV",
            }
            if trade_arg in _trade_map:
                ot, plan, scalp, lev = _trade_map[trade_arg]
                self.cfg.otonom_trade_type = ot
                self.cfg.trade_plan = plan
                self.cfg.scalp_enabled = scalp
                self.cfg.leverage_enabled = lev
                self.cfg.save()
            else:
                log.write("[bold cyan]── OTONOM TRADE TÜRÜ ──[/]")
                log.write("  [bold]/otonom ac long[/]      → Sadece LONG adayları (en güvenli)")
                log.write("  [bold]/otonom ac short[/]     → Sadece SHORT adayları")
                log.write("  [bold]/otonom ac longshort[/] → LONG + SHORT (her iki yön)")
                log.write("  [bold]/otonom ac scalp[/]     → Sadece SCALP (hızlı, 3dk tarama)")
                log.write("  [bold]/otonom ac kaldirac[/]  → Kaldıraçlı paper adaylar")
                log.write("  [bold]/otonom ac tam[/]       → LONG+SHORT+SCALP+KALDIRAÇ (hepsi)")
                log.write("[grey58]Örnek: /otonom ac short   veya   /otonom ac longshort[/]")
                return
            msg = await self._auto_engine.start()
            log.write(f"[bold green3]{msg}[/]")
            ot = self.cfg.otonom_trade_type
            mode_str = _TYPE_DISPLAY.get(ot, ot.upper())
            scan_iv = "3dk" if (self.cfg.scalp_enabled or ot in ("scalp", "tam")) else "15dk"
            log.write(f"[bold green3]Trade türü: {mode_str}[/] | Risk: [bold]{self._auto_engine.profile.name}[/]")
            log.write(f"[grey58]Tarama aralığı: {scan_iv} | 134 kripto sembol izleniyor | Claude analiz ediyor[/]")

        elif sub in ("kapat", "off"):
            msg = await self._auto_engine.stop()
            log.write(f"[bold dark_orange]{msg}[/]")

        elif sub in ("sifirla", "reset"):
            s = self._auto_engine.state
            s.daily_trades = 0
            s.risk_locked = False
            s.consecutive_losses = 0
            s.daily_leverage_locked = False
            s.cooldown_until = 0.0
            s.save(self._auto_engine._state_path)
            log.write("[bold cyan]Otonom sayaçlar sıfırlandı:[/] günlük işlem, risk kilidi, zarar serisi.")

        elif sub in ("durum", "status"):
            log.write("[bold cyan]── OTONOM MOD DURUMU ──[/]")
            log.write(self._auto_engine.status_text())

        elif sub in ("mod", "mode"):
            from autonomous import AUTONOMOUS_PROFILES
            if len(args) < 2:
                cur_key = getattr(self.cfg, "autonomous_mode", "dengeli")
                log.write("[bold cyan]── OTONOM RİSK MODLARı ──[/]")
                for key, p in AUTONOMOUS_PROFILES.items():
                    aktif = " [gold3]◀ AKTİF[/]" if key == cur_key else ""
                    log.write(
                        f"  [bold]/otonom mod {key}[/] → max {p.max_open_positions} pos | "
                        f"min güven %{p.min_confidence} | R/R {p.min_risk_reward} | "
                        f"günlük maks {p.max_daily_trades}{aktif}"
                    )
            else:
                msg = self._auto_engine.set_mode(args[1].lower())
                log.write(msg)
                self.refresh_tables()

        elif sub in ("ayar", "set"):
            from autonomous import AUTONOMOUS_PROFILES
            p = self._auto_engine.effective_profile
            base = self._auto_engine.profile
            # Alt komut: /otonom ayar işlem-limit N
            if len(args) >= 3 and args[1].lower() in ("işlem-limit", "trade-limit"):
                try:
                    val = int(args[2])
                    if val < 0:
                        raise ValueError()
                    self.cfg.custom_max_daily_trades = val
                    self.cfg.save()
                    label = "profil varsayılanı" if val == 0 else str(val)
                    log.write(f"[bold cyan]Günlük işlem limiti → {label}[/]")
                except ValueError:
                    log.write("[red3]Kullanım: /otonom ayar işlem-limit 10  (0 = profil varsayılanı)[/]")
                return
            elif len(args) >= 3 and args[1].lower() in ("pozisyon-limit", "pos-limit"):
                try:
                    val = int(args[2])
                    if val < 0:
                        raise ValueError()
                    self.cfg.custom_max_positions = val
                    self.cfg.save()
                    label = "profil varsayılanı" if val == 0 else str(val)
                    log.write(f"[bold cyan]Maksimum açık pozisyon → {label}[/]")
                except ValueError:
                    log.write("[red3]Kullanım: /otonom ayar pozisyon-limit 5  (0 = profil varsayılanı)[/]")
                return
            log.write("[bold cyan]── OTONOM ÖZEL AYARLAR ──[/]")
            log.write(f"  [bold]Temel profil:[/] {base.name}")
            log.write(f"  max_pozisyon={p.max_open_positions} "
                      f"(profil: {base.max_open_positions})")
            log.write(f"  max_gunluk_islem={p.max_daily_trades} "
                      f"(profil: {base.max_daily_trades})")
            log.write(f"  ardi_ardina_zarar={p.max_consecutive_losses} "
                      f"(profil: {base.max_consecutive_losses})")
            log.write(f"  gunluk_zarar_pct={p.daily_loss_limit_percent:.1f}% "
                      f"(profil: {base.daily_loss_limit_percent:.1f}%)")
            log.write("[grey58]Değiştirmek için:[/]")
            log.write("  /otonom ayar işlem-limit 10   → günlük max işlem sayısı")
            log.write("  /otonom ayar pozisyon-limit 5 → eş zamanlı max pozisyon")

        else:
            raise ValueError(
                "Kullanım: /otonom ac | kapat | durum | mod [guvenli|dengeli|agresif] | ayar"
            )

    # ── /scalp komutu ────────────────────────────────────────────────────────

    async def _cmd_scalp(self, args: list[str]) -> None:
        log = self.query_one("#log", RichLog)
        sub = args[0].lower() if args else "durum"
        if sub in ("ac", "on"):
            self.cfg.scalp_enabled = True
            self.cfg.save()
            log.write("[bold cyan]Scalp paper modu AÇILDI.[/] "
                      "[grey58]Tarama: /tara scalp[/]")
        elif sub in ("kapat", "off"):
            self.cfg.scalp_enabled = False
            self.cfg.save()
            log.write("[grey58]Scalp paper modu KAPATILDI.[/]")
        elif sub in ("durum", "status"):
            if self.cfg.scalp_enabled:
                log.write("[cyan]Scalp modu: AÇIK[/] — /tara scalp ile fırsat ara")
            else:
                log.write("[grey58]Scalp modu: KAPALI[/] — /scalp ac ile etkinleştir")
        else:
            raise ValueError("Kullanım: /scalp ac | /scalp kapat | /scalp durum")

    # ── /kaldirac komutu ──────────────────────────────────────────────────────

    async def _cmd_kaldirac(self, args: list[str]) -> None:
        log = self.query_one("#log", RichLog)
        sub = args[0].lower() if args else "durum"
        if sub in ("ac", "on"):
            self.cfg.leverage_enabled = True
            self.cfg.save()
            log.write("[bold gold3]Kaldıraçlı paper modu AÇILDI.[/] "
                      "[dark_orange]⚠ Yüksek risk — sadece Binance kripto sembolleri.[/]")
        elif sub in ("kapat", "off"):
            self.cfg.leverage_enabled = False
            self.cfg.save()
            log.write("[grey58]Kaldıraçlı paper modu KAPATILDI.[/]")
        elif sub in ("durum", "status"):
            if self.cfg.leverage_enabled:
                from autonomous import AUTONOMOUS_PROFILES
                mode_key = getattr(self.cfg, "autonomous_mode", "dengeli")
                p = AUTONOMOUS_PROFILES.get(mode_key)
                max_lev = p.max_leverage if p else "?"
                log.write(f"[gold3]Kaldıraç modu: AÇIK[/] — maks {max_lev}x "
                          f"(profil: {mode_key})")
            else:
                log.write("[grey58]Kaldıraç modu: KAPALI[/] — /kaldirac ac ile etkinleştir")
        else:
            raise ValueError("Kullanım: /kaldirac ac | /kaldirac kapat | /kaldirac durum")

    # ── /detay komutu ────────────────────────────────────────────────────────

    def _cmd_detay(self, sym: str) -> None:
        log = self.query_one("#log", RichLog)
        tk = self.feed.tickers.get(sym)
        price = self.feed.price(sym) or 0.0

        log.write(f"[bold cyan]── {market.short_name(sym)} DETAY ──[/]")
        if price:
            log.write(f"  [bold]Fiyat:[/] {fmt_price(price)}")
        if tk:
            chg_color = "green3" if tk.change_pct >= 0 else "red3"
            log.write(f"  [bold]Değişim:[/] [{chg_color}]{tk.change_pct:+.2f}%[/]")
            if tk.high:
                log.write(f"  [bold]Yüksek / Düşük:[/] "
                          f"{fmt_price(tk.high)} / {fmt_price(tk.low)}")

        # Veri kalitesi
        quality_label = market.data_quality_label(sym)
        lev_ok = market.leverage_allowed(sym)
        lev_reason = market.leverage_reason(sym)
        q_color = "green3" if "Anlık" in quality_label else (
            "gold3" if "Yakın" in quality_label else "red3"
        )
        log.write(f"  [bold]Veri kalitesi:[/] [{q_color}]{quality_label}[/]")
        lev_color = "green3" if lev_ok else "red3"
        log.write(f"  [bold]Kaldıraç izni:[/] [{lev_color}]{'İZİNLİ' if lev_ok else 'ENGELLENDİ'}[/]")
        log.write(f"    [grey58]{lev_reason}[/]")

        # Mevcut pozisyon
        pos = self.portfolio.positions.get(sym)
        if pos:
            cur = price or pos.entry
            pnl, pct = self.portfolio.unrealized_pnl(sym, cur)
            sign = "+" if pnl >= 0 else ""
            color = "green3" if pnl >= 0 else "red3"
            log.write(f"  [bold]Pozisyon:[/] {pos.qty:.6f} @ {fmt_price(pos.entry)} "
                      f"[{color}]({sign}{pnl:,.2f} USDT, {sign}{pct:.2f}%)[/]")
            if pos.stop:
                sp_pct = (cur - pos.stop) / cur * 100 if cur else 0
                log.write(f"  [bold]Stop:[/] [red3]{fmt_price(pos.stop)}[/] "
                          f"[grey58]({sp_pct:.1f}% uzakta)[/]")
            if pos.target:
                tp_pct = (pos.target - cur) / cur * 100 if cur else 0
                log.write(f"  [bold]Hedef:[/] [green3]{fmt_price(pos.target)}[/] "
                          f"[grey58]({tp_pct:.1f}% uzakta)[/]")
            if pos.is_leveraged:
                log.write(f"  [bold]Kaldıraç:[/] [gold3]{pos.leverage}x[/] | "
                          f"margin {pos.margin_usdt:,.2f} USDT | "
                          f"notional {pos.notional_usdt:,.2f} USDT | "
                          f"liq {fmt_price(pos.liquidation_price)}")
        else:
            log.write("  [grey58]Açık pozisyon yok.[/]")

    # ── /uygula komutu ───────────────────────────────────────────────────────

    async def _cmd_uygula(self, args: list[str]) -> None:
        log = self.query_one("#log", RichLog)
        if not self._auto_engine:
            raise ValueError("Otonom motor henüz hazır değil.")
        if not self._pending_position_decisions:
            raise ValueError(
                "Bekleyen Claude kararı yok. Önce /durum çalıştır."
            )

        all_kw = {"hepsi", "all", "tum", "tüm"}
        if not args or args[0].lower() in all_kw:
            targets = list(self._pending_position_decisions.keys())
        else:
            sym = market.resolve_symbol(args[0])
            if sym not in self._pending_position_decisions:
                raise ValueError(
                    f"{market.short_name(sym)} için bekleyen karar yok. /durum çalıştır."
                )
            targets = [sym]

        applied = 0
        for sym in targets:
            pd = self._pending_position_decisions.get(sym)
            if not pd or sym not in self.portfolio.positions:
                continue
            price = await self._price_of(sym)
            changed, msg = await self._auto_engine.apply_decision(sym, pd, price, auto=False)
            color = "green3" if changed else "grey58"
            log.write(f"[{color}]{msg}[/]")
            if changed:
                applied += 1
                self._pending_position_decisions.pop(sym, None)

        if applied == 0 and targets:
            log.write("[grey58]Uygulanacak aksiyon gerektiren karar yok "
                      "(DEVAM/BEKLE kararları atlandı).[/]")
        await self._sync_feed()

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

        # Piyasa kapalı uyarısı (Yahoo hisse/emtia sembolleri hafta sonu sıfır gösterir)
        yahoo_closed = [
            market.short_name(sym)
            for sym, p in self.portfolio.positions.items()
            if market.is_yahoo(sym) and self.feed.price(sym) == 0
        ]
        if yahoo_closed:
            log.write(
                f"[grey58]ℹ {', '.join(yahoo_closed)}: piyasa kapalı olduğundan "
                f"güncel fiyat alınamıyor (hafta sonu/tatil). K/Z giriş fiyatı baz alındı.[/]"
            )

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
                    self._pending_position_decisions[sym] = pd
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
        lang = i18n.lang()
        _PROVIDERS = ("claude", "openai", "gemini", "ollama", "grok")

        if not args:
            # Durum: aktif AI + Claude modelleri
            cur_provider = getattr(self.cfg, "ai_provider", "claude")
            cur_model = self.cfg.model
            if lang == "tr":
                log.write(f"[bold cyan]── AI Sağlayıcısı ──[/]  Aktif: [bold]{cur_provider.upper()}[/]")
                log.write("  [bold]/model claude[/] [opus|sonnet|haiku]  → Claude (abonelik)")
                log.write("  [bold]/model openai[/] [gpt-4o|o3-mini]     → OpenAI GPT")
                log.write("  [bold]/model gemini[/] [flash|pro]           → Google Gemini")
                log.write("  [bold]/model ollama[/] [llama3.2|mistral]    → Yerel Ollama")
                log.write("  [bold]/model grok[/]   [grok-3-mini]         → xAI Grok")
                log.write("  [bold]/model key[/] openai|gemini|grok API_KEY  → API key kaydet")
                log.write(f"\n  [bold cyan]Claude modelleri[/] (aktif: {cur_model}):")
            else:
                log.write(f"[bold cyan]── AI Provider ──[/]  Active: [bold]{cur_provider.upper()}[/]")
                log.write("  [bold]/model claude[/] [opus|sonnet|haiku]  → Claude (subscription)")
                log.write("  [bold]/model openai[/] [gpt-4o|o3-mini]     → OpenAI GPT")
                log.write("  [bold]/model gemini[/] [flash|pro]           → Google Gemini")
                log.write("  [bold]/model ollama[/] [llama3.2|mistral]    → Local Ollama")
                log.write("  [bold]/model grok[/]   [grok-3-mini]         → xAI Grok")
                log.write("  [bold]/model key[/] openai|gemini|grok API_KEY  → save API key")
                log.write(f"\n  [bold cyan]Claude models[/] (active: {cur_model}):")
            for key, (mid, tr_desc, en_desc) in MODELS.items():
                desc = tr_desc if lang == "tr" else en_desc
                mark = " ◀" if key == cur_model and cur_provider == "claude" else ""
                log.write(f"    [bold]/model claude {key}[/] → {desc}{mark}")
            return

        sub = args[0].lower()

        # ── /model key PROVIDER API_KEY ─────────────────────────────────────
        if sub == "key":
            if len(args) < 3:
                raise ValueError("/model key openai|gemini|grok YOUR_API_KEY")
            provider_name = args[1].lower()
            api_key = args[2]
            if provider_name == "openai":
                self.cfg.openai_api_key = api_key
                self.cfg.save()
                log.write("[green3]✓ OpenAI API key kaydedildi.[/]" if lang == "tr" else "[green3]✓ OpenAI API key saved.[/]")
            elif provider_name == "gemini":
                self.cfg.gemini_api_key = api_key
                self.cfg.save()
                log.write("[green3]✓ Gemini API key kaydedildi.[/]" if lang == "tr" else "[green3]✓ Gemini API key saved.[/]")
            elif provider_name == "grok":
                self.cfg.grok_api_key = api_key
                self.cfg.save()
                log.write("[green3]✓ Grok API key kaydedildi.[/]" if lang == "tr" else "[green3]✓ Grok API key saved.[/]")
            else:
                raise ValueError("Geçerli sağlayıcılar: openai, gemini, grok" if lang == "tr"
                                 else "Valid providers: openai, gemini, grok")
            return

        # ── /model PROVIDER [model_name] ────────────────────────────────────
        if sub in _PROVIDERS:
            self.cfg.ai_provider = sub
            if len(args) > 1:
                model_name = args[1].lower()
                if sub == "claude":
                    if model_name not in MODELS:
                        raise ValueError(f"Claude modelleri: {', '.join(MODELS)}")
                    self.cfg.model = model_name
                elif sub == "openai":
                    self.cfg.openai_model = model_name
                elif sub == "gemini":
                    # "flash" → "gemini-2.0-flash", "pro" → "gemini-2.0-pro" kısayolları
                    _gem_map = {"flash": "gemini-2.0-flash", "pro": "gemini-2.0-pro", "flash-lite": "gemini-2.0-flash-lite"}
                    self.cfg.gemini_model = _gem_map.get(model_name, model_name)
                elif sub == "ollama":
                    self.cfg.ollama_model = model_name
                elif sub == "grok":
                    self.cfg.grok_model = model_name
            self.cfg.save()
            _active_model = {
                "claude": f"{self.cfg.model} ({self.cfg.model_id or 'CLI'})",
                "openai": getattr(self.cfg, "openai_model", "gpt-4o"),
                "gemini": getattr(self.cfg, "gemini_model", "gemini-2.0-flash"),
                "ollama": getattr(self.cfg, "ollama_model", "llama3.2"),
                "grok": getattr(self.cfg, "grok_model", "grok-3-mini"),
            }.get(sub, sub)
            log.write(t("model.changed", model=f"{sub.upper()} · {_active_model}"))
            return

        # ── Geriye dönük uyumluluk: /model opus|sonnet|haiku → claude + model ─
        if sub in MODELS:
            self.cfg.ai_provider = "claude"
            self.cfg.model = sub
            self.cfg.save()
            log.write(t("model.changed", model=f"claude {sub} ({self.cfg.model_id or 'CLI'})"))
            return

        raise ValueError(t("model.usage"))

    async def _cmd_live(self, args: list[str]) -> None:
        log = self.query_one("#log", RichLog)
        sub = args[0].lower() if args else ""

        if not sub:
            log.write(t("live.header"))
            if self.cfg.binance_key:
                cur_mode = getattr(self.cfg, "trading_mode", "paper").upper()
                mode_color = "green3" if cur_mode == "LIVE" else "gold3"
                log.write(t("live.status_on", mode=f"[{mode_color}]{cur_mode}[/]"))
            else:
                log.write(t("live.status_off"))
            log.write(
                exchange.requirements(i18n.lang())
            )
            log.write(t("live.warning"))
            log.write(f"[grey58]{t('live.usage')}[/]")

        elif sub == "bagla":
            ex = getattr(self.cfg, "exchange", "binance")
            # OKX için 3 parametre (key + secret + passphrase)
            min_args = 4 if ex == "okx" else 3
            if len(args) < min_args:
                extra_hint = "  (OKX: /canli bagla KEY SECRET PASSPHRASE)" if ex == "okx" else ""
                raise ValueError(t("live.usage") + extra_hint)
            key, secret = args[1], args[2]
            passphrase = args[3] if ex == "okx" and len(args) > 3 else ""
            log.write(t("live.validating"))
            try:
                await exchange.validate_keys(key, secret, passphrase)
            except Exception as e:
                log.write(t("live.failed", err=e))
                return
            if ex == "binance":
                self.cfg.binance_key = key
                self.cfg.binance_secret = secret
            elif ex == "bybit":
                self.cfg.bybit_key = key  # type: ignore[attr-defined]
                self.cfg.bybit_secret = secret  # type: ignore[attr-defined]
            elif ex == "okx":
                self.cfg.okx_key = key  # type: ignore[attr-defined]
                self.cfg.okx_secret = secret  # type: ignore[attr-defined]
                self.cfg.okx_passphrase = passphrase  # type: ignore[attr-defined]
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
            _k, _s, _p = self._exchange_creds()
            if not _k:
                raise ValueError(t("live.no_keys"))
            log.write(t("live.validating"))
            try:
                balances = await exchange.fetch_balances(_k, _s, _p)
            except Exception as e:
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

        elif sub in ("mod", "mode"):
            mode_arg = args[1].lower() if len(args) > 1 else ""
            if mode_arg in ("live", "gercek", "gerçek"):
                _k, _s, _p = self._exchange_creds()
                _ex = getattr(self.cfg, "exchange", "binance").upper()
                if not _k:
                    raise ValueError(
                        f"Önce bağlan: /canli bagla API_KEY SECRET  "
                        f"({_ex} API'da Trading iznini aç)"
                    )
                can_trade = False
                try:
                    can_trade = await exchange.check_trading_permission(_k, _s, _p)
                except Exception as e:
                    raise ValueError(f"{_ex} doğrulaması başarısız: {e}")
                if not can_trade:
                    raise ValueError(
                        f"{_ex} hesabında trading izni yok. "
                        f"API Management'tan Trade iznini aç."
                    )
                self.cfg.trading_mode = "live"
                self.cfg.save()
                log.write(
                    f"[bold green3]⚡ GERÇEK PARA MODUNA GEÇİLDİ[/]  "
                    f"[dark_orange]Bundan sonra /al ve /sat komutları "
                    f"{_ex}'e gerçek emir gönderir.[/]"
                )
                await self._sync_live_balance()
                log.write(
                    f"[cyan]Gerçek USDT bakiyesi senkronize edildi: "
                    f"{self.portfolio.cash:,.2f} USDT[/]"
                )
            elif mode_arg in ("paper", "kagit", "kağıt", "simul"):
                self.cfg.trading_mode = "paper"
                self.cfg.save()
                log.write(
                    "[gold3]Paper moduna dönüldü.[/] "
                    "[grey58]İşlemler artık sanal hesapta (simülasyon).[/]"
                )
            elif not mode_arg:
                cur = getattr(self.cfg, "trading_mode", "paper")
                color = "green3" if cur == "live" else "gold3"
                log.write(f"Mevcut mod: [{color}]{cur.upper()}[/]")
                log.write("[grey58]/canli mod live  →  gerçek para (Binance)[/]")
                log.write("[grey58]/canli mod paper →  simülasyon (paper)[/]")
            else:
                raise ValueError("Kullanım: /canli mod live | /canli mod paper")

        elif sub == "kes":
            ex = getattr(self.cfg, "exchange", "binance")
            if ex == "binance":
                self.cfg.binance_key = ""
                self.cfg.binance_secret = ""
            elif ex == "bybit":
                self.cfg.bybit_key = ""  # type: ignore[attr-defined]
                self.cfg.bybit_secret = ""  # type: ignore[attr-defined]
            elif ex == "okx":
                self.cfg.okx_key = ""  # type: ignore[attr-defined]
                self.cfg.okx_secret = ""  # type: ignore[attr-defined]
                self.cfg.okx_passphrase = ""  # type: ignore[attr-defined]
            self.cfg.trading_mode = "paper"
            self.cfg.save()
            log.write(t("live.disconnected"))

        else:
            raise ValueError(t("live.usage"))

    async def _cmd_notify(self, args: list[str]) -> None:
        """
        /bildirim               → durumu göster
        /bildirim bagla TOKEN CHAT_ID
        /bildirim kes
        /bildirim test
        """
        log = self.query_one("#log", RichLog)
        lang = i18n.lang()
        sub = args[0].lower() if args else ""

        if not sub:
            n = notify.get()
            if n.enabled:
                bot = notify.get_bot()
                bot_status = "komut botu aktif" if (bot._task and not bot._task.done()) else "komut botu başlatılıyor..."
                bot_status_en = "command bot active" if (bot._task and not bot._task.done()) else "command bot starting..."
                if lang == "tr":
                    log.write(f"[green3]✔ Telegram aktif[/]  chat_id: {self.cfg.telegram_chat_id}  [{bot_status}]")
                else:
                    log.write(f"[green3]✔ Telegram active[/]  chat_id: {self.cfg.telegram_chat_id}  [{bot_status_en}]")
            else:
                if lang == "tr":
                    log.write("[grey58]Telegram kapalı. /bildirim bagla TOKEN CHAT_ID ile etkinleştir.[/]")
                    log.write("  1) @BotFather → /newbot → token al")
                    log.write("  2) Botu başlat (bir mesaj gönder)")
                    log.write("  3) api.telegram.org/bot<TOKEN>/getUpdates → chat_id bul")
                else:
                    log.write("[grey58]Telegram disabled. Enable: /notify bagla TOKEN CHAT_ID[/]")
            return

        elif sub == "bagla":
            if len(args) < 3:
                raise ValueError("/bildirim bagla BOT_TOKEN CHAT_ID")
            token, chat_id = args[1], args[2]
            log.write("[grey58]Telegram doğrulanıyor...[/]")
            ok, msg = await notify.get().validate(token, chat_id)
            if not ok:
                log.write(f"[red3]✗ Telegram hatası: {msg}[/]")
                return
            self.cfg.telegram_token = token
            self.cfg.telegram_chat_id = chat_id
            self.cfg.save()
            notify.configure(token, chat_id)
            notify.get_bot().start(
                portfolio=self.portfolio,
                engine=self._auto_engine,
                cfg=self.cfg,
                feed=self.feed,
                log_fn=log.write,
            )
            log.write(f"[green3]✔ Telegram bağlandı! {msg} — komut botu aktif[/]" if lang == "tr"
                      else f"[green3]✔ Telegram connected! {msg} — command bot active[/]")

        elif sub == "kes":
            self.cfg.telegram_token = ""
            self.cfg.telegram_chat_id = ""
            self.cfg.save()
            notify.get_bot().stop()
            notify.configure("", "")
            log.write("[dark_orange]Telegram bildirimleri devre dışı.[/]" if lang == "tr"
                      else "[dark_orange]Telegram notifications disabled.[/]")

        elif sub == "test":
            n = notify.get()
            if not n.enabled:
                raise ValueError("Önce bağla: /bildirim bagla TOKEN CHAT_ID" if lang == "tr"
                                 else "Connect first: /notify bagla TOKEN CHAT_ID")
            ok = await n.send("🧪 <b>trade-k test mesajı</b> — her şey çalışıyor!" if lang == "tr"
                              else "🧪 <b>trade-k test message</b> — everything works!")
            if ok:
                log.write("[green3]✔ Test mesajı gönderildi.[/]" if lang == "tr"
                          else "[green3]✔ Test message sent.[/]")
            else:
                log.write("[red3]✗ Gönderme başarısız.[/]" if lang == "tr"
                          else "[red3]✗ Send failed.[/]")
        else:
            raise ValueError("/bildirim bagla TOKEN CHAT_ID | /bildirim kes | /bildirim test")

    # ── Teknik analiz komutu ─────────────────────────────────────────────────

    async def _cmd_ta(self, args: list[str]) -> None:
        """
        /ta SEMBOL [ZAMAN_DİLİMİ]
        Örn: /ta BTC 1h   → RSI, MACD, Bollinger, EMA, sinyal
        Zaman dilimleri: 1m 5m 15m 30m 1h 4h 1d
        """
        log = self.query_one("#log", RichLog)
        if not args:
            raise ValueError("Kullanım: /ta SEMBOL [1m|5m|15m|1h|4h|1d]  örn: /ta BTC 1h")
        sym = market.resolve_symbol(args[0])
        tf = args[1].lower() if len(args) > 1 else "1h"
        if tf not in indicators.TIMEFRAMES:
            raise ValueError(f"Geçersiz zaman dilimi. Geçerliler: {', '.join(indicators.TIMEFRAMES)}")
        log.write(f"[grey58]TA hesaplanıyor: {market.short_name(sym)} [{tf}]...[/]")
        try:
            r = await indicators.analyze(sym, tf)
        except Exception as e:
            log.write(f"[red3]TA hatası: {e}[/]")
            return

        # Spread (yalnızca kripto)
        spread_str = ""
        if not market.is_yahoo(sym):
            try:
                bid, ask, spread_pct = await market.get_spread(sym)
                spread_color = "green3" if spread_pct < 0.05 else ("gold3" if spread_pct < 0.15 else "red3")
                spread_str = (
                    f"\n  Spread: bid {fmt_price(bid)} │ ask {fmt_price(ask)} │ "
                    f"[{spread_color}]{spread_pct:.4f}%[/]"
                    f"{'  ← geniş spread' if spread_pct > 0.1 else ''}"
                )
                # Stale data uyarısı
                if self._feed.is_stale(sym, max_age=30.0):
                    spread_str += "  [gold3]⚠ Anlık veri eski (>30s)[/]"
            except Exception:
                pass

        sig_color = {"GÜÇLÜ_AL": "green3", "AL": "green3",
                     "BEKLE": "gold3", "SAT": "red3", "GÜÇLÜ_SAT": "red3"}.get(r.signal, "white")
        sig_emoji = {"GÜÇLÜ_AL": "⬆⬆", "AL": "⬆", "BEKLE": "→", "SAT": "⬇", "GÜÇLÜ_SAT": "⬇⬇"}.get(r.signal, "")

        log.write(
            f"[bold cyan]── Teknik Analiz: {market.short_name(sym)} [{tf}] ──[/]\n"
            f"  Fiyat : [bold]{fmt_price(r.price)}[/]{spread_str}\n"
            f"  Sinyal: [bold {sig_color}]{sig_emoji} {r.signal}[/]  (skor: {r.score:+d}/8)\n"
            f"  RSI   : [bold]{r.rsi:.1f}[/]"
            f"{'  ← aşırı satım' if r.rsi < 30 else '  ← aşırı alım' if r.rsi > 70 else ''}\n"
            f"  MACD  : {r.macd:.4f}  /  Sinyal: {r.macd_signal:.4f}"
            f"  ({'↑ yukarı' if r.macd > r.macd_signal else '↓ aşağı'})\n"
            f"  BB    : ↑{fmt_price(r.bb_upper)} │ orta {fmt_price(r.bb_mid)} │ ↓{fmt_price(r.bb_lower)}\n"
            f"          Konum: %{r.bb_pct*100:.0f} (0=alt, 100=üst)\n"
            f"  EMA20 : {fmt_price(r.ema20)}  │  EMA50: {fmt_price(r.ema50)}\n"
            f"  ATR   : {fmt_price(r.atr)}  (stop için öneri: {fmt_price(r.price - r.atr*1.5)} – {fmt_price(r.price - r.atr*2)})\n"
            f"  Hacim : ×{r.vol_ratio:.1f} ort"
        )
        if r.reasons:
            log.write("  Nedenler:")
            for reason in r.reasons:
                log.write(f"    · {reason}")

    # ── Backtesting komutu ───────────────────────────────────────────────────

    async def _cmd_backtest(self, args: list[str]) -> None:
        """
        /backtest SEMBOL [TF] [GÜN] [STOP%] [HEDEF%]
        /backtest wf SEMBOL [TF] [GÜN]      → Walk-forward (%70 in-sample / %30 out-of-sample)
        /backtest mc SEMBOL [TF] [GÜN]      → Monte Carlo (200 simülasyon)
        /backtest scan [TF] [GÜN]           → İzleme listesini tara, en iyi sembolleri sırala
        """
        log = self.query_one("#log", RichLog)
        if not args:
            raise ValueError(
                "Kullanım:\n"
                "  /backtest SEMBOL [TF] [GÜN] [STOP%] [HEDEF%]\n"
                "  /backtest wf SEMBOL [TF] [GÜN]   — walk-forward analizi\n"
                "  /backtest mc SEMBOL [TF] [GÜN]   — Monte Carlo simülasyonu\n"
                "  /backtest scan [TF] [GÜN]        — izleme listesi taraması"
            )

        subcommand = args[0].lower()

        # ── Walk-forward ─────────────────────────────────────────────────────
        if subcommand == "wf":
            if len(args) < 2:
                raise ValueError("Kullanım: /backtest wf SEMBOL [TF] [GÜN]")
            sym = market.resolve_symbol(args[1])
            tf = args[2].lower() if len(args) > 2 else "1h"
            days = int(args[3]) if len(args) > 3 else 90
            if days < 30:
                raise ValueError("Walk-forward için en az 30 günlük veri gerekli.")
            log.write(
                f"[grey58]Walk-forward backtest: {market.short_name(sym)} [{tf}] "
                f"{days} gün (%70 in-sample / %30 out-of-sample)...[/]"
            )
            try:
                is_r, os_r = await backtest_mod.walk_forward(sym, tf, days)
            except Exception as e:
                log.write(f"[red3]Walk-forward hatası: {e}[/]")
                return
            log.write(f"[bold cyan]── Walk-Forward Analizi: {market.short_name(sym)} ──[/]")
            log.write(is_r.summary())
            log.write("")
            log.write(os_r.summary())
            # Overfit kontrolü
            diff = abs(is_r.total_return_pct - os_r.total_return_pct)
            if os_r.n_trades == 0:
                log.write("[dark_orange]⚠ Out-of-sample'da hiç işlem yok — süreyi artır.[/]")
            elif os_r.total_return_pct > 0 and diff < is_r.total_return_pct * 0.5:
                log.write("[green3]✔ In-sample ve out-of-sample tutarlı — düşük overfit riski.[/]")
            elif os_r.total_return_pct < 0 and is_r.total_return_pct > 0:
                log.write("[red3]✗ In-sample karlı ama out-of-sample zararlı → overfit işareti! "
                          "Bu strateji gerçek veriye genellemiyor.[/]")
            else:
                log.write("[gold3]~ Sonuçlar kısmen tutarsız. Daha uzun süre veya farklı TF dene.[/]")
            return

        # ── Monte Carlo ───────────────────────────────────────────────────────
        if subcommand == "mc":
            if len(args) < 2:
                raise ValueError("Kullanım: /backtest mc SEMBOL [TF] [GÜN]")
            sym = market.resolve_symbol(args[1])
            tf = args[2].lower() if len(args) > 2 else "1h"
            days = int(args[3]) if len(args) > 3 else 30
            log.write(
                f"[grey58]Monte Carlo: {market.short_name(sym)} [{tf}] "
                f"{days} gün, 200 simülasyon...[/]"
            )
            try:
                median, p5, p95, ruin = await backtest_mod.monte_carlo(sym, tf, days)
            except Exception as e:
                log.write(f"[red3]Monte Carlo hatası: {e}[/]")
                return
            log.write(f"[bold cyan]── Monte Carlo: {market.short_name(sym)} ──[/]")
            med_c = "green3" if median >= 0 else "red3"
            p5_c = "red3" if p5 < 0 else "green3"
            ruin_c = "red3" if ruin > 10 else ("gold3" if ruin > 2 else "green3")
            log.write(
                f"  Ortanca getiri : [bold {med_c}]{'+' if median >= 0 else ''}{median:.2f}%[/]\n"
                f"  %5 kötü senaryo: [{p5_c}]{'+' if p5 >= 0 else ''}{p5:.2f}%[/]\n"
                f"  %95 iyi senaryo: [green3]{'+' if p95 >= 0 else ''}{p95:.2f}%[/]\n"
                f"  Çöküş riski    : [{ruin_c}]%{ruin:.1f}[/]  (sim. %50+ kayıp)"
            )
            if ruin > 20:
                log.write("[red3]✗ Yüksek çöküş riski — bu parametrelerle gerçek para kullanma![/]")
            elif median > 0 and p5 > -10:
                log.write("[green3]✔ Risk/getiri dengesi makul görünüyor.[/]")
            return

        # ── Scan (çoklu sembol) ───────────────────────────────────────────────
        if subcommand == "scan":
            tf = args[1].lower() if len(args) > 1 else "1h"
            days = int(args[2]) if len(args) > 2 else 30
            watchlist = self._watchlist[:]
            crypto_wl = [s for s in watchlist if s.endswith("USDT") and "=" not in s and "-" not in s]
            if not crypto_wl:
                log.write("[gold3]İzleme listesinde kripto sembol bulunamadı.[/]")
                return
            log.write(
                f"[grey58]Backtest taraması: {len(crypto_wl)} sembol [{tf}] {days} gün...[/]"
            )
            try:
                results = await backtest_mod.multi_symbol_scan(crypto_wl, tf, days)
            except Exception as e:
                log.write(f"[red3]Scan hatası: {e}[/]")
                return
            log.write(f"[bold cyan]── Backtest Taraması [{tf}] {days}gün — En İyi 5 ──[/]")
            if not results:
                log.write("[dark_orange]Hiç sonuç yok.[/]")
                return
            for i, r in enumerate(results[:5], 1):
                pf = f"{r.profit_factor:.2f}" if r.profit_factor < 999 else "∞"
                ret_c = "green3" if r.total_return_pct >= 0 else "red3"
                log.write(
                    f"  {i}. [bold]{r.symbol}[/]  WR:{r.win_rate:.0f}%  "
                    f"PF:{pf}  Getiri:[{ret_c}]{r.total_return_pct:+.1f}%[/]  "
                    f"DD:-{r.max_drawdown_pct:.1f}%  ({r.n_trades} işlem)"
                )
            return

        # ── Standart tek sembol backtest ──────────────────────────────────────
        sym = market.resolve_symbol(args[0])
        tf = args[1].lower() if len(args) > 1 else "1h"
        if tf not in indicators.TIMEFRAMES:
            raise ValueError(f"Geçersiz TF. Geçerliler: {', '.join(indicators.TIMEFRAMES)}")
        days = int(args[2]) if len(args) > 2 else 30
        stop_pct = float(args[3]) / 100 if len(args) > 3 else 0.025
        target_pct = float(args[4]) / 100 if len(args) > 4 else 0.05

        if days < 7:
            raise ValueError("En az 7 günlük backtest gerekli.")
        if days > 365:
            raise ValueError("Binance en fazla ~1000 mum döndürüyor, büyük TF'de 365 gün sınırı.")

        log.write(
            f"[grey58]Backtest çalışıyor: {market.short_name(sym)} [{tf}] "
            f"{days} gün │ stop %{stop_pct*100:.1f} hedef %{target_pct*100:.1f}...[/]"
        )
        try:
            result = await backtest_mod.run(sym, tf, days, stop_pct, target_pct)
        except Exception as e:
            log.write(f"[red3]Backtest hatası: {e}[/]")
            return

        log.write(f"[bold cyan]── Backtest Sonucu ──[/]")
        log.write(result.summary())
        sig = backtest_mod.significance(result.wins, result.n_trades)
        log.write(f"  İstatistiksel anlam: {sig.verdict}")
        if result.n_trades == 0:
            log.write("[dark_orange]⚠ Bu periyotta hiç AL sinyali üretilmedi — TF veya süreyi değiştir.[/]")
        elif result.profit_factor >= 1.5 and result.win_rate >= 50:
            log.write("[green3]✔ Strateji bu dönemde karlı görünüyor. Walk-forward ile de doğrula: /backtest wf[/]")
        elif result.total_return_pct < 0 or result.profit_factor < 1.0:
            log.write("[red3]✗ Strateji bu dönemde zararlı. Parametreleri ayarla veya farklı TF dene.[/]")
        else:
            log.write("[gold3]~ Strateji sınırda. /backtest wf ile walk-forward testi önerilir.[/]")

    # ── Pozisyon boyutlama komutu ────────────────────────────────────────────

    async def _cmd_boyut(self, args: list[str]) -> None:
        """
        /boyut SEMBOL STOP% [RİSK%]
        Sermayenin RİSK%'ini riske edecek şekilde kaç USDT alman gerektiğini hesaplar.

        Örn: /boyut BTC 2.5      → %1 sermaye riskiyle, %2.5 stop ile kaç USDT?
        Örn: /boyut BTC 2.5 1.5  → %1.5 sermaye riski
        """
        log = self.query_one("#log", RichLog)
        if len(args) < 2:
            raise ValueError(
                "Kullanım: /boyut SEMBOL STOP_PCT [RİSK_PCT]\n"
                "Örn: /boyut BTC 2.5    (stop=%2.5, risk=%1 — sermayenin)\n"
                "Örn: /boyut ETH 3 1.5  (stop=%3, risk=%1.5)"
            )
        sym = market.resolve_symbol(args[0])
        stop_pct = float(args[1].replace(",", ".")) / 100
        risk_pct = float(args[2].replace(",", ".")) / 100 if len(args) > 2 else 0.01

        if stop_pct <= 0 or stop_pct > 0.5:
            raise ValueError("Stop %0.1–%50 arasında olmalı.")
        if risk_pct <= 0 or risk_pct > 0.2:
            raise ValueError("Risk %0.1–%20 arasında olmalı.")

        # Anlık fiyat
        price = self.feed.price(sym) or await self._price_of(sym)
        equity = self.portfolio.equity({sym: price})

        # Fixed-fractional pozisyon boyutu:
        # amount = equity × risk_pct / stop_pct
        amount_usdt = equity * risk_pct / stop_pct
        amount_usdt = min(amount_usdt, self.portfolio.cash)  # nakitten fazlasını gösterme
        amount_coin = amount_usdt / price if price else 0

        stop_price = price * (1 - stop_pct)
        target_price_1r = price * (1 + stop_pct)          # 1:1 RR
        target_price_2r = price * (1 + stop_pct * 2)      # 1:2 RR
        target_price_3r = price * (1 + stop_pct * 3)      # 1:3 RR
        dollar_risk = amount_usdt * stop_pct
        rr2_gain = dollar_risk * 2

        log.write(
            f"[bold cyan]── Pozisyon Boyutlama: {market.short_name(sym)} ──[/]\n"
            f"  Fiyat         : [bold]{fmt_price(price)}[/]\n"
            f"  Varlık        : ${equity:,.2f}\n"
            f"  Risk / işlem  : %{risk_pct*100:.1f}  →  ${dollar_risk:,.2f} maks kayıp\n"
            f"  Stop seviyesi : {fmt_price(stop_price)}  (-%{stop_pct*100:.1f})\n"
            f"  ── Önerilen alım ──\n"
            f"  Miktar        : [bold green3]{amount_usdt:,.2f} USDT[/]  ≈ {amount_coin:.6f} {market.short_name(sym)}\n"
            f"  ── Risk/Ödül hedefleri ──\n"
            f"  1:1 RR → {fmt_price(target_price_1r)}  (+${dollar_risk:,.2f})\n"
            f"  1:2 RR → {fmt_price(target_price_2r)}  (+${rr2_gain:,.2f})  ← tavsiye edilen minimum\n"
            f"  1:3 RR → {fmt_price(target_price_3r)}  (+${dollar_risk*3:,.2f})"
        )
        log.write(
            f"[grey58]  Komut: /al {args[0].upper()} {amount_usdt:,.0f}[/]  "
            f"[grey50]→ girdikten sonra: /koru {args[0].upper()}[/]"
        )

    # ── live mod yardımcıları ────────────────────────────────────────────────

    def _exchange_creds(self) -> tuple[str, str, str]:
        """Aktif borsa için (key, secret, extra/passphrase) döndür."""
        if not self.cfg:
            return "", "", ""
        ex = getattr(self.cfg, "exchange", "binance")
        if ex == "bybit":
            return (getattr(self.cfg, "bybit_key", ""),
                    getattr(self.cfg, "bybit_secret", ""), "")
        if ex == "okx":
            return (getattr(self.cfg, "okx_key", ""),
                    getattr(self.cfg, "okx_secret", ""),
                    getattr(self.cfg, "okx_passphrase", ""))
        # binance (varsayılan)
        return self.cfg.binance_key, self.cfg.binance_secret, ""

    @property
    def _is_live(self) -> bool:
        _k, _, _ = self._exchange_creds()
        return bool(_k) and getattr(self.cfg, "trading_mode", "paper") == "live"

    async def _sync_live_balance(self) -> None:
        """Live modda gerçek USDT bakiyesini portfolio.cash ile senkronize et."""
        if not self._is_live:
            return
        try:
            _k, _s, _p = self._exchange_creds()
            real_usdt = await exchange.get_usdt_balance(_k, _s, _p)
            self.portfolio.cash = real_usdt
        except Exception:
            pass

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

    @work(exclusive=True)
    async def run_directional(self, direction: str) -> None:
        """Yönsel tarama (/tara short, /tara long, /tara scalp...)."""
        log = self.query_one("#log", RichLog)
        if self.ai_busy:
            log.write("[dark_orange]Claude zaten çalışıyor, bekle...[/]")
            return
        self.ai_busy = True
        try:
            positions = {
                s: {"miktar": p.qty, "giris": p.entry, "stop": p.stop, "hedef": p.target}
                for s, p in self.portfolio.positions.items()
            }
            dir_labels = {
                "short": "SHORT/DÜŞÜŞ",
                "long": "LONG/YÜKSELİŞ", "yukselis": "LONG/YÜKSELİŞ",
                "scalp": "SCALP", "hizli": "SCALP",
                "day": "GÜN İÇİ", "swing": "SWING",
            }
            label = dir_labels.get(direction, direction.upper())
            log.write(f"[bold cyan]── Claude {label} fırsatları arıyor... ──[/]")
            full = await ai.scan_directional(
                list(self.watchlist), self.portfolio.cash, positions, direction
            )
            summary = ai.strip_machine_lines(full)
            if summary:
                log.write(summary)

            self.pending = ai.parse_suggestions(full)
            # Yön'e göre filtre
            _dir_allowed = {
                "short":    {"SHORT_AL"},
                "long":     {"AL", "SPOT_AL"},
                "yukselis": {"AL", "SPOT_AL"},
                "scalp":    {"SCALP_AL"},
                "hizli":    {"SCALP_AL"},
            }.get(direction, {"AL", "SPOT_AL", "SHORT_AL", "SCALP_AL"})
            self.pending = [s for s in self.pending if s.islem in _dir_allowed]

            if not self.pending:
                self.pending_ids = []
                log.write(f"[grey58]Claude {label} için net bir fırsat bulamadı.[/]")
                return

            await self._record_pending_suggestions()
            log.write(f"[bold gold3]── {label} ADAYLARI ──[/]")
            _TYPE_STYLE = {
                "AL": ("[green3]LONG[/]", "green3"),
                "SPOT_AL": ("[green3]LONG[/]", "green3"),
                "SHORT_AL": ("[red3]SHORT[/]", "red3"),
                "SCALP_AL": ("[cyan]SCALP[/]", "cyan"),
            }
            for i, s in enumerate(self.pending, 1):
                type_lbl, type_color = _TYPE_STYLE.get(s.islem, ("[white]AL[/]", "white"))
                log.write(
                    f"  [{type_color}]{i}.[/] {type_lbl} [bold]{market.short_name(s.sembol)}[/] "
                    f"%{s.basari_yuzdesi} güven | "
                    f"[red3]stop {fmt_price(s.zarar_kes)}[/] / [green3]hedef {fmt_price(s.kar_al)}[/]"
                )
                log.write(f"     [grey58]{s.gerekce}[/]")
            log.write(
                "[bold]Seçim: /onayla 1   hepsi: /onayla hepsi   vazgeç: /reddet[/]"
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

    def _poll_web_flags(self) -> None:
        """S-2/S-3: Web UI'dan gelen değişiklikleri 5 saniyede bir kontrol et."""
        try:
            # S-2: Web UI'dan alım/satım yapıldıysa tabloyu yenile
            ui_flag = Path(__file__).parent / ".ui_update_flag"
            if ui_flag.exists():
                try:
                    ui_flag.unlink()
                except Exception:
                    pass
                self.portfolio = self.portfolio.__class__.load()
                if self._auto_engine:
                    self._auto_engine.portfolio = self.portfolio
                self.refresh_tables()

            # WS bağlantı durumunu state dosyasına yaz (web UI okur)
            try:
                _state_path = Path(__file__).parent / "autonomous_state.json"
                _st = json.loads(_state_path.read_text()) if _state_path.exists() else {}
                _ws_now = self.feed.ws_connected if self.feed.crypto_symbols else True
                if _st.get("ws_connected") != _ws_now:
                    _st["ws_connected"] = _ws_now
                    _state_path.write_text(json.dumps(_st, ensure_ascii=False, indent=2))
            except Exception:
                pass

            # S-3: Web UI'dan otonom mod değiştirildiyse motoru başlat/durdur
            if self._auto_engine:
                from autonomous import AutonomousState, STATE_FILE
                state = AutonomousState.load(STATE_FILE)
                was_enabled = self._auto_engine.state.enabled
                if state.enabled and not was_enabled:
                    self.run_worker(self._web_start_auto(), exclusive=False)
                elif not state.enabled and was_enabled:
                    self.run_worker(self._web_stop_auto(), exclusive=False)
        except Exception:
            pass

    async def _web_start_auto(self) -> None:
        """Web UI'dan gelen 'otonom aç' sinyalini işle."""
        if not self._auto_engine:
            return
        log = self.query_one("#log", RichLog)
        msg = await self._auto_engine.start()
        log.write(f"[bold green3][Web] {msg}[/]")
        self.notify("Otonom mod web'den açıldı", timeout=4)

    async def _web_stop_auto(self) -> None:
        """Web UI'dan gelen 'otonom kapat' sinyalini işle."""
        if not self._auto_engine:
            return
        log = self.query_one("#log", RichLog)
        msg = await self._auto_engine.stop("Web UI'dan kapatıldı")
        log.write(f"[bold dark_orange][Web] {msg}[/]")

    def check_protections(self) -> None:
        try:
            prices = {s: tk.price for s, tk in self.feed.tickers.items()
                      if tk.price > 0}
            # Fiyat alarmlarını kontrol et
            if self._price_alerts:
                self.run_worker(self._check_price_alerts(prices), exclusive=False)
            # Paper limit emirleri kontrol et
            if not self._is_live and self._order_book.pending():
                self.run_worker(self._check_limit_fills(prices), exclusive=False)
            triggers = self.portfolio.check_triggers(prices)
            if not triggers:
                return
            log = self.query_one("#log", RichLog)
            for sym, kind, price in triggers:
                if self._is_live:
                    self.run_worker(self._live_close_position(sym, kind, price), exclusive=False)
                else:
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

    async def _check_price_alerts(self, prices: dict[str, float]) -> None:
        """Fiyat alarmlarını kontrol et ve tetiklenenleri uygula."""
        log = self.query_one("#log", RichLog)
        triggered: list[tuple] = []
        for sym in list(self._price_alerts.keys()):
            price = prices.get(sym) or self.feed.price(sym)
            if not price:
                continue
            remaining = []
            for direction, target, action, amount in self._price_alerts[sym]:
                hit = (
                    (direction == "asagi" and price <= target)
                    or (direction == "yukari" and price >= target)
                )
                if hit:
                    triggered.append((sym, direction, target, action, amount, price))
                else:
                    remaining.append((direction, target, action, amount))
            if remaining:
                self._price_alerts[sym] = remaining
            else:
                del self._price_alerts[sym]

        for sym, direction, target, action, amount, price in triggered:
            yön = "≤" if direction == "asagi" else "≥"
            log.write(
                f"[bold gold3]⚡ FİYAT ALARMI[/] "
                f"[white]{market.short_name(sym)}[/] {yön} {fmt_price(target)} "
                f"→ şu an [bold]{fmt_price(price)}[/]"
            )
            if action == "bildir":
                self.notify(f"⚡ {market.short_name(sym)} {yön} {fmt_price(target)}", timeout=8)
                asyncio.ensure_future(notify.get().send(
                    f"⚡ <b>FİYAT ALARMI</b>  {market.short_name(sym)} {yön} {fmt_price(target)}\n"
                    f"Şu an: <b>{fmt_price(price)}</b>"
                ))
            elif action == "al":
                log.write(f"[cyan]⚡ Otomatik alım: {amount} USDT {market.short_name(sym)}...[/]")
                try:
                    if self._is_live:
                        _k, _s, _p = self._exchange_creds()
                        fp, fq, fu = await exchange.place_market_buy(_k, _s, sym, amount, _p)
                        self.portfolio.buy(sym, fu, fp)
                        await self._sync_live_balance()
                        log.write(f"[green3]⚡ ALINDI: {fq:.6f} @ {fmt_price(fp)} ({fu:,.2f} USDT)[/]")
                        asyncio.ensure_future(notify.get().notify_buy(sym, fq, fp, fu, True))
                    else:
                        p2 = self.feed.price(sym) or price
                        res = self.portfolio.buy(sym, amount, p2)
                        log.write(f"[green3]⚡ {res}[/]")
                    await self._sync_feed()
                except Exception as e:
                    log.write(f"[red3]⚡ Otomatik alım hatası: {e}[/]")
            elif action == "sat":
                pos = self.portfolio.positions.get(sym)
                if pos:
                    log.write(f"[dark_orange]⚡ Otomatik satım: {market.short_name(sym)}...[/]")
                    try:
                        if self._is_live:
                            _k, _s, _p = self._exchange_creds()
                            fp, fq, fu = await exchange.place_market_sell(_k, _s, sym, pos.qty, _p)
                            _pnl_pct = ((fp - pos.entry) / pos.entry * 100) if pos.entry else 0
                            self.portfolio.sell(sym, fp)
                            await self._sync_live_balance()
                            log.write(f"[dark_orange]⚡ SATILDI: {fq:.6f} @ {fmt_price(fp)} ({fu:,.2f} USDT)[/]")
                            asyncio.ensure_future(notify.get().notify_sell(sym, fq, fp, fu, _pnl_pct, True))
                        else:
                            p2 = self.feed.price(sym) or price
                            res = self.portfolio.sell(sym, p2)
                            log.write(f"[dark_orange]⚡ {res}[/]")
                        await self._sync_feed()
                    except Exception as e:
                        log.write(f"[red3]⚡ Otomatik satım hatası: {e}[/]")
                else:
                    log.write(f"[dark_orange]⚡ {market.short_name(sym)} pozisyonu yok, satım atlandı.[/]")

    async def _cmd_fiyat(self, args: list[str]) -> None:
        """
        /fiyat al SEMBOL TUTAR HEDEF_FIYAT   → fiyat hedefe düşünce 'TUTAR' USDT al
        /fiyat sat SEMBOL HEDEF_FIYAT          → fiyat hedefe çıkınca pozisyonu sat
        /fiyat bildir SEMBOL HEDEF_FIYAT       → sadece bildir (işlem yapmaz)
        /fiyat liste                           → aktif alarmları listele
        /fiyat sil [SEMBOL]                    → alarmları sil
        """
        log = self.query_one("#log", RichLog)
        sub = args[0].lower() if args else "liste"

        if sub == "liste":
            if not self._price_alerts:
                log.write("[grey58]Aktif fiyat alarmı yok.[/]  /fiyat al|sat|bildir ile ekle")
                return
            log.write("[bold cyan]── Aktif Fiyat Alarmları ──[/]")
            for sym, alerts in self._price_alerts.items():
                for direction, target, action, amount in alerts:
                    yön = "↓≤" if direction == "asagi" else "↑≥"
                    act_str = f"AL {amount} USDT" if action == "al" else ("SAT" if action == "sat" else "BİLDİR")
                    log.write(f"  [white]{market.short_name(sym)}[/] {yön} [bold]{fmt_price(target)}[/] → {act_str}")
            return

        elif sub == "sil":
            if len(args) > 1:
                sym = market.resolve_symbol(args[1])
                removed = self._price_alerts.pop(sym, [])
                log.write(f"[dark_orange]{market.short_name(sym)} için {len(removed)} alarm silindi.[/]")
            else:
                count = sum(len(v) for v in self._price_alerts.values())
                self._price_alerts.clear()
                log.write(f"[dark_orange]{count} alarm silindi.[/]")
            return

        elif sub == "al":
            if len(args) < 4:
                raise ValueError("Kullanım: /fiyat al SEMBOL TUTAR HEDEF_FIYAT\n"
                                 "Örn: /fiyat al BTC 500 90000  (BTC 90000'e düşünce 500$ al)")
            sym = market.resolve_symbol(args[1])
            amount = float(args[2].replace(",", "."))
            target = float(args[3].replace(",", "."))
            cur = self.feed.price(sym) or 0
            direction = "asagi" if (not cur or target < cur) else "yukari"
            self._price_alerts.setdefault(sym, []).append((direction, target, "al", amount))
            yön_str = f"≤ {fmt_price(target)} (düşünce)" if direction == "asagi" else f"≥ {fmt_price(target)} (çıkınca)"
            log.write(f"[green3]⚡ Alarm kuruldu:[/] {market.short_name(sym)} {yön_str} → "
                      f"[bold]{amount:,.0f} USDT al[/]")

        elif sub == "sat":
            if len(args) < 3:
                raise ValueError("Kullanım: /fiyat sat SEMBOL HEDEF_FIYAT\n"
                                 "Örn: /fiyat sat BTC 110000  (BTC 110000'e çıkınca sat)")
            sym = market.resolve_symbol(args[1])
            target = float(args[2].replace(",", "."))
            cur = self.feed.price(sym) or 0
            direction = "yukari" if (not cur or target > cur) else "asagi"
            self._price_alerts.setdefault(sym, []).append((direction, target, "sat", 0))
            yön_str = f"≥ {fmt_price(target)} (çıkınca)" if direction == "yukari" else f"≤ {fmt_price(target)} (düşünce)"
            log.write(f"[dark_orange]⚡ Alarm kuruldu:[/] {market.short_name(sym)} {yön_str} → "
                      f"[bold]pozisyonu sat[/]")

        elif sub in ("bildir", "uyar", "alert"):
            if len(args) < 3:
                raise ValueError("Kullanım: /fiyat bildir SEMBOL HEDEF_FIYAT\n"
                                 "Örn: /fiyat bildir BTC 100000")
            sym = market.resolve_symbol(args[1])
            target = float(args[2].replace(",", "."))
            cur = self.feed.price(sym) or 0
            direction = "asagi" if (cur and target < cur) else "yukari"
            self._price_alerts.setdefault(sym, []).append((direction, target, "bildir", 0))
            yön_str = f"≤ {fmt_price(target)}" if direction == "asagi" else f"≥ {fmt_price(target)}"
            log.write(f"[cyan]⚡ Bildirim alarmı:[/] {market.short_name(sym)} {yön_str}")

        else:
            raise ValueError(
                "Alt komutlar: /fiyat al SEMBOL TUTAR HEDEF  |  /fiyat sat SEMBOL HEDEF\n"
                "              /fiyat bildir SEMBOL HEDEF    |  /fiyat liste  |  /fiyat sil"
            )

    # ── Limit emir yönetimi (paper) ──────────────────────────────────────────

    async def _check_limit_fills(self, prices: dict[str, float]) -> None:
        """Paper limit emirleri fiyat kontrolü — doldurulanları uygula."""
        log = self.query_one("#log", RichLog)
        filled = self._order_book.check_fills(prices)
        for order, fill_price in filled:
            sym = order.symbol
            slip = fill_price * 1.001 if order.side == "AL" else fill_price * 0.999
            if order.side == "AL":
                try:
                    res = self.portfolio.buy(sym, order.amount_usdt, slip)
                    log.write(
                        f"[bold green3]⚡ LİMİT DOLDU [AL][/] {order.id[:8]}  "
                        f"{market.short_name(sym)} @ {fmt_price(slip)}"
                    )
                    log.write(f"  {res}")
                    await self._sync_feed()
                    self.run_protect(sym)
                except Exception as e:
                    log.write(f"[red3]Limit AL hatası: {e}[/]")
            else:  # SAT
                pos = self.portfolio.positions.get(sym)
                if pos:
                    try:
                        res = self.portfolio.sell(sym, slip)
                        log.write(
                            f"[bold dark_orange]⚡ LİMİT DOLDU [SAT][/] {order.id[:8]}  "
                            f"{market.short_name(sym)} @ {fmt_price(slip)}"
                        )
                        log.write(f"  {res}")
                        await self._sync_feed()
                    except Exception as e:
                        log.write(f"[red3]Limit SAT hatası: {e}[/]")

    async def _cmd_limit(self, args: list[str]) -> None:
        """
        /limit al SEMBOL TUTAR LİMİT_FİYAT [SAAT]  → fiyat hedefe düşünce al
        /limit sat SEMBOL FİYAT [SAAT]               → fiyat hedefe çıkınca sat
        /limit liste                                 → bekleyen emirler
        /limit iptal [ID|SEMBOL|hepsi]               → iptal et
        """
        log = self.query_one("#log", RichLog)
        sub = args[0].lower() if args else "liste"

        if sub == "liste":
            pending = self._order_book.pending()
            if not pending:
                log.write("[grey58]Bekleyen limit emir yok.[/]  /limit al veya /limit sat ile ekle")
                return
            log.write(f"[bold cyan]── Bekleyen Limit Emirler ({len(pending)}) ──[/]")
            for o in pending:
                log.write(f"  {o.summary()}")
            return

        elif sub in ("iptal", "cancel"):
            target = args[1].lower() if len(args) > 1 else "hepsi"
            if target == "hepsi":
                n = self._order_book.cancel_all()
                log.write(f"[dark_orange]{n} limit emir iptal edildi.[/]")
            else:
                # Sembol mi yoksa ID mi?
                try:
                    sym = market.resolve_symbol(target)
                    n = self._order_book.cancel_symbol(sym)
                    log.write(f"[dark_orange]{sym} için {n} emir iptal edildi.[/]")
                except Exception:
                    cancelled = self._order_book.cancel(target)
                    log.write(f"[dark_orange]{len(cancelled)} emir iptal edildi.[/]")
            return

        elif sub == "al":
            if len(args) < 4:
                raise ValueError(
                    "Kullanım: /limit al SEMBOL TUTAR LİMİT_FİYAT [SAAT]\n"
                    "Örn: /limit al BTC 500 103000     → BTC 103000'e düşünce 500 USDT al\n"
                    "Örn: /limit al ETH 200 3400 48    → 48 saat geçerli"
                )
            sym = market.resolve_symbol(args[1])
            amount = float(args[2].replace(",", "."))
            limit_price = float(args[3].replace(",", "."))
            expiry = float(args[4]) if len(args) > 4 else 24.0
            cur = self.feed.price(sym)
            if cur and limit_price >= cur:
                log.write(f"[gold3]Uyarı: limit {fmt_price(limit_price)} ≥ şu an {fmt_price(cur)} — "
                           "fiyat zaten bu seviyede veya üstünde, hemen dolabilir[/]")
            order = self._order_book.add_buy(sym, limit_price, amount, expiry)
            log.write(
                f"[green3]✔ Limit AL emri eklendi[/] [{order.id[:8]}]\n"
                f"  {market.short_name(sym)} ≤ {fmt_price(limit_price)} → "
                f"{amount:,.0f} USDT al  ({expiry:.0f}sa geçerli)"
            )

        elif sub == "sat":
            if len(args) < 3:
                raise ValueError(
                    "Kullanım: /limit sat SEMBOL LİMİT_FİYAT [SAAT]\n"
                    "Örn: /limit sat BTC 110000    → BTC 110000'e çıkınca pozisyonu sat"
                )
            sym = market.resolve_symbol(args[1])
            limit_price = float(args[2].replace(",", "."))
            expiry = float(args[3]) if len(args) > 3 else 24.0
            pos = self.portfolio.positions.get(sym)
            if not pos:
                raise ValueError(f"{market.short_name(sym)} pozisyonu yok — önce al, sonra limit sat koy.")
            order = self._order_book.add_sell(sym, limit_price, pos.qty, expiry)
            log.write(
                f"[dark_orange]✔ Limit SAT emri eklendi[/] [{order.id[:8]}]\n"
                f"  {market.short_name(sym)} ≥ {fmt_price(limit_price)} → "
                f"{pos.qty:.6f} coin sat  ({expiry:.0f}sa geçerli)"
            )

        else:
            raise ValueError(
                "Alt komutlar: /limit al SEMBOL TUTAR FİYAT  |  /limit sat SEMBOL FİYAT\n"
                "              /limit liste  |  /limit iptal [ID|SEMBOL|hepsi]"
            )

    # ── Strateji komutu ──────────────────────────────────────────────────────

    async def _cmd_strateji(self, args: list[str]) -> None:
        """
        /strateji                → aktif stratejiyi göster
        /strateji liste          → tüm stratejileri açıkla
        /strateji momentum|dönüş|kırılım|konsensüs  → aktif stratejiyi değiştir
        /strateji analiz SEMBOL  → SEMBOL için tüm stratejileri çalıştır
        """
        log = self.query_one("#log", RichLog)
        sub = args[0].lower() if args else ""

        if not sub or sub == "göster":
            active = getattr(self.cfg, "active_strategy", "konsensüs") if self.cfg else "konsensüs"
            log.write(
                f"[bold cyan]Aktif strateji:[/] [bold]{active.upper()}[/]  "
                f"— {strategies_mod.STRATEGY_NAMES.get(active, active)}\n"
                "[grey58]/strateji liste  |  /strateji momentum|dönüş|kırılım|konsensüs[/]"
            )
            return

        elif sub == "liste":
            log.write("[bold cyan]── Strateji Modları ──[/]")
            active = getattr(self.cfg, "active_strategy", "konsensüs") if self.cfg else "konsensüs"
            descs = {
                "momentum": "Trend takibi — EMA crossover + MACD. Güçlü trendlerde çalışır.",
                "dönüş":    "Ortalamaya dönüş — RSI + Bollinger. Yatay piyasada daha iyi.",
                "kırılım":  "Breakout — Hacim + fiyat kırılımı. Volatil piyasada fırsat arar.",
                "konsensüs":"3 stratejiyi ağırlıklandırır — en dengeli seçenek (tavsiye).",
            }
            for name, desc in descs.items():
                marker = "[bold green3]→[/] " if name == active else "  "
                log.write(f"{marker}[bold]{name:12}[/] {desc}")
            return

        elif sub == "analiz":
            if len(args) < 2:
                raise ValueError("Kullanım: /strateji analiz SEMBOL")
            sym = market.resolve_symbol(args[1])
            log.write(f"[grey58]Strateji analizi: {market.short_name(sym)}...[/]")
            try:
                ta = await indicators.analyze(sym, "1h")
            except Exception as e:
                log.write(f"[red3]TA hatası: {e}[/]")
                return
            results = strategies_mod.evaluate_all(ta)
            log.write(f"[bold cyan]── Strateji Analizi: {market.short_name(sym)} [1h] ──[/]")
            for r in results:
                sc = r.score
                c = "green3" if sc > 0 else ("red3" if sc < 0 else "gold3")
                log.write(
                    f"  [bold]{r.name:18}[/] [{c}]{r.signal:<12}[/] "
                    f"skor:{sc:+d}  güven:%{r.confidence:.0f}"
                )
                for reason in r.reasons[:3]:
                    log.write(f"    · {reason}")
            return

        elif sub in strategies_mod.STRATEGIES:
            if not self.cfg:
                raise ValueError("Yapılandırma yüklenemedi.")
            self.cfg.active_strategy = sub  # type: ignore[attr-defined]
            self.cfg.save()
            log.write(f"[green3]✔ Strateji değişti:[/] [bold]{sub.upper()}[/]  "
                      f"— {strategies_mod.STRATEGY_NAMES[sub]}")
        else:
            raise ValueError(
                f"Geçersiz strateji. Geçerliler: {', '.join(strategies_mod.STRATEGIES)}"
            )

    # ── Risk komutu ──────────────────────────────────────────────────────────

    def _cmd_risk(self) -> None:
        """Portföy risk dashboardu."""
        log = self.query_one("#log", RichLog)
        prices = {s: tk.price for s, tk in self.feed.tickers.items() if tk.price > 0}
        log.write(risk_mod.risk_dashboard(self.portfolio, prices))

    # ── MTF komutu ───────────────────────────────────────────────────────────

    async def _cmd_mtf(self, args: list[str]) -> None:
        """
        /mtf SEMBOL  → 4 zaman dilimi (15m, 1h, 4h, 1d) aynı anda analiz et
        """
        log = self.query_one("#log", RichLog)
        if not args:
            raise ValueError("Kullanım: /mtf SEMBOL  (örn: /mtf BTC)")
        sym = market.resolve_symbol(args[0])
        log.write(f"[grey58]MTF analiz: {market.short_name(sym)} [15m·1h·4h·1d]...[/]")
        try:
            result = await indicators.multi_timeframe(sym)
            log.write(result)
        except Exception as e:
            log.write(f"[red3]MTF hatası: {e}[/]")

    async def _live_close_position(self, sym: str, kind: str, trigger_price: float) -> None:
        """Live modda stop/target tetiklenince borsada market sell gönder."""
        log = self.query_one("#log", RichLog)
        pos = self.portfolio.positions.get(sym)
        if not pos:
            return
        _k, _s, _p = self._exchange_creds()
        _ex = getattr(self.cfg, "exchange", "binance").upper()
        try:
            await exchange.cancel_open_orders(_k, _s, sym, _p)
            fp, _fq, _fu = await exchange.place_market_sell(_k, _s, sym, pos.qty, _p)
            result = self.portfolio.sell(sym, fp)
            _entry = pos.entry if pos else 0
            _pnl_pct = ((fp - _entry) / _entry * 100) if _entry else 0
            if kind == "stop":
                log.write(f"[bold white on red3] ZARAR KESİLDİ [/] "
                          f"[red3]{market.short_name(sym)} @ {fmt_price(fp)}[/]")
                self.notify(f"✕ {market.short_name(sym)}: ZARAR KESİLDİ", severity="warning", timeout=6)
                asyncio.ensure_future(notify.get().notify_stop(sym, fp, _pnl_pct))
            else:
                log.write(f"[bold black on green3] KÂR ALINDI [/] "
                          f"[green3]{market.short_name(sym)} @ {fmt_price(fp)}[/]")
                self.notify(f"✔ {market.short_name(sym)}: KÂR ALINDI", severity="information", timeout=5)
                asyncio.ensure_future(notify.get().notify_target(sym, fp, _pnl_pct))
            log.write(f"   {result}")
            await self._sync_live_balance()
        except Exception as e:
            log.write(f"[red3][{_ex}] {market.short_name(sym)} kapatma hatası: {e}[/]")

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
                symbol, pos.entry, pos.qty, self.portfolio.cash, pos.direction
            )
            prot = ai.parse_protection(full)
            if not prot:
                log.write(
                    "[red3]Koruma seviyesi alınamadı; /koru ile tekrar dene.[/]"
                )
                return
            stop, target = sanitize_levels(
                pos.entry, prot.zarar_kes, prot.kar_al, pos.direction
            )
            if symbol not in self.portfolio.positions:
                return
            self.portfolio.set_protection(symbol, stop, target)
            log.write(
                f"[bold]{market.short_name(symbol)} koruması:[/] "
                f"[red3]stop {fmt_price(stop)}[/] / "
                f"[green3]hedef {fmt_price(target)}[/]"
            )
            if prot.gerekce:
                log.write(f"   [grey58]{prot.gerekce}[/]")
            # Live modda OCO/TP+SL emri gönder
            if self._is_live:
                _k, _s, _p = self._exchange_creds()
                _ex = getattr(self.cfg, "exchange", "binance").upper()
                try:
                    await exchange.cancel_open_orders(_k, _s, symbol, _p)
                    await exchange.place_oco_sell(_k, _s, symbol, pos.qty, target, stop, _p)
                    log.write(
                        f"[green3]TP+SL emri {_ex}'e gönderildi:[/] "
                        f"take-profit {fmt_price(target)} / stop {fmt_price(stop)}"
                    )
                except Exception as e:
                    log.write(f"[dark_orange]{_ex} OCO emir hatası: {e} — "
                              f"yerel koruma aktif (app stop izliyor).[/]")
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

        # ── Profesyonel performans raporu (trade history bazlı) ──
        log.write(perf_mod.full_report(self.portfolio.history))

        # ── AI öneri performansı (tracker bazlı) ──
        if self.tracker.recs:
            log.write("[grey58]Fiyatlar çekiliyor...[/]")
            prices = await self._tracker_prices()
            st = self.tracker.stats(prices)
            table = Table(
                title="AI ÖNERİ PERFORMANSI", title_style="bold cyan",
                show_header=False, border_style="grey37",
            )
            table.add_column(style="bold")
            table.add_column(justify="right")
            table.add_row("Toplam öneri", str(st["toplam_oneri"]))
            table.add_row("Onaylanan", str(st["onaylanan"]))
            table.add_row("Kazanan", Text(str(st["kazanan"]), style="green3"))
            table.add_row("Kaybeden", Text(str(st["kaybeden"]), style="red3"))
            pnl = st["toplam_pnl"]
            table.add_row(
                "Toplam sanal PnL",
                Text(f"{'+' if pnl >= 0 else ''}{pnl:,.2f} USDT",
                     style="green3" if pnl >= 0 else "red3"),
            )
            if st["basari_orani"] is not None:
                table.add_row(
                    "AI başarı oranı",
                    Text(f"%{st['basari_orani']:.0f}",
                         style="green3" if st["basari_orani"] >= 50 else "red3")
                )
            log.write(table)

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

    async def on_unmount(self) -> None:
        bot = notify.get_bot()
        bot_task = bot._task
        bot.stop()
        if self._auto_engine:
            await self._auto_engine.stop()
        await self.feed.stop()
        if bot_task and not bot_task.done():
            await asyncio.gather(bot_task, return_exceptions=True)


if __name__ == "__main__":
    try:
        TradeApp().run()
    except KeyboardInterrupt:
        pass
