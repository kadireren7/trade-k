"""Profesyonel portföy risk yönetimi.

Fonksiyonlar:
  portfolio_heat()     — açık pozisyonların toplam risk %'si
  position_var()       — tek pozisyon VaR
  correlation_warning()— BTC/ETH yoğunlaşma uyarısı
  check_before_buy()   — alım öncesi risk kapısı
  risk_dashboard()     — tam risk raporu (Rich markup)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from portfolio import Portfolio, Position

# Sabitler — bunlar config'den override edilebilir
MAX_PORTFOLIO_HEAT = 15.0      # % — toplam risk limiti (açık tüm stop mesafeleri toplamı)
MAX_SINGLE_POSITION_PCT = 35.0  # % — tek pozisyon varlığın max %'si
MAX_CORRELATED_EXPOSURE = 60.0  # % — BTC+ETH gibi korelasyonlu grup limiti
DEFAULT_STOP_PCT = 5.0          # % — stop belirlenmemişse varsayılan risk uzaklığı

# Yüksek korelasyonlu grup — hepsi birlikte tutulursa risk büyür
BTC_CORRELATED = {"BTCUSDT", "BTCEUR", "BTC"}
ETH_CORRELATED = {"ETHUSDT", "ETHEUR", "ETH"}


# ── Portfolio Heat ────────────────────────────────────────────────────────────

def portfolio_heat(portfolio: "Portfolio", prices: dict[str, float]) -> float:
    """Açık pozisyonların toplam risk %, stop mesafeleri üzerinden.

    Heat = Σ (pozisyon_değeri × stop_uzaklık_pct) / toplam_varlık × 100
    """
    total_equity = portfolio.equity(prices)
    if total_equity <= 0:
        return 0.0
    total_risk_usdt = 0.0
    for sym, pos in portfolio.positions.items():
        price = prices.get(sym) or pos.entry
        pos_val = pos.qty * price
        if pos.stop:
            stop_pct = abs(price - pos.stop) / price
        else:
            stop_pct = DEFAULT_STOP_PCT / 100
        total_risk_usdt += pos_val * stop_pct
    return round(total_risk_usdt / total_equity * 100, 2)


def single_position_pct(pos: "Position", sym: str,
                         prices: dict[str, float], equity: float) -> float:
    """Tek pozisyonun toplam varlığa oranı %."""
    price = prices.get(sym) or pos.entry
    pos_val = pos.qty * price
    return round(pos_val / equity * 100, 2) if equity > 0 else 0.0


def correlated_exposure(portfolio: "Portfolio", prices: dict[str, float]) -> dict[str, float]:
    """BTC ve ETH korelasyon gruplarının portföydeki ağırlığı %."""
    equity = portfolio.equity(prices)
    if equity <= 0:
        return {}
    groups: dict[str, float] = {}
    for sym, pos in portfolio.positions.items():
        price = prices.get(sym) or pos.entry
        pct = pos.qty * price / equity * 100
        if sym in BTC_CORRELATED:
            groups["BTC Grubu"] = groups.get("BTC Grubu", 0) + pct
        if sym in ETH_CORRELATED:
            groups["ETH Grubu"] = groups.get("ETH Grubu", 0) + pct
    return {k: round(v, 1) for k, v in groups.items()}


# ── Alım öncesi risk kapısı ───────────────────────────────────────────────────

@dataclass
class RiskGateResult:
    allowed: bool
    warnings: list[str]
    blockers: list[str]

    def ok(self) -> bool:
        return self.allowed and not self.blockers


def check_before_buy(
    symbol: str,
    amount_usdt: float,
    portfolio: "Portfolio",
    prices: dict[str, float],
    stop_pct: float | None = None,
) -> RiskGateResult:
    """Alım yapılmadan önce risk kurallarını kontrol et."""
    warnings: list[str] = []
    blockers: list[str] = []
    equity = portfolio.equity(prices)

    # 1. Nakit yeterli mi?
    if amount_usdt > portfolio.cash:
        blockers.append(f"Yetersiz nakit: {portfolio.cash:,.2f} USDT mevcut, {amount_usdt:,.2f} USDT gerekli")

    # 2. Portfolio heat — limiti aşıyor mu?
    heat = portfolio_heat(portfolio, prices)
    if heat >= MAX_PORTFOLIO_HEAT:
        blockers.append(
            f"Portföy ısısı DOLU: %{heat:.1f} (limit %{MAX_PORTFOLIO_HEAT:.0f}) — "
            "önce bir pozisyonu kapat veya stop'ları sıkılaştır"
        )
    elif heat >= MAX_PORTFOLIO_HEAT * 0.85:
        warnings.append(f"Portföy ısısı yüksek: %{heat:.1f} / %{MAX_PORTFOLIO_HEAT:.0f}")

    # 3. Tek pozisyon limiti
    pos_pct = amount_usdt / equity * 100 if equity > 0 else 100
    if pos_pct > MAX_SINGLE_POSITION_PCT:
        warnings.append(
            f"Bu alım varlığın %{pos_pct:.0f}'ini oluşturuyor "
            f"(tavsiye max %{MAX_SINGLE_POSITION_PCT:.0f})"
        )

    # 4. Korelasyon kontrolü
    corr = correlated_exposure(portfolio, prices)
    for grp, pct in corr.items():
        if symbol in (BTC_CORRELATED if "BTC" in grp else ETH_CORRELATED):
            new_pct = pct + pos_pct
            if new_pct > MAX_CORRELATED_EXPOSURE:
                warnings.append(
                    f"{grp} yoğunlaşması: %{new_pct:.0f} > limit %{MAX_CORRELATED_EXPOSURE:.0f}"
                )

    # 5. Stop tanımsızsa uyar
    if stop_pct is None and symbol not in portfolio.positions:
        warnings.append("Stop belirlenmedi — girdikten sonra /koru komutu ile stop koy")

    allowed = len(blockers) == 0
    return RiskGateResult(allowed=allowed, warnings=warnings, blockers=blockers)


# ── Risk Dashboard ────────────────────────────────────────────────────────────

def risk_dashboard(portfolio: "Portfolio", prices: dict[str, float]) -> str:
    """Profesyonel risk paneli — Rich markup."""
    equity = portfolio.equity(prices)
    heat = portfolio_heat(portfolio, prices)
    corr = correlated_exposure(portfolio, prices)
    n_pos = len(portfolio.positions)

    heat_color = "green3" if heat < 8 else ("gold3" if heat < MAX_PORTFOLIO_HEAT else "red3")
    heat_bar_len = min(20, int(heat / MAX_PORTFOLIO_HEAT * 20))
    heat_bar = ("█" * heat_bar_len).ljust(20, "░")

    lines = [
        "[bold cyan]══ Risk Paneli ══[/]",
        f"  Toplam Varlık  : [bold]${equity:,.2f}[/]",
        f"  Nakit          : [bold]${portfolio.cash:,.2f}[/]  (%{portfolio.cash/equity*100:.0f})",
        f"  Açık Pozisyon  : {n_pos}",
        "",
        f"  [bold]Portföy Isısı[/] [{heat_color}]{heat_bar}[/] [bold {heat_color}]%{heat:.1f}[/] / %{MAX_PORTFOLIO_HEAT:.0f}",
        "  (Tüm pozisyonların stop seviyelerine kadar toplam risk)",
        "",
    ]

    if portfolio.positions:
        lines.append("[bold]── Pozisyon Detayı ──[/]")
        for sym, pos in portfolio.positions.items():
            price = prices.get(sym) or pos.entry
            pos_val = pos.qty * price
            pct_of_eq = pos_val / equity * 100 if equity else 0
            pnl = (price - pos.entry) * pos.qty
            pnl_pct = (price / pos.entry - 1) * 100 if pos.entry else 0
            pnl_c = "green3" if pnl >= 0 else "red3"
            stop_dist = ((price - pos.stop) / price * 100) if pos.stop else None
            stop_str = f"  stop: {pos.stop:,.2f} (-%{stop_dist:.1f})" if stop_dist else "  stop: YOK ⚠"
            lines.append(
                f"  [bold]{sym}[/]  ${pos_val:,.2f} (%{pct_of_eq:.1f})"
                f"  [{pnl_c}]{'+' if pnl >= 0 else ''}{pnl:.2f} ({pnl_pct:+.2f}%)[/]"
                f"{stop_str}"
            )

    if corr:
        lines.append("")
        lines.append("[bold]── Korelasyon Grupları ──[/]")
        for grp, pct in corr.items():
            c = "red3" if pct > MAX_CORRELATED_EXPOSURE else ("gold3" if pct > 40 else "green3")
            lines.append(f"  {grp}: [{c}]%{pct:.1f}[/]")

    # Tavsiyeler
    lines.append("")
    lines.append("[bold]── Tavsiyeler ──[/]")
    if heat >= MAX_PORTFOLIO_HEAT:
        lines.append(f"  [red3]⚠ Portföy ısısı limitte — yeni pozisyon açma![/]")
    elif heat < 5:
        lines.append(f"  [green3]✔ Portföy ısısı düşük — yeni pozisyon için yer var[/]")
    else:
        lines.append(f"  [gold3]~ Orta düzeyde risk — dikkatli genişle[/]")

    no_stop = [sym for sym, pos in portfolio.positions.items() if not pos.stop]
    if no_stop:
        lines.append(f"  [red3]⚠ Stop eksik: {', '.join(no_stop)} — /koru ile ekle![/]")
    else:
        lines.append("  [green3]✔ Tüm pozisyonlarda stop var[/]")

    return "\n".join(lines)
