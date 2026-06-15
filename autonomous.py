"""Otonom paper trading döngüsü.

GÜVENLİK: Bu modül gerçek emir GÖNDERMEz.
create_order veya futures_create_order çağrılırsa REAL_ORDER_DISABLED hatası fırlatır.
Live bağlantı olsa bile tüm işlemler sanal hesapta (paper) kalır.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import ai
import config
import indicators
import market
from portfolio import (
    Portfolio, calc_liquidation_price, sanitize_levels,
    validate_leverage_trade, validate_stop_update,
    MAX_LEVERAGE,
)


# ── Otonom risk profilleri ───────────────────────────────────────────────────
@dataclass(frozen=True)
class AutonomousProfile:
    key: str
    name: str
    max_open_positions: int
    max_trade_percent: float           # tek işlem: nakitin bu oranı (0.05 = %5)
    max_total_exposure_percent: float  # toplam açık risk: portföyün bu oranı
    max_daily_trades: int
    min_confidence: int
    min_risk_reward: float
    max_consecutive_losses: int
    daily_loss_limit_percent: float
    # Kaldıraç parametreleri
    max_leverage: int = 0              # 0 = kaldıraç yok
    leverage_min_confidence: int = 75
    leverage_min_rr: float = 2.5
    leverage_max_risk_pct: float = 0.005  # portföyün %0.5'i / işlem


AUTONOMOUS_PROFILES: dict[str, AutonomousProfile] = {
    "guvenli": AutonomousProfile(
        key="guvenli", name="GÜVENLİ",
        max_open_positions=1,
        max_trade_percent=0.05,
        max_total_exposure_percent=0.10,
        max_daily_trades=1,
        min_confidence=65,
        min_risk_reward=2.0,
        max_consecutive_losses=1,
        daily_loss_limit_percent=1.0,
        max_leverage=2,
        leverage_min_confidence=75,
        leverage_min_rr=2.5,
        leverage_max_risk_pct=0.005,
    ),
    "dengeli": AutonomousProfile(
        key="dengeli", name="DENGELİ",
        max_open_positions=2,
        max_trade_percent=0.10,
        max_total_exposure_percent=0.25,
        max_daily_trades=3,
        min_confidence=55,
        min_risk_reward=1.5,
        max_consecutive_losses=2,
        daily_loss_limit_percent=2.0,
        max_leverage=3,
        leverage_min_confidence=72,
        leverage_min_rr=2.2,
        leverage_max_risk_pct=0.005,
    ),
    "agresif": AutonomousProfile(
        key="agresif", name="AGRESİF",
        max_open_positions=3,
        max_trade_percent=0.15,
        max_total_exposure_percent=0.40,
        max_daily_trades=5,
        min_confidence=50,
        min_risk_reward=1.3,
        max_consecutive_losses=4,
        daily_loss_limit_percent=3.0,
        max_leverage=5,
        leverage_min_confidence=70,
        leverage_min_rr=2.0,
        leverage_max_risk_pct=0.01,
    ),
}

DEFAULT_AUTONOMOUS_MODE = "dengeli"
MAX_CONFIDENCE = 80  # tüm modlarda sabit üst sınır

SCAN_INTERVAL = 900         # 15 dakika (normal mod)
SCALP_SCAN_INTERVAL = 180   # 3 dakika (scalp modu — daha hızlı tarama)
ANALYSIS_INTERVAL = 300     # 5 dakika
PRICE_CHECK_INTERVAL = 2    # 2 saniye

LOG_FILE = Path(__file__).parent / "autonomous_log.jsonl"
STATE_FILE = Path(__file__).parent / "autonomous_state.json"


# ── Durum kalıcılığı ─────────────────────────────────────────────────────────
CIRCUIT_BREAKER_COOLDOWN = 7200  # 2 saat (saniye)


@dataclass
class AutonomousState:
    enabled: bool = False
    daily_trades: int = 0
    consecutive_losses: int = 0
    daily_start_equity: float = 0.0
    daily_date: str = ""
    risk_locked: bool = False
    daily_leveraged_trades: int = 0   # günlük kaldıraçlı işlem sayacı
    daily_leverage_locked: bool = False  # kaldıraçlı kayıp sonrası kilit
    cooldown_until: float = 0.0       # ardışık zarar sonrası 2s tarama duraklaması
    last_scan_time: float = 0.0       # son tarama zamanı
    last_analysis_time: float = 0.0   # son pozisyon analizi zamanı

    def save(self, path: Path = STATE_FILE) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def load(cls, path: Path = STATE_FILE) -> "AutonomousState":
        if path.exists():
            try:
                d = json.loads(path.read_text())
                return cls(**{k: v for k, v in d.items()
                              if k in cls.__dataclass_fields__})
            except Exception:
                pass
        return cls()


# ── Ana motor ────────────────────────────────────────────────────────────────
class AutonomousEngine:
    """Otonom paper trading motoru.

    Paper only — live bağlantı olsa bile gerçek emir gönderilmez.
    """

    def __init__(
        self,
        portfolio: Portfolio,
        feed,           # market.MarketFeed
        tracker,        # tracker.Tracker
        cfg,            # config.Config
        log_fn: Callable[[str], None],
        watchlist_fn: Callable[[], list[str]],
        sync_feed_fn: Callable[[], None] | None = None,
        state_path: Path = STATE_FILE,
        log_path: Path = LOG_FILE,
        live_buy_fn=None,   # async (sym, usdt) → (fill_price, fill_qty, fill_usdt)
        live_sell_fn=None,  # async (sym, qty)  → (fill_price, fill_qty, fill_usdt)
    ) -> None:
        self.portfolio = portfolio
        self.feed = feed
        self.tracker = tracker
        self.cfg = cfg
        self.log = log_fn
        self.get_watchlist = watchlist_fn
        self.sync_feed = sync_feed_fn
        self.live_buy_fn = live_buy_fn
        self.live_sell_fn = live_sell_fn
        self._state_path = state_path
        self._log_path = log_path
        self.state = AutonomousState.load(state_path)
        self.state.enabled = False  # her başlangıçta kapalı
        self.state.save(state_path)  # dosyaya yaz → _poll_web_flags stale enabled görmesin
        self._task: asyncio.Task | None = None
        self._history_len = len(portfolio.history)
        self.position_decisions: dict[str, str] = {}

    # ── public API ──────────────────────────────────────────────────────────

    @property
    def profile(self) -> AutonomousProfile:
        mode_key = getattr(self.cfg, "autonomous_mode", DEFAULT_AUTONOMOUS_MODE)
        return AUTONOMOUS_PROFILES.get(mode_key, AUTONOMOUS_PROFILES[DEFAULT_AUTONOMOUS_MODE])

    @property
    def effective_profile(self) -> AutonomousProfile:
        """Custom cfg ayarlarını profil üzerine uygular."""
        import dataclasses
        p = self.profile
        cfg = self.cfg
        # Custom ayarlar 0 değilse profil değerini geç
        max_pos = getattr(cfg, "custom_max_positions", 0) or p.max_open_positions
        max_trades = getattr(cfg, "custom_max_daily_trades", 0) or p.max_daily_trades
        loss_streak = getattr(cfg, "custom_loss_streak", 0) or p.max_consecutive_losses
        daily_loss = getattr(cfg, "custom_daily_loss_pct", 0.0) or p.daily_loss_limit_percent

        if (max_pos != p.max_open_positions or max_trades != p.max_daily_trades or
                loss_streak != p.max_consecutive_losses or
                daily_loss != p.daily_loss_limit_percent):
            return dataclasses.replace(
                p,
                max_open_positions=max_pos,
                max_daily_trades=max_trades,
                max_consecutive_losses=loss_streak,
                daily_loss_limit_percent=daily_loss,
            )
        return p

    @property
    def enabled(self) -> bool:
        return self.state.enabled

    @property
    def risk_locked(self) -> bool:
        return self.state.risk_locked

    @property
    def daily_trades(self) -> int:
        return self.state.daily_trades

    def set_mode(self, mode_key: str) -> str:
        if mode_key not in AUTONOMOUS_PROFILES:
            valid = " / ".join(AUTONOMOUS_PROFILES.keys())
            return f"Geçersiz mod: '{mode_key}'. Geçerli modlar: {valid}"
        self.cfg.autonomous_mode = mode_key
        try:
            self.cfg.save()
        except Exception:
            pass
        p = self.profile
        return (
            f"Otonom risk modu → [bold]{p.name}[/]  "
            f"(max {p.max_open_positions} pos | "
            f"min güven %{p.min_confidence} | "
            f"R/R {p.min_risk_reward})"
        )

    async def start(self) -> str:
        if self.state.enabled:
            return "Otonom mod zaten açık."
        self._check_daily_reset()
        if self.state.risk_locked:
            return ("Risk kilidi aktif (ardışık zarar veya günlük limit). "
                    "Hesabı /sifirla ile sıfırla veya yarın tekrar dene.")
        self.state.enabled = True
        self.state.save(self._state_path)
        self._history_len = len(self.portfolio.history)
        self._task = asyncio.create_task(self._loop())
        self._log_event("start", decision="AÇILDI", reason="Kullanıcı başlattı")
        return "Otonom mod açıldı."

    async def stop(self, reason: str = "Kullanıcı durdurdu") -> str:
        self.state.enabled = False
        self.state.save(self._state_path)
        if self._task:
            self._task.cancel()
            self._task = None
        self._log_event("stop", decision="KAPATILDI", reason=reason)
        return "Otonom mod kapatıldı."

    def reset_risk_lock(self) -> None:
        """Hesap sıfırlamasında risk kilidini temizle."""
        self.state.risk_locked = False
        self.state.consecutive_losses = 0
        self.state.daily_trades = 0
        self.state.save(self._state_path)

    def status_text(self) -> str:
        p = self.effective_profile
        base = self.profile
        mode_key = getattr(self.cfg, "autonomous_mode", DEFAULT_AUTONOMOUS_MODE)
        mode_colors = {
            "guvenli": "cyan",
            "dengeli": "green3",
            "agresif": "dark_orange",
        }
        mc = mode_colors.get(mode_key, "white")

        lev_status = (
            "[grey58]KAPALI[/]"
            if not getattr(self.cfg, "leverage_enabled", False)
            else (
                "[red3]KİLİTLİ[/]" if self.state.daily_leverage_locked
                else f"[gold3]AÇIK[/] (max {p.max_leverage}x | "
                     f"min güven %{p.leverage_min_confidence} | R/R {p.leverage_min_rr})"
            )
        )
        otonom_type = getattr(self.cfg, "otonom_trade_type", "long")
        _ALLOWED_MAP: dict[str, set[str]] = {
            "long":      {"AL", "SPOT_AL"},
            "short":     {"SHORT_AL"},
            "longshort": {"AL", "SPOT_AL", "SHORT_AL"},
            "scalp":     {"SCALP_AL"},
            "kaldirac":  {"AL", "SPOT_AL", "LEVERAGE_AL"},
            "tam":       {"AL", "SPOT_AL", "SHORT_AL", "SCALP_AL", "LEVERAGE_AL"},
        }
        _active_allowed = _ALLOWED_MAP.get(otonom_type, {"AL", "SPOT_AL"})
        _TYPE_LABEL = {
            "long": "LONG", "short": "SHORT",
            "longshort": "LONG+SHORT", "scalp": "SCALP",
            "kaldirac": "KALDIRAÇ", "tam": "LONG+SHORT+SCALP+LEV",
        }
        trade_type_label = _TYPE_LABEL.get(otonom_type, otonom_type.upper())
        lines = [
            f"[bold]Otonom:[/] {'[green3]AÇIK[/]' if self.state.enabled else '[grey58]KAPALI[/]'}",
            f"[bold]Aktif trade türü:[/] [cyan]{trade_type_label}[/]",
            f"[bold]İzinli aksiyonlar:[/] {', '.join(sorted(_active_allowed))}",
            f"[bold]Otonom risk modu:[/] [{mc}]{p.name}[/]",
            f"[bold]Bugünkü işlem:[/] {self.state.daily_trades} / {p.max_daily_trades}",
            f"[bold]Açık pozisyon:[/] {len(self.portfolio.positions)} / {p.max_open_positions}",
            f"[bold]Tek işlem limiti:[/] nakitin %{p.max_trade_percent * 100:.0f}'i",
            f"[bold]Toplam risk limiti:[/] portföyün %{p.max_total_exposure_percent * 100:.0f}'i",
            f"[bold]Confidence eşiği:[/] minimum %{p.min_confidence}",
            f"[bold]Risk/reward eşiği:[/] minimum {p.min_risk_reward}",
            f"[bold]Günlük zarar limiti:[/] %{p.daily_loss_limit_percent:.1f} → otonom kapanır",
            f"[bold]Ardışık zarar limiti:[/] {p.max_consecutive_losses} zarar → yeni işlem kilidi",
            f"[bold]Risk kilidi:[/] {'[red3]AKTİF[/]' if self.state.risk_locked else '[green3]Kapalı[/]'}",
            *(
                [f"[bold]Circuit breaker:[/] [gold3]Soğuma {int(self.state.cooldown_until - time.time())//60}dk[/]"]
                if self.state.cooldown_until and time.time() < self.state.cooldown_until
                else []
            ),
            f"[bold]Kaldıraçlı paper:[/] {lev_status}",
            f"[bold]Bugünkü kaldıraçlı:[/] {self.state.daily_leveraged_trades} / 1",
        ]
        if self.state.daily_start_equity:
            all_prices = {s: t.price for s, t in self.feed.tickers.items()
                          if t.price > 0}
            cur_eq = self.portfolio.equity(all_prices)
            daily_pnl = cur_eq - self.state.daily_start_equity
            pct = daily_pnl / self.state.daily_start_equity * 100
            color = "green3" if daily_pnl >= 0 else "red3"
            sign = "+" if daily_pnl >= 0 else ""
            lines.append(
                f"[bold]Günlük PnL:[/] [{color}]{sign}{daily_pnl:,.2f} USDT "
                f"({sign}{pct:.2f}%)[/]"
            )
        # Özel ayarlar aktifse bilgi satırı ekle
        if (p.max_open_positions != base.max_open_positions or
                p.max_daily_trades != base.max_daily_trades or
                p.max_consecutive_losses != base.max_consecutive_losses or
                p.daily_loss_limit_percent != base.daily_loss_limit_percent):
            lines.append(
                f"[gold3]⚡ Özel ayarlar aktif:[/] "
                f"max_pos={p.max_open_positions} max_trades={p.max_daily_trades} "
                f"zarar_serisi={p.max_consecutive_losses} "
                f"günlük_zarar=%{p.daily_loss_limit_percent:.0f}"
            )
        return "\n".join(lines)

    # ── iç döngü ────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        if self.state.last_scan_time == 0.0:
            self.state.last_scan_time = time.time() - SCAN_INTERVAL
        if self.state.last_analysis_time == 0.0:
            self.state.last_analysis_time = time.time() - ANALYSIS_INTERVAL

        while self.state.enabled:
            try:
                now = time.time()
                self._check_daily_reset()
                self._check_trades_from_history()
                self._check_daily_loss_limit()

                if not self.state.enabled:
                    break

                # Kaldıraçlı pozisyonlarda kâr varsa stop'u hemen break-even'e taşı
                self._check_leveraged_break_even()

                if now - self.state.last_analysis_time >= ANALYSIS_INTERVAL:
                    self.state.last_analysis_time = now
                    await self._run_position_analysis()

                _scalp_on = getattr(config.current(), "scalp_enabled", False)
                _tam_mod = getattr(config.current(), "trade_plan", "dengeli") == "tam"
                _scan_iv = SCALP_SCAN_INTERVAL if (_scalp_on or _tam_mod) else SCAN_INTERVAL
                if now - self.state.last_scan_time >= _scan_iv:
                    self.state.last_scan_time = now
                    await self._run_scan()

            except asyncio.CancelledError:
                return
            except Exception as e:
                self._log_event("error", reason=f"Döngü hatası: {e}")

            await asyncio.sleep(PRICE_CHECK_INTERVAL)

    def _check_daily_reset(self) -> None:
        today = time.strftime("%Y-%m-%d")
        if self.state.daily_date != today:
            self.state.daily_date = today
            self.state.daily_trades = 0
            self.state.consecutive_losses = 0
            self.state.risk_locked = False
            self.state.daily_leveraged_trades = 0
            self.state.daily_leverage_locked = False
            all_prices = {s: t.price for s, t in self.feed.tickers.items()
                          if t.price > 0}
            self.state.daily_start_equity = self.portfolio.equity(all_prices)
            self.state.save(self._state_path)

    def _check_trades_from_history(self) -> None:
        """Portföy geçmişindeki yeni SAT işlemlerini izle (ardışık zarar için)."""
        current_len = len(self.portfolio.history)
        if current_len <= self._history_len:
            return
        new_trades = self.portfolio.history[self._history_len:current_len]
        self._history_len = current_len
        p = self.effective_profile
        for trade in new_trades:
            side = trade.get("side", "")
            pnl = trade.get("pnl")
            if side in ("SAT", "SHORT_KAP", "LEVERAGE KAPATILDI", "LİKİDE") and pnl is not None:
                if pnl < 0:
                    self.state.consecutive_losses += 1
                    self._log_event(
                        "loss", symbol=trade.get("symbol", ""),
                        reason=(f"Zarar: {pnl:,.2f} USDT. "
                                f"Ardışık zarar: {self.state.consecutive_losses}"),
                    )
                    if self.state.consecutive_losses >= p.max_consecutive_losses:
                        # Ardışık zarar → 2 saatlik tarama duraklaması (tam kilit değil)
                        self.state.cooldown_until = time.time() + CIRCUIT_BREAKER_COOLDOWN
                        self.state.consecutive_losses = 0
                        cooldown_end = time.strftime(
                            "%H:%M", time.localtime(self.state.cooldown_until)
                        )
                        self.log(
                            f"[bold red3][OTONOM] Üst üste "
                            f"{p.max_consecutive_losses} zarar — "
                            f"2 saatlik tarama duraklaması ({cooldown_end}'a kadar).[/]"
                        )
                    # Kaldıraçlı kayıp: günlük leverage kilitlensin
                    if side in ("LEVERAGE KAPATILDI", "LİKİDE"):
                        self.state.daily_leverage_locked = True
                        self.log(
                            "[bold red3][OTONOM] Kaldıraçlı zarar — "
                            "günlük kaldıraçlı işlem kilitleniyor.[/]"
                        )
                else:
                    self.state.consecutive_losses = 0
                self.state.save(self._state_path)

    def _check_daily_loss_limit(self) -> None:
        if not self.state.daily_start_equity or self.state.risk_locked:
            return
        all_prices = {s: t.price for s, t in self.feed.tickers.items()
                      if t.price > 0}
        cur_eq = self.portfolio.equity(all_prices)
        loss_pct = ((self.state.daily_start_equity - cur_eq)
                    / self.state.daily_start_equity * 100)
        p = self.effective_profile
        if loss_pct >= p.daily_loss_limit_percent:
            self.state.enabled = False
            self.state.risk_locked = True
            self.state.save(self._state_path)
            self.log(
                f"[bold red3][OTONOM] Günlük zarar limiti "
                f"(%{p.daily_loss_limit_percent:.0f}) aşıldı "
                f"({loss_pct:.1f}%) — otonom mod kapatılıyor.[/]"
            )
            self._log_event("shutdown",
                            reason=f"Günlük zarar limiti: {loss_pct:.1f}%")

    async def apply_decision(
        self,
        sym: str,
        pd: ai.PositionDecision,
        current_price: float,
        auto: bool = False,
    ) -> tuple[bool, str]:
        """Bir pozisyon kararını uygula.

        auto=True  → otonom mod (log'da [OTONOM] prefix)
        auto=False → manuel /uygula komutu
        Döndürür: (değişiklik_yapıldı, açıklama_mesajı)
        """
        prefix = "[OTONOM] " if auto else ""

        if sym not in self.portfolio.positions:
            return False, f"{market.short_name(sym)}: pozisyon bulunamadı"

        pos = self.portfolio.positions[sym]

        if pd.karar in ("DEVAM", "BEKLE"):
            msg = f"{market.short_name(sym)} {pd.karar}: {pd.gerekce}"
            if auto:
                self._log_event("hold", symbol=sym, decision=pd.karar, reason=pd.gerekce)
                self.log(f"[grey58]{prefix}{msg}[/]")
            return False, msg

        elif pd.karar in ("KAR_AL", "ZARARI_KES"):
            close_reason = pd.close_reason or pd.gerekce
            try:
                pos = self.portfolio.positions.get(sym)
                fill_price = current_price
                if (self.live_sell_fn and pos
                        and getattr(self.cfg, "live_autonomous", False)):
                    try:
                        fp, _fq, _fu = await self.live_sell_fn(sym, pos.qty)
                        fill_price = fp
                    except Exception as le:
                        self._log_event("error", symbol=sym,
                                        reason=f"Live sell hatası: {le}")
                        return False, f"{market.short_name(sym)}: live satış başarısız: {le}"
                result_str = self.portfolio.sell(sym, fill_price)
                if pd.karar == "KAR_AL":
                    color, label = "green3", "kâr alındı"
                else:
                    color, label = "red3", "zarar kesildi"
                self._log_event(
                    "close", symbol=sym, decision=pd.karar, reason=close_reason
                )
                msg = f"{market.short_name(sym)} {label}: {close_reason}"
                self.log(
                    f"[bold {color}]{prefix}{market.short_name(sym)} {label}:[/] "
                    f"{close_reason}"
                )
                self.log(f"   {result_str}")
                if self.sync_feed:
                    self.sync_feed()
                return True, msg
            except Exception as e:
                err = f"{market.short_name(sym)}: kapatma hatası: {e}"
                self._log_event("error", symbol=sym, reason=err)
                return False, err

        elif pd.karar == "STOP_GUNCELLE":
            new_stop = pd.new_stop_loss
            if not new_stop:
                msg = f"{market.short_name(sym)}: STOP_GUNCELLE için yeni stop değeri eksik"
                if auto:
                    self.log(f"[grey58]{prefix}{msg}[/]")
                return False, msg

            valid, reason = validate_stop_update(
                pos.entry, current_price, pos.stop, new_stop, pos.direction
            )
            if not valid:
                msg = f"{market.short_name(sym)} stop güncellenemedi: {reason}"
                if auto:
                    self.log(f"[red3]{prefix}{msg}[/]")
                return False, msg

            old_str = f"{pos.stop:,.4f}" if pos.stop else "yok"
            self.portfolio.set_protection(sym, new_stop, pos.target)
            self._log_event(
                "stop_update", symbol=sym, decision="STOP_GUNCELLE",
                reason=pd.gerekce, stop_loss=new_stop,
            )
            msg = (
                f"{market.short_name(sym)} stop güncellendi: "
                f"{old_str} → {new_stop:,.4f}, sebep: {pd.gerekce}"
            )
            self.log(f"[cyan]{prefix}{msg}[/]")
            return True, msg

        elif pd.karar == "KORU":
            new_stop = pd.new_stop_loss or 0.0
            new_target = pd.new_take_profit or 0.0
            changes: list[str] = []

            if new_stop and not pos.stop:
                valid, reason = validate_stop_update(
                    pos.entry, current_price, pos.stop, new_stop, pos.direction
                )
                if not valid:
                    msg = f"{market.short_name(sym)} KORU stop geçersiz: {reason}"
                    if auto:
                        self.log(f"[red3]{prefix}{msg}[/]")
                    return False, msg
                changes.append(f"stop={new_stop:,.4f}")

            if new_target and not pos.target:
                if pos.direction == "short":
                    if new_target >= current_price:
                        msg = f"{market.short_name(sym)} KORU: short hedef anlık fiyatın üstünde — reddedildi"
                        if auto:
                            self.log(f"[red3]{prefix}{msg}[/]")
                        return False, msg
                else:
                    if new_target <= current_price:
                        msg = f"{market.short_name(sym)} KORU: hedef anlık fiyatın altında — reddedildi"
                        if auto:
                            self.log(f"[red3]{prefix}{msg}[/]")
                        return False, msg
                changes.append(f"hedef={new_target:,.4f}")

            if not changes:
                msg = f"{market.short_name(sym)} KORU: zaten korumalı, atlandı"
                if auto:
                    self.log(f"[grey58]{prefix}{msg}[/]")
                return False, msg

            final_stop = new_stop if (new_stop and not pos.stop) else pos.stop
            final_target = new_target if (new_target and not pos.target) else pos.target
            self.portfolio.set_protection(sym, final_stop, final_target)
            self._log_event(
                "protect", symbol=sym, decision="KORU", reason=pd.gerekce,
                stop_loss=final_stop or 0, take_profit=final_target or 0,
            )
            msg = (
                f"{market.short_name(sym)} koruma eklendi: "
                f"{', '.join(changes)}, sebep: {pd.gerekce}"
            )
            self.log(f"[cyan]{prefix}{msg}[/]")
            return True, msg

        return False, f"{market.short_name(sym)}: bilinmeyen karar ({pd.karar})"

    def _check_leveraged_break_even(self) -> None:
        """Kaldıraçlı pozisyon %2 kâra geçince stop'u break-even'e taşı.

        Claude API çağrısı yok — kural tabanlı, her döngü tickinde çalışır.
        Stop zaten entry'nin üzerindeyse tekrarlanmaz.
        """
        for sym, pos in list(self.portfolio.positions.items()):
            if not pos.is_leveraged or not pos.stop:
                continue
            if pos.stop >= pos.entry:
                continue  # zaten break-even veya daha iyi

            cur = self.feed.price(sym)
            if not cur or cur <= 0:
                continue

            profit_pct = (cur - pos.entry) / pos.entry * 100
            if profit_pct < 2.0:
                continue

            # Entry + %0.05 tampon (spread ve slippage için)
            new_stop = round(pos.entry * 1.0005, 8)
            if new_stop >= cur:
                continue  # fiyat çok yakın, geçersiz olurdu

            valid, _ = validate_stop_update(
                pos.entry, cur, pos.stop, new_stop
            )
            if not valid:
                continue

            self.portfolio.set_protection(sym, new_stop, pos.target)
            self._log_event(
                "stop_update", symbol=sym, decision="STOP_GUNCELLE",
                reason=(
                    f"Kaldıraçlı %{profit_pct:.1f} kâr — "
                    "stop break-even'e otomatik taşındı"
                ),
                stop_loss=new_stop,
            )
            self.log(
                f"[bold gold3][OTONOM][LEVERAGE] {market.short_name(sym)} "
                f"stop break-even'e taşındı:[/] "
                f"{pos.stop:,.4f} → {new_stop:,.4f} "
                f"(kâr %{profit_pct:.1f})"
            )

    async def _run_position_analysis(self) -> None:
        """5 dakikada bir: açık pozisyonları Claude ile analiz et."""
        if not self.portfolio.positions:
            return
        syms = ", ".join(market.short_name(s) for s in self.portfolio.positions)
        self.log(f"[grey58][OTONOM] Pozisyon analizi başlıyor: {syms}…[/]")
        try:
            positions_data = self._build_positions_data()
            result = await ai.analyze_positions(positions_data, self.portfolio.cash)
            analysis = ai.parse_status_analysis(result)
            summary = ai.strip_machine_lines(result)
            if summary:
                self.log(f"[cyan][OTONOM] Pozisyon analizi:[/] {summary}")

            if not analysis:
                self.log("[grey58][OTONOM] Analiz tamamlandı — karar verisi ayrıştırılamadı.[/]")
                return

            for pd in analysis.pozisyonlar:
                sym = market.resolve_symbol(pd.sembol)
                self.position_decisions[sym] = pd.karar

                if pd.karar not in ("DEVAM", "BEKLE"):
                    price = (self.feed.price(sym)
                             or (self.portfolio.positions[sym].entry
                                 if sym in self.portfolio.positions else 0))
                    if price and sym in self.portfolio.positions:
                        await self.apply_decision(sym, pd, price, auto=True)
                else:
                    self._log_event(
                        "hold", symbol=sym, decision=pd.karar, reason=pd.gerekce
                    )
                    self.log(
                        f"[grey58][OTONOM] {market.short_name(sym)} "
                        f"{pd.karar}: {pd.gerekce}[/]"
                    )

            if analysis.genel_oneri:
                self.log(f"[cyan][OTONOM][/] {analysis.genel_oneri}")

        except Exception as e:
            self._log_event("error", reason=f"Pozisyon analiz hatası: {e}")
            self.log(f"[red3][OTONOM] Pozisyon analiz hatası: {e}[/]")

    def _log_summary(self, result: str) -> None:
        summary = ai.strip_machine_lines(result)
        if summary:
            self.log(f"[grey58][OTONOM] Tarama:[/] {summary}")

    async def _run_scan(self) -> None:
        """15 dakikada bir: yeni fırsat ara ve uygun adayda paper trade aç."""
        p = self.effective_profile
        if self.state.risk_locked:
            self._log_event("skip", reason="risk kilidi aktif")
            self.log("[red3][OTONOM] Tarama atlandı: risk kilidi aktif.[/]")
            return
        # Ardışık zarar sonrası circuit breaker soğuma süresi
        if self.state.cooldown_until and time.time() < self.state.cooldown_until:
            remaining = int(self.state.cooldown_until - time.time()) // 60
            self._log_event("skip", reason=f"circuit breaker soğuma: {remaining}dk kaldı")
            self.log(f"[gold3][OTONOM] Tarama atlandı: soğuma süresi {remaining}dk.[/]")
            return
        if len(self.portfolio.positions) >= p.max_open_positions:
            self._log_event(
                "skip",
                reason=f"max açık pozisyon ({p.max_open_positions}) doldu"
            )
            self.log(
                f"[grey58][OTONOM] Tarama atlandı: max pozisyon dolu "
                f"({len(self.portfolio.positions)}/{p.max_open_positions}).[/]"
            )
            return
        if self.state.daily_trades >= p.max_daily_trades:
            self._log_event(
                "skip",
                reason=f"günlük işlem limiti ({p.max_daily_trades}) doldu"
            )
            self.log(
                f"[grey58][OTONOM] Tarama atlandı: günlük işlem limiti "
                f"({self.state.daily_trades}/{p.max_daily_trades}) doldu.[/]"
            )
            return

        self.log(
            f"[grey58][OTONOM] Piyasa taraması başlıyor… "
            f"(işlem: {self.state.daily_trades}/{p.max_daily_trades} | "
            f"pos: {len(self.portfolio.positions)}/{p.max_open_positions})[/]"
        )
        try:
            positions = {
                s: {"miktar": pos.qty, "giris": pos.entry,
                    "stop": pos.stop, "hedef": pos.target}
                for s, pos in self.portfolio.positions.items()
            }
            # Kullanıcı watchlist'ini al, sonra kripto universe ile birleştir
            # Yahoo Finance / forex / emtia sembolleri otonom moda dahil edilmiyor
            user_wl = [
                s for s in self.get_watchlist()
                if s.endswith("USDT") and "=" not in s and "-" not in s
            ]
            crypto_universe = list(market.AUTONOMOUS_CRYPTO_UNIVERSE)
            # Kullanıcı watchlist'indeki semboller önce gelsin
            watchlist = user_wl + [s for s in crypto_universe if s not in user_wl]

            lev_enabled = getattr(self.cfg, "leverage_enabled", False)
            trade_plan = getattr(self.cfg, "trade_plan", "dengeli")
            otonom_type = getattr(self.cfg, "otonom_trade_type", "long")

            # ── İzin verilen işlem tipleri (otonom_trade_type'a göre) ───────────
            _ALLOWED_MAP: dict[str, set[str]] = {
                "long":      {"AL", "SPOT_AL"},
                "short":     {"SHORT_AL"},
                "longshort": {"AL", "SPOT_AL", "SHORT_AL"},
                "scalp":     {"SCALP_AL"},
                "kaldirac":  {"AL", "SPOT_AL", "LEVERAGE_AL"},
                "tam":       {"AL", "SPOT_AL", "SHORT_AL", "SCALP_AL", "LEVERAGE_AL"},
            }
            _allowed = _ALLOWED_MAP.get(otonom_type, {"AL", "SPOT_AL"})
            # kaldıraç devre dışıysa LEVERAGE_AL kaldır
            if not lev_enabled:
                _allowed = _allowed - {"LEVERAGE_AL"}

            # ── TA ön filtresi: otonom_trade_type'a göre AL/SAT sinyali ─────────
            _TA_MODE = {
                "long":      "AL",
                "short":     "SAT",
                "longshort": "AL+SAT",
                "scalp":     "AL+SAT",
                "kaldirac":  "AL",
                "tam":       "AL+SAT",
            }
            ta_mode = _TA_MODE.get(otonom_type, "AL")

            crypto_wl = watchlist  # zaten sadece kripto
            tf = "15m" if (otonom_type == "scalp" or
                           getattr(config.current(), "scalp_enabled", False)) else "1h"

            # TA ön filtresi — yönlü setleri ayrı tut (longshort/tam için kritik)
            ta_long_syms: set[str] = set()
            ta_short_syms: set[str] = set()
            try:
                if ta_mode == "AL+SAT":
                    ta_long_r, ta_short_r = await asyncio.gather(
                        indicators.scan_signals(crypto_wl, tf, filter_signal="AL"),
                        indicators.scan_signals(crypto_wl, tf, filter_signal="SAT"),
                    )
                    ta_long_syms = {r.symbol for r in ta_long_r}
                    ta_short_syms = {r.symbol for r in ta_short_r}
                    ta_symbols = ta_long_syms | ta_short_syms
                elif ta_mode == "SAT":
                    ta_short_r = await indicators.scan_signals(crypto_wl, tf, filter_signal="SAT")
                    ta_short_syms = {r.symbol for r in ta_short_r}
                    ta_symbols = ta_short_syms
                else:
                    ta_long_r = await indicators.scan_signals(crypto_wl, tf, filter_signal="AL")
                    ta_long_syms = {r.symbol for r in ta_long_r}
                    ta_symbols = ta_long_syms

                in_pos = set(self.portfolio.positions.keys())
                filtered_wl = [s for s in watchlist if s in ta_symbols or s in in_pos]
                if filtered_wl:
                    watchlist = filtered_wl
                    self._log_event(
                        "ta_filter",
                        reason=f"TA filtresi ({ta_mode}): {len(crypto_wl)}→{len(filtered_wl)} kripto aday"
                    )
                    long_c = len([s for s in filtered_wl if s in ta_long_syms])
                    short_c = len([s for s in filtered_wl if s in ta_short_syms])
                    self.log(
                        f"[grey58][OTONOM] TA filtresi ({ta_mode}): {len(crypto_wl)} sembolden "
                        f"{len(filtered_wl)} aday ({long_c} yükseliş / {short_c} düşüş) → AI'ya gönderiliyor[/]"
                    )
                else:
                    fallback = user_wl or crypto_wl[:20]
                    watchlist = fallback
                    self.log(
                        f"[grey58][OTONOM] TA filtresi ({ta_mode}): sinyal bulunamadı, "
                        f"watchlist fallback ({len(watchlist)} sembol) → AI'ya gönderiliyor[/]"
                    )
            except Exception as ta_err:
                self.log(f"[grey58][OTONOM] TA filtresi atlandı ({ta_err}), tam liste kullanılıyor[/]")

            # AI taraması: otonom_type'a göre doğru fonksiyonu seç
            suggestions: list[ai.Suggestion] = []

            if otonom_type == "short":
                result = await ai.scan_directional(
                    watchlist, self.portfolio.cash, positions, direction="short"
                )
                self._log_summary(result)
                suggestions = ai.parse_suggestions(result)

            elif otonom_type == "scalp":
                result = await ai.scan_directional(
                    watchlist, self.portfolio.cash, positions, direction="scalp"
                )
                self._log_summary(result)
                suggestions = ai.parse_suggestions(result)

            elif otonom_type == "long":
                result = await ai.scan_market_filtered(
                    watchlist, self.portfolio.cash, positions,
                    category="kripto", leverage_enabled=False,
                    max_leverage=p.max_leverage, trade_plan="sadece_long",
                )
                self._log_summary(result)
                suggestions = ai.parse_suggestions(result)

            elif otonom_type == "kaldirac":
                result = await ai.scan_market_filtered(
                    watchlist, self.portfolio.cash, positions,
                    category="kripto", leverage_enabled=lev_enabled,
                    max_leverage=p.max_leverage, trade_plan="tam",
                )
                self._log_summary(result)
                suggestions = ai.parse_suggestions(result)

            else:
                # longshort / tam → paralel yönsel taramalar
                # LONG için TA-bullish, SHORT için TA-bearish semboller
                long_wl  = [s for s in watchlist if s in ta_long_syms]  or (user_wl or watchlist[:15])
                short_wl = [s for s in watchlist if s in ta_short_syms] or (user_wl or watchlist[:10])

                gather_tasks = [
                    ai.scan_directional(long_wl,  self.portfolio.cash, positions, direction="long"),
                    ai.scan_directional(short_wl, self.portfolio.cash, positions, direction="short"),
                ]
                # tam modda scalp ve kaldıraç da dahil
                if otonom_type == "tam":
                    scalp_wl = long_wl[:8]   # en likit semboller
                    gather_tasks.append(
                        ai.scan_directional(scalp_wl, self.portfolio.cash, positions, direction="scalp")
                    )
                    if lev_enabled:
                        gather_tasks.append(
                            ai.scan_market_filtered(
                                long_wl[:10], self.portfolio.cash, positions,
                                category="kripto", leverage_enabled=True,
                                max_leverage=p.max_leverage, trade_plan="tam",
                            )
                        )

                results = await asyncio.gather(*gather_tasks)
                labels  = ["LONG", "SHORT", "SCALP", "KALDIRAÇ"]
                suggestions = []
                for i, res in enumerate(results):
                    lbl = labels[i] if i < len(labels) else "TARAMA"
                    s = ai.strip_machine_lines(res)
                    if s:
                        self.log(f"[grey58][OTONOM] {lbl} tarama:[/] {s}")
                    suggestions += ai.parse_suggestions(res)

            candidates = []
            for s in suggestions:
                if s.islem in _allowed:
                    candidates.append(s)
                else:
                    self._log_event(
                        "skip", symbol=s.sembol,
                        reason=f"blocked_by_trade_type: {s.islem} otonom_type={otonom_type}",
                    )

            if not candidates:
                self.log("[grey58][OTONOM] Tarama tamamlandı — işlem yapılacak aday bulunamadı.[/]")

            for s in candidates:
                if not self.state.enabled:
                    break
                if self.state.daily_trades >= p.max_daily_trades:
                    break

                sym = market.resolve_symbol(s.sembol)

                if sym in self.portfolio.positions:
                    self._log_event("skip", symbol=sym,
                                    reason="zaten açık pozisyon var")
                    self.log(f"[grey58][OTONOM] {market.short_name(sym)} atlandı: zaten açık pozisyon var.[/]")
                    continue

                # LEVERAGE_AL adayını ayrı işle — max_open_positions limitini geçer
                # (kaldıraç kendi günlük limitine sahip: daily_leveraged_trades)
                if s.islem == "LEVERAGE_AL":
                    await self._handle_leverage_candidate(s, sym, p)
                    continue

                # Normal işlemler için pozisyon limiti kontrolü
                if len(self.portfolio.positions) >= p.max_open_positions:
                    break

                if s.basari_yuzdesi < p.min_confidence:
                    self._log_event("skip", symbol=sym,
                                    reason=f"confidence düşük: %{s.basari_yuzdesi} < %{p.min_confidence}")
                    self.log(
                        f"[grey58][OTONOM] {market.short_name(sym)} atlandı: "
                        f"güven %{s.basari_yuzdesi} < eşik %{p.min_confidence}[/]"
                    )
                    continue
                if s.basari_yuzdesi > MAX_CONFIDENCE:
                    s.basari_yuzdesi = MAX_CONFIDENCE

                if not s.zarar_kes or not s.kar_al:
                    self._log_event("skip", symbol=sym, reason="stop/hedef eksik")
                    self.log(f"[grey58][OTONOM] {market.short_name(sym)} atlandı: stop/hedef eksik[/]")
                    continue

                price = self.feed.price(sym)
                if not price:
                    try:
                        price = await market.quote(sym)
                    except Exception:
                        self._log_event("skip", symbol=sym, reason="fiyat alınamadı")
                        self.log(f"[grey58][OTONOM] {market.short_name(sym)} atlandı: fiyat alınamadı[/]")
                        continue

                stop_risk = abs(price - s.zarar_kes)
                target_gain = abs(s.kar_al - price)
                rr = target_gain / stop_risk if stop_risk > 0 else 0
                if rr < p.min_risk_reward:
                    self._log_event("skip", symbol=sym,
                                    reason=f"R/R düşük: {rr:.2f} < {p.min_risk_reward}")
                    self.log(
                        f"[grey58][OTONOM] {market.short_name(sym)} atlandı: "
                        f"R/R {rr:.2f} < eşik {p.min_risk_reward}[/]"
                    )
                    continue

                usdt = min(s.tutar_usdt, self.portfolio.cash * p.max_trade_percent)
                if usdt < 1:
                    self._log_event("skip", symbol=sym, reason="yetersiz nakit")
                    self.log(f"[grey58][OTONOM] {market.short_name(sym)} atlandı: yetersiz nakit[/]")
                    continue

                # SHORT_AL: veri kalitesi kontrolü
                if s.islem == "SHORT_AL":
                    allowed, reason = market.trade_allowed(sym)
                    if not allowed:
                        self._log_event("skip", symbol=sym, reason=f"short engellendi: {reason}")
                        self.log(f"[grey58][OTONOM] {market.short_name(sym)} short atlandı: {reason}[/]")
                        continue

                # SCALP_AL: veri kalitesi kontrolü
                if s.islem == "SCALP_AL":
                    allowed, reason = market.trade_allowed(sym)
                    if not allowed:
                        self._log_event("skip", symbol=sym, reason=f"scalp engellendi: {reason}")
                        self.log(f"[grey58][OTONOM] {market.short_name(sym)} scalp atlandı: {reason}[/]")
                        continue

                try:
                    if s.islem == "SHORT_AL":
                        self.portfolio.buy_short(sym, usdt, price,
                                                 stop=s.zarar_kes, target=s.kar_al)
                        decision_label = "SHORT_AL"
                        log_color = "red3"
                        log_action = "SHORT açıldı"
                    elif s.islem == "SCALP_AL":
                        stop, target = s.zarar_kes or price*0.99, s.kar_al or price*1.015
                        self.portfolio.buy(sym, usdt, price, trade_style="scalp",
                                           stop=stop, target=target)
                        decision_label = "SCALP_AL"
                        log_color = "cyan"
                        log_action = "SCALP açıldı"
                    else:
                        stop, target = sanitize_levels(price, s.zarar_kes, s.kar_al)
                        fill_price = price
                        fill_usdt = usdt
                        if (self.live_buy_fn
                                and getattr(self.cfg, "live_autonomous", False)):
                            try:
                                fp, _fq, fu = await self.live_buy_fn(sym, usdt)
                                fill_price, fill_usdt = fp, fu
                            except Exception as le:
                                self._log_event("error", symbol=sym,
                                                reason=f"Live buy hatası: {le}")
                                continue
                        self.portfolio.buy(sym, fill_usdt, fill_price,
                                           stop=stop, target=target)
                        decision_label = "AL"
                        log_color = "green3"
                        log_action = "AL açıldı"
                        self.portfolio.set_protection(sym, stop, target)

                    self.state.daily_trades += 1
                    self.state.save(self._state_path)
                    stop_used = s.zarar_kes if s.islem in ("SHORT_AL", "SCALP_AL") else stop
                    target_used = s.kar_al if s.islem in ("SHORT_AL", "SCALP_AL") else target
                    rr_actual = (abs(target_used - price) / abs(price - stop_used)
                                 if abs(price - stop_used) > 0 else 0)
                    self._log_event(
                        "open", symbol=sym, decision=decision_label,
                        reason=s.gerekce, confidence=s.basari_yuzdesi,
                        stop_loss=stop_used, take_profit=target_used,
                        risk_reward=round(rr_actual, 2),
                    )
                    def _fp(v):
                        return f"{v:,.2f}" if v >= 1 else f"{v:.6f}"
                    self.log(
                        f"[bold {log_color}][OTONOM] {market.short_name(sym)} {log_action}:[/] "
                        f"{usdt:,.0f} USDT | stop {_fp(stop_used)} | "
                        f"hedef {_fp(target_used)} | R/R {rr_actual:.2f}"
                    )
                    if self.sync_feed:
                        self.sync_feed()
                except ValueError as e:
                    self._log_event("error", symbol=sym, reason=str(e))

        except Exception as e:
            self._log_event("error", reason=f"Tarama hatası: {e}")
            self.log(f"[red3][OTONOM] Tarama hatası: {e}[/]")

    async def _handle_leverage_candidate(
        self, s: "ai.Suggestion", sym: str, p: AutonomousProfile
    ) -> None:
        """LEVERAGE_AL adayını otonom modda doğrula ve aç."""
        # Kaldıraç etkin mi?
        if not getattr(self.cfg, "leverage_enabled", False):
            self._log_event("skip", symbol=sym,
                            reason="kaldıraç devre dışı (/kaldirac ac)")
            return
        # Günlük kaldıraç kilidi
        if self.state.daily_leverage_locked:
            self._log_event("skip", symbol=sym,
                            reason="günlük kaldıraç kilidi aktif")
            return
        # Günlük kaldıraçlı işlem limiti (1/gün)
        if self.state.daily_leveraged_trades >= 1:
            self._log_event("skip", symbol=sym,
                            reason="günlük kaldıraçlı işlem limiti (1) doldu")
            return
        # Zaten açık kaldıraçlı pozisyon var mı?
        if self.portfolio.leveraged_positions():
            self._log_event("skip", symbol=sym,
                            reason="zaten açık kaldıraçlı pozisyon var")
            return

        # Confidence / R/R eşikleri (kaldıraç için daha sıkı)
        if s.basari_yuzdesi < p.leverage_min_confidence:
            self._log_event(
                "skip", symbol=sym,
                reason=f"leverage confidence düşük: %{s.basari_yuzdesi} < %{p.leverage_min_confidence}",
            )
            return
        if s.basari_yuzdesi > MAX_CONFIDENCE:
            s.basari_yuzdesi = MAX_CONFIDENCE

        if not s.zarar_kes or not s.kar_al:
            self._log_event("skip", symbol=sym, reason="stop/hedef eksik")
            return

        price = self.feed.price(sym)
        if not price:
            try:
                price = await market.quote(sym)
            except Exception:
                self._log_event("skip", symbol=sym, reason="fiyat alınamadı")
                return

        stop_risk = abs(price - s.zarar_kes)
        target_gain = abs(s.kar_al - price)
        rr = target_gain / stop_risk if stop_risk > 0 else 0
        if rr < p.leverage_min_rr:
            self._log_event(
                "skip", symbol=sym,
                reason=f"leverage R/R düşük: {rr:.2f} < {p.leverage_min_rr}",
            )
            return

        # Etkili kaldıraç (önerileni modun limitine sabitle)
        effective_lev = min(s.leverage, p.max_leverage, MAX_LEVERAGE)
        effective_lev = max(effective_lev, 2)

        # Portföy değerini hesapla
        all_prices = {ss: t.price for ss, t in self.feed.tickers.items() if t.price > 0}
        equity = self.portfolio.equity(all_prices)

        margin = min(
            s.tutar_usdt or (equity * p.leverage_max_risk_pct * 2),
            equity * p.leverage_max_risk_pct * 2,
            self.portfolio.cash * 0.20,  # nakitin max %20'si margin
        )
        if margin < 5:
            self._log_event("skip", symbol=sym, reason="yetersiz nakit (margin < 5 USDT)")
            return

        valid, reason = validate_leverage_trade(
            entry=price,
            stop=s.zarar_kes,
            target=s.kar_al,
            leverage=effective_lev,
            margin_usdt=margin,
            portfolio_equity=equity,
            max_leverage=p.max_leverage,
            max_risk_pct=p.leverage_max_risk_pct,
        )
        if not valid:
            self._log_event("skip", symbol=sym,
                            reason=f"leverage validasyon başarısız: {reason}")
            return

        try:
            result_str = self.portfolio.buy_leveraged(
                sym, margin, effective_lev, price, s.zarar_kes, s.kar_al
            )
            self.state.daily_trades += 1
            self.state.daily_leveraged_trades += 1
            self.state.save(self._state_path)
            liq = calc_liquidation_price(price, effective_lev)
            notional = margin * effective_lev
            risk = abs((price - s.zarar_kes) * (notional / price))
            self._log_event(
                "open_leveraged", symbol=sym, decision="LEVERAGE_AL",
                reason=s.gerekce, confidence=s.basari_yuzdesi,
                stop_loss=s.zarar_kes, take_profit=s.kar_al,
                risk_reward=round(rr, 2),
            )
            self.log(
                f"[bold gold3][OTONOM][LEVERAGE PAPER] {market.short_name(sym)} "
                f"{effective_lev}x açıldı:[/] margin {margin:,.0f} USDT | "
                f"notional {notional:,.0f} USDT | "
                f"stop {s.zarar_kes:,.4f} | hedef {s.kar_al:,.4f} | "
                f"liq {liq:,.4f} | risk {risk:.2f} USDT"
            )
            if self.sync_feed:
                self.sync_feed()
        except ValueError as e:
            self._log_event("error", symbol=sym, reason=str(e))

    # ── yardımcılar ─────────────────────────────────────────────────────────

    def _build_positions_data(self) -> list[dict]:
        data = []
        for sym, pos in self.portfolio.positions.items():
            cur = self.feed.price(sym) or pos.entry
            if pos.direction == "short":
                pnl = (pos.entry - cur) * pos.qty
                stop_dist = (
                    round((pos.stop - cur) / cur * 100, 2) if pos.stop else None
                )
                target_dist = (
                    round((cur - pos.target) / cur * 100, 2) if pos.target else None
                )
            else:
                pnl = (cur - pos.entry) * pos.qty
                stop_dist = (
                    round((cur - pos.stop) / cur * 100, 2) if pos.stop else None
                )
                target_dist = (
                    round((pos.target - cur) / cur * 100, 2) if pos.target else None
                )
            stop_risk = abs(cur - pos.stop) if pos.stop else 0
            target_gain = abs(pos.target - cur) if pos.target else 0
            rr = (round(target_gain / stop_risk, 2)
                  if stop_risk > 0 else None)
            row: dict = {
                "sembol": sym,
                "giris": pos.entry,
                "guncel": cur,
                "kz_usdt": round(pnl, 2),
                "kz_pct": round((cur / pos.entry - 1) * 100, 2) if pos.entry else 0,
                "stop": pos.stop,
                "hedef": pos.target,
                "stop_uzaklik_pct": stop_dist,
                "hedef_uzaklik_pct": target_dist,
                "rr": rr,
            }
            if pos.is_leveraged:
                row.update({
                    "trade_type": "leveraged_paper",
                    "leverage": pos.leverage,
                    "margin_usdt": pos.margin_usdt,
                    "notional_usdt": pos.notional_usdt,
                    "liquidation_price": pos.liquidation_price,
                    "liq_uzaklik_pct": (
                        round((cur - pos.liquidation_price) / cur * 100, 2)
                        if cur > 0 and pos.liquidation_price else None
                    ),
                    "kz_margin_pct": (
                        round(pnl / pos.margin_usdt * 100, 2)
                        if pos.margin_usdt else 0
                    ),
                })
            data.append(row)
        return data

    def _log_event(
        self,
        action: str,
        symbol: str = "",
        decision: str = "",
        reason: str = "",
        confidence: int = 0,
        stop_loss: float = 0,
        take_profit: float = 0,
        risk_reward: float = 0,
        result: str = "",
    ) -> None:
        entry = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "action": action,
            "symbol": symbol,
            "decision": decision,
            "reason": reason,
            "confidence": confidence,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_reward": risk_reward,
            "result": result,
        }
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            # Rotasyon: 10.000 satırı aşarsa son 5.000 satırı tut
            try:
                lines = self._log_path.read_text(encoding="utf-8").splitlines()
                if len(lines) > 10_000:
                    self._log_path.write_text(
                        "\n".join(lines[-5_000:]) + "\n", encoding="utf-8"
                    )
            except Exception:
                pass
        except Exception:
            pass
