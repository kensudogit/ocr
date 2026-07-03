FROM python:3.11-slim

# ── システム依存パッケージ ─────────────────────────────────────────
# OpenCV / pdf2image / Pillow に必要なシステムライブラリをインストール
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OpenCV
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxrender1 \
    libxext6 \
    # pdf2image (Poppler)
    poppler-utils \
    # 画像処理
    libzbar0 \
    # curl (ヘルスチェック用)
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python 依存パッケージ ─────────────────────────────────────────
COPY requirements.txt .
# PaddleOCR はモデルが大きいため先にインストール
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ── アプリケーションコード ────────────────────────────────────────
COPY . .

# ── アップロード・エクスポートディレクトリ ──────────────────────────
RUN mkdir -p uploads exports

# ── PaddleOCR 日本語モデルを事前にダウンロード ───────────────────
# ビルド時にダウンロードすることで起動を高速化
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='japan', show_log=False)" || true

EXPOSE 8000

# ── 起動コマンド ──────────────────────────────────────────────────
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
