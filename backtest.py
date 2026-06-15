"""Profesyonel backtesting motoru — RSI + MACD + BB stratejisi.

İçerir:
  run()               — tek sembol, tek dönem backtest
  walk_forward()      — %70 in-sample / %30 out-of-sample ayrımı
  multi_symbol_scan() — birden fazla sembolu sıralar
  monte_carlo()       — trade sırası randomize edilerek dağılım analizi
  significance()      — binomial p-value + Sharpe t-istatistiği
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

import httpx
from indicators import _rsi, _ema, _bb, _score_and_signal

BINANCE_BASE = "https://api.binance.com"

_TF_CANDLES_PER_DAY: dict[str, int] = {
    "1m": 1440, "3m": 480, "5m": 288, "15m": 96,
    "30m": 48, "1h": 24, "2h": 12, "4h": 6,
    "6h": 4, "12h": 2, "1d": 1,
}
MAX_BINANCE_LIMIT = 1000
WARMUP = 52  # EMA50 ısınması için minimum mum


# ── Veri yapıları ─────────────────────────────────────────────────────────────

@dataclass
class BtTrade:
    bar: int
    entry_price: float
    exit_price: float
    pnl_pct: float
    exit_reason: str   # STOP | HEDEF | SİNYAL


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    n_candles: int
    n_trades: int
    wins: int
    losses: int
    win_rate: float
    total_return_pct: float
    max_drawdown_pct: float
    profit_factor: float
    avg_win_pct: float
    avg_loss_pct: float
    stop_pct: float
    target_pct: float
    label: str = ""                    # "In-Sample" | "Out-of-Sample" | ""
    trades: list[BtTrade] = field(default_factory=list, repr=False)

    def summary(self, color: bool = True) -> str:
        pf_str = f"{self.profit_factor:.2f}" if self.profit_factor < 999 else "∞"
        ret_c = "green3" if self.total_return_pct >= 0 else "red3"
        lbl = f"[bold cyan][{self.label}][/]  " if self.label else ""
        sig = significance(self.wins, self.n_trades)
        p_str = f"p={sig.p_value:.3f}" if sig.p_value < 1 else ""
        t_str = f"t={sig.sharpe_t:.2f}" if sig.n_returns >= 5 else ""
        stat_str = f"  [grey50]{p_str}  {t_str}[/]" if (p_str or t_str) else ""
        return (
            f"{lbl}[bold]{self.symbol}[/]  [{self.timeframe}]  {self.n_candles} mum\n"
            f"  İşlem: {self.n_trades}  |  Kazanma: [bold]{self.win_rate:.1f}%[/]  "
            f"({self.wins}K/{self.losses}K){stat_str}\n"
            f"  Toplam getiri: [bold {ret_c}]"
            f"{'+' if self.total_return_pct >= 0 else ''}{self.total_return_pct:.2f}%[/]  |  "
            f"Max DD: [bold red3]-{self.max_drawdown_pct:.2f}%[/]  |  PF: [bold]{pf_str}[/]\n"
            f"  Ort kazanç: +{self.avg_win_pct:.2f}%  |  Ort kayıp: {self.avg_loss_pct:.2f}%  |  "
            f"Stop: {self.stop_pct*100:.1f}%  Hedef: {self.target_pct*100:.1f}%"
        )


@dataclass
class SignificanceResult:
    wins: int
    total: int
    p_value: float       # binomial p-değeri (H0: win_rate=50%)
    significant: bool    # p < 0.05
    sharpe_approx: float # yaklaşık Sharpe (win_rate / std)
    sharpe_t: float      # t-istatistiği = Sharpe × √n
    n_returns: int       # dönüş serisi uzunluğu
    verdict: str


# ── İstatistiksel anlamlılık ──────────────────────────────────────────────────

def _binomial_p(wins: int, n: int, p0: float = 0.5) -> float:
    """P(X ≥ wins | Binomial(n, p0)) — one-sided."""
    if n == 0:
        return 1.0
    # Normal approximation for large n (accurate for n>30)
    if n > 30:
        mu = n * p0
        sigma = math.sqrt(n * p0 * (1 - p0))
        z = (wins - mu) / sigma if sigma else 0.0
        # Approximate P(Z > z) using error function
        return max(0.0, 0.5 * (1 - math.erf(z / math.sqrt(2))))
    # Exact for small n
    from math import comb
    p = sum(comb(n, k) * (p0 ** k) * ((1 - p0) ** (n - k)) for k in range(wins, n + 1))
    return round(min(p, 1.0), 5)


def significance(wins: int, total: int, trade_pnls: list[float] | None = None) -> SignificanceResult:
    """Win rate ve Sharpe istatistiksel anlamlılığı."""
    if total == 0:
        return SignificanceResult(0, 0, 1.0, False, 0.0, 0.0, 0, "Veri yok")

    p_val = _binomial_p(wins, total)
    sig = p_val < 0.05

    # Sharpe yaklaşımı (trade bazlı)
    wr = wins / total
    # Win rate'i Sharpe proxy olarak kullan (wr=0 veya wr=1 durumunda paydanın sıfır olmaması için)
    _variance = wr * (1 - wr)
    sharpe_approx = (wr - 0.5) / math.sqrt(_variance / max(total, 1)) if (total > 1 and _variance > 0) else 0.0
    sharpe_t = sharpe_approx * math.sqrt(total)
    n_ret = len(trade_pnls) if trade_pnls else total

    if p_val < 0.01:
        verdict = "[bold green3]Güçlü istatistiksel kanıt (%99)[/]"
    elif p_val < 0.05:
        verdict = "[green3]İstatistiksel olarak anlamlı (%95)[/]"
    elif p_val < 0.10:
        verdict = "[gold3]Sınırda (%90) — daha fazla veri gerekli[/]"
    elif total < 20:
        verdict = "[gold3]Yetersiz işlem sayısı (<20) — sonuç güvenilmez[/]"
    else:
        verdict = "[red3]İstatistiksel kanıt yok — şans eseri olabilir[/]"

    return SignificanceResult(
        wins=wins, total=total, p_value=round(p_val, 4),
        significant=sig, sharpe_approx=round(sharpe_approx, 3),
        sharpe_t=round(sharpe_t, 3), n_returns=n_ret, verdict=verdict,
    )


# ── Çekirdek backtest motoru ──────────────────────────────────────────────────

def _run_on_candles(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    symbol: str,
    timeframe: str,
    stop_pct: float,
    target_pct: float,
    slippage_pct: float,
    label: str = "",
) -> BacktestResult:
    """OHLCV dizisi üzerinde stratejiyi çalıştır."""
    trades: list[BtTrade] = []
    in_pos = False
    entry = stop_lvl = tgt_lvl = 0.0
    equity = 1.0
    peak = 1.0
    max_dd = 0.0

    for i in range(WARMUP, len(closes)):
        c_s = closes[: i + 1]
        price = closes[i]

        e12 = _ema(c_s, 12)
        e26 = _ema(c_s, 26)
        if len(e12) > len(e26):
            e12 = e12[-len(e26):]
        elif len(e26) > len(e12):
            e26 = e26[-len(e12):]
        ml = [a - b for a, b in zip(e12, e26)]
        ms = _ema(ml, 9)

        sig, _, _ = _score_and_signal(
            price,
            _rsi(c_s),
            ml[-1] if ml else 0.0,
            ms[-1] if ms else 0.0,
            *_bb(c_s)[:1], _bb(c_s)[2],   # bb_upper, bb_lower
            _ema(c_s, 20)[-1] if len(c_s) >= 20 else price,
            _ema(c_s, 50)[-1] if len(c_s) >= 50 else price,
            1.0,
        )

        if not in_pos:
            if sig in ("AL", "GÜÇLÜ_AL"):
                in_pos = True
                entry = price * (1 + slippage_pct)
                stop_lvl = entry * (1 - stop_pct)
                tgt_lvl = entry * (1 + target_pct)
        else:
            hit_stop = lows[i] <= stop_lvl
            hit_target = highs[i] >= tgt_lvl
            exit_sig = sig in ("SAT", "GÜÇLÜ_SAT")
            if hit_stop or hit_target or exit_sig:
                if hit_stop:
                    ep, reason = stop_lvl * (1 - slippage_pct), "STOP"
                elif hit_target:
                    ep, reason = tgt_lvl * (1 - slippage_pct), "HEDEF"
                else:
                    ep, reason = price * (1 - slippage_pct), "SİNYAL"
                pnl = (ep - entry) / entry * 100.0
                trades.append(BtTrade(i, entry, ep, pnl, reason))
                equity *= 1.0 + pnl / 100.0
                peak = max(peak, equity)
                max_dd = max(max_dd, (peak - equity) / peak * 100.0)
                in_pos = False

    wins = [t for t in trades if t.pnl_pct > 0]
    losses = [t for t in trades if t.pnl_pct <= 0]
    n = len(trades)
    gross_loss = abs(sum(t.pnl_pct for t in losses)) or 1e-9

    return BacktestResult(
        symbol=symbol, timeframe=timeframe, n_candles=len(closes),
        n_trades=n, wins=len(wins), losses=len(losses),
        win_rate=(len(wins) / n * 100.0) if n else 0.0,
        total_return_pct=(equity - 1.0) * 100.0,
        max_drawdown_pct=max_dd,
        profit_factor=sum(t.pnl_pct for t in wins) / gross_loss,
        avg_win_pct=(sum(t.pnl_pct for t in wins) / len(wins)) if wins else 0.0,
        avg_loss_pct=(sum(t.pnl_pct for t in losses) / len(losses)) if losses else 0.0,
        stop_pct=stop_pct, target_pct=target_pct,
        label=label, trades=trades,
    )


async def _fetch_candles(symbol: str, timeframe: str, days: int) -> tuple[list, list, list]:
    """Binance'ten OHLCV çek."""
    cpd = _TF_CANDLES_PER_DAY.get(timeframe, 24)
    limit = min(days * cpd + 60, MAX_BINANCE_LIMIT)
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(
            f"{BINANCE_BASE}/api/v3/klines",
            params={"symbol": symbol, "interval": timeframe, "limit": limit},
        )
        r.raise_for_status()
        raw = r.json()
    return (
        [float(k[2]) for k in raw],
        [float(k[3]) for k in raw],
        [float(k[4]) for k in raw],
    )


# ── Genel API ─────────────────────────────────────────────────────────────────

async def run(
    symbol: str,
    timeframe: str = "1h",
    days: int = 30,
    stop_pct: float = 0.025,
    target_pct: float = 0.05,
    slippage_pct: float = 0.001,
) -> BacktestResult:
    """Tek dönem backtest."""
    highs, lows, closes = await _fetch_candles(symbol, timeframe, days)
    return _run_on_candles(highs, lows, closes, symbol, timeframe,
                           stop_pct, target_pct, slippage_pct)


async def walk_forward(
    symbol: str,
    timeframe: str = "1h",
    days: int = 90,
    stop_pct: float = 0.025,
    target_pct: float = 0.05,
    train_ratio: float = 0.70,
) -> tuple[BacktestResult, BacktestResult]:
    """
    Walk-forward analizi: %70 in-sample (eğitim) / %30 out-of-sample (gerçek test).

    In-sample iyi ama out-of-sample kötüyse → strateji overfit edilmiş.
    İkisi birbirine yakınsa → strateji gerçekten çalışıyor.
    """
    highs, lows, closes = await _fetch_candles(symbol, timeframe, days)
    n = len(closes)
    split = int(n * train_ratio)
    # Her bölüm ısınma için yeterli mum içermeli
    if split < WARMUP + 20 or (n - split) < WARMUP + 10:
        raise ValueError(f"Çok az mum ({n}) — daha uzun dönem veya daha küçük TF kullan.")

    is_result = _run_on_candles(
        highs[:split], lows[:split], closes[:split],
        symbol, timeframe, stop_pct, target_pct, 0.001, "In-Sample %70"
    )
    os_result = _run_on_candles(
        highs[split:], lows[split:], closes[split:],
        symbol, timeframe, stop_pct, target_pct, 0.001, "Out-of-Sample %30"
    )
    return is_result, os_result


async def monte_carlo(
    symbol: str,
    timeframe: str = "1h",
    days: int = 30,
    n_simulations: int = 200,
    stop_pct: float = 0.025,
    target_pct: float = 0.05,
) -> tuple[float, float, float, float]:
    """
    Monte Carlo: trade sırasını n kez karıştır, getiri dağılımını hesapla.

    Returns: (median_pct, p5_pct, p95_pct, ruin_probability_pct)
    ruin_probability: kaç simülasyonda %50+ kayıp yaşandı (portföy çöküşü riski)
    """
    base = await run(symbol, timeframe, days, stop_pct, target_pct)
    if base.n_trades < 5:
        r = base.total_return_pct
        return r, r, r, 0.0

    pnls = [t.pnl_pct for t in base.trades]
    sim_returns: list[float] = []
    ruin_count = 0

    for _ in range(n_simulations):
        shuffled = random.sample(pnls, len(pnls))
        equity = 1.0
        min_equity = 1.0
        for pnl in shuffled:
            equity *= 1.0 + pnl / 100.0
            min_equity = min(min_equity, equity)
        total_ret = (equity - 1.0) * 100.0
        sim_returns.append(total_ret)
        if min_equity < 0.5:   # %50 altı = ruin
            ruin_count += 1

    sim_returns.sort()
    n = len(sim_returns)
    ruin_pct = ruin_count / n_simulations * 100

    return (
        round(sim_returns[n // 2], 2),
        round(sim_returns[max(0, int(n * 0.05))], 2),
        round(sim_returns[min(n - 1, int(n * 0.95))], 2),
        round(ruin_pct, 1),
    )


async def multi_symbol_scan(
    symbols: list[str],
    timeframe: str = "1h",
    days: int = 30,
    stop_pct: float = 0.025,
    target_pct: float = 0.05,
) -> list[BacktestResult]:
    """Birden fazla sembolde aynı stratejiyi test et, profit factor'a göre sırala."""
    results: list[BacktestResult] = []
    for sym in symbols:
        try:
            r = await run(sym, timeframe, days, stop_pct, target_pct)
            results.append(r)
        except Exception:
            pass
    results.sort(key=lambda r: r.profit_factor, reverse=True)
    return results
