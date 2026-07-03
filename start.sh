#!/bin/sh
# start.sh — launch FastAPI backend + Next.js frontend in a single container
# NOTE: This file must have LF (Unix) line endings. Do NOT convert to CRLF.

echo "====================================================="
echo " OCR System startup — $(date)"
echo "====================================================="
echo "PORT=${PORT:-3000}"
echo "DATABASE_URL length: ${#DATABASE_URL}"

# ── Python environment diagnostics ────────────────────────────────────
echo ""
echo "--- Python diagnostics ---"
/venv/bin/python3 --version 2>&1
ls /api/src/main.py 2>/dev/null && echo "src/main.py: OK" || echo "src/main.py: NOT FOUND"

/venv/bin/python3 -c "
import sys
sys.path.insert(0, '/api')
errors = []
packages = ['fastapi', 'uvicorn', 'sqlalchemy', 'asyncpg', 'aiosqlite',
            'cv2', 'PIL', 'pydantic_settings']
for pkg in packages:
    try:
        m = __import__(pkg)
        ver = getattr(m, '__version__', '?')
        print(f'  {pkg}: OK ({ver})')
    except ImportError as e:
        print(f'  {pkg}: FAILED — {e}')
        errors.append(pkg)

print('Importing src.config...')
try:
    import src.config as cfg
    print(f'  settings.is_sqlite={cfg.settings.is_sqlite}')
    print(f'  db_url_scheme={cfg.settings.database_url_normalized.split(\"//\")[0]}')
except Exception as e:
    print(f'  src.config FAILED: {e}')
    import traceback; traceback.print_exc()

print('Importing src.main...')
try:
    import src.main
    print('  src.main: OK')
except Exception as e:
    print(f'  src.main FAILED: {e}')
    import traceback; traceback.print_exc()
" 2>&1

echo ""
echo "--- Starting services ---"

# ── FastAPI backend (127.0.0.1:8000 internal) ─────────────────────────
if [ ! -d /api ]; then
  echo "ERROR: /api directory not found — aborting"
  exit 1
fi
cd /api || { echo "ERROR: cd /api failed"; exit 1; }

echo "Starting uvicorn on 127.0.0.1:8000..."
/venv/bin/uvicorn src.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --log-level info \
  2>&1 &
BACKEND_PID=$!
echo "Backend PID: $BACKEND_PID"

# Brief pause then check if uvicorn is still running
sleep 3
if kill -0 $BACKEND_PID 2>/dev/null; then
  echo "Backend process alive after 3s ✓"
else
  echo "WARNING: Backend process already exited after 3s!"
fi

# ── Next.js frontend (public Railway PORT) ─────────────────────────────
echo "Starting Next.js on port ${PORT:-3000}..."
cd /frontend || { echo "ERROR: cd /frontend failed"; exit 1; }
HOSTNAME=0.0.0.0 \
  PORT="${PORT:-3000}" \
  BACKEND_INTERNAL_URL="http://127.0.0.1:8000" \
  node server.js 2>&1 &
FRONTEND_PID=$!
echo "Frontend PID: $FRONTEND_PID"

echo "Both processes launched."
echo "  Frontend: http://0.0.0.0:${PORT:-3000}"
echo "  Backend:  http://127.0.0.1:8000"

# ── Keep container alive ───────────────────────────────────────────────
wait $BACKEND_PID $FRONTEND_PID
EXIT_CODE=$?
echo "A process exited with code $EXIT_CODE — container stopping."
exit $EXIT_CODE
