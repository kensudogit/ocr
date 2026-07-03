#!/bin/sh
# start.sh — FastAPI (127.0.0.1:8000) background + Next.js ($PORT) foreground
#
# Design:
#   - Next.js runs in the FOREGROUND as the main process (PID 1 equivalent).
#     Railway monitors it via healthcheckPath="/". The container lives as long
#     as Next.js lives.
#   - uvicorn runs in the BACKGROUND with an auto-restart loop so a transient
#     Python crash does NOT bring down the whole container.
#   - No `set -e` — we want the container to keep running even if the backend
#     has a brief startup error.

echo "=== OCR PoC startup ==="
echo "PORT=${PORT:-3000}"
echo "PWD=$(pwd)"

# ── FastAPI backend (background, auto-restart on crash) ──────────────────────
_run_backend() {
  while true; do
    echo "[backend] Starting uvicorn on 127.0.0.1:8000 ..."
    cd /api
    /venv/bin/uvicorn src.main:app \
      --host 127.0.0.1 \
      --port 8000 \
      --log-level info \
      --workers 1
    CODE=$?
    echo "[backend] uvicorn exited (code=${CODE}). Restarting in 5s ..."
    sleep 5
  done
}
_run_backend &

# Give the backend a few seconds to initialise before Next.js starts forwarding
# API proxy requests (avoids 502 on the very first health-check page load).
echo "[startup] Waiting 5s for backend to initialise ..."
sleep 5

# ── Next.js frontend (foreground — Railway health check hits this process) ───
echo "[frontend] Starting Next.js on port ${PORT:-3000} ..."
cd /frontend
exec env \
  HOSTNAME=0.0.0.0 \
  PORT="${PORT:-3000}" \
  BACKEND_INTERNAL_URL="http://127.0.0.1:8000" \
  node server.js
