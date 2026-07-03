#!/bin/sh
set -e

echo "[start.sh] Starting OCR System..."

# Start FastAPI backend on internal port 8000
echo "[start.sh] Starting FastAPI backend on 127.0.0.1:8000..."
cd /api
python3 -m uvicorn src.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --workers "${WORKERS:-1}" &

BACKEND_PID=$!
echo "[start.sh] Backend PID: $BACKEND_PID"

# Wait for backend to be ready
echo "[start.sh] Waiting for backend to start..."
for i in $(seq 1 30); do
  if curl -sf http://127.0.0.1:8000/health > /dev/null 2>&1; then
    echo "[start.sh] Backend is ready."
    break
  fi
  sleep 1
done

# Start Next.js frontend on Railway's PORT
echo "[start.sh] Starting Next.js frontend on port ${PORT:-3000}..."
cd /frontend
HOSTNAME=0.0.0.0 PORT="${PORT:-3000}" BACKEND_INTERNAL_URL="http://127.0.0.1:8000" node server.js &

FRONTEND_PID=$!
echo "[start.sh] Frontend PID: $FRONTEND_PID"

echo "[start.sh] Both services started."
echo "[start.sh]   Frontend: http://0.0.0.0:${PORT:-3000}"
echo "[start.sh]   Backend:  http://127.0.0.1:8000 (internal)"

# Keep container alive; exit if either process dies
wait $FRONTEND_PID $BACKEND_PID
