"""Tracker (öneri performans takibi) testleri."""
import json
import time

import pytest

from tracker import MIN_SAMPLES, PENDING_TTL, Recommendation, Tracker


def make_item(symbol="BTCUSDT", side="AL", amount=500.0, conf=60,
              reason="test", entry=100.0):
    return {"symbol": symbol, "side": side, "suggested_amount": amount,
            "confidence_percent": conf, "reason": reason, "entry_price": entry}


@pytest.fixture
def tracker(tmp_path):
    return Tracker(path=tmp_path / "recommendations.json")


# ---------- kayıt ve durum ----------

def test_add_creates_pending_records(tracker):
    recs = tracker.add([make_item(), make_item(symbol="GC=F")])
    assert len(recs) == 2
    assert all(r.status == "pending" for r in recs)
    assert all(r.id for r in recs)
    # alanlar spec'e uygun
    r = recs[0]
    assert r.symbol == "BTCUSDT" and r.side == "AL"
    assert r.suggested_amount == 500.0 and r.confidence_percent == 60
    assert r.reason == "test" and r.entry_price == 100.0
    assert r.timestamp > 0


def test_add_persists_to_json(tracker):
    tracker.add([make_item()])
    data = json.loads(tracker.path.read_text())
    assert len(data) == 1
    assert data[0]["status"] == "pending"
    assert set(data[0]) == {"id", "timestamp", "symbol", "side", "suggested_amount",
                            "confidence_percent", "reason", "entry_price", "status"}


def test_new_scan_expires_old_pending(tracker):
    old = tracker.add([make_item()])
    new = tracker.add([make_item(symbol="ETHUSDT")])
    assert tracker.recs[0].status == "expired"
    assert tracker.recs[1].status == "pending"
    assert old[0].id != new[0].id


def test_approve_and_reject_only_affect_pending(tracker):
    recs = tracker.add([make_item(), make_item(symbol="GC=F"), make_item(symbol="ETHUSDT")])
    tracker.set_status([recs[0].id], "approved")
    tracker.set_status([recs[1].id], "rejected")
    assert tracker.recs[0].status == "approved"
    assert tracker.recs[1].status == "rejected"
    assert tracker.recs[2].status == "pending"
    # approved olan tekrar rejected yapılamaz
    tracker.set_status([recs[0].id], "rejected")
    assert tracker.recs[0].status == "approved"


def test_load_expires_stale_pending(tmp_path):
    path = tmp_path / "recommendations.json"
    t = Tracker(path=path)
    recs = t.add([make_item()])
    # kaydı 25 saat geriye çek
    recs[0].timestamp = time.time() - PENDING_TTL - 3600
    t.save()
    t2 = Tracker.load(path)
    assert t2.recs[0].status == "expired"


def test_load_roundtrip(tmp_path):
    path = tmp_path / "recommendations.json"
    t = Tracker(path=path)
    t.add([make_item(symbol="GC=F", side="SAT", conf=55)])
    t2 = Tracker.load(path)
    assert len(t2.recs) == 1
    r = t2.recs[0]
    assert isinstance(r, Recommendation)
    assert r.symbol == "GC=F" and r.side == "SAT" and r.confidence_percent == 55


# ---------- PnL ve istatistik ----------

def test_pnl_direction_al_and_sat():
    al = Recommendation("x", 0, "BTCUSDT", "AL", 1000, 60, "", entry_price=100)
    sat = Recommendation("y", 0, "BTCUSDT", "SAT", 1000, 60, "", entry_price=100)
    assert Tracker.pnl_of(al, 110) == pytest.approx(100)    # %10 yukarı → +100
    assert Tracker.pnl_of(al, 90) == pytest.approx(-100)
    assert Tracker.pnl_of(sat, 90) == pytest.approx(100)    # SAT sonrası düşüş → kazanç
    assert Tracker.pnl_of(sat, 110) == pytest.approx(-100)


def test_stats_counts_and_pnl(tracker):
    recs = tracker.add([
        make_item(symbol="WIN", entry=100, amount=1000),   # fiyat 110 → +100 kazanan
        make_item(symbol="LOSE", entry=100, amount=500),   # fiyat 90  → -50 kaybeden
        make_item(symbol="SKIP", entry=100),               # fiyatı yok → sayılmaz
    ])
    tracker.set_status([r.id for r in recs], "approved")
    tracker.add([make_item(symbol="REJ")])  # pending kalan; bir tane de reddet
    rej = tracker.recs[-1]
    tracker.set_status([rej.id], "rejected")

    st = tracker.stats({"WIN": 110, "LOSE": 90})
    assert st["toplam_oneri"] == 4
    assert st["onaylanan"] == 3
    assert st["reddedilen"] == 1
    assert st["kazanan"] == 1
    assert st["kaybeden"] == 1
    assert st["toplam_pnl"] == pytest.approx(50)  # +100 - 50
    assert st["basari_orani"] == pytest.approx(50)


def test_stats_empty(tracker):
    st = tracker.stats({})
    assert st["toplam_oneri"] == 0
    assert st["basari_orani"] is None
    assert st["toplam_pnl"] == 0


# ---------- kalibrasyon ----------

def _seed_history(tracker, wins: int, losses: int):
    """Geçmişe wins kazanan + losses kaybeden onaylanmış öneri ekle."""
    items = [make_item(symbol=f"W{i}", entry=100) for i in range(wins)]
    items += [make_item(symbol=f"L{i}", entry=100) for i in range(losses)]
    recs = tracker.add(items)
    tracker.set_status([r.id for r in recs], "approved")
    prices = {f"W{i}": 110 for i in range(wins)}
    prices.update({f"L{i}": 90 for i in range(losses)})
    return prices


def test_calibrate_needs_min_samples(tracker):
    prices = _seed_history(tracker, wins=2, losses=2)  # 4 < MIN_SAMPLES
    assert tracker.calibrate(70, prices) == 70


def test_calibrate_lowers_when_history_is_bad(tracker):
    prices = _seed_history(tracker, wins=2, losses=8)  # isabet %20
    cal = tracker.calibrate(70, prices)
    assert cal == round((70 + 20) / 2) == 45


def test_calibrate_never_raises_above_stated(tracker):
    prices = _seed_history(tracker, wins=10, losses=0)  # isabet %100
    # geçmiş mükemmel bile olsa beyan yukarı çekilmez (temkinli tek yön)
    assert tracker.calibrate(55, prices) == 55


def test_calibrate_excludes_pending(tracker):
    prices = _seed_history(tracker, wins=MIN_SAMPLES, losses=0)
    tracker.add([make_item(symbol="FRESH", entry=100)])  # pending, taze
    prices["FRESH"] = 100  # fiyat oynamadı; dahil edilse kaybeden sayılırdı
    rate, n = tracker.win_rate(prices)
    assert n == MIN_SAMPLES  # FRESH dahil edilmedi
    assert rate == pytest.approx(100)
