FROM python:3.11-slim

# System dependencies for OpenCV / pdf2image / Pillow / zbar
# build-essential required for C-extension packages (neologdn, mojimoji)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
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

WORKDIR /app

# Copy from backend/ subdirectory (Railway build context = repo root)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY backend/ .

RUN mkdir -p uploads exports originals test-reports

# Skip PaddleOCR model pre-download to avoid Railway build timeout
# Models will be downloaded on first use
# RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='japan', show_log=False)" || true

EXPOSE 8000

# Railway injects PORT at runtime; shell form expands env vars
CMD sh -c "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WORKERS:-1}"
