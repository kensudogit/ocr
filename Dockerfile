# ============================================================
# PoC Dockerfile: Next.js (frontend) + FastAPI (backend)
# OpenCV headless + Azure DI + OpenAI 後処理パイプライン対応
# ============================================================

# ── Stage 1: Build Next.js frontend ──────────────────────────────────
FROM node:20-alpine AS frontend-builder

WORKDIR /frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ .

ENV NEXT_TELEMETRY_DISABLED=1
# /api/* proxied by app/api/[...path]/route.ts → FastAPI on 127.0.0.1:8000
ENV NEXT_PUBLIC_API_URL=/api
RUN npm run build

# ── Stage 2: Runtime ─────────────────────────────────────────────────
FROM node:20-slim

# OpenCV headless 用システムライブラリ + Python ランタイム
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-venv \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# ── Python backend ────────────────────────────────────────────────────
WORKDIR /api

COPY backend/requirements-poc.txt ./

RUN python3 -m venv /venv && \
    /venv/bin/pip install --no-cache-dir --upgrade pip && \
    /venv/bin/pip install --no-cache-dir -r requirements-poc.txt

COPY backend/ .

RUN mkdir -p uploads exports originals test-reports

ENV PATH="/venv/bin:$PATH"

# ── Next.js frontend (standalone) ────────────────────────────────────
WORKDIR /frontend

COPY --from=frontend-builder /frontend/.next/standalone ./
COPY --from=frontend-builder /frontend/.next/static ./.next/static
COPY --from=frontend-builder /frontend/public ./public

# ── Startup script ────────────────────────────────────────────────────
WORKDIR /

COPY start.sh /start.sh
RUN sed -i 's/\r//' /start.sh && chmod +x /start.sh

EXPOSE 3000

CMD ["/start.sh"]
