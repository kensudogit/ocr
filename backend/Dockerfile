FROM python:3.11-slim

# System dependencies + build tools for C-extension Python packages
# (neologdn, mojimoji, etc. require gcc/g++ to compile)
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

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p uploads exports originals test-reports

# Pre-download PaddleOCR Japanese model to speed up first run
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='japan', show_log=False)" || true

EXPOSE ${PORT:-8000}

# Use shell form so $PORT env var is expanded at runtime (required for Railway)
CMD sh -c "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers ${WORKERS:-2}"
