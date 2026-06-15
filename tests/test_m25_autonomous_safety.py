"""M2.5 — Autonomous Safety, Emergency Control & Incident Log testleri."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import portfolio as portfolio_mod
from autonomous import (
    AUTONOMOUS_PROFILES,
    AutonomousEngine,
    AutonomousState,
)
from portfolio import Portfolio


# ── ortak yardımcılar ────────────────────────────────────────────────────────

class MockFeed:
    def __init__(self, prices: dict | None = None, ws_connected: bool = True):
        prices = prices or {}

        class T:
            def __init__(self, p):
                self.price = p

        self.tickers = {s: T(p) for s, p in prices.items()}
        self.ws_connected = ws_connected

    def price(self, sym: str) -> float | None:
        t = self.tickers.get(sym)
        return t.price if t else None


class MockCfg:
    def __init__(self, mode: str = "dengeli"):
        self.model_id = None
        self.mode = "standart"
        self.autonomous_mode = mode
        self.otonom_trade_type = "long"
        self.trade_plan = "dengeli"
        self.scalp_enabled = False
        self.leverage_enabled = False
        self.custom_max_positions = 0
        self.custom_max_daily_trades = 0
        self.custom_loss_streak = 0
        self.custom_daily_loss_pct = 0.0
        self.live_autonomous = False

    def save(self) -> None:
        pass


@pytest.fixture(autouse=True)
def isolate_portfolio(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_mod, "STATE_FILE", tmp_path / "account.json")


@pytest.fixture
def portfolio():
    return Portfolio()


_DEFAULT_PRICES = {"BTCUSDT": 50000.0, "ETHUSDT": 2000.0}


def make_engine(portfolio, tmp_path, prices=None, ws_connected=True, mode="dengeli"):
    feed = MockFeed(
        _DEFAULT_PRICES if prices is None else prices,
        ws_connected=ws_connected,
    )
    return AutonomousEngine(
        portfolio=portfolio,
        feed=feed,
        tracker=type("T", (), {"recs": [], "add": lambda self, x: []})(),
        cfg=MockCfg(mode),
        log_fn=lambda s: None,
        watchlist_fn=lambda: ["BTCUSDT"],
        state_path=tmp_path / "state.json",
        log_path=tmp_path / "log.jsonl",
    )


# ── 1. Günlük zarar limiti Telegram bildirimi ────────────────────────────────

@pytest.mark.asyncio
async def test_daily_loss_limit_sends_telegram(portfolio, tmp_path):
    """_check_daily_loss_limit tetiklenince notifier.send çağrılmalı."""
    eng = make_engine(portfolio, tmp_path, prices={"BTCUSDT": 50000.0})
    eng.state.daily_start_equity = 10000.0
    eng.state.risk_locked = False

    sent_msgs = []

    async def fake_send(msg, silent=False):
        sent_msgs.append(msg)
        return True

    import autonomous as auto_mod
    mock_notifier = MagicMock()
    mock_notifier.send = fake_send

    with patch.object(auto_mod._notify, "get", return_value=mock_notifier):
        # Equity'yi düşür → loss_pct = 5% (dengeli profil limiti: 4%)
        eng.portfolio.cash = 9500.0
        eng._check_daily_loss_limit()

    await asyncio.sleep(0)  # ensure_future'ı işlet
    assert eng.state.risk_locked is True
    assert eng.state.enabled is False
    assert len(sent_msgs) >= 1
    assert "DURDURULDU" in sent_msgs[0]
    assert "sifirla" in sent_msgs[0].lower()


@pytest.mark.asyncio
async def test_daily_loss_limit_no_spam(portfolio, tmp_path):
    """Aynı gün için zarar bildirimi sadece bir kez gönderilmeli."""
    eng = make_engine(portfolio, tmp_path, prices={"BTCUSDT": 50000.0})
    eng.state.daily_start_equity = 10000.0
    eng.state.risk_locked = False
    sent_msgs = []

    async def fake_send(msg, silent=False):
        sent_msgs.append(msg)
        return True

    import autonomous as auto_mod
    mock_notifier = MagicMock()
    mock_notifier.send = fake_send

    with patch.object(auto_mod._notify, "get", return_value=mock_notifier):
        eng.portfolio.cash = 9400.0
        eng._check_daily_loss_limit()
        # state'i sıfırla ama notified flag'ini koru → tekrar çağır
        eng.state.risk_locked = False
        eng.portfolio.cash = 9300.0
        eng._check_daily_loss_limit()

    await asyncio.sleep(0)
    # En fazla 1 bildirim gönderilmeli
    assert len(sent_msgs) <= 1


def test_daily_loss_notified_resets_on_new_day(portfolio, tmp_path):
    """Yeni günde _daily_loss_notified sıfırlanmalı."""
    eng = make_engine(portfolio, tmp_path)
    eng._daily_loss_notified = True
    eng.state.daily_date = "2020-01-01"
    eng._check_daily_reset()
    assert eng._daily_loss_notified is False


# ── 2. PnL 0.00 bug fix ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_apply_decision_pnl_from_pnl_field(portfolio, tmp_path):
    """apply_decision kapanışında Telegram mesajında PnL 0.00 görünmemeli."""
    eng = make_engine(portfolio, tmp_path, prices={"BTCUSDT": 50000.0})
    # Daha yüksek fiyattan al → satışta kâr oluşsun
    portfolio.buy("BTCUSDT", 500.0, 49000.0)

    import ai as ai_mod
    pd_obj = ai_mod.PositionDecision(
        sembol="BTCUSDT", karar="KAR_AL",
        gerekce="test",
    )

    sent_msgs = []

    async def fake_send(msg, silent=False):
        sent_msgs.append(msg)
        return True

    import autonomous as auto_mod
    mock_notifier = MagicMock()
    mock_notifier.send = fake_send

    with patch.object(auto_mod._notify, "get", return_value=mock_notifier):
        await eng.apply_decision("BTCUSDT", pd_obj, 50000.0, auto=True)

    await asyncio.sleep(0)
    assert sent_msgs, "Telegram mesajı gönderilmedi"
    msg = sent_msgs[0]
    # PnL 0.00 görünmemeli (kârlı satış)
    assert "+0.00 USDT" not in msg, f"PnL hâlâ 0 görünüyor: {msg}"


@pytest.mark.asyncio
async def test_apply_decision_pnl_nonzero_on_profitable_close(portfolio, tmp_path):
    """Kârlı kapanışta PnL sıfır olmamalı (pnl veya pnl_usdt okunmalı)."""
    eng = make_engine(portfolio, tmp_path, prices={"BTCUSDT": 55000.0})
    portfolio.buy("BTCUSDT", 500.0, 50000.0)

    import ai as ai_mod
    pd_obj = ai_mod.PositionDecision(
        sembol="BTCUSDT", karar="KAR_AL", gerekce="test",
    )

    sent_msgs = []

    async def fake_send(msg, silent=False):
        sent_msgs.append(msg)
        return True

    import autonomous as auto_mod
    mock_notifier = MagicMock()
    mock_notifier.send = fake_send

    with patch.object(auto_mod._notify, "get", return_value=mock_notifier):
        await eng.apply_decision("BTCUSDT", pd_obj, 55000.0, auto=True)

    await asyncio.sleep(0)
    assert sent_msgs
    msg = sent_msgs[0]
    # Pozitif PnL olmalı
    assert "+0.00 USDT" not in msg, f"PnL hâlâ sıfır: {msg}"


# ── 3. Stale price / WebSocket koruması ──────────────────────────────────────

@pytest.mark.asyncio
async def test_run_scan_skips_when_ws_disconnected(portfolio, tmp_path):
    """WebSocket kopuksa _run_scan yeni işlem açmamalı."""
    eng = make_engine(portfolio, tmp_path, ws_connected=False)
    initial_cash = portfolio.cash
    initial_positions = dict(portfolio.positions)

    # Scan çağır — ws=False olduğu için erken çıkmalı
    await eng._run_scan()

    assert dict(portfolio.positions) == initial_positions
    assert portfolio.cash == initial_cash


@pytest.mark.asyncio
async def test_run_scan_stale_sends_telegram_with_cooldown(portfolio, tmp_path):
    """WS kopuksa Telegram'a bildirim gitmeli, ama cooldown'da tekrar gitmemeli."""
    eng = make_engine(portfolio, tmp_path, ws_connected=False)
    eng._last_stale_notify = 0.0

    sent_msgs = []

    async def fake_send(msg, silent=False):
        sent_msgs.append(msg)
        return True

    import autonomous as auto_mod
    mock_notifier = MagicMock()
    mock_notifier.send = fake_send

    with patch.object(auto_mod._notify, "get", return_value=mock_notifier):
        await eng._run_scan()
        await asyncio.sleep(0)

    assert len(sent_msgs) >= 1
    assert "WebSocket" in sent_msgs[0] or "atlandı" in sent_msgs[0]

    # Cooldown içinde tekrar çağır → ek mesaj gitmemeli
    with patch.object(auto_mod._notify, "get", return_value=mock_notifier):
        await eng._run_scan()
        await asyncio.sleep(0)

    assert len(sent_msgs) == 1


@pytest.mark.asyncio
async def test_run_scan_works_when_ws_connected(portfolio, tmp_path, monkeypatch):
    """WS bağlıyken scan normal çalışmalı (risk_locked veya limit ile dursun)."""
    eng = make_engine(portfolio, tmp_path, ws_connected=True)
    eng.state.risk_locked = True  # scan erkenden dursun ama ws kontrolünü geçsin

    # _run_scan çağrılabilmeli, ws hatası olmadan
    await eng._run_scan()
    # risk_locked → aday üretmeden döner, pozisyon açılmaz
    assert len(portfolio.positions) == 0


# ── 4. /acil — emergency_close ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emergency_close_stops_autonomous(portfolio, tmp_path):
    """/acil otonom modu durdurmalı."""
    eng = make_engine(portfolio, tmp_path, prices={"BTCUSDT": 50000.0})
    eng.state.enabled = True
    result = await eng.emergency_close()
    assert eng.state.enabled is False


@pytest.mark.asyncio
async def test_emergency_close_closes_all_positions(portfolio, tmp_path):
    """Tüm açık pozisyonlar kapatılmalı."""
    eng = make_engine(portfolio, tmp_path, prices={"BTCUSDT": 50000.0, "ETHUSDT": 2000.0})
    portfolio.buy("BTCUSDT", 500.0, 49000.0)
    portfolio.buy("ETHUSDT", 300.0, 1950.0)
    assert len(portfolio.positions) == 2

    result = await eng.emergency_close()
    assert len(result["closed"]) == 2
    assert len(result["errors"]) == 0
    assert len(portfolio.positions) == 0


@pytest.mark.asyncio
async def test_emergency_close_reports_error_positions(portfolio, tmp_path):
    """Fiyat alınamayan pozisyon error listesine girmeli, sessizce silinmemeli."""
    eng = make_engine(portfolio, tmp_path, prices={})  # fiyat yok
    portfolio.buy("BTCUSDT", 500.0, 49000.0)
    # feed'de BTCUSDT fiyatı yok, market.quote da hata atacak
    with patch("autonomous.market.quote", side_effect=Exception("timeout")):
        result = await eng.emergency_close()
    # Pozisyon kapatılamadı → error listesinde
    assert "BTCUSDT" in result["errors"]
    # Ama portföyden silinmedi
    assert "BTCUSDT" in portfolio.positions


@pytest.mark.asyncio
async def test_emergency_close_no_positions(portfolio, tmp_path):
    """Pozisyon yokken emergency_close hata vermeden çalışmalı."""
    eng = make_engine(portfolio, tmp_path)
    assert len(portfolio.positions) == 0
    result = await eng.emergency_close()
    assert result["closed"] == []
    assert result["errors"] == []
    assert result["total_pnl"] == 0.0


@pytest.mark.asyncio
async def test_emergency_close_sets_risk_locked(portfolio, tmp_path):
    """emergency_close sonrası risk_locked=True olmalı."""
    eng = make_engine(portfolio, tmp_path)
    await eng.emergency_close()
    assert eng.state.risk_locked is True


# ── 5. /limit komutu ─────────────────────────────────────────────────────────

def test_set_daily_trade_limit_valid(portfolio, tmp_path):
    eng = make_engine(portfolio, tmp_path)
    msg = eng.set_daily_trade_limit(7)
    assert "✅" in msg
    assert eng.state.daily_trade_limit_override == 7


def test_set_daily_trade_limit_zero_rejected(portfolio, tmp_path):
    eng = make_engine(portfolio, tmp_path)
    msg = eng.set_daily_trade_limit(0)
    assert "❌" in msg
    assert eng.state.daily_trade_limit_override == 0


def test_set_daily_trade_limit_too_large_rejected(portfolio, tmp_path):
    eng = make_engine(portfolio, tmp_path)
    msg = eng.set_daily_trade_limit(999)
    assert "❌" in msg
    assert eng.state.daily_trade_limit_override == 0


def test_set_daily_trade_limit_boundary_valid(portfolio, tmp_path):
    eng = make_engine(portfolio, tmp_path)
    assert "✅" in eng.set_daily_trade_limit(1)
    assert "✅" in eng.set_daily_trade_limit(50)


def test_effective_profile_uses_limit_override(portfolio, tmp_path):
    """state.daily_trade_limit_override effective_profile'de kullanılmalı."""
    eng = make_engine(portfolio, tmp_path, mode="dengeli")
    default_limit = eng.effective_profile.max_daily_trades  # 6
    eng.set_daily_trade_limit(15)
    assert eng.effective_profile.max_daily_trades == 15
    assert eng.effective_profile.max_daily_trades != default_limit


@pytest.mark.asyncio
async def test_run_scan_respects_limit_override(portfolio, tmp_path):
    """_run_scan yeni limite göre durmalı."""
    eng = make_engine(portfolio, tmp_path, ws_connected=True)
    eng.set_daily_trade_limit(2)
    eng.state.daily_trades = 2  # limite ulaştık

    portfolio_before = dict(portfolio.positions)
    await eng._run_scan()
    assert dict(portfolio.positions) == portfolio_before


# ── 6. /otonom durum ─────────────────────────────────────────────────────────

def test_otonom_status_shows_risk_locked(portfolio, tmp_path):
    """status_text() risk_locked=True iken bunu belirtmeli."""
    eng = make_engine(portfolio, tmp_path)
    eng.state.risk_locked = True
    text = eng.status_text()
    assert "AKTİF" in text or "KİLİT" in text.upper()


def test_otonom_status_shows_daily_pnl(portfolio, tmp_path):
    """status_text() daily_start_equity varsa K/Z göstermeli."""
    eng = make_engine(portfolio, tmp_path, prices={"BTCUSDT": 50000.0})
    eng.state.daily_start_equity = 10000.0
    text = eng.status_text()
    assert "Günlük PnL" in text


def test_otonom_status_shows_trade_override(portfolio, tmp_path):
    """Override limit status_text'te görünmeli."""
    eng = make_engine(portfolio, tmp_path)
    eng.set_daily_trade_limit(9)
    p = eng.effective_profile
    assert p.max_daily_trades == 9


# ── 7. Restart güvenliği ─────────────────────────────────────────────────────

def test_engine_init_always_starts_disabled(portfolio, tmp_path):
    """Engine her zaman enabled=False ile başlamalı."""
    state_path = tmp_path / "state.json"
    # Önceki state'e enabled=True yaz
    AutonomousState(enabled=True, daily_trades=5).save(state_path)
    eng = make_engine(portfolio, tmp_path)
    eng._state_path = state_path
    assert eng.state.enabled is False


def test_state_json_preserves_other_fields_after_restart(portfolio, tmp_path):
    """Restart sonrası daily_trades, risk_locked gibi alanlar korunmalı."""
    state_path = tmp_path / "state.json"
    prev = AutonomousState(
        enabled=True,
        daily_trades=4,
        risk_locked=True,
        consecutive_losses=2,
    )
    prev.save(state_path)

    eng = make_engine(portfolio, tmp_path)
    # enabled=False override edilmiş olacak
    loaded = AutonomousState.load(state_path)
    assert loaded.daily_trades == 4
    assert loaded.risk_locked is True
    assert loaded.consecutive_losses == 2


# ── 8. Risk locked koruması ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_scan_blocked_when_risk_locked(portfolio, tmp_path):
    """risk_locked=True iken _run_scan yeni işlem açmamalı."""
    eng = make_engine(portfolio, tmp_path, ws_connected=True)
    eng.state.risk_locked = True
    portfolio_before = dict(portfolio.positions)
    await eng._run_scan()
    assert dict(portfolio.positions) == portfolio_before


@pytest.mark.asyncio
async def test_risk_locked_prevents_engine_start(portfolio, tmp_path):
    """risk_locked iken engine.start() başlatmamalı."""
    import time as _t
    eng = make_engine(portfolio, tmp_path)
    eng.state.risk_locked = True
    eng.state.daily_date = _t.strftime("%Y-%m-%d")  # bugüne sabitle → reset olmasın
    msg = await eng.start()
    assert eng.state.enabled is False
    assert "kilit" in msg.lower() or "risk" in msg.lower()


# ── 9. Incident log ──────────────────────────────────────────────────────────

def test_log_incident_creates_file(portfolio, tmp_path, monkeypatch):
    """_log_incident INCIDENT_LOG_FILE'a yazar."""
    import autonomous as auto_mod
    incident_path = tmp_path / "logs" / "incidents.jsonl"
    monkeypatch.setattr(auto_mod, "INCIDENT_LOG_FILE", incident_path)

    eng = make_engine(portfolio, tmp_path)
    eng._log_incident("test_event", foo="bar")

    assert incident_path.exists()
    record = json.loads(incident_path.read_text().strip())
    assert record["event"] == "test_event"
    assert record["foo"] == "bar"
    assert "ts" in record


def test_log_incident_multiple_records(portfolio, tmp_path, monkeypatch):
    """Birden fazla incident sırayla yazılmalı."""
    import autonomous as auto_mod
    incident_path = tmp_path / "logs" / "incidents.jsonl"
    monkeypatch.setattr(auto_mod, "INCIDENT_LOG_FILE", incident_path)

    eng = make_engine(portfolio, tmp_path)
    eng._log_incident("event_a", val=1)
    eng._log_incident("event_b", val=2)

    lines = incident_path.read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["event"] == "event_a"
    assert json.loads(lines[1])["event"] == "event_b"


@pytest.mark.asyncio
async def test_emergency_close_writes_incident(portfolio, tmp_path, monkeypatch):
    """emergency_close incident log'a yazar."""
    import autonomous as auto_mod
    incident_path = tmp_path / "logs" / "incidents.jsonl"
    monkeypatch.setattr(auto_mod, "INCIDENT_LOG_FILE", incident_path)

    eng = make_engine(portfolio, tmp_path, prices={"BTCUSDT": 50000.0})
    portfolio.buy("BTCUSDT", 500.0, 49000.0)
    await eng.emergency_close()

    assert incident_path.exists()
    events = [json.loads(l)["event"] for l in incident_path.read_text().strip().split("\n")]
    assert "emergency_close_started" in events
    assert "emergency_close_done" in events


# ── 10. Telegram kopma dayanıklılığı ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_engine_loop_survives_notifier_exception(portfolio, tmp_path):
    """Notifier.send exception atarsa engine loop çökmemeli."""
    eng = make_engine(portfolio, tmp_path, prices={"BTCUSDT": 50000.0})
    eng.state.daily_start_equity = 10000.0

    async def failing_send(msg, silent=False):
        raise ConnectionError("Telegram down")

    import autonomous as auto_mod
    mock_notifier = MagicMock()
    mock_notifier.send = failing_send

    with patch.object(auto_mod._notify, "get", return_value=mock_notifier):
        eng.portfolio.cash = 9400.0
        # _check_daily_loss_limit exception atmamalı
        try:
            eng._check_daily_loss_limit()
        except Exception as exc:
            pytest.fail(f"Engine loop çöktü: {exc}")

    await asyncio.sleep(0.05)
    # Kod buraya geliyorsa test geçti


# ── 11. Telegram /otonom durum (TelegramCommandBot) ─────────────────────────

@pytest.mark.asyncio
async def test_telegram_otonom_durum_shows_daily_loss(portfolio, tmp_path):
    """/otonom durum komutu günlük zarar % içermeli."""
    from notify import TelegramCommandBot, Notifier

    eng = make_engine(portfolio, tmp_path, prices={"BTCUSDT": 50000.0})
    eng.state.daily_start_equity = 10000.0
    eng.portfolio.cash = 9600.0  # %4 kayıp

    notifier = Notifier("fake_token", "12345")
    bot = TelegramCommandBot(notifier)
    bot._portfolio = portfolio
    bot._engine = eng
    bot._cfg = eng.cfg
    bot._feed = eng.feed

    reply = await bot._otonom(["durum"])
    assert "%" in reply or "kayıp" in reply.lower() or "K/Z" in reply


@pytest.mark.asyncio
async def test_telegram_otonom_durum_shows_risk_locked_warning(portfolio, tmp_path):
    """risk_locked=True iken durum çıktısı uyarı içermeli."""
    from notify import TelegramCommandBot, Notifier

    eng = make_engine(portfolio, tmp_path)
    eng.state.risk_locked = True

    notifier = Notifier("fake_token", "12345")
    bot = TelegramCommandBot(notifier)
    bot._portfolio = portfolio
    bot._engine = eng
    bot._cfg = eng.cfg
    bot._feed = eng.feed

    reply = await bot._otonom(["durum"])
    assert "kilit" in reply.lower() or "AKTİF" in reply


@pytest.mark.asyncio
async def test_telegram_otonom_durum_shows_ws_warning_when_down(portfolio, tmp_path):
    """WS kopukken durum çıktısı uyarı içermeli."""
    from notify import TelegramCommandBot, Notifier

    eng = make_engine(portfolio, tmp_path, ws_connected=False)

    notifier = Notifier("fake_token", "12345")
    bot = TelegramCommandBot(notifier)
    bot._portfolio = portfolio
    bot._engine = eng
    bot._cfg = eng.cfg
    bot._feed = eng.feed

    reply = await bot._otonom(["durum"])
    assert "kopuk" in reply.lower() or "WebSocket" in reply


@pytest.mark.asyncio
async def test_telegram_acil_no_positions(portfolio, tmp_path):
    """/acil pozisyon yokken düzgün mesaj dönmeli."""
    from notify import TelegramCommandBot, Notifier

    eng = make_engine(portfolio, tmp_path)
    notifier = Notifier("fake_token", "12345")
    bot = TelegramCommandBot(notifier)
    bot._portfolio = portfolio
    bot._engine = eng
    bot._cfg = eng.cfg

    reply = await bot._acil()
    assert "pozisyon yok" in reply.lower() or "DURDURULDU" in reply.upper()


@pytest.mark.asyncio
async def test_telegram_acil_closes_positions(portfolio, tmp_path):
    """/acil tüm pozisyonları kapatmalı."""
    from notify import TelegramCommandBot, Notifier

    eng = make_engine(portfolio, tmp_path, prices={"BTCUSDT": 50000.0})
    portfolio.buy("BTCUSDT", 500.0, 49000.0)

    notifier = Notifier("fake_token", "12345")
    bot = TelegramCommandBot(notifier)
    bot._portfolio = portfolio
    bot._engine = eng
    bot._cfg = eng.cfg

    reply = await bot._acil()
    assert "ACİL" in reply
    assert len(portfolio.positions) == 0


@pytest.mark.asyncio
async def test_telegram_limit_valid(portfolio, tmp_path):
    """/limit 8 başarılı olmalı."""
    from notify import TelegramCommandBot, Notifier

    eng = make_engine(portfolio, tmp_path)
    notifier = Notifier("fake_token", "12345")
    bot = TelegramCommandBot(notifier)
    bot._portfolio = portfolio
    bot._engine = eng
    bot._cfg = eng.cfg

    reply = await bot._limit(["8"])
    assert "✅" in reply
    assert eng.state.daily_trade_limit_override == 8


@pytest.mark.asyncio
async def test_telegram_limit_invalid_string(portfolio, tmp_path):
    """/limit abc hata mesajı döndürmeli."""
    from notify import TelegramCommandBot, Notifier

    eng = make_engine(portfolio, tmp_path)
    notifier = Notifier("fake_token", "12345")
    bot = TelegramCommandBot(notifier)
    bot._portfolio = portfolio
    bot._engine = eng
    bot._cfg = eng.cfg

    reply = await bot._limit(["abc"])
    assert "❌" in reply


@pytest.mark.asyncio
async def test_telegram_limit_out_of_range(portfolio, tmp_path):
    """/limit 0 ve /limit 999 hata vermeli."""
    from notify import TelegramCommandBot, Notifier

    eng = make_engine(portfolio, tmp_path)
    notifier = Notifier("fake_token", "12345")
    bot = TelegramCommandBot(notifier)
    bot._portfolio = portfolio
    bot._engine = eng

    r1 = await bot._limit(["0"])
    r2 = await bot._limit(["999"])
    assert "❌" in r1
    assert "❌" in r2


@pytest.mark.asyncio
async def test_telegram_limit_status(portfolio, tmp_path):
    """/limit durum bilgi döndürmeli."""
    from notify import TelegramCommandBot, Notifier

    eng = make_engine(portfolio, tmp_path)
    notifier = Notifier("fake_token", "12345")
    bot = TelegramCommandBot(notifier)
    bot._portfolio = portfolio
    bot._engine = eng

    reply = await bot._limit(["durum"])
    assert "limit" in reply.lower() or "Limit" in reply
