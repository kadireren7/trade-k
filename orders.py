"""Paper limit emir defteri — gerçekçi emir simülasyonu.

Live modda Binance zaten limit emirleri yönetir.
Paper modda bu modül fiyat tetiklenince otomatik doldurur.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

ORDERS_FILE = Path(__file__).parent / "orders.json"
DEFAULT_EXPIRY_HOURS = 24.0


@dataclass
class LimitOrder:
    id: str
    symbol: str
    side: str              # "AL" | "SAT"
    limit_price: float     # fiyat bu seviyeye gelince doldur
    amount_usdt: float     # AL için: kaç USDT   SAT için: kaç coin × entry_price
    qty: float             # SAT için coin miktarı (AL'da 0 kullan)
    created_at: float = field(default_factory=time.time)
    expiry_hours: float = DEFAULT_EXPIRY_HOURS
    note: str = ""
    filled: bool = False
    filled_at: float | None = None
    filled_price: float | None = None

    @property
    def expired(self) -> bool:
        return time.time() > self.created_at + self.expiry_hours * 3600

    @property
    def direction(self) -> str:
        return "AL: limit ≤" if self.side == "AL" else "SAT: limit ≥"

    def summary(self) -> str:
        age_h = (time.time() - self.created_at) / 3600
        note_str = f"  [{self.note}]" if self.note else ""
        return (
            f"[bold]{self.id[:8]}[/] {self.symbol} {self.direction} "
            f"{self.limit_price:,.4f}  "
            f"{'$'+str(round(self.amount_usdt,0))+' USDT' if self.side == 'AL' else str(round(self.qty,6))+' coin'}"
            f"  [grey50]{age_h:.1f}sa önce{note_str}[/]"
        )


class LimitOrderBook:
    """Paper mode için limit emir yöneticisi."""

    def __init__(self) -> None:
        self._orders: list[LimitOrder] = []
        self._load()

    # ── Kalıcılık ─────────────────────────────────────────────────────────────

    def _load(self) -> None:
        if ORDERS_FILE.exists():
            try:
                raw = json.loads(ORDERS_FILE.read_text())
                self._orders = [LimitOrder(**d) for d in raw if not d.get("filled")]
            except Exception:
                self._orders = []

    def _save(self) -> None:
        data = json.dumps([asdict(o) for o in self._orders], indent=2)
        tmp = ORDERS_FILE.with_suffix(".tmp")
        tmp.write_text(data)
        os.replace(tmp, ORDERS_FILE)

    # ── Emir işlemleri ────────────────────────────────────────────────────────

    def add_buy(
        self,
        symbol: str,
        limit_price: float,
        amount_usdt: float,
        expiry_hours: float = DEFAULT_EXPIRY_HOURS,
        note: str = "",
    ) -> LimitOrder:
        order = LimitOrder(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side="AL",
            limit_price=limit_price,
            amount_usdt=amount_usdt,
            qty=0.0,
            expiry_hours=expiry_hours,
            note=note,
        )
        self._orders.append(order)
        self._save()
        return order

    def add_sell(
        self,
        symbol: str,
        limit_price: float,
        qty: float,
        expiry_hours: float = DEFAULT_EXPIRY_HOURS,
        note: str = "",
    ) -> LimitOrder:
        order = LimitOrder(
            id=str(uuid.uuid4()),
            symbol=symbol,
            side="SAT",
            limit_price=limit_price,
            amount_usdt=qty * limit_price,
            qty=qty,
            expiry_hours=expiry_hours,
            note=note,
        )
        self._orders.append(order)
        self._save()
        return order

    def cancel(self, order_id_prefix: str) -> list[LimitOrder]:
        """ID prefix'ine göre iptal et."""
        cancelled = [o for o in self._orders if o.id.startswith(order_id_prefix)]
        self._orders = [o for o in self._orders if not o.id.startswith(order_id_prefix)]
        self._save()
        return cancelled

    def cancel_symbol(self, symbol: str) -> int:
        before = len(self._orders)
        self._orders = [o for o in self._orders if o.symbol != symbol]
        self._save()
        return before - len(self._orders)

    def cancel_all(self) -> int:
        n = len(self._orders)
        self._orders.clear()
        self._save()
        return n

    def pending(self) -> list[LimitOrder]:
        """Dolmamış ve süresi geçmemiş emirler."""
        active = [o for o in self._orders if not o.filled and not o.expired]
        if len(active) < len(self._orders):
            # Süresi geçenleri temizle
            self._orders = active
            self._save()
        return active

    def check_fills(
        self, prices: dict[str, float]
    ) -> list[tuple[LimitOrder, float]]:
        """Canlı fiyatları kontrol et, dolmuş emirleri döndür (emir, fill_price)."""
        filled: list[tuple[LimitOrder, float]] = []
        remaining: list[LimitOrder] = []
        for order in self._orders:
            if order.filled or order.expired:
                continue
            price = prices.get(order.symbol)
            if price is None:
                remaining.append(order)
                continue
            # AL emiri: fiyat limit fiyatına düşünce doldur
            # SAT emiri: fiyat limit fiyatına çıkınca doldur
            triggered = (
                (order.side == "AL" and price <= order.limit_price)
                or (order.side == "SAT" and price >= order.limit_price)
            )
            if triggered:
                order.filled = True
                order.filled_at = time.time()
                order.filled_price = price
                filled.append((order, price))
            else:
                remaining.append(order)
        self._orders = remaining
        if filled:
            self._save()
        return filled

    def __len__(self) -> int:
        return len(self.pending())


# Singleton
_book: LimitOrderBook | None = None


def book() -> LimitOrderBook:
    global _book
    if _book is None:
        _book = LimitOrderBook()
    return _book
