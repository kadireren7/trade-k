#!/usr/bin/env bash
# trade-k Web UI başlatıcı
cd "$(dirname "$0")"
echo "[trade-k] Web UI başlatılıyor → http://localhost:8765"
exec .venv/bin/uvicorn api:app --host 0.0.0.0 --port 8765 --reload
