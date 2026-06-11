"""Paper trading cüzdanı — sanal bakiye, pozisyonlar ve işlem geçmişi.

Durum account.json dosyasında saklanır; uygulama kapansa da kaybolmaz.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

STATE_FILE = Path(__file__).parent / "account.json"
STARTING_CASH = 10_000.0


@dataclass
class Position:
    qty: float
    entry: float  # ortalama giriş fiyatı (USDT)
    stop: float | None = None    # zarar-kes fiyatı (otomatik satış)
    target: float | None = None  # kâr-al fiyatı (otomatik satış)


def sanitize_levels(entry: float, stop: float, target: float) -> tuple[float, float]:
    """Claude'un verdiği stop/hedef seviyelerini kod tarafında doğrula.

    Mantıksız değerlerde güvenli varsayılana çek: stop girişin %0.1-20 altında
    olmalı (değilse %5 altı), hedef girişin %0.1-60 üstünde olmalı (değilse %10 üstü).
    """
    if not stop or not (entry * 0.80 <= stop <= entry * 0.999):
        stop = entry * 0.95
    if not target or not (entry * 1.001 <= target <= entry * 1.60):
        target = entry * 1.10
    return stop, target


@dataclass
class Portfolio:
    cash: float = STARTING_CASH
    positions: dict[str, Position] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    # ---- kalıcılık ----
    @classmethod
    def load(cls) -> "Portfolio":
        if STATE_FILE.exists():
            d = json.loads(STATE_FILE.read_text())
            return cls(
                cash=d["cash"],
                positions={s: Position(**p) for s, p in d["positions"].items()},
                history=d.get("history", []),
            )
        return cls()

    def save(self) -> None:
        STATE_FILE.write_text(json.dumps({
            "cash": self.cash,
            "positions": {s: vars(p) for s, p in self.positions.items()},
            "history": self.history[-200:],
        }, indent=2))

    def reset(self) -> None:
        self.cash = STARTING_CASH
        self.positions.clear()
        self.history.clear()
        self.save()

    # ---- işlemler ----
    def buy(self, symbol: str, usdt: float, price: float) -> str:
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
        else:
            self.positions[symbol] = Position(qty=qty, entry=price)
        self.cash -= usdt
        self._log("AL", symbol, qty, price, usdt)
        self.save()
        return f"ALINDI: {qty:.6f} {symbol} @ {price:,.2f} ({usdt:,.2f} USDT)"

    def sell(self, symbol: str, price: float, usdt: float | None = None) -> str:
        pos = self.positions.get(symbol)
        if not pos:
            raise ValueError(f"{symbol} pozisyonu yok.")
        if usdt is None:  # hepsini sat
            qty = pos.qty
        else:
            qty = min(usdt / price, pos.qty)
        proceeds = qty * price
        pnl = (price - pos.entry) * qty
        pos.qty -= qty
        if pos.qty * price < 0.01:
            del self.positions[symbol]
        self.cash += proceeds
        self._log("SAT", symbol, qty, price, proceeds, pnl)
        self.save()
        sign = "+" if pnl >= 0 else ""
        return f"SATILDI: {qty:.6f} {symbol} @ {price:,.2f} → {proceeds:,.2f} USDT (K/Z: {sign}{pnl:,.2f})"

    def _log(self, side: str, symbol: str, qty: float, price: float,
             usdt: float, pnl: float | None = None) -> None:
        self.history.append({
            "ts": time.time(), "side": side, "symbol": symbol,
            "qty": qty, "price": price, "usdt": usdt, "pnl": pnl,
        })

    # ---- koruma (zarar-kes / kâr-al) ----
    def set_protection(self, symbol: str, stop: float | None,
                       target: float | None) -> None:
        pos = self.positions.get(symbol)
        if not pos:
            raise ValueError(f"{symbol} pozisyonu yok.")
        pos.stop = stop
        pos.target = target
        self.save()

    def check_triggers(self, prices: dict[str, float]) -> list[tuple[str, str, float]]:
        """Stop/hedef seviyesi gelen pozisyonlar: (sembol, 'stop'|'target', fiyat)."""
        out = []
        for sym, pos in self.positions.items():
            p = prices.get(sym)
            if not p:
                continue
            if pos.stop and p <= pos.stop:
                out.append((sym, "stop", p))
            elif pos.target and p >= pos.target:
                out.append((sym, "target", p))
        return out

    # ---- değerleme ----
    def equity(self, prices: dict[str, float]) -> float:
        total = self.cash
        for sym, pos in self.positions.items():
            total += pos.qty * prices.get(sym, pos.entry)
        return total

    def unrealized_pnl(self, symbol: str, price: float) -> tuple[float, float]:
        pos = self.positions[symbol]
        pnl = (price - pos.entry) * pos.qty
        pct = (price / pos.entry - 1) * 100 if pos.entry else 0.0
        return pnl, pct
