"""Profesyonel performans metrikleri — Sharpe, Sortino, Calmar, equity curve.

Girdi: portfolio.history listesi (SAT kayıtlarının pnl alanları kullanılır).
Tüm hesaplamalar standart quant finans formüllerine dayanır.
"""
from __future__ import annotations

import math
import re
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

STARTING_CASH = 10_000.0
BLOCK = "▁▂▃▄▅▆▇█"
RISK_FREE_ANNUAL = 0.05   # %5 yıllık risksiz getiri (tahvil benchmark)
TRADING_DAYS_YEAR = 365   # kripto 365/7 açık

# Tüm kapanış ve açılış tarafları (portfolio.py ile senkron)
_CLOSE_SIDES: frozenset[str] = frozenset({
    "SAT", "SHORT_KAP", "LEVERAGE KAPATILDI", "SCALP_KAP", "LİKİDE"
})
_OPEN_SIDES: frozenset[str] = frozenset({"AL", "SHORT", "LEVERAGE"})


# ── Temel yardımcılar ────────────────────────────────────────────────────────

def _sell_records(history: list[dict]) -> list[dict]:
    """Tüm kapanış kayıtları — SAT, SHORT_KAP, LEVERAGE KAPATILDI, LİKİDE dahil."""
    return [h for h in history if h.get("side") in _CLOSE_SIDES and h.get("pnl") is not None]


def _equity_series(history: list[dict]) -> list[float]:
    """Her kapanış işleminden sonra kümülatif varlık değeri."""
    eq = STARTING_CASH
    out: list[float] = []
    for h in history:
        side = h.get("side", "")
        if side in _OPEN_SIDES:
            eq -= h.get("usdt", 0)
        elif side in _CLOSE_SIDES:
            eq += h.get("usdt", 0)   # usdt = geri dönen nakit (proceeds / cash_back)
            out.append(eq)
    return out if out else [STARTING_CASH]


def _trade_returns_pct(history: list[dict]) -> list[float]:
    """Her kapalı işlemin eşitliğe göre yüzde getirisi."""
    if not _sell_records(history):
        return []
    equity = STARTING_CASH
    returns = []
    for h in history:
        side = h.get("side", "")
        if side in _OPEN_SIDES:
            equity -= h.get("usdt", 0)
        elif side in _CLOSE_SIDES:
            pnl = h.get("pnl") or 0.0
            if equity > 0 and pnl != 0:
                returns.append(pnl / max(equity, 1) * 100)
            equity += h.get("usdt", 0)
    return returns


def _daily_returns_pct(history: list[dict]) -> list[float]:
    """İşlemleri güne göre grupla → günlük % getiri serisi."""
    if not _sell_records(history):
        return []
    daily: dict[str, float] = {}
    equity = STARTING_CASH
    for h in history:
        side = h.get("side", "")
        if side in _OPEN_SIDES:
            equity -= h.get("usdt", 0)
        elif side in _CLOSE_SIDES:
            pnl = h.get("pnl") or 0.0
            day = time.strftime("%Y-%m-%d", time.localtime(h["ts"]))
            daily[day] = daily.get(day, 0) + (pnl / max(equity, 1) * 100)
            equity += h.get("usdt", 0)
    return list(daily.values())


# ── Maliyet özeti ─────────────────────────────────────────────────────────────

def cost_summary(history: list[dict]) -> dict:
    """Gerçekleşen komisyon, kayma ve net PnL özeti."""
    total_fee = sum(h.get("fee_usdt") or 0.0 for h in history)
    total_slip = sum(h.get("slip_usdt") or 0.0 for h in history)
    gross_pnl = sum(
        h.get("pnl") or 0.0
        for h in history if h.get("side") in _CLOSE_SIDES
    )
    return {
        "gross_pnl": round(gross_pnl, 4),
        "total_fee": round(total_fee, 4),
        "total_slip": round(total_slip, 4),
        "net_pnl": round(gross_pnl - total_fee - total_slip, 4),
    }


def equity_breakdown(
    history: list[dict],
    cash: float = STARTING_CASH,
    pos_value: float = 0.0,
    unrealized_pnl: float = 0.0,
    starting_equity: float = STARTING_CASH,
) -> dict:
    """Starting equity'den net PnL'ye tam finansal özet."""
    current_equity = cash + pos_value
    costs = cost_summary(history)
    net = costs["net_pnl"]
    net_return_pct = net / starting_equity * 100 if starting_equity else 0.0
    total_return_pct = (current_equity - starting_equity) / starting_equity * 100 if starting_equity else 0.0
    return {
        "starting_equity": round(starting_equity, 2),
        "current_equity": round(current_equity, 2),
        "cash": round(cash, 2),
        "pos_value": round(pos_value, 2),
        "realized_pnl": costs["gross_pnl"],
        "unrealized_pnl": round(unrealized_pnl, 2),
        "gross_pnl": costs["gross_pnl"],
        "total_fee": costs["total_fee"],
        "total_slip": costs["total_slip"],
        "net_pnl": costs["net_pnl"],
        "net_return_pct": round(net_return_pct, 3),
        "total_return_pct": round(total_return_pct, 3),
    }


def closed_by_type(history: list[dict]) -> dict[str, dict]:
    """Kapalı işlemleri tipe göre gruplandırılmış istatistikler döndür.

    Gruplar: LONG (SAT), SHORT (SHORT_KAP), SCALP (SCALP_KAP),
             LEVERAGE (LEVERAGE KAPATILDI + LİKİDE).
    """
    raw: dict[str, list[dict]] = {"LONG": [], "SHORT": [], "SCALP": [], "LEVERAGE": []}
    for h in history:
        side = h.get("side", "")
        if h.get("pnl") is None:
            continue
        if side == "SAT":
            raw["LONG"].append(h)
        elif side == "SHORT_KAP":
            raw["SHORT"].append(h)
        elif side == "SCALP_KAP":
            raw["SCALP"].append(h)
        elif side in ("LEVERAGE KAPATILDI", "LİKİDE"):
            raw["LEVERAGE"].append(h)

    result: dict[str, dict] = {}
    for typ, trades in raw.items():
        if not trades:
            result[typ] = {
                "count": 0, "wins": 0, "losses": 0,
                "win_rate": 0.0, "total_pnl": 0.0, "net_pnl": 0.0,
            }
            continue
        pnls = [t["pnl"] for t in trades]
        wins = [p for p in pnls if p > 0]
        total_fee = sum(t.get("fee_usdt") or 0.0 for t in trades)
        total_slip = sum(t.get("slip_usdt") or 0.0 for t in trades)
        result[typ] = {
            "count": len(trades),
            "wins": len(wins),
            "losses": len(trades) - len(wins),
            "win_rate": round(len(wins) / len(trades) * 100, 1),
            "total_pnl": round(sum(pnls), 2),
            "net_pnl": round(sum(pnls) - total_fee - total_slip, 2),
        }
    return result


def telegram_summary(
    history: list[dict],
    cash: float,
    equity: float,
    unrealized_pnl: float = 0.0,
    n_positions: int = 0,
) -> str:
    """Telegram için kısa HTML rapor özeti (tek mesaj olarak okunabilir boyut)."""
    stats = trade_stats(history)
    costs = cost_summary(history)
    net = costs["net_pnl"]
    net_pct = net / STARTING_CASH * 100 if STARTING_CASH else 0.0
    total_ret_pct = (equity - STARTING_CASH) / STARTING_CASH * 100

    emoji = "📈" if net >= 0 else "📉"
    sign = "+" if net >= 0 else ""
    eq_sign = "+" if total_ret_pct >= 0 else ""
    open_sign = "+" if unrealized_pnl >= 0 else ""

    if stats.n_total == 0:
        return (
            f"📊 <b>Paper Trading Özet</b>\n\n"
            f"Nakit: <b>{cash:,.2f} USDT</b>\n"
            f"Varlık: <b>{equity:,.2f} USDT</b>\n"
            f"Açık K/Z: {open_sign}{unrealized_pnl:,.2f} USDT\n"
            f"Açık pozisyon: {n_positions}\n\n"
            f"<i>Henüz kapalı işlem yok. Detaylı rapor dosyaya yazıldı.</i>"
        )

    wl_emoji = "🟢" if stats.win_rate >= 50 else "🔴"

    return (
        f"{emoji} <b>Paper Trading Özet</b>\n\n"
        f"<b>💰 Portföy</b>\n"
        f"Başlangıç : {STARTING_CASH:,.0f} USDT\n"
        f"Varlık    : {equity:,.2f} USDT  ({eq_sign}{total_ret_pct:.2f}%)\n"
        f"Nakit     : {cash:,.2f} USDT\n"
        f"Açık K/Z  : {open_sign}{unrealized_pnl:,.2f} USDT  ({n_positions} poz.)\n\n"
        f"<b>📋 İşlemler</b>\n"
        f"Toplam: {stats.n_total}  Kazanan: {stats.n_wins}  Kaybeden: {stats.n_losses}\n"
        f"{wl_emoji} Kazanma: {stats.win_rate:.1f}%  |  PF: {stats.profit_factor:.2f}\n\n"
        f"<b>💵 PnL</b>\n"
        f"Brüt K/Z  : {'+' if costs['gross_pnl'] >= 0 else ''}{costs['gross_pnl']:.2f} USDT\n"
        f"Komisyon  : -{costs['total_fee']:.2f} USDT\n"
        f"Kayma     : -{costs['total_slip']:.2f} USDT\n"
        f"<b>Net K/Z  : {sign}{net:.2f} USDT ({sign}{net_pct:.2f}%)</b>\n\n"
        f"<i>📝 Detaylı rapor dosyaya yazıldı.</i>"
    )


def _strip_rich(text: str) -> str:
    """Rich markup etiketlerini kaldır — .txt dosyası için."""
    return re.sub(r"\[/?[^\]]*\]", "", text)


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
    win_pcts = [p / e * 100 for p, e in zip(pnls, entries) if p > 0 and e > 0]
    loss_pcts = [p / e * 100 for p, e in zip(pnls, entries) if p <= 0 and e > 0]
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

_PAPER_DISCLAIMER = (
    "\n[bold]── ⚠ Paper Mode Uyarıları ──[/]\n"
    "  [bold dark_orange]📝 Bu rapor simülasyon (paper) verisidir — gerçek para riski yoktur.[/]\n"
    "  [green3]✅ Komisyon (%0.1) ve kayma (%0.05) her işlemde simüle edilmektedir.[/]\n"
    "  [red3]❌ Funding rate (fonlama ücreti) henüz hesaplanmıyor.[/]\n"
    "  [red3]❌ Exchange-level stop emirleri yok — stop'lar yazılım tarafından izlenir.[/]\n"
    "  [grey50]📊 Net PnL = Brüt PnL − Komisyon − Kayma maliyeti[/]"
)


def full_report(
    history: list[dict],
    unrealized_pnl: float | None = None,
    *,
    cash: float | None = None,
    pos_value: float = 0.0,
    starting_equity: float = STARTING_CASH,
    positions_data: list[dict] | None = None,
) -> str:
    """Profesyonel performans raporu — Rich markup.

    unrealized_pnl: açık poz. K/Z (opsiyonel, cash verilmediğinde kullanılır).
    cash: anlık nakit — verilirse kapsamlı equity breakdown gösterilir.
    pos_value: açık pozisyonların toplam değeri.
    starting_equity: başlangıç referans bakiyesi (varsayılan 10 000 USDT).
    positions_data: [{symbol, side, entry, current, qty, unrealized_pnl, pnl_pct,
                       stop, target}, ...] — açık pozisyon tablosu için.
    """
    stats = trade_stats(history)
    if stats.n_total == 0 and not positions_data:
        if cash is not None:
            return (
                "[grey50]Henüz kapalı işlem yok — paper trade yap, sonra buraya bak.[/]\n"
                + _PAPER_DISCLAIMER
            )
        return "[grey50]Henüz kapalı işlem yok — paper trade yap, sonra buraya bak.[/]"

    def gc(v: float) -> str:
        return "green3" if v >= 0 else "red3"

    def gs(v: float) -> str:
        return "+" if v >= 0 else ""

    lines = ["[bold cyan]══ Performans Raporu ══[/]"]

    # ── Equity sparkline (kapalı işlem varsa) ──────────────────────────────
    if stats.n_total > 0:
        sparkline = equity_sparkline(history)
        lines.append(f"  Equity : {sparkline}")

    # ── Portföy Durumu (cash sağlanmışsa) ──────────────────────────────────
    if cash is not None:
        unreal = unrealized_pnl if unrealized_pnl is not None else 0.0
        bd = equity_breakdown(history, cash, pos_value, unreal, starting_equity)
        lines += [
            "",
            "[bold]── Portföy Durumu ──[/]",
            f"  Başlangıç Varlık  : [bold]{bd['starting_equity']:>12,.2f} USDT[/]",
            f"  Nakit             : [bold]{bd['cash']:>12,.2f} USDT[/]",
            f"  Açık Poz. Değeri  : [bold]{bd['pos_value']:>12,.2f} USDT[/]",
            f"  Mevcut Varlık     : [bold]{bd['current_equity']:>12,.2f} USDT"
            f"  ({gs(bd['total_return_pct'])}{bd['total_return_pct']:.2f}%)[/]",
            "",
            "[bold]── PnL Dökümü ──[/]",
            f"  Realized PnL (brüt) : [bold {gc(bd['realized_pnl'])}]{gs(bd['realized_pnl'])}{bd['realized_pnl']:>10.2f} USDT[/]",
            f"  Unrealized PnL      : [{gc(bd['unrealized_pnl'])}]{gs(bd['unrealized_pnl'])}{bd['unrealized_pnl']:>10.2f} USDT[/]"
            "  [grey50](açık poz.)[/]",
            f"  Komisyon            : [red3]-{bd['total_fee']:>10.2f} USDT[/]",
            f"  Kayma Maliyeti      : [red3]-{bd['total_slip']:>10.2f} USDT[/]",
            f"  [bold]Net PnL (Realized)  : [bold {gc(bd['net_pnl'])}]{gs(bd['net_pnl'])}{bd['net_pnl']:>10.2f} USDT"
            f"  ({gs(bd['net_return_pct'])}{bd['net_return_pct']:.2f}%)[/][/bold]",
        ]
        if unreal != 0:
            combined = bd["net_pnl"] + unreal
            lines.append(
                f"  Net + Unrealized    : [bold {gc(combined)}]{gs(combined)}{combined:>10.2f} USDT[/]"
            )

    # ── Açık Pozisyonlar ───────────────────────────────────────────────────
    if positions_data:
        lines += ["", f"[bold]── Açık Pozisyonlar ({len(positions_data)}) ──[/]"]
        for pd in positions_data:
            sym = pd["symbol"]
            side = pd.get("side", "LONG")
            entry = pd.get("entry", 0.0)
            cur = pd.get("current", 0.0)
            qty = pd.get("qty", 0.0)
            upnl = pd.get("unrealized_pnl", 0.0)
            pct = pd.get("pnl_pct", 0.0)
            stop = pd.get("stop")
            target = pd.get("target")

            side_colors = {
                "LONG": "green3", "SHORT": "red3", "SCALP": "cyan",
            }
            sc = side_colors.get(side, "gold3")
            pnl_c = gc(upnl)
            name = sym.replace("USDT", "")
            stop_str = f"{stop:,.4f}" if stop else "—"
            tgt_str = f"{target:,.4f}" if target else "—"

            lines.append(
                f"  [bold]{name}/USDT[/]  [{sc}]{side}[/]"
                f"  Giriş: {entry:,.4f} → Şimdi: [bold]{cur:,.4f}[/]"
                f"  K/Z: [{pnl_c}]{gs(upnl)}{upnl:,.2f} USDT ({gs(pct)}{pct:.2f}%)[/]"
            )
            lines.append(
                f"           Miktar: {qty:.6f}"
                f"  Stop: [red3]{stop_str}[/]"
                f"  Hedef: [green3]{tgt_str}[/]"
            )

    # ── İşlem Özeti (kapalı işlem varsa) ───────────────────────────────────
    if stats.n_total > 0:
        wl_color = "green3" if stats.win_rate >= 50 else "red3"
        pf_color = (
            "green3" if stats.profit_factor >= 1.5
            else ("gold3" if stats.profit_factor >= 1.0 else "red3")
        )
        lines += [
            "",
            "[bold]── İşlem Özeti ──[/]",
            f"  İşlem    : {stats.n_total}  "
            f"  Kazanan  : [bold {wl_color}]{stats.n_wins}[/]  "
            f"  Kaybeden : [bold red3]{stats.n_losses}[/]",
            f"  Kazanma  : [bold {wl_color}]{stats.win_rate:.1f}%[/]  "
            f"  Profit F : [bold {pf_color}]{stats.profit_factor:.2f}[/]  "
            f"  Beklenti : {gs(stats.expectancy)}{stats.expectancy:.2f} USDT/işlem",
            f"  Ort Kazanç: [green3]+{stats.avg_win_pct:.2f}%[/]  "
            f"  Ort Kayıp : [red3]{stats.avg_loss_pct:.2f}%[/]",
            f"  En İyi   : [green3]+{stats.best_pnl:.2f} USDT[/]  "
            f"  En Kötü  : [red3]{stats.worst_pnl:.2f} USDT[/]",
        ]

        # ── PnL Dökümü (sadece cash verilmemişse — eski davranış) ──────────
        if cash is None:
            costs = cost_summary(history)
            gross = costs["gross_pnl"]
            fees = costs["total_fee"]
            slip = costs["total_slip"]
            net = costs["net_pnl"]
            has_costs = (fees + slip) > 0

            lines += [
                "",
                "[bold]── PnL Dökümü ──[/]",
                f"  Realized PnL (brüt)  : [bold {gc(gross)}]{gs(gross)}{gross:.4f} USDT[/]",
            ]
            if has_costs:
                lines += [
                    f"  Komisyon maliyeti    : [red3]-{fees:.4f} USDT[/]",
                    f"  Kayma maliyeti       : [red3]-{slip:.4f} USDT[/]",
                    f"  Net PnL              : [bold {gc(net)}]{gs(net)}{net:.4f} USDT[/]",
                ]
            else:
                lines.append(
                    f"  Net PnL              : [bold {gc(gross)}]{gs(gross)}{gross:.4f} USDT[/]"
                    "  [grey50](komisyon/kayma simülasyonu otonom modda)[/]"
                )

            if unrealized_pnl is not None:
                u_color = gc(unrealized_pnl)
                lines.append(
                    f"  Unrealized PnL       : [{u_color}]{gs(unrealized_pnl)}{unrealized_pnl:.4f} USDT[/]"
                    "  [grey50](açık pozisyonlar)[/]"
                )
                total_combined = net + unrealized_pnl
                lines.append(
                    f"  Toplam (net+unreal.) : [bold {gc(total_combined)}]{gs(total_combined)}{total_combined:.4f} USDT[/]"
                )

        # ── Risk-Adjusted Getiri ────────────────────────────────────────────
        sharpe = sharpe_ratio(history)
        sortino = sortino_ratio(history)
        calmar = calmar_ratio(history)
        mdd = max_drawdown(history)

        if sharpe > 2.0:
            sharpe_label, sh_c = "Mükemmel", "green3"
        elif sharpe > 1.0:
            sharpe_label, sh_c = "İyi", "green3"
        elif sharpe > 0.5:
            sharpe_label, sh_c = "Kabul edilebilir", "gold3"
        elif sharpe > 0:
            sharpe_label, sh_c = "Zayıf", "dark_orange"
        else:
            sharpe_label, sh_c = "Negatif", "red3"

        lines += [
            "",
            "[bold]── Risk-Adjusted Getiri ──[/]",
            f"  Sharpe  : [bold {sh_c}]{sharpe:.3f}[/]  [{sh_c}]{sharpe_label}[/]"
            f"   (>1.0 iyi, >2.0 mükemmel)",
            f"  Sortino : [bold]{sortino:.3f}[/]   (Sharpe'ın downside versiyonu)",
            f"  Calmar  : [bold]{calmar:.3f}[/]   (yıllık getiri / max drawdown)",
            f"  Max DD  : [bold red3]-{mdd:.2f}%[/]",
        ]

        # ── Aylık Özet ─────────────────────────────────────────────────────
        monthly = monthly_breakdown(history)
        if monthly:
            lines.append("")
            lines.append("[bold]── Aylık Özet ──[/]")
            for month, pnl, n in monthly:
                mc = gc(pnl)
                bar_len = min(20, abs(int(pnl / 10)))
                bar = ("█" * bar_len).ljust(20)
                lines.append(
                    f"  {month}  [{mc}]{bar}[/]  "
                    f"[{mc}]{gs(pnl)}{pnl:.0f} USDT[/]  "
                    f"[grey50]{n} işlem[/]"
                )

        # ── Tipe Göre Kapalı İşlemler ──────────────────────────────────────
        by_type = closed_by_type(history)
        active_types = [(t, d) for t, d in by_type.items() if d["count"] > 0]
        if active_types:
            lines.append("")
            lines.append("[bold]── Tipe Göre Kapalı İşlemler ──[/]")
            for typ, td in by_type.items():
                if td["count"] == 0:
                    continue
                tc = gc(td["net_pnl"])
                wc = "green3" if td["win_rate"] >= 50 else "red3"
                lines.append(
                    f"  [bold]{typ:<8}[/] {td['count']:>3} işlem  "
                    f"Kaz: [{wc}]{td['win_rate']:.0f}%[/]  "
                    f"Net: [{tc}]{gs(td['net_pnl'])}{td['net_pnl']:,.2f} USDT[/]"
                )

    # ── Paper Mode Disclaimer ───────────────────────────────────────────────
    lines.append(_PAPER_DISCLAIMER)

    return "\n".join(lines)
