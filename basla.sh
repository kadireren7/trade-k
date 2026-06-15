#!/usr/bin/env bash
# trade-k başlatıcı — otomatik yeniden başlatma (watchdog) destekli

cd "$(dirname "$0")"

MAX_RESTARTS=5
RESTART_COUNT=0
BACKOFF=5

while true; do
    .venv/bin/python app.py
    EXIT_CODE=$?

    # Kod 0: kullanıcı uygulamayı normal kapattı
    if [ "$EXIT_CODE" -eq 0 ]; then
        echo "[trade-k] Normal çıkış."
        break
    fi

    RESTART_COUNT=$((RESTART_COUNT + 1))
    if [ "$RESTART_COUNT" -gt "$MAX_RESTARTS" ]; then
        echo "[trade-k] Maksimum yeniden başlatma sayısına ulaşıldı ($MAX_RESTARTS). Durduruluyor."
        exit 1
    fi

    echo "[trade-k] Çöktü (kod $EXIT_CODE). ${BACKOFF}s sonra yeniden başlatılıyor... ($RESTART_COUNT/$MAX_RESTARTS)"
    sleep "$BACKOFF"
    BACKOFF=$((BACKOFF * 2))
    if [ "$BACKOFF" -gt 120 ]; then
        BACKOFF=120
    fi
done
