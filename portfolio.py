"""Paper trading cüzdanı — sanal bakiye, pozisyonlar ve işlem geçmişi.

Durum account.json dosyasında saklanır; uygulama kapansa da kaybolmaz.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field, fields as dc_fields
from pathlib import Path

STATE_FILE = Path(__file__).parent / "account.json"
STARTING_CASH = 10_000.0

SCALP_MAX_DURATION = 1800  # 30 dakika (saniye)
MAX_LEVERAGE = 5
MAINTENANCE_MARGIN_RATE = 0.005  # %0.5 bakım teminatı oranı


@dataclass
class Position:
    qty: float
    entry: float                    # ortalama giriş fiyatı (USDT)
    stop: float | None = None       # zarar-kes fiyatı
    target: float | None = None     # kâr-al fiyatı
    trade_style: str = "spot"       # "spot" | "scalp" | "short" | "leveraged"
    direction: str = "long"         # "long" | "short"
    opened_at: float = field(default_factory=time.time)
    is_leveraged: bool = False
    leverage: int = 1
    margin_usdt: float = 0.0
    notional_usdt: float = 0.0
    liquidation_price: float = 0.0


def _load_position(d: dict) -> Position:
    valid = {f.name for f in dc_fields(Position)}
    return Position(**{k: v for k, v in d.items() if k in valid})


def sanitize_levels(
    entry: float, stop: float, target: float, direction: str = "long"
) -> tuple[float, float]:
    """Claude'un verdiği stop/hedef seviyelerini kod tarafında doğrula."""
    if direction == "short":
        if not stop or not (entry * 1.001 <= stop <= entry * 1.20):
            stop = entry * 1.05
        if not target or not (entry * 0.80 <= target <= entry * 0.999):
            target = entry * 0.90
    else:
        if not stop or not (entry * 0.80 <= stop <= entry * 0.999):
            stop = entry * 0.95
        if not target or not (entry * 1.001 <= target <= entry * 1.60):
            target = entry * 1.10
    return stop, target


def calc_liquidation_price(entry: float, leverage: int) -> float:
    """Isolated margin likidasyon fiyatı hesapla."""
    return round(entry * (1 - 1 / leverage + MAINTENANCE_MARGIN_RATE), 4)


def validate_leverage_trade(
    entry: float,
    stop: float,
    target: float,
    leverage: int,
    margin_usdt: float,
    portfolio_equity: float,
    max_leverage: int = MAX_LEVERAGE,
    max_risk_pct: float = 0.005,
    direction: str = "long",
) -> tuple[bool, str]:
    """Kaldıraçlı işlem güvenlik doğrulaması — (geçerli, mesaj)."""
    if not stop or stop <= 0:
        return False, "stop eksik veya sıfır"
    if not target or target <= 0:
        return False, "take_profit/hedef eksik veya sıfır"
    if leverage > max_leverage:
        return False, f"Kaldıraç {leverage}x limiti ({max_leverage}x) aşıyor"

    if direction == "short":
        risk_per_unit = stop - entry
        reward_per_unit = entry - target
        if risk_per_unit <= 0:
            return False, "short stop giriş fiyatının altında olamaz"
    else:
        risk_per_unit = entry - stop
        reward_per_unit = target - entry
        if risk_per_unit <= 0:
            return False, "stop giriş fiyatının üstünde olamaz"

    rr = reward_per_unit / risk_per_unit if risk_per_unit > 0 else 0
    if rr < 2.0:
        return False, f"R/R {rr:.1f} < 2.0 — yetersiz kâr/risk oranı"

    notional = margin_usdt * leverage
    qty = notional / entry
    risk_usdt = risk_per_unit * qty
    max_risk = portfolio_equity * max_risk_pct
    if risk_usdt > max_risk:
        return False, (
            f"risk {risk_usdt:.0f} USDT > max {max_risk:.0f} USDT "
            f"(portföyün %{max_risk_pct * 100:.1f})"
        )

    liq = calc_liquidation_price(entry, leverage)
    safety_buffer = abs(entry - stop) * 0.5
    if (stop - liq) < safety_buffer:
        return False, (
            f"Likidasyon {liq:.1f} stop'a ({stop:.1f}) çok yakın — "
            "güvenlik tamponu yetersiz"
        )

    return True, ""


def validate_stop_update(
    entry: float,
    current_price: float,
    current_stop: float | None,
    new_stop: float,
    direction: str = "long",
) -> tuple[bool, str]:
    """Stop güncelleme güvenlik kontrolü — (geçerli, sebep)."""
    if new_stop <= 0:
        return False, "sıfır veya negatif stop kabul edilmez"
    if direction == "short":
        if new_stop <= current_price:
            return False, "short stop anlık fiyatın altında veya eşit olamaz"
        if new_stop > entry * 1.25:
            return False, "stop çok geniş — giriş fiyatının %25'inden fazla üstüne çıkamaz"
        if current_stop is not None and new_stop > current_stop:
            return False, "mevcut stoptan kötüye gidiyor — stop geriye alınamaz"
    else:
        if new_stop >= current_price:
            return False, "stop anlık fiyatın üstünde veya eşit olamaz"
        if new_stop < entry * 0.75:
            return False, "stop çok geniş — giriş fiyatının %25'inden fazla altına çekilemez"
        if current_stop is not None and new_stop < current_stop:
            return False, "mevcut stoptan kötüye gidiyor — stop geriye alınamaz"
    return True, ""


@dataclass
class Portfolio:
    cash: float = STARTING_CASH
    positions: dict[str, Position] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_save_lock", threading.Lock())

    # ---- kalıcılık ----
    @classmethod
    def load(cls) -> "Portfolio":
        if STATE_FILE.exists():
            try:
                d = json.loads(STATE_FILE.read_text())
                raw_cash = d.get("cash")
                return cls(
                    cash=float(raw_cash) if raw_cash is not None else STARTING_CASH,
                    positions={s: _load_position(p) for s, p in d.get("positions", {}).items()},
                    history=d.get("history", []),
                )
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        with self._save_lock:
            data = json.dumps(
                {
                    "cash": self.cash,
                    "positions": {s: vars(p) for s, p in self.positions.items()},
                    "history": self.history[-200:],
                },
                indent=2,
            )
            tmp = STATE_FILE.with_suffix(".tmp")
            tmp.write_text(data)
            os.replace(tmp, STATE_FILE)

    def reset(self) -> None:
        self.cash = STARTING_CASH
        self.positions.clear()
        self.history.clear()
        self.save()

    # ---- işlemler ----
    def buy(self, symbol: str, usdt: float, price: float,
            trade_style: str = "spot",
            stop: float | None = None, target: float | None = None) -> str:
        if usdt <= 0:
            raise ValueError("Tutar pozitif olmalı.")
        if usdt > self.cash:
            raise ValueError(f"Yetersiz bakiye: {self.cash:,.2f} USDT mevcut.")
        qty = usdt / price
        pos = self.positions.get(symbol)
        if pos:
            total_cost = pos.qty * pos.entry + usdt
            pos.qty += qty
            pos.entry = total_cost / pos.qty
            if stop is not None:
                pos.stop = stop
            if target is not None:
                pos.target = target
        else:
            self.positions[symbol] = Position(
                qty=qty, entry=price, trade_style=trade_style,
                stop=stop, target=target,
            )
        self.cash -= usdt
        self._log("AL", symbol, qty, price, usdt)
        self.save()
        return f"ALINDI: {qty:.6f} {symbol} @ {price:,.2f} ({usdt:,.2f} USDT)"

    def buy_short(
        self, symbol: str, usdt: float, price: float,
        stop: float, target: float,
    ) -> str:
        if usdt <= 0:
            raise ValueError("Tutar pozitif olmalı.")
        if usdt > self.cash:
            raise ValueError(f"Yetersiz bakiye: {self.cash:,.2f} USDT mevcut.")
        qty = usdt / price
        self.positions[symbol] = Position(
            qty=qty, entry=price, stop=stop, target=target,
            trade_style="short", direction="short",
        )
        self.cash -= usdt
        self._log("SHORT", symbol, qty, price, usdt)
        self.save()
        return f"SHORT AÇILDI: {qty:.6f} {symbol} @ {price:,.2f} ({usdt:,.2f} USDT)"

    def buy_leveraged(
        self, symbol: str, margin_usdt: float, leverage: int,
        price: float, stop: float, target: float,
    ) -> str:
        if margin_usdt > self.cash:
            raise ValueError(f"Yetersiz bakiye: {self.cash:,.2f} USDT mevcut.")
        if symbol in self.positions:
            raise ValueError(f"{symbol}: açık pozisyon var.")
        notional = margin_usdt * leverage
        qty = notional / price
        liq = calc_liquidation_price(price, leverage)
        self.positions[symbol] = Position(
            qty=qty, entry=price, stop=stop, target=target,
            trade_style="leveraged", direction="long",
            is_leveraged=True, leverage=leverage,
            margin_usdt=margin_usdt, notional_usdt=notional,
            liquidation_price=liq,
        )
        self.cash -= margin_usdt
        self._log("LEVERAGE", symbol, qty, price, margin_usdt)
        self.save()
        return (
            f"⚡ LEVERAGE {leverage}x AÇILDI: {qty:.6f} {symbol} @ {price:,.2f} "
            f"(margin: {margin_usdt:,.2f} USDT, notional: {notional:,.2f} USDT)"
        )

    def sell(self, symbol: str, price: float, usdt: float | None = None) -> str:
        pos = self.positions.get(symbol)
        if not pos:
            raise ValueError(f"{symbol} pozisyonu yok.")

        if pos.is_leveraged:
            qty = pos.qty
            if price <= pos.liquidation_price:
                del self.positions[symbol]
                self._log("LİKİDE", symbol, qty, price, 0.0, -pos.margin_usdt)
                self.save()
                return (
                    f"⚡ LİKİDE: {symbol} @ {price:,.2f} — "
                    f"tüm margin ({pos.margin_usdt:,.2f} USDT) kayboldu."
                )
            pnl = (price - pos.entry) * qty
            cash_back = max(0.0, pos.margin_usdt + pnl)
            del self.positions[symbol]
            self.cash += cash_back
            self._log("LEVERAGE KAPATILDI", symbol, qty, price, cash_back, pnl)
            self.save()
            sign = "+" if pnl >= 0 else ""
            return (
                f"LEVERAGE KAPATILDI: {symbol} @ {price:,.2f} → "
                f"K/Z: {sign}{pnl:,.2f} USDT"
            )

        if pos.direction == "short":
            qty = pos.qty if usdt is None else min(usdt / price, pos.qty)
            pnl = (pos.entry - price) * qty
            cash_back = max(0.0, qty * pos.entry + pnl)
            pos.qty -= qty
            if pos.qty * price < 0.01:
                del self.positions[symbol]
            self.cash += cash_back
            self._log("SHORT_KAP", symbol, qty, price, cash_back, pnl)
            self.save()
            sign = "+" if pnl >= 0 else ""
            return (
                f"SHORT KAPANDI: {qty:.6f} {symbol} @ {price:,.2f} → "
                f"K/Z: {sign}{pnl:,.2f} USDT"
            )

        # Spot long
        qty = pos.qty if usdt is None else min(usdt / price, pos.qty)
        proceeds = qty * price
        pnl = (price - pos.entry) * qty
        pos.qty -= qty
        if pos.qty * price < 0.01:
            del self.positions[symbol]
        self.cash += proceeds
        self._log("SAT", symbol, qty, price, proceeds, pnl)
        self.save()
        sign = "+" if pnl >= 0 else ""
        return (
            f"SATILDI: {qty:.6f} {symbol} @ {price:,.2f} → "
            f"{proceeds:,.2f} USDT (K/Z: {sign}{pnl:,.2f})"
        )

    def _log(
        self, side: str, symbol: str, qty: float, price: float,
        usdt: float, pnl: float | None = None,
    ) -> None:
        self.history.append(
            {
                "ts": time.time(), "side": side, "symbol": symbol,
                "qty": qty, "price": price, "usdt": usdt, "pnl": pnl,
            }
        )

    # ---- koruma (zarar-kes / kâr-al) ----
    def set_protection(
        self, symbol: str, stop: float | None, target: float | None,
    ) -> None:
        pos = self.positions.get(symbol)
        if not pos:
            raise ValueError(f"{symbol} pozisyonu yok.")
        pos.stop = stop
        pos.target = target
        self.save()

    def check_triggers(
        self, prices: dict[str, float],
    ) -> list[tuple[str, str, float]]:
        """Stop/hedef/zaman tetikleyicileri: (sembol, tür, fiyat)."""
        out = []
        now = time.time()
        for sym, pos in list(self.positions.items()):
            p = prices.get(sym)

            # Scalp zaman çıkışı
            if pos.trade_style == "scalp" and (now - pos.opened_at) > SCALP_MAX_DURATION:
                out.append((sym, "time_exit", p or pos.entry))
                continue

            if not p:
                continue

            # Kaldıraç likidasyon
            if pos.is_leveraged and p <= pos.liquidation_price:
                out.append((sym, "liquidation", p))
                continue

            if pos.direction == "short":
                if pos.stop and p >= pos.stop:
                    out.append((sym, "stop", p))
                elif pos.target and p <= pos.target:
                    out.append((sym, "target", p))
            else:
                if pos.stop and p <= pos.stop:
                    out.append((sym, "stop", p))
                elif pos.target and p >= pos.target:
                    out.append((sym, "target", p))
        return out

    # ---- değerleme ----
    def leveraged_positions(self) -> dict[str, "Position"]:
        return {s: p for s, p in self.positions.items() if p.is_leveraged}

    def equity(self, prices: dict[str, float]) -> float:
        total = self.cash
        for sym, pos in self.positions.items():
            cur = prices.get(sym, pos.entry)
            if pos.is_leveraged:
                pnl = (cur - pos.entry) * pos.qty
                total += max(0.0, pos.margin_usdt + pnl)
            elif pos.direction == "short":
                # Short: teminat (qty*entry) + kâr/zarar = qty*(2*entry - current)
                pnl = (pos.entry - cur) * pos.qty
                total += max(0.0, pos.qty * pos.entry + pnl)
            else:
                total += pos.qty * cur
        return total

    def unrealized_pnl(self, symbol: str, price: float) -> tuple[float, float]:
        pos = self.positions[symbol]
        if pos.direction == "short":
            pnl = (pos.entry - price) * pos.qty
            pct = (pos.entry / price - 1) * 100 if price else 0.0
        elif pos.is_leveraged:
            pnl = (price - pos.entry) * pos.qty
            pct = (price / pos.entry - 1) * 100 * pos.leverage if pos.entry else 0.0
        else:
            pnl = (price - pos.entry) * pos.qty
            pct = (price / pos.entry - 1) * 100 if pos.entry else 0.0
        return pnl, pct
