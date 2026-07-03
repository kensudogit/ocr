FROM python:3.11-slim

# System dependencies for OpenCV / pdf2image / Pillow / zbar
RUN apt-get update && apt-get install -y --no-install-recommends \
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

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
