"""Piyasa verisi — iki kaynak, API key gerektirmez:

- Kripto:  Binance public data (websocket + REST)
- Altın, gümüş, petrol, forex, endeksler:  Yahoo Finance (polling)
"""
from __future__ import annotations

import asyncio
import json
import time
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


# ── Veri kalitesi ve kaldıraç izin tablosu ────────────────────────────────────
_LEVERAGE_DATA: dict[str, tuple[str, bool, str]] = {
    "GC=F":      ("near_realtime", False,
                  "goldprice.org ~dakikalık güncelleme — tick-by-tick değil"),
    "SI=F":      ("near_realtime", False,
                  "goldprice.org ~dakikalık güncelleme — tick-by-tick değil"),
    "CL=F":      ("delayed",       False,
                  "Yahoo Finance ~15dk gecikmeli — kaldıraç stop hesabı güvensiz"),
    "NG=F":      ("delayed",       False,
                  "Yahoo Finance ~15dk gecikmeli — kaldıraç stop hesabı güvensiz"),
    "HG=F":      ("delayed",       False,
                  "Yahoo Finance ~15dk gecikmeli — kaldıraç stop hesabı güvensiz"),
    "EURUSD=X":  ("delayed",       False,
                  "Yahoo Finance forex gecikmeli — kaldıraç için anlık veri şart"),
    "GBPUSD=X":  ("delayed",       False,
                  "Yahoo Finance forex gecikmeli — kaldıraç için anlık veri şart"),
    "USDJPY=X":  ("delayed",       False,
                  "Yahoo Finance forex gecikmeli — kaldıraç için anlık veri şart"),
    "USDTRY=X":  ("delayed",       False,
                  "Yahoo Finance forex gecikmeli — kaldıraç için anlık veri şart"),
    "^GSPC":     ("delayed",       False,
                  "Yahoo Finance endeks gecikmeli — kaldıraç için anlık veri şart"),
    "NQ=F":      ("delayed",       False,
                  "Yahoo Finance endeks gecikmeli — kaldıraç için anlık veri şart"),
    "^DJI":      ("delayed",       False,
                  "Yahoo Finance endeks gecikmeli — kaldıraç için anlık veri şart"),
    "^GDAXI":    ("delayed",       False,
                  "Yahoo Finance endeks gecikmeli — kaldıraç için anlık veri şart"),
    "XU100.IS":  ("delayed",       False,
                  "BIST verisi Yahoo üzerinden gecikmeli/belirsiz"),
}

_QUALITY_LABELS: dict[str, str] = {
    "realtime":      "Anlık (Binance WebSocket)",
    "near_realtime": "Yakın-anlık (~1dk güncelleme)",
    "delayed":       "Gecikmeli (~15dk, Yahoo Finance)",
    "unknown":       "Bilinmiyor",
}


def data_quality(symbol: str) -> str:
    """Sembolün veri kalite seviyesini döndür."""
    if not is_yahoo(symbol):
        return "realtime"
    return _LEVERAGE_DATA.get(symbol, ("unknown", False, ""))[0]


def leverage_allowed(symbol: str) -> bool:
    """Sembolün kaldıraçlı paper işlem için uygun olup olmadığını döndür."""
    if not is_yahoo(symbol):
        return True
    return _LEVERAGE_DATA.get(symbol, ("unknown", False, ""))[1]


def leverage_reason(symbol: str) -> str:
    """Kaldıraç izninin gerekçesini döndür."""
    if not is_yahoo(symbol):
        return "Binance WebSocket anlık veri — kaldıraçlı paper işlem için uygun"
    info = _LEVERAGE_DATA.get(symbol)
    if info:
        izin = "izinli" if info[1] else "izinsiz"
        return f"{info[2]} ({izin})"
    return "Bilinmeyen kaynak — kaldıraç izinsiz (güvenli varsayılan)"


def data_quality_label(symbol: str) -> str:
    """Okunabilir veri kalite etiketi döndür."""
    return _QUALITY_LABELS.get(data_quality(symbol), "Bilinmiyor")


def leverage_eligible_symbols(watchlist: list[str]) -> list[str]:
    """Watchlist'ten sadece kaldıraçlı paper işleme uygun sembolleri filtrele."""
    return [s for s in watchlist if leverage_allowed(s)]


def trade_allowed(symbol: str) -> tuple[bool, str]:
    """Returns (allowed, reason). Blocks scalp/short on delayed data."""
    q = data_quality(symbol)
    if q in ("realtime", "near_realtime"):
        return True, ""
    if q == "delayed":
        return False, f"{short_name(symbol)} veri gecikmeli (~15dk, Yahoo Finance) — scalp/short için anlık veri şart"
    return False, f"{short_name(symbol)} veri kalitesi bilinmiyor — işlem için güvenli değil"


def is_yahoo(symbol: str) -> bool:
    return any(c in symbol for c in "=^.")


def is_crypto(symbol: str) -> bool:
    return not is_yahoo(symbol)


def resolve_symbol(name: str) -> str:
    name = name.upper().strip().lstrip("/")
    _COMMON_NAMES = {
        "BITCOIN": "BTCUSDT", "BTC": "BTCUSDT",
        "ETHEREUM": "ETHUSDT", "ETH": "ETHUSDT",
        "SOLANA": "SOLUSDT", "SOL": "SOLUSDT",
        "DOGECOIN": "DOGEUSDT", "DOGE": "DOGEUSDT",
        "RIPPLE": "XRPUSDT", "XRP": "XRPUSDT",
        "CARDANO": "ADAUSDT", "ADA": "ADAUSDT",
        "AVALANCHE": "AVAXUSDT", "AVAX": "AVAXUSDT",
        "CHAINLINK": "LINKUSDT", "LINK": "LINKUSDT",
        "POLKADOT": "DOTUSDT", "DOT": "DOTUSDT",
        "MATIC": "MATICUSDT", "POLYGON": "MATICUSDT",
        "UNI": "UNIUSDT", "UNISWAP": "UNIUSDT",
        "LITECOIN": "LTCUSDT", "LTC": "LTCUSDT",
        "NEAR": "NEARUSDT",
        "APT": "APTUSDT", "APTOS": "APTUSDT",
        "SUI": "SUIUSDT",
        "INJ": "INJUSDT", "INJECTIVE": "INJUSDT",
        "TRX": "TRXUSDT", "TRON": "TRXUSDT",
    }
    if name in _COMMON_NAMES:
        return _COMMON_NAMES[name]
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
    last_updated: float = 0.0  # unix timestamp, fiyat yaşı için


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
        last_updated=time.time(),
    )


@dataclass
class MarketFeed:
    """Watchlist için canlı veri: kripto websocket + Yahoo polling."""
    symbols: list[str]
    tickers: dict[str, Ticker] = field(default_factory=dict)
    ws_connected: bool = False
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
                last_updated=time.time(),
            )

    async def _prime_yahoo(self, client: httpx.AsyncClient, ysym: str) -> None:
        self.tickers[ysym] = await _yahoo_quote(client, ysym)

    def is_stale(self, symbol: str, max_age: float = 30.0) -> bool:
        """Sembolün fiyat verisinin eski olup olmadığını kontrol et."""
        t = self.tickers.get(symbol)
        if not t or t.last_updated == 0:
            return True
        return time.time() - t.last_updated > max_age

    async def _ws_loop(self) -> None:
        syms = self.crypto_symbols
        if not syms:
            return
        streams = "/".join(f"{s.lower()}@miniTicker" for s in syms)
        url = f"{WS}?streams={streams}"
        backoff = 2
        while True:
            try:
                async with websockets.connect(url, ping_interval=20) as ws:
                    self.ws_connected = True
                    backoff = 2  # başarılı bağlantıda sıfırla
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
                            last_updated=time.time(),
                        )
            except asyncio.CancelledError:
                return
            except Exception:
                self.ws_connected = False
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

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


async def get_spread(symbol: str) -> tuple[float, float, float]:
    """Binance order book'tan bid/ask ve spread yüzdesi çek.

    Returns: (bid, ask, spread_pct)
    Sadece Binance kriptolar için kullanılabilir.
    """
    async with httpx.AsyncClient(timeout=8) as c:
        r = await c.get(f"{REST}/ticker/bookTicker", params={"symbol": symbol})
        r.raise_for_status()
        d = r.json()
        bid = float(d["bidPrice"])
        ask = float(d["askPrice"])
        spread_pct = (ask - bid) / bid * 100 if bid > 0 else 0.0
        return bid, ask, round(spread_pct, 4)


async def quote(symbol: str) -> float:
    """Tek seferlik güncel fiyat (watchlist dışı semboller için)."""
    if is_yahoo(symbol):
        async with httpx.AsyncClient(timeout=10) as client:
            return (await _yahoo_quote(client, symbol)).price
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(f"{REST}/ticker/bookTicker", params={"symbol": symbol})
        r.raise_for_status()
        d = r.json()
        bid = float(d["bidPrice"])
        ask = float(d["askPrice"])
        return (bid + ask) / 2


_top_movers_cache: tuple[float, list[dict]] = (0.0, [])
_TOP_MOVERS_TTL = 300  # 5 dakika


async def fetch_top_movers(limit: int = 12) -> list[dict]:
    """Kripto taraması: hacimli USDT paritelerinde en çok hareket edenler (5dk cache)."""
    global _top_movers_cache
    ts, cached = _top_movers_cache
    if cached and time.time() - ts < _TOP_MOVERS_TTL:
        return cached[:limit]
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
        result = [
            {"symbol": t["symbol"], "price": float(t["lastPrice"]),
             "change_pct": float(t["priceChangePercent"]),
             "volume_usdt": float(t["quoteVolume"])}
            for t in rows[:50]
        ]
    _top_movers_cache = (time.time(), result)
    return result[:limit]


# Kategori bazlı piyasa listeleri
SCAN_EMTIA = ["GC=F", "SI=F", "CL=F", "NG=F", "HG=F"]
SCAN_FOREX = ["EURUSD=X", "GBPUSD=X", "USDJPY=X", "USDTRY=X"]
SCAN_ENDEKS = ["^GSPC", "NQ=F", "^DJI", "^GDAXI", "XU100.IS"]

# /tara sırasında Claude'a sunulan ve GLOBAL panelde gösterilen kripto dışı evren
SCAN_INSTRUMENTS = SCAN_EMTIA + SCAN_FOREX + SCAN_ENDEKS

# Otonom mod kripto evreni — çeşitlendirilmiş, likit Binance çiftleri
AUTONOMOUS_CRYPTO_UNIVERSE = [
    # Mega cap
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT",
    # Large cap
    "AVAXUSDT", "DOGEUSDT", "LINKUSDT", "DOTUSDT", "MATICUSDT",
    "ADAUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT", "NEARUSDT",
    "TRXUSDT", "ICPUSDT", "APTUSDT", "XLMUSDT", "ETCUSDT",
    "FILUSDT", "HBARUSDT", "LDOUSDT", "QNTUSDT", "CROUSDT",
    # Mid cap momentum
    "SUIUSDT", "ARBUSDT", "OPUSDT", "INJUSDT", "TIAUSDT",
    "SEIUSDT", "WIFUSDT", "FETUSDT", "RENDERUSDT", "JUPUSDT",
    "BONKUSDT", "MEMEUSDT", "PEPEUSDT", "FLOKIUSDT", "SHIBUSDT",
    "WLDUSDT", "STRKUSDT", "PYTHUSDT", "ALTUSDT", "DYMUSDT",
    "ONDOUSDT", "EIGENUSDT", "MOVEUSDT", "ZROUSDT", "KAIAUSDT",
    # DeFi
    "AAVEUSDT", "MKRUSDT", "SNXUSDT", "CRVUSDT", "COMPUSDT",
    "YFIUSDT", "1INCHUSDT", "RUNEUSDT", "DYDXUSDT", "GMXUSDT",
    "PENDLEUSDT", "ENAUSDT", "ETHFIUSDT", "REZUSDT", "EZUSDT",
    # Layer 1 / Layer 2
    "FTMUSDT", "ALGOUSDT", "EGLDUSDT", "XTZUSDT", "FLOWUSDT",
    "KASUSDT", "MINAUSDT", "KAVAUSDT", "IOTAUSDT",
    "ZILUSDT", "ONTUSDT", "VETUSDT", "NEOUSDT", "WAVESUSDT",
    "BTTCUSDT", "STXUSDT", "CFXUSDT", "COREUSDT", "BEAMUSDT",
    # Gaming / NFT / Metaverse
    "SANDUSDT", "MANAUSDT", "AXSUSDT", "GALAUSDT", "ILVUSDT",
    "YGGUSDT", "PIXELUSDT", "RONUSDT", "IMXUSDT", "BLURUSDT",
    # AI / Data
    "TAOUSDT", "AGIXUSDT", "OCEANUSDT", "GRTUSDT", "NMRUSDT",
    "CTXCUSDT", "RNDRUSDT", "AIUSDT",
    # Infrastructure
    "STORJUSDT", "AKASHUSDT", "ARPAUSDT", "POWRUSDT", "OMUSDT",
    "WANUSDT", "CELRUSDT", "CTSIUSDT", "REQUSDT", "BANDUSDT",
    # Exchange tokens
    "OKBUSDT", "HTUSDT", "KCSUSDT",
    # Other liquid pairs
    "XMRUSDT", "DASHUSDT", "ZECUSDT", "BCHUSDT", "EOSUSDT",
    "RVNUSDT", "COTIUSDT", "STPTUSDT", "TUSDT", "NKNUSDT",
    "ASTRUSDT", "LOOMUSDT", "IDUSDT", "EDUUSDT", "ACEUSDT",
    "PORTALUSDT", "AEVOLUSDT", "WUSDT", "MYROUSDT",
]


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
