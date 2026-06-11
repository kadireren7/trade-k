"""Piyasa verisi — iki kaynak, API key gerektirmez:

- Kripto:  Binance public data (websocket + REST)
- Altın, gümüş, petrol, forex, endeksler:  Yahoo Finance (polling)
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

import httpx
import websockets

REST = "https://data-api.binance.vision/api/v3"
WS = "wss://data-stream.binance.vision/stream"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart"
UA = {"User-Agent": "Mozilla/5.0"}

# Kripto kısayolları
CRYPTO_ALIASES = {
    "PAXG": "PAXGUSDT",  # tokenize altın (kripto tarafı)
}

# Kripto dışı enstrümanlar: kullanıcı adı → Yahoo sembolü
YAHOO_ALIASES = {
    "ALTIN": "GC=F", "XAU": "GC=F", "XAUUSD": "GC=F", "GOLD": "GC=F",
    "GUMUS": "SI=F", "GÜMÜŞ": "SI=F", "XAG": "SI=F", "SILVER": "SI=F",
    "PETROL": "CL=F", "OIL": "CL=F", "WTI": "CL=F", "CRUDE": "CL=F",
    "DOGALGAZ": "NG=F", "DOĞALGAZ": "NG=F", "NATGAS": "NG=F", "GAS": "NG=F",
    "BAKIR": "HG=F", "COPPER": "HG=F",
    "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "USDJPY=X",
    "DOLAR": "USDTRY=X", "USDTRY": "USDTRY=X",
    "SP500": "^GSPC", "SPX": "^GSPC",
    "NASDAQ": "NQ=F", "NDX": "NQ=F",
    "DOW": "^DJI", "DJI": "^DJI", "DOWJONES": "^DJI",
    "DAX": "^GDAXI", "DAX40": "^GDAXI",
    "BIST": "XU100.IS", "BIST100": "XU100.IS", "XU100": "XU100.IS",
}

# Yahoo sembolü → ekranda görünen ad (enstrümanların gerçek/uluslararası adları)
DISPLAY = {
    "GC=F": "GOLD (XAU)", "SI=F": "SILVER (XAG)", "CL=F": "WTI CRUDE",
    "NG=F": "NATURAL GAS", "HG=F": "COPPER",
    "EURUSD=X": "EUR/USD", "GBPUSD=X": "GBP/USD", "USDJPY=X": "USD/JPY",
    "USDTRY=X": "USD/TRY", "^GSPC": "S&P 500", "NQ=F": "NASDAQ 100",
    "^DJI": "DOW JONES", "^GDAXI": "DAX 40", "XU100.IS": "BIST 100",
}


def is_yahoo(symbol: str) -> bool:
    return any(c in symbol for c in "=^.")


def resolve_symbol(name: str) -> str:
    name = name.upper().strip().lstrip("/")
    if is_yahoo(name):
        return name
    if name in YAHOO_ALIASES:
        return YAHOO_ALIASES[name]
    if name in CRYPTO_ALIASES:
        return CRYPTO_ALIASES[name]
    if name.endswith("USDT"):
        return name
    return name + "USDT"


def short_name(symbol: str) -> str:
    if symbol in DISPLAY:
        return DISPLAY[symbol]
    base = symbol.removesuffix("USDT")
    return "PAXG (gold)" if base == "PAXG" else base


@dataclass
class Ticker:
    symbol: str
    price: float = 0.0
    change_pct: float = 0.0  # güne/24s'e göre değişim %
    high: float = 0.0
    low: float = 0.0
    prev_price: float = 0.0  # tick yönü için


async def _yahoo_quote(client: httpx.AsyncClient, ysym: str) -> Ticker:
    r = await client.get(f"{YAHOO}/{ysym}", params={"interval": "1m", "range": "1d"},
                         headers=UA)
    r.raise_for_status()
    meta = r.json()["chart"]["result"][0]["meta"]
    price = float(meta["regularMarketPrice"])
    prev = float(meta.get("chartPreviousClose") or meta.get("previousClose") or price)
    return Ticker(
        symbol=ysym,
        price=price,
        change_pct=(price - prev) / prev * 100 if prev else 0.0,
        high=float(meta.get("regularMarketDayHigh") or price),
        low=float(meta.get("regularMarketDayLow") or price),
    )


@dataclass
class MarketFeed:
    """Watchlist için canlı veri: kripto websocket + Yahoo polling."""
    symbols: list[str]
    tickers: dict[str, Ticker] = field(default_factory=dict)
    _ws_task: asyncio.Task | None = None
    _poll_task: asyncio.Task | None = None

    @property
    def crypto_symbols(self) -> list[str]:
        return [s for s in self.symbols if not is_yahoo(s)]

    @property
    def yahoo_symbols(self) -> list[str]:
        return [s for s in self.symbols if is_yahoo(s)]

    async def start(self) -> None:
        await self.prime()
        self._restart_tasks()

    def _restart_tasks(self) -> None:
        for t in (self._ws_task, self._poll_task):
            if t:
                t.cancel()
        self._ws_task = asyncio.create_task(self._ws_loop())
        self._poll_task = asyncio.create_task(self._yahoo_loop())

    async def set_symbols(self, symbols: list[str]) -> None:
        self.symbols = symbols
        self.tickers = {s: t for s, t in self.tickers.items() if s in symbols}
        await self.prime()
        self._restart_tasks()

    async def prime(self) -> None:
        """İlk fiyatları REST ile çek (ilk tick'i beklemeden tablo dolsun)."""
        async with httpx.AsyncClient(timeout=10) as client:
            tasks = []
            if self.crypto_symbols:
                tasks.append(self._prime_crypto(client))
            for ysym in self.yahoo_symbols:
                tasks.append(self._prime_yahoo(client, ysym))
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _prime_crypto(self, client: httpx.AsyncClient) -> None:
        params = {"symbols": json.dumps(self.crypto_symbols, separators=(",", ":"))}
        r = await client.get(f"{REST}/ticker/24hr", params=params)
        r.raise_for_status()
        for t in r.json():
            self.tickers[t["symbol"]] = Ticker(
                symbol=t["symbol"],
                price=float(t["lastPrice"]),
                change_pct=float(t["priceChangePercent"]),
                high=float(t["highPrice"]),
                low=float(t["lowPrice"]),
            )

    async def _prime_yahoo(self, client: httpx.AsyncClient, ysym: str) -> None:
        self.tickers[ysym] = await _yahoo_quote(client, ysym)

    async def _ws_loop(self) -> None:
        syms = self.crypto_symbols
        if not syms:
            return
        streams = "/".join(f"{s.lower()}@miniTicker" for s in syms)
        url = f"{WS}?streams={streams}"
        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    async for raw in ws:
                        d = json.loads(raw).get("data", {})
                        sym = d.get("s")
                        if not sym:
                            continue
                        prev = self.tickers.get(sym)
                        price = float(d["c"])
                        open_ = float(d["o"])
                        self.tickers[sym] = Ticker(
                            symbol=sym,
                            price=price,
                            change_pct=(price - open_) / open_ * 100 if open_ else 0.0,
                            high=float(d["h"]),
                            low=float(d["l"]),
                            prev_price=prev.price if prev else price,
                        )
            except asyncio.CancelledError:
                return
            except Exception:
                await asyncio.sleep(3)  # kopunca yeniden bağlan

    async def _yahoo_loop(self) -> None:
        """Yahoo enstrümanlarını ~5 saniyede bir yenile."""
        if not self.yahoo_symbols:
            return
        while True:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    while True:
                        for ysym in self.yahoo_symbols:
                            prev = self.tickers.get(ysym)
                            t = await _yahoo_quote(client, ysym)
                            t.prev_price = prev.price if prev else t.price
                            self.tickers[ysym] = t
                        await asyncio.sleep(5)
            except asyncio.CancelledError:
                return
            except Exception:
                await asyncio.sleep(8)

    def price(self, symbol: str) -> float | None:
        t = self.tickers.get(symbol)
        return t.price if t and t.price > 0 else None


# ---------- geçmiş veri (Claude analizi için) ----------

# uygulama aralığı → (yahoo interval, yahoo range)
_YAHOO_INTERVALS = {"1m": ("1m", "1d"), "1h": ("60m", "5d"), "4h": ("1d", "3mo")}


async def fetch_klines(symbol: str, interval: str = "1h", limit: int = 48) -> list[dict]:
    """OHLCV mum verisi. Yahoo sembollerinde 4h yerine günlük mum döner."""
    async with httpx.AsyncClient(timeout=15) as client:
        if is_yahoo(symbol):
            yint, yrange = _YAHOO_INTERVALS.get(interval, ("60m", "5d"))
            r = await client.get(f"{YAHOO}/{symbol}",
                                 params={"interval": yint, "range": yrange}, headers=UA)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            ts = res["timestamp"]
            q = res["indicators"]["quote"][0]
            out = []
            for i in range(len(ts)):
                if q["close"][i] is None:
                    continue
                out.append({"t": ts[i] * 1000, "o": q["open"][i], "h": q["high"][i],
                            "l": q["low"][i], "c": q["close"][i], "v": q["volume"][i] or 0})
            return out[-limit:]
        r = await client.get(f"{REST}/klines", params={
            "symbol": symbol, "interval": interval, "limit": limit,
        })
        r.raise_for_status()
        return [
            {"t": k[0], "o": float(k[1]), "h": float(k[2]),
             "l": float(k[3]), "c": float(k[4]), "v": float(k[5])}
            for k in r.json()
        ]


async def quote(symbol: str) -> float:
    """Tek seferlik güncel fiyat (watchlist dışı semboller için)."""
    if is_yahoo(symbol):
        async with httpx.AsyncClient(timeout=10) as client:
            return (await _yahoo_quote(client, symbol)).price
    klines = await fetch_klines(symbol, "1m", 1)
    return klines[-1]["c"]


async def fetch_top_movers(limit: int = 12) -> list[dict]:
    """Kripto taraması: hacimli USDT paritelerinde en çok hareket edenler."""
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{REST}/ticker/24hr")
        r.raise_for_status()
        rows = [
            t for t in r.json()
            if t["symbol"].endswith("USDT")
            and float(t["quoteVolume"]) > 20_000_000
            and not any(x in t["symbol"] for x in ("UP", "DOWN", "BULL", "BEAR"))
        ]
        rows.sort(key=lambda t: abs(float(t["priceChangePercent"])), reverse=True)
        return [
            {"symbol": t["symbol"], "price": float(t["lastPrice"]),
             "change_pct": float(t["priceChangePercent"]),
             "volume_usdt": float(t["quoteVolume"])}
            for t in rows[:limit]
        ]


# Kategori bazlı piyasa listeleri
SCAN_EMTIA = ["GC=F", "SI=F", "CL=F", "NG=F", "HG=F"]
SCAN_FOREX = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDTRY=X"]
SCAN_ENDEKS = ["^GSPC", "NQ=F", "^DJI", "^GDAXI", "XU100.IS"]

# /tara sırasında Claude'a sunulan ve GLOBAL panelde gösterilen kripto dışı evren
SCAN_INSTRUMENTS = SCAN_EMTIA + SCAN_FOREX + SCAN_ENDEKS


def instruments_for_category(category: str) -> list[str]:
    """Kategori adına göre Yahoo sembol listesi döndür."""
    if category == "emtia":
        return SCAN_EMTIA
    if category == "forex":
        return SCAN_FOREX
    if category == "endeks":
        return SCAN_ENDEKS
    return SCAN_INSTRUMENTS  # "global" veya bilinmeyen → hepsi


async def fetch_yahoo_snapshot(instruments: list[str] | None = None) -> list[dict]:
    syms = instruments if instruments is not None else SCAN_INSTRUMENTS
    async with httpx.AsyncClient(timeout=15) as client:
        results = await asyncio.gather(
            *(_yahoo_quote(client, s) for s in syms),
            return_exceptions=True,
        )
    out = []
    for s, t in zip(syms, results):
        if isinstance(t, Ticker):
            out.append({"sembol": s, "ad": DISPLAY.get(s, s), "fiyat": t.price,
                        "gunluk_degisim_pct": round(t.change_pct, 2)})
    return out
