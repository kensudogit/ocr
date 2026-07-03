#!/bin/sh
# start.sh — launch FastAPI backend + Next.js frontend in a single container
# NOTE: This file must have LF (Unix) line endings. Do NOT convert to CRLF.

echo "[start.sh] ============================================"
echo "[start.sh] OCR System starting up..."
echo "[start.sh] PORT=${PORT:-3000}"
echo "[start.sh] ============================================"

# ── FastAPI backend on internal port 8000 ──────────────────────────────
echo "[start.sh] Starting FastAPI backend (uvicorn on 127.0.0.1:8000)..."
cd /api

# Run uvicorn; redirect output so it appears in Railway logs
/venv/bin/uvicorn src.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --log-level info \
  2>&1 &

BACKEND_PID=$!
echo "[start.sh] Backend PID: $BACKEND_PID"

# ── Next.js frontend on Railway's public PORT ──────────────────────────
# Start immediately so Railway's health check responds quickly.
echo "[start.sh] Starting Next.js frontend (port ${PORT:-3000})..."
cd /frontend
HOSTNAME=0.0.0.0 \
  PORT="${PORT:-3000}" \
  BACKEND_INTERNAL_URL="http://127.0.0.1:8000" \
  node server.js 2>&1 &

FRONTEND_PID=$!
echo "[start.sh] Frontend PID: $FRONTEND_PID"

echo "[start.sh] Both processes launched."
echo "[start.sh]   Frontend: http://0.0.0.0:${PORT:-3000}"
echo "[start.sh]   Backend:  http://127.0.0.1:8000 (internal)"

# ── Keep container alive; exit if either process dies ──────────────────
wait $BACKEND_PID $FRONTEND_PID
EXIT_CODE=$?
echo "[start.sh] A process exited with code $EXIT_CODE"
exit $EXIT_CODE
