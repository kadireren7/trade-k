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
import market
from portfolio import Portfolio, sanitize_levels

# ── Güvenlik engeli ─────────────────────────────────────────────────────────
def create_order(*args, **kwargs):
    raise RuntimeError("REAL_ORDER_DISABLED")


def futures_create_order(*args, **kwargs):
    raise RuntimeError("REAL_ORDER_DISABLED")


# ── Risk sabitleri ───────────────────────────────────────────────────────────
MAX_OPEN_POSITIONS = 2
MAX_TRADE_CASH_RATIO = 0.10
MAX_PORTFOLIO_RISK_RATIO = 0.25
MAX_DAILY_TRADES = 3
MAX_CONSECUTIVE_LOSSES = 2
DAILY_LOSS_LIMIT_PCT = 2.0
MIN_CONFIDENCE = 55
MAX_CONFIDENCE = 80
MIN_RISK_REWARD = 1.5

SCAN_INTERVAL = 900     # 15 dakika
ANALYSIS_INTERVAL = 300  # 5 dakika
PRICE_CHECK_INTERVAL = 2  # 2 saniye

LOG_FILE = Path(__file__).parent / "autonomous_log.jsonl"
STATE_FILE = Path(__file__).parent / "autonomous_state.json"


# ── Durum kalıcılığı ─────────────────────────────────────────────────────────
@dataclass
class AutonomousState:
    enabled: bool = False
    daily_trades: int = 0        # bugün otonom mod tarafından açılan işlem sayısı
    consecutive_losses: int = 0  # ardışık zarar sayacı
    daily_start_equity: float = 0.0
    daily_date: str = ""         # YYYY-MM-DD (günlük sıfırlama için)
    risk_locked: bool = False    # True → otonom yeni işlem açmaz

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
    ) -> None:
        self.portfolio = portfolio
        self.feed = feed
        self.tracker = tracker
        self.cfg = cfg
        self.log = log_fn
        self.get_watchlist = watchlist_fn
        self.sync_feed = sync_feed_fn
        self._state_path = state_path
        self._log_path = log_path
        self.state = AutonomousState.load(state_path)
        self.state.enabled = False  # her başlangıçta kapalı
        self._task: asyncio.Task | None = None
        self._history_len = len(portfolio.history)
        # Sembol → son Claude kararı (UI için)
        self.position_decisions: dict[str, str] = {}

    # ── public API ──────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self.state.enabled

    @property
    def risk_locked(self) -> bool:
        return self.state.risk_locked

    @property
    def daily_trades(self) -> int:
        return self.state.daily_trades

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
        lines = [
            f"Durum: {'[green3]AÇIK[/]' if self.state.enabled else '[grey58]KAPALI[/]'}",
            f"Günlük işlem: {self.state.daily_trades}/{MAX_DAILY_TRADES}",
            f"Ardışık zarar: {self.state.consecutive_losses}/{MAX_CONSECUTIVE_LOSSES}",
            f"Risk kilidi: {'[red3]AKTİF[/]' if self.state.risk_locked else '[green3]Kapalı[/]'}",
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
                f"Günlük PnL: [{color}]{sign}{daily_pnl:,.2f} USDT "
                f"({sign}{pct:.2f}%)[/]"
            )
        lines.append(
            f"Limitler: max {MAX_OPEN_POSITIONS} pozisyon | "
            f"tek işlem max %{MAX_TRADE_CASH_RATIO*100:.0f} nakit | "
            f"günlük max {MAX_DAILY_TRADES} işlem | "
            f"min güven %{MIN_CONFIDENCE} | min R/R {MIN_RISK_REWARD}"
        )
        return "\n".join(lines)

    # ── iç döngü ────────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        # İlk çalışmada zamanları geçmişe alarak hemen çalışmalarını sağla
        self.state.last_scan_time = time.time() - SCAN_INTERVAL
        self.state.last_analysis_time = time.time() - ANALYSIS_INTERVAL

        while self.state.enabled:
            try:
                now = time.time()
                self._check_daily_reset()
                self._check_trades_from_history()
                self._check_daily_loss_limit()

                if not self.state.enabled:
                    break

                if now - getattr(self.state, "last_analysis_time", 0) >= ANALYSIS_INTERVAL:
                    self.state.last_analysis_time = now
                    await self._run_position_analysis()

                if now - getattr(self.state, "last_scan_time", 0) >= SCAN_INTERVAL:
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
        for trade in new_trades:
            if trade.get("side") == "SAT" and trade.get("pnl") is not None:
                if trade["pnl"] < 0:
                    self.state.consecutive_losses += 1
                    self._log_event(
                        "loss", symbol=trade.get("symbol", ""),
                        reason=(f"Zarar: {trade['pnl']:,.2f} USDT. "
                                f"Ardışık zarar: {self.state.consecutive_losses}"),
                    )
                    if self.state.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                        self.state.risk_locked = True
                        self.state.save(self._state_path)
                        self.log(
                            f"[bold red3][OTONOM] Üst üste {MAX_CONSECUTIVE_LOSSES} zarar — "
                            f"yeni işlem açma kilidi devreye girdi.[/]"
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
        if loss_pct >= DAILY_LOSS_LIMIT_PCT:
            self.state.enabled = False
            self.state.risk_locked = True
            self.state.save(self._state_path)
            self.log(
                f"[bold red3][OTONOM] Günlük zarar limiti "
                f"(%{DAILY_LOSS_LIMIT_PCT:.0f}) aşıldı "
                f"({loss_pct:.1f}%) — otonom mod kapatılıyor.[/]"
            )
            self._log_event("shutdown",
                            reason=f"Günlük zarar limiti: {loss_pct:.1f}%")

    async def _run_position_analysis(self) -> None:
        """5 dakikada bir: açık pozisyonları Claude ile analiz et."""
        if not self.portfolio.positions:
            return
        try:
            positions_data = self._build_positions_data()
            result = await ai.analyze_positions(positions_data, self.portfolio.cash)
            analysis = ai.parse_status_analysis(result)
            summary = ai.strip_machine_lines(result)
            if summary:
                self.log(f"[cyan][OTONOM] Pozisyon analizi:[/] {summary}")

            if not analysis:
                return

            for pd in analysis.pozisyonlar:
                sym = market.resolve_symbol(pd.sembol)
                self.position_decisions[sym] = pd.karar

                if pd.acil:
                    await self._execute_position_decision(sym, pd)
                else:
                    self._log_event(
                        "hold" if pd.karar in ("DEVAM", "BEKLE") else "suggest",
                        symbol=sym, decision=pd.karar, reason=pd.gerekce,
                    )

            if analysis.genel_oneri:
                self.log(f"[cyan][OTONOM][/] {analysis.genel_oneri}")

        except Exception as e:
            self._log_event("error", reason=f"Pozisyon analiz hatası: {e}")

    async def _execute_position_decision(self, sym: str, pd) -> None:
        """Acil kararları uygula (sadece KAR_AL ve ZARARI_KES)."""
        if sym not in self.portfolio.positions:
            return
        if pd.karar not in ("KAR_AL", "ZARARI_KES"):
            return
        price = self.feed.price(sym) or self.portfolio.positions[sym].entry
        try:
            result_str = self.portfolio.sell(sym, price)
            karar_label = "kâr alındı" if pd.karar == "KAR_AL" else "zarar kesildi"
            color = "green3" if pd.karar == "KAR_AL" else "red3"
            self._log_event("close", symbol=sym, decision=pd.karar, reason=pd.gerekce)
            self.log(
                f"[bold {color}][OTONOM] {market.short_name(sym)} "
                f"{karar_label} (acil karar):[/] {pd.gerekce}"
            )
            self.log(f"   {result_str}")
            if self.sync_feed:
                asyncio.create_task(self.sync_feed())
        except Exception as e:
            self._log_event("error", symbol=sym, reason=f"Kapatma hatası: {e}")

    async def _run_scan(self) -> None:
        """15 dakikada bir: yeni fırsat ara ve uygun adayda paper trade aç."""
        if self.state.risk_locked:
            self._log_event("skip", reason="risk kilidi aktif")
            return
        if len(self.portfolio.positions) >= MAX_OPEN_POSITIONS:
            self._log_event(
                "skip",
                reason=f"max açık pozisyon ({MAX_OPEN_POSITIONS}) doldu"
            )
            return
        if self.state.daily_trades >= MAX_DAILY_TRADES:
            self._log_event(
                "skip",
                reason=f"günlük işlem limiti ({MAX_DAILY_TRADES}) doldu"
            )
            return

        try:
            positions = {
                s: {"miktar": p.qty, "giris": p.entry,
                    "stop": p.stop, "hedef": p.target}
                for s, p in self.portfolio.positions.items()
            }
            watchlist = self.get_watchlist()
            result = await ai.scan_market_filtered(
                watchlist, self.portfolio.cash, positions
            )

            summary = ai.strip_machine_lines(result)
            if summary:
                self.log(f"[grey58][OTONOM] Tarama:[/] {summary}")

            suggestions = ai.parse_suggestions(result)
            # Sadece AL önerilerini işle
            candidates = [s for s in suggestions if s.islem == "AL"]

            for s in candidates:
                if not self.state.enabled:
                    break
                if len(self.portfolio.positions) >= MAX_OPEN_POSITIONS:
                    break
                if self.state.daily_trades >= MAX_DAILY_TRADES:
                    break

                sym = market.resolve_symbol(s.sembol)

                # Zaten açık pozisyon
                if sym in self.portfolio.positions:
                    self._log_event("skip", symbol=sym,
                                    reason="zaten açık pozisyon var")
                    continue

                # Confidence kontrolü
                if s.basari_yuzdesi < MIN_CONFIDENCE:
                    self._log_event(
                        "skip", symbol=sym,
                        reason=f"confidence düşük: %{s.basari_yuzdesi}"
                    )
                    continue
                if s.basari_yuzdesi > MAX_CONFIDENCE:
                    s.basari_yuzdesi = MAX_CONFIDENCE

                # Stop/hedef zorunlu
                if not s.zarar_kes or not s.kar_al:
                    self._log_event("skip", symbol=sym,
                                    reason="stop/hedef eksik")
                    continue

                # Fiyat al
                price = self.feed.price(sym)
                if not price:
                    try:
                        price = await market.quote(sym)
                    except Exception:
                        self._log_event("skip", symbol=sym,
                                        reason="fiyat alınamadı")
                        continue

                # R/R kontrolü (güncel fiyata göre)
                stop_risk = abs(price - s.zarar_kes)
                target_gain = abs(s.kar_al - price)
                rr = target_gain / stop_risk if stop_risk > 0 else 0
                if rr < MIN_RISK_REWARD:
                    self._log_event(
                        "skip", symbol=sym,
                        reason=f"R/R düşük: {rr:.2f} < {MIN_RISK_REWARD}"
                    )
                    continue

                # Tutar hesapla
                usdt = min(
                    s.tutar_usdt,
                    self.portfolio.cash * MAX_TRADE_CASH_RATIO,
                )
                if usdt < 1:
                    self._log_event("skip", symbol=sym,
                                    reason="yetersiz nakit")
                    continue

                # Pozisyon aç
                try:
                    self.portfolio.buy(sym, usdt, price)
                    stop, target = sanitize_levels(price, s.zarar_kes, s.kar_al)
                    self.portfolio.set_protection(sym, stop, target)
                    self.state.daily_trades += 1
                    self.state.save(self._state_path)
                    rr_actual = (abs(target - price) / abs(price - stop)
                                 if abs(price - stop) > 0 else 0)
                    self._log_event(
                        "open", symbol=sym, decision="AL",
                        reason=s.gerekce, confidence=s.basari_yuzdesi,
                        stop_loss=stop, take_profit=target,
                        risk_reward=round(rr_actual, 2),
                    )
                    self.log(
                        f"[bold green3][OTONOM] {market.short_name(sym)} AL açıldı:[/] "
                        f"{usdt:,.0f} USDT | stop {stop:,.4f} | "
                        f"hedef {target:,.4f} | R/R {rr_actual:.2f}"
                    )
                    if self.sync_feed:
                        asyncio.create_task(self.sync_feed())
                except ValueError as e:
                    self._log_event("error", symbol=sym, reason=str(e))

        except Exception as e:
            self._log_event("error", reason=f"Tarama hatası: {e}")

    # ── yardımcılar ─────────────────────────────────────────────────────────

    def _build_positions_data(self) -> list[dict]:
        data = []
        for sym, pos in self.portfolio.positions.items():
            cur = self.feed.price(sym) or pos.entry
            pnl = (cur - pos.entry) * pos.qty
            stop_dist = (
                round((cur - pos.stop) / cur * 100, 2)
                if pos.stop else None
            )
            target_dist = (
                round((pos.target - cur) / cur * 100, 2)
                if pos.target else None
            )
            stop_risk = abs(cur - pos.stop) if pos.stop else 0
            target_gain = abs(pos.target - cur) if pos.target else 0
            rr = (round(target_gain / stop_risk, 2)
                  if stop_risk > 0 else None)
            data.append({
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
            })
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
        except Exception:
            pass
