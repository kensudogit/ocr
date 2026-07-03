#!/bin/sh
# start.sh — launch FastAPI (127.0.0.1:8000) + Next.js ($PORT) in one container
set -e

echo "=== OCR PoC startup ==="
echo "PORT=${PORT:-3000}"

# ── FastAPI backend ─────────────────────────────────────────────────
cd /api
echo "Starting uvicorn..."
/venv/bin/uvicorn src.main:app --host 127.0.0.1 --port 8000 --log-level info &
BACKEND_PID=$!

# ── Next.js frontend ────────────────────────────────────────────────
cd /frontend
echo "Starting Next.js on port ${PORT:-3000}..."
HOSTNAME=0.0.0.0 PORT="${PORT:-3000}" BACKEND_INTERNAL_URL="http://127.0.0.1:8000" node server.js &
FRONTEND_PID=$!

echo "Backend PID=$BACKEND_PID  Frontend PID=$FRONTEND_PID"

wait $BACKEND_PID $FRONTEND_PID
