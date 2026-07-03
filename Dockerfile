# ============================================================
# Combined Railway Dockerfile: Next.js (frontend) + FastAPI (backend)
# - Next.js listens on Railway $PORT (public)
# - FastAPI listens on 127.0.0.1:8000 (internal only)
# - Next.js /api/* rewrites proxy to FastAPI
# ============================================================

# ── Stage 1: Build Next.js frontend ──────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ .

ENV NEXT_TELEMETRY_DISABLED=1
# /api prefix: Next.js rewrites proxy /api/* to FastAPI internally
ENV NEXT_PUBLIC_API_URL=/api

RUN npm run build

# ── Stage 2: Runtime (Node.js base + Python) ─────────────────────────
FROM node:20-slim

# Install Python 3 + system libraries for OpenCV / PaddleOCR / etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    libgomp1 \
    poppler-utils \
    libzbar0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Python backend ────────────────────────────────────────────────────
WORKDIR /api

COPY backend/requirements.txt .

# PEP 668: node:20-slim (Debian Bookworm) blocks global pip install.
# Use a virtualenv instead of --break-system-packages.
RUN python3 -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --upgrade pip && \
    /venv/bin/pip install --no-cache-dir -r requirements.txt

COPY backend/ .

RUN mkdir -p uploads exports originals test-reports

# Always use the venv python/uvicorn
ENV PATH="/venv/bin:$PATH"

# ── Next.js frontend (standalone) ────────────────────────────────────
WORKDIR /frontend

COPY --from=frontend-builder /frontend/.next/standalone ./
COPY --from=frontend-builder /frontend/.next/static ./.next/static
COPY --from=frontend-builder /frontend/public ./public

# ── Startup script ────────────────────────────────────────────────────
WORKDIR /

COPY start.sh /start.sh
RUN chmod +x /start.sh

# Railway injects PORT; Next.js uses it for the public listener
EXPOSE 3000

CMD ["/start.sh"]
