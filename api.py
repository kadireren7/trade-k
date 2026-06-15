"""trade-k Web API — FastAPI backend (tam kontrol).

Terminal uygulamasıyla aynı portföyü, konfigürasyonu paylaşır.
Paper al/sat, ayar değişikliği, otonom kontrol, fiyat alarmı hepsi buradan yapılabilir.

Başlatmak: .venv/bin/uvicorn api:app --host 0.0.0.0 --port 8765 --reload
"""
from __future__ import annotations

import asyncio
import collections
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware

import ai as ai_mod
import config as cfg_mod
import market
import portfolio as portfolio_mod
import indicators
import backtest as backtest_mod
import performance as perf_mod

app = FastAPI(title="trade-k API", version="2.0")

UI_FLAG = Path(__file__).parent / ".ui_update_flag"


# ── Güvenlik başlıkları (CSP) ─────────────────────────────────────────────────
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://unpkg.com; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self' ws: wss:; "
            "img-src 'self' data:;"
        )
        return response

app.add_middleware(SecurityHeadersMiddleware)

# ── AI chat rate limiter ──────────────────────────────────────────────────────
_ai_rate: dict[str, collections.deque] = {}  # ip → timestamps
_AI_RATE_LIMIT = 10   # max 10 istek
_AI_RATE_WINDOW = 60  # 60 saniye içinde

WEB_DIR = Path(__file__).parent / "web"
BINANCE_REST = "https://data-api.binance.vision/api/v3"

# Portfolio işlemleri için process-level lock (dosya yarışını önler)
_portfolio_lock = threading.Lock()


# ── Static & index ────────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

@app.get("/")
async def index():
    return FileResponse(str(WEB_DIR / "index.html"))


# ── Yardımcılar ───────────────────────────────────────────────────────────────

def _load_portfolio() -> portfolio_mod.Portfolio:
    with _portfolio_lock:
        return portfolio_mod.Portfolio.load()

def _get_prices(symbols: list[str]) -> dict[str, float]:
    """Senkron fiyat çek (threading içinden çağrılabilir)."""
    return {}  # async versiyonu aşağıda

async def _prices_async(symbols: list[str]) -> dict[str, float]:
    prices: dict[str, float] = {}
    crypto = [s for s in symbols if not market.is_yahoo(s)]
    if not crypto:
        return prices
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{BINANCE_REST}/ticker/price",
                            params={"symbols": json.dumps(crypto, separators=(",", ":"))})
            r.raise_for_status()
            for t in r.json():
                prices[t["symbol"]] = float(t["price"])
    except Exception:
        pass
    return prices


# ── Portfolio & hesap ─────────────────────────────────────────────────────────

@app.get("/api/portfolio")
async def get_portfolio():
    p = _load_portfolio()
    syms = list(p.positions.keys())
    prices = await _prices_async(syms)
    # Also fetch Yahoo Finance prices for non-crypto symbols
    yahoo_syms = [s for s in syms if market.is_yahoo(s)]
    for sym in yahoo_syms:
        try:
            prices[sym] = await market.quote(sym)
        except Exception:
            pass

    equity = p.equity(prices)
    open_pnl = 0.0
    positions_out = []
    for sym, pos in p.positions.items():
        cur = prices.get(sym, pos.entry)
        pnl = (cur - pos.entry) * pos.qty
        pnl_pct = (cur / pos.entry - 1) * 100 if pos.entry else 0
        open_pnl += pnl
        positions_out.append({
            "symbol": sym,
            "name": market.short_name(sym),
            "qty": pos.qty,
            "entry": pos.entry,
            "current": cur,
            "pnl_usdt": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
            "stop": pos.stop,
            "target": pos.target,
            "trade_style": pos.trade_style,
            "is_leveraged": pos.is_leveraged,
            "leverage": pos.leverage,
            "margin_usdt": pos.margin_usdt,
            "value_usdt": round(cur * pos.qty, 2),
        })

    START_EQUITY = 10_000.0
    total_pnl = equity - START_EQUITY
    total_pct = total_pnl / START_EQUITY * 100

    # Günlük K/Z: autonomous_state'deki daily_start_equity'den hesapla
    daily_pnl = 0.0
    try:
        state_path = Path(__file__).parent / "autonomous_state.json"
        st = json.loads(state_path.read_text()) if state_path.exists() else {}
        dse = st.get("daily_start_equity", 0)
        if dse and dse > 0:
            daily_pnl = equity - dse
    except Exception:
        pass

    return {
        "cash": round(p.cash, 2),
        "equity": round(equity, 2),
        "open_pnl": round(open_pnl, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pct": round(total_pct, 2),
        "daily_pnl": round(daily_pnl, 2),
        "positions": positions_out,
        "n_positions": len(positions_out),
    }


@app.get("/api/history")
async def get_history(limit: int = 100):
    p = _load_portfolio()
    history = list(reversed(p.history[-limit:]))
    return {"history": history}


@app.get("/api/performance")
async def get_performance():
    try:
        p = _load_portfolio()
        stats = perf_mod.trade_stats(p.history)
        # monthly_breakdown returns list[tuple[str, float, int]]
        monthly_raw = perf_mod.monthly_breakdown(p.history)
        monthly = [{"month": m, "pnl": round(pnl, 2), "trades": n}
                   for m, pnl, n in monthly_raw]
        # equity_sparkline returns Rich-markup string — strip tags for web
        spark_raw = perf_mod.equity_sparkline(p.history)
        sparkline = re.sub(r'\[/?[^\]]+\]', '', spark_raw).strip()
        return {
            "n_total": stats.n_total,
            "n_wins": stats.n_wins,
            "n_losses": stats.n_losses,
            "win_rate": stats.win_rate,
            "avg_win_pct": stats.avg_win_pct,
            "avg_loss_pct": stats.avg_loss_pct,
            "profit_factor": stats.profit_factor,
            "expectancy": stats.expectancy,
            "total_pnl": stats.total_pnl,
            "best_pnl": stats.best_pnl,
            "worst_pnl": stats.worst_pnl,
            "sharpe": perf_mod.sharpe_ratio(p.history),
            "sortino": perf_mod.sortino_ratio(p.history),
            "calmar": perf_mod.calmar_ratio(p.history),
            "max_drawdown": perf_mod.max_drawdown(p.history),
            "monthly": monthly,
            "sparkline": sparkline,
        }
    except Exception as e:
        return {"error": str(e), "n_total": 0}


# ── Paper trade emirleri ──────────────────────────────────────────────────────

class BuyRequest(BaseModel):
    symbol: str
    usdt: float
    stop: float | None = None
    target: float | None = None
    style: str = "spot"   # spot | scalp

class SellRequest(BaseModel):
    symbol: str

class AlertRequest(BaseModel):
    symbol: str
    price: float
    action: str = "bildir"   # bildir | al | sat
    amount: float = 0.0

class StopUpdateRequest(BaseModel):
    symbol: str
    stop: float
    target: float | None = None


def _write_ui_flag() -> None:
    """Terminal'e 'portföy değişti' sinyali ver."""
    try:
        UI_FLAG.write_text(str(time.time()))
    except Exception:
        pass


@app.post("/api/trade/buy")
async def paper_buy(req: BuyRequest):
    sym = market.resolve_symbol(req.symbol)
    try:
        price = await market.quote(sym)
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": f"Fiyat alınamadı: {e}"})

    with _portfolio_lock:
        p = portfolio_mod.Portfolio.load()
        if req.usdt > p.cash:
            return JSONResponse(status_code=400,
                                content={"error": f"Yetersiz nakit: {p.cash:.2f} USDT"})
        if sym in p.positions:
            return JSONResponse(status_code=400,
                                content={"error": f"{sym} zaten açık pozisyonda"})

        slip = price * 1.001  # %0.1 slippage
        stop = req.stop or slip * 0.95
        target = req.target or slip * 1.10

        if req.style == "scalp":
            p.buy(sym, req.usdt, slip, trade_style="scalp", stop=stop, target=target)
        else:
            p.buy(sym, req.usdt, slip, stop=stop, target=target)
            p.set_protection(sym, stop, target)
        p.save()

    pos = p.positions.get(sym)
    _write_ui_flag()
    return {
        "ok": True,
        "symbol": sym,
        "fill_price": round(slip, 6),
        "qty": round(pos.qty, 6) if pos else 0,
        "usdt": req.usdt,
        "stop": round(stop, 6),
        "target": round(target, 6),
    }


@app.post("/api/trade/sell")
async def paper_sell(req: SellRequest):
    sym = market.resolve_symbol(req.symbol)
    with _portfolio_lock:
        p = portfolio_mod.Portfolio.load()
        if sym not in p.positions:
            return JSONResponse(status_code=404,
                                content={"error": f"{sym} pozisyonda değil"})
        try:
            price = await market.quote(sym)
        except Exception:
            price = p.positions[sym].entry

        slip = price * 0.999
        result = p.sell(sym, slip)
        p.save()

    _write_ui_flag()
    return {"ok": True, "symbol": sym, "fill_price": round(slip, 6), "result": result}


@app.post("/api/trade/protection")
async def set_protection(req: StopUpdateRequest):
    sym = market.resolve_symbol(req.symbol)
    with _portfolio_lock:
        p = portfolio_mod.Portfolio.load()
        if sym not in p.positions:
            return JSONResponse(status_code=404, content={"error": f"{sym} pozisyonda değil"})
        p.set_protection(sym, req.stop, req.target)
        p.save()
    return {"ok": True, "symbol": sym, "stop": req.stop, "target": req.target}


# ── Fiyat alarmları ───────────────────────────────────────────────────────────

_alerts: list[dict] = []   # [{"symbol","price","action","amount","created"}]

@app.get("/api/alerts")
async def get_alerts():
    return {"alerts": _alerts}

@app.post("/api/alerts")
async def add_alert(req: AlertRequest):
    sym = market.resolve_symbol(req.symbol)
    alert = {
        "id": int(time.time() * 1000),
        "symbol": sym,
        "price": req.price,
        "action": req.action,
        "amount": req.amount,
        "created": time.strftime("%H:%M:%S"),
        "triggered": False,
    }
    _alerts.append(alert)
    return {"ok": True, "alert": alert}

@app.delete("/api/alerts/{alert_id}")
async def delete_alert(alert_id: int):
    global _alerts
    _alerts = [a for a in _alerts if a["id"] != alert_id]
    return {"ok": True}


# ── Konfigürasyon ─────────────────────────────────────────────────────────────

@app.get("/api/config")
async def get_config():
    try:
        c = cfg_mod.Config.load()
        return {
            "trading_mode": c.trading_mode,
            "exchange": c.exchange,
            "ai_provider": c.ai_provider,
            "model": c.model,
            "autonomous_mode": c.autonomous_mode,
            "active_strategy": c.active_strategy,
            "leverage_enabled": c.leverage_enabled,
            "scalp_enabled": c.scalp_enabled,
            "theme": c.theme,
            "language": c.language,
            "openai_model": c.openai_model,
            "gemini_model": c.gemini_model,
            "ollama_model": c.ollama_model,
            "grok_model": c.grok_model,
            # API key varlık kontrolü (key değil)
            "binance_connected": bool(c.binance_key),
            "bybit_connected": bool(getattr(c, "bybit_key", "")),
            "okx_connected": bool(getattr(c, "okx_key", "")),
            "openai_key_set": bool(c.openai_api_key),
            "gemini_key_set": bool(c.gemini_api_key),
            "grok_key_set": bool(c.grok_api_key),
        }
    except Exception as e:
        return {"error": str(e)}


class ConfigUpdate(BaseModel):
    key: str
    value: Any

@app.put("/api/config")
async def update_config(update: ConfigUpdate):
    """Güvenli config güncellemesi — hassas alanlar hariç."""
    ALLOWED = {
        "trading_mode", "exchange", "ai_provider", "model",
        "autonomous_mode", "active_strategy", "leverage_enabled",
        "scalp_enabled", "theme", "language",
        "openai_model", "gemini_model", "ollama_model", "grok_model",
    }
    if update.key not in ALLOWED:
        return JSONResponse(status_code=400,
                            content={"error": f"'{update.key}' değiştirilemez"})
    try:
        c = cfg_mod.Config.load()
        setattr(c, update.key, update.value)
        c.save()
        cfg_mod.set_current(c)
        return {"ok": True, "key": update.key, "value": update.value}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


class ApiKeyRequest(BaseModel):
    exchange: str   # binance | bybit | okx
    api_key: str
    api_secret: str
    passphrase: str = ""   # OKX için


class AiKeyRequest(BaseModel):
    provider: str   # openai | gemini | grok
    api_key: str


@app.post("/api/config/exchange-key")
async def save_exchange_key(req: ApiKeyRequest):
    if req.exchange not in ("binance", "bybit", "okx"):
        return JSONResponse(status_code=400, content={"error": "Geçersiz borsa"})
    try:
        c = cfg_mod.Config.load()
        if req.exchange == "binance":
            c.binance_key = req.api_key
            c.binance_secret = req.api_secret
        elif req.exchange == "bybit":
            c.bybit_key = req.api_key
            c.bybit_secret = req.api_secret
        elif req.exchange == "okx":
            c.okx_key = req.api_key
            c.okx_secret = req.api_secret
            c.okx_passphrase = req.passphrase
        c.exchange = req.exchange
        c.save()
        return {"ok": True, "exchange": req.exchange}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/config/ai-key")
async def save_ai_key(req: AiKeyRequest):
    if req.provider not in ("openai", "gemini", "grok"):
        return JSONResponse(status_code=400, content={"error": "Geçersiz AI sağlayıcı"})
    try:
        c = cfg_mod.Config.load()
        if req.provider == "openai":
            c.openai_api_key = req.api_key
        elif req.provider == "gemini":
            c.gemini_api_key = req.api_key
        elif req.provider == "grok":
            c.grok_api_key = req.api_key
        c.save()
        return {"ok": True, "provider": req.provider}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.delete("/api/config/exchange-key/{exchange}")
async def remove_exchange_key(exchange: str):
    try:
        c = cfg_mod.Config.load()
        if exchange == "binance":
            c.binance_key = ""; c.binance_secret = ""
        elif exchange == "bybit":
            c.bybit_key = ""; c.bybit_secret = ""
        elif exchange == "okx":
            c.okx_key = ""; c.okx_secret = ""; c.okx_passphrase = ""
        c.save()
        return {"ok": True}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ── Otonom mod ────────────────────────────────────────────────────────────────

@app.get("/api/autonomous/status")
async def autonomous_status():
    state_path = Path(__file__).parent / "autonomous_state.json"
    try:
        st = json.loads(state_path.read_text())
        c = cfg_mod.Config.load()
        return {
            "enabled": st.get("enabled", False),
            "daily_trades": st.get("daily_trades", 0),
            "consecutive_losses": st.get("consecutive_losses", 0),
            "risk_locked": st.get("risk_locked", False),
            "cooldown_until": st.get("cooldown_until", 0),
            "daily_start_equity": st.get("daily_start_equity", 0),
            "mode": c.autonomous_mode,
            "trade_plan": getattr(c, "trade_plan", "dengeli"),
            "scalp_enabled": getattr(c, "scalp_enabled", False),
            "leverage_enabled": getattr(c, "leverage_enabled", False),
        }
    except Exception:
        return {"enabled": False, "daily_trades": 0, "risk_locked": False}


@app.post("/api/autonomous/mode")
async def set_autonomous_mode(body: dict):
    mode = body.get("mode", "dengeli")
    state_path = Path(__file__).parent / "autonomous_state.json"

    if mode == "kapat":
        try:
            st = json.loads(state_path.read_text()) if state_path.exists() else {}
            st["enabled"] = False
            state_path.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        except Exception:
            pass
        return {"ok": True, "mode": "kapat", "enabled": False}

    # trade_plan modu: long / dengeli / scalp / kaldirac / tam
    _TRADE_PLAN_MAP = {
        "long":     {"trade_plan": "sadece_long", "scalp_enabled": False, "leverage_enabled": False},
        "dengeli":  {"trade_plan": "dengeli",     "scalp_enabled": False, "leverage_enabled": False},
        "scalp":    {"trade_plan": "sadece_long", "scalp_enabled": True,  "leverage_enabled": False},
        "kaldirac": {"trade_plan": "dengeli",     "scalp_enabled": False, "leverage_enabled": True},
        "tam":      {"trade_plan": "tam",         "scalp_enabled": True,  "leverage_enabled": True},
    }
    if mode in _TRADE_PLAN_MAP:
        opts = _TRADE_PLAN_MAP[mode]
        c = cfg_mod.Config.load()
        c.trade_plan = opts["trade_plan"]
        c.scalp_enabled = opts["scalp_enabled"]
        c.leverage_enabled = opts["leverage_enabled"]
        c.save()
        cfg_mod.set_current(c)
        try:
            st = json.loads(state_path.read_text()) if state_path.exists() else {}
            st["enabled"] = True
            st["trade_plan"] = mode
            state_path.write_text(json.dumps(st, ensure_ascii=False, indent=2))
        except Exception:
            pass
        return {"ok": True, "trade_plan": mode, "enabled": True}

    # risk profili: guvenli / dengeli / agresif
    if mode not in ("guvenli", "dengeli", "agresif"):
        return JSONResponse(status_code=400, content={
            "error": "Geçersiz mod: long | dengeli | scalp | kaldirac | tam | guvenli | agresif | kapat"
        })

    c = cfg_mod.Config.load()
    c.autonomous_mode = mode
    c.save()
    cfg_mod.set_current(c)

    try:
        st = json.loads(state_path.read_text()) if state_path.exists() else {}
        st["enabled"] = True
        st["mode"] = mode
        state_path.write_text(json.dumps(st, ensure_ascii=False, indent=2))
    except Exception:
        pass

    return {"ok": True, "mode": mode, "enabled": True}


@app.get("/api/connections")
async def get_connections():
    """Bağlantı durumları: Binance WS, API key, AI provider."""
    c = cfg_mod.Config.load()
    # WS durumunu state dosyasından oku (app.py MarketFeed yazar)
    state_path = Path(__file__).parent / "autonomous_state.json"
    ws_ok = False
    try:
        st = json.loads(state_path.read_text()) if state_path.exists() else {}
        ws_ok = st.get("ws_connected", False)
    except Exception:
        pass
    api_key_set = bool(getattr(c, "binance_key", ""))
    ai_key_set = bool(getattr(c, "claude_key", "") or getattr(c, "openai_key", ""))
    return {
        "binance_ws": ws_ok,
        "binance_api_key": api_key_set,
        "ai_provider": getattr(c, "ai_provider", "claude"),
        "ai_key_set": ai_key_set,
        "trading_mode": getattr(c, "trading_mode", "paper"),
        "trade_plan": getattr(c, "trade_plan", "dengeli"),
        "scalp_enabled": getattr(c, "scalp_enabled", False),
        "leverage_enabled": getattr(c, "leverage_enabled", False),
    }


# ── Piyasa verisi ─────────────────────────────────────────────────────────────

@app.get("/api/prices")
async def get_prices_batch(symbols: str = ""):
    """Watchlist sembolleri için toplu fiyat + 24s değişim (Binance)."""
    syms = [s.strip().upper() for s in symbols.split(",")
            if s.strip() and not market.is_yahoo(s.strip())]
    if not syms:
        return {"prices": {}, "changes": {}}
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{BINANCE_REST}/ticker/24hr",
                            params={"symbols": json.dumps(syms, separators=(",", ":"))})
            r.raise_for_status()
            prices: dict[str, float] = {}
            changes: dict[str, float] = {}
            for t in r.json():
                prices[t["symbol"]] = float(t["lastPrice"])
                changes[t["symbol"]] = float(t["priceChangePercent"])
            return {"prices": prices, "changes": changes}
    except Exception as e:
        return {"prices": {}, "changes": {}, "error": str(e)}


@app.get("/api/price/{symbol}")
async def get_price(symbol: str):
    sym = market.resolve_symbol(symbol)
    try:
        price = await market.quote(sym)
        return {"symbol": sym, "price": price}
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@app.get("/api/klines/{symbol}")
async def get_klines(symbol: str, interval: str = "1h", limit: int = 300):
    sym = market.resolve_symbol(symbol)
    if interval not in ("1m","3m","5m","15m","30m","1h","2h","4h","6h","12h","1d"):
        return JSONResponse(status_code=400, content={"error": "Geçersiz interval"})
    try:
        klines = await market.fetch_klines(sym, interval, limit)
        return {"symbol": sym, "interval": interval, "klines": klines}
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@app.get("/api/spread/{symbol}")
async def get_spread(symbol: str):
    sym = market.resolve_symbol(symbol)
    if market.is_yahoo(sym):
        return JSONResponse(status_code=400, content={"error": "Spread sadece kripto için"})
    try:
        bid, ask, spread_pct = await market.get_spread(sym)
        return {"symbol": sym, "bid": bid, "ask": ask, "spread_pct": spread_pct}
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@app.get("/api/ta/{symbol}")
async def get_ta(symbol: str, timeframe: str = "1h"):
    sym = market.resolve_symbol(symbol)
    if timeframe not in indicators.TIMEFRAMES:
        return JSONResponse(status_code=400, content={"error": "Geçersiz timeframe"})
    try:
        r = await indicators.analyze(sym, timeframe)
        return {
            "symbol": r.symbol, "timeframe": r.timeframe, "price": r.price,
            "signal": r.signal, "score": r.score,
            "rsi": r.rsi, "macd": r.macd, "macd_signal": r.macd_signal,
            "macd_hist": r.macd_hist, "bb_upper": r.bb_upper, "bb_mid": r.bb_mid,
            "bb_lower": r.bb_lower, "bb_pct": r.bb_pct,
            "ema20": r.ema20, "ema50": r.ema50, "atr": r.atr,
            "vol_ratio": r.vol_ratio, "adx": r.adx,
            "support": r.support, "resistance": r.resistance, "reasons": r.reasons,
        }
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@app.get("/api/movers")
async def get_movers():
    try:
        return {"movers": await market.fetch_top_movers(limit=20)}
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


@app.get("/api/backtest/{symbol}")
async def run_backtest(symbol: str, timeframe: str = "1h", days: int = 30,
                       stop_pct: float = 2.5, target_pct: float = 5.0):
    sym = market.resolve_symbol(symbol)
    try:
        r = await backtest_mod.run(sym, timeframe, int(days),
                                   stop_pct / 100, target_pct / 100)
        sig = backtest_mod.significance(r.wins, r.n_trades)
        # Kümülatif özkaynak eğrisi (100 = başlangıç)
        equity_curve = [100.0]
        for t in r.trades:
            equity_curve.append(round(equity_curve[-1] * (1 + t.pnl_pct / 100), 4))
        return {
            "symbol": r.symbol, "timeframe": r.timeframe,
            "n_candles": r.n_candles, "n_trades": r.n_trades,
            "wins": r.wins, "losses": r.losses, "win_rate": r.win_rate,
            "total_return_pct": r.total_return_pct,
            "max_drawdown_pct": r.max_drawdown_pct,
            "profit_factor": r.profit_factor,
            "avg_win_pct": r.avg_win_pct, "avg_loss_pct": r.avg_loss_pct,
            "p_value": sig.p_value, "significant": sig.significant,
            "equity_curve": equity_curve,
        }
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


# ── Otonom log ────────────────────────────────────────────────────────────────

@app.get("/api/log")
async def get_log(limit: int = 200):
    log_path = Path(__file__).parent / "autonomous_log.jsonl"
    entries = []
    if log_path.exists():
        lines = log_path.read_text().strip().splitlines()
        for line in reversed(lines[-limit:]):
            try:
                raw = json.loads(line)
                # Normalize to web-friendly format
                # autonomous_log fields: time (ISO), action, symbol, decision, reason, confidence
                ts = 0.0
                if raw.get("time"):
                    try:
                        ts = time.mktime(time.strptime(raw["time"], "%Y-%m-%dT%H:%M:%S"))
                    except Exception:
                        pass
                entries.append({
                    "ts": ts,
                    "type": raw.get("action", raw.get("type", "—")),
                    "symbol": raw.get("symbol", ""),
                    "reason": raw.get("reason", raw.get("decision", "")),
                    "confidence": raw.get("confidence", 0),
                })
            except Exception:
                pass
    return {"log": entries}


# ── AI Sohbet ─────────────────────────────────────────────────────────────────

_AI_CHAT_SYSTEM = f"""{ai_mod.PERSONA}

Kullanıcı sana trading soruları soruyor veya piyasa hakkında konuşmak istiyor.
Kısa, net ve Türkçe yanıt ver. Eğer işlem önerisi yapıyorsan, son satırda şu formatı kullan:
ONERI: {{"islem":"AL"|"SAT"|"BEKLE","sembol":"...","tutar_usdt":500,"basari_yuzdesi":65,"zarar_kes":0,"kar_al":0,"gerekce":"..."}}
Yoksa JSON satırı yazma.
{ai_mod.SLTP_RULES}"""


@app.post("/api/ai/chat")
async def ai_chat(request: Request, body: dict):
    # Rate limit: IP başına dakikada 10 istek
    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    q = _ai_rate.setdefault(client_ip, collections.deque())
    while q and now - q[0] > _AI_RATE_WINDOW:
        q.popleft()
    if len(q) >= _AI_RATE_LIMIT:
        return JSONResponse(status_code=429,
                            content={"error": f"Dakikada en fazla {_AI_RATE_LIMIT} mesaj gönderilebilir"})
    q.append(now)

    message = body.get("message", "").strip()
    symbol = body.get("symbol", "BTCUSDT")
    if not message:
        return JSONResponse(status_code=400, content={"error": "Mesaj boş"})
    try:
        p = _load_portfolio()
        price = 0.0
        try:
            sym = market.resolve_symbol(symbol)
            price = await market.quote(sym)
        except Exception:
            pass

        context = (
            f"Kullanıcının incelediği sembol: {symbol}, anlık fiyat: {price:.4f} USDT\n"
            f"Portföy: {p.cash:.2f} USDT nakit, açık pozisyonlar: {list(p.positions.keys()) or 'yok'}\n\n"
            f"Kullanıcı mesajı: {message}"
        )
        raw = await ai_mod._ask(context, _AI_CHAT_SYSTEM)
        suggestions = ai_mod.parse_suggestions(raw)
        clean = ai_mod.strip_machine_lines(raw)
        return {
            "ok": True,
            "text": clean,
            "suggestions": [
                {
                    "islem": s.islem,
                    "sembol": s.sembol,
                    "tutar_usdt": s.tutar_usdt,
                    "basari_yuzdesi": s.basari_yuzdesi,
                    "zarar_kes": s.zarar_kes,
                    "kar_al": s.kar_al,
                    "gerekce": s.gerekce,
                    "risk_reward": s.risk_reward,
                }
                for s in suggestions
            ],
        }
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": str(e)})


# ── WebSocket: gerçek zamanlı fiyat akışı ────────────────────────────────────

class _Broadcaster:
    def __init__(self):
        self._clients: set[WebSocket] = set()
        self._symbols: set[str] = set()
        self._task: asyncio.Task | None = None

    def add(self, ws: WebSocket) -> None:
        self._clients.add(ws)

    def remove(self, ws: WebSocket) -> None:
        self._clients.discard(ws)

    def subscribe(self, syms: list[str]) -> None:
        self._symbols.update(syms)
        if not self._task or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        _yahoo_prices: dict[str, float] = {}
        _yahoo_changes: dict[str, float] = {}
        _yahoo_last_poll: float = 0.0

        while True:
            await asyncio.sleep(2)
            if not self._clients or not self._symbols:
                continue

            crypto_syms = [s for s in self._symbols if not market.is_yahoo(s)]
            yahoo_syms  = [s for s in self._symbols if market.is_yahoo(s)]

            prices: dict[str, float] = {}
            changes: dict[str, float] = {}

            # Kripto: her 2 saniyede Binance'ten çek
            if crypto_syms:
                try:
                    async with httpx.AsyncClient(timeout=5) as c:
                        r = await c.get(f"{BINANCE_REST}/ticker/price",
                                        params={"symbols": json.dumps(crypto_syms, separators=(",",":"))})
                        r.raise_for_status()
                        for t in r.json():
                            prices[t["symbol"]] = float(t["price"])
                        r2 = await c.get(f"{BINANCE_REST}/ticker/24hr",
                                         params={"symbols": json.dumps(crypto_syms[:20], separators=(",",":"))})
                        if r2.is_success:
                            for t in r2.json():
                                changes[t["symbol"]] = float(t["priceChangePercent"])
                except Exception:
                    pass

            # Yahoo Finance: her 30 saniyede bir güncelle
            now = time.time()
            if yahoo_syms and (now - _yahoo_last_poll) > 30:
                _yahoo_last_poll = now
                try:
                    async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "Mozilla/5.0"}) as yc:
                        for ysym in yahoo_syms:
                            try:
                                r = await yc.get(
                                    f"https://query1.finance.yahoo.com/v8/finance/chart/{ysym}",
                                    params={"interval": "1m", "range": "1d"},
                                )
                                if r.is_success:
                                    meta = r.json()["chart"]["result"][0]["meta"]
                                    p = float(meta["regularMarketPrice"])
                                    prev = float(meta.get("chartPreviousClose") or meta.get("previousClose") or p)
                                    _yahoo_prices[ysym] = p
                                    _yahoo_changes[ysym] = (p - prev) / prev * 100 if prev else 0.0
                            except Exception:
                                pass
                except Exception:
                    pass

            # Yahoo fiyatlarını ekle (önbellekten)
            prices.update(_yahoo_prices)
            changes.update(_yahoo_changes)

            if not prices:
                continue

            msg = json.dumps({
                "type": "prices", "prices": prices,
                "changes": changes, "ts": time.time()
            })
            dead = set()
            for ws in list(self._clients):
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.add(ws)
            self._clients -= dead

    async def broadcast(self, msg: dict) -> None:
        text = json.dumps(msg)
        dead = set()
        for ws in list(self._clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.add(ws)
        self._clients -= dead


_bc = _Broadcaster()


@app.websocket("/ws/prices")
async def ws_prices(ws: WebSocket):
    await ws.accept()
    _bc.add(ws)
    try:
        while True:
            try:
                data = await asyncio.wait_for(ws.receive_text(), timeout=30)
                msg = json.loads(data)
                if msg.get("type") == "subscribe":
                    syms = [market.resolve_symbol(s) for s in msg.get("symbols", [])]
                    _bc.subscribe(syms)
                    await ws.send_text(json.dumps({"type": "subscribed", "symbols": syms}))
            except asyncio.TimeoutError:
                await ws.send_text(json.dumps({"type": "ping"}))
    except (WebSocketDisconnect, Exception):
        _bc.remove(ws)
