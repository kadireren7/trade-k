/* trade-k Web UI v2 — app.js */
'use strict';

// ── State ──
const S = {
  symbol: 'BTCUSDT',
  tf: '1h',
  btMode: 'simple',
  ctrlTab: 'order',
  mainTab: 'chart',
  prices: {},   // SYMBOL → price (float)
  changes: {},  // SYMBOL → change_pct (float)
  portfolio: null,
  alerts: [],
  config: null,
  chart: null,
  series: null,
  volSeries: null,
  ws: null,
  wsReconn: null,
};

// ── Helpers ──
const $ = id => document.getElementById(id);
const qs = sel => document.querySelector(sel);
const qsa = sel => document.querySelectorAll(sel);

function toast(msg, type = 'info', ms = 3000) {
  const el = $('toast');
  el.textContent = msg;
  el.className = type;
  el.classList.remove('hidden');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add('hidden'), ms);
}

function setMsg(id, msg, ok) {
  const el = $(id);
  if (!el) return;
  el.textContent = msg;
  el.className = ok ? 'msg-ok' : 'msg-err';
  setTimeout(() => { if (el) { el.textContent = ''; el.className = ''; } }, 4000);
}

async function api(method, path, body) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  const data = await r.json();
  if (!r.ok) throw new Error(data.detail || data.error || JSON.stringify(data));
  return data;
}

// ── Chart ──
function initChart() {
  const container = $('chart-container');
  const chart = LightweightCharts.createChart(container, {
    layout: { background: { color: '#0a0e14' }, textColor: '#7a94b0' },
    grid: { vertLines: { color: '#111820' }, horzLines: { color: '#111820' } },
    crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
    rightPriceScale: { borderColor: '#1a2740' },
    timeScale: { borderColor: '#1a2740', timeVisible: true, secondsVisible: false },
    width: container.clientWidth,
    height: container.clientHeight,
  });

  S.series = chart.addCandlestickSeries({
    upColor: '#3ddc84', downColor: '#ff5252',
    borderUpColor: '#3ddc84', borderDownColor: '#ff5252',
    wickUpColor: '#3ddc84', wickDownColor: '#ff5252',
  });

  S.volSeries = chart.addHistogramSeries({
    priceFormat: { type: 'volume' },
    priceScaleId: 'vol',
    scaleMargins: { top: 0.85, bottom: 0 },
  });
  chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

  S.chart = chart;
  new ResizeObserver(() => {
    chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
  }).observe(container);

  loadCandles();
}

async function loadCandles() {
  try {
    const d = await api('GET', `/api/klines/${encodeURIComponent(S.symbol)}?interval=${S.tf}&limit=200`);
    const klines = d.klines || [];
    if (!klines.length) return;
    // t is in milliseconds from Binance / Yahoo; divide to get seconds for LWC
    const candles = klines.map(k => ({ time: Math.floor(k.t / 1000), open: k.o, high: k.h, low: k.l, close: k.c }));
    const vols = klines.map(k => ({
      time: Math.floor(k.t / 1000), value: k.v,
      color: k.c >= k.o ? '#1a3a2044' : '#3a1a1a44',
    }));
    S.series.setData(candles);
    S.volSeries.setData(vols);
    S.chart.timeScale().fitContent();
  } catch (e) {
    console.warn('candles:', e.message);
  }
}

// ── WebSocket ──
// api.py sends: {type:"prices", prices:{SYMBOL:FLOAT}, changes:{SYMBOL:FLOAT}, ts:...}
let _wsBackoff = 1500;
function connectWS() {
  if (S.ws) { try { S.ws.close(); } catch(_){} }
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${protocol}://${location.host}/ws/prices`);
  S.ws = ws;

  ws.onopen = () => {
    _wsBackoff = 1500;
    // Subscribe to watchlist symbols
    ws.send(JSON.stringify({ type: 'subscribe', symbols: WATCHLIST }));
  };

  ws.onmessage = ev => {
    try {
      const d = JSON.parse(ev.data);
      if (d.type === 'prices') {
        Object.assign(S.prices, d.prices || {});
        Object.assign(S.changes, d.changes || {});
        updateWatchlistPrices();
        const p = S.prices[S.symbol];
        if (p) updateTopTicker(S.symbol, p, S.changes[S.symbol] || 0);
        if (S.mainTab === 'portfolio' && S.portfolio) updatePortfolioPnL();
      }
    } catch (_) {}
  };

  ws.onclose = () => {
    S.ws = null;
    clearTimeout(S.wsReconn);
    S.wsReconn = setTimeout(connectWS, _wsBackoff);
    _wsBackoff = Math.min(_wsBackoff * 2, 60000);
  };
  ws.onerror = () => ws.close();
}

function updateTopTicker(sym, price, chg) {
  $('cur-symbol').textContent = sym;
  $('cur-price').textContent = fmtPrice(price);
  const chgEl = $('cur-change');
  chgEl.textContent = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
  chgEl.className = chg >= 0 ? 'up' : 'down';
}

function fmtPrice(p) {
  p = parseFloat(p);
  if (isNaN(p)) return '—';
  if (p >= 1000) return p.toLocaleString('tr-TR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (p >= 1)    return p.toFixed(4);
  return p.toFixed(6);
}

function fmtVol(v) {
  if (!v) return '—';
  v = parseFloat(v);
  if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
  if (v >= 1e6) return (v / 1e6).toFixed(1) + 'M';
  if (v >= 1e3) return (v / 1e3).toFixed(0) + 'K';
  return v.toFixed(0);
}

// ── Config / status chips ──
async function loadConfig() {
  try {
    S.config = await api('GET', '/api/config');
    applyConfigToUI(S.config);
  } catch (e) { console.warn('config:', e.message); }
}

function applyConfigToUI(cfg) {
  if (!cfg) return;
  const mode = (cfg.trading_mode || 'paper').toUpperCase();
  const chipMode = $('chip-mode');
  chipMode.textContent = mode;
  chipMode.className = 'chip' + (mode === 'LIVE' ? ' live' : '');

  const exch = (cfg.exchange || 'binance').toUpperCase();
  const connected = cfg.binance_connected || cfg.bybit_connected || cfg.okx_connected;
  const chipEx = $('chip-exchange');
  chipEx.textContent = exch + (connected ? '·OK' : '·OFF');
  chipEx.className = 'chip' + (connected ? ' connected' : '');

  const provider = (cfg.ai_provider || 'claude').toUpperCase();
  const model = cfg.model ? `·${cfg.model}` : '';
  $('chip-ai').textContent = provider + model;
  const badge = $('ai-provider-badge');
  if (badge) badge.textContent = provider + (model ? ' ' + model.replace('·','') : '') + ' · sohbet hazır';

  if ($('set-exchange')) {
    const ex = cfg.exchange || 'binance';
    $('set-exchange').value = ex;
    $('okx-pass-row').style.display = ex === 'okx' ? '' : 'none';
    const row = $('exchange-status-row');
    if (row) {
      const isConn = ex === 'binance' ? cfg.binance_connected : ex === 'bybit' ? cfg.bybit_connected : cfg.okx_connected;
      row.innerHTML = isConn
        ? '<span class="ex-connected">✓ Bağlı</span>'
        : '<span class="ex-disconnected">○ Bağlı değil</span>';
    }
  }
  if ($('set-mode')) $('set-mode').value = cfg.trading_mode || 'paper';
  if ($('set-ai-provider')) {
    $('set-ai-provider').value = cfg.ai_provider || 'claude';
    updateAiModelOptions(cfg.ai_provider || 'claude');
    if (cfg.model) $('set-ai-model').value = cfg.model;
  }
  if ($('set-scalp')) $('set-scalp').checked = !!cfg.scalp_enabled;
  if ($('set-leverage')) $('set-leverage').checked = !!cfg.leverage_enabled;
}

function updateAiModelOptions(provider) {
  const sel = $('set-ai-model');
  if (!sel) return;
  const opts = {
    claude:  [['claude-sonnet-4-6', 'Sonnet 4.6 (Önerilen)'], ['claude-opus-4-8', 'Opus 4.8 (En Güçlü)'], ['claude-haiku-4-5-20251001', 'Haiku 4.5 (En Hızlı)']],
    openai:  [['gpt-4o', 'GPT-4o'], ['gpt-4o-mini', 'GPT-4o Mini'], ['o3-mini', 'o3 Mini']],
    gemini:  [['gemini-2.0-flash', 'Gemini 2.0 Flash'], ['gemini-1.5-pro', 'Gemini 1.5 Pro']],
    grok:    [['grok-3', 'Grok-3'], ['grok-3-fast', 'Grok-3 Fast']],
    ollama:  [['llama3.3', 'LLaMA 3.3'], ['mistral', 'Mistral'], ['deepseek-r1', 'DeepSeek-R1']],
  };
  const list = opts[provider] || opts.claude;
  sel.innerHTML = list.map(([v, l]) => `<option value="${v}">${l}</option>`).join('');
  $('ai-key-row').classList.toggle('hidden', provider === 'claude' || provider === 'ollama');
}

// ── Autonomous status ──
async function loadAutoStatus() {
  try {
    const d = await api('GET', '/api/autonomous/status');
    const el = $('auto-status');
    if (!el) return;
    const _planLabels = { sadece_long:'LONG', dengeli:'DENGELI', tam:'TAM' };
    const rows = [
      ['Durum', d.enabled ? '🟢 Çalışıyor' : '⚫ Durdu'],
      ['Risk Profili', d.mode || '—'],
      ['Trade Planı', _planLabels[d.trade_plan] || d.trade_plan || '—'],
      ['Günlük İşlem', d.daily_trades != null ? d.daily_trades : '0'],
      ['Ardışık Kayıp', d.consecutive_losses != null ? d.consecutive_losses : '0'],
    ];
    if (d.cooldown_until && d.cooldown_until > Date.now() / 1000) {
      const mins = Math.ceil((d.cooldown_until - Date.now() / 1000) / 60);
      rows.push(['Soğuma', mins + 'dk kaldı']);
    }
    if (d.risk_locked) rows.push(['Risk', '🔒 Kilitli']);
    el.innerHTML = rows.map(([k, v]) =>
      `<div class="auto-row"><span class="auto-key">${k}</span><span class="auto-val">${v}</span></div>`
    ).join('');

    const isOn = d.enabled;
    $('chip-auto').textContent = 'AUTO:' + (isOn ? 'ON' : 'OFF');
    $('chip-auto').className = 'chip' + (isOn ? ' auto-on' : '');
    if ($('auto-mode-sel') && d.mode) $('auto-mode-sel').value = d.mode;
  } catch (e) { console.warn('auto status:', e.message); }
}

// ── Watchlist ──
const WATCHLIST = [
  'BTCUSDT',  'ETHUSDT',  'SOLUSDT',  'BNBUSDT',  'XRPUSDT',
  'AVAXUSDT', 'DOGEUSDT', 'LINKUSDT', 'ADAUSDT',  'DOTUSDT',
  'MATICUSDT','UNIUSDT',  'LTCUSDT',  'ATOMUSDT', 'NEARUSDT',
  'APTUSDT',  'SUIUSDT',  'ARBUSDT',  'OPUSDT',   'INJUSDT',
];

function renderWatchlist() {
  const el = $('watchlist');
  el.innerHTML = WATCHLIST.map(sym => {
    const price = S.prices[sym] ? fmtPrice(S.prices[sym]) : '—';
    const chg = S.changes[sym] != null ? S.changes[sym] : null;
    const chgStr = chg !== null ? (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%' : '—';
    const chgClass = chg === null ? '' : chg >= 0 ? 'up' : 'down';
    return `<div class="wl-item${sym === S.symbol ? ' active' : ''}" data-sym="${sym}">
      <div class="wl-row1"><span class="wl-sym">${sym.replace('USDT','')}</span><span class="wl-price">${price}</span></div>
      <div class="wl-change ${chgClass}">${chgStr}</div>
    </div>`;
  }).join('');
  qsa('#watchlist .wl-item').forEach(el => {
    el.addEventListener('click', () => switchSymbol(el.dataset.sym));
  });
}

function updateWatchlistPrices() {
  WATCHLIST.forEach(sym => {
    const item = qs(`#watchlist [data-sym="${sym}"]`);
    if (!item) return;
    const p = S.prices[sym];
    if (p == null) return;
    item.querySelector('.wl-price').textContent = fmtPrice(p);
    const chg = S.changes[sym] || 0;
    const chgEl = item.querySelector('.wl-change');
    chgEl.textContent = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
    chgEl.className = 'wl-change ' + (chg >= 0 ? 'up' : 'down');
  });
}

function switchSymbol(sym) {
  S.symbol = sym;
  $('sym-input').value = '';
  qsa('#watchlist .wl-item').forEach(el => el.classList.toggle('active', el.dataset.sym === sym));
  $('cur-symbol').textContent = sym;
  document.title = sym + ' — trade-k';
  loadCandles();
  loadTA();
  loadSpread();
}

// ── TA detail — uses /api/ta/{symbol}?timeframe=... ──
// Response fields: signal, score, rsi, macd_hist, ema20, ema50, atr, vol_ratio, price
async function loadTA() {
  const el = $('ta-detail');
  const taBar = $('ta-bar');
  if (!el) return;
  el.innerHTML = '<span style="color:var(--text3);font-size:10px">Yükleniyor...</span>';
  taBar.innerHTML = '<span class="ta-loading">Yükleniyor...</span>';
  try {
    const d = await api('GET', `/api/ta/${encodeURIComponent(S.symbol)}?timeframe=${S.tf}`);
    const sig = d.signal || 'BEKLE';
    const sigClass = sig.includes('AL') || sig === 'BUY' ? 'AL' : sig.includes('SAT') || sig === 'SELL' ? 'SAT' : 'BEKLE';
    const emaColor = (d.ema20 || 0) > (d.ema50 || 0) ? 'up' : 'down';
    const macdColor = (d.macd_hist || 0) > 0 ? 'up' : 'down';
    const rsiColor = d.rsi > 70 ? 'down' : d.rsi < 30 ? 'up' : 'gold';

    el.innerHTML = `
      <span class="signal-badge ${sigClass}">${sig}</span>
      <div class="ta-row"><span class="ta-key">Fiyat</span><span class="ta-val">${fmtPrice(d.price)}</span></div>
      <div class="ta-row"><span class="ta-key">EMA20</span><span class="ta-val ${emaColor}">${fmtPrice(d.ema20)}</span></div>
      <div class="ta-row"><span class="ta-key">EMA50</span><span class="ta-val ${emaColor}">${fmtPrice(d.ema50)}</span></div>
      <div class="ta-row"><span class="ta-key">MACD</span><span class="ta-val ${macdColor}">${(d.macd_hist||0).toFixed(4)}</span></div>
      <div class="ta-row"><span class="ta-key">RSI</span><span class="ta-val ${rsiColor}">${(d.rsi||0).toFixed(1)}</span></div>
      <div class="ta-row"><span class="ta-key">ATR</span><span class="ta-val">${(d.atr||0).toFixed(4)}</span></div>
      <div class="ta-row"><span class="ta-key">Vol Ratio</span><span class="ta-val ${(d.vol_ratio||1)>1.5?'up':''}">${(d.vol_ratio||0).toFixed(2)}x</span></div>
      <div class="ta-row"><span class="ta-key">ADX</span><span class="ta-val ${(d.adx||0)>25?'up':''}">${(d.adx||0).toFixed(1)}</span></div>
      <div class="ta-row"><span class="ta-key">Skor</span><span class="ta-val">${d.score != null ? d.score : '—'}</span></div>
    `;

    const sigColor = sigClass === 'AL' ? 'up' : sigClass === 'SAT' ? 'down' : 'gold';
    taBar.innerHTML = `
      <div class="ta-pill"><span class="lbl">SİNYAL&nbsp;</span><span class="val ${sigColor}">${sig}</span></div>
      <div class="ta-pill"><span class="lbl">RSI&nbsp;</span><span class="val ${rsiColor}">${(d.rsi||0).toFixed(1)}</span></div>
      <div class="ta-pill"><span class="lbl">MACD&nbsp;</span><span class="val ${macdColor}">${(d.macd_hist||0).toFixed(4)}</span></div>
      <div class="ta-pill"><span class="lbl">ADX&nbsp;</span><span class="val">${(d.adx||0).toFixed(1)}</span></div>
      <div class="ta-pill"><span class="lbl">BB%&nbsp;</span><span class="val">${(d.bb_pct||0).toFixed(2)}</span></div>
    `;
    loadSpread();
  } catch (e) {
    el.innerHTML = `<span style="color:var(--text3);font-size:10px">TA alınamadı: ${e.message}</span>`;
    taBar.innerHTML = '<span class="ta-loading">TA alınamadı</span>';
  }
}

// ── Spread — uses /api/spread/{symbol} ──
async function loadSpread() {
  // Yahoo Finance sembolleri (= içerenler) için spread verisi yok
  if (S.symbol.includes('=')) {
    const chip = $('cur-spread');
    if (chip) { chip.textContent = ''; chip.classList.add('hidden'); }
    const spd = $('spread-detail');
    if (spd) spd.innerHTML = '<div class="ta-row" style="color:var(--text3);font-size:10px">Hisse/emtia için spread verisi yok</div>';
    return;
  }
  try {
    const d = await api('GET', `/api/spread/${encodeURIComponent(S.symbol)}`);
    const pct = parseFloat(d.spread_pct || 0);
    const cls = pct < 0.05 ? 'spd-good' : pct < 0.15 ? 'spd-wide' : 'spd-bad';

    const chip = $('cur-spread');
    chip.textContent = 'Spread: ' + pct.toFixed(4) + '%';
    chip.className = 'spread-chip';
    chip.classList.remove('hidden');

    const spd = $('spread-detail');
    if (spd) spd.innerHTML = `
      <div class="ta-row"><span class="ta-key">Alış</span><span class="ta-val">${fmtPrice(d.bid)}</span></div>
      <div class="ta-row"><span class="ta-key">Satış</span><span class="ta-val">${fmtPrice(d.ask)}</span></div>
      <div class="ta-row"><span class="ta-key">Spread</span><span class="ta-val ${cls}">${pct.toFixed(4)}%</span></div>
    `;
  } catch (_) {}
}

// ── Portfolio — response: {cash, equity, open_pnl, positions:[{symbol,qty,entry,current,...}]} ──
async function refreshPortfolio() {
  try {
    const d = await api('GET', '/api/portfolio');
    S.portfolio = d;
    renderPortfolioStats(d);
    renderPositions(d.positions || []);
    renderPositionsMini(d.positions || []);
    renderAccountSummary(d);

    // Account card güncelle
    const fmt2 = v => (parseFloat(v)||0).toFixed(2);
    const opnl = d.open_pnl || 0;
    const totpnl = (d.equity || 0) - 10000;
    if ($('ac-cash')) $('ac-cash').textContent = fmt2(d.cash) + ' USDT';
    if ($('ac-equity')) $('ac-equity').textContent = fmt2(d.equity) + ' USDT';
    if ($('ac-opnl')) {
      $('ac-opnl').textContent = (opnl>=0?'+':'') + fmt2(opnl) + ' USDT';
      $('ac-opnl').className = 'acc-card-val ' + (opnl>=0?'up':'down');
    }
    if ($('ac-totalpnl')) {
      $('ac-totalpnl').textContent = (totpnl>=0?'+':'') + fmt2(totpnl) + ' USDT';
      $('ac-totalpnl').className = 'acc-card-val ' + (totpnl>=0?'up':'down');
    }

    const h = await api('GET', '/api/history?limit=50');
    renderHistory(h.history || []);
  } catch (e) {
    toast('Portföy yüklenemedi: ' + e.message, 'err');
  }
}

function renderAccountSummary(d) {
  const el = $('account-summary');
  if (!el) return;
  const sign = v => v >= 0 ? '+' : '';
  const cls = v => v >= 0 ? 'up' : 'down';
  const f2 = v => (parseFloat(v)||0).toFixed(2);

  const opnl = d.open_pnl || 0;
  const tpnl = d.total_pnl || 0;
  const tpct = d.total_pct || 0;
  const dpnl = d.daily_pnl || 0;
  const npos = d.n_positions || 0;

  el.innerHTML = `
    <div class="acc-row">
      <span class="acc-label">Nakit</span>
      <span class="acc-val">${f2(d.cash)} USDT</span>
    </div>
    <div class="acc-row">
      <span class="acc-label">Varlık</span>
      <span class="acc-val">${f2(d.equity)} <small class="${cls(tpnl)}">${sign(tpct)}${f2(tpct)}%</small></span>
    </div>
    <div class="acc-row">
      <span class="acc-label">Açık K/Z</span>
      <span class="acc-val ${cls(opnl)}">${sign(opnl)}${f2(opnl)} USDT</span>
    </div>
    <div class="acc-row">
      <span class="acc-label">Gün K/Z</span>
      <span class="acc-val ${cls(dpnl)}">${sign(dpnl)}${f2(dpnl)} USDT</span>
    </div>
    <div class="acc-row">
      <span class="acc-label">Toplam K/Z</span>
      <span class="acc-val ${cls(tpnl)}">${sign(tpnl)}${f2(tpnl)} USDT</span>
    </div>
    <div class="acc-row">
      <span class="acc-label">Pozisyon</span>
      <span class="acc-val">${npos} açık</span>
    </div>
  `;
}

function updatePortfolioPnL() {
  if (!S.portfolio || !S.portfolio.positions) return;
  let openPnl = 0;

  S.portfolio.positions.forEach(p => {
    const cur = S.prices[p.symbol] || p.current || p.entry;
    const pnl = (cur - p.entry) * p.qty;
    const pnlPct = p.entry ? (cur / p.entry - 1) * 100 : 0;
    openPnl += pnl;

    // Portföy tabı tablo satırlarını güncelle
    const tbody = $('positions-tbody');
    if (tbody) {
      tbody.querySelectorAll('tr').forEach(row => {
        const symCell = row.querySelector('.sym');
        if (!symCell || symCell.textContent !== p.symbol) return;
        const cells = row.querySelectorAll('td');
        if (cells[3]) cells[3].textContent = fmtPrice(cur);
        if (cells[4]) {
          cells[4].textContent = (pnl >= 0 ? '+' : '') + pnl.toFixed(2);
          cells[4].className = 'num ' + (pnl >= 0 ? 'up' : 'down');
        }
        if (cells[5]) {
          cells[5].textContent = (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(2) + '%';
          cells[5].className = 'num ' + (pnlPct >= 0 ? 'up' : 'down');
        }
      });
    }

    // Mini pozisyon listesini de güncelle
    const miniEl = document.querySelector(`#positions-mini [data-sym="${p.symbol}"] .pos-pnl`);
    if (miniEl) {
      miniEl.textContent = (pnlPct >= 0 ? '+' : '') + pnlPct.toFixed(2) + '%';
      miniEl.className = 'pos-pnl ' + (pnlPct >= 0 ? 'up' : 'down');
    }
  });

  // Sidebar account summary güncelle (Açık K/Z satırı = 3. satır, index 2)
  const summary = $('account-summary');
  if (summary) {
    const rows = summary.querySelectorAll('.acc-row');
    if (rows[2]) {
      const valEl = rows[2].querySelector('.acc-val');
      if (valEl) {
        valEl.textContent = (openPnl >= 0 ? '+' : '') + openPnl.toFixed(2) + ' USDT';
        valEl.className = 'acc-val ' + (openPnl >= 0 ? 'up' : 'down');
      }
    }
  }

  // account-card güncelle (sağ panel her zaman görünür)
  const opnlEl = $('ac-opnl');
  if (opnlEl) {
    opnlEl.textContent = (openPnl >= 0 ? '+' : '') + openPnl.toFixed(2) + ' USDT';
    opnlEl.className = 'acc-card-val ' + (openPnl >= 0 ? 'up' : 'down');
  }
}

function renderPortfolioStats(d) {
  const stats = [
    { label: 'USDT', val: (d.cash||0).toFixed(2), cls: '' },
    { label: 'Toplam Değer', val: (d.equity||0).toFixed(2), cls: '' },
    { label: 'Açık PnL', val: (d.open_pnl||0).toFixed(2), cls: (d.open_pnl||0)>=0?'up':'down' },
    { label: 'Açık Pozisyon', val: (d.n_positions||0), cls: '' },
  ];
  $('portfolio-stats').innerHTML = stats.map(s =>
    `<div class="stat-card"><div class="stat-label">${s.label}</div><div class="stat-val ${s.cls}">${s.val}</div></div>`
  ).join('');
}

function renderPositions(positions) {
  const tbody = $('positions-tbody');
  if (!positions.length) {
    tbody.innerHTML = '<tr><td colspan="10" style="color:var(--text3);text-align:center;padding:20px">Açık pozisyon yok</td></tr>';
    return;
  }
  tbody.innerHTML = positions.map(p => {
    // api.py returns: symbol, qty, entry, current, pnl_usdt, pnl_pct, stop, target, value_usdt
    return `<tr>
      <td class="sym">${p.symbol}</td>
      <td class="num">${(p.qty||0).toFixed(6)}</td>
      <td class="num">${fmtPrice(p.entry)}</td>
      <td class="num">${fmtPrice(p.current)}</td>
      <td class="num ${(p.pnl_usdt||0)>=0?'up':'down'}">${((p.pnl_usdt||0)>=0?'+':'')}${(p.pnl_usdt||0).toFixed(2)}</td>
      <td class="num ${(p.pnl_pct||0)>=0?'up':'down'}">${((p.pnl_pct||0)>=0?'+':'')}${(p.pnl_pct||0).toFixed(2)}%</td>
      <td class="num">${p.stop ? fmtPrice(p.stop) : '—'}</td>
      <td class="num">${p.target ? fmtPrice(p.target) : '—'}</td>
      <td class="num">${(p.value_usdt||0).toFixed(2)}</td>
      <td><button class="danger-btn" style="padding:2px 8px;font-size:10px" onclick="quickSell('${p.symbol}')">SAT</button></td>
    </tr>`;
  }).join('');
}

function renderHistory(history) {
  const tbody = $('history-tbody');
  if (!history.length) {
    tbody.innerHTML = '<tr><td colspan="7" style="color:var(--text3);text-align:center;padding:20px">Geçmiş yok</td></tr>';
    return;
  }
  tbody.innerHTML = history.map(t => {
    const pnl = t.pnl || 0;
    // history uses: ts, side (AL/SAT/SHORT/LEVERAGE...), symbol, qty, price, usdt, pnl
    const side = t.side || t.action || '';
    const isBuy = side === 'AL' || side === 'buy' || side === 'LEVERAGE' || side === 'SHORT';
    const isClose = !isBuy;
    const pnlVal = t.pnl || 0;
    const entryUsdt = t.usdt || 1;
    const pnlPct = isClose && entryUsdt > 0 ? (pnlVal / entryUsdt * 100) : null;
    return `<tr>
      <td>${t.ts ? new Date(t.ts * 1000).toLocaleDateString('tr-TR') : '—'}</td>
      <td class="sym">${t.symbol || '—'}</td>
      <td class="${isBuy?'up':'down'}">${side}</td>
      <td class="num">${fmtPrice(t.price)}</td>
      <td class="num">${(t.qty||0).toFixed(6)}</td>
      <td class="num ${pnlVal>=0?'up':'down'}">${isClose ? (pnlVal>=0?'+':'')+pnlVal.toFixed(2) : '—'}</td>
      <td class="num ${pnlVal>=0?'up':'down'}">${pnlPct !== null ? (pnlPct>=0?'+':'')+pnlPct.toFixed(2)+'%' : '—'}</td>
    </tr>`;
  }).join('');
}

function renderPositionsMini(positions) {
  const el = $('positions-mini');
  if (!el) return;
  if (!positions.length) {
    el.innerHTML = '<div style="padding:8px 10px;color:var(--text3);font-size:10px">Pozisyon yok</div>';
    return;
  }
  el.innerHTML = positions.map(p => {
    const pnl = p.pnl_usdt || 0;
    const pct = p.pnl_pct || 0;
    const cls = pnl >= 0 ? 'up' : 'down';
    const sign = pnl >= 0 ? '+' : '';
    const style = p.trade_style === 'scalp' ? ' <small style="color:#64748b">SCALP</small>' : '';
    const lev = p.is_leveraged ? ` <small style="color:#f59e0b">${p.leverage}x</small>` : '';
    return `<div class="pos-item" data-sym="${p.symbol}" onclick="switchSymbol('${p.symbol}')">
      <div class="pos-row1">
        <span class="pos-sym">${p.name || p.symbol}${style}${lev}</span>
        <span class="pos-pnl ${cls}">${sign}${pnl.toFixed(2)} USDT</span>
      </div>
      <div class="pos-row2">
        <span style="color:var(--text3);font-size:10px">Giriş: ${fmtPrice(p.entry)}</span>
        <span class="pos-pnl ${cls}" style="font-size:10px">${sign}${pct.toFixed(2)}%</span>
      </div>
    </div>`;
  }).join('');
}

async function quickSell(symbol) {
  if (!confirm(symbol + ' pozisyonu kapatılsın mı?')) return;
  try {
    await api('POST', '/api/trade/sell', { symbol });
    toast(symbol + ' SAT emri verildi', 'ok');
    refreshPortfolio();
  } catch (e) { toast('Satış hatası: ' + e.message, 'err'); }
}

// ── Performance ──
// api.py response: {n_total, n_wins, n_losses, win_rate, profit_factor, sharpe, sortino, max_drawdown, monthly, sparkline}
async function loadPerformance() {
  try {
    const d = await api('GET', '/api/performance');
    const grid = $('perf-grid');
    const metrics = [
      { label: 'Sharpe', val: (d.sharpe||0).toFixed(2), cls: d.sharpe>=1?'up':d.sharpe<0?'down':'' },
      { label: 'Sortino', val: (d.sortino||0).toFixed(2), cls: d.sortino>=1?'up':d.sortino<0?'down':'' },
      { label: 'Max DD', val: (d.max_drawdown||0).toFixed(2)+'%', cls: 'down' },
      { label: 'Win Rate', val: (d.win_rate||0).toFixed(1)+'%', cls: (d.win_rate||0)>=50?'up':'down' },
      { label: 'Kazanılan', val: d.n_wins||0, cls: 'up' },
      { label: 'Kaybedilen', val: d.n_losses||0, cls: 'down' },
      { label: 'Profit Factor', val: (d.profit_factor||0).toFixed(2), cls: (d.profit_factor||0)>=1?'up':'down' },
      { label: 'Toplam', val: d.n_total||0, cls: '' },
    ];
    grid.innerHTML = metrics.map(m =>
      `<div class="stat-card"><div class="stat-label">${m.label}</div><div class="stat-val ${m.cls}">${m.val}</div></div>`
    ).join('');

    // sparkline is already a string of block chars from perf_mod.equity_sparkline
    if (d.sparkline) {
      $('sparkline').textContent = d.sparkline;
    }

    // monthly is [{month, pnl, trades}, ...] (already sorted, show newest first)
    if (Array.isArray(d.monthly) && d.monthly.length) {
      const tbody = $('monthly-tbody');
      tbody.innerHTML = [...d.monthly].reverse().map(v => {
        const pnl = v.pnl || 0;
        return `<tr><td>${v.month||'—'}</td><td class="${pnl>=0?'up':'down'}">${(pnl>=0?'+':'')}${pnl.toFixed(2)}</td><td>${v.trades||0}</td></tr>`;
      }).join('');
    } else if (d.n_total === 0) {
      $('monthly-tbody').innerHTML = '<tr><td colspan="3" style="color:var(--text3);text-align:center">Kapalı işlem yok</td></tr>';
    }
  } catch (e) {
    toast('Performans yüklenemedi', 'err');
  }
}

// ── Log — api.py returns {log: [...]} ──
async function loadLog() {
  try {
    const d = await api('GET', '/api/log?limit=200');
    renderLog(d.log || []);
  } catch (e) { console.warn('log:', e.message); }
}

function renderLog(entries) {
  const showOpen  = $('lf-open')?.checked ?? true;
  const showClose = $('lf-close')?.checked ?? true;
  const showHold  = $('lf-hold')?.checked ?? false;
  const showSkip  = $('lf-skip')?.checked ?? false;
  const showError = $('lf-error')?.checked ?? true;
  const el = $('log-container');
  const filtered = entries.filter(e => {
    const t = (e.type || e.event || '').toLowerCase();
    if ((t === 'open' || t === 'open_leveraged') && !showOpen) return false;
    if (t === 'close' && !showClose) return false;
    if (t === 'hold' && !showHold) return false;
    if (t === 'skip' && !showSkip) return false;
    if (t === 'error' && !showError) return false;
    return true;
  });
  el.innerHTML = filtered.map(e => {
    const ts = e.ts ? new Date(e.ts * 1000).toLocaleTimeString('tr-TR') : '—';
    const type = e.type || e.event || '—';
    const reason = e.reason || e.note || e.signal || '';
    const sym = e.symbol || '';
    return `<div class="log-row">
      <span class="log-time">${ts}</span>
      <span class="log-badge ${type}">${type}</span>
      ${sym ? `<span class="log-sym">${sym}</span>` : ''}
      <span class="log-reason">${reason}</span>
    </div>`;
  }).join('') || '<div style="padding:12px;color:var(--text3);font-size:11px">Log girişi yok</div>';
}

// ── Backtest — POST /api/backtest/{symbol} doesn't exist; use GET ──
async function runBacktest() {
  const btn = $('bt-run');
  btn.disabled = true;
  btn.textContent = '⏳ Çalışıyor...';
  $('bt-result').innerHTML = '<span style="color:var(--text3);font-size:11px">Çalışıyor...</span>';
  const sym    = ($('bt-symbol').value.trim().toUpperCase() || S.symbol);
  const tf     = $('bt-tf').value;
  const days   = parseInt($('bt-days').value) || 30;
  const stop   = parseFloat($('bt-stop').value) || 2.5;
  const target = parseFloat($('bt-target').value) || 5;
  try {
    const url = `/api/backtest/${encodeURIComponent(sym)}?timeframe=${tf}&days=${days}&stop_pct=${stop}&target_pct=${target}`;
    const d = await api('GET', url);
    renderBtResult(d, S.btMode);
  } catch (e) {
    $('bt-result').innerHTML = `<div style="color:var(--red);font-size:11px">Hata: ${e.message}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ Çalıştır';
  }
}

function renderBtSparkline(equity) {
  if (!equity || equity.length < 2) return '';
  const w = 180, h = 40, pad = 2;
  const min = Math.min(...equity);
  const max = Math.max(...equity);
  const range = max - min || 1;
  const pts = equity.map((v, i) => {
    const x = pad + (i / (equity.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const isUp = equity[equity.length - 1] >= equity[0];
  const color = isUp ? 'var(--green)' : 'var(--red)';
  return `<svg width="${w}" height="${h}" style="display:block;margin:6px auto 0">
    <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.5" stroke-linejoin="round"/>
  </svg>`;
}

function renderBtResult(d, mode) {
  // api.py returns: symbol, n_trades, wins, losses, win_rate, total_return_pct, max_drawdown_pct, profit_factor, p_value, significant, equity_curve
  const el = $('bt-result');
  const spark = renderBtSparkline(d.equity_curve || []);
  el.innerHTML = `
    ${spark}
    <div class="bt-row"><span class="bt-key">Sembol</span><span>${d.symbol}</span></div>
    <div class="bt-row"><span class="bt-key">PnL</span><span class="${(d.total_return_pct||0)>=0?'up':'down'}">${((d.total_return_pct||0)>=0?'+':'')}${(d.total_return_pct||0).toFixed(2)}%</span></div>
    <div class="bt-row"><span class="bt-key">İşlem</span><span>${d.n_trades||0}</span></div>
    <div class="bt-row"><span class="bt-key">Kazanma %</span><span>${(d.win_rate||0).toFixed(1)}%</span></div>
    <div class="bt-row"><span class="bt-key">Max DD</span><span class="down">${(d.max_drawdown_pct||0).toFixed(2)}%</span></div>
    <div class="bt-row"><span class="bt-key">Profit Factor</span><span class="${(d.profit_factor||0)>=1?'up':'down'}">${(d.profit_factor||0).toFixed(2)}</span></div>
    <div class="bt-row"><span class="bt-key">p-değeri</span><span class="${d.significant?'up':'gold'}">${(d.p_value||1).toFixed(4)} ${d.significant?'✓ Anlamlı':'— Belirsiz'}</span></div>
  `;
}

// ── Alerts ──
async function loadAlerts() {
  try {
    const d = await api('GET', '/api/alerts');
    S.alerts = d.alerts || [];
    renderAlerts();
  } catch (e) { console.warn('alerts:', e.message); }
}

function renderAlerts() {
  const el = $('alerts-list');
  if (!el) return;
  if (!S.alerts.length) {
    el.innerHTML = '<div style="color:var(--text3);font-size:10px;padding:4px 0">Alarm yok</div>';
    return;
  }
  el.innerHTML = S.alerts.map(a =>
    `<div class="alert-item">
      <span><span class="a-sym">${a.symbol}</span> ${a.action} @ ${fmtPrice(a.price)}</span>
      <span class="a-del" data-id="${a.id}">✕</span>
    </div>`
  ).join('');
  el.querySelectorAll('.a-del').forEach(btn => {
    btn.addEventListener('click', () => deleteAlert(parseInt(btn.dataset.id)));
  });
}

async function addAlert() {
  const price = parseFloat($('alr-price').value);
  const action = $('alr-action').value;
  const amount = parseFloat($('alr-amount').value) || 100;
  if (!price || isNaN(price)) { toast('Geçerli bir fiyat girin', 'err'); return; }
  try {
    // api.py: AlertRequest = {symbol, price, action, amount}
    await api('POST', '/api/alerts', { symbol: S.symbol, price, action, amount });
    toast('Alarm eklendi', 'ok');
    $('alr-price').value = '';
    loadAlerts();
  } catch (e) { toast('Alarm eklenemedi: ' + e.message, 'err'); }
}

async function deleteAlert(id) {
  try {
    await api('DELETE', `/api/alerts/${id}`);
    toast('Alarm silindi', 'info');
    loadAlerts();
  } catch (e) { toast('Alarm silinemedi', 'err'); }
}

// ── Trading orders ──
// api.py BuyRequest: {symbol, usdt, stop, target, style}
// api.py SellRequest: {symbol}
async function placeOrder(side) {
  const usdt   = parseFloat($('ord-usdt').value);
  const stop   = parseFloat($('ord-stop').value) || undefined;
  const target = parseFloat($('ord-target').value) || undefined;
  const style  = $('ord-style').value;
  if (!usdt || usdt <= 0) { setMsg('order-msg', 'Geçerli miktar girin', false); return; }

  const btn = side === 'buy' ? $('btn-buy') : $('btn-sell');
  btn.disabled = true;
  try {
    if (side === 'buy') {
      const body = { symbol: S.symbol, usdt, style };
      if (stop)   body.stop   = stop;
      if (target) body.target = target;
      const r = await api('POST', '/api/trade/buy', body);
      setMsg('order-msg', 'AL: ' + (r.qty||0).toFixed(6) + ' @ ' + fmtPrice(r.fill_price), true);
      toast(S.symbol + ' AL emri verildi', 'ok');
    } else {
      const r = await api('POST', '/api/trade/sell', { symbol: S.symbol });
      setMsg('order-msg', 'SAT emri verildi @ ' + fmtPrice(r.fill_price), true);
      toast(S.symbol + ' SAT emri verildi', 'ok');
    }
    refreshPortfolio();
  } catch (e) {
    setMsg('order-msg', 'Hata: ' + e.message, false);
    toast(e.message, 'err');
  } finally {
    btn.disabled = false;
  }
}

// ── Settings ──
// api.py PUT /api/config takes {key: str, value: Any} one at a time
async function updateConfig(key, value) {
  return api('PUT', '/api/config', { key, value });
}

async function saveExchangeSettings() {
  const exchange = $('set-exchange').value;
  const api_key = $('set-api-key').value.trim();
  const api_secret = $('set-api-secret').value.trim();
  const passphrase = $('set-api-pass').value.trim();
  if (!api_key || !api_secret) { setMsg('settings-msg', 'API Key ve Secret gerekli', false); return; }
  try {
    // api.py: ApiKeyRequest = {exchange, api_key, api_secret, passphrase}
    await api('POST', '/api/config/exchange-key', { exchange, api_key, api_secret, passphrase: passphrase || '' });
    setMsg('settings-msg', exchange.toUpperCase() + ' bağlantısı kaydedildi', true);
    toast('Borsa bağlantısı kaydedildi', 'ok');
    $('set-api-key').value = '';
    $('set-api-secret').value = '';
    $('set-api-pass').value = '';
    loadConfig();
  } catch (e) { setMsg('settings-msg', 'Kayıt hatası: ' + e.message, false); }
}

async function deleteExchangeKey() {
  const exchange = $('set-exchange').value;
  if (!confirm(exchange.toUpperCase() + ' API anahtarları silinsin mi?')) return;
  try {
    await api('DELETE', `/api/config/exchange-key/${exchange}`);
    setMsg('settings-msg', exchange.toUpperCase() + ' bağlantısı silindi', true);
    toast('Borsa bağlantısı silindi', 'info');
    loadConfig();
  } catch (e) { setMsg('settings-msg', 'Silme hatası: ' + e.message, false); }
}

async function saveMode() {
  const mode = $('set-mode').value;
  if (mode === 'live' && !confirm('DİKKAT: Gerçek para modu seçildi. Emin misiniz?')) return;
  try {
    await updateConfig('trading_mode', mode);
    setMsg('settings-msg', 'Mod: ' + mode.toUpperCase(), true);
    toast('Trading modu: ' + mode.toUpperCase(), 'ok');
    loadConfig();
  } catch (e) { setMsg('settings-msg', e.message, false); }
}

async function saveAiSettings() {
  const provider = $('set-ai-provider').value;
  const model    = $('set-ai-model').value;
  const key      = $('set-ai-key').value.trim();
  try {
    await updateConfig('ai_provider', provider);
    await updateConfig('model', model);
    if (key) {
      // api.py: AiKeyRequest = {provider, api_key}
      await api('POST', '/api/config/ai-key', { provider, api_key: key });
    }
    setMsg('settings-msg', 'AI ayarları kaydedildi', true);
    toast('AI: ' + provider.toUpperCase() + ' · ' + model, 'ok');
    $('set-ai-key').value = '';
    loadConfig();
  } catch (e) { setMsg('settings-msg', e.message, false); }
}

async function saveToggles() {
  try {
    await updateConfig('scalp_enabled', $('set-scalp').checked);
    await updateConfig('leverage_enabled', $('set-leverage').checked);
    toast('Seçenekler kaydedildi', 'ok');
  } catch (e) { toast(e.message, 'err'); }
}

// ── Trade plan selection ──
let _selectedPlan = 'tam';
const _PLAN_DESC = {
  long:     'Sadece LONG pozisyonlar — en güvenli, kripto düşüşlerinde bekler',
  dengeli:  'LONG + SHORT karışık — her iki yönde pozisyon alır',
  scalp:    'Hızlı SCALP işlemler — 3 dakikada bir tarama, küçük kâr hedefi',
  kaldirac: 'LONG + küçük kaldıraç — maks 3x, %0.5 risk per işlem',
  tam:      'Tüm türler: long/short/scalp/kaldıraç — 3dk tarama, profesyonel mod',
};

function setupTradePlanButtons() {
  document.querySelectorAll('.plan-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.plan-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      _selectedPlan = btn.dataset.plan;
      const desc = $('plan-desc');
      if (desc) desc.textContent = _PLAN_DESC[_selectedPlan] || '';
    });
  });
}

// ── Connections panel ──
async function loadConnections() {
  try {
    const d = await api('GET', '/api/connections');
    const set = (id, ok, label) => {
      const el = $(id);
      if (!el) return;
      el.textContent = label;
      el.className = 'conn-status ' + (ok ? 'conn-ok' : 'conn-err');
    };
    set('conn-ws', d.binance_ws, d.binance_ws ? 'BAĞLI ✓' : 'YOK');
    set('conn-key', d.binance_api_key, d.binance_api_key ? 'Ayarlı ✓' : 'Paper (key yok)');
    const aiLabel = d.ai_provider.toUpperCase() + (d.ai_key_set ? ' ✓' : ' (key yok)');
    set('conn-ai', d.ai_key_set, aiLabel);
    const modeLabel = d.trading_mode === 'live' ? 'GERÇEK' : 'PAPER';
    const modeEl = $('conn-mode');
    if (modeEl) {
      modeEl.textContent = modeLabel;
      modeEl.className = 'conn-status ' + (d.trading_mode === 'live' ? 'conn-ok' : 'conn-warn');
    }
    // Sync active plan button
    const planMap = { sadece_long: 'long', dengeli: 'dengeli', tam: 'tam' };
    let activePlan = planMap[d.trade_plan] || 'dengeli';
    if (d.scalp_enabled && d.leverage_enabled) activePlan = 'tam';
    else if (d.scalp_enabled) activePlan = 'scalp';
    else if (d.leverage_enabled) activePlan = 'kaldirac';
    document.querySelectorAll('.plan-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.plan === activePlan);
    });
    _selectedPlan = activePlan;
    const desc = $('plan-desc');
    if (desc) desc.textContent = _PLAN_DESC[activePlan] || '';
  } catch (e) { /* silently ignore */ }
}

// ── Autonomous controls ──
async function startAuto() {
  try {
    // First apply trade plan, then apply risk profile
    await api('POST', '/api/autonomous/mode', { mode: _selectedPlan });
    const riskMode = $('auto-mode-sel')?.value || 'dengeli';
    await api('POST', '/api/autonomous/mode', { mode: riskMode });
    toast('Otonom mod başlatıldı — ' + _selectedPlan.toUpperCase(), 'ok');
    setMsg('auto-msg', 'Başlatıldı: ' + _selectedPlan.toUpperCase(), true);
    loadAutoStatus();
    loadConnections();
  } catch (e) { setMsg('auto-msg', e.message, false); }
}

async function stopAuto() {
  try {
    await api('POST', '/api/autonomous/mode', { mode: 'kapat' });
    toast('Otonom mod durduruldu', 'info');
    setMsg('auto-msg', 'Durduruldu', true);
    loadAutoStatus();
  } catch (e) { setMsg('auto-msg', e.message, false); }
}

async function applyAutoMode() {
  const mode = $('auto-mode-sel').value;
  try {
    await api('POST', '/api/autonomous/mode', { mode });
    toast('Risk profili: ' + mode, 'ok');
    setMsg('auto-msg', 'Profil: ' + mode, true);
    loadAutoStatus();
  } catch (e) { setMsg('auto-msg', e.message, false); }
}

async function applyStrategy() {
  const strat = $('strat-sel').value;
  try {
    await updateConfig('active_strategy', strat);
    toast('Strateji: ' + strat, 'ok');
    setMsg('auto-msg', 'Strateji: ' + strat, true);
  } catch (e) { setMsg('auto-msg', e.message, false); }
}

// ── Symbol search ──
function setupSearch() {
  const inp = $('sym-input');
  const dd = $('sym-dropdown');
  let _t;
  inp.addEventListener('input', () => {
    clearTimeout(_t);
    const q = inp.value.trim().toUpperCase();
    if (!q) { dd.classList.add('hidden'); return; }
    _t = setTimeout(() => fetchSearch(q), 250);
  });
  inp.addEventListener('keydown', e => {
    if (e.key === 'Escape') { dd.classList.add('hidden'); inp.value = ''; }
    if (e.key === 'Enter') {
      const first = dd.querySelector('.dd-item');
      if (first) { switchSymbol(first.dataset.sym); dd.classList.add('hidden'); inp.value = ''; }
    }
  });
  document.addEventListener('click', e => {
    if (!e.target.closest('#search-wrap')) dd.classList.add('hidden');
  });
}

async function fetchSearch(q) {
  const dd = $('sym-dropdown');
  // Build local matches from watchlist + movers
  const candidates = WATCHLIST.filter(s => s.includes(q));
  if (candidates.length) {
    dd.innerHTML = candidates.map(sym => {
      const p = S.prices[sym];
      const chg = S.changes[sym] || 0;
      return `<div class="dd-item" data-sym="${sym}">
        <span class="dd-sym">${sym}</span>
        <span class="dd-price">${p ? fmtPrice(p) : '—'}</span>
        <span class="dd-chg ${chg>=0?'up':'down'}">${(chg>=0?'+':'')}${chg.toFixed(2)}%</span>
      </div>`;
    }).join('');
    dd.classList.remove('hidden');
  } else {
    // Try generic USDT pair
    const sym = q.endsWith('USDT') ? q : q + 'USDT';
    dd.innerHTML = `<div class="dd-item" data-sym="${sym}">
      <span class="dd-sym">${sym}</span>
      <span class="dd-price">—</span>
      <span class="dd-chg">seç</span>
    </div>`;
    dd.classList.remove('hidden');
  }
  dd.querySelectorAll('.dd-item').forEach(el => {
    el.addEventListener('click', () => {
      switchSymbol(el.dataset.sym);
      dd.classList.add('hidden');
      $('sym-input').value = '';
    });
  });
}

// ── Tab navigation ──
function setupNavTabs() {
  qsa('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      qsa('.nav-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      S.mainTab = btn.dataset.tab;
      qsa('#content .tab-panel').forEach(p => p.classList.add('hidden'));
      const panel = $('tab-' + btn.dataset.tab);
      if (panel) panel.classList.remove('hidden');
      if (S.mainTab === 'portfolio') refreshPortfolio();
      if (S.mainTab === 'performance') loadPerformance();
      if (S.mainTab === 'log') loadLog();
    });
  });
}

function renderAiHistory() {
  const el = $('ai-messages');
  if (!el) return;
  el.innerHTML = '';
  _aiHistory.forEach(({ role, text }) => {
    const div = document.createElement('div');
    div.className = 'ai-msg ' + role;
    div.textContent = text;
    el.appendChild(div);
  });
  el.scrollTop = el.scrollHeight;
}

function setupCtrlTabs() {
  qsa('.ctrl-tab').forEach(btn => {
    btn.addEventListener('click', () => {
      qsa('.ctrl-tab').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      S.ctrlTab = btn.dataset.ctrl;
      qsa('#ctrl-panel .ctrl-pane').forEach(p => p.classList.add('hidden'));
      const pane = $('ctrl-' + btn.dataset.ctrl);
      if (pane) pane.classList.remove('hidden');
      if (btn.dataset.ctrl === 'ai') renderAiHistory();
    });
  });
}

function setupBtModeTabs() {
  qsa('.bt-mode').forEach(btn => {
    btn.addEventListener('click', () => {
      qsa('.bt-mode').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      S.btMode = btn.dataset.mode;
    });
  });
}

function setupTfButtons() {
  qsa('.tf-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      qsa('.tf-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      S.tf = btn.dataset.tf;
      loadCandles();
      loadTA();
    });
  });
}

function setupLogFilters() {
  ['lf-open','lf-close','lf-hold','lf-skip','lf-error'].forEach(id => {
    const el = $(id);
    if (el) el.addEventListener('change', () => { if (S.mainTab === 'log') loadLog(); });
  });
}

function setupAiProviderChange() {
  const sel = $('set-ai-provider');
  if (sel) sel.addEventListener('change', () => updateAiModelOptions(sel.value));
}

function setupExchangeChange() {
  const sel = $('set-exchange');
  if (sel) sel.addEventListener('change', () => {
    $('okx-pass-row').style.display = sel.value === 'okx' ? '' : 'none';
    // Update exchange status
    const cfg = S.config;
    if (!cfg) return;
    const ex = sel.value;
    const isConn = ex === 'binance' ? cfg.binance_connected : ex === 'bybit' ? cfg.bybit_connected : cfg.okx_connected;
    const row = $('exchange-status-row');
    if (row) row.innerHTML = isConn
      ? '<span class="ex-connected">✓ Bağlı</span>'
      : '<span class="ex-disconnected">○ Bağlı değil</span>';
  });
}

function setupAlertActionChange() {
  const sel = $('alr-action');
  const row = $('alr-amount-row');
  if (sel && row) {
    const update = () => { row.style.display = sel.value === 'bildir' ? 'none' : ''; };
    sel.addEventListener('change', update);
    update();
  }
}

// ── AI Chat ──
const _aiHistory = [];

function aiAddMsg(text, role) {
  _aiHistory.push({ role, text });
  const el = $('ai-messages');
  if (!el) return;
  const div = document.createElement('div');
  div.className = 'ai-msg ' + role;
  div.textContent = text;
  el.appendChild(div);
  el.scrollTop = el.scrollHeight;
  return div;
}

function aiShowSuggestions(suggestions) {
  const el = $('ai-suggestions');
  if (!el || !suggestions.length) return;
  el.innerHTML = suggestions.map((s, i) => {
    const isAction = s.islem !== 'BEKLE';
    const sl = s.zarar_kes ? fmtPrice(s.zarar_kes) : '—';
    const tp = s.kar_al ? fmtPrice(s.kar_al) : '—';
    const rr = s.risk_reward ? s.risk_reward.toFixed(2) + 'x' : '—';
    return `<div class="ai-sug">
      <div class="sug-header">
        <span class="sug-action ${s.islem}">${s.islem} ${s.sembol}</span>
        <span class="sug-conf">%${s.basari_yuzdesi} başarı</span>
      </div>
      <div class="sug-reason">${s.gerekce}</div>
      ${isAction ? `<div class="sug-levels">
        <span>Stop: ${sl}</span>
        <span>Hedef: ${tp}</span>
        <span>R/R: ${rr}</span>
      </div>
      <div class="sug-btns">
        <button class="buy-btn" onclick="aiApprove(${i})">✓ Onayla</button>
        <button class="danger-btn" onclick="aiReject(${i})">✗ Reddet</button>
      </div>` : ''}
    </div>`;
  }).join('');
  el._suggestions = suggestions;
}

async function aiApprove(idx) {
  const el = $('ai-suggestions');
  const sugs = el?._suggestions;
  if (!sugs || !sugs[idx]) return;
  const s = sugs[idx];
  try {
    if (s.islem === 'SAT') {
      await api('POST', '/api/trade/sell', { symbol: s.sembol });
    } else {
      await api('POST', '/api/trade/buy', {
        symbol: s.sembol,
        usdt: s.tutar_usdt || 100,
        stop: s.zarar_kes || undefined,
        target: s.kar_al || undefined,
        style: 'spot',
      });
    }
    toast(s.islem + ' ' + s.sembol + ' onaylandı', 'ok');
    aiAddMsg('✓ ' + s.islem + ' ' + s.sembol + ' emri verildi.', 'ai');
    el.innerHTML = '';
    refreshPortfolio();
  } catch (e) {
    toast('Emir hatası: ' + e.message, 'err');
  }
}

function aiReject(idx) {
  const el = $('ai-suggestions');
  if (el) el.innerHTML = '';
  aiAddMsg('Öneri reddedildi.', 'ai');
}

async function aiSend() {
  const inp = $('ai-input');
  const msg = (inp?.value || '').trim();
  if (!msg) return;
  inp.value = '';
  inp.disabled = true;
  $('btn-ai-send').disabled = true;

  aiAddMsg(msg, 'user');
  $('ai-suggestions').innerHTML = '';
  const loadingEl = aiAddMsg('Düşünüyor...', 'loading');

  try {
    const d = await api('POST', '/api/ai/chat', { message: msg, symbol: S.symbol });
    loadingEl.remove();
    aiAddMsg(d.text || '(yanıt yok)', 'ai');
    if (d.suggestions && d.suggestions.length > 0) {
      aiShowSuggestions(d.suggestions);
    }
  } catch (e) {
    loadingEl.remove();
    aiAddMsg('Hata: ' + e.message, 'err');
  } finally {
    inp.disabled = false;
    $('btn-ai-send').disabled = false;
    inp.focus();
  }
}

function setupAiChat() {
  $('btn-ai-send')?.addEventListener('click', aiSend);
  $('ai-input')?.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); aiSend(); }
  });
}

// ── Mobile hamburger menu ──
function setupMobileMenu() {
  const btn = $('menu-toggle');
  const panel = $('ctrl-panel');
  if (!btn || !panel) return;
  btn.addEventListener('click', () => panel.classList.toggle('mobile-open'));
  // Close when tapping outside
  document.addEventListener('click', e => {
    if (panel.classList.contains('mobile-open') &&
        !panel.contains(e.target) && e.target !== btn) {
      panel.classList.remove('mobile-open');
    }
  });
}

// ── Event bindings ──
function bindEvents() {
  $('btn-buy')?.addEventListener('click', () => placeOrder('buy'));
  $('btn-sell')?.addEventListener('click', () => placeOrder('sell'));
  $('btn-alert')?.addEventListener('click', addAlert);
  $('btn-auto-start')?.addEventListener('click', startAuto);
  $('btn-auto-stop')?.addEventListener('click', stopAuto);
  $('btn-auto-mode')?.addEventListener('click', applyAutoMode);
  $('btn-save-exchange')?.addEventListener('click', saveExchangeSettings);
  $('btn-del-exchange')?.addEventListener('click', deleteExchangeKey);
  $('btn-save-mode')?.addEventListener('click', saveMode);
  $('btn-save-ai')?.addEventListener('click', saveAiSettings);
  $('bt-run')?.addEventListener('click', runBacktest);
  $('set-scalp')?.addEventListener('change', saveToggles);
  $('set-leverage')?.addEventListener('change', saveToggles);
}

// ── Periodic refresh ──
function startPolling() {
  setInterval(() => {
    loadAutoStatus();
    loadConnections();
    if (S.mainTab === 'portfolio') refreshPortfolio();
    if (S.mainTab === 'performance') loadPerformance();
  }, 15000);
  setInterval(() => {
    if (S.mainTab === 'chart') { loadTA(); loadSpread(); }
  }, 30000);
}

async function fetchInitialPrices() {
  try {
    const syms = WATCHLIST.join(',');
    const d = await api('GET', `/api/prices?symbols=${encodeURIComponent(syms)}`);
    if (d.prices) Object.assign(S.prices, d.prices);
    if (d.changes) Object.assign(S.changes, d.changes);
    updateWatchlistPrices();
    const p = S.prices[S.symbol];
    if (p) updateTopTicker(S.symbol, p, S.changes[S.symbol] || 0);
  } catch (_) {}
}

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
  setupNavTabs();
  setupCtrlTabs();
  setupBtModeTabs();
  setupTfButtons();
  setupSearch();
  setupLogFilters();
  setupAiProviderChange();
  setupExchangeChange();
  setupAlertActionChange();
  setupAiChat();
  setupMobileMenu();
  setupTradePlanButtons();
  bindEvents();

  initChart();
  loadConfig();
  loadAutoStatus();
  loadConnections();
  renderWatchlist();
  fetchInitialPrices();
  loadTA();
  loadAlerts();
  connectWS();
  startPolling();
});
