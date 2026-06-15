"""Profesyonel performans metrikleri — Sharpe, Sortino, Calmar, equity curve.

Girdi: portfolio.history listesi (SAT kayıtlarının pnl alanları kullanılır).
Tüm hesaplamalar standart quant finans formüllerine dayanır.
"""
from __future__ import annotations

import math
import statistics
import time
from dataclasses import dataclass

STARTING_CASH = 10_000.0
BLOCK = "▁▂▃▄▅▆▇█"
RISK_FREE_ANNUAL = 0.05   # %5 yıllık risksiz getiri (tahvil benchmark)
TRADING_DAYS_YEAR = 365   # kripto 365/7 açık


# ── Temel yardımcılar ────────────────────────────────────────────────────────

def _sell_records(history: list[dict]) -> list[dict]:
    return [h for h in history if h.get("side") == "SAT" and h.get("pnl") is not None]


def _equity_series(history: list[dict]) -> list[float]:
    """Her SAT işleminden sonra kümülatif varlık değeri."""
    eq = STARTING_CASH
    # AL işlemleri nakit düşürür, SAT geri katar + pnl
    out: list[float] = []
    for h in history:
        if h["side"] == "AL":
            eq -= h.get("usdt", 0)
        elif h["side"] == "SAT":
            eq += h.get("usdt", 0) - (h.get("pnl") or 0)  # usdt = giriş + pnl
            out.append(eq)
    return out if out else [STARTING_CASH]


def _trade_returns_pct(history: list[dict]) -> list[float]:
    """Her kapalı işlemin eşitliğe göre yüzde getirisi."""
    sells = _sell_records(history)
    if not sells:
        return []
    equity = STARTING_CASH
    returns = []
    for h in history:
        if h["side"] == "AL":
            equity -= h.get("usdt", 0)
        elif h["side"] == "SAT":
            pnl = h.get("pnl") or 0.0
            usdt = h.get("usdt", 0)
            if equity > 0 and pnl != 0:
                returns.append(pnl / max(equity, 1) * 100)
            equity += usdt
    return returns


def _daily_returns_pct(history: list[dict]) -> list[float]:
    """İşlemleri güne göre grupla → günlük % getiri serisi."""
    sells = _sell_records(history)
    if not sells:
        return []
    daily: dict[str, float] = {}
    equity = STARTING_CASH
    for h in history:
        if h["side"] == "AL":
            equity -= h.get("usdt", 0)
        elif h["side"] == "SAT":
            pnl = h.get("pnl") or 0.0
            day = time.strftime("%Y-%m-%d", time.localtime(h["ts"]))
            daily[day] = daily.get(day, 0) + (pnl / max(equity, 1) * 100)
            equity += h.get("usdt", 0)
    return list(daily.values())


# ── Risk-adjusted getiri metrikleri ──────────────────────────────────────────

def sharpe_ratio(history: list[dict]) -> float:
    """Yıllıklaştırılmış Sharpe oranı (günlük getiri bazlı)."""
    rets = _daily_returns_pct(history)
    if len(rets) < 5:
        return 0.0
    daily_rf = RISK_FREE_ANNUAL / TRADING_DAYS_YEAR * 100
    excess = [r - daily_rf for r in rets]
    avg = statistics.mean(excess)
    std = statistics.stdev(excess) if len(excess) > 1 else 1.0
    if std == 0:
        return 0.0
    return round(avg / std * math.sqrt(TRADING_DAYS_YEAR), 3)


def sortino_ratio(history: list[dict]) -> float:
    """Sortino oranı — yalnızca aşağı yönlü volatilite kullanır."""
    rets = _daily_returns_pct(history)
    if len(rets) < 5:
        return 0.0
    daily_rf = RISK_FREE_ANNUAL / TRADING_DAYS_YEAR * 100
    excess = [r - daily_rf for r in rets]
    avg = statistics.mean(excess)
    downside = [r for r in excess if r < 0]
    if not downside:
        return 99.0
    dd_std = statistics.stdev(downside) if len(downside) > 1 else abs(downside[0])
    if dd_std == 0:
        return 0.0
    return round(avg / dd_std * math.sqrt(TRADING_DAYS_YEAR), 3)


def max_drawdown(history: list[dict]) -> float:
    """Tarihsel maksimum peak-to-trough düşüş (%)."""
    eq = _equity_series(history)
    if len(eq) < 2:
        return 0.0
    peak = eq[0]
    mdd = 0.0
    for e in eq:
        peak = max(peak, e)
        dd = (peak - e) / peak * 100
        mdd = max(mdd, dd)
    return round(mdd, 2)


def calmar_ratio(history: list[dict]) -> float:
    """Calmar = yıllık getiri / maksimum drawdown."""
    sells = _sell_records(history)
    if not sells:
        return 0.0
    first_ts = sells[0]["ts"]
    last_ts = sells[-1]["ts"]
    elapsed_years = (last_ts - first_ts) / (365 * 86400) or (1 / 365)
    eq = _equity_series(history)
    total_ret = (eq[-1] - STARTING_CASH) / STARTING_CASH * 100
    annual_ret = total_ret / elapsed_years
    mdd = max_drawdown(history)
    if mdd == 0:
        return 99.0
    return round(annual_ret / mdd, 3)


# ── İşlem istatistikleri ──────────────────────────────────────────────────────

@dataclass
class TradeStats:
    n_total: int
    n_wins: int
    n_losses: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    expectancy: float      # beklenen kazanç (USDT / işlem)
    best_pnl: float
    worst_pnl: float
    total_pnl: float


def trade_stats(history: list[dict]) -> TradeStats:
    sells = _sell_records(history)
    if not sells:
        return TradeStats(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    pnls = [h["pnl"] for h in sells]
    entries = [h.get("usdt", 1) for h in sells]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    win_pcts = [p / e * 100 for p, e in zip(pnls, entries) if p > 0]
    loss_pcts = [p / e * 100 for p, e in zip(pnls, entries) if p <= 0]
    gross_win = sum(wins) or 0
    gross_loss = abs(sum(losses)) or 1e-9
    return TradeStats(
        n_total=len(pnls),
        n_wins=len(wins),
        n_losses=len(losses),
        win_rate=round(len(wins) / len(pnls) * 100, 1) if pnls else 0.0,
        avg_win_pct=round(statistics.mean(win_pcts), 2) if win_pcts else 0.0,
        avg_loss_pct=round(statistics.mean(loss_pcts), 2) if loss_pcts else 0.0,
        profit_factor=round(gross_win / gross_loss, 3),
        expectancy=round(statistics.mean(pnls), 2) if pnls else 0.0,
        best_pnl=round(max(pnls), 2),
        worst_pnl=round(min(pnls), 2),
        total_pnl=round(sum(pnls), 2),
    )


# ── ASCII Equity Curve ────────────────────────────────────────────────────────

def equity_sparkline(history: list[dict], width: int = 50) -> str:
    """Terminal'de ASCII equity eğrisi."""
    eq = _equity_series(history)
    if len(eq) < 2:
        return "[grey50]Henüz yeterli işlem yok[/]"

    # Downsample to width
    if len(eq) > width:
        step = len(eq) / width
        eq = [eq[int(i * step)] for i in range(width)]

    mn, mx = min(eq), max(eq)
    rng = mx - mn

    if rng == 0:
        bars = "─" * len(eq)
    else:
        bars = "".join(BLOCK[min(7, int((v - mn) / rng * 7.999))] for v in eq)

    start, end = eq[0], eq[-1]
    color = "green3" if end >= start else "red3"
    sign = "+" if end >= start else ""
    pct = (end - start) / start * 100

    return (
        f"[grey50]${start:,.0f}[/]  [{color}]{bars}[/]  [bold {color}]${end:,.0f} ({sign}{pct:.1f}%)[/]"
    )


# ── Aylık breakdown ───────────────────────────────────────────────────────────

def monthly_breakdown(history: list[dict]) -> list[tuple[str, float, int]]:
    """(ay, toplam_pnl, işlem_sayısı) listesi — son 6 ay."""
    sells = _sell_records(history)
    monthly: dict[str, list[float]] = {}
    for h in sells:
        month = time.strftime("%Y-%m", time.localtime(h["ts"]))
        monthly.setdefault(month, []).append(h["pnl"])
    result = [(m, sum(v), len(v)) for m, v in sorted(monthly.items())]
    return result[-6:]


# ── Tam rapor ────────────────────────────────────────────────────────────────

def full_report(history: list[dict]) -> str:
    """Profesyonel performans raporu — Rich markup."""
    stats = trade_stats(history)
    if stats.n_total == 0:
        return "[grey50]Henüz kapalı işlem yok — paper trade yap, sonra buraya bak.[/]"

    sharpe = sharpe_ratio(history)
    sortino = sortino_ratio(history)
    calmar = calmar_ratio(history)
    mdd = max_drawdown(history)
    sparkline = equity_sparkline(history)

    # Sharpe yorumu
    if sharpe > 2.0:
        sharpe_label, sc = "Mükemmel", "green3"
    elif sharpe > 1.0:
        sharpe_label, sc = "İyi", "green3"
    elif sharpe > 0.5:
        sharpe_label, sc = "Kabul edilebilir", "gold3"
    elif sharpe > 0:
        sharpe_label, sc = "Zayıf", "dark_orange"
    else:
        sharpe_label, sc = "Negatif", "red3"

    wl_color = "green3" if stats.win_rate >= 50 else "red3"
    pf_color = "green3" if stats.profit_factor >= 1.5 else ("gold3" if stats.profit_factor >= 1.0 else "red3")

    lines = [
        "[bold cyan]══ Performans Raporu ══[/]",
        f"  Equity : {sparkline}",
        "",
        "[bold]── İşlem Özeti ──[/]",
        f"  İşlem    : {stats.n_total}  "
        f"  Kazanan  : [bold {wl_color}]{stats.n_wins}[/]  "
        f"  Kaybeden : [bold red3]{stats.n_losses}[/]",
        f"  Kazanma  : [bold {wl_color}]{stats.win_rate:.1f}%[/]  "
        f"  Profit F : [bold {pf_color}]{stats.profit_factor:.2f}[/]  "
        f"  Beklenti : {'+' if stats.expectancy >= 0 else ''}{stats.expectancy:.2f} USDT/işlem",
        f"  Ort Kazanç: [green3]+{stats.avg_win_pct:.2f}%[/]  "
        f"  Ort Kayıp : [red3]{stats.avg_loss_pct:.2f}%[/]",
        f"  En İyi   : [green3]+{stats.best_pnl:.2f} USDT[/]  "
        f"  En Kötü  : [red3]{stats.worst_pnl:.2f} USDT[/]",
        f"  Toplam PnL: [bold {'green3' if stats.total_pnl >= 0 else 'red3'}]"
        f"{'+' if stats.total_pnl >= 0 else ''}{stats.total_pnl:.2f} USDT[/]",
        "",
        "[bold]── Risk-Adjusted Getiri ──[/]",
        f"  Sharpe  : [bold {sc}]{sharpe:.3f}[/]  [{sc}]{sharpe_label}[/]"
        f"   (>1.0 iyi, >2.0 mükemmel)",
        f"  Sortino : [bold]{sortino:.3f}[/]   (Sharpe'ın downside versiyonu)",
        f"  Calmar  : [bold]{calmar:.3f}[/]   (yıllık getiri / max drawdown)",
        f"  Max DD  : [bold red3]-{mdd:.2f}%[/]",
    ]

    # Aylık breakdown
    monthly = monthly_breakdown(history)
    if monthly:
        lines.append("")
        lines.append("[bold]── Aylık Özet ──[/]")
        for month, pnl, n in monthly:
            c = "green3" if pnl >= 0 else "red3"
            bar_len = min(20, abs(int(pnl / 10)))
            bar = ("█" * bar_len).ljust(20)
            lines.append(
                f"  {month}  [{c}]{bar}[/]  "
                f"[{c}]{'+' if pnl >= 0 else ''}{pnl:.0f} USDT[/]  "
                f"[grey50]{n} işlem[/]"
            )

    return "\n".join(lines)
